"""Duration preferences and deadlines must remain independent of delivery state."""

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from pathlib import Path

from PySide6.QtCore import QSettings

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.bubble_timing import BubbleDurationPolicy, DURATION_KINDS
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.project_activity.service import ProjectActivityService


class BubbleTimingTests(unittest.TestCase):
    def test_old_setting_and_overrides_survive_real_settings_reload(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "preferences.ini")
            settings = QSettings(path, QSettings.Format.IniFormat)
            settings.setValue("bubbleDurationSeconds", 12)
            prefs = ApplicationPreferences(settings)
            policy = prefs.load_bubble_duration_policy()
            self.assertEqual(
                [policy.seconds(k) for k in DURATION_KINDS], [12, 12, 12, 15]
            )
            policy = policy.with_override("schedule", 30).with_override("result", 60)
            prefs.save_bubble_duration_policy(policy)
            settings.sync()
            reloaded = ApplicationPreferences(
                QSettings(path, QSettings.Format.IniFormat)
            )
            self.assertEqual(reloaded.load_bubble_duration_policy(), policy)
            reloaded.save_bubble_duration_policy(policy.with_override("schedule", None))
            self.assertEqual(
                reloaded.load_bubble_duration_policy().seconds("schedule"), 12
            )
            reloaded.save_bubble_duration_policy(BubbleDurationPolicy())
            self.assertEqual(
                reloaded.load_bubble_duration_policy(), BubbleDurationPolicy()
            )
            self.assertFalse(settings.contains("bubbleDurationOverrides/result"))

    def test_common_changes_keep_override_and_values_are_bounded(self):
        policy = BubbleDurationPolicy(common=10).with_override("schedule", 30)
        policy = replace(policy, common=20)
        self.assertEqual([policy.seconds(k) for k in DURATION_KINDS], [20, 20, 30, 15])
        self.assertEqual(policy.with_override("general", 0).seconds("general"), 5)
        self.assertEqual(policy.with_override("general", 99).seconds("general"), 60)

    def test_shown_deadline_is_frozen_and_queued_notice_uses_latest_policy(self):
        now = [100.0]
        service = NotificationService()
        service.managed_delivery = True
        service.now = lambda: now[0]
        for message in ("first", "queued"):
            service.submit(NoticeRequest("system", message))
        first = service.candidates()[0]
        service.shown(first.record_id)
        service.duration_policy = BubbleDurationPolicy(common=20, schedule=30)
        service.submit(NoticeRequest("schedule", "meeting", category="schedule"))
        alarm = service.candidates()[1]
        service.shown(alarm.record_id)
        now[0] += 8
        selected = service.candidates()
        self.assertEqual([r.message for r in selected], ["queued", "meeting"])
        service.shown(selected[0].record_id)
        service.duration_policy = BubbleDurationPolicy(common=5)
        now[0] += 19
        self.assertEqual(len(service.candidates()), 2)
        now[0] += 1
        self.assertEqual([r.message for r in service.candidates()], ["meeting"])
        now[0] += 2
        self.assertEqual(service.candidates(), ())
        self.assertTrue(all(not r.confirmed for r in service.snapshot.recent))

    def test_result_deadline_is_frozen_waiting_persists_and_running_goes_stale(self):
        now = [100.0]
        projects = ProjectActivityService(now=lambda: now[0])

        def event(thread, name):
            projects.observe(
                dict(source="codex", session_id=thread, turn_id="1", event=name)
            )

        for thread in ("done", "later", "running", "waiting"):
            event(thread, "prompt")
        event("waiting", "waiting")
        event("done", "done")
        projects.duration = BubbleDurationPolicy(common=20).seconds("result")
        event("later", "done")
        now[0] += 8
        projects.expire()
        self.assertNotIn("done", projects.activities)
        self.assertIn("later", projects.activities)
        now[0] += 1000
        projects.expire()
        self.assertEqual(set(projects.activities), {"waiting", "running"})
        self.assertTrue(projects.activities["running"].uncertain)
