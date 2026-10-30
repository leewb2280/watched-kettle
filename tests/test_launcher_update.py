"""The launcher swaps a staged runtime in (packaging/launcher, ADR 0007).

Builds the real launcher and a tiny stand-in app with the .NET Framework
compiler that ships with Windows; skipped where it is missing.
"""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / (
    "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
)
FAKE_APP = """
using System;
using System.IO;
static class FakeApp
{
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        File.WriteAllText(Path.ChangeExtension(
            Environment.GetEnvironmentVariable("WK_LAUNCH_LOG"), ".pid"),
            System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
        File.AppendAllText(Environment.GetEnvironmentVariable("WK_LAUNCH_LOG"),
            File.ReadAllText(Path.Combine(root, "version.txt")).Trim() + "|" +
            string.Join(" ", args) + "\\n");
        return 0;
    }
}
"""


def compile_cs(source, output, target):
    subprocess.run(
        [
            str(CSC),
            "/nologo",
            f"/target:{target}",
            "/codepage:65001",
            f"/out:{output}",
            str(source),
        ],
        check=True,
        capture_output=True,
    )


def wait_for_process(pid, timeout):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the child already exited.
            return
        raise ctypes.WinError(error)
    try:
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise TimeoutError("the owned fake app did not exit")
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(sys.platform == "win32" and CSC.is_file(), "needs csc.exe")
class LauncherUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = TemporaryDirectory()
        build = Path(cls.build.name)
        cls.launcher = build / "WatchedKettle.exe"
        compile_cs(
            PROJECT_ROOT / "packaging" / "launcher" / "WatchedKettleLauncher.cs",
            cls.launcher,
            "winexe",
        )
        fake = build / "FakeApp.cs"
        fake.write_text(FAKE_APP, encoding="utf-8")
        cls.fake_app = build / "FakeApp.exe"
        compile_cs(fake, cls.fake_app, "exe")

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = Path(temp.name) / "app"
        self.runtime = self.app / "runtime"
        self.runtime.mkdir(parents=True)
        shutil.copy2(self.launcher, self.app / "WatchedKettle.exe")
        (self.runtime / "edition").write_text("pet-only", encoding="ascii")
        self.runtime_folder("pet-only", "old", installed="1.0.0")
        self.log = Path(temp.name) / "launch.log"

    def runtime_folder(self, name, version, ready=None, installed=None):
        folder = self.runtime / name
        folder.mkdir()
        shutil.copy2(self.fake_app, folder / "WatchedKettle.exe")
        (folder / "version.txt").write_text(version, encoding="ascii")
        if installed:
            (folder / "BUILD_PROFILE.txt").write_text(
                f"version={installed}\nprofile=public\nedition=pet-only\n",
                encoding="ascii",
            )
        if ready:
            (folder / ".ready").write_text(ready, encoding="ascii")
        return folder

    def launch(self, *arguments):
        return subprocess.Popen(
            [str(self.app / "WatchedKettle.exe"), *arguments],
            env=dict(os.environ, WK_LAUNCH_LOG=str(self.log)),
        )

    def started(self, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.log.is_file() and self.log.read_text().strip():
                # The launcher exits after spawning the app. Its log proves
                # startup, but Windows can still hold the child's executable
                # open until that process exits. Join the owned fake app before
                # TemporaryDirectory cleanup rather than racing its shutdown.
                pid = int(self.log.with_suffix(".pid").read_text())
                wait_for_process(pid, timeout)
                return self.log.read_text().strip().splitlines()
            time.sleep(0.05)
        self.fail("the app did not start")

    def result(self):
        path = self.runtime / "update-result.txt"
        return path.read_text() if path.is_file() else ""

    def test_staged_runtime_is_swapped_in_and_the_app_starts(self):
        self.runtime_folder("pet-only.next", "new", ready="9.9.9")
        self.assertEqual(self.launch("--apply-staged-update", "--x").wait(30), 0)
        # The flag is the launcher's; the app gets the rest.
        self.assertEqual(self.started(), ["new|--x"])
        self.assertEqual((self.runtime / "pet-only" / "version.txt").read_text(), "new")
        self.assertFalse((self.runtime / "pet-only" / ".ready").exists())
        self.assertFalse((self.runtime / "pet-only.next").exists())
        self.assertEqual(
            (self.runtime / "pet-only.old" / "version.txt").read_text(), "old"
        )
        self.assertIn("state=applied", self.result())
        self.assertIn("version=9.9.9", self.result())

    def test_swap_waits_until_nothing_runs_from_the_current_runtime(self):
        self.runtime_folder("pet-only.next", "new", ready="9.9.9")
        # An open file stands in for the quitting app.
        handle = open(self.runtime / "pet-only" / "version.txt", "rb")
        try:
            process = self.launch("--apply-staged-update")
            time.sleep(1.0)
            self.assertIsNone(process.poll())
            self.assertTrue((self.runtime / "pet-only.next").exists())
        finally:
            handle.close()
        self.assertEqual(process.wait(30), 0)
        self.assertEqual(self.started(), ["new|"])
        self.assertIn("state=applied", self.result())

    def test_a_normal_start_next_to_a_running_app_does_not_wait(self):
        self.runtime_folder("pet-only.next", "new", ready="9.9.9")
        with open(self.runtime / "pet-only" / "version.txt", "rb"):
            started = time.monotonic()
            self.assertEqual(self.launch().wait(30), 0)
            self.assertLess(time.monotonic() - started, 10)
            self.assertEqual(self.started(), ["old|"])
        # Not a failure: the staged runtime waits for the next start.
        self.assertEqual(self.result(), "")
        self.assertTrue((self.runtime / "pet-only.next" / ".ready").exists())

    def test_a_staged_runtime_not_newer_than_the_installed_one_is_dropped(self):
        # Setup installed a newer version after the app had staged an update.
        for staged in ("0.15.11", "1.0.0", "broken"):
            with self.subTest(staged=staged):
                self.log.unlink(missing_ok=True)
                self.runtime_folder("pet-only.next", "stale", ready=staged)
                self.assertEqual(self.launch("--apply-staged-update").wait(30), 0)
                self.assertEqual(self.started(), ["old|"])
                self.assertFalse((self.runtime / "pet-only.next").exists())
                self.assertEqual(
                    (self.runtime / "pet-only" / "version.txt").read_text(), "old"
                )
                self.assertEqual(self.result(), "")

    def verify(self, folder):
        return subprocess.run(
            [str(self.app / "WatchedKettle.exe"), "--verify-runtime", str(folder)],
            timeout=30,
            check=False,
        ).returncode

    def test_setup_checks_a_copied_runtime_against_its_manifest(self):
        from scripts.release_artifacts import generate_manifest

        folder = self.runtime / "pet-only.install"
        (folder / "_internal").mkdir(parents=True)
        (folder / "_internal" / "python314.dll").write_bytes(b"dll" * 1000)
        (folder / "_internal" / "펫 이름.txt").write_text("한글", encoding="utf-8")
        (folder / "WatchedKettle.exe").write_bytes(b"app")
        generate_manifest(folder)
        self.assertEqual(self.verify(folder), 0)

        dll = folder / "_internal" / "python314.dll"
        for damage in (
            lambda: dll.write_bytes(b"dll" * 999),
            lambda: dll.write_bytes(b"DLL" * 1000),
            dll.unlink,
        ):
            with self.subTest(damage=damage):
                damage()
                self.assertEqual(self.verify(folder), 1)
                dll.write_bytes(b"dll" * 1000)
        self.assertEqual(self.verify(folder), 0)
        (folder / "PACKAGE_MANIFEST.sha256.json").unlink()
        self.assertEqual(self.verify(folder), 1)
        # The app is never started by a check.
        self.assertFalse(self.log.exists())

    def test_a_staged_runtime_without_its_ready_marker_is_never_used(self):
        self.runtime_folder("pet-only.next", "half")
        self.assertEqual(self.launch("--apply-staged-update").wait(30), 0)
        self.assertEqual(self.started(), ["old|"])
        self.assertEqual(self.result(), "")


if __name__ == "__main__":
    unittest.main()
