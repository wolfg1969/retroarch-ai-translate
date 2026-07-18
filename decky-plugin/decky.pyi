"""
Type stubs for the ``decky`` module injected into the Python backend process.

The decky module is provided by Decky Loader's plugin runtime and is NOT
installable via pip.  It is only available when the plugin runs inside the
Decky Loader environment.
"""

import logging
from typing import Any, Callable

# ── Paths ────────────────────────────────────────────────────────────
DECKY_HOME: str
"""Decky's home directory, typically ``/home/deck/homebrew``."""

DECKY_USER_HOME: str
"""The home directory of the user running the plugin, e.g. ``/home/deck``."""

DECKY_PLUGIN_DIR: str
"""Root directory of *this* plugin, e.g. ``/home/deck/homebrew/plugins/my-plugin``."""

DECKY_PLUGIN_NAME: str
"""Plugin display name from ``plugin.json``."""

DECKY_PLUGIN_VERSION: str
"""Plugin version from ``package.json``."""

DECKY_PLUGIN_SETTINGS_DIR: str
"""Persistent per-plugin settings directory.  Safe to write config files here."""

DECKY_PLUGIN_RUNTIME_DIR: str
"""Per-plugin runtime / cache directory.  Data may be lost across reboots."""

DECKY_PLUGIN_LOG_DIR: str
"""Directory for persistent plugin logs."""

DECKY_PLUGIN_LOG: str
"""Full path to the main plugin log file."""

# ── Logger ────────────────────────────────────────────────────────────
logger: logging.Logger
"""Pre-configured logger writing to ``DECKY_PLUGIN_LOG``."""

# ── Events ────────────────────────────────────────────────────────────
async def emit(event: str, *args: Any) -> None:
    """Push an event to the frontend with arbitrary JSON-safe arguments."""
    ...

# ── Migration helpers ─────────────────────────────────────────────────
def migrate_settings(old_path: str, new_path: str) -> None: ...
def migrate_logs(old_path: str, new_path: str) -> None: ...
def migrate_runtime(old_path: str, new_path: str) -> None: ...

# ── Plugin class base (not required to inherit, but can be used) ──────
class PluginBase:
    """Optional base class for Decky plugins.  Not required."""
    pass
