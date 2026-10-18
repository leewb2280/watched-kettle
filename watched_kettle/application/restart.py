"""Restart intent and detached relaunch after the normal application shutdown."""

from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer


REOPEN_SETTINGS_FLAG = "--reopen-app-settings"


def consume_restart_route(arguments):
    reopen = REOPEN_SETTINGS_FLAG in arguments
    arguments[:] = [value for value in arguments if value != REOPEN_SETTINGS_FLAG]
    return reopen


class AppRestart:
    def __init__(self, app, *, pet_only=False):
        self.app = app
        self.requested = False
        self.frozen = bool(getattr(sys, "frozen", False))
        self.program = sys.executable
        self.arguments = list(sys.argv[1:])
        if not self.frozen:
            root = Path(__file__).resolve().parents[2]
            entry = "main_pet_only.py" if pet_only else "main.py"
            self.arguments.insert(0, str(root / entry))
        self.arguments.append(REOPEN_SETTINGS_FLAG)
        self.directory = str(Path.cwd())

    def request(self):
        if not self.requested:
            self.requested = True
            QTimer.singleShot(0, self.app.quit)

    def launch(self):
        """The caller must finish runtime cleanup and release single-instance IPC."""
        process = QProcess()
        process.setProgram(self.program)
        process.setArguments(self.arguments)
        process.setWorkingDirectory(self.directory)
        environment = QProcessEnvironment.systemEnvironment()
        if self.frozen:
            # PyInstaller 6.9+: a restart is independent of its exiting parent.
            environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
        process.setProcessEnvironment(environment)
        return process.startDetached()
