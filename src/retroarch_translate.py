#!/usr/bin/env python3
"""RetroArch AI Translate Service — Vision API pipeline.

RetroArch sends a base64 PNG screenshot.  The service calls a vision
OCR model to recognise Japanese pixel-font text, then a translation
model to produce simplified Chinese, and returns the result as a
RetroArch AI Service JSON reply with an optional PNG text overlay.

Typical RetroArch AI Service URL:
  http://127.0.0.1:4404/?game=gyakuten&scene=courtroom

Environment:
  VISION_API_KEY=sk-...        (SiliconFlow API key)
  TRANSLATE_API_KEY=sk-...     (optional, defaults to free MT)
  GAME_CONFIG_PATH=/path/to/game_config.yaml
"""

import sys
from http.server import ThreadingHTTPServer

from . import config, game_config, http_server
from .log_buffer import install_capture, restore_capture


def main() -> int:
    install_capture()
    try:
        configs = game_config.load_all()

        print(f"RetroArch Translation Service on http://{config.LISTEN_HOST}:{config.LISTEN_PORT}")
        mt_model = config.TRANSLATE_MODEL if config.TRANSLATE_API_KEY else config.TRANSLATE_MT_FREE_MODEL
        mt_label = f"{mt_model} (paid)" if config.TRANSLATE_API_KEY else f"{mt_model} (free)"
        print(f"  Pipeline: {config.VISION_OCR_MODEL} → {mt_label}")
        print(f"  Vision API: {config.VISION_BASE_URL}")
        if config.TRANSLATE_API_KEY:
            print(f"  MT API:     {config.TRANSLATE_BASE_URL}")
        print(f"  Config path: {config.GAME_CONFIG_PATH}")
        print(f"  User config dir: {config.CONFIG_DIR}")
        if not config.CONFIG_DIR.exists():
            print("  User config dir does not exist; using project game_config.yaml only.")
        print(f"  Loaded game configs: {len(configs)}")
        if not config.VISION_API_KEY:
            print("  Warning: VISION_API_KEY is not set; translation calls will return an error.")
        print("  ─────────────────────────────────────────────────────────────")
        print("  IMPORTANT: This is a TEXT-ONLY translation service.")
        print("  In RetroArch, go to Settings → AI Service and set:")
        print("    AI Service Mode = Image (mode 0)")
        print("  Otherwise, translated text will NOT display in-game.")
        print("  URL example: http://127.0.0.1:4404/?game=gyakuten&scene=courtroom")
        print("  ─────────────────────────────────────────────────────────────")
        print("  Press Ctrl+C to stop")
        print()

        ThreadingHTTPServer(
            (config.LISTEN_HOST, config.LISTEN_PORT),
            http_server.TranslationHandler,
        ).serve_forever()
        return 0
    finally:
        restore_capture()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
