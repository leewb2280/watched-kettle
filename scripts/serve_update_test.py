"""Local stand-in for GitHub Releases, for testing updates; never product input.

Bundles built with ``build_windows.ps1 -UpdateTestPort <port>`` (or a source run
with ``WATCHED_KETTLE_UPDATE_SOURCE`` set from ``--print-source``) ask this
server for the latest release. It answers the way the GitHub API does: the
release lists the installer and its ``.sha256`` file as assets, and asset links
redirect to a separate download path. It listens on 127.0.0.1 unless
``--host`` names this PC's private network address, so another PC on the same
network can update a bundle built with ``-UpdateTestHost`` set to that address.
"""

import argparse
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

from watched_kettle.application.update_check import local_test_host
from watched_kettle.branding import APPLICATION_VERSION

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MODES = {
    "ok": "a release with the installer and its checksum",
    "none": "no release yet (404)",
    "invalid": "a broken release answer",
    "slow": "a release answer slower than the check timeout",
    "no-assets": "a release without installer assets (page link only)",
    "bad-hash": "a checksum that does not match the installer",
    "slow-download": "an installer download that stops halfway",
    "redirect-elsewhere": "asset links that redirect to another address",
}
API_PATH = "/api/releases/latest"
RELEASES_PATH = "/releases"
# Longer than the update check's 8 second timeout.
SLOW_SECONDS = 10
# Longer than the update download's 30 second stall timeout.
STALL_SECONDS = 60


def installer_version(installer):
    match = re.match(r"WatchedKettle-(\d+\.\d+\.\d+)-", Path(installer).name)
    return match.group(1) if match else APPLICATION_VERSION


def update_source(port, host=HOST):
    base = f"http://{host}:{port}"
    return {"api_url": base + API_PATH, "release_url": base + RELEASES_PATH}


class ReleaseServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, installer, version, mode, host=HOST):
        self.host = host
        self.installer = Path(installer) if installer else None
        self.version = version
        self.mode = mode
        self.asset_name = ""
        self.checksum = b""
        if self.installer is not None:
            # Published under the announced version, so --version 9.9.9 lets an
            # installed build "upgrade" with the same installer.
            self.asset_name = re.sub(
                r"^WatchedKettle-\d+\.\d+\.\d+-",
                f"WatchedKettle-{version}-",
                self.installer.name,
            )
            data = b"tampered" if mode == "bad-hash" else self.installer.read_bytes()
            digest = hashlib.sha256(data).hexdigest().upper()
            self.checksum = f"{digest}  {self.asset_name}\n".encode("ascii")
        super().__init__((host, port), ReleaseHandler)

    def handle_error(self, request, client_address):
        # The app gives up on a slow answer and closes the connection.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)

    @property
    def base_url(self):
        return f"http://{self.host}:{self.server_address[1]}"

    @property
    def page_path(self):
        return f"{RELEASES_PATH}/tag/v{self.version}"

    @property
    def checksum_name(self):
        return self.asset_name + ".sha256"

    def assets(self):
        if self.installer is None or self.mode == "no-assets":
            return []
        return [
            {
                "name": name,
                "size": size,
                "browser_download_url": f"{self.base_url}/download/{name}",
            }
            for name, size in (
                (self.asset_name, self.installer.stat().st_size),
                (self.checksum_name, len(self.checksum)),
            )
        ]


class ReleaseHandler(BaseHTTPRequestHandler):
    server: ReleaseServer

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        names = {asset["name"] for asset in self.server.assets()}
        if path == API_PATH:
            self._latest()
        elif path == self.server.page_path:
            self._page()
        elif path.startswith("/download/") and path[10:] in names:
            self._redirect(path[10:])
        elif path.startswith("/assets/") and path[8:] in names:
            self._asset(path[8:])
        else:
            self._send(404, "application/json", b'{"message":"Not Found"}')

    def _latest(self):
        mode = self.server.mode
        if mode == "none":
            self._send(404, "application/json", b'{"message":"Not Found"}')
            return
        if mode == "invalid":
            self._send(200, "application/json", b'{"tag_name": ')
            return
        if mode == "slow":
            time.sleep(SLOW_SECONDS)
        row = {
            "tag_name": f"v{self.server.version}",
            "html_url": self.server.base_url + self.server.page_path,
            "assets": self.server.assets(),
        }
        self._send(200, "application/json", json.dumps(row).encode("utf-8"))

    def _page(self):
        links = "".join(
            f'<li><a href="/download/{html.escape(asset["name"])}">'
            f"{html.escape(asset['name'])}</a> ({asset['size']:,} bytes)</li>"
            for asset in self.server.assets()
        )
        version = html.escape(self.server.version)
        page = (
            '<!doctype html><meta charset="utf-8">'
            f"<title>Watched Kettle v{version} (시험)</title>"
            f"<h1>Watched Kettle v{version}</h1>"
            "<p>로컬 업데이트 시험 서버의 배포 페이지입니다.</p>"
            + (f"<ul>{links}</ul>" if links else "<p>첨부 파일이 없습니다.</p>")
        )
        self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))

    def _redirect(self, name):
        # GitHub sends asset downloads to a separate host; another port stands
        # in for a host the app does not allow.
        if self.server.mode == "redirect-elsewhere":
            port = self.server.server_address[1] + 1
            target = f"http://{self.server.host}:{port}/assets/{name}"
        else:
            target = f"{self.server.base_url}/assets/{name}"
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _asset(self, name):
        if name == self.server.checksum_name:
            self._send(200, "application/octet-stream", self.server.checksum)
            return
        data = self.server.installer.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        if self.server.mode == "slow-download":
            self.wfile.write(data[: len(data) // 2])
            self.wfile.flush()
            time.sleep(STALL_SECONDS)
            return
        self.wfile.write(data)

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(format % args)


def serve(port, installer=None, version=None, mode="ok", host=HOST):
    """Start the server on a background thread and return it."""
    version = version or (
        installer_version(installer) if installer else APPLICATION_VERSION
    )
    server = ReleaseServer(port, installer, version, mode, host)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="modes: "
        + "; ".join(f"{name} = {text}" for name, text in MODES.items()),
    )
    parser.add_argument("--installer", type=Path, help="setup.exe offered for download")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--host",
        default=HOST,
        help="address to listen on and announce: 127.0.0.1 (default) or this "
        "PC's private network IPv4 address, for a bundle built with "
        "-UpdateTestHost",
    )
    parser.add_argument(
        "--version", help="announced version; defaults to the installer's version"
    )
    parser.add_argument("--mode", choices=sorted(MODES), default="ok")
    parser.add_argument(
        "--print-source",
        action="store_true",
        help="write an address file for WATCHED_KETTLE_UPDATE_SOURCE (source runs)",
    )
    args = parser.parse_args()
    # Request lines show up at once even when the output is piped.
    sys.stdout.reconfigure(line_buffering=True)
    if not local_test_host(args.host):
        parser.error(f"not a loopback or private network IPv4 address: {args.host}")
    if args.installer is not None and not args.installer.is_file():
        parser.error(f"installer not found: {args.installer}")
    server = serve(args.port, args.installer, args.version, args.mode, args.host)
    port = server.server_address[1]
    print(f"Announcing v{server.version} ({args.mode}) at {server.base_url}{API_PATH}")
    if server.installer is not None:
        # Shows which build the app will install, so an older installer
        # left on the command line is easy to spot.
        installer = server.installer.resolve()
        modified = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(installer.stat().st_mtime)
        )
        print(f"Installer: {installer}")
        print(f"  {installer.stat().st_size:,} bytes, built {modified}")
        print(f"  SHA-256 {server.checksum.decode('ascii').split()[0]}")
        print(f"  offered as {server.asset_name}")
    if args.print_source:
        source = (
            Path(tempfile.gettempdir()) / f"watched-kettle-update-source-{port}.json"
        )
        source.write_text(
            json.dumps(update_source(port, server.host)), encoding="utf-8"
        )
        print(f'$env:WATCHED_KETTLE_UPDATE_SOURCE = "{source}"')
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
