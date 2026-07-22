"""Text translation — MT step."""

import json
import os
import ssl
import time
from typing import Any
from urllib.request import Request, urlopen

from . import config

TRANSLATION_PROMPT_VERSION = 2

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
    parts = [
        "将以下日文完整翻译成简体中文。只输出译文，不要解释。",
        "完整性要求：不得省略、合并或概括任何可见文字。输入若有多行，输出必须按原顺序逐行对应并保留相同行数；菜单标题、操作提示和每个选项都必须翻译。",
        "角色规则：只有当输入明确是『角色名单独一行 + 对话正文』时，才把第一行作为说话人。菜单选项中出现角色名不代表该角色正在说话。",
        "防替规则：绝不能用已知角色名替换不认识的说话人。输入中的说话人姓名如果在术语表或角色列表中找不到，请按发音音译；不要猜测、也不要改写成其他已知角色。",
    ]

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
                "格式要求：仅当输入明确为说话人姓名单独占据第一行、后续为其对话正文时，"
                "第一行输出角色名，第二行起输出译文。菜单、选项列表或无法确认说话人时，"
                "逐行翻译全部内容，不要猜测说话人。"
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
    source_lines = [line for line in ocr_text.splitlines() if line.strip()]
    translated_lines = [line for line in translated.splitlines() if line.strip()]
    if len(source_lines) > 1 and len(translated_lines) < len(source_lines):
        print(
            f"[MT] INCOMPLETE ({len(translated_lines)}/{len(source_lines)} lines), retrying",
            flush=True,
        )
        retry_payload = dict(payload)
        retry_payload["messages"] = [
            payload["messages"][0],
            payload["messages"][1],
            {"role": "assistant", "content": translated},
            {
                "role": "user",
                "content": (
                    f"上次译文遗漏了内容。原文共有 {len(source_lines)} 个非空行，"
                    f"请重新翻译全部内容，严格输出 {len(source_lines)} 个非空行，"
                    "与原文逐行对应、顺序一致，不要省略菜单标题或任何选项。"
                ),
            },
        ]
        retry_data = _api_call(url, retry_payload, key)
        retry_choice = retry_data["choices"][0]
        retry_text = (
            retry_choice.get("message", {}).get("content", "") or ""
        ).strip()
        retry_lines = [line for line in retry_text.splitlines() if line.strip()]
        if len(retry_lines) >= len(translated_lines):
            data = retry_data
            choice = retry_choice
            translated = retry_text
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
