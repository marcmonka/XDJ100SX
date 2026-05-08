from __future__ import annotations

"""
Image utilities: white-background removal and PIL-image → Rich-Text rendering.

Half-block trick: the ▄ character covers the BOTTOM half of a terminal cell.
  • Both halves opaque  → bgcolor=top, color=bottom, char=▄
  • Top transparent     → color=bottom, no bgcolor (panel bg shows through), char=▄
  • Bottom transparent  → color=top, no bgcolor, char=▀  (upper-half block)
  • Both transparent    → space (panel background shows through)

This avoids any fixed background-colour guessing, so the image blends naturally
against whatever Textual's panel colour happens to be.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as _PILImage

_IMAGES_DIR = Path(__file__).parent / "images"

# Pixels with alpha below this are treated as fully transparent
_ALPHA_THRESH = 80


def _remove_white_bg(img: "_PILImage.Image", threshold: int = 230) -> "_PILImage.Image":
    """
    BFS flood-fill from all four corners: connected white pixels become transparent.
    Corner-flood avoids touching white silkscreen text on the board itself.
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()

    def _is_white(px) -> bool:
        return px[0] >= threshold and px[1] >= threshold and px[2] >= threshold

    visited: set[tuple[int, int]] = set()
    queue: list[tuple[int, int]] = []
    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if _is_white(pixels[sx, sy]) and (sx, sy) not in visited:
            queue.append((sx, sy))
            visited.add((sx, sy))

    while queue:
        x, y = queue.pop()
        r, g, b, _ = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                if _is_white(pixels[nx, ny]):
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    return img


def img_to_rich(img: "_PILImage.Image", target_width: int = 32) -> object:
    """
    Convert a PIL RGBA image to a Rich Text object using half-block characters.
    Transparent areas render as plain spaces so the panel background shows through.
    Returns a rich.text.Text ready to pass to Static() or RichLog.write().
    """
    from PIL import Image
    from rich.text import Text
    from rich.style import Style
    from rich.color import Color

    aspect = img.height / img.width
    target_height = max(2, int(target_width * aspect * 0.5) * 2)  # must be even
    img = img.resize((target_width, target_height), Image.LANCZOS).convert("RGBA")
    pixels = img.load()

    result = Text(no_wrap=True)
    for row in range(0, target_height, 2):
        if row > 0:
            result.append("\n")
        for col in range(target_width):
            tr, tg, tb, ta = pixels[col, row]
            br, bg, bb, ba  = pixels[col, min(row + 1, target_height - 1)]
            top_opaque = ta > _ALPHA_THRESH
            bot_opaque = ba > _ALPHA_THRESH

            if not top_opaque and not bot_opaque:
                # Both transparent — let the panel background show through
                result.append(" ")
            elif top_opaque and bot_opaque:
                # Both opaque — full half-block encoding
                result.append("▄", style=Style(
                    bgcolor=Color.from_rgb(tr, tg, tb),
                    color=Color.from_rgb(br, bg, bb),
                ))
            elif not top_opaque and bot_opaque:
                # Bottom opaque, top transparent — ▄ with no background
                result.append("▄", style=Style(color=Color.from_rgb(br, bg, bb)))
            else:
                # Top opaque, bottom transparent — upper-half block, no background
                result.append("▀", style=Style(color=Color.from_rgb(tr, tg, tb)))
    return result


def load_board_rich(board_key: str, target_width: int = 32) -> object | None:
    """
    Load, background-remove, and render a board image as Rich Text.
    Returns None if Pillow is not installed or the image is missing.
    board_key: 'pico' | 'pico2' | 'teensy'
    """
    _FILE_MAP = {
        "pico":   "raspberry pi pico.png",
        "pico2":  "raspberry pi pico 2.png",
        "teensy": "teensy 4-0.png",
    }
    fname = _FILE_MAP.get(board_key)
    if not fname:
        return None
    path = _IMAGES_DIR / fname
    if not path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(path)
        img = _remove_white_bg(img)
        return img_to_rich(img, target_width)
    except Exception:
        return None
