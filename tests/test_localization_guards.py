"""Guards that keep Korean source text and English translations in step."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMenu

from scripts import localization_guard as guard
from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT, source_catalog
from watched_kettle.localization.packs import load_pack


def has_hangul(text):
    return bool(guard.HANGUL.search(text or ""))


class LiteralGuardTests(unittest.TestCase):
    def test_repository_passes_every_guard(self):
        self.assertEqual(guard.check(), [])

    def test_control_characters_other_than_newline_fail(self):
        pack = {"messages": {"a": {"value": "줄\n바꿈", "context": "x\x07pplication"}}}

        self.assertEqual(
            guard.control_problems("catalog.json", pack),
            ["catalog.json: messages.a.context has control characters U+0007"],
        )

    def test_python_scan_ignores_comments_and_docstrings(self):
        source = '"""문서."""\n# 주석\ndef f():\n    """설명."""\n    return "보임", f"{1} 값"\n'
        self.assertEqual(guard.python_literals(source), [5, 5])

    def test_qml_scan_ignores_comments_and_keeps_line_numbers(self):
        source = '// "주석"\n/* "여러\n줄" */\nText { text: "보임" }\n'
        self.assertEqual(guard.qml_literals(source), [4])

    def test_new_literal_fails_and_shrinking_requires_updating_the_count(self):
        allow = {"a.py": {"count": 1, "reason": "frozen"}}
        self.assertEqual(guard.literal_problems({"a.py": [3]}, allow), [])
        self.assertIn(
            "2 Korean literal", guard.literal_problems({"a.py": [3, 4]}, allow)[0]
        )
        self.assertIn("Lower the count", guard.literal_problems({}, allow)[0])
        self.assertIn(
            "needs a reason",
            guard.literal_problems({"a.py": [3]}, {"a.py": {"count": 1}})[0],
        )


class MessageKeyTests(unittest.TestCase):
    def test_every_reference_form_is_found_with_its_location(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "watched_kettle").mkdir()
            (root / "watched_kettle/a.py").write_text(
                'x = t("pet.title")\ny = MessageId("message.0001")\n'
                'z = t("status." + state)\n',
                encoding="utf-8",
            )
            (root / "settings-ui/src").mkdir(parents=True)
            (root / "settings-ui/src/b.tsx").write_text(
                'parts("usage.total", {})\n<LocalizedText\n  id="usage.help"\n'
                '<LocalizedText id={"usage.more"} />\n',
                encoding="utf-8",
            )
            found = guard.scan_keys(root)
        self.assertEqual(
            found,
            {
                "pet.title": ["watched_kettle/a.py:1"],
                "message.0001": ["watched_kettle/a.py:2"],
                "usage.total": ["settings-ui/src/b.tsx:1"],
                "usage.help": ["settings-ui/src/b.tsx:2"],
                "usage.more": ["settings-ui/src/b.tsx:4"],
            },
        )

    def test_unknown_key_is_reported_with_where_it_is_used(self):
        (problem,) = guard.key_problems(
            {"pet.title": ["a.py:1"], "pet.titel": ["b.tsx:9"]}, {"pet.title": {}}
        )
        self.assertIn("pet.titel", problem)
        self.assertIn("b.tsx:9", problem)


class SourceLockTests(unittest.TestCase):
    def setUp(self):
        self.messages = {
            "a": {"value": "원문", "revision": 1, "variables": {}, "context": "x"},
            "b": {"value": "{n}개", "revision": 2, "variables": {"n": "string"}},
        }
        self.lock = guard.updated_lock(self.messages, {})

    def test_locked_catalog_passes_and_context_is_not_part_of_the_meaning(self):
        self.messages["a"]["context"] = "new note"
        self.assertEqual(guard.lock_problems(self.messages, self.lock), [])

    def test_source_change_without_revision_bump_fails(self):
        self.messages["a"]["value"] = "바뀐 원문"
        (problem,) = guard.lock_problems(self.messages, self.lock)
        self.assertIn("without a revision bump", problem)
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            guard.updated_lock(self.messages, self.lock)
        relocked = guard.updated_lock(self.messages, self.lock, wording_only=["a"])
        self.assertEqual(guard.lock_problems(self.messages, relocked), [])

    def test_wording_only_rejects_keys_that_did_not_reword(self):
        with self.assertRaisesRegex(ValueError, "not a same-revision"):
            guard.updated_lock(self.messages, self.lock, wording_only=["b"])

    def test_bump_add_and_remove_need_a_relock_but_a_lower_revision_is_refused(self):
        self.messages["a"].update(value="새 뜻", revision=2)
        self.messages["c"] = {"value": "추가", "revision": 1, "variables": {}}
        del self.messages["b"]
        (problem,) = guard.lock_problems(self.messages, self.lock)
        self.assertIn("c, b, a", problem)  # added, removed, then bumped
        self.assertEqual(
            guard.lock_problems(
                self.messages, guard.updated_lock(self.messages, self.lock)
            ),
            [],
        )
        self.messages["a"]["revision"] = 0
        self.assertIn("backwards", guard.lock_problems(self.messages, self.lock)[0])
        with self.assertRaises(ValueError):
            guard.updated_lock(self.messages, self.lock)

    def test_variable_or_plural_changes_count_as_source_changes(self):
        self.messages["b"]["variables"] = {"count": "number"}
        self.assertTrue(guard.lock_problems(self.messages, self.lock))

    def test_lock_covers_the_real_catalog(self):
        lock = guard._read(guard.LOCK_PATH)
        self.assertEqual(set(lock), set(source_catalog()["messages"]))


class EnglishSurfaceTests(unittest.TestCase):
    """Real tray menus and project labels built while English is active."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())

    def flush(self):
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def menu_texts(self, menu):
        menu.aboutToShow.emit()
        texts = [menu.title()]
        for action in menu.actions():
            texts.append(action.text())
            texts.append(action.toolTip())
            if action.menu() is not None:
                texts.extend(self.menu_texts(action.menu()))
        for child in menu.findChildren(QMenu):
            texts.append(child.title())
        return texts

    def test_tray_menu_and_project_labels_have_no_korean(self):
        from watched_kettle.features.project_activity.service import (
            ProjectActivityService,
        )
        from watched_kettle.ui.assistant_tray import AssistantSystemTray

        clock = N(value=100.0)
        projects = ProjectActivityService(now=lambda: clock.value)
        # Untitled conversations in both agents and every visible row state.
        for source in ("codex", "claude_code"):
            for thread, event, extra in (
                ("run", "prompt", {}),
                ("wait", "waiting", {"event_id": "request"}),
                ("done", "done", {}),
                ("fail", "failed", {"outcome_reason": "usage_limit"}),
            ):
                if event != "prompt":
                    projects.observe(
                        dict(
                            source=source,
                            session_id=source + thread,
                            event="prompt",
                            turn_id="1",
                        )
                    )
                projects.observe(
                    dict(
                        source=source,
                        session_id=source + thread,
                        event=event,
                        turn_id="1",
                        **extra,
                    )
                )
        self.assertTrue(projects.cards)
        labels = [
            text
            for card in projects.cards
            for text in (card.label, card.summary, *(r.title for r in card.rows))
        ]
        router = N(
            label=lambda _kind, _identifier="": "Open",
            register=lambda kind, value: (kind, value),
            open=lambda _: None,
        )
        tray = AssistantSystemTray(
            N(
                refresh=lambda: N(visual_state="working", active_count=2, visible=True),
                snooze_bubbles=lambda _: None,
                resume_bubbles=lambda: None,
                toggle_visibility=lambda: None,
            ),
            N(
                enabled=True,
                snapshot=N(account_hash="one"),
                tray_summary=lambda: "80%",
            ),
            N(
                projects=projects,
                router=router,
                snapshot=N(recent=(), last_message=""),
            ),
            lambda _: None,
            QPixmap(16, 16),
        )
        self.addCleanup(self.flush)
        self.addCleanup(tray.close)
        tray.refresh()
        texts = labels + self.menu_texts(tray.menu) + [tray.tray.toolTip()]
        self.assertGreater(len([text for text in texts if text]), 10)
        self.assertEqual([text for text in texts if has_hangul(text)], [])


if __name__ == "__main__":
    unittest.main()
