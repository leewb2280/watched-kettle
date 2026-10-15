import os
import unittest
from pathlib import Path

from tests import ISOLATED_LOCAL_APP_DATA
from watched_kettle.application.paths import AppPaths
from watched_kettle.integrations.codex_spool import DEFAULT_USER_RUNTIME_ROOT


class UserDataIsolationTests(unittest.TestCase):
    """Fails when a test runner skips the tests package isolation."""

    def test_user_data_root_points_to_the_isolated_folder(self):
        isolated = Path(ISOLATED_LOCAL_APP_DATA)

        self.assertEqual(Path(os.environ["LOCALAPPDATA"]), isolated)
        self.assertTrue(AppPaths.default().data_root.is_relative_to(isolated))
        # Resolved at import time, so it proves isolation ran first.
        self.assertTrue(DEFAULT_USER_RUNTIME_ROOT.is_relative_to(isolated))


if __name__ == "__main__":
    unittest.main()
