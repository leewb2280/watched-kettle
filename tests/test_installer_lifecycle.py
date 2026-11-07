"""Run the production installer callbacks in an isolated Inno Setup engine.

Only filesystem/integration work is stubbed. The actual [Run] entries,
readiness/relaunch helpers and CurStepChanged body come from the product .iss.
No product AppId, user data, hooks or running app are used.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from tests.test_launcher_update import CSC, wait_for_process

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "packaging/windows-installer.iss"
ISCC = (
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    / "Inno Setup 6/ISCC.exe"
)
# A launch is nowait, so a Setup that started the app can exit before the app
# writes its log. A launch that is expected not to happen gets this long.
LAUNCH_GRACE = 2
# Inno Setup logs every [Run] entry it runs; the silent relaunch must not be one.
RUN_ENTRY = "-- Run entry --"
FAKE_LAUNCHER = r"""
using System;
using System.IO;
static class FakeLauncher {
    [STAThread]
    static int Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string log = Path.Combine(root, "..", "launch.log");
        File.WriteAllText(log + ".pid", System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
        File.AppendAllText(log, File.ReadAllText(Path.Combine(root, "runtime", "fixture-version.txt")) + "\n");
        return 0;
    }
}
"""

HEADER = r"""
#define AppExe "WatchedKettle.exe"
#define LegacyAppExe "UnusedLegacy.exe"
#define AppId "WatchedKettleLifecycleFixture"
[Setup]
AppId=WatchedKettle-LifecycleFixture-{#FixtureId}
AppName=Installer lifecycle fixture
AppVersion=1.0.0
DefaultDirName={param:CASE}\app
UsePreviousAppDir=no
UsePreviousLanguage=no
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
CloseApplications=no
RestartApplications=no
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
OutputDir={#OutputRoot}
OutputBaseFilename=fixture-setup
SetupLogging=yes
[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
"""

# Each case passes its folder, edition and swap result as Setup parameters,
# so one compiled fixture serves every case.
STUBS = r"""
function CaseFile(const Name: String): String;
begin Result := ExpandConstant('{param:CASE}\') + Name; end;
procedure DetectInstalledState();
begin
  if RuntimeReady() then
    SaveStringToFile(CaseFile('before-ready.txt'), '1', False)
  else
    SaveStringToFile(CaseFile('before-ready.txt'), '0', False);
end;
function SelectedEdition(): String;
begin Result := ExpandConstant('{param:EDITION}'); end;
function SwapInstalledRuntime(const Edition: String): Boolean;
begin
  Result := ExpandConstant('{param:FAILSWAP|0}') = '0';
  if Result then
    SaveStringToFile(ExpandConstant('{app}\runtime\fixture-version.txt'), 'new', False);
end;
function InstallAssistant(): Boolean;
begin Result := SelectedEdition() = 'pet-assistant'; end;
function LegacyHookPresent(): Boolean;
begin Result := False; end;
function SelectedExecutable(const Suffix: String): String;
begin Result := ''; end;
procedure DeleteLegacyExecutables(const Edition: String);
begin end;
function IntegrationArguments(): String;
begin Result := ''; end;
function RuntimeExecutable(const Edition: String): String;
begin Result := ''; end;
procedure UpdateStartupEntry();
begin end;
"""

TAIL = r"""
procedure DeinitializeSetup();
begin
  if RuntimeReady() then
    SaveStringToFile(CaseFile('after-ready.txt'), '1', False)
  else
    SaveStringToFile(CaseFile('after-ready.txt'), '0', False);
end;
"""


def fixture_source(*, postinstall=False):
    source = INSTALLER.read_text(encoding="utf-8")
    messages = source.split("[CustomMessages]", 1)[1].split("[Files]", 1)[0]
    runs = source.split("[Run]", 1)[1].split("[Code]", 1)[0]
    if postinstall:
        # Exercise the real postinstall scheduling without showing a wizard.
        # Only skipifsilent is removed; production launch checks are unchanged.
        runs = runs.replace(" skipifsilent", "")
    helpers = source.split("function RuntimeReady(): Boolean;", 1)[1].split(
        "// Runs before Restart Manager", 1
    )[0]
    callback = source.split("procedure CurStepChanged(CurStep: TSetupStep);", 1)[
        1
    ].split("// ---- Uninstall steps", 1)[0]
    return (
        HEADER
        + "\n[CustomMessages]\n"
        + messages
        + "\n[Run]\n"
        + runs
        + "\n[Code]\nvar RuntimeSwapError, RuntimeCommitted, RuntimeRelaunchError: Boolean;\n"
        + "function RuntimeReady(): Boolean;"
        + helpers
        + STUBS
        + "procedure CurStepChanged(CurStep: TSetupStep);"
        + callback
        + TAIL
    )


@unittest.skipUnless(
    sys.platform == "win32" and CSC.is_file() and ISCC.is_file(),
    "requires Windows, .NET Framework compiler and Inno Setup",
)
class InstallerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / "build/installer-lifecycle-tests"
        base.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=base)
        cls.root = Path(cls.temp.name)
        source = cls.root / "FakeLauncher.cs"
        source.write_text(FAKE_LAUNCHER, encoding="utf-8")
        cls.launcher = cls.root / "FakeLauncher.exe"
        subprocess.run(
            [
                str(CSC),
                "/nologo",
                "/target:winexe",
                f"/out:{cls.launcher}",
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        cls.setups = {
            postinstall: cls.compile_fixture(postinstall)
            for postinstall in (False, True)
        }
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def compile_fixture(cls, postinstall):
        output = cls.root / ("postinstall" if postinstall else "silent")
        output.mkdir()
        script = output / "fixture.iss"
        script.write_text(fixture_source(postinstall=postinstall), encoding="utf-8")
        compiled = subprocess.run(
            [
                str(ISCC),
                f"/DOutputRoot={output}",
                f"/DFixtureId={output.name}-{os.getpid()}",
                str(script),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if compiled.returncode != 0:
            raise AssertionError(compiled.stdout + compiled.stderr)
        return output / "fixture-setup.exe"

    def run_case(
        self, edition, *, swap=True, relaunch=True, launcher=True, postinstall=False
    ):
        type(self).counter += 1
        root = self.root / f"case-{self.counter}"
        app = root / "app"
        runtime = app / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "fixture-version.txt").write_text("old", encoding="ascii")
        sentinel = root / "user-data-sentinel.txt"
        sentinel.write_text("keep", encoding="ascii")
        if launcher:
            shutil.copy2(self.launcher, app / "WatchedKettle.exe")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            [
                str(self.setups[postinstall]),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/SP-",
                "/NORESTART",
                "/LANG=en",
                f"/RELAUNCH={1 if relaunch else 0}",
                f"/CASE={root}",
                f"/EDITION={edition}",
                f"/FAILSWAP={0 if swap else 1}",
                f"/LOG={root / 'setup.log'}",
            ],
            startupinfo=startup,
            timeout=25,
        )
        setup_log = (root / "setup.log").read_text(encoding="utf-8-sig")
        log = root / "launch.log"
        expected = swap and launcher and (relaunch or postinstall)
        deadline = time.monotonic() + (10 if expected else LAUNCH_GRACE)
        while not log.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        if log.is_file():
            wait_for_process(int(log.with_suffix(".log.pid").read_text()), 10)
        self.assertEqual(log.is_file(), expected, setup_log)
        # Only the interactive launch may come from [Run]; the silent relaunch
        # runs after the runtime commit, which no [Run] entry can follow.
        self.assertEqual(RUN_ENTRY in setup_log, postinstall and expected, setup_log)
        self.assertEqual(sentinel.read_text(), "keep")
        return (
            result.returncode,
            root,
            log.read_text().splitlines() if log.exists() else [],
        )

    def test_silent_relaunch_starts_only_the_committed_runtime(self):
        for edition in ("pet-only", "pet-assistant"):
            with self.subTest(edition=edition):
                code, root, launches = self.run_case(edition)
                self.assertEqual(code, 0)
                self.assertEqual(launches, ["new"])
                self.assertEqual((root / "before-ready.txt").read_text(), "0")
                self.assertEqual((root / "after-ready.txt").read_text(), "1")

    def test_failed_swap_never_relaunches_and_returns_failure(self):
        for edition in ("pet-only", "pet-assistant"):
            with self.subTest(edition=edition):
                code, root, launches = self.run_case(edition, swap=False)
                self.assertEqual(code, 9)
                self.assertEqual(launches, [])
                self.assertEqual(
                    (root / "app/runtime/fixture-version.txt").read_text(), "old"
                )
                self.assertEqual((root / "after-ready.txt").read_text(), "0")

    def test_silent_install_without_relaunch_keeps_the_app_closed(self):
        code, _, launches = self.run_case("pet-assistant", relaunch=False)
        self.assertEqual(code, 0)
        self.assertEqual(launches, [])

    def test_postinstall_launch_checks_the_committed_runtime_at_finish(self):
        code, _, launches = self.run_case(
            "pet-assistant", relaunch=False, postinstall=True
        )
        self.assertEqual(code, 0)
        self.assertEqual(launches, ["new"])

    def test_failed_relaunch_has_a_distinct_exit_code(self):
        code, root, launches = self.run_case("pet-assistant", launcher=False)
        self.assertEqual(code, 10)
        self.assertEqual(launches, [])
        self.assertEqual((root / "app/runtime/fixture-version.txt").read_text(), "new")
