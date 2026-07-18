"""SiliconFlow Vision API — OCR step."""

import json
import os
import ssl
import time
from urllib.request import Request, urlopen

from . import config

# SteamOS / Arch Linux may ship with an incomplete CA certificate store.
# Use an unverified SSL context — safe enough for this use case since
# we call well-known API endpoints from a local gaming device.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _api_call(url: str, payload: dict, key: str) -> dict:
    """POST with one retry.  Raises with HTTP status on failure."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(2):
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=config.REQUEST_TIMEOUT, context=_SSL_CTX) as response:
                return json.loads(response.read())
        except Exception as exc:
            last_err = exc
            if attempt == 0:
                time.sleep(2)
    # Build error with HTTP status if available
    code_str = ""
    try:
        code_str = f"[{last_err.code}] " if hasattr(last_err, "code") else ""
    except Exception:
        pass
    raise RuntimeError(f"{code_str}{last_err}") from last_err


def call(model: str, messages: list[dict], max_tokens: int = 512) -> str:
    """Single SiliconFlow chat-completion call."""
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }
    # Only DeepSeek models support (and need) thinking-disabled
    if "deepseek" in model.lower():
        payload["thinking"] = {"type": "disabled"}
    url = f"{config.VISION_BASE_URL.rstrip('/')}/chat/completions"
    data = _api_call(url, payload, config.VISION_API_KEY)
    return data["choices"][0]["message"]["content"].strip()


def extract_text(png_b64: str) -> str:
    """OCR: screenshot → Japanese text.

    Reads API settings from ``os.environ`` so changes via the web UI or
    Decky QAM take effect immediately without a server restart.
    """
    model = os.environ.get("VISION_OCR_MODEL", config.VISION_OCR_MODEL)
    base_url = os.environ.get("VISION_BASE_URL", config.VISION_BASE_URL)
    api_key = os.environ.get("VISION_API_KEY", config.VISION_API_KEY)

    print(f"[OCR] model={model}", flush=True)
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {
            "url": f"data:image/png;base64,{png_b64}",
        }},
        {"type": "text", "text": "请识别这张GBA游戏截图中的所有日文文字，只输出文字，不要解释。"},
    ]}]
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.1,
        "stream": False,
    }
    if "deepseek" in model.lower():
        payload["thinking"] = {"type": "disabled"}
    url = f"{base_url.rstrip('/')}/chat/completions"
    data = _api_call(url, payload, api_key)
    text = data["choices"][0]["message"]["content"].strip()
    print(f"[OCR] → {text}", flush=True)
    return text
