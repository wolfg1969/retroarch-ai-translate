# DeepSeek V4 API — Vision Limitations & Pricing

Last verified: 2026-07-13 from api-docs.deepseek.com

## Model Lineup (current)

| Model | Features | Vision | Status |
|-------|----------|--------|--------|
| deepseek-v4-flash | JSON Output, Tool Calls, Chat Prefix Completion, FIM Completion, Thinking Mode | NO | Active |
| deepseek-v4-pro | Same as above | NO | Active |
| deepseek-chat | Legacy (maps to v4-flash non-thinking) | NO | Deprecated 2026/07/24 |
| deepseek-reasoner | Legacy (maps to v4-flash thinking) | NO | Deprecated 2026/07/24 |

## Vision/Multimodal Support

**Confirmed: DeepSeek V4 models do NOT support image input.** Both v4-flash and v4-pro return `unknown variant 'image_url', expected 'text'` when sent image content via the Chat Completions API.

The DeepSeek web interface (chat.deepseek.com) supports file/image upload, but this is **not available through the API**.

**Workaround**: Use local OCR (PaddleOCR/Tesseract) to extract text from game screenshots, then send text-only to DeepSeek V4 for translation.

## Pricing (per 1M tokens, RMB)

| | v4-flash | v4-pro |
|---|---------|--------|
| Input (cache miss) | ¥1 | ¥3 |
| Input (cache hit) | ¥0.02 | ¥0.025 |
| Output | ¥2 | ¥6 |

## Context Length: 1M tokens (both models)
## Max Output: 384K tokens (both models)
## Concurrency: 2500 (flash) / 500 (pro)

## GBA Translation Cost Estimate (OCR + Text Translation)

GBA screenshots are 240×160 pixels. After local OCR, only extracted text is sent to DeepSeek.

Per-translation token usage:
- Input: ~50 tokens (system prompt + OCR text)
- Output: ~30 tokens (Chinese translation)

Per-translation cost:
- v4-flash: (50/1M × ¥1) + (30/1M × ¥2) = ¥0.00011
- v4-pro: (50/1M × ¥3) + (30/1M × ¥6) = ¥0.00033

**One hour of gameplay** (~200 hotkey presses):
- v4-flash: ~¥0.02
- v4-pro: ~¥0.07

**Full Phoenix Wright trilogy** (~90 hours, ~18,000 translations):
- v4-flash: ~¥1.98
- v4-pro: ~¥5.94

Conclusion: Translation costs are negligible. OCR speed is the real bottleneck, not API pricing.
