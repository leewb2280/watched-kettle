"""Opening Claude Code returns to VS Code as it is; it never makes a new chat."""

from pathlib import Path
import inspect
import sys
import unittest
from unittest.mock import Mock, patch

from watched_kettle.integrations import vscode_launcher
from watched_kettle.integrations.vscode_launcher import (
    WindowsVSCodeLauncher,
    open_vscode,
)
from watched_kettle.integrations.windows_apps import AppInstallation


class VSCodeLauncherTests(unittest.TestCase):
    def setUp(self):
        self.code = Path("C:/Program Files/Microsoft VS Code/Code.exe")
        self.installation = AppInstallation(self.code)
        self.backend = Mock()
        self.backend.installations.return_value = (self.installation,)
        self.backend.windows.return_value = (
            (1, Path("C:/Apps/Codex/ChatGPT.exe")),
            (2, Path("C:/Program Files/Cursor/Cursor.exe")),
            (3, self.code),
            (4, self.code),
        )
        self.backend.activate.return_value = True
        self.backend.start.return_value = True

    def test_activates_the_frontmost_vscode_window_only(self):
        result = open_vscode(self.backend)
        self.assertTrue(result.opened)
        self.assertEqual(result.operation, "activated")
        self.backend.activate.assert_called_once_with(3)
        self.backend.start.assert_not_called()

    def test_refused_activation_is_reported_without_retry_or_start(self):
        self.backend.activate.return_value = False
        result = open_vscode(self.backend)
        self.assertFalse(result.opened)
        self.assertIn("VS Code", result.message)
        self.backend.activate.assert_called_once_with(3)
        self.backend.start.assert_not_called()

    def test_no_window_starts_vscode_without_arguments(self):
        self.backend.windows.return_value = ()
        result = open_vscode(self.backend)
        self.assertEqual(result.operation, "started")
        self.backend.start.assert_called_once_with(self.installation)
        with patch(
            "watched_kettle.integrations.windows_apps.subprocess.Popen"
        ) as popen:
            backend = object.__new__(WindowsVSCodeLauncher)
            self.assertTrue(backend.start(self.installation))
        self.assertEqual(popen.call_args.args, ([str(self.code)],))

    def test_missing_install_start_failure_and_errors_are_failures(self):
        self.backend.windows.return_value = ()
        self.backend.start.return_value = False
        self.assertFalse(open_vscode(self.backend).opened)
        self.backend.installations.return_value = ()
        self.assertFalse(open_vscode(self.backend).opened)
        self.backend.installations.side_effect = OSError("denied")
        self.assertFalse(open_vscode(self.backend).opened)
        with patch("watched_kettle.integrations.windows_apps.sys.platform", "other"):
            self.assertFalse(open_vscode().opened)

    def test_installation_is_the_registered_vscode_handler(self):
        backend = object.__new__(WindowsVSCodeLauncher)
        backend.registered_executable = Mock(return_value=self.code)
        self.assertEqual(backend.installations(), (self.installation,))
        backend.registered_executable.assert_called_once_with("vscode")
        backend.registered_executable.return_value = None
        self.assertEqual(backend.installations(), ())

    def test_never_uses_the_extension_link_that_creates_a_conversation(self):
        source = inspect.getsource(vscode_launcher)
        code = source.split('"""', 2)[2]
        self.assertNotIn("anthropic.claude-code", code)
        self.assertNotIn("vscode://", code)

    @unittest.skipUnless(sys.platform == "win32", "Windows command parser")
    def test_registered_command_resolves_to_code_exe(self):
        backend = WindowsVSCodeLauncher()
        self.assertEqual(
            backend.command_executable(
                '"C:\\Program Files\\Microsoft VS Code\\Code.exe" --open-url -- "%1"'
            ),
            self.code,
        )
