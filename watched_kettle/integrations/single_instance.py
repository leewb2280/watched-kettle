"""User-scoped single-instance coordination for the desktop pet."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


DEFAULT_INSTANCE_SERVER_NAME = "watched-kettle-instance-v1"
ACTIVATE_COMMAND = b"show\n"
# Sent by the installer and uninstaller (packaging/windows-installer.iss) so the
# app closes normally before its files change.
QUIT_COMMAND = b"quit\n"
ACK_COMMAND = b"ok\n"


def configured_instance_server_name():
    """Return the endpoint name; measurement runs override it to coexist."""
    return (
        os.environ.get("WATCHED_KETTLE_INSTANCE_SERVER_NAME")
        or DEFAULT_INSTANCE_SERVER_NAME
    )


class SingleInstanceCoordinator(QObject):
    """Keep one pet process and forward later launches to it."""

    activation_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        server_name=DEFAULT_INSTANCE_SERVER_NAME,
        connect_timeout_ms=250,
        parent=None,
    ):
        super().__init__(parent)
        self.server_name = str(server_name)
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.server = None
        self._clients = set()

    def start(self):
        """Return ``True`` for the primary process, otherwise activate it."""
        if self._notify_existing_instance():
            return False

        if self._listen():
            return True

        # A process may have started between the first probe and listen.
        if self._notify_existing_instance():
            return False

        # Failed launches can leave a stale local endpoint behind. Only remove
        # it after two probes have confirmed that no process accepts it.
        QLocalServer.removeServer(self.server_name)
        if self._listen():
            return True
        raise OSError("프로그램 중복 실행 감지용 로컬 서버를 시작하지 못했습니다.")

    def _listen(self):
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept_connections)
        if not server.listen(self.server_name):
            server.deleteLater()
            return False
        self.server = server
        return True

    def _notify_existing_instance(self):
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(self.connect_timeout_ms):
            socket.abort()
            return False
        socket.write(ACTIVATE_COMMAND)
        socket.flush()
        socket.waitForBytesWritten(self.connect_timeout_ms)
        socket.waitForReadyRead(self.connect_timeout_ms)
        socket.readAll()
        socket.disconnectFromServer()
        return True

    def _accept_connections(self):
        while self.server is not None and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._clients.add(socket)
            socket.readyRead.connect(lambda socket=socket: self._read_client(socket))
            socket.disconnected.connect(
                lambda socket=socket: self._release_client(socket)
            )
            self._read_client(socket)

    def _read_client(self, socket):
        commands = bytes(socket.readAll()).splitlines()
        if QUIT_COMMAND.strip() in commands:
            socket.write(ACK_COMMAND)
            socket.flush()
            self.quit_requested.emit()
        elif ACTIVATE_COMMAND.strip() in commands:
            socket.write(ACK_COMMAND)
            socket.flush()
            self.activation_requested.emit()

    def _release_client(self, socket):
        self._clients.discard(socket)
        socket.deleteLater()

    def close(self):
        for socket in tuple(self._clients):
            # A quit request arrives while the installer is still connected;
            # drop the callbacks so a late disconnect never reaches a freed socket.
            socket.readyRead.disconnect()
            socket.disconnected.disconnect()
            socket.abort()
            socket.deleteLater()
        self._clients.clear()
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
