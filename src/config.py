"""Configuration — all environment variables and constants."""

import os
from pathlib import Path

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

VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "https://api.siliconflow.cn/v1")
VISION_OCR_MODEL = os.environ.get("VISION_OCR_MODEL", "PaddlePaddle/PaddleOCR-VL-1.5")

TRANSLATE_API_KEY = os.environ.get("TRANSLATE_API_KEY", "")
TRANSLATE_BASE_URL = os.environ.get("TRANSLATE_BASE_URL", "https://api.siliconflow.cn/v1")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
TRANSLATE_MT_FREE_MODEL = os.environ.get("TRANSLATE_MT_FREE_MODEL", "tencent/Hunyuan-MT-7B")

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

_CACHE_MAX = int(os.environ.get("TRANSLATION_CACHE_SIZE", "128"))
_CJK_FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
