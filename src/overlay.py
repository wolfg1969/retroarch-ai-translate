"""Image overlay — renders translated text onto a transparent PNG."""

import re
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from . import config

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _parse_color(color: str) -> tuple[int, int, int, int]:
    """Parse hex color (#rgb or #rrggbb) to RGBA tuple."""
    if not color.startswith("#"):
        return (255, 200, 0, 255)  # Default yellow
    hex_str = color.lstrip("#")
    if len(hex_str) == 3:
        r, g, b = (int(c, 16) * 17 for c in hex_str)  # #abc -> a*17, b*17, c*17
    elif len(hex_str) == 6:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    else:
        return (255, 200, 0, 255)
    return (r, g, b, 255)


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        try:
            _FONT_CACHE[size] = ImageFont.truetype(config._CJK_FONT_PATH, size)
        except (OSError, IOError):
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _collect_known_speakers(game_cfg: dict | None) -> set[str]:
    """Gather known character names from game config.

    Two sources:
    1. ``character_tones`` keys — Japanese short names (e.g. "成歩堂").
    2. Glossary values that look like names (2–6 chars) — these become
       the Chinese short/full forms that the MT model outputs.  Prefix
       matching in ``_is_speaker_name`` then catches partial forms
       (e.g. "矢张" from "矢张政志").
    """
    names: set[str] = set()
    if not game_cfg:
        return names

    tones = game_cfg.get("character_tones", {})
    if isinstance(tones, dict):
        names.update(str(k).strip() for k in tones)

    glossary = game_cfg.get("glossary", {})
    if isinstance(glossary, dict):
        for v in glossary.values():
            v = str(v).strip()
            if 2 <= len(v) <= 6:
                names.add(v)

    return names


def _is_speaker_name(candidate: str, known: set[str]) -> bool:
    """Check whether *candidate* looks like a speaker / character name."""
    if not candidate:
        return False
    if len(candidate) > 10:
        return False
    # Dialogue punctuation marks ⇒ not a speaker name
    if any(c in candidate for c in "。！？…，、！？"):
        return False
    # If we have a known-character list, require a match (exact or prefix)
    if known:
        if candidate in known:
            return True
        # The MT model may output a short form (e.g. "成步堂" or "千寻")
        # while the glossary stores the full name ("成步堂龙一", "绫里千寻").
        if len(candidate) >= 2:
            pattern = re.escape(candidate)
            for name in known:
                if re.search(pattern, name):
                    return True
        return False
    # Without known characters, be conservative:
    # accept only if short AND followed by more text (checked by caller)
    return len(candidate) <= 6


def _parse_text(text: str, known_speakers: set[str]) -> tuple[str | None, list[str]]:
    """Split translated text into an optional speaker + dialogue paragraphs.

    Returns ``(speaker_or_None, [dialogue_paragraph, …])``.
    """
    raw = [p.strip() for p in text.split("\n") if p.strip()]
    if not raw:
        return None, []

    first = raw[0]
    rest = raw[1:]

    # ── Inline format: "speaker：dialogue" ──
    if "：" in first or ":" in first:
        sep = "：" if "：" in first else ":"
        parts = first.split(sep, 1)
        potential = parts[0].strip()
        if _is_speaker_name(potential, known_speakers):
            dialogue_paras: list[str] = []
            remainder = parts[1].strip()
            if remainder:
                dialogue_paras.append(remainder)
            dialogue_paras.extend(rest)
            return potential, dialogue_paras

    # ── Newline format: "speaker\\ndialogue" ──
    if rest and _is_speaker_name(first, known_speakers):
        return first, rest

    # ── No speaker detected ──
    return None, raw


def render(
    text: str,
    source_png_bytes: bytes,
    viewport: tuple[int, int] | None = None,
    text_position: int = 1,
    game_cfg: dict | None = None,
) -> bytes:
    """Render translated Chinese text onto a transparent PNG overlay.

    Returns PNG bytes for the RetroArch AI Service ``image`` field.
    """
    if viewport and len(viewport) >= 2:
        width, height = int(viewport[0]), int(viewport[1])
    else:
        src = Image.open(BytesIO(source_png_bytes))
        width, height = src.size

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(10, min(16, height // 12))
    font = _get_font(font_size)

    chars_per_line = max(6, width // (font_size + 2))

    # Load overlay config from game config
    overlay_cfg = game_cfg.get("overlay", {}) if game_cfg else {}
    speaker_style = overlay_cfg.get("speaker", {})
    speaker_left_align = speaker_style.get("left_align", True)
    speaker_color = speaker_style.get("color", "#ffc800")  # Default yellow

    known_speakers = _collect_known_speakers(game_cfg)
    speaker_name, dialogue_paragraphs = _parse_text(text, known_speakers)

    print(f"[Overlay] known_speakers={sorted(known_speakers)}", flush=True)
    print(f"[Overlay] text={text!r}", flush=True)
    print(f"[Overlay] speaker={speaker_name!r} dialogue={dialogue_paragraphs}", flush=True)

    # Build display lines — each line is (is_speaker, text)
    display_items: list[tuple[bool, str]] = []

    if speaker_name:
        for i in range(0, len(speaker_name), chars_per_line):
            display_items.append((True, speaker_name[i:i + chars_per_line]))

    for paragraph in dialogue_paragraphs:
        for i in range(0, len(paragraph), chars_per_line):
            display_items.append((False, paragraph[i:i + chars_per_line]))

    max_lines = height // (font_size + 6)
    display_items = display_items[-max_lines:]

    line_height = font_size + 4
    text_area_height = len(display_items) * line_height + 10

    padding_y = 6
    if text_position == 1:  # bottom
        bg_y0 = height - text_area_height - padding_y
        bg_y1 = height
    else:  # top
        bg_y0 = 0
        bg_y1 = text_area_height + padding_y

    draw.rectangle([(0, bg_y0), (width, bg_y1)], fill=(0, 0, 0, 180))

    text_y = bg_y0 + 5
    for is_speaker, line_text in display_items:
        bbox = draw.textbbox((0, 0), line_text, font=font)
        text_w = bbox[2] - bbox[0]

        if is_speaker:
            text_x = 4 if speaker_left_align else max(2, (width - text_w) // 2)
            fill_color = _parse_color(speaker_color)
        else:
            text_x = max(2, (width - text_w) // 2)
            fill_color = (255, 255, 255, 255)

        draw.text((text_x + 1, text_y + 1), line_text, font=font, fill=(0, 0, 0, 200))
        draw.text((text_x, text_y), line_text, font=font, fill=fill_color)
        text_y += line_height

    buf = BytesIO()
    overlay.save(buf, format="PNG")
    return buf.getvalue()
