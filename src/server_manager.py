"""Server lifecycle manager — runs the HTTP server in a daemon thread."""

import socket
import threading
from http.server import ThreadingHTTPServer

from . import config, http_server
from .log_buffer import get_recent_logs, install_capture, restore_capture


class ServerManager:
    """Wraps a ``ThreadingHTTPServer`` in a daemon thread with clean shutdown."""

    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(
            (config.LISTEN_HOST, config.LISTEN_PORT),
            http_server.TranslationHandler,
        )
        # Set SO_REUSEADDR so restarting doesn't hit TIME_WAIT
        self._server.socket.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self._server.timeout = 1.0  # shutdown() returns within ~1s
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.running = False
        self._capture_installed = False

    def start(self) -> None:
        if self.running:
            return
        install_capture()
        self._capture_installed = True
        self.running = True
        try:
            self._thread.start()
        except Exception:
            self.running = False
            self._release_capture()
            raise

    def stop(self, timeout: float = 5.0) -> None:
        if self.running:
            self.running = False
            self._server.shutdown()
            self._thread.join(timeout=timeout)
        self._release_capture()

    def _release_capture(self) -> None:
        if self._capture_installed:
            restore_capture()
            self._capture_installed = False

    def _serve(self) -> None:
        try:
            self._server.serve_forever()
        except Exception:
            pass
        finally:
            self.running = False
