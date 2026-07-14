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
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


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
OCR_DEBUG_DIR = os.environ.get("OCR_DEBUG_DIR", "")
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "")  # "siliconflow" or "" (local OCR)
VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.siliconflow.cn/v1")

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

    det_kwargs = {
        "det_db_thresh": 0.2,
        "det_db_box_thresh": 0.35,
        "det_db_unclip_ratio": 1.8,
    }
    try:
        _ocr = PaddleOCR(
            lang="japan", use_angle_cls=False, show_log=False,
            **det_kwargs,
        )
    except ValueError:
        _ocr = PaddleOCR(
            lang="japan", use_textline_orientation=False,
            **det_kwargs,
        )
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


def _flatten_ocr_text(result: Any) -> list[tuple[str, float]]:
    """Walk PaddleOCR result tree, return (text, confidence) pairs."""
    pairs: list[tuple[str, float]] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for key in ("rec_texts", "texts"):
                values = node.get(key)
                if isinstance(values, list):
                    for item in values:
                        text = str(item).strip()
                        if text:
                            pairs.append((text, 1.0))
                    return
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                inner = node[1]
                text = inner[0] if isinstance(inner[0], str) else str(inner[0]) if inner[0] else ""
                try:
                    conf = float(inner[1]) if len(inner) >= 2 and inner[1] is not None else 0.5
                except (ValueError, TypeError):
                    conf = 0.5
                text = text.strip()
                if text:
                    pairs.append((text, conf))
                return
            for item in node:
                walk(item)

    walk(result)
    return pairs


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
                        try:
                            score = float(candidate[1] or 0)
                        except (ValueError, TypeError):
                            score = 0.0
                        text = candidate[0].strip()
                        if text and score > best_score:
                            best_text = text
                            best_score = score
        if best_text and best_score >= 0.45:
            lines.append(best_text)

    return list(dict.fromkeys(lines))


def _save_debug_image(image_or_path: Any, ocr_text: str, tag: str) -> None:
    """Save OCR input image + result text to OCR_DEBUG_DIR for inspection."""
    if not OCR_DEBUG_DIR:
        return
    import cv2
    debug_path = Path(OCR_DEBUG_DIR)
    debug_path.mkdir(parents=True, exist_ok=True)
    ts = tag.replace(" ", "_").replace("/", "-")
    # Save image
    image = cv2.imread(image_or_path) if isinstance(image_or_path, str) else image_or_path
    if image is not None:
        img_file = debug_path / f"{ts}.png"
        cv2.imwrite(str(img_file), image)
    # Save OCR result
    txt_file = debug_path / f"{ts}.txt"
    txt_file.write_text(ocr_text or "(EMPTY)", encoding="utf-8")


def _timestamp_tag() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _ocr_image(ocr: Any, image: Any) -> list[str]:
    """Run PaddleOCR detection+recognition, return quality-filtered text."""
    if hasattr(ocr, "ocr"):
        try:
            result = ocr.ocr(image, cls=False)
        except TypeError:
            result = ocr.ocr(image)
    elif hasattr(ocr, "predict"):
        result = ocr.predict(image)
    else:
        raise RuntimeError("Unsupported PaddleOCR API")
    pairs = _flatten_ocr_text(result)
    return [t for t, c in pairs if _is_likely_game_text(t, c)]


def _ocr_strips(ocr: Any, bgr: Any, num_strips: int = 10) -> list[str]:
    """Recognition-only OCR on horizontal strips — bypasses detection.

    GBA pixel fonts (8–12 px) are too small for PaddleOCR's detection
    model, but the *recognition* model reads them well when given the
    right image region.  Slicing the screen into horizontal bands and
    running rec-only on each strip catches text that detection misses.
    """
    import cv2
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    lines: list[str] = []
    strip_h = h // num_strips
    # Use overlapping strips (50 % overlap) so characters spanning a
    # boundary aren't cut in half.
    for i in range(num_strips * 2 - 1):
        y0 = (i * strip_h) // 2
        y1 = min(h, y0 + strip_h)
        if y1 - y0 < 8:
            continue
        strip = gray_bgr[y0:y1, :, :]
        try:
            result = ocr.ocr(strip, det=False, cls=False)
        except TypeError:
            result = ocr.ocr(strip, det=False)
        if result:
            for item in result[0] if isinstance(result, list) else result:
                if not (isinstance(item, (list, tuple)) and len(item) >= 2):
                    continue
                text = (item[0] if isinstance(item[0], str)
                        else str(item[0]) if item[0] else "").strip()
                if not text or len(text) < 2:
                    continue
                try:
                    conf = float(item[1]) if len(item) > 1 and item[1] is not None else 0.0
                except (ValueError, TypeError):
                    conf = 0.0
                if not _is_likely_game_text(text, conf):
                    continue
                lines.append(text)
    return list(dict.fromkeys(lines))


def _is_likely_game_text(text: str, confidence: float = 1.0) -> bool:
    """Filter OCR noise from real GBA game dialog text."""
    if len(text) < 3:
        return False
    if confidence < 0.42:
        return False
    return _has_min_japanese(text)


def _has_min_japanese(text: str) -> bool:
    """True when *text* has ≥3 kana/kanji and they make up ≥50 %."""
    kana_kanji = sum(
        1 for c in text
        if re.match(r"[぀-ゟ゠-ヿ一-鿿]", c) and c != "ー"
    )
    if kana_kanji < 3:
        return False
    if kana_kanji / len(text) < 0.50:
        return False
    return True


def extract_text(png_bytes: bytes) -> str:
    """Extract Japanese text from a RetroArch PNG screenshot.

    Uses two complementary strategies for GBA pixel fonts:

    1. **Strip rec-only** (primary) — slices the screen into horizontal
       bands and runs recognition-only OCR on each.  Bypasses detection
       entirely, which is the weak link for 8–12 px bitmap fonts.
    2. **Detection + recognition** (supplement) — standard PaddleOCR
       pipeline.  Catches text that strip OCR may fragment.

    Results from both passes are merged and deduplicated.
    """
    import cv2
    image_or_path = _decode_png_for_ocr(png_bytes)
    tag = _timestamp_tag()
    try:
        ocr = get_ocr()
        if isinstance(image_or_path, str):
            bgr = cv2.imread(image_or_path)
        else:
            bgr = image_or_path

        h, w = bgr.shape[:2]
        # Pick strip count based on screen height
        num_strips = max(6, h // 12)

        # ── Pass 1: strip rec-only (primary) ──
        strip_lines = _ocr_strips(ocr, bgr, num_strips)
        source = f"strips({len(strip_lines)})"

        # ── Pass 2: standard detection+recognition ──
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        det_lines: list[str] = []
        for attempt, candidate in [("gray", gray_bgr), ("color", bgr)]:
            det_lines = _ocr_image(ocr, candidate)
            if det_lines:
                source += f" + det+rec[{attempt}]({len(det_lines)})"
                break
        if not det_lines:
            source += " + det+rec[miss]"

        # ── Pass 3: Tesseract OCR (complementary engine) ──
        tess_lines = _ocr_tesseract(bgr)
        if tess_lines:
            source += f" + tesseract({len(tess_lines)})"
        else:
            source += " + tesseract[miss]"

        # ── Merge, deduplicate & quality-filter ──
        lines = list(dict.fromkeys(strip_lines + det_lines + tess_lines))
        before = len(lines)
        lines = [l for l in lines if _has_min_japanese(l)]
        if before != len(lines):
            source += f" (filtered {before - len(lines)} noise)"

        # ── Fallbacks ──
        if not lines:
            lines = _recognize_fallback_regions(ocr, bgr)
            source = "fallback_regions"
        if not lines:
            try:
                full_result = ocr.ocr(gray_bgr, det=False, cls=False)
            except TypeError:
                full_result = ocr.ocr(gray_bgr, det=False)
            if full_result:
                full_pairs = _flatten_ocr_text(full_result)
                lines = [t for t, c in full_pairs if _is_likely_game_text(t, c)]
                source = "full_image_rec"

        ocr_text = "\n".join(lines)
        if ocr_text:
            print(f"[OCR] {len(lines)} line(s) via {source}: {ocr_text}", flush=True)
        else:
            print("[OCR] EMPTY — no visible characters detected", flush=True)
        _save_debug_image(bgr, ocr_text, f"{tag}_ocr")
        return ocr_text
    finally:
        if isinstance(image_or_path, str):
            Path(image_or_path).unlink(missing_ok=True)


# ── Tesseract OCR (complementary engine) ────────────────────────

def _ocr_tesseract(bgr: Any) -> list[str]:
    """Run Tesseract Japanese OCR as a complementary text source.

    Tesseract's LSTM model reads pixel fonts differently than
    PaddleOCR — running both in parallel catches text that either
    engine misses on its own.
    """
    try:
        import pytesseract  # type: ignore
        import cv2
    except ModuleNotFoundError:
        return []

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Tesseract works better with binarized images for pixel fonts
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    try:
        text = pytesseract.image_to_string(
            binary, lang="jpn",
            config="--psm 6",
        )
    except Exception:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Apply same quality filter as PaddleOCR results
    return [l for l in lines if _has_min_japanese(l)]


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


# ── Vision API Translation (SiliconFlow DeepSeek-OCR) ────────────

_VISION_SYSTEM_PROMPT = """你是 RetroArch GBA 日文游戏的实时翻译器。

这张截图来自 GBA 游戏（240×160 像素），请仔细识别画面中的日文像素文字，将其翻译成简体中文。

规则：
1. 只输出简体中文译文，一行一句，不加解释或标记。
2. 只翻译游戏对话和 UI 文字，不扩写或补剧情。
3. 保留原文的省略号、感叹号、问号和停顿节奏。
4. 截图中的角色名字（如成步堂/御剑/真宵/审判长）直接使用中文名，根据角色语气调整翻译风格。
5. 像素字体可能有残缺笔画，请根据上下文推断正确文字。"""


def translate_via_vision(png_b64: str) -> str:
    """Send screenshot to SiliconFlow DeepSeek-OCR for end-to-end translation.

    One API call replaces the entire local-OCR + translate pipeline.
    """
    if not VISION_API_KEY:
        raise RuntimeError("VISION_API_KEY is not set")

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{png_b64}",
                }},
            ]},
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "stream": False,
    }
    url = f"{VISION_BASE_URL.rstrip('/')}/chat/completions"
    print(
        f"[Vision request] provider=siliconflow model={VISION_MODEL} "
        f"image_len={len(png_b64)}",
        flush=True,
    )
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
    print(
        "[Vision response] "
        + json.dumps(data, ensure_ascii=False)[:500],
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
            all_output_vals = params.get("output", [])
            combined_raw = ",".join(v for v in all_output_vals if v)
            output_modes = parse_output_modes(combined_raw if combined_raw else None)
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

            if VISION_PROVIDER == "siliconflow":
                # ── Vision mode: screenshot → DeepSeek-OCR (one call) ──
                translated = translate_via_vision(png_b64)
                print(f"[Vision] → {translated}", flush=True)
            else:
                # ── Local OCR + DeepSeek translation ──
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
    if VISION_PROVIDER == "siliconflow":
        print(f"  Translation: Vision API — {VISION_MODEL} @ {VISION_BASE_URL}")
    else:
        print(f"  OCR: PaddleOCR + Tesseract (lazy-loaded on first POST)")
        print(f"  Provider: {BASE_URL}")
        print(f"  Model: {MODEL}")
    print(f"  Config path: {GAME_CONFIG_PATH}")
    print(f"  User config dir: {CONFIG_DIR}")
    if not CONFIG_DIR.exists():
        print("  User config dir does not exist; using project game_config.yaml only.")
    print(f"  Loaded game configs: {len(configs)}")
    if not API_KEY:
        print("  Warning: DEEPSEEK_API_KEY is not set; translation calls will return an error.")
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
