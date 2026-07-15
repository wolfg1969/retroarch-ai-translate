"""Image overlay — renders translated text onto a transparent PNG."""

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
    lines: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for i in range(0, len(paragraph), chars_per_line):
            lines.append(paragraph[i:i + chars_per_line])

    max_lines = height // (font_size + 6)
    lines = lines[-max_lines:]

    line_height = font_size + 4
    text_area_height = len(lines) * line_height + 10

    padding_y = 6
    if text_position == 1:  # bottom
        bg_y0 = height - text_area_height - padding_y
        bg_y1 = height
    else:  # top
        bg_y0 = 0
        bg_y1 = text_area_height + padding_y

    draw.rectangle([(0, bg_y0), (width, bg_y1)], fill=(0, 0, 0, 180))

    text_y = bg_y0 + 5
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]

        # Parse speaker color from hex (#rgb or #rrggbb) or use default
        if i == 0:
            # First line (speaker name)
            text_x = 4 if speaker_left_align else max(2, (width - text_w) // 2)
            fill_color = _parse_color(speaker_color)
        else:
            # Rest (dialogue) centered, white
            text_x = max(2, (width - text_w) // 2)
            fill_color = (255, 255, 255, 255)

        draw.text((text_x + 1, text_y + 1), line, font=font, fill=(0, 0, 0, 200))
        draw.text((text_x, text_y), line, font=font, fill=fill_color)
        text_y += line_height

    buf = BytesIO()
    overlay.save(buf, format="PNG")
    return buf.getvalue()
