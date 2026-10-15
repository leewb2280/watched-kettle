"""Bundle file boundaries: Qt Quick stays out of the pet-only edition."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_edition_modules import check_bundle_files


class EditionBundleFileTests(unittest.TestCase):
    def bundle(self, *files):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
        return root

    def test_pet_only_rejects_the_usage_widget_and_qt_quick(self):
        root = self.bundle(
            "PySide6/Qt6Quick.dll",
            "PySide6/QtQuick.pyd",
            "PySide6/qml/QtQuick/qmldir",
            "watched_kettle/ui/usage_widget/qml/UsageWidget.qml",
            "assets/app_icon.png",
        )
        self.assertEqual(
            check_bundle_files(root, "pet-only"),
            [
                "PySide6/QtQuick.pyd",
                "PySide6/qml/QtQuick/qmldir",
                "watched_kettle/ui/usage_widget/qml/UsageWidget.qml",
            ],
        )

    def test_assistant_keeps_only_the_widget_qml_modules(self):
        root = self.bundle(
            "PySide6/QtQuick.pyd",
            "PySide6/qml/QtQuick/Shapes/qmldir",
            "PySide6/qml/QtQuick/Controls/qmldir",
            "PySide6/Qt6WebEngineCore.dll",
        )
        self.assertEqual(
            check_bundle_files(root, "pet-assistant"),
            ["PySide6/Qt6WebEngineCore.dll", "PySide6/qml/QtQuick/Controls/qmldir"],
        )


if __name__ == "__main__":
    unittest.main()
