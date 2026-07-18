"""Game config loader — YAML parsing and game config resolution."""

import json
import re
from pathlib import Path
from typing import Any

from . import config

_config_cache: dict[str, Any] = {"stamp": None, "configs": []}

_DEVICE_FILE = config.CONFIG_DIR / ".device_games.json"
_DEFAULT_KEY = "_default"


def _load_device_games() -> dict[str, str]:
    """Load per-IP game selections from JSON.

    Migrates legacy ``.current_game`` on first access if present.
    """
    try:
        data = json.loads(_DEVICE_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (OSError, FileNotFoundError):
        pass
    except json.JSONDecodeError:
        pass

    # Migrate from legacy .current_game file
    legacy = config.CONFIG_DIR / ".current_game"
    try:
        game_id = legacy.read_text().strip()
        legacy.unlink()
        if game_id:
            data = {_DEFAULT_KEY: game_id}
            _save_device_games(data)
            return data
    except (OSError, FileNotFoundError):
        pass

    return {}


def _save_device_games(data: dict[str, str]) -> None:
    """Persist per-IP game selections to JSON."""
    try:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _DEVICE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def get_game_for_ip(ip: str) -> str:
    """Return the game_id configured for *ip*, or empty string.

    In single-device mode all IPs resolve to the ``_default`` key.
    """
    data = _load_device_games()
    if config.SINGLE_DEVICE_MODE:
        return data.get(_DEFAULT_KEY, "")
    return data.get(ip, "")

def set_game_for_ip(ip: str, game_id: str) -> None:
    """Set the game_id for a specific IP (empty string clears the mapping).

    In single-device mode always writes to the ``_default`` key.
    """
    data = _load_device_games()
    key = _DEFAULT_KEY if config.SINGLE_DEVICE_MODE else ip
    if game_id:
        data[key] = game_id
    else:
        data.pop(key, None)
    _save_device_games(data)

def set_current_game(game_id: str) -> None:
    """Set the default game for all devices (backward-compat)."""
    global current_game_id
    set_game_for_ip(_DEFAULT_KEY, game_id)
    current_game_id = game_id


def _current_game_id() -> str:
    """Return the default game id (backward-compat accessor)."""
    return _load_device_games().get(_DEFAULT_KEY, "")


current_game_id: str = _current_game_id()


# ── Small YAML Loader Fallback ─────────────────────────────────

def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if char == "\\" and in_double and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
        escaped = False
    return value.rstrip()


def _parse_scalar(value: str) -> Any:
    value = _strip_inline_comment(value).strip()
    if value == "":
        return ""
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _minimal_yaml_load_all(text: str) -> list[dict[str, Any]]:
    """Parse the limited YAML shape used by templates/game_config.yaml."""
    docs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_map: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.strip() == "---":
            if current:
                docs.append(current)
            current = {}
            current_map = None
            continue
        if current is None:
            current = {}

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if value.strip():
                current[key] = _parse_scalar(value)
                current_map = None
            else:
                current[key] = {}
                current_map = current[key]
        elif current_map is not None and ":" in line:
            key, value = line.split(":", 1)
            current_map[_parse_scalar(key)] = _parse_scalar(value)

    if current:
        docs.append(current)
    return docs


def load_yaml_documents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        loaded = list(yaml.safe_load_all(text))
        return [doc for doc in loaded if isinstance(doc, dict)]
    except ModuleNotFoundError:
        return _minimal_yaml_load_all(text)


# ── Config Loading ─────────────────────────────────────────────

def _config_stamp() -> tuple[tuple[str, float | None], ...]:
    files = [config.GAME_CONFIG_PATH]
    if config.CONFIG_DIR.exists():
        files.extend(sorted(config.CONFIG_DIR.glob("*.yaml")))
        files.extend(sorted(config.CONFIG_DIR.glob("*.yml")))
    return tuple(
        (str(path), path.stat().st_mtime if path.exists() else None)
        for path in files
    )


def load_all() -> list[dict[str, Any]]:
    stamp = _config_stamp()
    if _config_cache["stamp"] == stamp:
        return _config_cache["configs"]

    configs: list[dict[str, Any]] = []
    configs.extend(load_yaml_documents(config.GAME_CONFIG_PATH))

    if config.CONFIG_DIR.exists():
        for path in sorted(config.CONFIG_DIR.glob("*.y*ml")):
            configs.extend(load_yaml_documents(path))

    _config_cache["stamp"] = stamp
    _config_cache["configs"] = configs
    return configs


def normalize_game_id(value: str | None) -> str | None:
    if not value:
        return None
    game_id = value.strip().lower()
    if "__" in game_id:
        game_id = game_id.split("__", 1)[1]
    game_id = re.sub(r"[^a-z0-9_\-]+", "_", game_id).strip("_")
    return config.GAME_ALIASES.get(game_id, game_id)


def resolve(query_game: str | None, label: str | None) -> str | None:
    return normalize_game_id(query_game) or normalize_game_id(label)


def load(game_id: str | None) -> dict[str, Any] | None:
    """Load a game config by game_id from project YAML or user config dir."""
    normalized = normalize_game_id(game_id)
    configs = load_all()
    if not normalized:
        return configs[0] if len(configs) == 1 else None

    for cfg in configs:
        candidates = {
            normalize_game_id(str(cfg.get("game_id", ""))),
            normalize_game_id(str(cfg.get("id", ""))),
            normalize_game_id(str(cfg.get("display_name", ""))),
        }
        aliases = cfg.get("aliases", [])
        if isinstance(aliases, list):
            candidates.update(normalize_game_id(str(alias)) for alias in aliases)
        if normalized in candidates:
            return cfg
    return None
