"""Wire contracts, generated clients and least-privilege command exposure."""

import ast
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import types
from typing import (
    Literal,
    ForwardRef,
    NotRequired,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)
import unittest

from scripts.generate_settings_protocol import outputs, ts_type
from watched_kettle import settings_protocol as protocol
from watched_kettle.application.settings_ui.contracts import wire


def matches(value, annotation):
    """Check the small DTO subset against real wire values, only in tests."""
    if isinstance(annotation, str):
        return matches(value, getattr(protocol, annotation))
    if isinstance(annotation, ForwardRef):
        return matches(value, getattr(protocol, annotation.__forward_arg__))
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is NotRequired:
        return matches(value, args[0])
    if origin in (Union, types.UnionType):
        return any(matches(value, option) for option in args)
    if origin is Literal:
        return any(type(value) is type(option) and value == option for option in args)
    if is_typeddict(annotation):
        if not isinstance(value, dict):
            return False
        hints = get_type_hints(annotation, include_extras=True)
        required = annotation.__required_keys__ - {
            key for key, hint in hints.items() if get_origin(hint) is NotRequired
        }
        return required <= value.keys() and all(
            matches(value[key], hint) for key, hint in hints.items() if key in value
        )
    if origin in (list, tuple):
        if not isinstance(value, list):
            return False
        if origin is list:
            return all(matches(item, args[0]) for item in value)
        return len(value) == len(args) and all(
            matches(v, t) for v, t in zip(value, args)
        )
    if origin is dict:
        return isinstance(value, dict) and all(
            matches(k, args[0]) and matches(v, args[1]) for k, v in value.items()
        )
    if annotation is object:
        return True
    if annotation is float:
        return type(value) in (int, float)
    if annotation is type(None):
        return value is None
    return type(value) is annotation


class SettingsProtocolTests(unittest.TestCase):
    def test_generated_clients_are_current(self):
        for path, expected in outputs().items():
            with self.subTest(path=path.name):
                self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_native_commands_never_enter_renderer_allowlist(self):
        path = Path("settings-ui/electron/commands.generated.cjs")
        exposed = json.loads(
            path.read_text().split("module.exports = ", 1)[1].rstrip(";\n")
        )
        forbidden = {
            "file.import",
            "file.pet.prepare",
            "file.pet.cancel",
            "file.export",
            "window.visibility",
            "window.state",
            "window.restore",
        }
        self.assertTrue(forbidden.isdisjoint(exposed["renderer"]))
        self.assertIn("navigation.ack", exposed["renderer"])
        self.assertTrue(set(exposed["assistant"]) <= set(exposed["renderer"]))
        for command in protocol.COMMANDS.values():
            self.assertIn(command.request, vars(protocol))
            self.assertIn(command.response, vars(protocol))

    def test_unknown_generator_types_fail_instead_of_becoming_any(self):
        with self.assertRaises(ValueError):
            ts_type(ast.parse("Callable[[str], int]", mode="eval").body)

    def test_core_adapter_returns_declared_contracts(self):
        from tests.test_settings_bridge import SettingsBridgeTests

        SettingsBridgeTests.setUpClass()
        fixture = SettingsBridgeTests()
        fixture.setUp()
        try:
            for method, args in (
                ("settings.snapshot", {}),
                ("pet.catalog", {}),
                ("pet.preview", {"petId": fixture.vm.snapshot.pet_id}),
                ("pet.trash.list", {}),
                ("bubble.editor", {}),
                ("pet.trash.batch.status", fixture.context()),
            ):
                with self.subTest(method=method):
                    result = fixture.core.execute(method, args)
                    self.assert_contract(result, protocol.COMMANDS[method].response)
            core = fixture.assistant()
            for method in (
                "usage.snapshot",
                "activity.snapshot",
                "integration.snapshot",
            ):
                with self.subTest(method=method):
                    self.assert_contract(
                        core.execute(method, {}), protocol.COMMANDS[method].response
                    )
        finally:
            fixture.tearDown()
            fixture.doCleanups()

    def assert_contract(self, value, name):
        annotation = getattr(protocol, name)
        value = wire(value)
        # Report the field as well as the response, so a changed contract is actionable.
        hints = get_type_hints(annotation, include_extras=True)
        for key, hint in hints.items():
            if key in value:
                self.assertTrue(
                    matches(value[key], hint), f"{name}.{key}: {value[key]!r}"
                )
        self.assertTrue(matches(value, annotation), name)

    def test_wire_models_keep_domain_field_names(self):
        from watched_kettle.usage import models
        from watched_kettle.pet.bubble_theme import SpeechBubbleTheme

        for model in (
            models.UsageSnapshot,
            models.TaskUsageRecord,
            models.RateLimitBucket,
            SpeechBubbleTheme,
        ):
            self.assertTrue(is_dataclass(model))
            self.assertEqual(
                set(get_type_hints(getattr(protocol, model.__name__))),
                {field.name for field in fields(model)} - {"unknown"},
            )

    def test_populated_usage_records_match_both_providers(self):
        from watched_kettle.usage import models
        from watched_kettle.usage.claude_code_service import ClaudeCodeUsageSnapshot
        from watched_kettle.usage.conversation_models import (
            ConversationUsage,
            ProjectUsageSummary,
        )

        now = datetime.now(timezone.utc)
        task = models.TaskUsageRecord(now, "account", "thread", "done", total_tokens=9)
        conversation = ConversationUsage(
            "thread", "Title", "project", "Project", now, 1, 1, 0, 0, 9
        )
        project = ProjectUsageSummary("project", "Project", 1, 1, now)
        bucket = models.RateLimitBucket(
            "codex", primary=models.UsageWindow(20, 80, 300, now)
        )
        # Dates and nested numeric arrays exercise the real wire transformation,
        # not just empty collections from initial snapshots.
        common = dict(
            projects=(project,),
            conversations=(conversation,),
            recent_tasks=(task,),
            latest_tasks=(task,),
            buckets=(bucket,),
            trend_hours={
                "date": date.today(),
                "hours": [None, 9],
                "average": [1.5, None],
            },
            trend_quota={"five_hour": {"points": [(now, 80.0)], "observed": 1}},
        )
        codex = models.UsageSnapshot(**common, selected_conversation=conversation)
        claude = ClaudeCodeUsageSnapshot(**common, daily_tokens=((date.today(), 9),))
        self.assert_contract(codex, "UsageSnapshot")
        self.assert_contract(claude, "ClaudeCodeUsageSnapshot")
        broken = wire(codex)
        broken["recent_tasks"][0]["total_tokens"] = "nine"
        self.assertFalse(matches(broken, protocol.UsageSnapshot))
