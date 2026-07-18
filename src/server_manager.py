"""Server lifecycle manager — runs the HTTP server in a daemon thread."""

import collections
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from typing import Any

from . import config, http_server

# ── Log ring buffer ──────────────────────────────────────────────────

_log_buffer: collections.deque[str] = collections.deque(maxlen=200)


class _TeeOutput:
    """Duplicate writes to the original stream *and* a ring buffer."""

    def __init__(self, original: Any) -> None:
        self._original = original

    def write(self, s: str) -> int:
        ret = self._original.write(s)
        stripped = s.rstrip("\r\n")
        if stripped:
            for line in stripped.split("\n"):
                _log_buffer.append(line.rstrip())
        return ret

    def flush(self) -> None:
        self._original.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def get_recent_logs(lines: int = 50) -> list[str]:
    """Return the most recent *lines* from the ring buffer."""
    count = min(lines, len(_log_buffer))
    if count == 0:
        return []
    result = list(_log_buffer)[-count:]
    return result


# ── Server Manager ───────────────────────────────────────────────────


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
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def start(self) -> None:
        if self.running:
            return
        # Redirect stdout/stderr to ring buffer
        sys.stdout = _TeeOutput(self._original_stdout)  # type: ignore[assignment]
        sys.stderr = _TeeOutput(self._original_stderr)  # type: ignore[assignment]
        self.running = True
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        self.running = False
        self._server.shutdown()
        self._thread.join(timeout=timeout)
        # Restore original stdout/stderr
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

    def _serve(self) -> None:
        try:
            self._server.serve_forever()
        except Exception:
            pass
        finally:
            self.running = False
