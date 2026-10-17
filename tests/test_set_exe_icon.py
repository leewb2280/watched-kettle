import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.set_exe_icon import read_icon_groups, read_icon_ids, read_ico, set_exe_icon
from watched_kettle.branding import PROJECT_ROOT


APP_ICON = PROJECT_ROOT / "assets" / "app_icon.ico"


@unittest.skipUnless(sys.platform == "win32", "Windows resource API")
class SetExeIconTests(unittest.TestCase):
    def test_first_icon_group_is_replaced_and_old_images_removed(self):
        images = read_ico(APP_ICON)
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "sample.exe"
            shutil.copyfile(sys._base_executable, executable)
            before = read_icon_groups(executable)
            name, languages = next(iter(before.items()))
            self.assertGreater(len(next(iter(languages.values()))), len(images))

            set_exe_icon(executable, APP_ICON)

            after = read_icon_groups(executable)
            self.assertEqual(list(after), list(before))
            for language in languages:
                self.assertEqual(len(after[name][language]), len(images))
            self.assertEqual(
                sorted(read_icon_ids(executable)), list(range(1, len(images) + 1))
            )

    def test_non_icon_file_is_rejected(self):
        with self.assertRaises(ValueError):
            read_ico(PROJECT_ROOT / "assets" / "app_icon.png")


if __name__ == "__main__":
    unittest.main()
