"""Text translation — MT step."""

import json
import os
import ssl
import time
from typing import Any
from urllib.request import Request, urlopen

from . import config

# SteamOS / Arch Linux may ship with an incomplete CA certificate store.
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
            parts.append(
                "格式要求：若识别到说话人，第一行只输出角色名（如「成步堂」），"
                "第二行起输出译文；若无法识别说话人，直接输出译文。"
            )

    return "\n\n".join(parts)


def translate(ocr_text: str, game_config: dict[str, Any] | None = None) -> str:
    """Japanese → Chinese.  Uses TRANSLATE_API_KEY if set, otherwise
    falls back to the free Hunyuan-MT-7B on SiliconFlow.

    Reads API settings from ``os.environ`` so changes via the web UI or
    Decky QAM take effect immediately without a server restart.
    """
    translate_key = os.environ.get("TRANSLATE_API_KEY", config.TRANSLATE_API_KEY)
    if translate_key:
        model = os.environ.get("TRANSLATE_MODEL", config.TRANSLATE_MODEL)
        url_base = os.environ.get("TRANSLATE_BASE_URL", config.TRANSLATE_BASE_URL)
        key = translate_key
    else:
        model = os.environ.get("TRANSLATE_MT_FREE_MODEL", config.TRANSLATE_MT_FREE_MODEL)
        url_base = os.environ.get("VISION_BASE_URL", config.VISION_BASE_URL)
        key = os.environ.get("VISION_API_KEY", config.VISION_API_KEY)

    url = f"{url_base.rstrip('/')}/chat/completions"

    sys_prompt = _build_system_prompt(game_config)
    print(f"[MT] model={model} key={'***' if key else '(free)'} game={bool(game_config)}", flush=True)
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": ocr_text},
        ],
        "max_tokens": 1024,
        "temperature": 0.1,
        "stream": False,
    }
    if "deepseek" in model.lower():
        payload["thinking"] = {"type": "disabled"}
    data = _api_call(url, payload, key)
    choice = data["choices"][0]
    translated = (choice.get("message", {}).get("content", "") or "").strip()
    if not translated:
        finish = choice.get("finish_reason", "?")
        print(f"[MT] EMPTY (finish_reason={finish}): {json.dumps(data, ensure_ascii=False)[:300]}", flush=True)
        # Retry once more if we got empty content (some APIs return empty on content filter)
        if finish != "stop":
            time.sleep(1)
            data = _api_call(url, payload, key)
            choice = data["choices"][0]
            translated = (choice.get("message", {}).get("content", "") or "").strip()
    print(f"[MT] → {translated}", flush=True)
    return translated
