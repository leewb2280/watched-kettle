import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from watched_kettle.integrations.windows_startup import (
    LEGACY_RUN_VALUE_NAME,
    RUN_VALUE_NAME,
    WindowsStartupRegistration,
)


class FakeRegistry:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self, name):
        return self.values.get(name, "")

    def write(self, name, command):
        self.values[name] = command

    def delete(self, name):
        self.values.pop(name, None)


class WindowsStartupRegistrationTests(unittest.TestCase):
    def test_source_launch_uses_pythonw_and_absolute_entry_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python.exe"
            pythonw = root / "pythonw.exe"
            entry = root / "project" / "main.py"
            pythonw.touch()
            service = WindowsStartupRegistration(
                registry=FakeRegistry(),
                platform="nt",
                executable=python,
                source_entry=entry,
                frozen=False,
            )

            self.assertEqual(
                service.expected_command(),
                subprocess.list2cmdline(
                    [
                        str(pythonw.resolve()),
                        str(entry.resolve()),
                    ]
                ),
            )

    def test_enabling_writes_only_the_dedicated_current_user_value(self):
        registry = FakeRegistry()
        service = WindowsStartupRegistration(
            registry=registry,
            platform="nt",
            executable="C:/Assistant/pet.exe",
            frozen=True,
        )

        status = service.set_enabled(True)

        self.assertEqual(
            registry.values,
            {RUN_VALUE_NAME: service.expected_command()},
        )
        self.assertTrue(status.enabled)
        self.assertTrue(status.matches_current_app)

    def test_mismatched_old_path_is_reported_and_repaired(self):
        registry = FakeRegistry({RUN_VALUE_NAME: '"C:\\Old\\pet.exe"'})
        service = WindowsStartupRegistration(
            registry=registry,
            platform="nt",
            executable="C:/Assistant/pet.exe",
            frozen=True,
        )

        before = service.inspect()
        after = service.set_enabled(True)

        self.assertTrue(before.enabled)
        self.assertFalse(before.matches_current_app)
        self.assertTrue(after.matches_current_app)

    def test_disabling_removes_only_the_dedicated_value(self):
        registry = FakeRegistry(
            {
                RUN_VALUE_NAME: "pet",
                "AnotherApp": "another",
            }
        )
        service = WindowsStartupRegistration(
            registry=registry,
            platform="nt",
            frozen=True,
        )

        status = service.set_enabled(False)

        self.assertFalse(status.enabled)
        self.assertEqual(registry.values, {"AnotherApp": "another"})

    def test_non_windows_platform_is_disabled_without_registry_access(self):
        class ExplodingRegistry:
            def read(self, name):
                raise AssertionError("registry should not be read")

        service = WindowsStartupRegistration(
            registry=ExplodingRegistry(),
            platform="posix",
            frozen=True,
        )

        status = service.inspect()

        self.assertFalse(status.supported)
        self.assertFalse(status.enabled)
        with self.assertRaises(OSError):
            service.set_enabled(True)

    def test_installed_runtime_registers_the_stable_launcher(self):
        with TemporaryDirectory() as directory:
            app = Path(directory) / "Watched Kettle"
            runtime = app / "runtime" / "pet-assistant" / "WatchedKettle.exe"
            runtime.parent.mkdir(parents=True)
            runtime.touch()
            launcher = app / "WatchedKettle.exe"
            launcher.touch()
            service = WindowsStartupRegistration(
                registry=FakeRegistry(),
                platform="nt",
                executable=runtime,
                frozen=True,
            )

            self.assertEqual(
                service.expected_command(),
                subprocess.list2cmdline([str(launcher.resolve())]),
            )

    def test_runtime_without_launcher_registers_itself(self):
        with TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime" / "pet-only" / "WatchedKettle.exe"
            runtime.parent.mkdir(parents=True)
            runtime.touch()
            service = WindowsStartupRegistration(
                registry=FakeRegistry(),
                platform="nt",
                executable=runtime,
                frozen=True,
            )

            self.assertEqual(
                service.expected_command(),
                subprocess.list2cmdline([str(runtime.resolve())]),
            )

    def test_legacy_value_moves_to_current_name_for_this_executable(self):
        registry = FakeRegistry(
            {LEGACY_RUN_VALUE_NAME: '"C:/Old/CodexDesktopPets.exe"'}
        )
        service = WindowsStartupRegistration(
            registry=registry,
            platform="nt",
            executable="C:/Kettle/WatchedKettle.exe",
            frozen=True,
        )

        self.assertTrue(service.migrate_legacy_entry())

        self.assertEqual(registry.values, {RUN_VALUE_NAME: service.expected_command()})
        self.assertFalse(service.migrate_legacy_entry())

    def test_legacy_value_is_removed_without_overwriting_current_value(self):
        registry = FakeRegistry(
            {LEGACY_RUN_VALUE_NAME: "old.exe", RUN_VALUE_NAME: "custom.exe"}
        )
        service = WindowsStartupRegistration(
            registry=registry, platform="nt", executable="new.exe", frozen=True
        )

        self.assertTrue(service.migrate_legacy_entry())
        self.assertEqual(registry.values, {RUN_VALUE_NAME: "custom.exe"})

    def test_legacy_migration_does_nothing_off_windows(self):
        registry = FakeRegistry({LEGACY_RUN_VALUE_NAME: "old.exe"})
        service = WindowsStartupRegistration(registry=registry, platform="posix")

        self.assertFalse(service.migrate_legacy_entry())
        self.assertEqual(registry.values, {LEGACY_RUN_VALUE_NAME: "old.exe"})


if __name__ == "__main__":
    unittest.main()
