"""Decky Loader plugin backend — manages the RetroArch AI Translation service.

The Decky plugin runtime injects the ``decky`` module and looks for a class
named ``Plugin``.  All public methods are exposed as RPC endpoints to the
frontend React app.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

# The decky module is injected by Decky Loader at runtime — it is NOT
# installable via pip.  The ``decky.pyi`` file provides type hints for IDE
# support but is never imported at runtime.
try:
    import decky  # type: ignore[import-not-found]
except ModuleNotFoundError:
    # Running outside Decky — provide a minimal mock for local testing
    class _MockDecky:
        DECKY_HOME = os.path.expanduser("~/.local/share/decky-mock")
        DECKY_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
        DECKY_PLUGIN_SETTINGS_DIR = os.path.join(DECKY_HOME, "settings")
        DECKY_PLUGIN_RUNTIME_DIR = os.path.join(DECKY_HOME, "runtime")
        DECKY_PLUGIN_LOG = os.path.join(DECKY_HOME, "plugin.log")

        class logger:
            @staticmethod
            def info(msg: str) -> None:
                print(f"[decky] {msg}")

            @staticmethod
            def error(msg: str) -> None:
                print(f"[decky ERROR] {msg}", file=sys.stderr)

    decky = _MockDecky()  # type: ignore[assignment]

# Inject vendored py_modules so we can import retroarch_ai as a top-level package.
_PY_MODULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "py_modules")
if _PY_MODULES not in sys.path:
    sys.path.insert(0, _PY_MODULES)


# ── Settings ─────────────────────────────────────────────────────────

SETTINGS_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

DEFAULT_SETTINGS: dict[str, Any] = {
    "vision_api_key": "",
    "translate_api_key": "",
    "translate_base_url": "https://api.siliconflow.cn/v1",
    "translate_model": "deepseek-ai/DeepSeek-V4-Flash",
    "listen_port": 4404,
    "auto_start": True,
    "cjk_font_path": "",
}


def _load_settings() -> dict[str, Any]:
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # Merge with defaults (in case new keys were added)
                merged = {**DEFAULT_SETTINGS, **saved}
                return merged
    except (json.JSONDecodeError, OSError) as exc:
        decky.logger.error(f"Failed to load settings: {exc}")
    return dict(DEFAULT_SETTINGS)


def _save_settings(settings: dict[str, Any]) -> bool:
    try:
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        decky.logger.error(f"Failed to save settings: {exc}")
        return False


# ── Path / env bootstrapping ─────────────────────────────────────────

def _inject_env(settings: dict[str, Any]) -> None:
    """Set environment variables before the retroarch_ai package is imported.

    The vendored ``config.py`` reads all paths from env vars with fallbacks,
    so we just need to set the right overrides before the first import.
    """
    settings_dir = decky.DECKY_PLUGIN_SETTINGS_DIR
    runtime_dir = decky.DECKY_PLUGIN_RUNTIME_DIR

    os.environ.setdefault(
        "GAME_CONFIG_PATH",
        os.path.join(settings_dir, "game_config.yaml"),
    )
    os.environ.setdefault(
        "GAME_CONFIG_DIR",
        os.path.join(settings_dir, "games"),
    )
    os.environ.setdefault("LISTEN_HOST", "0.0.0.0")
    os.environ.setdefault("LISTEN_PORT", str(settings.get("listen_port", 4404)))

    # API keys from settings → env vars
    if settings.get("vision_api_key"):
        os.environ["VISION_API_KEY"] = settings["vision_api_key"]
    if settings.get("translate_api_key"):
        os.environ["TRANSLATE_API_KEY"] = settings["translate_api_key"]
    if settings.get("translate_base_url"):
        os.environ["TRANSLATE_BASE_URL"] = settings["translate_base_url"]
    if settings.get("translate_model"):
        os.environ["TRANSLATE_MODEL"] = settings["translate_model"]


def _ensure_font(settings: dict[str, Any]) -> None:
    """Make a CJK font available for the overlay renderer.

    1. Honour an explicit ``cjk_font_path`` in settings.
    2. Check the system Debian/Ubuntu path.
    3. Check common SteamOS / Arch paths.
    4. Fall back to the bundled font in ``assets/``.
    """
    # Explicit user setting wins
    user_path = settings.get("cjk_font_path", "")
    if user_path and os.path.exists(user_path):
        os.environ["CJK_FONT_PATH"] = user_path
        decky.logger.info(f"CJK font (user): {user_path}")
        return

    # System paths
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",      # Debian/Ubuntu
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",  # Arch/SteamOS
        "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",      # Alternative Arch
        "/usr/share/fonts/TTF/NotoSansCJK-Regular.ttc",       # Arch TTF dir
    ]
    for path in candidates:
        if os.path.exists(path):
            os.environ["CJK_FONT_PATH"] = path
            decky.logger.info(f"CJK font (system): {path}")
            return

    # Bundled fallback
    bundled = os.path.join(decky.DECKY_PLUGIN_DIR, "assets", "wqy-zenhei.ttc")
    if os.path.exists(bundled):
        runtime_font = os.path.join(
            decky.DECKY_PLUGIN_RUNTIME_DIR, "wqy-zenhei.ttc"
        )
        try:
            os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
            if not os.path.exists(runtime_font):
                shutil.copy2(bundled, runtime_font)
            os.environ["CJK_FONT_PATH"] = runtime_font
            decky.logger.info(f"CJK font (bundled): {runtime_font}")
            return
        except OSError as exc:
            decky.logger.error(f"Failed to copy bundled font: {exc}")

    decky.logger.error("No CJK font found — overlay text rendering may fail")


def _ensure_default_config() -> None:
    """Copy the default game_config.yaml to settings dir on first run."""
    target = os.environ.get("GAME_CONFIG_PATH", "")
    if not target or os.path.exists(target):
        return

    src = os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "game_config.yaml")
    if os.path.exists(src):
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
            decky.logger.info(f"Seeded default game config → {target}")
        except OSError as exc:
            decky.logger.error(f"Failed to seed default config: {exc}")


# ── Plugin class ─────────────────────────────────────────────────────


class Plugin:
    """Decky Loader plugin backend for RetroArch AI Translation."""

    _manager: Any = None  # ServerManager, set after import

    # ═══════════════════════════════════════════════════════════════
    # Lifecycle hooks
    # ═══════════════════════════════════════════════════════════════

    async def _main(self) -> None:
        """Called when the plugin is loaded."""
        # 1. Load settings
        settings = _load_settings()

        # 2. Inject env vars (must happen before retroarch_ai imports)
        _inject_env(settings)

        # 3. Ensure CJK font is available
        _ensure_font(settings)

        # 4. Seed default game config if needed
        _ensure_default_config()

        # 5. Import retroarch_ai (after env vars are set)
        decky.logger.info("Starting RetroArch AI Translation service…")

        # 6. Auto-start the server
        if settings.get("auto_start", True):
            self._start_server()
            decky.logger.info(
                f"Service started on port {os.environ.get('LISTEN_PORT', 4404)}"
            )
        else:
            decky.logger.info("auto_start is off — service not started")

    async def _unload(self) -> None:
        """Called when the plugin is disabled or Steam exits."""
        self._stop_server()
        decky.logger.info("RetroArch AI Translation service stopped")

    async def _uninstall(self) -> None:
        """Called when the plugin is fully removed."""
        self._stop_server()
        # Optionally clean up settings and runtime data
        try:
            if os.path.exists(SETTINGS_FILE):
                os.remove(SETTINGS_FILE)
        except OSError:
            pass

    # ═══════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════

    def _start_server(self) -> None:
        if self._manager is not None and self._manager.running:
            return
        # Lazy import so env vars are already set
        from retroarch_ai.server_manager import ServerManager

        self._manager = ServerManager()
        self._manager.start()

    def _stop_server(self) -> None:
        if self._manager is not None:
            self._manager.stop(timeout=5.0)
            self._manager = None

    def _apply_env_from_settings(self, settings: dict[str, Any]) -> None:
        """Push settings into os.environ (for already-running service)."""
        if settings.get("vision_api_key"):
            os.environ["VISION_API_KEY"] = settings["vision_api_key"]
        if settings.get("translate_api_key"):
            os.environ["TRANSLATE_API_KEY"] = settings["translate_api_key"]
        if settings.get("translate_base_url"):
            os.environ["TRANSLATE_BASE_URL"] = settings["translate_base_url"]
        if settings.get("translate_model"):
            os.environ["TRANSLATE_MODEL"] = settings["translate_model"]
        if settings.get("listen_port"):
            os.environ["LISTEN_PORT"] = str(settings["listen_port"])

    # ═══════════════════════════════════════════════════════════════
    # RPC methods (called by frontend via callable())
    # ═══════════════════════════════════════════════════════════════

    async def get_status(self) -> dict[str, Any]:
        """Return current service status for the frontend."""
        # Import after env vars are set
        from .py_modules.retroarch_ai import config as ra_config

        running = self._manager is not None and self._manager.running
        port = int(os.environ.get("LISTEN_PORT", 4404))

        return {
            "running": running,
            "port": port,
            "host": os.environ.get("LISTEN_HOST", "0.0.0.0"),
            "vision_model": ra_config.VISION_OCR_MODEL,
            "translate_model": (
                ra_config.TRANSLATE_MODEL
                if ra_config.TRANSLATE_API_KEY
                else ra_config.TRANSLATE_MT_FREE_MODEL
            ),
            "has_vision_key": bool(ra_config.VISION_API_KEY),
            "has_translate_key": bool(ra_config.TRANSLATE_API_KEY),
            "cjk_font_path": (
                os.environ.get("CJK_FONT_PATH", "")
                or ra_config._CJK_FONT_PATH
            ),
        }

    async def get_games(self) -> list[dict[str, str]]:
        """Return available game configs (id + display_name)."""
        from retroarch_ai.game_config import load_all

        configs = load_all()
        return [
            {
                "id": str(gc.get("game_id", "")),
                "name": str(gc.get("display_name", gc.get("game_id", ""))),
            }
            for gc in configs
        ]

    async def get_settings(self) -> dict[str, Any]:
        """Return current settings (API keys masked)."""
        settings = _load_settings()
        # Mask keys for display
        display = dict(settings)
        if display.get("vision_api_key"):
            display["vision_api_key"] = "••••" + display["vision_api_key"][-4:]
        if display.get("translate_api_key"):
            display["translate_api_key"] = (
                "••••" + display["translate_api_key"][-4:]
            )
        return display

    async def save_settings(
        self, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist settings, apply to env, and optionally restart server."""
        # Update settings
        current = _load_settings()
        current.update(settings)
        ok = _save_settings(current)
        if not ok:
            return {"success": False, "error": "Failed to save settings"}

        # Apply to env
        self._apply_env_from_settings(current)

        # Restart server if port changed or if it was running
        was_running = self._manager is not None and self._manager.running
        if was_running:
            self._stop_server()
        if was_running or current.get("auto_start", True):
            self._start_server()

        return {"success": True}

    async def start_service(self) -> dict[str, Any]:
        """Start the HTTP translation server."""
        self._start_server()
        return await self.get_status()

    async def stop_service(self) -> dict[str, Any]:
        """Stop the HTTP translation server."""
        self._stop_server()
        return await self.get_status()

    async def get_logs(self, lines: int = 50) -> list[str]:
        """Return recent log lines from the ring buffer."""
        from retroarch_ai.server_manager import get_recent_logs

        return get_recent_logs(lines)
