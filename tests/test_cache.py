import unittest
from io import BytesIO

from PIL import Image

from src import cache, game_config


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), "white").save(output, format="PNG")
    return output.getvalue()


class CacheContextTests(unittest.TestCase):
    def setUp(self):
        cache._cache.clear()
        self.png = _png_bytes()

    def test_same_image_and_context_hits(self):
        cache.put(self.png, "翻译", "config-a")
        self.assertEqual(cache.get(self.png, "config-a"), "翻译")

    def test_same_image_with_different_context_misses(self):
        cache.put(self.png, "翻译", "config-a")
        self.assertIsNone(cache.get(self.png, "config-b"))

    def test_legacy_empty_context_remains_supported(self):
        cache.put(self.png, "翻译")
        self.assertEqual(cache.get(self.png), "翻译")

    def test_config_changes_isolate_cached_translation(self):
        first = {"ocr": {"ui_style": "像素"}, "glossary": {"A": "甲"}}
        changed_ocr = {"ocr": {"ui_style": "手写"}, "glossary": {"A": "甲"}}
        changed_glossary = {"ocr": {"ui_style": "像素"}, "glossary": {"A": "乙"}}
        first_context = game_config.config_fingerprint(first)
        cache.put(self.png, "翻译", first_context)
        self.assertIsNone(cache.get(self.png, game_config.config_fingerprint(changed_ocr)))
        self.assertIsNone(cache.get(self.png, game_config.config_fingerprint(changed_glossary)))


if __name__ == "__main__":
    unittest.main()
