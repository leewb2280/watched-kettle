"""The GUI target is registered identity, never a title or CLI process name."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from watched_kettle.integrations.codex_launcher import (
    WindowsCodexLauncher,
    open_codex,
)
from watched_kettle.integrations.windows_apps import AppInstallation


class CodexLauncherTests(unittest.TestCase):
    def setUp(self):
        self.gui = Path("C:/Apps/Codex/ChatGPT.exe")
        self.installation = AppInstallation(self.gui, "CodexFamily!App")
        self.backend = Mock()
        self.backend.installations.return_value = (self.installation,)
        self.backend.windows.return_value = (
            (1, Path("C:/Apps/ChatGPT/ChatGPT.exe")),
            (2, Path("C:/Tools/codex.exe")),
            (3, self.gui),
            (4, self.gui),
        )
        self.backend.activate.return_value = True
        self.backend.start.return_value = True

    def test_skips_cli_and_other_chatgpt_then_activates_first_gui_in_z_order(self):
        result = open_codex(self.backend)
        self.assertTrue(result.opened)
        self.assertEqual(result.operation, "activated")
        self.backend.activate.assert_called_once_with(3)
        self.backend.start.assert_not_called()

    def test_denied_activation_never_starts_or_retries_other_windows(self):
        self.backend.activate.return_value = False
        self.assertFalse(open_codex(self.backend).opened)
        self.backend.activate.assert_called_once_with(3)
        self.backend.start.assert_not_called()

    def test_absent_window_starts_registered_app(self):
        self.backend.windows.return_value = ()
        result = open_codex(self.backend)
        self.assertEqual(result.operation, "started")
        self.backend.start.assert_called_once_with(self.installation)
        self.backend.activate.assert_not_called()

    def test_missing_install_and_start_failure_are_not_reported_as_success(self):
        self.backend.start.return_value = False
        self.backend.windows.return_value = ()
        self.assertFalse(open_codex(self.backend).opened)
        self.backend.installations.return_value = ()
        self.assertFalse(open_codex(self.backend).opened)

    def test_platform_and_access_errors_are_results(self):
        self.backend.installations.side_effect = OSError("denied")
        self.assertFalse(open_codex(self.backend).opened)
        with patch("watched_kettle.integrations.windows_apps.sys.platform", "other"):
            self.assertFalse(open_codex().opened)
        with patch(
            "watched_kettle.integrations.codex_launcher.WindowsCodexLauncher",
            side_effect=OSError("denied"),
        ):
            if sys.platform == "win32":
                self.assertFalse(open_codex().opened)

    def test_minimized_window_is_restored_without_repositioning(self):
        backend = object.__new__(WindowsCodexLauncher)
        user = Mock()
        user.IsIconic.return_value = True
        user.GetForegroundWindow.return_value = 42
        backend.user = user
        self.assertTrue(backend.activate(42))
        user.ShowWindow.assert_called_once_with(42, 9)
        user.SetForegroundWindow.assert_called_once_with(42)
        user.reset_mock()
        user.IsIconic.return_value = False
        user.GetForegroundWindow.return_value = 99
        self.assertFalse(backend.activate(42))
        user.ShowWindow.assert_not_called()

    def test_classic_start_has_no_url_thread_or_resume_arguments(self):
        with patch(
            "watched_kettle.integrations.windows_apps.subprocess.Popen"
        ) as popen:
            backend = object.__new__(WindowsCodexLauncher)
            self.assertTrue(backend.start(AppInstallation(self.gui)))
        popen.assert_called_once_with(
            [str(self.gui)],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )


class RegisteredExecutableTests(unittest.TestCase):
    def test_empty_registration_is_not_interpreted_as_the_current_python(self):
        backend = object.__new__(WindowsCodexLauncher)
        for command in ("", " ", None, 123):
            self.assertIsNone(backend.command_executable(command))

    @unittest.skipUnless(sys.platform == "win32", "Windows command parser")
    def test_registration_uses_an_absolute_executable_without_url_arguments(self):
        backend = WindowsCodexLauncher()
        self.assertEqual(
            backend.command_executable(
                '"C:\\Program Files\\Codex\\ChatGPT.exe" --open-url "%1"'
            ),
            Path("C:/Program Files/Codex/ChatGPT.exe"),
        )
        for command in ('codex.exe "%1"', '"C:\\Apps\\launch.bat" "%1"'):
            self.assertIsNone(backend.command_executable(command))
