"""Thread-safe, bounded in-memory log capture for service diagnostics."""

import collections
import os
import re
import sys
import threading
from typing import Any

LOG_CAPACITY = 1000
MAX_LOG_LINE_LENGTH = 4096
_DEFAULT_LINES = 50

_log_buffer: collections.deque[tuple[int, str]] = collections.deque(
    maxlen=LOG_CAPACITY
)
_log_lock = threading.Lock()
_next_log_id = 1
_capture_lock = threading.Lock()
_original_stdout: Any = None
_original_stderr: Any = None
_capture_refs = 0

_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)


def _redact(text: str) -> str:
    """Remove configured and commonly formatted API credentials."""
    redacted = text
    for env_name in ("VISION_API_KEY", "TRANSLATE_API_KEY"):
        value = os.environ.get(env_name, "")
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    redacted = _BEARER_RE.sub(r"\1[REDACTED]", redacted)
    return _SK_KEY_RE.sub("[REDACTED]", redacted)


def append_log(text: str) -> None:
    """Append one or more sanitized lines to the bounded log buffer."""
    global _next_log_id
    stripped = text.rstrip("\r\n")
    if not stripped:
        return
    for raw_line in stripped.splitlines():
        line = _redact(raw_line.rstrip())[:MAX_LOG_LINE_LENGTH]
        if not line:
            continue
        with _log_lock:
            _log_buffer.append((_next_log_id, line))
            _next_log_id += 1


def snapshot_logs(lines: int = 500, after: int | None = None) -> dict[str, Any]:
    """Return a bounded recent or cursor-based snapshot of captured logs."""
    try:
        limit = max(1, min(int(lines), LOG_CAPACITY))
    except (TypeError, ValueError):
        limit = 500
    with _log_lock:
        records = list(_log_buffer)
        next_id = _next_log_id

    cursor = records[-1][0] if records else next_id - 1
    truncated = False
    if after is None:
        selected = records[-limit:]
        truncated = False
    else:
        try:
            after_int = int(after) if after is not None else 0
        except (TypeError, ValueError):
            after_int = 0
        oldest_id = records[0][0] if records else next_id
        truncated = after_int < oldest_id - 1
        selected = [record for record in records if record[0] > after_int]
        if len(selected) > limit:
            selected = selected[-limit:]
            truncated = True

    return {
        "logs": [{"id": record_id, "text": text} for record_id, text in selected],
        "cursor": cursor,
        "truncated": truncated,
        "capacity": LOG_CAPACITY,
    }


def get_recent_logs(lines: int = _DEFAULT_LINES) -> list[str]:
    """Return recent lines in the legacy Decky RPC shape."""
    try:
        limit = max(0, min(int(lines), LOG_CAPACITY))
    except (TypeError, ValueError):
        limit = _DEFAULT_LINES
    if limit == 0:
        return []
    with _log_lock:
        return [text for _, text in list(_log_buffer)[-limit:]]


def clear_logs() -> None:
    """Clear captured records while preserving monotonically increasing IDs."""
    with _log_lock:
        _log_buffer.clear()


class TeeOutput:
    """Duplicate writes to the original stream and the shared log buffer."""

    def __init__(self, original: Any) -> None:
        self._original = original

    def write(self, text: str) -> int:
        result = self._original.write(text)
        append_log(text)
        return result

    def flush(self) -> None:
        self._original.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def install_capture() -> None:
    """Install process-wide stdout/stderr tee capture, reference counted."""
    global _original_stdout, _original_stderr, _capture_refs
    with _capture_lock:
        if _capture_refs == 0:
            _original_stdout = sys.stdout
            _original_stderr = sys.stderr
            sys.stdout = TeeOutput(_original_stdout)  # type: ignore[assignment]
            sys.stderr = TeeOutput(_original_stderr)  # type: ignore[assignment]
        _capture_refs += 1


def restore_capture() -> None:
    """Release one capture reference and restore streams at zero."""
    global _original_stdout, _original_stderr, _capture_refs
    with _capture_lock:
        if _capture_refs == 0:
            return
        _capture_refs -= 1
        if _capture_refs == 0:
            sys.stdout = _original_stdout
            sys.stderr = _original_stderr
            _original_stdout = None
            _original_stderr = None
