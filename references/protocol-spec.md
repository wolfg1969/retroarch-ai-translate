# RetroArch AI Service — Complete Protocol Specification

Based on RetroArch source code analysis (task_translation.c, config.def.h) and the RetroSprite project's reverse-engineering documentation.

## 1. HTTP Request

**Method**: POST

**URL Construction**:
- Base: user-configured `ai_service_url` (e.g., `http://localhost:4404/`)
- Query params appended: `output=` (required), `source_lang=`, `target_lang=` (optional)
- If base URL already contains `?`, append with `&`; otherwise use `?`

**Examples**:
```
http://localhost:4404/?output=image,png
http://localhost:4404/?output=text&source_lang=jpn&target_lang=zh
http://localhost:4404/service?api_key=ABC&output=sound,wav&target_lang=en
```

**Headers**: Content-Type: application/json

**Request Body** (JSON):
```json
{
  "image": "<base64-encoded PNG file bytes>",
  "label": "system_id__content_id",
  "coords": [x, y, width, height],
  "viewport": [width, height],
  "state": {
    "paused": 1,
    "a": 0, "b": 0, "x": 0, "y": 0,
    "select": 0, "start": 0,
    "up": 0, "down": 0, "left": 0, "right": 0,
    "l": 0, "r": 0, "l2": 0, "r2": 0, "l3": 0, "r3": 0
  }
}
```

- `image` (required): Base64-encoded PNG. BGR24 pixels → PNG encoded → Base64. Not raw pixels, not BMP.
- `label` (optional): Game identifier, format `system_id__content_id` (e.g., `snes__super_metroid`, `gba__phoenix_wright`).
- `state` (required): Controller button states, all integers 0 or 1.
- `coords` and `viewport`: optional context fields.

## 2. Output Modes (query parameter)

| Mode | output= value | Response field |
|------|---------------|----------------|
| Image Mode (mode 0) | `image,png` or `image,png,png-a` | `image` (base64 PNG overlay) |
| Speech Mode (mode 1, default) | `sound,wav` | `sound` (base64 WAV audio) |
| Narrator/TTS Mode (mode 2) | `text` | `text` (string for TTS) |
| Combined (mode 3) | `sound,wav,image,png` | both `sound` and `image` |

## 3. HTTP Response

**Status**: Always 200 OK (even for errors — use `error` JSON field)

**Response Body** (JSON, all fields optional):
```json
{
  "text": "<translated subtitle text>",
  "image": "<base64-encoded overlay image>",
  "sound": "<base64-encoded WAV audio>",
  "text_position": 1,
  "press": ["a", "b", "start"],
  "auto": "auto",
  "error": "<error message>"
}
```

- `text_position`: 1 = bottom (default), 2 = top
- `press`: Button names to simulate remotely. Values: a, b, x, y, select, start, up, down, left, right, l, r, l2, r2, l3, r3, pause, unpause
- `auto`: "auto" = continue polling, "continue" = skip display but continue polling, absent = stop auto mode
- `error`: If present, all other fields are ignored and the error is displayed

## 4. Image Encoding Details

**Input from emulator**: BGR24 raw pixels (Blue-Green-Red, 24-bit uncompressed, 3 bytes/pixel)
**Processing**: BGR24 pixels → rpng_save_image_bgr24_string() → PNG file bytes → base64() → JSON string
**Key**: NOT raw pixels. NOT BMP (deprecated since 1.16.0+). Must be complete PNG with signature/IHDR.

## 5. Auto Mode

When the user presses the AI Service hotkey once while the service supports auto mode:
- RetroArch polls at `ai_service_poll_delay` intervals (default 200ms)
- Each response's `auto` field controls continuation
- Pressing hotkey again or opening menu stops auto mode

## 6. RetroArch Configuration

```
ai_service_enabled = "true"
ai_service_url = "http://localhost:4404/"
ai_service_mode = "1"          # 0=image, 1=speech, 2=narrator, 3=combined
ai_service_pause = "true"      # pause game during translation
ai_service_source_lang = "7"   # 0=auto, 1=en, 7=ja (Japanese)
ai_service_target_lang = "0"   # 0=en (default for English target)
ai_service_poll_delay = "200"  # ms between auto-mode requests
```

Language codes: 0=auto/don't care, 1=en, 2=es, 3=fr, 4=de, 5=it, 6=pt, 7=ja, 8=ko, 9=zh-CN, 10=zh-TW, etc.

## 7. Version History

- 1.7.8 (2018): Initial AI Service, image+text only, BMP format
- 1.15.0 (2020): Auto mode, speech/audio, TTS support
- 1.16.0+ (2021+): PNG replaces BMP, improved error handling, extended languages
- Current: All features supported. PNG format strongly recommended.

## 8. Known Implementations

| Name | URL | Approach |
|------|-----|----------|
| VGTranslate (official) | gitlab.com/spherebeaker/vgtranslate | Google Cloud Vision OCR + TTS, Python/Docker |
| VGTranslate Local | github.com/objaction/vgtranslate_local | PaddleOCR + GPT-4V, local-first |
| ZTranslate (commercial) | ztranslate.net | Commercial OCR/translation, Win/Linux |
| RetroSprite | github.com/MightyKartz/RetroSprite | BYOK vision API + local ASR, Android/Kotlin |

## 9. Test Script

A minimal curl test for any AI Service endpoint:

```bash
# Must use a valid minimal PNG (1x1 transparent pixel)
PNG_B64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

curl -sS -X POST "http://localhost:4404/?output=text" \
  -H "Content-Type: application/json" \
  -d "{\"image\":\"$PNG_B64\",\"label\":\"snes__test\",\"state\":{\"paused\":1}}"
```
