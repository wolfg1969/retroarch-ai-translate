"""Text translation — MT step."""

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


def translate(ocr_text: str) -> str:
    """Japanese → Chinese.  Uses TRANSLATE_API_KEY if set, otherwise
    falls back to the free Hunyuan-MT-7B on SiliconFlow."""
    if config.TRANSLATE_API_KEY:
        model = config.TRANSLATE_MODEL
        url = f"{config.TRANSLATE_BASE_URL.rstrip('/')}/chat/completions"
        key = config.TRANSLATE_API_KEY
    else:
        model = config.TRANSLATE_MT_FREE_MODEL
        url = f"{config.VISION_BASE_URL.rstrip('/')}/chat/completions"
        key = config.VISION_API_KEY

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
    data = _api_call(url, payload, key)
    translated = data["choices"][0]["message"]["content"].strip()
    print(f"[MT] → {translated}", flush=True)
    return translated
