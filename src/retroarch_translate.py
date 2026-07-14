#!/usr/bin/env python3
"""RetroArch AI Translation Service: PaddleOCR Japanese OCR + DeepSeek V4.

RetroArch sends a base64 PNG screenshot to this HTTP service. The service
extracts Japanese text locally with PaddleOCR, translates the extracted text
with the DeepSeek V4 text API, and returns a RetroArch AI Service JSON reply.

Typical RetroArch AI Service URL:
  http://127.0.0.1:4404/?output=text&game=gyakuten&scene=courtroom

Environment:
  DEEPSEEK_API_KEY=sk-...
  DEEPSEEK_BASE_URL=https://api.deepseek.com
  TRANSLATION_MODEL=deepseek-v4-flash
  GAME_CONFIG_PATH=/path/to/game_config.yaml
  GAME_CONFIG_DIR=~/.hermes/retroarch/games
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


# ── Configuration ──────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GAME_CONFIG_PATH = BASE_DIR / "templates" / "game_config.yaml"

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("TRANSLATION_MODEL", "deepseek-v4-flash")
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

TEXT_POSITION_BOTTOM = 1
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

_ocr: Any | None = None
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


# ── OCR ────────────────────────────────────────────────────────

def get_ocr() -> Any:
    global _ocr
    if _ocr is not None:
        return _ocr

    from paddleocr import PaddleOCR  # type: ignore

    try:
        _ocr = PaddleOCR(lang="japan", use_angle_cls=False, show_log=False)
    except ValueError:
        _ocr = PaddleOCR(lang="japan", use_textline_orientation=False)
    except TypeError:
        _ocr = PaddleOCR(lang="japan")
    return _ocr


def _decode_png_for_ocr(png_bytes: bytes) -> Any:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        encoded = np.frombuffer(png_bytes, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("invalid PNG data")
        return image
    except ModuleNotFoundError:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            tmp.write(png_bytes)
            tmp.close()
            return tmp.name
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise


def _flatten_ocr_text(result: Any) -> list[str]:
    lines: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for key in ("rec_texts", "texts"):
                values = node.get(key)
                if isinstance(values, list):
                    lines.extend(str(item).strip() for item in values if str(item).strip())
                    return
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                text = node[1][0]
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
                    return
            for item in node:
                walk(item)

    walk(result)
    return lines


def _recognize_fallback_regions(ocr: Any, image_or_path: Any) -> list[str]:
    """Recognize fixed UI bands when PaddleOCR detection misses pixel fonts."""
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError:
        return []

    image = cv2.imread(image_or_path) if isinstance(image_or_path, str) else image_or_path
    if image is None:
        return []

    height, width = image.shape[:2]
    regions = [
        image[0:int(height * 0.24), 0:int(width * 0.70)],          # title/nameplate
        image[int(height * 0.80):int(height * 0.98), 0:width],     # bottom text line
    ]

    lines: list[str] = []
    for region in regions:
        if region.size == 0:
            continue
        variants = [
            region,
            cv2.cvtColor(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR),
        ]
        best_text = ""
        best_score = 0.0
        for variant in variants:
            try:
                result = ocr.ocr(variant, det=False, cls=False)
            except TypeError:
                result = ocr.ocr(variant, det=False)
            for item in result or []:
                candidates = item if isinstance(item, list) else [item]
                for candidate in candidates:
                    if (
                        isinstance(candidate, (list, tuple))
                        and len(candidate) >= 2
                        and isinstance(candidate[0], str)
                    ):
                        text, score = candidate[0].strip(), float(candidate[1] or 0)
                        if text and score > best_score:
                            best_text = text
                            best_score = score
        if best_text and best_score >= 0.45:
            lines.append(best_text)

    return list(dict.fromkeys(lines))


def extract_text(png_bytes: bytes) -> str:
    """Extract Japanese text from a RetroArch PNG screenshot with PaddleOCR."""
    image_or_path = _decode_png_for_ocr(png_bytes)
    try:
        ocr = get_ocr()
        if hasattr(ocr, "ocr"):
            try:
                result = ocr.ocr(image_or_path, cls=False)
            except TypeError:
                result = ocr.ocr(image_or_path)
        elif hasattr(ocr, "predict"):
            result = ocr.predict(image_or_path)
        else:
            raise RuntimeError("Unsupported PaddleOCR API")
        lines = _flatten_ocr_text(result)
        if not lines:
            lines = _recognize_fallback_regions(ocr, image_or_path)
        return "\n".join(dict.fromkeys(lines))
    finally:
        if isinstance(image_or_path, str):
            Path(image_or_path).unlink(missing_ok=True)


# ── Prompt Assembly ────────────────────────────────────────────

def build_prompt(
    ocr_text: str,
    config: dict[str, Any] | None,
    scene: str | None,
    source_lang: str | None,
    target_lang: str | None,
) -> tuple[str, str]:
    """Assemble a translation prompt from OCR text and game config."""
    parts: list[str] = []

    parts.append(
        "你是 RetroArch GBA 日文游戏的实时翻译器。"
        "输入来自 OCR，可能有少量错字；请结合上下文纠正明显 OCR 误识别。"
    )

    if config:
        display_name = config.get("display_name") or config.get("game_id")
        if display_name:
            parts.append(f"当前游戏：{display_name}")

        glossary = config.get("glossary", {})
        if isinstance(glossary, dict) and glossary:
            term_list = "\n".join(f"- {src} => {dst}" for src, dst in glossary.items())
            parts.append(f"固定术语表（必须严格使用）：\n{term_list}")

        scene_mode = scene or config.get("default_scene")
        scene_modes = config.get("scene_modes", {})
        if scene_mode and isinstance(scene_modes, dict) and scene_mode in scene_modes:
            parts.append(f"当前场景：{scene_modes[scene_mode]}")

        tones = config.get("character_tones", {})
        if isinstance(tones, dict) and tones:
            tone_rules = "\n".join(f"- {name}：{tone}" for name, tone in tones.items())
            parts.append(f"角色语气规则（看见说话人姓名时应用）：\n{tone_rules}")

        signatures = config.get("signature_phrases", {})
        if isinstance(signatures, dict) and signatures:
            sig_list = "\n".join(f"- {src} => {dst}" for src, dst in signatures.items())
            parts.append(
                "标志性台词锁定（最高优先级；出现时逐字使用指定译法）：\n"
                f"{sig_list}"
            )

    source_hint = source_lang or "jpn"
    target_hint = target_lang or "zh-CN"
    parts.append(f"语言方向：{source_hint} => {target_hint}。")
    parts.append(
        "输出规则（必须遵守）：\n"
        "1. 只输出简体中文译文，一行一句，不加解释、注释、Markdown 或原文。\n"
        "2. 只翻译游戏对话和 UI 文字；不要扩写、补剧情或加入旁白。\n"
        "3. 保留原文省略号、感叹号、问号和停顿节奏，句长尽量接近原文。\n"
        "4. 若出现成步堂/御剑/真宵/审判长等角色，按角色语气翻译。\n"
        "5. 固定术语表和标志性台词优先于自然润色。"
    )

    return "\n\n".join(parts), f"请翻译以下日文 OCR 文本：\n\n{ocr_text}"


# ── Translation ────────────────────────────────────────────────

def _post_deepseek(messages: list[dict[str, str]], max_tokens: int = 1024) -> str:
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    print(
        "[DeepSeek request] "
        + json.dumps(
            {
                "url": f"{BASE_URL.rstrip('/')}/chat/completions",
                "headers": {
                    "Authorization": "Bearer ***",
                    "Content-Type": "application/json",
                },
                "payload": payload,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    req = Request(
        f"{BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read())
    print(
        "[DeepSeek response] "
        + json.dumps(data, ensure_ascii=False),
        flush=True,
    )
    return data["choices"][0]["message"]["content"].strip()


def translate_text(
    ocr_text: str,
    config: dict[str, Any] | None,
    scene: str | None,
    source_lang: str | None,
    target_lang: str | None,
) -> str:
    sys_prompt, user_msg = build_prompt(
        ocr_text=ocr_text,
        config=config,
        scene=scene,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_msg},
    ]
    text = _post_deepseek(messages)

    if not _has_chinese(text):
        repair_messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": (
                    "上一轮没有输出简体中文。请重新翻译，只输出简体中文译文：\n\n"
                    f"{ocr_text[:3000]}"
                ),
            },
        ]
        text = _post_deepseek(repair_messages)
    return text


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


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


def json_response(handler: BaseHTTPRequestHandler, data: dict[str, Any]) -> None:
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
            "model": MODEL,
            "ocr": "paddleocr",
            "config_path": str(GAME_CONFIG_PATH),
            "config_dir": str(CONFIG_DIR),
            "endpoint": parsed.path or "/",
        })

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            output_modes = parse_output_modes(params.get("output", [None])[0])
            source_lang = language_name(params.get("source_lang", [None])[0])
            target_lang = language_name(params.get("target_lang", [None])[0]) or "zh-CN"
            scene = params.get("scene", [None])[0]
            query_game = params.get("game", [None])[0]

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                json_response(self, {"error": "Missing JSON request body"})
                return

            request_body = self.rfile.read(length)
            body = json.loads(request_body)
            if not isinstance(body, dict):
                json_response(self, {"error": "JSON request body must be an object"})
                return

            label = str(body.get("label") or "")
            game_id = resolve_game_id(query_game, label)
            config = load_game_config(game_id)

            png_b64 = body.get("image")
            if not isinstance(png_b64, str) or not png_b64.strip():
                json_response(self, {"error": "Missing required image field"})
                return

            try:
                png_bytes = base64.b64decode(png_b64, validate=True)
            except Exception:
                json_response(self, {"error": "image must be base64-encoded PNG bytes"})
                return

            ocr_text = extract_text(png_bytes)
            if not ocr_text.strip():
                json_response(self, {
                    "text": "[未检测到文字]",
                    "text_position": TEXT_POSITION_BOTTOM,
                    "auto": "continue",
                })
                return

            translated = translate_text(
                ocr_text=ocr_text,
                config=config,
                scene=scene,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            response: dict[str, Any] = {
                "text": translated,
                "text_position": TEXT_POSITION_BOTTOM,
            }

            # This service is a text translator. For sound/image AI modes we
            # still return text so narrator/text configurations work, and add
            # a clear hint instead of fabricating audio or an overlay image.
            if output_modes == {"sound"}:
                response["error"] = (
                    "This service returns translated text only. "
                    "Set RetroArch AI Service mode to narrator/text."
                )
            elif "image" in output_modes and "text" not in output_modes:
                response["error"] = (
                    "This service returns translated text only. "
                    "Use output=text or narrator/text AI Service mode."
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
    print(f"  OCR: PaddleOCR Japanese (lazy-loaded on first POST)")
    print(f"  Provider: {BASE_URL}")
    print(f"  Model: {MODEL}")
    print(f"  Config path: {GAME_CONFIG_PATH}")
    print(f"  User config dir: {CONFIG_DIR}")
    if not CONFIG_DIR.exists():
        print("  User config dir does not exist; using project game_config.yaml only.")
    print(f"  Loaded game configs: {len(configs)}")
    if not API_KEY:
        print("  Warning: DEEPSEEK_API_KEY is not set; translation calls will return an error.")
    print("  RetroArch URL example: http://127.0.0.1:4404/?output=text&game=gyakuten&scene=courtroom")
    print("  Press Ctrl+C to stop")
    print()

    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), TranslationHandler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
