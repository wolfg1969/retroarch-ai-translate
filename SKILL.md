---
name: retroarch-ai-translation
description: Build a local OCR + DeepSeek V4 translation service for RetroArch. Extracts game text with PaddleOCR/Tesseract, translates via DeepSeek V4 text API. Optimized for GBA Japanese games (Phoenix Wright, Fire Emblem, Zelda). Includes game-specific prompt design with glossary, character tone layering, and signature phrase handling.
version: 2.0.0
platforms: [linux, macos, windows]
---

# RetroArch AI Translation Service — GBA + DeepSeek V4

Build a local HTTP service that plugs into RetroArch's AI Service to provide real-time Japanese→Chinese translation for GBA games. Uses local OCR (PaddleOCR or Tesseract) to extract text, then DeepSeek V4 for translation. Does NOT touch the ROM — RetroAchievements work normally.

## Trigger Conditions

Load this skill when the user:
- Wants to build an AI translation service for RetroArch + GBA games
- Needs to understand the RetroArch AI Service HTTP protocol
- Asks about translating retro games (GBA, SNES, PS1) in real time
- Mentions "AI Service hotkey translation" or similar patterns
- Needs game-specific prompt design for Japanese visual novels or RPGs
- Wants cost/latency estimates for translation

## Architecture

```
RetroArch (GBA core)
  │  Hotkey pressed → pause → screenshot (PNG, 240×160)
  ▼
HTTP POST to localhost:4404
  │
  ▼
Local OCR (PaddleOCR japan / Tesseract jpn)
  │  Extract Japanese text from screenshot (~100ms)
  ▼
DeepSeek V4 Chat Completions API
  │  Text-only translation (~500ms)
  ▼
Response → RetroArch overlay display
```

**Total latency: ~0.6–1.0 seconds.** No Vision API needed, no ROM modification.

## Protocol Summary

RetroArch sends a POST to the configured URL with a JSON body containing a base64-encoded PNG screenshot. The service returns JSON with translated text. Always respond with HTTP 200 — errors go in the `error` JSON field.

See `references/protocol-spec.md` for the complete specification.

## GBA-Specific Considerations

GBA screens are **240×160 pixels**. Japanese pixel fonts are typically 8×8 to 12×12 bitmap fonts. Key implications:

- **Low resolution is a double-edged sword**: Small image = fast OCR, but complex kanji strokes merge at 12px height (e.g., 難, 議, 驚)
- **Clean source**: No noise, no perspective distortion, sharp pixel edges — OCR engines handle this well
- **PaddleOCR preferred over Tesseract**: Deep learning models handle low-res CJK pixel fonts better than Tesseract's traditional approach. Tesseract struggles with merged strokes on complex kanji
- **OCR latency**: ~50–100ms for a 240×160 image on a Celeron J1900 (tested)

## OCR Setup

### PaddleOCR (recommended)

```bash
pip install paddlepaddle paddleocr
```

Japanese model (PP-OCRv4 multilingual) handles CJK + kana with strong low-res robustness.

```python
from paddleocr import PaddleOCR
ocr = PaddleOCR(lang='japan', use_angle_cls=False)
results = ocr.ocr(png_bytes, cls=False)
text = '\n'.join([line[1][0] for line in results[0]])
```

First run downloads the model (~10MB). Subsequent runs are instant.

### Tesseract (fallback)

```bash
# Debian/Ubuntu
apt install tesseract-ocr tesseract-ocr-jpn
# Or via pip wrapper
pip install pytesseract
```

```python
import pytesseract
text = pytesseract.image_to_string(image, lang='jpn')
```

Tesseract is lighter but less accurate on GBA pixel fonts. Use only if PaddleOCR is unavailable.

## Game Configuration Format

Each game gets a YAML config file with glossary terms, character tone rules, and signature phrases. Place in `./games/<game_id>.yaml` (project root).

See `templates/game_config.yaml` for examples (Phoenix Wright, Fire Emblem, Zelda: Minish Cap).

### Config structure:

```yaml
game_id: gyakuten
display_name: 逆转裁判
language: jpn

# Fixed translations for signature phrases (NEVER let model rewrite these)
signature_phrases:
  異議あり！: 反对！
  待った！: 等等！
  くらえ！: 接招！

# Character tone rules (model adjusts Chinese output based on speaker)
character_tones:
  成歩堂: "口语化，偶尔吐槽，语气词多（吧、啊、呢），紧急时短促有力"
  御劍: "冷静克制，句式完整，用词正式，不轻易感叹"
  真宵: "活泼轻快，尾音上扬，偶尔卖萌，带颜文字感"

# Scene modes for context injection (optional, switch via hotkey combos)
scene_modes:
  courtroom: "法庭辩论场景。保持紧迫感，句子短，用感叹号，不加解释。成步堂正在质证。"
  investigation: "调查取证场景。语气平和，描述性文字可以完整翻译。"
  daily: "日常对话场景。语气放松，可以保留调侃和幽默。"

# Term glossary (enforces consistent translations)
glossary:
  証拠: 证据
  法廷: 法庭
  検察官: 检察官
  弁護士: 律师
```

## Translation Prompt Design

### Prompt skeleton (assembled at runtime)

```
[Glossary terms injected as "固定译名：X→Y, A→B..."]
[Active character tone rules]
[Active scene mode context]
[Signature phrase fixed translations]

翻译规则：
1. 只翻译对话/UI文字，不翻译括号内的动作描述
2. 保留原文的省略号(...)和停顿节奏
3. 句子长度尽量接近原文，不补全不扩写
4. 区分说话人语气，按照角色设定调整中文风格
5. 你只输出中文翻译，一行一句，不加任何解释或标记
```

### Key techniques

| Technique | Detail |
|-----------|--------|
| Temperature | 0.3 — low enough for consistent output, high enough to avoid robotic stiffness |
| Thinking disabled | Add `"thinking": {"type": "disabled"}` to prevent wasted reasoning tokens |
| Signature phrase lock | Put fixed translations LAST in the prompt — DeepSeek weights end-of-prompt content highest |
| Character tone by speaker | OCR output often includes speaker names; the model uses these to adjust tone |
| CJK validation | After response, verify output contains actual Chinese characters; if not, re-send as repair |
| Scene mode switching | Embed context hints to shift translation style (courtroom urgency vs. casual chat) |

### Prompt pitfalls

1. **Do NOT add "只翻译成简体中文" at the start** — it makes the model skip the tone rules. Put it at the end instead.
2. **Don't ask the model to explain or annotate** — it will bloat output with commentary.
3. **OCR errors propagate**: If OCR misreads 証拠 as 証期, the glossary won't match. Test OCR quality first before tuning prompts.

## Cost Estimates (DeepSeek V4, RMB)

| Model | Input (per 1M) | Output (per 1M) | Single translation (~50 in + ~30 out) |
|-------|---------------|-----------------|--------------------------------------|
| v4-flash | ¥1 | ¥2 | ¥0.00011 |
| v4-pro | ¥3 | ¥6 | ¥0.00033 |

**One hour of gameplay** (~200 hotkey presses):

| | v4-flash | v4-pro |
|---|---------|--------|
| Hourly cost | ¥0.02 | ¥0.07 |
| Full Phoenix Wright (~30hrs) | ¥0.60 | ¥2.10 |
| Full trilogy (~90hrs) | ¥1.80 | ¥6.30 |

**Verdict: It's not going to burn a hole in your wallet.** You can play all day every day and spend less than ¥1.

## Implementation Template

See `templates/retroarch_translate.py` for a complete, working service (~200 lines). It includes:

- PaddleOCR text extraction from PNG screenshots
- DeepSeek V4 text translation with game config loading
- Character tone + glossary injection
- Scene mode switching via URL query param
- CJK output validation + repair fallback

To use:

```bash
export DEEPSEEK_API_KEY=sk-...
python3 retroarch_translate.py
```

Then configure RetroArch: Settings → AI Service → AI Service Mode = Image (mode 0), URL = `http://localhost:4404`, bind a hotkey, done.

### Example: Phoenix Wright scene modes

Set the RetroArch AI Service URL to include the game ID:

```
http://localhost:4404/?game=gyakuten&scene=courtroom
```

The service loads `gyakuten.yaml`, injects character tones for 成歩堂/御劍/真宵, locks signature phrases (異議あり！→ 反对！), and applies courtroom urgency style.

## Deployment Patterns

**Same machine (recommended)**: Python service + RetroArch on the same PC. Bind to 127.0.0.1:4404. Zero network overhead.

**OpenWrt router**: Can host on a Celeron J1900 / 4GB RAM box. The service is lightweight — OCR runs on CPU, API calls are proxied. Tested.

**Retro handhelds (RG35XX, Miyoo)**: Run the service on a home server/NAS, point RetroArch to its LAN IP. For Android: `adb forward tcp:4404 tcp:4404`.

## Pitfalls

1. **DeepSeek V4 is TEXT-ONLY**: No `image_url` support. Must use local OCR first. Confirmed: both v4-flash and v4-pro return `unknown variant 'image_url'`.
2. **DeepSeek thinking tokens**: Without `"thinking": {"type": "disabled"}`, V4 models waste tokens on internal reasoning. Always disable for translation.
3. **RetroArch expects HTTP 200 always**: Never return 4xx/5xx. Send `{"error": "message"}` with HTTP 200.
4. **Pause During Translation must be ON**: Without it, screenshots may capture mid-animation frames with partial text.
5. **OCR accuracy trumps translation quality**: If OCR misreads text, the best prompt won't save it. Test OCR output on actual game screens before tuning translation prompts.
6. **PaddleOCR first-run delay**: First invocation downloads the Japanese model (~10MB). Subsequent calls are fast.
7. **Tesseract jpn model requires additional install**: `apt install tesseract-ocr-jpn` (Debian) or equivalent. Not included in base tesseract package.

## Related Work

- RetrOSprite (Android BYOK translation): https://github.com/MightyKartz/RetroSprite
- VGTranslate Local (Python/PaddleOCR): https://github.com/objaction/vgtranslate_local
- RetroArch AI Service docs: https://docs.libretro.com/guides/ai-service/
