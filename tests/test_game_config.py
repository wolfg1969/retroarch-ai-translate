import datetime
import unittest

from src import game_config


class MinimalYamlTests(unittest.TestCase):
    def test_ocr_mapping_uses_supported_one_level_shape(self):
        docs = game_config._minimal_yaml_load_all('''
---
game_id: gyakuten
ocr:
  ui_style: "法庭: 主界面 # 不是注释"
  dialogue_style: '白字 # 黑底'
  dialogue_location: 画面下方 # 行尾注释
  characters: "成歩堂龍一、綾里真宵, 御劍怜侍"
  ignore_regions: "右下角 A/B 按钮"
''')
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["ocr"], {
            "ui_style": "法庭: 主界面 # 不是注释",
            "dialogue_style": "白字 # 黑底",
            "dialogue_location": "画面下方",
            "characters": "成歩堂龍一、綾里真宵, 御劍怜侍",
            "ignore_regions": "右下角 A/B 按钮",
        })


class ConfigFingerprintTests(unittest.TestCase):
    def test_dict_order_does_not_change_fingerprint(self):
        first = {"game_id": "test", "ocr": {"ui_style": "像素", "characters": "A、B"}}
        second = {"ocr": {"characters": "A、B", "ui_style": "像素"}, "game_id": "test"}
        self.assertEqual(
            game_config.config_fingerprint(first),
            game_config.config_fingerprint(second),
        )

    def test_none_has_stable_distinct_fingerprint(self):
        self.assertEqual(
            game_config.config_fingerprint(None),
            game_config.config_fingerprint(None),
        )
        self.assertNotEqual(
            game_config.config_fingerprint(None),
            game_config.config_fingerprint({}),
        )

    def test_ocr_and_translation_changes_update_fingerprint(self):
        base = {"game_id": "test", "ocr": {"ui_style": "像素"}, "glossary": {"A": "甲"}}
        changed_ocr = {**base, "ocr": {"ui_style": "手写"}}
        changed_glossary = {**base, "glossary": {"A": "乙"}}
        fingerprint = game_config.config_fingerprint(base)
        self.assertNotEqual(fingerprint, game_config.config_fingerprint(changed_ocr))
        self.assertNotEqual(fingerprint, game_config.config_fingerprint(changed_glossary))
    def test_yaml_dates_mixed_keys_and_cycles_are_supported(self):
        cyclic = {}
        cyclic["self"] = cyclic
        config = {
            "released": datetime.date(2001, 10, 12),
            "glossary": {1: "一", "1": "字符串一"},
            "alias": cyclic,
        }
        fingerprint = game_config.config_fingerprint(config)
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(fingerprint, game_config.config_fingerprint(config))


if __name__ == "__main__":
    unittest.main()
