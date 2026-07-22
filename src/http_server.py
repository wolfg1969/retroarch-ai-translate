"""HTTP server — RetroArch AI Service protocol handler + web UI."""

import base64
import html
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


def json_response(
    handler: BaseHTTPRequestHandler,
    data: dict[str, Any],
    *,
    log_payload: bool = True,
) -> None:
    if log_payload:
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
    settings = _load_service_settings()
    msg = (
        '<p class="saved">✅ 设置已保存，服务已自动应用</p>'
        if saved else ""
    )

    def row(label: str, key: str, pw: bool = False) -> str:
        configured = bool(settings.get(key))
        input_type = "password" if pw else "text"
        value = "" if pw else html.escape(str(settings.get(key, "")), quote=True)
        placeholder = "已配置，留空保持不变" if pw and configured else ""
        return f"""<label>{html.escape(label, quote=True)}</label>
        <input type="{input_type}" name="{html.escape(key, quote=True)}"
          value="{value}" placeholder="{html.escape(placeholder, quote=True)}">"""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Settings — RetroArch AI Translate</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; max-width: 880px; margin: 2em auto; padding: 0 1em; }}
  h1 {{ font-size: 1.35em; }}
  h2 {{ margin: 1.8em 0 0.5em; font-size: 1.15em; }}
  label {{ display:block; margin-top:0.8em; font-weight:600; }}
  input {{ width:100%; padding:0.55em; font-size:1em; box-sizing:border-box; }}
  button {{ padding:0.55em 0.8em; border:0; border-radius:6px; cursor:pointer; }}
  .primary {{ width:100%; margin-top:1.2em; font-size:1.05em; background:#388e3c; color:#fff; }}
  .saved {{ color:#4caf50; text-align:center; }}
  .muted {{ color:#888; font-size:0.85em; }}
  .log-toolbar {{ display:flex; flex-wrap:wrap; gap:0.5em; align-items:center; margin:0.7em 0; }}
  .log-toolbar button {{ background:#555; color:#fff; }}
  .log-filter {{ flex:1 1 220px; min-width:0; }}
  #log-view {{ height:420px; overflow:auto; background:#111; color:#ddd; padding:10px;
    font:12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space:pre-wrap;
    word-break:break-word; border-radius:6px; border:1px solid #444; }}
  #log-status {{ min-height:1.3em; }}
  .footer {{ text-align:center; margin:1.5em 0; }}
  a {{ color:#888; }}
  @media (max-width:600px) {{ body {{ margin-top:1em; }} #log-view {{ height:55vh; }} }}
</style>
</head>
<body>
<h1>⚙️ API 设置</h1>
<p class="muted">密码字段留空会保留现有密钥。日志可能包含游戏文字与客户端 IP。</p>
{msg}
<form method="post" action="/settings">
  {row("Vision API Key", "vision_api_key", pw=True)}
  {row("Vision API URL", "vision_base_url")}
  {row("Vision OCR Model", "vision_ocr_model")}
  {row("Translate API Key（可选）", "translate_api_key", pw=True)}
  {row("Translate API URL", "translate_base_url")}
  {row("Translate Model", "translate_model")}
  <button class="primary" type="submit">💾 保存设置</button>
</form>

<h2>📋 服务日志</h2>
<p class="muted">最多保留最近 1000 行；页面默认实时增量刷新。</p>
<div class="log-toolbar">
  <button id="log-pause" type="button">暂停</button>
  <button id="log-refresh" type="button">立即刷新</button>
  <button id="log-scroll" type="button">自动滚动：开</button>
  <button id="log-copy" type="button">复制</button>
  <button id="log-download" type="button">下载</button>
  <input id="log-filter" class="log-filter" type="search" placeholder="筛选日志…">
</div>
<div id="log-status" class="muted">正在连接日志…</div>
<div id="log-view" role="log" aria-live="polite"></div>

<p class="footer"><a href="/">← 返回首页</a></p>
<script>
(() => {{
  const capacity = 1000;
  const view = document.getElementById("log-view");
  const status = document.getElementById("log-status");
  const filter = document.getElementById("log-filter");
  const pauseButton = document.getElementById("log-pause");
  const scrollButton = document.getElementById("log-scroll");
  let records = [];
  let cursor = null;
  let paused = false;
  let autoScroll = true;
  let loading = false;

  function visibleText() {{
    const term = filter.value.toLowerCase();
    return records
      .filter(item => !term || item.text.toLowerCase().includes(term))
      .map(item => item.text)
      .join("\\n");
  }}

  function render(message = "") {{
    const text = visibleText();
    view.textContent = text;
    if (autoScroll) view.scrollTop = view.scrollHeight;
    const shown = text ? text.split("\\n").length : 0;
    status.textContent = message || `${{shown}} 行显示 / ${{records.length}} 行保留${{paused ? " · 已暂停" : ""}}`;
  }}

  async function loadLogs(reset = false) {{
    if (loading || (paused && !reset) || document.hidden) return;
    loading = true;
    try {{
      const query = reset || cursor === null
        ? "?lines=500"
        : `?lines=1000&after=${{encodeURIComponent(cursor)}}`;
      const response = await fetch("/logs" + query, {{ cache: "no-store" }});
      const data = await response.json();
      if (reset || cursor === null || data.truncated) records = [];
      if (Array.isArray(data.logs)) records.push(...data.logs);
      records = records.slice(-capacity);
      cursor = Number.isInteger(data.cursor) ? data.cursor : cursor;
      render(data.error ? "日志读取失败：" + data.error : (data.truncated ? "较早日志已淘汰，已重新同步" : ""));
    }} catch (error) {{
      render("日志连接失败：" + String(error));
    }} finally {{
      loading = false;
    }}
  }}

  pauseButton.addEventListener("click", () => {{
    paused = !paused;
    pauseButton.textContent = paused ? "继续" : "暂停";
    render();
    if (!paused) loadLogs(false);
  }});
  document.getElementById("log-refresh").addEventListener("click", () => loadLogs(true));
  scrollButton.addEventListener("click", () => {{
    autoScroll = !autoScroll;
    scrollButton.textContent = "自动滚动：" + (autoScroll ? "开" : "关");
    render();
  }});
  view.addEventListener("scroll", () => {{
    const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 30;
    if (!atBottom && autoScroll) {{
      autoScroll = false;
      scrollButton.textContent = "自动滚动：关";
    }}
  }});
  filter.addEventListener("input", () => render());
  document.getElementById("log-copy").addEventListener("click", async () => {{
    try {{
      const text = visibleText();
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {{
        await navigator.clipboard.writeText(text);
      }} else {{
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("浏览器不支持自动复制");
      }}
      render("日志已复制");
    }} catch (error) {{
      render("复制失败：" + String(error));
    }}
  }});
  document.getElementById("log-download").addEventListener("click", () => {{
    const url = URL.createObjectURL(new Blob([visibleText() + "\\n"], {{ type:"text/plain;charset=utf-8" }}));
    const link = document.createElement("a");
    link.href = url;
    link.download = "retroarch-ai-translate.log";
    link.click();
    URL.revokeObjectURL(url);
  }});
  document.addEventListener("visibilitychange", () => {{ if (!document.hidden) loadLogs(false); }});
  loadLogs(true);
  setInterval(() => loadLogs(false), 2000);
}})();
</script>
</body>
</html>"""


def _web_ui(current_id: str, client_ip: str = "") -> str:
    configs = game_config.load_all()
    options = []
    for gc in configs:
        gid = str(gc.get("game_id", ""))
        name = str(gc.get("display_name", gid))
        sel = " selected" if gid == current_id else ""
        escaped_gid = html.escape(gid, quote=True)
        escaped_name = html.escape(name, quote=True)
        options.append(
            f'<option value="{escaped_gid}"{sel}>{escaped_name} ({escaped_gid})</option>'
        )

    ip_info = f"设备 IP：{html.escape(client_ip, quote=True)}" if client_ip else ""
    escaped_current = html.escape(
        current_id or "未设置（自动检测或使用术语表）", quote=True
    )

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RetroArch AI Translate</title>
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
<h1>RetroArch AI Translate</h1>
<p class="ip-info">{ip_info}</p>
<div class="status {'active' if current_id else 'none'}">
  当前游戏：<strong>{escaped_current}</strong>
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


def _pipeline_cache_context(game_cfg: dict[str, Any] | None) -> str:
    """Fingerprint game config and effective output-affecting AI settings."""
    translate_key = os.environ.get("TRANSLATE_API_KEY", config.TRANSLATE_API_KEY)
    if translate_key:
        translate_model = os.environ.get("TRANSLATE_MODEL", config.TRANSLATE_MODEL)
        translate_base_url = os.environ.get(
            "TRANSLATE_BASE_URL", config.TRANSLATE_BASE_URL
        )
        translate_mode = "configured"
    else:
        translate_model = os.environ.get(
            "TRANSLATE_MT_FREE_MODEL", config.TRANSLATE_MT_FREE_MODEL
        )
        translate_base_url = os.environ.get("VISION_BASE_URL", config.VISION_BASE_URL)
        translate_mode = "free"

    return game_config.config_fingerprint({
        "game": game_cfg,
        "vision": {
            "model": os.environ.get("VISION_OCR_MODEL", config.VISION_OCR_MODEL),
            "base_url": os.environ.get("VISION_BASE_URL", config.VISION_BASE_URL),
        },
        "translation": {
            "prompt_version": translate.TRANSLATION_PROMPT_VERSION,
            "mode": translate_mode,
            "model": translate_model,
            "base_url": translate_base_url,
        },
    })


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
        elif parsed.path == "/logs":
            try:
                from .log_buffer import LOG_CAPACITY, snapshot_logs

                params = parse_qs(parsed.query)
                try:
                    lines = int(params.get("lines", ["500"])[0])
                except (TypeError, ValueError):
                    lines = 500
                lines = max(1, min(lines, LOG_CAPACITY))
                after_raw = params.get("after", [None])[0]
                try:
                    after = int(after_raw) if after_raw is not None else None
                except (TypeError, ValueError):
                    after = None
                json_response(
                    self,
                    snapshot_logs(lines=lines, after=after),
                    log_payload=False,
                )
            except Exception:
                json_response(
                    self,
                    {
                        "logs": [],
                        "cursor": 0,
                        "truncated": False,
                        "capacity": 1000,
                        "error": "日志暂时不可用",
                    },
                    log_payload=False,
                )
        else:
            mt_model = config.TRANSLATE_MODEL if config.TRANSLATE_API_KEY else config.TRANSLATE_MT_FREE_MODEL
            json_response(self, {
                "status": "ok",
                "service": "retroarch-ai-translate",
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
            cache_context = _pipeline_cache_context(gc)

            cached = cache.get(png_bytes, cache_context)
            if cached is not None:
                translated = cached
                print("[Cache] hit", flush=True)
            else:
                ocr_text = ocr.extract_text(png_b64, gc)
                if not ocr_text.strip():
                    translated = "[未检测到文字]"
                else:
                    translated = translate.translate(ocr_text, gc)
                    if not translated.strip():
                        translated = "[翻译失败]"
                    else:
                        cache.put(png_bytes, translated, cache_context)

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
        if urlparse(self.path).path == "/logs":
            return
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), fmt % args)
        )
