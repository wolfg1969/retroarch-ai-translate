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


if __name__ == "__main__":
    unittest.main()
