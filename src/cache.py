"""Translation cache — same screenshot → same translation."""

import hashlib
from collections import OrderedDict
from io import BytesIO

from PIL import Image

from . import config


_cache: OrderedDict[str, str] = OrderedDict()


def _cache_key(png_bytes: bytes) -> str:
    """Hash the dialog-relevant portion of the screenshot.

    Crops off margins where blinking cursors and status bars live so
    the same dialog text produces the same cache key regardless of
    cursor animation state.
    """
    img = Image.open(BytesIO(png_bytes)).convert("L")
    w, h = img.size
    y0 = int(h * 0.05)
    y1 = int(h * 0.90)
    crop = img.crop((0, y0, w, y1))
    thumb = crop.resize((32, 24), Image.Resampling.LANCZOS)
    return hashlib.sha256(thumb.tobytes()).hexdigest()


def get(png_bytes: bytes) -> str | None:
    key = _cache_key(png_bytes)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def put(png_bytes: bytes, translated: str) -> None:
    key = _cache_key(png_bytes)
    if key in _cache:
        _cache.move_to_end(key)
    _cache[key] = translated
    while len(_cache) > config._CACHE_MAX:
        _cache.popitem(last=False)
