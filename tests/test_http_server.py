import base64
import io
import json
import unittest
from unittest.mock import patch

from src import http_server


class _Headers:
    def __init__(self, length: int):
        self.length = length

    def get(self, name: str, default: str = "") -> str:
        if name == "Content-Length":
            return str(self.length)
        return default


class HttpConfigPropagationTests(unittest.TestCase):
    def _handler(self, body: bytes):
        handler = object.__new__(http_server.TranslationHandler)
        handler.path = "/?output=text"
        handler.headers = _Headers(len(body))
        handler.rfile = io.BytesIO(body)
        handler.client_address = ("192.0.2.10", 12345)
        return handler

    def test_ip_label_and_default_resolution_pass_same_config_to_ocr(self):
        png_b64 = base64.b64encode(b"not-decoded-by-mocked-cache").decode("ascii")
        body = json.dumps({"image": png_b64, "label": "gba__label-game"}).encode("utf-8")
        cases = (
            ("IP override", "ip-game", "label-game", "default-game", "ip-game"),
            ("label auto-detect", "", "label-game", "default-game", "label-game"),
            ("default fallback", "", None, "default-game", "default-game"),
        )

        for name, ip_game, label_game, default_game, expected_game in cases:
            with self.subTest(name=name):
                game_cfg = {"game_id": expected_game, "ocr": {"ui_style": name}}

                def selected_game(ip: str) -> str:
                    return ip_game if ip == "192.0.2.10" else default_game

                with (
                    patch("src.http_server.game_config.get_game_for_ip", side_effect=selected_game),
                    patch("src.http_server.game_config.resolve", return_value=label_game),
                    patch("src.http_server.game_config.load", return_value=game_cfg) as load,
                    patch(
                        "src.http_server._pipeline_cache_context",
                        return_value="pipeline-context",
                    ),
                    patch("src.http_server.cache.get", return_value=None) as cache_get,
                    patch("src.http_server.cache.put") as cache_put,
                    patch("src.http_server.ocr.extract_text", return_value="テスト") as extract_text,
                    patch("src.http_server.translate.translate", return_value="测试") as translate,
                    patch("src.http_server.json_response") as respond,
                ):
                    self._handler(body).do_POST()

                context = "pipeline-context"
                load.assert_called_once_with(expected_game)
                cache_get.assert_called_once_with(b"not-decoded-by-mocked-cache", context)
                extract_text.assert_called_once_with(png_b64, game_cfg)
                translate.assert_called_once_with("テスト", game_cfg)
                cache_put.assert_called_once_with(
                    b"not-decoded-by-mocked-cache", "测试", context
                )
                respond.assert_called_once()
                self.assertEqual(respond.call_args.args[1]["text"], "测试")


class PipelineCacheContextTests(unittest.TestCase):
    def test_model_and_translation_mode_changes_update_context(self):
        game_cfg = {"game_id": "test"}
        with patch.dict("src.http_server.os.environ", {}, clear=True):
            baseline = http_server._pipeline_cache_context(game_cfg)

        with patch.dict(
            "src.http_server.os.environ",
            {"VISION_OCR_MODEL": "other-vision-model"},
            clear=True,
        ):
            changed_vision = http_server._pipeline_cache_context(game_cfg)

        with patch.dict(
            "src.http_server.os.environ",
            {
                "TRANSLATE_API_KEY": "secret-a",
                "TRANSLATE_MODEL": "paid-model",
            },
            clear=True,
        ):
            paid_a = http_server._pipeline_cache_context(game_cfg)

        with patch.dict(
            "src.http_server.os.environ",
            {
                "TRANSLATE_API_KEY": "secret-b",
                "TRANSLATE_MODEL": "paid-model",
            },
            clear=True,
        ):
            paid_b = http_server._pipeline_cache_context(game_cfg)

        self.assertNotEqual(baseline, changed_vision)
        self.assertNotEqual(baseline, paid_a)
        self.assertEqual(paid_a, paid_b)



class HttpLogsEndpointTests(unittest.TestCase):
    def _handler(self, path: str):
        handler = object.__new__(http_server.TranslationHandler)
        handler.path = path
        handler.headers = _Headers(0)
        handler.rfile = io.BytesIO(b"")
        handler.client_address = ("192.0.2.10", 12345)
        return handler

    def test_logs_endpoint_returns_200_and_json(self):
        from unittest.mock import MagicMock
        from src.log_buffer import clear_logs
        clear_logs()
        handler = self._handler("/logs")
        http_server.json_response = MagicMock()
        handler.do_GET()
        http_server.json_response.assert_called_once()
        args, kwargs = http_server.json_response.call_args
        self.assertEqual(args[0], handler)
        data = args[1]
        self.assertIn("logs", data)
        self.assertIn("cursor", data)
        self.assertIn("truncated", data)
        self.assertIn("capacity", data)
        self.assertEqual(data["capacity"], 1000)
        self.assertFalse(data["truncated"])

    def test_logs_params_are_bounded(self):
        from unittest.mock import MagicMock
        from src.log_buffer import clear_logs, append_log
        clear_logs()
        for i in range(50):
            append_log(f"line {i}")
        http_server.json_response = MagicMock()
        handler = self._handler("/logs?lines=5&after=invalid")
        handler.do_GET()
        args, kwargs = http_server.json_response.call_args
        data = args[1]
        self.assertLessEqual(len(data["logs"]), 5)

    def test_logs_default_lines(self):
        from unittest.mock import MagicMock
        from src.log_buffer import clear_logs, append_log
        clear_logs()
        for i in range(100):
            append_log(f"line {i}")
        http_server.json_response = MagicMock()
        handler = self._handler("/logs?lines=9999999999")
        handler.do_GET()
        args, kwargs = http_server.json_response.call_args
        data = args[1]
        self.assertLessEqual(len(data["logs"]), 1000)

    def test_logs_negative_defaults(self):
        from unittest.mock import MagicMock
        from src.log_buffer import clear_logs, append_log
        clear_logs()
        append_log("test")
        http_server.json_response = MagicMock()
        handler = self._handler("/logs?lines=-5")
        handler.do_GET()
        args, kwargs = http_server.json_response.call_args
        data = args[1]
        self.assertEqual(len(data["logs"]), 1)


class HttpHtmlEscapingTests(unittest.TestCase):
    def test_settings_escapes_html_in_values(self):
        import src.http_server
        with patch.object(src.http_server, '_load_service_settings', return_value={
            "vision_api_key": "",
            "vision_base_url": '<script>alert(1)</script>',
            "vision_ocr_model": "test",
            "translate_api_key": "",
            "translate_base_url": "",
            "translate_model": "",
        }):
            html = src.http_server._settings_ui()
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_settings_does_not_include_api_key_in_value(self):
        import src.http_server
        with patch.object(src.http_server, '_load_service_settings', return_value={
            "vision_api_key": "sk-test-secret-key",
            "vision_base_url": "https://example.com",
            "vision_ocr_model": "test",
            "translate_api_key": "sk-another-secret",
            "translate_base_url": "",
            "translate_model": "",
        }):
            html = src.http_server._settings_ui()
            self.assertNotIn("sk-test-secret-key", html)
            self.assertNotIn("sk-another-secret", html)
            self.assertIn("已配置，留空保持不变", html)

    def test_web_ui_escapes_game_names(self):
        import src.http_server
        from src import game_config as gc
        malicious = [{"game_id": "test", "display_name": '<script>alert("xss")</script>'}]
        with patch.object(gc, 'load_all', return_value=malicious),              patch.object(gc, 'get_game_for_ip', return_value='test'):
            html = src.http_server._web_ui("test", "192.0.2.10")
            self.assertIn('&lt;script&gt;', html)
            self.assertIn('&gt;', html)
            self.assertNotIn('<script>', html)

    def test_web_ui_escapes_client_ip(self):
        import src.http_server
        from src import game_config as gc
        with patch.object(gc, 'load_all', return_value=[{"game_id": "test"}]),              patch.object(gc, 'get_game_for_ip', return_value=''):
            html = src.http_server._web_ui("", '<script>alert("xss")</script>')
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;', html)


if __name__ == "__main__":
    unittest.main()
