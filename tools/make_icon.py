"""Generate the Murmur app icon as a 1024x1024 PNG.

Run: python tools/make_icon.py [output_path]
Default output: assets/icon.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(size: int = 1024) -> Image.Image:
    """A teal-to-violet rounded square with three concentric speech-arc curves."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square background with a vertical gradient (teal -> deep violet).
    radius = int(size * 0.22)
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top = (24, 178, 173)      # teal
    bot = (88, 49, 168)       # violet
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        gd.line([(0, y), (size, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (size - 1, size - 1)], radius=radius, fill=255
    )
    img.paste(grad, (0, 0), mask)

    # Mic capsule: rounded rect in the centre.
    cx = size // 2
    cy = int(size * 0.46)
    mic_w = int(size * 0.20)
    mic_h = int(size * 0.36)
    mic_box = [
        (cx - mic_w // 2, cy - mic_h // 2),
        (cx + mic_w // 2, cy + mic_h // 2),
    ]
    draw.rounded_rectangle(mic_box, radius=mic_w // 2, fill=(255, 255, 255, 240))

    # Mic stand U-curve under the capsule.
    stand_pad = int(size * 0.06)
    stand_box = [
        (cx - mic_w, cy + mic_h // 2 - stand_pad),
        (cx + mic_w, cy + mic_h // 2 + int(mic_h * 0.55)),
    ]
    draw.arc(
        stand_box,
        start=15,
        end=165,
        fill=(255, 255, 255, 240),
        width=int(size * 0.025),
    )

    # Vertical post + base.
    post_x = cx
    post_top = stand_box[1][1] - int(size * 0.005)
    post_bot = post_top + int(size * 0.08)
    draw.line(
        [(post_x, post_top), (post_x, post_bot)],
        fill=(255, 255, 255, 240),
        width=int(size * 0.025),
    )
    base_w = int(size * 0.16)
    draw.line(
        [(post_x - base_w // 2, post_bot), (post_x + base_w // 2, post_bot)],
        fill=(255, 255, 255, 240),
        width=int(size * 0.025),
    )

    return img


def main(argv: list[str]) -> int:
    default_out = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
    out = Path(argv[1]) if len(argv) > 1 else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    img = make_icon()
    img.save(out, format="PNG")
    print(f"wrote {out} ({img.size[0]}x{img.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
