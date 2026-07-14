#!/usr/bin/env python3
"""RetroArch AI Translation Service — GBA + DeepSeek V4 (OCR-based).

Local OCR extracts Japanese text from GBA screenshots, then DeepSeek V4
translates to Chinese. No Vision API needed — DeepSeek V4 is text-only.

Setup:
  1. pip install paddlepaddle paddleocr pyyaml
  2. export DEEPSEEK_API_KEY=sk-...
  3. Place game configs in ~/.hermes/retroarch/games/<game_id>.yaml
  4. Run: python3 retroarch_translate.py
  5. RetroArch: Settings → AI Service → URL = http://localhost:4404
  6. Bind AI Service hotkey in Settings → Input → Hotkeys

Game/Scene switching: append query params to the RetroArch URL:
  http://localhost:4404/?game=gyakuten&scene=courtroom
"""

import base64
import json
import os
import sys
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs

# ── Configuration ──────────────────────────────────────────────
API_KEY = os.environ["DEEPSEEK_API_KEY"]
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("TRANSLATION_MODEL", "deepseek-v4-flash")
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 4404
REQUEST_TIMEOUT = 45
CONFIG_DIR = os.path.expanduser("~/.hermes/retroarch/games")

# Lazy-loaded OCR engine
_ocr = None


def get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(lang="japan", use_angle_cls=False, show_log=False)
    return _ocr


# ── Game Config Loading ────────────────────────────────────────

def load_game_config(game_id: str) -> dict | None:
    """Load game YAML config from ~/.hermes/retroarch/games/<game_id>.yaml"""
    path = os.path.join(CONFIG_DIR, f"{game_id}.yaml")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f)


# ── Prompt Assembly ────────────────────────────────────────────

def build_prompt(ocr_text: str, config: dict | None, scene: str | None) -> str:
    """Assemble the full translation prompt from OCR text + game config."""
    parts = []

    if config:
        # 1. Glossary (term → fixed translation)
        glossary = config.get("glossary", {})
        if glossary:
            term_list = ", ".join(f"{k}→{v}" for k, v in glossary.items())
            parts.append(f"固定译名（必须严格使用，不得改写）：{term_list}")

        # 2. Signature phrases (locked — highest priority)
        signatures = config.get("signature_phrases", {})
        if signatures:
            sig_list = ", ".join(f"{k}→「{v}」" for k, v in signatures.items())
            parts.append(
                f"标志性台词严格对译（出现时必须用指定翻译，不得自由发挥）：{sig_list}"
            )

        # 3. Scene context
        scene_mode = scene or config.get("default_scene")
        if scene_mode:
            modes = config.get("scene_modes", {})
            if scene_mode in modes:
                parts.append(f"当前场景：{modes[scene_mode]}")

        # 4. Character tones (placed second-to-last for high weight)
        tones = config.get("character_tones", {})
        if tones:
            tone_rules = "; ".join(f"{char}：{style}" for char, style in tones.items())
            parts.append(
                f"角色语气规则（根据说话人调整中文风格）：{tone_rules}"
            )

    # 5. Core translation rules (always last — highest weight)
    parts.append("""翻译规则（按优先级执行）：
1. 只翻译对话和UI文字，不翻译括号内动作描述、系统提示
2. 保留原文省略号(...)、感叹号、问号和停顿节奏
3. 句子长度尽量接近原文，不补全不扩写不加解释
4. 区分说话人语气，按角色设定调整中文风格
5. 只输出简体中文翻译，一行一句，不加任何标记或注释""")

    sys_prompt = "\n\n".join(parts)
    user_msg = f"翻译以下日文游戏文本：\n\n{ocr_text}"

    return sys_prompt, user_msg


# ── Translation ────────────────────────────────────────────────

def translate_text(ocr_text: str, config: dict | None, scene: str | None) -> str:
    """Send extracted text to DeepSeek V4 for translation."""
    sys_prompt, user_msg = build_prompt(ocr_text, config, scene)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "stream": False,
        "thinking": {"type": "disabled"},
    }

    req = Request(
        f"{BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )

    resp = json.loads(urlopen(req, timeout=REQUEST_TIMEOUT).read())
    text = resp["choices"][0]["message"]["content"].strip()

    # CJK validation — repair if output has no Chinese characters
    if not _has_cjk(text):
        text = _repair_translation(ocr_text, sys_prompt)

    return text


def _has_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return any(
        "\u4E00" <= c <= "\u9FFF"  # CJK Unified
        or "\u3040" <= c <= "\u309F"  # Hiragana
        or "\u30A0" <= c <= "\u30FF"  # Katakana
        for c in text
    )


def _repair_translation(ocr_text: str, original_prompt: str) -> str:
    """Re-send as plain text if first attempt returned no CJK."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": original_prompt},
            {
                "role": "user",
                "content": (
                    "上一轮你只返回了原文/英文，没有翻译成中文。"
                    "请把以下内容翻译成简体中文，只输出译文：\n\n"
                    f"{ocr_text[:3000]}"
                ),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        req = Request(
            f"{BASE_URL.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp = json.loads(urlopen(req, timeout=REQUEST_TIMEOUT).read())
        return resp["choices"][0]["message"]["content"].strip()
    except Exception:
        return "[翻译失败，请重试]"


# ── OCR ────────────────────────────────────────────────────────

def extract_text(png_bytes: bytes) -> str:
    """Extract Japanese text from PNG screenshot using PaddleOCR."""
    ocr = get_ocr()
    results = ocr.ocr(png_bytes, cls=False)
    if not results or not results[0]:
        return ""
    lines = [item[1][0] for item in results[0] if item[1][0].strip()]
    return "\n".join(lines)


# ── HTTP Handler ───────────────────────────────────────────────

class TranslationHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send_json({"status": "ok", "model": MODEL})

    def do_POST(self):
        try:
            # Parse query params for game/scene
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            game_id = params.get("game", [None])[0]
            scene = params.get("scene", [None])[0]

            # Read request body
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            png_b64 = body.get("image", "")

            if not png_b64:
                self._send_json({"error": "Missing image field"})
                return

            # Decode PNG and run OCR
            png_bytes = base64.b64decode(png_b64)
            ocr_text = extract_text(png_bytes)

            if not ocr_text.strip():
                self._send_json({"text": "[未检测到文字]"})
                return

            # Load game config and translate
            config = load_game_config(game_id) if game_id else None
            result = translate_text(ocr_text, config, scene)

            self._send_json({"text": result})

        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON request body"})
        except Exception as e:
            self._send_json({"error": str(e)[:500]})

    def _send_json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Silent during gameplay


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: DEEPSEEK_API_KEY not set.", file=sys.stderr)
        print("  export DEEPSEEK_API_KEY=sk-...", file=sys.stderr)
        sys.exit(1)

    os.makedirs(CONFIG_DIR, exist_ok=True)

    print(f"RetroArch Translation Service on {LISTEN_HOST}:{LISTEN_PORT}")
    print(f"  Provider: {BASE_URL}")
    print(f"  Model: {MODEL}")
    print(f"  Config dir: {CONFIG_DIR}")
    print(f"  Press Ctrl+C to stop")
    print()

    # Warm up OCR (first call downloads model)
    print("Loading PaddleOCR model...")
    try:
        get_ocr()
        print("OCR ready.")
    except Exception as e:
        print(f"OCR load failed: {e}", file=sys.stderr)
        print("Install: pip install paddlepaddle paddleocr", file=sys.stderr)
        sys.exit(1)

    HTTPServer((LISTEN_HOST, LISTEN_PORT), TranslationHandler).serve_forever()
