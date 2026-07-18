"""HTTP server — RetroArch AI Service protocol handler + web UI."""

import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import config, cache, ocr, translate, overlay, game_config


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


def json_response(handler: BaseHTTPRequestHandler, data: dict[str, Any]) -> None:
    print(f"[Response] {json.dumps(data, ensure_ascii=False)}", flush=True)
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


SETTINGS_DEFAULTS = {
    "vision_api_key": "",
    "vision_base_url": "https://api.siliconflow.cn/v1",
    "vision_ocr_model": "PaddlePaddle/PaddleOCR-VL-1.5",
    "translate_api_key": "",
    "translate_base_url": "https://api.siliconflow.cn/v1",
    "translate_model": "deepseek-ai/DeepSeek-V4-Flash",
}


def _load_service_settings() -> dict[str, Any]:
    """Load saved settings, falling back to current config module values."""
    base = {
        "vision_api_key": config.VISION_API_KEY,
        "vision_base_url": config.VISION_BASE_URL,
        "vision_ocr_model": config.VISION_OCR_MODEL,
        "translate_api_key": config.TRANSLATE_API_KEY,
        "translate_base_url": config.TRANSLATE_BASE_URL,
        "translate_model": config.TRANSLATE_MODEL,
    }
    try:
        path = config.SERVICE_SETTINGS_PATH
        if path.exists():
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return {**base, **data}
    except Exception:
        pass
    return base


def _save_service_settings(data: dict[str, Any]) -> None:
    path = config.SERVICE_SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _settings_ui(saved: bool = False) -> str:
    s = _load_service_settings()
    msg = '<p style="color:#4caf50;text-align:center">✅ 设置已保存，服务已自动应用</p>' if saved else ""

    def row(label: str, key: str, pw: bool = False) -> str:
        val = s.get(key, "")
        t = "password" if pw else "text"
        return f"""<label style="display:block;margin-top:0.8em;font-weight:600">{label}</label>
        <input type="{t}" name="{key}" value="{val.replace(chr(34), '&quot;')}" style="width:100%;padding:0.5em;font-size:1em;box-sizing:border-box">"""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API Settings — RetroArch AI Translation</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 520px; margin: 2em auto; padding: 0 1em; }}
  h1 {{ font-size: 1.3em; }}
  button {{ font-size: 1.1em; padding: 0.6em; width: 100%; margin-top: 1.2em; background: #4caf50; color: #fff; border: none; border-radius: 6px; cursor: pointer; }}
  a {{ color: #888; }}
</style>
</head>
<body>
<h1>🔑 API 设置</h1>
<p style="color:#888;font-size:0.85em">在电脑或手机上打开此页面，粘贴 API Key 更方便</p>
{msg}
<form method="post" action="/settings">
  {row("Vision API Key", "vision_api_key", pw=True)}
  {row("Vision API URL", "vision_base_url")}
  {row("Vision OCR Model", "vision_ocr_model")}
  {row("Translate API Key（可选）", "translate_api_key", pw=True)}
  {row("Translate API URL", "translate_base_url")}
  {row("Translate Model", "translate_model")}
  <button type="submit">💾 保存设置</button>
</form>
<p style="text-align:center;margin-top:1.5em"><a href="/">← 返回首页</a></p>
	<p style="text-align:center;margin-top:1em">
	  <a href="/settings" style="color:#888">⚙️ API 设置</a>
	</p>
</body>
</html>"""


def _web_ui(current_id: str, client_ip: str = "") -> str:
    configs = game_config.load_all()
    options = []
    for gc in configs:
        gid = gc.get("game_id", "")
        name = gc.get("display_name", gid)
        sel = " selected" if gid == current_id else ""
        options.append(f'<option value="{gid}"{sel}>{name} ({gid})</option>')

    ip_info = f"设备 IP：{client_ip}" if client_ip else ""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RetroArch AI Translation</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 480px; margin: 2em auto; padding: 0 1em; }}
  select, button {{ font-size: 1.1em; padding: 0.5em; width: 100%; margin: 0.5em 0; }}
  .status {{ padding: 1em; border-radius: 8px; margin: 1em 0; }}
  .active {{ background: #d4edda; }}
  .none {{ background: #fff3cd; }}
  .ip-info {{ color: #888; font-size: 0.85em; margin-bottom: 0.5em; }}
</style>
</head>
<body>
<h1>RetroArch AI Translation</h1>
<p class="ip-info">{ip_info}</p>
<div class="status {'active' if current_id else 'none'}">
  当前游戏：<strong>{current_id or '未设置（自动检测或使用术语表）'}</strong>
</div>
<form method="post" action="/set-game">
  <select name="game_id">
    <option value="">-- 自动检测 --</option>
    {''.join(options)}
  </select>
  <button type="submit">切换游戏</button>
</form>
<p style="color:#888;font-size:0.9em;">
  服务已加载 {len(configs)} 个游戏配置。选择"自动检测"将根据 RetroArch 发送的游戏标识自动匹配配置。
</p>
	<p style="text-align:center;margin-top:1em">
	  <a href="/settings" style="color:#888">⚙️ API 设置</a>
	</p>
</body>
</html>"""


class TranslationHandler(BaseHTTPRequestHandler):
    server_version = "RetroArchAI/3.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        client_ip = self.client_address[0]
        if parsed.path == "/" or parsed.path == "/index.html":
            current_id = game_config.get_game_for_ip(client_ip)
            if not current_id:
                current_id = game_config.get_game_for_ip("_default")
            html_response(self, _web_ui(current_id, client_ip))
        elif parsed.path == "/settings":
            html_response(self, _settings_ui())
        else:
            mt_model = config.TRANSLATE_MODEL if config.TRANSLATE_API_KEY else config.TRANSLATE_MT_FREE_MODEL
            json_response(self, {
                "status": "ok",
                "service": "retroarch-ai-translation",
                "current_game": game_config.current_game_id or None,
                "pipeline": f"{config.VISION_OCR_MODEL} → {mt_model}",
                "config_path": str(config.GAME_CONFIG_PATH),
                "config_dir": str(config.CONFIG_DIR),
            })

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        # ── /settings — save API settings ──
        if parsed.path == "/settings":
            length = int(self.headers.get("Content-Length", "0"))
            body = parse_qs(self.rfile.read(length).decode("utf-8"))
            data = _load_service_settings()
            for key in SETTINGS_DEFAULTS:
                val = body.get(key, [""])[0].strip()
                if val:
                    data[key] = val
            _save_service_settings(data)
            # Apply to both os.environ and config globals so the running
            # service picks up changes immediately (config vars are read
            # once at import time, not re-read from os.environ per request).
            for key in SETTINGS_DEFAULTS:
                val = data.get(key, "")
                if val:
                    os.environ[key.upper()] = val
                    setattr(config, key.upper(), val)
            html_response(self, _settings_ui(saved=True))
            return

        # ── /set-game — switch current game for this device ──
        if parsed.path == "/set-game":
            client_ip = self.client_address[0]
            length = int(self.headers.get("Content-Length", "0"))
            body = parse_qs(self.rfile.read(length).decode("utf-8"))
            game_id = body.get("game_id", [""])[0].strip()
            game_config.set_game_for_ip(client_ip, game_id)
            if not game_id:
                game_id = game_config.get_game_for_ip("_default")
            print(f"[Game] IP {client_ip} set to '{game_id or 'auto-detect'}'", flush=True)
            html_response(self, _web_ui(game_id or "", client_ip) + "<script>location.href='/'</script>")
            return

        # ── AI Service endpoint ──
        png_bytes = None
        try:
            params = parse_qs(parsed.query)
            all_output_vals = params.get("output", [])
            combined_raw = ",".join(v for v in all_output_vals if v)
            output_modes = parse_output_modes(combined_raw if combined_raw else None)

            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                json_response(self, {"error": "Missing JSON request body"})
                return

            request_body = self.rfile.read(length)
            body = json.loads(request_body)
            if not isinstance(body, dict):
                json_response(self, {"error": "JSON request body must be an object"})
                return

            png_b64 = body.get("image")
            if not isinstance(png_b64, str) or not png_b64.strip():
                json_response(self, {"error": "Missing required image field"})
                return

            try:
                png_bytes = base64.b64decode(png_b64, validate=True)
            except Exception:
                json_response(self, {"error": "image must be base64-encoded PNG bytes"})
                return

            # Resolve game: IP override > label auto-detect > default
            client_ip = self.client_address[0]
            label = body.get("label")
            game_id = (
                game_config.get_game_for_ip(client_ip)
                or game_config.resolve(None, label)
                or game_config.get_game_for_ip("_default")
            )
            if game_id:
                print(f"[Game] resolved '{game_id}' (IP={client_ip}, label={label!r})", flush=True)
            gc = game_config.load(game_id)

            cached = cache.get(png_bytes)
            if cached is not None:
                translated = cached
                print("[Cache] hit", flush=True)
            else:
                ocr_text = ocr.extract_text(png_b64)
                if not ocr_text.strip():
                    translated = "[未检测到文字]"
                else:
                    translated = translate.translate(ocr_text, gc)
                    if not translated.strip():
                        translated = "[翻译失败]"
                    else:
                        cache.put(png_bytes, translated)

            response: dict[str, Any] = {
                "text": translated,
                "text_position": config.TEXT_POSITION_BOTTOM,
            }

            if "image" in output_modes:
                vp = body.get("viewport")
                viewport = (int(vp[0]), int(vp[1])) if vp and len(vp) >= 2 else None
                try:
                    overlay_bytes = overlay.render(
                        text=translated,
                        source_png_bytes=png_bytes,
                        viewport=viewport,
                        text_position=config.TEXT_POSITION_BOTTOM,
                        game_cfg=gc,
                    )
                    response["image"] = base64.b64encode(overlay_bytes).decode("ascii")
                except Exception as exc:
                    print(f"[Image render failed] {exc}", flush=True)

            if "text" not in output_modes and "image" not in output_modes:
                actual_modes = ", ".join(sorted(output_modes)) if output_modes else "default"
                print(
                    f"[MODE WARNING] RetroArch output mode is '{actual_modes}', "
                    f"but this service returns text + image only. "
                    f"Fix: Settings → AI Service → AI Service Mode → Image (mode 0).",
                    flush=True,
                )

            json_response(self, response)

        except json.JSONDecodeError:
            json_response(self, {"error": "Invalid JSON request body"})
        except Exception as exc:
            err_text = f"[服务错误] {exc!s}"[:500]
            print(f"[ERROR] {exc}", flush=True)
            resp: dict[str, Any] = {"error": err_text}
            try:
                if png_bytes:
                    ov = overlay.render(err_text, png_bytes)
                    resp["image"] = base64.b64encode(ov).decode("ascii")
            except Exception:
                pass
            json_response(self, resp)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), fmt % args)
        )
