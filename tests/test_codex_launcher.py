import unittest
from unittest.mock import patch

from watched_kettle.integrations.codex_launcher import (
    CODEX_NEW_CONVERSATION_URL,
    open_codex_new_conversation,
)


class CodexLauncherTests(unittest.TestCase):
    def test_opens_registered_new_conversation_url(self):
        with patch(
            "watched_kettle.integrations.codex_launcher.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            opened = open_codex_new_conversation()

        self.assertTrue(opened)
        url = open_url.call_args.args[0]
        self.assertEqual(url.toString(), CODEX_NEW_CONVERSATION_URL)

    def test_returns_false_when_url_handler_rejects_request(self):
        with patch(
            "watched_kettle.integrations.codex_launcher.QDesktopServices.openUrl",
            return_value=False,
        ):
            self.assertFalse(open_codex_new_conversation())

    def test_returns_false_when_dispatch_raises(self):
        with patch(
            "watched_kettle.integrations.codex_launcher.QDesktopServices.openUrl",
            side_effect=RuntimeError("dispatch failed"),
        ):
            self.assertFalse(open_codex_new_conversation())


if __name__ == "__main__":
    unittest.main()
