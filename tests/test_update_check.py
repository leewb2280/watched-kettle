"""User-requested update against the local test server: rules, check, download."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from scripts import serve_update_test
from watched_kettle.application import update_check
from watched_kettle.application.update_check import (
    UpdateService,
    download_url_allowed,
    installed_app_root,
    installer_asset_name,
    release_url_kind,
)
from watched_kettle.branding import APPLICATION_VERSION

INSTALLER_NAME = "WatchedKettle-9.9.9-public-update-test-unsigned-setup.exe"


class AddressRuleTests(unittest.TestCase):
    def test_official_and_local_test_addresses(self):
        repo = "https://api.github.com/repos/leewb2280/watched-kettle/releases/latest"
        self.assertEqual(release_url_kind(repo, api=True), "official")
        self.assertEqual(
            release_url_kind("https://github.com/leewb2280/watched-kettle/releases"),
            "official",
        )
        self.assertEqual(
            release_url_kind("http://127.0.0.1:8765/api/releases/latest", api=True),
            "local-test",
        )
        self.assertEqual(
            release_url_kind("http://127.0.0.1:8765/releases"), "local-test"
        )
        # A test server on another PC of the same private network.
        for host in ("192.168.0.10", "10.1.2.3", "172.16.0.5", "172.31.255.1"):
            self.assertEqual(
                release_url_kind(f"http://{host}:8765/releases"), "local-test", host
            )

    def test_rejected_addresses(self):
        for url, api in (
            ("", False),
            ("https://github.com/org/repo/releases", True),
            ("https://api.github.com/repos/org/repo/releases/latest", False),
            ("http://github.com/org/repo/releases", False),
            ("https://github.com:8443/org/repo/releases", False),
            ("https://user@github.com/org/repo/releases", False),
            ("http://localhost:8765/releases", False),
            ("http://127.0.0.1/releases", False),
            ("http://127.0.0.1.example.com:8765/releases", False),
            ("http://192.168.0.10/releases", False),
            ("https://192.168.0.10:8765/releases", False),
            ("http://8.8.8.8:8765/releases", False),
            ("http://172.32.0.1:8765/releases", False),
            ("http://169.254.1.1:8765/releases", False),
            ("http://127.0.0.2:8765/releases", False),
            ("http://[::1]:8765/releases", False),
            ("http://kettle.local:8765/releases", False),
            ("https://127.0.0.1:8765/releases", False),
            ("file:///C:/releases", False),
        ):
            self.assertIsNone(release_url_kind(url, api=api), url)

    def test_download_hosts(self):
        for url in (
            "https://github.com/o/r/releases/download/v1.0.0/setup.exe",
            "https://objects.githubusercontent.com/a/b",
            "https://release-assets.githubusercontent.com/a/b",
        ):
            self.assertTrue(download_url_allowed(url, "official"), url)
        for url in (
            "http://github.com/o/r/releases/download/v1.0.0/setup.exe",
            "https://example.com/setup.exe",
            "https://githubusercontent.com.example.com/a",
            "http://127.0.0.1:8765/assets/setup.exe",
        ):
            self.assertFalse(download_url_allowed(url, "official"), url)
        self.assertTrue(
            download_url_allowed("http://127.0.0.1:8765/a", "local-test", 8765)
        )
        self.assertFalse(
            download_url_allowed("http://127.0.0.1:8766/a", "local-test", 8765)
        )
        self.assertFalse(
            download_url_allowed("https://github.com/a", "local-test", 8765)
        )
        # Only from the test server that was asked, on its port.
        lan = "192.168.0.10"
        self.assertTrue(
            download_url_allowed(f"http://{lan}:8765/a", "local-test", 8765, lan)
        )
        self.assertFalse(
            download_url_allowed("http://192.168.0.11:8765/a", "local-test", 8765, lan)
        )
        self.assertFalse(
            download_url_allowed("http://127.0.0.1:8765/a", "local-test", 8765, lan)
        )

    def test_installer_names_each_channel_may_run(self):
        self.assertTrue(
            installer_asset_name(
                "WatchedKettle-1.2.3-public-unsigned-setup.exe", "1.2.3", "official"
            )
        )
        self.assertTrue(
            installer_asset_name(
                "WatchedKettle-1.2.3-public-setup.exe", "1.2.3", "official"
            )
        )
        for name in (
            "WatchedKettle-1.2.3-private-pets-unsigned-setup.exe",
            "WatchedKettle-1.2.3-public-update-test-unsigned-setup.exe",
            "WatchedKettle-1.2.4-public-unsigned-setup.exe",
            "WatchedKettle-1.2.3-public-unsigned-setup.exe.sha256",
            "WatchedKettle-1.2.3-public-unsigned-setup.zip",
        ):
            self.assertFalse(installer_asset_name(name, "1.2.3", "official"), name)
        for name in (
            "WatchedKettle-1.2.3-public-update-test-unsigned-setup.exe",
            "WatchedKettle-1.2.3-private-pets-update-test-unsigned-setup.exe",
        ):
            self.assertTrue(installer_asset_name(name, "1.2.3", "local-test"), name)

    def test_only_an_installed_runtime_can_install(self):
        with TemporaryDirectory() as directory:
            app = Path(directory) / "WatchedKettle"
            runtime = app / "runtime" / "pet-only"
            runtime.mkdir(parents=True)
            executable = runtime / "WatchedKettle.exe"
            executable.write_bytes(b"")
            self.assertIsNone(installed_app_root(executable))
            (app / "runtime" / "edition").write_text("pet-only", encoding="utf-8")
            self.assertIsNone(installed_app_root(executable))
            (app / "unins000.exe").write_bytes(b"")
            self.assertEqual(installed_app_root(executable), app.resolve())
        # Source runs never install.
        self.assertIsNone(installed_app_root())


class UpdateSourcePathTests(unittest.TestCase):
    def test_source_runs_honor_the_override_and_frozen_builds_do_not(self):
        with patch.dict(os.environ, {"WATCHED_KETTLE_UPDATE_SOURCE": "C:/x/s.json"}):
            self.assertEqual(update_check.update_source_path(), Path("C:/x/s.json"))
            with (
                patch.object(update_check.sys, "frozen", True, create=True),
                patch.object(
                    update_check.sys, "executable", "C:/app/WatchedKettle.exe"
                ),
            ):
                self.assertEqual(
                    update_check.update_source_path(),
                    Path("C:/app/UPDATE_SOURCE.json"),
                )


class UpdateServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.updates = self.root / "updates"
        self.servers = []
        self.services = []
        self.installer = self.root / INSTALLER_NAME
        # Several network chunks, so progress and hashing run more than once.
        self.installer.write_bytes(os.urandom(300_000))

    def tearDown(self):
        for service in self.services:
            service.cancel()
        QTest.qWait(20)
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def write_source(self, source):
        path = self.root / "UPDATE_SOURCE.json"
        path.write_text(json.dumps(source), encoding="utf-8")
        return path

    def serve(self, version="9.9.9", mode="ok"):
        server = serve_update_test.serve(0, self.installer, version, mode)
        self.servers.append(server)
        return self.write_source(
            serve_update_test.update_source(server.server_address[1])
        )

    def service(self, source):
        service = UpdateService(source, updates_dir=self.updates)
        self.services.append(service)
        return service

    def wait_while(self, service, *states, timeout_ms=10000):
        waited = 0
        while service.state in states and waited < timeout_ms:
            QTest.qWait(10)
            waited += 10
        self.assertNotIn(service.state, states)
        return service.snapshot()

    def check(self, source):
        service = self.service(source)
        service.check()
        return service, self.wait_while(service, "checking")

    def installed(self):
        return patch.object(update_check, "installed_app_root", return_value=self.root)

    def test_requires_a_configured_and_consistent_source(self):
        _, update = self.check(self.root / "missing.json")
        self.assertEqual(update["state"], "idle")
        self.assertIn("아직", update["message"])
        for source in (
            {
                "api_url": "http://example.com/latest",
                "release_url": "https://github.com/org/repo/releases",
            },
            # Official API with a local page, or the reverse, never mixes.
            {
                "api_url": "https://api.github.com/repos/org/repo/releases/latest",
                "release_url": "http://127.0.0.1:8765/releases",
            },
            {
                "api_url": "http://127.0.0.1:8765/api/releases/latest",
                "release_url": "https://github.com/org/repo/releases",
            },
            # Two local test servers never mix either.
            {
                "api_url": "http://192.168.0.10:8765/api/releases/latest",
                "release_url": "http://192.168.0.11:8765/releases",
            },
            {
                "api_url": "http://192.168.0.10:8765/api/releases/latest",
                "release_url": "http://192.168.0.10:8766/releases",
            },
        ):
            _, update = self.check(self.write_source(source))
            self.assertIn("올바르지", update["message"])

    def test_same_version_missing_release_and_broken_answer(self):
        _, update = self.check(self.serve(APPLICATION_VERSION))
        self.assertEqual(update["state"], "current")
        _, update = self.check(self.serve(mode="none"))
        self.assertEqual(
            (update["state"], update["message"]),
            ("idle", "아직 공개된 배포가 없습니다."),
        )
        _, update = self.check(self.serve(mode="invalid"))
        self.assertEqual((update["state"], update["retry"]), ("error", "check"))

    def test_newer_release_offers_install_only_from_an_installed_runtime(self):
        source = self.serve()
        _, update = self.check(source)
        self.assertEqual(update["state"], "available")
        self.assertEqual(update["version"], "9.9.9")
        self.assertFalse(update["can_install"])
        self.assertIn("설치판에서만", update["message"])
        self.assertTrue(update["page_url"].endswith("/releases/tag/v9.9.9"))
        with self.installed():
            _, update = self.check(source)
            self.assertTrue(update["can_install"])
            _, update = self.check(self.serve(mode="no-assets"))
            self.assertFalse(update["can_install"])
            self.assertIn("배포 페이지", update["message"])

    def test_verified_download_starts_the_installer_and_quits(self):
        with (
            self.installed(),
            patch.object(update_check, "installer_language", return_value="en"),
            patch.object(
                update_check.QProcess, "startDetached", return_value=(True, 1)
            ) as start,
            patch.object(update_check.QCoreApplication, "quit") as quit_app,
            patch.object(update_check, "INSTALL_NOTICE_MS", 200),
        ):
            service, _ = self.check(self.serve())
            progress = []
            service.changed.connect(lambda: progress.append(service.snapshot()))
            service.download()
            update = self.wait_while(service, "downloading")
            # A full bar and the notice show before Setup starts and the app quits.
            self.assertEqual(update["state"], "installing", update["message"])
            self.assertEqual(update["message"], update_check.INSTALLING_MESSAGE)
            self.assertEqual((update["received"], update["total"]), (300_000, 300_000))
            start.assert_not_called()
            quit_app.assert_not_called()
            QTest.qWait(400)
            installer = self.updates / INSTALLER_NAME
            self.assertEqual(installer.read_bytes(), self.installer.read_bytes())
            self.assertEqual(list(self.updates.glob("*.part")), [])
            start.assert_called_once_with(
                str(installer),
                ["/VERYSILENT", "/RELAUNCH=1", "/LANG=en"],
                str(self.updates),
            )
            quit_app.assert_called_once()
            self.assertEqual(progress[0]["state"], "downloading")
            self.assertEqual(progress[0]["total"], 300_000)

    def assert_download_refused(self, service, message):
        with patch.object(update_check.QProcess, "startDetached") as start:
            service.download()
            update = self.wait_while(service, "downloading")
        self.assertEqual((update["state"], update["retry"]), ("error", "download"))
        self.assertIn(message, update["message"])
        start.assert_not_called()
        self.assertEqual(list(self.updates.glob("*")), [])
        # The same release can be tried again.
        self.assertTrue(service.snapshot()["can_install"])

    def test_mismatched_redirected_stalled_or_oversized_downloads_never_run(self):
        with self.installed():
            service, _ = self.check(self.serve(mode="bad-hash"))
            self.assert_download_refused(service, "배포와 달라")
            service, _ = self.check(self.serve(mode="redirect-elsewhere"))
            self.assert_download_refused(service, "허용하지 않은 주소")
            service, _ = self.check(self.serve())
            service.release = dict(service.release, size=1000)
            self.assert_download_refused(service, "배포와 달라")
            with patch.object(update_check, "STALL_TIMEOUT_MS", 300):
                service, _ = self.check(self.serve(mode="slow-download"))
                self.assert_download_refused(service, "오래 멈춰")

    def test_cancel_discards_the_partial_download(self):
        with self.installed():
            service, _ = self.check(self.serve(mode="slow-download"))
            service.download()
            waited = 0
            while service.snapshot()["received"] == 0 and waited < 5000:
                QTest.qWait(10)
                waited += 10
            self.assertGreater(service.snapshot()["received"], 0)
            service.cancel()
            update = self.wait_while(service, "downloading")
        self.assertEqual(update["state"], "available")
        self.assertEqual(list(self.updates.glob("*")), [])

    def test_download_needs_an_installable_release(self):
        service, _ = self.check(self.serve())
        service.download()
        self.assertEqual(service.state, "available")
        self.assertFalse(self.updates.exists())

    def test_leftover_installers_are_removed_and_other_files_stay(self):
        self.updates.mkdir()
        for name in (
            "WatchedKettle-0.0.1-public-unsigned-setup.exe",
            f"WatchedKettle-{APPLICATION_VERSION}-public-unsigned-setup.exe",
            "WatchedKettle-99.0.0-public-unsigned-setup.exe.part",
            "WatchedKettle-99.0.0-public-update-test-unsigned-setup.exe",
            "notes.txt",
        ):
            (self.updates / name).write_bytes(b"x")
        self.service(self.root / "missing.json").remove_finished_downloads()
        self.assertEqual(
            sorted(entry.name for entry in self.updates.iterdir()), ["notes.txt"]
        )


class ServeUpdateTestTests(unittest.TestCase):
    def test_installer_version_comes_from_the_file_name(self):
        self.assertEqual(
            serve_update_test.installer_version(
                "dist/WatchedKettle-0.15.2-public-update-test-unsigned-setup.exe"
            ),
            "0.15.2",
        )
        self.assertEqual(
            serve_update_test.installer_version("setup.exe"), APPLICATION_VERSION
        )

    def test_release_lists_assets_that_redirect_to_downloads(self):
        with TemporaryDirectory() as directory:
            installer = (
                Path(directory) / "WatchedKettle-9.9.9-public-unsigned-setup.exe"
            )
            installer.write_bytes(b"setup")
            server = serve_update_test.serve(0, installer)
            try:
                base = server.base_url
                row = json.loads(
                    urlopen(base + "/api/releases/latest", timeout=5).read()
                )
                assets = {asset["name"]: asset for asset in row["assets"]}
                self.assertEqual(assets[installer.name]["size"], 5)
                checksum = urlopen(
                    assets[installer.name + ".sha256"]["browser_download_url"],
                    timeout=5,
                ).read()
                digest = hashlib.sha256(b"setup").hexdigest().upper()
                self.assertEqual(checksum, f"{digest}  {installer.name}\n".encode())
                download = urlopen(
                    assets[installer.name]["browser_download_url"], timeout=5
                )
                self.assertEqual(download.url, f"{base}/assets/{installer.name}")
                self.assertEqual(download.read(), b"setup")
                page = urlopen(base + "/releases/tag/v9.9.9", timeout=5).read()
                self.assertIn(f"/download/{installer.name}".encode(), page)
                for path in ("/download/other.exe", "/assets/../pyproject.toml"):
                    with self.assertRaises(HTTPError) as caught:
                        urlopen(base + path, timeout=5)
                    self.assertEqual(caught.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()

    def test_announced_version_renames_the_assets(self):
        # Lets an installed build "upgrade" to --version 9.9.9 with its own
        # installer; the app only accepts assets named for the new version.
        with TemporaryDirectory() as directory:
            installer = (
                Path(directory)
                / f"WatchedKettle-{APPLICATION_VERSION}-public-update-test-unsigned-setup.exe"
            )
            installer.write_bytes(b"setup")
            server = serve_update_test.serve(0, installer, "9.9.9")
            try:
                names = [asset["name"] for asset in server.assets()]
                renamed = "WatchedKettle-9.9.9-public-update-test-unsigned-setup.exe"
                self.assertEqual(names, [renamed, renamed + ".sha256"])
                self.assertTrue(installer_asset_name(renamed, "9.9.9", "local-test"))
                self.assertTrue(server.checksum.decode().strip().endswith(renamed))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
