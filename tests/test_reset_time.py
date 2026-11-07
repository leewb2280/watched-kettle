"""Reset wording for usage limits: time left or the local 12-hour clock time."""

from datetime import datetime, timedelta, timezone
import unittest

from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT
from watched_kettle.localization.packs import load_pack
from watched_kettle.usage.claude_code_limits import QuotaSample, threshold_notices
from watched_kettle.usage.reset_time import (
    clock_text,
    notice_reset_text,
    widget_reset_text,
)

KST = timezone(timedelta(hours=9))
# Saturday 2026-10-03 21:00 KST.
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def at(hour, minute=0, day=3):
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


class ResetTimeTests(unittest.TestCase):
    def test_remaining_keeps_the_time_left_wording(self):
        self.assertEqual(
            widget_reset_text(NOW + timedelta(days=1, hours=2), NOW),
            "1일 2시간 뒤 갱신",
        )
        self.assertEqual(
            widget_reset_text(NOW + timedelta(hours=4, minutes=12), NOW),
            "4시간 12분 뒤 갱신",
        )
        self.assertEqual(
            widget_reset_text(NOW + timedelta(minutes=5), NOW), "5분 뒤 갱신"
        )
        self.assertEqual(widget_reset_text(None, NOW, "clock", KST), "")

    def test_clock_uses_twelve_hours_with_noon_and_midnight(self):
        self.assertEqual(clock_text(at(12, 39)), "오후 12:39")
        self.assertEqual(clock_text(at(0, 5)), "오전 12:05")
        self.assertEqual(clock_text(at(9, 0)), "오전 9:00")
        self.assertEqual(clock_text(at(23, 59)), "오후 11:59")

    def test_clock_shows_the_date_only_when_the_reset_is_not_today(self):
        self.assertEqual(
            widget_reset_text(at(23, 0), NOW, "clock", KST), "오후 11:00 갱신"
        )
        # Past midnight in local time is another day even within the 5 hours.
        self.assertEqual(
            widget_reset_text(at(0, 30, day=4), NOW, "clock", KST),
            "10/4(일) 오전 12:30 갱신",
        )
        self.assertEqual(
            widget_reset_text(at(12, 39, day=8), NOW, "clock", KST),
            "10/8(목) 오후 12:39 갱신",
        )

    def test_unknown_display_falls_back_to_time_left(self):
        self.assertEqual(
            widget_reset_text(NOW + timedelta(minutes=5), NOW, "other", KST),
            "5분 뒤 갱신",
        )

    def test_notice_suffix_follows_the_display(self):
        resets = NOW + timedelta(hours=3, minutes=20)
        self.assertEqual(notice_reset_text(resets, NOW), " · 3시간 20분 후 초기화")
        self.assertEqual(
            notice_reset_text(NOW + timedelta(minutes=7), NOW), " · 7분 후 초기화"
        )
        self.assertEqual(
            notice_reset_text(at(23, 0), NOW, "clock", KST), " · 오후 11:00 초기화"
        )
        self.assertEqual(
            notice_reset_text(at(1, 0, day=4), NOW, "clock", KST),
            " · 10/4(일) 오전 1:00 초기화",
        )
        self.assertEqual(notice_reset_text(None, NOW, "clock", KST), "")

    def test_claude_code_threshold_notice_uses_the_chosen_display(self):
        resets = NOW + timedelta(hours=2)
        before = QuotaSample("five_hour", NOW, 60.0, resets)
        after = QuotaSample("five_hour", NOW, 75.0, resets)
        remaining = threshold_notices(before, after, now=NOW)
        clock = threshold_notices(before, after, now=NOW, reset_display="clock")
        self.assertTrue(remaining[0].message.endswith(" · 2시간 0분 후 초기화"))
        local = resets.astimezone()
        self.assertIn(clock_text(local), clock[0].message)
        self.assertNotIn("후 초기화", clock[0].message)

    def test_codex_notice_uses_the_system_zone_not_the_start_offset(self):
        from types import SimpleNamespace

        from watched_kettle.usage.models import RateLimitBucket, UsageWindow
        from watched_kettle.usage.notice_policy import UsageNoticePolicy

        notices = []
        resets = NOW + timedelta(hours=2)
        # A fixed offset taken at start would be an hour off after a DST change.
        stale_offset = timezone(timedelta(hours=-4))
        policy = UsageNoticePolicy(
            None,
            lambda: NOW,
            stale_offset,
            lambda text, *_args: notices.append(text),
            lambda _error: None,
        )
        policy.reset_display = "clock"
        snapshot = SimpleNamespace(account_hash="")
        bucket = RateLimitBucket("codex", primary=UsageWindow(75, 25, 300, resets))
        policy.check_thresholds(snapshot, [bucket])
        self.assertEqual(len(notices), 1)
        self.assertTrue(
            notices[0].endswith(clock_text(resets.astimezone()) + " 초기화")
        )

    def test_english_wording(self):
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.assertEqual(
            widget_reset_text(at(12, 39), NOW, "clock", KST), "Resets 12:39 PM"
        )
        self.assertEqual(
            widget_reset_text(at(0, 30, day=4), NOW, "clock", KST),
            "Resets Sun 10/4 12:30 AM",
        )
        self.assertEqual(
            notice_reset_text(at(23, 0), NOW, "clock", KST), " · Resets 11:00 PM"
        )


if __name__ == "__main__":
    unittest.main()
