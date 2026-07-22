# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run standalone
python -m src.retroarch_translate

# Docker
docker compose up -d

# Decky plugin frontend
cd decky-plugin && pnpm install && pnpm run build

# Sync Python modules into Decky plugin (after changing src/*.py)
cd decky-plugin && bash sync-py-modules.sh

# Package Decky plugin for distribution
cd decky-plugin && pnpm run package

# Smoke test the endpoint (1×1 transparent PNG)
PNG_B64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
curl -sS -X POST "http://localhost:4404/?output=text" \
  -H "Content-Type: application/json" \
  -d "{\"image\":\"$PNG_B64\",\"label\":\"snes__test\",\"state\":{\"paused\":1}}"

# Offline regression tests (no real API calls)
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

A small standard-library `unittest` regression suite covers OCR hints, game config parsing/fingerprints, cache isolation, HTTP config propagation, log buffer core/snapshot/redaction, and HTML escaping. No linter or type checker is configured.

## Architecture

Real-time translation overlay for RetroArch. Python 3.10+, zero external deps at runtime (urllib + Pillow wheel).

### Translation Pipeline (per request, `http_server.py:277-290`)

```
PNG base64 → LRU cache check → Vision LLM OCR → MT translate → JSON response + PNG overlay
```

- **Cache** (`cache.py`): Hashes the dialog area (5% top / 10% bottom cropped, downscaled to 32×24 grayscale) together with a stable full-game-config fingerprint, so animated cursors/status bars don't break cache hits while OCR or translation config changes invalidate old results. LRU, ~128 entries by default.
- **OCR** (`ocr.py`): Sends base64 PNG to a Vision LLM (`PaddleOCR-VL-1.5` on SiliconFlow by default) asking it to extract Japanese text, with optional bounded UI/context hints from the selected game's `ocr` mapping.
- **Translate** (`translate.py`): Builds a game-aware system prompt (glossary → signature phrases → character tones → format rules) and sends OCR text to an MT model. Falls back to free `Hunyuan-MT-7B` if `TRANSLATE_API_KEY` is unset. Disables DeepSeek thinking tokens.
- **Overlay** (`overlay.py`): Parses speaker name vs dialogue from translated text, renders semi-transparent background bar + CJK text with Pillow. Font path from `CJK_FONT_PATH` env var (falls back to `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`).

### Key source files

| File | Role |
|---|---|
| `src/retroarch_translate.py` | Entry point — loads configs, starts server |
| `src/config.py` | All env-var-based config constants |
| `src/game_config.py` | YAML loader, per-IP game tracking, game resolution |
| `src/http_server.py` | HTTP endpoints: `/`, `/settings`, `/set-game`, AI translate |
| `src/ocr.py` | Vision LLM OCR (SiliconFlow-compatible API) |
| `src/translate.py` | MT (paid model or free Hunyuan-MT-7B fallback) |
| `src/overlay.py` | Pillow-based text overlay with speaker detection |
| `src/cache.py` | LRU cache keyed on downsampled screenshot crops |
| `src/server_manager.py` | `ThreadingHTTPServer` in a daemon thread, delegates log capture to `log_buffer` |
| `src/log_buffer.py` | Thread-safe bounded log buffer (1000 lines), API key redaction, stdout/stderr tee, `snapshot_logs()` and `get_recent_logs()` |
| `decky-plugin/main.py` | Decky backend: RPC methods, env bootstrap, server lifecycle |
| `decky-plugin/src/` | Decky frontend: StatusPanel, GameSelector, ApiKeySettings, LogViewer |
| `templates/game_config.yaml` | Built-in game configs (glossary, phrases, tones) |

### RetroArch Protocol Contract (critical)

- **Always return HTTP 200.** RetroArch ignores HTTP status codes; errors go in the `"error"` JSON field.
- Request: `{"image": "<base64 PNG>", "label": "system__content", "state": {...}, "viewport": [w, h]}`
- Response: `{"text": "...", "image": "<base64 PNG overlay>", "text_position": 1}`
- The `output` query param controls which fields RetroArch expects. If RetroArch is set to Speech/Narrator mode instead of **Image (mode 0)**, the service logs a warning and the overlay won't display.

## Two deployment modes

Controlled by `SINGLE_DEVICE_MODE` env var (truthy: `"1"`, `"true"`, `"yes"`, read in `config.py`):

- **Decky plugin** — `SINGLE_DEVICE_MODE=1`. All game selection goes through `_default` key. Set in `decky-plugin/main.py:_inject_env()`.
- **Docker / standalone** — flag unset (default). Per-IP game tracking in `.device_games.json`. Each RetroArch client gets independent game selection.

Mode logic is encapsulated in `game_config.py` — `get_game_for_ip()` and `set_game_for_ip()` transparently remap IPs→`_default` when single-device. Zero changes needed in `http_server.py`.

## Game config resolution (3-tier, per AI request)

1. Per-IP override (`get_game_for_ip(client_ip)`)
2. Auto-detect from RetroArch `label` field (`resolve(None, label)`)
3. `_default` fallback in `.device_games.json`

In single-device mode, tiers 1 and 3 are identical → collapses to `_default || label_autodetect`.

## Vendored py_modules rule

The canonical Python source is `src/`. The decky plugin vendors a copy at `decky-plugin/py_modules/retroarch_ai/`. **Always edit `src/` first**, then sync into the plugin:

```bash
cd decky-plugin && bash sync-py-modules.sh
```

This copies all `.py` files from `src/` into the vendored directory, skipping `__init__.py` (the decky plugin has its own).

## Decky plugin conventions

- Settings persisted to `decky.DECKY_PLUGIN_SETTINGS_DIR/settings.json`
- `_inject_env()` sets env vars BEFORE first `retroarch_ai` import
- `_apply_env_from_settings()` handles API keys + listen_port only (NOT game_id)
- `save_settings()` handles `game_id` separately via `set_current_game()`
- Server restart via `_stop_server()` → `_start_server()` to pick up new env vars

## API settings flow

Settings read from `os.environ` on every request → changes take effect without restart. Web UI POST to `/settings` saves JSON + applies to env. Decky plugin does same via `save_settings` RPC.

SSL is unverified via custom context (SteamOS may have incomplete CA certs).
