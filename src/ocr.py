"""SiliconFlow Vision API — OCR step."""

import json
import time
from urllib.request import Request, urlopen

from . import config


def _api_call(url: str, payload: dict, key: str) -> dict:
    """POST with one retry for transient network errors."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(2):
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=config.REQUEST_TIMEOUT) as response:
                return json.loads(response.read())
        except Exception:
            if attempt == 0:
                time.sleep(2)
                continue
            raise


def call(model: str, messages: list[dict], max_tokens: int = 512) -> str:
    """Single SiliconFlow chat-completion call."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }
    url = f"{config.VISION_BASE_URL.rstrip('/')}/chat/completions"
    data = _api_call(url, payload, config.VISION_API_KEY)
    return data["choices"][0]["message"]["content"].strip()


def extract_text(png_b64: str) -> str:
    """OCR: screenshot → Japanese text."""
    print(f"[OCR] model={config.VISION_OCR_MODEL}", flush=True)
    text = call(
        model=config.VISION_OCR_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{png_b64}",
            }},
            {"type": "text", "text": "请识别这张GBA游戏截图中的所有日文文字，只输出文字，不要解释。"},
        ]}],
    )
    print(f"[OCR] → {text}", flush=True)
    return text
