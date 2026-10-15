"""BA-01/BA-09 static dependency boundaries; behavior lives in regression tests."""

import ast
from importlib.util import resolve_name
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_DEPENDENCIES = (
    "watched_kettle.ui",
    "watched_kettle.pet",
    "watched_kettle.application",
    "PySide6.QtWidgets",
    "PySide6.QtGui",
)
BOUNDARIES = {
    "watched_kettle.pet.importer": (
        "watched_kettle.application",
        "watched_kettle.ui",
        "watched_kettle.features",
        "watched_kettle.integrations",
        "watched_kettle.state",
        "watched_kettle.storage",
        "watched_kettle.usage",
    ),
    "watched_kettle.activity_diagnostics": (
        *UI_DEPENDENCIES,
        "watched_kettle.features",
        "watched_kettle.integrations",
        "watched_kettle.state",
        "watched_kettle.storage",
    ),
    "watched_kettle.features.project_activity.service": UI_DEPENDENCIES,
    "watched_kettle.features.project_activity.metadata": UI_DEPENDENCIES,
    "watched_kettle.usage.conversation_catalog": UI_DEPENDENCIES,
    "watched_kettle.usage.project_history": UI_DEPENDENCIES,
    "watched_kettle.features.notifications.service": UI_DEPENDENCIES,
    **dict.fromkeys(
        (
            "watched_kettle.integrations.activity_recovery",
            "watched_kettle.integrations.codex_log",
            "watched_kettle.integrations.codex_log_worker",
            "watched_kettle.integrations.log_lifecycle",
            "watched_kettle.integrations.codex_hooks",
            "watched_kettle.integrations.claude_code_launcher",
            "watched_kettle.state.events",
        ),
        (*UI_DEPENDENCIES, "watched_kettle.features"),
    ),
    **dict.fromkeys(
        (
            "watched_kettle.ui.actionable_bubbles",
            "watched_kettle.ui.project_bubble_rows",
            "watched_kettle.ui.wrapped_title_button",
        ),
        (
            "watched_kettle.integrations",
            "watched_kettle.storage",
            "watched_kettle.state",
        ),
    ),
}


def violations(source, module, forbidden):
    """Resolve ordinary and relative imports, including from-package imports."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, module.rpartition(".")[0])
            imports = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            if any(alias.name == "*" for alias in node.names):
                found.append(
                    f"{module}:{node.lineno}: wildcard import hides dependencies"
                )
        else:
            continue
        for imported in imports:
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in forbidden
            ):
                found.append(f"{module}:{node.lineno}: forbidden dependency {imported}")
    return found


class BubbleArchitectureTests(unittest.TestCase):
    def test_core_dependencies_follow_documented_boundaries(self):
        for module, forbidden in BOUNDARIES.items():
            with self.subTest(module=module):
                source = (ROOT / (module.replace(".", "/") + ".py")).read_text(
                    encoding="utf-8"
                )
                self.assertEqual(violations(source, module, forbidden), [])

    def test_services_cannot_hide_widget_imports_behind_aliases(self):
        for source in (
            "import PySide6.QtWidgets as widgets",
            "from PySide6 import QtWidgets",
            "def build():\n    from PySide6.QtWidgets import QWidget as View",
        ):
            with self.subTest(source=source):
                self.assertTrue(
                    violations(
                        source,
                        "watched_kettle.features.project_activity.service",
                        UI_DEPENDENCIES,
                    )
                )

    def test_relative_imports_cannot_bypass_the_boundary(self):
        self.assertTrue(
            violations(
                "from ...ui import actionable_bubbles",
                "watched_kettle.features.project_activity.service",
                UI_DEPENDENCIES,
            )
        )
        self.assertTrue(
            violations(
                "from .. import ui",
                "watched_kettle.integrations.activity_recovery",
                UI_DEPENDENCIES,
            )
        )

    def test_value_contracts_and_qt_signals_remain_allowed(self):
        self.assertEqual(
            violations(
                "from PySide6.QtCore import QObject, Signal",
                "watched_kettle.features.project_activity.service",
                UI_DEPENDENCIES,
            ),
            [],
        )
        module = "watched_kettle.ui.project_bubble_rows"
        self.assertEqual(
            violations(
                "from watched_kettle.features.project_activity.service import LABELS",
                module,
                BOUNDARIES[module],
            ),
            [],
        )

    def test_wildcard_imports_cannot_hide_dependencies(self):
        self.assertTrue(
            violations(
                "from PySide6 import *",
                "watched_kettle.features.project_activity.service",
                UI_DEPENDENCIES,
            )
        )
