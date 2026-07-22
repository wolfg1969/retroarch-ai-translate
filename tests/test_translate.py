import unittest
from unittest.mock import patch

from src import translate


class TranslationPromptTests(unittest.TestCase):
    def test_prompt_requires_complete_line_preserving_menu_translation(self):
        prompt = translate._build_system_prompt({"character_tones": {"千尋": "沉稳"}})
        self.assertIn("不得省略、合并或概括", prompt)
        self.assertIn("保留相同行数", prompt)
        self.assertIn("菜单标题", prompt)
        self.assertIn("菜单选项中出现角色名不代表该角色正在说话", prompt)

    @patch("src.translate._api_call")
    def test_incomplete_multiline_translation_retries_with_line_count(self, api_call):
        api_call.side_effect = [
            {"choices": [{"message": {"content": "绫里千寻"}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": "交谈\n拒绝委托的理由\n关于千寻姐\n关于那幅画"}, "finish_reason": "stop"}]},
        ]
        source = "話す\n依頼を断る理由\n千尋さんのこと\n絵のこと"

        result = translate.translate(source, {"glossary": {"千尋": "绫里千寻"}})

        self.assertEqual(result.splitlines(), [
            "交谈",
            "拒绝委托的理由",
            "关于千寻姐",
            "关于那幅画",
        ])
        self.assertEqual(api_call.call_count, 2)
        retry_payload = api_call.call_args_list[1].args[1]
        self.assertEqual(retry_payload["messages"][2], {
            "role": "assistant",
            "content": "绫里千寻",
        })
        self.assertIn("严格输出 4 个非空行", retry_payload["messages"][3]["content"])

    @patch("src.translate._api_call")
    def test_complete_multiline_translation_does_not_retry(self, api_call):
        api_call.return_value = {
            "choices": [{"message": {"content": "交谈\n关于画"}, "finish_reason": "stop"}]
        }

        result = translate.translate("話す\n絵のこと")

        self.assertEqual(result, "交谈\n关于画")
        api_call.assert_called_once()

    @patch("src.translate._api_call")
    def test_retry_keeps_more_complete_result(self, api_call):
        api_call.side_effect = [
            {"choices": [{"message": {"content": "第一行\n第二行"}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": "只有一行"}, "finish_reason": "stop"}]},
        ]

        result = translate.translate("一\n二\n三")

        self.assertEqual(result, "第一行\n第二行")
        self.assertEqual(api_call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
