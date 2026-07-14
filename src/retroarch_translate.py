#!/usr/bin/env python3
"""RetroArch AI Translation Service — Vision API pipeline.

RetroArch sends a base64 PNG screenshot.  The service calls a multimodal
vision model (default: SiliconFlow free pipeline — PaddleOCR-VL →
Hunyuan-MT) to recognise and translate Japanese pixel-font text to
simplified Chinese, then returns the result as a RetroArch AI Service
JSON reply with an optional PNG text overlay.

Typical RetroArch AI Service URL:
  http://127.0.0.1:4404/?game=gyakuten&scene=courtroom

Environment:
  VISION_API_KEY=sk-...        (SiliconFlow API key)
  VISION_PROVIDER=siliconflow  (or empty for free pipeline)
  GAME_CONFIG_PATH=/path/to/game_config.yaml
  GAME_CONFIG_DIR=~/.hermes/retroarch/games
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


# ── Configuration ──────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GAME_CONFIG_PATH = BASE_DIR / "templates" / "game_config.yaml"

LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "4404"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "45"))
CONFIG_DIR = Path(os.path.expanduser(os.environ.get(
    "GAME_CONFIG_DIR",
    "~/.hermes/retroarch/games",
)))
GAME_CONFIG_PATH = Path(os.path.expanduser(os.environ.get(
    "GAME_CONFIG_PATH",
    str(DEFAULT_GAME_CONFIG_PATH),
)))
# ── Vision / OCR step ──
VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.siliconflow.cn/v1")
VISION_OCR_MODEL = os.environ.get("VISION_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL-1.5")

# ── Translate / MT step ──
TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "")
TRANSLATE_BASE_URL = os.environ.get("TRANSLATE_BASE_URL", "https://api.siliconflow.cn/v1")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
TRANSLATE_MT_FREE_MODEL = os.environ.get("TRANSLATE_MT_FREE_MODEL", "tencent/Hunyuan-MT-7B")

TEXT_POSITION_BOTTOM = 1

# ── Translation cache ───────────────────────────────────────────
# Same screenshot → same translation.  Common when re-reading dialog.

_CACHE_MAX = int(os.environ.get("TRANSLATION_CACHE_SIZE", "128"))
_translation_cache: OrderedDict[str, str] = OrderedDict()


def _cache_key(png_bytes: bytes) -> str:
    """Hash the dialog-relevant portion of the screenshot.

    Crops off margins where blinking cursors and status bars live so
    the same dialog text produces the same cache key regardless of
    cursor animation state.
    """
    from io import BytesIO
    img = Image.open(BytesIO(png_bytes)).convert("L")
    w, h = img.size
    # Trim: top 5% (status bar), bottom 10% (blinking cursor)
    y0 = int(h * 0.05)
    y1 = int(h * 0.90)
    crop = img.crop((0, y0, w, y1))
    # Small thumbnail of the text region
    thumb = crop.resize((32, 24), Image.Resampling.LANCZOS)
    return hashlib.sha256(thumb.tobytes()).hexdigest()


def _cache_get(png_bytes: bytes) -> str | None:
    key = _cache_key(png_bytes)
    if key in _translation_cache:
        # Move to end (most recently used)
        _translation_cache.move_to_end(key)
        return _translation_cache[key]
    return None


def _cache_put(png_bytes: bytes, translated: str) -> None:
    key = _cache_key(png_bytes)
    if key in _translation_cache:
        _translation_cache.move_to_end(key)
    _translation_cache[key] = translated
    while len(_translation_cache) > _CACHE_MAX:
        _translation_cache.popitem(last=False)
SUPPORTED_BUTTONS = {
    "a", "b", "x", "y", "select", "start", "up", "down", "left", "right",
    "l", "r", "l2", "r2", "l3", "r3", "pause", "unpause",
}

GAME_ALIASES = {
    "phoenix_wright": "gyakuten",
    "ace_attorney": "gyakuten",
    "gyakuten_saiban": "gyakuten",
    "gba__phoenix_wright": "gyakuten",
}

_config_cache: dict[str, Any] = {"stamp": None, "configs": []}


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
    """Parse the limited YAML shape used by templates/game_config.yaml.

    PyYAML is preferred when installed. This fallback keeps the service
    startable in a fresh Python environment and supports the project's
    top-level maps plus one-level nested maps.
    """
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


# ── Game Config Loading ────────────────────────────────────────

def _config_stamp() -> tuple[tuple[str, float | None], ...]:
    files = [GAME_CONFIG_PATH]
    if CONFIG_DIR.exists():
        files.extend(sorted(CONFIG_DIR.glob("*.yaml")))
        files.extend(sorted(CONFIG_DIR.glob("*.yml")))
    return tuple(
        (str(path), path.stat().st_mtime if path.exists() else None)
        for path in files
    )


def load_all_game_configs() -> list[dict[str, Any]]:
    stamp = _config_stamp()
    if _config_cache["stamp"] == stamp:
        return _config_cache["configs"]

    configs: list[dict[str, Any]] = []
    configs.extend(load_yaml_documents(GAME_CONFIG_PATH))

    if CONFIG_DIR.exists():
        for path in sorted(CONFIG_DIR.glob("*.y*ml")):
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
    return GAME_ALIASES.get(game_id, game_id)


def resolve_game_id(query_game: str | None, label: str | None) -> str | None:
    return normalize_game_id(query_game) or normalize_game_id(label)


def load_game_config(game_id: str | None) -> dict[str, Any] | None:
    """Load a game config by game_id from project YAML or user config dir."""
    normalized = normalize_game_id(game_id)
    configs = load_all_game_configs()
    if not normalized:
        return configs[0] if len(configs) == 1 else None

    for config in configs:
        candidates = {
            normalize_game_id(str(config.get("game_id", ""))),
            normalize_game_id(str(config.get("id", ""))),
            normalize_game_id(str(config.get("display_name", ""))),
        }
        aliases = config.get("aliases", [])
        if isinstance(aliases, list):
            candidates.update(normalize_game_id(str(alias)) for alias in aliases)
        if normalized in candidates:
            return config
    return None


def _siliconflow_call(model: str, messages: list[dict], max_tokens: int = 512) -> str:
    """Single SiliconFlow chat-completion call.  Used by the free pipeline."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }
    url = f"{VISION_BASE_URL.rstrip('/')}/chat/completions"
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {VISION_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read())
    return data["choices"][0]["message"]["content"].strip()


def _translate_text(ocr_text: str) -> str:
    """Text translation step.  Uses TRANSLATE_API_KEY if set, otherwise
    falls back to the free Hunyuan-MT-7B on SiliconFlow."""
    if TRANSLATE_API_KEY:
        model = TRANSLATE_MODEL
        url = f"{TRANSLATE_BASE_URL.rstrip('/')}/chat/completions"
        key = TRANSLATE_API_KEY
    else:
        model = TRANSLATE_MT_FREE_MODEL
        url = f"{VISION_BASE_URL.rstrip('/')}/chat/completions"
        key = VISION_API_KEY

    print(f"[MT] model={model} key={'***' if key else '(free)'}", flush=True)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "将以下日文翻译成简体中文。只输出译文，不要解释。"},
            {"role": "user", "content": ocr_text},
        ],
        "max_tokens": 512,
        "temperature": 0.1,
        "stream": False,
    }
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read())
    translated = data["choices"][0]["message"]["content"].strip()
    print(f"[MT] → {translated}", flush=True)
    return translated


def translate_via_free_pipeline(png_b64: str) -> str:
    """Two-step pipeline:

    1. PaddleOCR-VL (free) — screenshot → Japanese text
    2. Translate — Japanese → Chinese (free or paid, see TRANSLATE_API_KEY)
    """
    # Step 1: OCR
    print(f"[OCR] model={VISION_OCR_MODEL}", flush=True)
    ocr_text = _siliconflow_call(
        model=VISION_OCR_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
            {"type": "text", "text": "请识别这张GBA游戏截图中的所有日文文字，只输出文字，不要解释。"},
        ]}],
    )
    print(f"[OCR] → {ocr_text}", flush=True)

    # Step 2: Translate
    return _translate_text(ocr_text)


# ── RetroArch AI Service Protocol ──────────────────────────────

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


def language_name(code: str | None) -> str | None:
    if not code:
        return None
    mapping = {
        "0": None,
        "1": "en",
        "2": "es",
        "3": "fr",
        "4": "de",
        "5": "it",
        "6": "pt",
        "7": "jpn",
        "8": "ko",
        "9": "zh-CN",
        "10": "zh-TW",
    }
    return mapping.get(str(code), code)


# ── Image Overlay Rendering ─────────────────────────────────────

_CJK_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        try:
            _FONT_CACHE[size] = ImageFont.truetype(_CJK_FONT_PATH, size)
        except (OSError, IOError):
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def render_text_overlay(
    text: str,
    source_png_bytes: bytes,
    viewport: tuple[int, int] | None = None,
    text_position: int = 1,
) -> bytes:
    """Render translated Chinese text onto a transparent PNG overlay.

    Returns PNG bytes for the RetroArch AI Service ``image`` field.
    """
    if viewport and len(viewport) >= 2:
        width, height = int(viewport[0]), int(viewport[1])
    else:
        src = Image.open(BytesIO(source_png_bytes))
        width, height = src.size

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(10, min(16, height // 12))
    font = _get_font(font_size)

    chars_per_line = max(6, width // (font_size + 2))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for i in range(0, len(paragraph), chars_per_line):
            lines.append(paragraph[i:i + chars_per_line])

    max_lines = height // (font_size + 6)
    lines = lines[-max_lines:]

    line_height = font_size + 4
    text_area_height = len(lines) * line_height + 10

    padding_y = 6
    if text_position == 1:  # bottom
        bg_y0 = height - text_area_height - padding_y
        bg_y1 = height
    else:  # top
        bg_y0 = 0
        bg_y1 = text_area_height + padding_y

    draw.rectangle([(0, bg_y0), (width, bg_y1)], fill=(0, 0, 0, 180))

    text_y = bg_y0 + 5
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        text_x = max(2, (width - text_w) // 2)
        draw.text((text_x + 1, text_y + 1), line, font=font, fill=(0, 0, 0, 200))
        draw.text((text_x, text_y), line, font=font, fill=(255, 255, 255, 255))
        text_y += line_height

    buf = BytesIO()
    overlay.save(buf, format="PNG")
    return buf.getvalue()


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
    server_version = "RetroArchPaddleDeepSeek/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        json_response(self, {
            "status": "ok",
            "service": "retroarch-ai-translation",
            "pipeline": f"{VISION_OCR_MODEL} → {TRANSLATE_MODEL if TRANSLATE_API_KEY else TRANSLATE_MT_FREE_MODEL}",
            "config_path": str(GAME_CONFIG_PATH),
            "config_dir": str(CONFIG_DIR),
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

            # ── Translation cache ──
            cached = _cache_get(png_bytes)
            if cached is not None:
                translated = cached
                print("[Cache] hit", flush=True)
            else:
                # ── OCR → MT pipeline ──
                translated = translate_via_free_pipeline(png_b64)
                _cache_put(png_bytes, translated)
            response: dict[str, Any] = {
                "text": translated,
                "text_position": TEXT_POSITION_BOTTOM,
            }

            # Image mode: render text onto transparent PNG for on-screen overlay
            if "image" in output_modes:
                vp = body.get("viewport")
                viewport = (int(vp[0]), int(vp[1])) if vp and len(vp) >= 2 else None
                try:
                    overlay_bytes = render_text_overlay(
                        text=translated,
                        source_png_bytes=png_bytes,
                        viewport=viewport,
                        text_position=TEXT_POSITION_BOTTOM,
                    )
                    response["image"] = base64.b64encode(overlay_bytes).decode("ascii")
                except Exception as exc:
                    print(f"[Image render failed] {exc}", flush=True)

            if "text" not in output_modes and "image" not in output_modes:
                actual_modes = ", ".join(sorted(output_modes)) if output_modes else "default"
                print(
                    f"[MODE WARNING] RetroArch output mode is '{actual_modes}', "
                    f"but this service returns text + image only. "
                    f"Translation IS in the response but RetroArch "
                    f"will ignore it in the current mode. "
                    f"Fix: Settings → AI Service → AI Service Mode → Image (mode 0), "
                    f"or add 'output=image,png' to the AI Service URL.",
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


# ── Main ───────────────────────────────────────────────────────

def main() -> int:
    configs = load_all_game_configs()

    print(f"RetroArch Translation Service on http://{LISTEN_HOST}:{LISTEN_PORT}")
    mt_model = TRANSLATE_MODEL if TRANSLATE_API_KEY else TRANSLATE_MT_FREE_MODEL
    mt_label = f"{mt_model} (paid)" if TRANSLATE_API_KEY else f"{mt_model} (free)"
    print(f"  Pipeline: {VISION_OCR_MODEL} → {mt_label}")
    print(f"  Vision API: {VISION_BASE_URL}")
    if TRANSLATE_API_KEY:
        print(f"  MT API:     {TRANSLATE_BASE_URL}")
    print(f"  Config path: {GAME_CONFIG_PATH}")
    print(f"  User config dir: {CONFIG_DIR}")
    if not CONFIG_DIR.exists():
        print("  User config dir does not exist; using project game_config.yaml only.")
    print(f"  Loaded game configs: {len(configs)}")
    if not VISION_API_KEY:
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

    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), TranslationHandler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
