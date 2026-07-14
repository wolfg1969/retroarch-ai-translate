"""HTTP server — RetroArch AI Service protocol handler."""

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import config, cache, ocr, translate, overlay


def parse_output_modes(raw_output: str | None) -> set[str]:
    if not raw_output:
        return {"sound", "wav"}
    parts = {part.strip().lower() for part in raw_output.split(",") if part.strip()}
    modes: set[str] = set()
    if "text" in parts:
        modes.add("text")
    if "sound" in parts or "wav" in parts:
        modes.add("sound")
    if "image" in parts or "png" in parts or "png-a" in parts:
        modes.add("image")
    return modes or {"text"}


def json_response(handler: BaseHTTPRequestHandler, data: dict[str, Any]) -> None:
    print(f"[Response] {json.dumps(data, ensure_ascii=False)}", flush=True)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class TranslationHandler(BaseHTTPRequestHandler):
    server_version = "RetroArchAI/3.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        mt_model = config.TRANSLATE_MODEL if config.TRANSLATE_API_KEY else config.TRANSLATE_MT_FREE_MODEL
        json_response(self, {
            "status": "ok",
            "service": "retroarch-ai-translation",
            "pipeline": f"{config.VISION_OCR_MODEL} → {mt_model}",
            "config_path": str(config.GAME_CONFIG_PATH),
            "config_dir": str(config.CONFIG_DIR),
            "endpoint": parsed.path or "/",
        })

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            all_output_vals = params.get("output", [])
            combined_raw = ",".join(v for v in all_output_vals if v)
            output_modes = parse_output_modes(combined_raw if combined_raw else None)

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                json_response(self, {"error": "Missing JSON request body"})
                return

            request_body = self.rfile.read(length)
            body = json.loads(request_body)
            if not isinstance(body, dict):
                json_response(self, {"error": "JSON request body must be an object"})
                return

            png_b64 = body.get("image")
            if not isinstance(png_b64, str) or not png_b64.strip():
                json_response(self, {"error": "Missing required image field"})
                return

            try:
                png_bytes = base64.b64decode(png_b64, validate=True)
            except Exception:
                json_response(self, {"error": "image must be base64-encoded PNG bytes"})
                return

            # Cache check
            cached = cache.get(png_bytes)
            if cached is not None:
                translated = cached
                print("[Cache] hit", flush=True)
            else:
                ocr_text = ocr.extract_text(png_b64)
                translated = translate.translate(ocr_text)
                cache.put(png_bytes, translated)

            response: dict[str, Any] = {
                "text": translated,
                "text_position": config.TEXT_POSITION_BOTTOM,
            }

            # Image overlay
            if "image" in output_modes:
                vp = body.get("viewport")
                viewport = (int(vp[0]), int(vp[1])) if vp and len(vp) >= 2 else None
                try:
                    overlay_bytes = overlay.render(
                        text=translated,
                        source_png_bytes=png_bytes,
                        viewport=viewport,
                        text_position=config.TEXT_POSITION_BOTTOM,
                    )
                    response["image"] = base64.b64encode(overlay_bytes).decode("ascii")
                except Exception as exc:
                    print(f"[Image render failed] {exc}", flush=True)

            if "text" not in output_modes and "image" not in output_modes:
                actual_modes = ", ".join(sorted(output_modes)) if output_modes else "default"
                print(
                    f"[MODE WARNING] RetroArch output mode is '{actual_modes}', "
                    f"but this service returns text + image only. "
                    f"Fix: Settings → AI Service → AI Service Mode → Image (mode 0).",
                    flush=True,
                )

            json_response(self, response)

        except json.JSONDecodeError:
            json_response(self, {"error": "Invalid JSON request body"})
        except Exception as exc:
            json_response(self, {"error": str(exc)[:500]})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), fmt % args)
        )
