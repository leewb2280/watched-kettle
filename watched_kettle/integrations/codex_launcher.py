"""Open the Codex desktop app through its registered URL handler."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


CODEX_NEW_CONVERSATION_URL = "codex://new"


def open_codex_new_conversation():
    """Open Codex at a new conversation, returning whether dispatch succeeded."""
    try:
        return bool(QDesktopServices.openUrl(QUrl(CODEX_NEW_CONVERSATION_URL)))
    except Exception:
        return False
