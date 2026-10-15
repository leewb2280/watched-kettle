"""User-requested update: release lookup, verified download, installer start.

Every step starts from the settings window's buttons; nothing checks or
downloads in the background. The downloaded installer runs only when its
SHA-256 matches the release's checksum file, then upgrades silently and starts
the app again (packaging/windows-installer.iss, /RELAUNCH=1).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from watched_kettle.application.logging import log_event
from watched_kettle.application.paths import resolve_data_root
from watched_kettle.branding import APPLICATION_ID, APPLICATION_VERSION

CHECK_TIMEOUT_MS = 8000
# A download stops only when no bytes arrive for this long.
STALL_TIMEOUT_MS = 30000
PROGRESS_INTERVAL_SECONDS = 0.25
# The full progress bar and the "back soon" notice stay this long before the
# app quits; the installer then runs with no window of its own.
INSTALL_NOTICE_MS = 1500
INSTALLING_MESSAGE = "업데이트를 설치하고 곧 다시 켜집니다."
MAX_RELEASE_BYTES = 256 * 1024
MAX_CHECKSUM_BYTES = 1024
MAX_INSTALLER_BYTES = 1 << 30
# Release asset links on github.com redirect to these download hosts.
OFFICIAL_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)
# The local test channel also reads a test server on the same private network,
# so another PC there can try updates. IP literals only, never names.
LOCAL_TEST_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in ("127.0.0.1/32", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
INSTALLER_NAME = re.compile(r"WatchedKettle-(\d+\.\d+\.\d+)-[a-z-]+-setup\.exe")
USER_AGENT = b"WatchedKettle-update-check"
IDLE_MESSAGE = "업데이트는 직접 확인할 때만 조회합니다."
FAILURE_MESSAGES = {
    "timeout": "내려받기가 오래 멈춰 있어 중단했습니다.",
    "redirect": "허용하지 않은 주소로 연결되어 내려받기를 중단했습니다.",
    "too_large": "내려받은 파일이 배포와 달라 설치하지 않았습니다. 다시 시도해 주세요.",
    "write": "설치 파일을 저장하지 못했습니다.",
}


def update_source_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "UPDATE_SOURCE.json"
    # Source runs can point at scripts/serve_update_test.py's address file.
    override = os.environ.get("WATCHED_KETTLE_UPDATE_SOURCE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "UPDATE_SOURCE.json"


def local_test_host(host):
    """Whether ``host`` is an address the local test channel may read."""
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return any(address in network for network in LOCAL_TEST_NETWORKS)


def release_url_kind(value, *, api=False):
    """Return "official", "local-test", or None for an address never used.

    Official builds read GitHub Releases over HTTPS. Builds made with
    build_windows.ps1 -UpdateTestPort read scripts/serve_update_test.py on
    this machine or, with -UpdateTestHost, on a PC of the same private network.
    """
    url = QUrl(value)
    if not url.isValid() or url.userInfo():
        return None
    official_host = "api.github.com" if api else "github.com"
    if url.scheme() == "https" and url.host() == official_host and url.port() == -1:
        return "official"
    if url.scheme() == "http" and local_test_host(url.host()) and url.port() > 0:
        return "local-test"
    return None


def download_url_allowed(value, kind, port=-1, host="127.0.0.1"):
    """Whether a release asset, or a redirect while fetching one, may be read.

    The local test channel downloads only from the test server it asked.
    """
    url = QUrl(value)
    if not url.isValid() or url.userInfo():
        return False
    if kind == "official":
        return (
            url.scheme() == "https"
            and url.host() in OFFICIAL_DOWNLOAD_HOSTS
            and url.port() == -1
        )
    if kind == "local-test":
        return url.scheme() == "http" and url.host() == host and url.port() == port
    return False


def installer_asset_name(name, version, kind):
    """Whether ``name`` is the installer this update channel may run.

    Official releases carry the Public installer only. The local test channel
    also offers the invitation and -update-test installers it builds.
    """
    v = re.escape(version)
    if kind == "official":
        pattern = rf"WatchedKettle-{v}-public(?:-unsigned)?-setup\.exe"
    else:
        pattern = (
            rf"WatchedKettle-{v}-(?:public|private-pets)"
            r"(?:-update-test)?(?:-unsigned)?-setup\.exe"
        )
    return re.fullmatch(pattern, name) is not None


def installed_app_root(executable=None):
    """The install folder when running from an installed runtime, else None.

    The installer lays out {app}\\runtime\\<edition>\\WatchedKettle.exe beside
    the edition marker the launcher reads, with its uninstaller in {app}.
    Source runs and unpacked ZIP bundles are not upgraded by the installer.
    """
    if executable is None:
        if not getattr(sys, "frozen", False):
            return None
        executable = sys.executable
    runtime = Path(executable).resolve().parent.parent
    app = runtime.parent
    if (
        runtime.name.casefold() == "runtime"
        and (runtime / "edition").is_file()
        and any(app.glob("unins*.exe"))
    ):
        return app
    return None


def installer_language():
    """The language the user chose in the installer (HKCU\\Software\\<AppId>)."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"Software\{APPLICATION_ID}"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Language")
    except (ImportError, OSError):
        return "ko"
    return value if value in ("ko", "en") else "ko"


def _version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def _parse_checksum(payload, name):
    """Return the digest from a ``<HEX>  <name>`` checksum file, or None."""
    try:
        text = payload.decode("ascii").strip()
    except UnicodeError:
        return None
    match = re.fullmatch(r"([0-9A-Fa-f]{64})[ \t]+\*?(\S+)", text)
    if match is None or match.group(2) != name:
        return None
    return match.group(1).lower()


class UpdateService(QObject):
    """State behind the settings window's version and update row."""

    changed = Signal()

    def __init__(self, source_path=None, updates_dir=None, parent=None):
        super().__init__(parent)
        self.source_path = Path(source_path or update_source_path())
        self._updates_dir = Path(updates_dir) if updates_dir else None
        self.manager = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.reply = None
        self.release_url = ""
        self.release = None
        self._kind = None
        self._host = ""
        self._port = -1
        self._abort_reason = ""
        self._download = None
        self._last_progress = 0.0
        self._state = dict(
            state="idle",
            version="",
            page_url="",
            received=0,
            total=0,
            message=IDLE_MESSAGE,
            can_install=False,
            retry="",
        )
        if installed_app_root() is not None:
            # Installers left by an earlier update are not needed any more.
            QTimer.singleShot(0, self.remove_finished_downloads)

    # ---- state -------------------------------------------------------------

    def snapshot(self):
        return dict(self._state)

    @property
    def state(self):
        return self._state["state"]

    @property
    def page_url(self):
        return self._state["page_url"]

    @property
    def updates_dir(self):
        if self._updates_dir is None:
            self._updates_dir = resolve_data_root() / "updates"
        return self._updates_dir

    def _set(self, state, message, **fields):
        self._state = dict(
            self._state, state=state, message=message, received=0, total=0, retry=""
        )
        self._state.update(fields)
        self.changed.emit()

    def _settle(self, state, message, **fields):
        """End a check without a release to install."""
        self.release = None
        self._set(state, message, version="", page_url="", can_install=False, **fields)

    # ---- check -------------------------------------------------------------

    def check(self):
        if self.reply is not None or self.state in ("downloading", "installing"):
            return
        try:
            source = json.loads(self.source_path.read_text(encoding="utf-8"))
            api_url = str(source["api_url"])
            release_url = str(source["release_url"])
        except (OSError, ValueError, KeyError, TypeError):
            self._settle("idle", "공식 업데이트 주소가 아직 설정되지 않았습니다.")
            return
        kind = release_url_kind(api_url, api=True)
        api, page = QUrl(api_url), QUrl(release_url)
        if (
            kind is None
            or kind != release_url_kind(release_url)
            or (
                kind == "local-test"
                and (api.host(), api.port()) != (page.host(), page.port())
            )
        ):
            self._settle("idle", "업데이트 주소 설정이 올바르지 않습니다.")
            return
        self.release_url = release_url
        self._kind = kind
        self._host = api.host()
        self._port = api.port()
        self._settle("checking", "확인하는 중…")
        self.reply = self._get(api_url, api=True)
        self.reply.finished.connect(self._read_release)
        self.timer.start(CHECK_TIMEOUT_MS)

    def _get(self, url, *, api=False):
        """GET that follows a redirect only to an address this channel allows."""
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.UserVerifiedRedirectPolicy,
        )
        reply = self.manager.get(request)

        def redirected(target):
            if api:
                # A renamed repository redirects to the API under its new name.
                allowed = release_url_kind(target, api=True) == self._kind and (
                    self._kind == "official"
                    or (QUrl(target).host(), QUrl(target).port())
                    == (self._host, self._port)
                )
            else:
                allowed = download_url_allowed(
                    target, self._kind, self._port, self._host
                )
            if allowed:
                reply.redirectAllowed.emit()
            else:
                self._abort_reason = "redirect"
                reply.abort()

        reply.redirected.connect(redirected)
        return reply

    def _timeout(self):
        if self.reply is not None:
            self._abort_reason = self._abort_reason or "timeout"
            self.reply.abort()

    def _read_release(self):
        reply, self.reply = self.reply, None
        self.timer.stop()
        self._abort_reason = ""
        if reply is None:
            return
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                # GitHub answers 404 until the repository has a published release.
                self._settle("idle", "아직 공개된 배포가 없습니다.")
                return
            # PySide6 enum members are always truthy, NoError included.
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._settle(
                    "error", "업데이트 정보를 확인하지 못했습니다.", retry="check"
                )
                return
            payload = bytes(reply.read(MAX_RELEASE_BYTES + 1))
            if len(payload) > MAX_RELEASE_BYTES:
                raise ValueError("release_response_too_large")
            self._accept_release(json.loads(payload))
        except (ValueError, TypeError, UnicodeError):
            self._settle("error", "업데이트 응답을 확인할 수 없습니다.", retry="check")
        finally:
            reply.deleteLater()

    def _accept_release(self, row):
        if not isinstance(row, dict):
            raise ValueError("invalid_release_response")
        tag = str(row.get("tag_name") or "")
        latest = _version(tag)
        page = str(row.get("html_url") or "")
        if latest is None or not page.startswith(self.release_url.rstrip("/") + "/"):
            raise ValueError("invalid_release_response")
        current = _version(APPLICATION_VERSION)
        if current is not None and latest <= current:
            self._settle("current", "최신 버전을 사용 중입니다.")
            return
        version = tag.removeprefix("v")
        self.release = self._release_assets(row.get("assets"), version)
        if self.release is None:
            can_install = False
            message = f"v{version} 버전이 나왔습니다. 배포 페이지에서 받아 주세요."
        elif installed_app_root() is None:
            can_install = False
            message = f"v{version} 버전이 나왔습니다. 앱 안 업데이트는 설치판에서만 할 수 있습니다."
        else:
            can_install = True
            message = f"v{version} 버전을 받을 수 있습니다."
        self._set(
            "available",
            message,
            version=version,
            page_url=page,
            can_install=can_install,
        )

    def _release_assets(self, assets, version):
        """The installer and its checksum file this channel may use, or None."""
        if not isinstance(assets, list):
            return None
        by_name = {}
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if name and download_url_allowed(url, self._kind, self._port, self._host):
                by_name[name] = (url, asset.get("size"))
        installers = sorted(
            (
                name
                for name in by_name
                if installer_asset_name(name, version, self._kind)
                and name + ".sha256" in by_name
            ),
            # The Public installer when the test channel offers several.
            key=lambda name: ("-public-" not in name, name),
        )
        if not installers:
            return None
        name = installers[0]
        url, size = by_name[name]
        if not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
            return None
        return dict(
            name=name, url=url, size=size, checksum_url=by_name[name + ".sha256"][0]
        )

    # ---- download ----------------------------------------------------------

    def download(self):
        if self.state not in ("available", "error") or self.reply is not None:
            return
        if self.release is None or installed_app_root() is None:
            return
        self._abort_reason = ""
        self._last_progress = 0.0
        self._download = dict(digest=None, hash=hashlib.sha256(), file=None, part=None)
        self._set("downloading", "내려받는 중…", total=self.release["size"])
        self.reply = self._get(self.release["checksum_url"])
        self.reply.finished.connect(self._read_checksum)
        self.timer.start(STALL_TIMEOUT_MS)

    def cancel(self):
        if self.state == "downloading" and self.reply is not None:
            self._abort_reason = "cancel"
            self.reply.abort()

    def _read_checksum(self):
        reply, self.reply = self.reply, None
        self.timer.stop()
        try:
            if self._download_stopped(reply):
                return
            payload = bytes(reply.read(MAX_CHECKSUM_BYTES + 1))
            digest = None
            if len(payload) <= MAX_CHECKSUM_BYTES:
                digest = _parse_checksum(payload, self.release["name"])
            if digest is None:
                self._fail_download("배포의 확인용 체크섬을 읽지 못했습니다.")
                return
            self._download["digest"] = digest
            self._start_installer_download()
        finally:
            reply.deleteLater()

    def _start_installer_download(self):
        try:
            self.updates_dir.mkdir(parents=True, exist_ok=True)
            part = self.updates_dir / (self.release["name"] + ".part")
            self._download["part"] = part
            self._download["file"] = part.open("wb")
        except OSError:
            self._fail_download("내려받을 폴더를 준비하지 못했습니다.")
            return
        self.reply = self._get(self.release["url"])
        self.reply.readyRead.connect(self._write_chunk)
        self.reply.finished.connect(self._finish_installer)
        self.timer.start(STALL_TIMEOUT_MS)

    def _write_chunk(self, reply=None):
        reply = reply or self.reply
        if reply is None or self._download is None or self._abort_reason:
            return
        chunk = bytes(reply.readAll())
        if not chunk:
            return
        received = self._state["received"] + len(chunk)
        if received > self.release["size"]:
            self._abort_reason = "too_large"
            reply.abort()
            return
        try:
            self._download["file"].write(chunk)
        except OSError:
            self._abort_reason = "write"
            reply.abort()
            return
        self._download["hash"].update(chunk)
        self._state = dict(self._state, received=received)
        self.timer.start(STALL_TIMEOUT_MS)
        now = time.monotonic()
        if now - self._last_progress >= PROGRESS_INTERVAL_SECONDS:
            self._last_progress = now
            self.changed.emit()

    def _finish_installer(self):
        reply, self.reply = self.reply, None
        self.timer.stop()
        try:
            if self._download_stopped(reply):
                return
            # Bytes that arrived together with the finished signal.
            self._write_chunk(reply)
            if self._abort_reason:
                self._fail_download(self._failure_message())
                return
            self._verify_and_install()
        finally:
            reply.deleteLater()

    def _verify_and_install(self):
        download = self._download
        try:
            download["file"].close()
        except OSError:
            self._fail_download(FAILURE_MESSAGES["write"])
            return
        if (
            self._state["received"] != self.release["size"]
            or download["hash"].hexdigest() != download["digest"]
        ):
            self._fail_download(FAILURE_MESSAGES["too_large"])
            return
        installer = download["part"].with_suffix("")
        try:
            download["part"].replace(installer)
        except OSError:
            self._fail_download(FAILURE_MESSAGES["write"])
            return
        self._download = None
        # A full bar and the notice first; quitting at once hid both.
        size = self.release["size"]
        self._set("installing", INSTALLING_MESSAGE, received=size, total=size)
        QTimer.singleShot(INSTALL_NOTICE_MS, lambda: self.install(installer))

    def _download_stopped(self, reply):
        """Handle a cancelled or failed reply; True when the download ended."""
        if self._abort_reason == "cancel":
            self._discard_download()
            self._abort_reason = ""
            self._set(
                "available", f"v{self._state['version']} 버전을 받을 수 있습니다."
            )
            return True
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if (
            self._abort_reason
            or reply.error() != QNetworkReply.NetworkError.NoError
            or status != 200
        ):
            self._fail_download(self._failure_message())
            return True
        return False

    def _failure_message(self):
        return FAILURE_MESSAGES.get(
            self._abort_reason, "설치 파일을 내려받지 못했습니다."
        )

    def _fail_download(self, message):
        self._discard_download()
        self._abort_reason = ""
        self._set("error", message, retry="download")

    def _discard_download(self):
        download, self._download = self._download, None
        if not download:
            return
        try:
            if download["file"] is not None:
                download["file"].close()
            if download["part"] is not None:
                download["part"].unlink(missing_ok=True)
        except OSError:
            pass

    # ---- install -----------------------------------------------------------

    def install(self, installer):
        """Start the verified installer and quit so it can replace the app.

        /VERYSILENT shows no Setup window, as app updates usually do; Setup
        still reports a failure in a message box, and /RELAUNCH=1 starts the
        app again when it finishes.
        """
        arguments = ["/VERYSILENT", "/RELAUNCH=1", f"/LANG={installer_language()}"]
        started = QProcess.startDetached(
            str(installer), arguments, str(installer.parent)
        )
        if isinstance(started, tuple):
            started = started[0]
        if not started:
            self._set("error", "설치 프로그램을 시작하지 못했습니다.", retry="download")
            return
        log_event(
            "application.update", "install_started", version=self._state["version"]
        )
        # The same quit as the tray's, so the installer finds every process gone.
        QTimer.singleShot(0, QCoreApplication.quit)

    def remove_finished_downloads(self):
        """Delete installers and partial downloads an earlier update left.

        Every update downloads its installer again, so none is worth keeping:
        a finished one already ran, and one that never ran is checked anew.
        """
        try:
            entries = list(self.updates_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            name = entry.name.removesuffix(".part")
            if (
                INSTALLER_NAME.fullmatch(name)
                and entry.is_file()
                and not entry.is_symlink()
            ):
                try:
                    entry.unlink()
                except OSError:
                    pass
