# RetroArch AI Translation

Real-time Japanese→Chinese translation overlay for RetroArch. Vision LLM OCR → MT → Pillow overlay.

## Architecture

```
RetroArch AI Service ──POST {image, label}──► ThreadingHTTPServer (:4404)
                                                ├── ocr.py    (Vision LLM → JP text)
                                                ├── translate.py (MT → CN text)
                                                └── overlay.py (PNG overlay)
```

- **Python 3.11+**, zero external deps at runtime (urllib + Pillow vendored wheel)
- `ServerManager` wraps `ThreadingHTTPServer` in a daemon thread with log ring buffer
- Web UI at `/` (game selector) and `/settings` (API keys form)
- Decky Loader plugin at `decky-plugin/` (React/TypeScript QAM panels)

## Key source files

| File | Role |
|---|---|
| `src/config.py` | All env-var-based config constants |
| `src/game_config.py` | YAML loader, per-IP game tracking, game resolution |
| `src/http_server.py` | HTTP endpoints: `/`, `/settings`, `/set-game`, AI translate |
| `src/ocr.py` | Vision LLM OCR (SiliconFlow-compatible API) |
| `src/translate.py` | MT (paid model or free Hunyuan-MT-7B fallback) |
| `src/overlay.py` | Pillow-based text overlay with speaker detection |
| `src/server_manager.py` | ThreadingHTTPServer daemon wrapper |
| `decky-plugin/main.py` | Decky backend: RPC methods, env bootstrap, server lifecycle |
| `decky-plugin/src/` | Decky frontend: StatusPanel, GameSelector, ApiKeySettings, LogViewer |
| `templates/game_config.yaml` | Built-in game configs (glossary, phrases, tones) |

## Two deployment modes

Controlled by env var `SINGLE_DEVICE_MODE` (truthy: `"1"`, `"true"`, `"yes"`):

- **Decky plugin** — `SINGLE_DEVICE_MODE=1`. All game selection goes through `_default` key. QAM and web UI share one global setting. Set in `decky-plugin/main.py:_inject_env()`.
- **Docker** — flag unset (default). Per-IP game tracking in `.device_games.json`. Each RetroArch client gets independent game selection.

Mode logic is encapsulated in `game_config.py` data layer — `get_game_for_ip()` and `set_game_for_ip()` transparently remap IPs→`_default` when single-device. Zero changes needed in `http_server.py`.

## Game config resolution (3-tier, per AI request)

1. Per-IP override (`get_game_for_ip(client_ip)`)
2. Auto-detect from RetroArch `label` field (`resolve(None, label)`)
3. `_default` fallback in `.device_games.json`

In single-device mode, tiers 1 and 3 are identical → collapses to `_default || label_autodetect`.

## Vendored py_modules rule

**CRITICAL**: `decky-plugin/py_modules/retroarch_ai/` must stay byte-identical to `src/`. Any runtime behavior change to `src/*.py` MUST be mirrored. Verify with:
```bash
diff src/config.py decky-plugin/py_modules/retroarch_ai/config.py
diff src/game_config.py decky-plugin/py_modules/retroarch_ai/game_config.py
# ... etc for all .py files
```

## Decky plugin conventions

- Settings persisted to `decky.DECKY_PLUGIN_SETTINGS_DIR/settings.json`
- `_inject_env()` sets env vars BEFORE first `retroarch_ai` import
- `_apply_env_from_settings()` handles API keys + listen_port only (NOT game_id)
- `save_settings()` handles `game_id` separately via `set_current_game()`
- Server restart via `_stop_server()` → `_start_server()` to pick up new env vars

## API settings flow

Settings read from `os.environ` on every request → changes take effect without restart. Web UI POST to `/settings` saves JSON + applies to env. Decky plugin does same via `save_settings` RPC.

SSL is unverified via custom context (SteamOS may have incomplete CA certs).
