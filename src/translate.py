"""Text translation — MT step."""

import json
import time
from typing import Any
from urllib.request import Request, urlopen

from . import config


def _api_call(url: str, payload: dict, key: str) -> dict:
    """POST with one retry.  Raises with HTTP status on failure."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(2):
        try:
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=config.REQUEST_TIMEOUT) as response:
                return json.loads(response.read())
        except Exception as exc:
            last_err = exc
            if attempt == 0:
                time.sleep(2)
    code_str = ""
    try:
        code_str = f"[{last_err.code}] " if hasattr(last_err, "code") else ""
    except Exception:
        pass
    raise RuntimeError(f"{code_str}{last_err}") from last_err


def _build_system_prompt(gc: dict[str, Any] | None) -> str:
    """Build a game-aware system prompt from a game config."""
    parts = ["将以下日文翻译成简体中文。只输出译文，不要解释。"]

    if gc:
        gloss = gc.get("glossary", {})
        if isinstance(gloss, dict) and gloss:
            terms = "\n".join(f"  {k} → {v}" for k, v in gloss.items())
            parts.append(f"固定术语（必须使用）：\n{terms}")

        sig = gc.get("signature_phrases", {})
        if isinstance(sig, dict) and sig:
            phrases = "\n".join(f"  {k} → {v}" for k, v in sig.items())
            parts.append(f"标志性台词（最高优先级，逐字使用）：\n{phrases}")

        tones = gc.get("character_tones", {})
        if isinstance(tones, dict) and tones:
            rules = "\n".join(f"  {k}：{v}" for k, v in tones.items())
            parts.append(f"角色语气（识别到说话人时应用）：\n{rules}")

    return "\n\n".join(parts)


def translate(ocr_text: str, game_config: dict[str, Any] | None = None) -> str:
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

    sys_prompt = _build_system_prompt(game_config)
    print(f"[MT] model={model} key={'***' if key else '(free)'} game={bool(game_config)}", flush=True)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
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
