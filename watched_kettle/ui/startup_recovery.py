"""Startup recovery dialog for missing or damaged pet packages."""

from __future__ import annotations

from watched_kettle.localization import t

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


@dataclass(frozen=True)
class StartupRecoveryChoice:
    action: str
    pet_directory: Path | None = None


class StartupRecoveryDialog(QDialog):
    def __init__(self, startup_error, initial_directory, parent=None):
        super().__init__(parent)
        self.startup_error = startup_error
        self.initial_directory = Path(initial_directory)
        self.choice = StartupRecoveryChoice("quit")
        self.setWindowTitle(t("message.0327"))
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet(
            """
            QDialog { background: #f5f2ec; color: #2d2924; }
            QLabel#recoveryTitle { font-size: 20px; font-weight: 700; }
            QLabel#recoveryGuidance { color: #746c62; }
            QPlainTextEdit {
                background: #fffdf9;
                border: 1px solid #d8d1c6;
                padding: 6px;
            }
            QPushButton { padding: 7px 12px; }
            """
        )

        layout = QVBoxLayout(self)
        title = QLabel(t("message.0328"))
        title.setObjectName("recoveryTitle")
        layout.addWidget(title)

        message = QLabel(startup_error.user_message)
        message.setWordWrap(True)
        layout.addWidget(message)

        guidance = QLabel(t("message.0329"))
        guidance.setWordWrap(True)
        guidance.setObjectName("recoveryGuidance")
        layout.addWidget(guidance)

        self.details = QPlainTextEdit(startup_error.details)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)

        actions = QHBoxLayout()
        quit_button = QPushButton(t("message.0226"))
        quit_button.clicked.connect(self.reject)
        actions.addWidget(quit_button)
        actions.addStretch(1)
        choose_button = QPushButton(t("message.0330"))
        choose_button.clicked.connect(self.choose_directory)
        actions.addWidget(choose_button)
        retry_button = QPushButton(t("message.0331"))
        retry_button.setDefault(True)
        retry_button.clicked.connect(self.retry)
        actions.addWidget(retry_button)
        layout.addLayout(actions)

    def retry(self):
        self.choice = StartupRecoveryChoice("retry")
        self.accept()

    def choose_directory(self):
        selected = QFileDialog.getExistingDirectory(
            self,
            t("message.0332"),
            str(self.initial_directory),
        )
        if not selected:
            return
        self.choice = StartupRecoveryChoice(
            "choose",
            Path(selected),
        )
        self.accept()

    @classmethod
    def request(cls, startup_error, initial_directory, parent=None):
        dialog = cls(startup_error, initial_directory, parent)
        dialog.exec()
        return dialog.choice
