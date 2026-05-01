"""Generate the Murmuro app icon as a 1024x1024 PNG.

Bold lowercase Greek mu (μ) on a vivid-orange rounded square, with a
diagonal long-shadow trailing to the bottom-right corner. The glyph is
rendered from ``SFNSRounded`` for the chunky rounded shape Apple ships
in macOS — no embedded font binary, no third-party assets.

Run: python tools/make_icon.py [output_path]
Default output: assets/icon.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

# Vivid orange gradient — top peach → bottom burnt-orange.
TOP_RGB = (251, 142, 41)
BOT_RGB = (235, 95, 18)

# Glyph color (warm white, not pure white — slight cream tone reads
# softer against the saturated orange).
GLYPH_RGB = (255, 248, 240)

# Long-shadow stamp color: a darker orange that fades to transparent
# as the streak extends. The fill alpha is computed per step so the
# shadow has a natural falloff instead of a hard tail.
SHADOW_RGB = (150, 50, 5)

# Font candidates in preference order. SFNSRounded ships with macOS and
# has the chunky rounded μ shape we want; the rest are fallbacks for
# environments where SFNSRounded isn't installed (e.g. CI runners).
_FONT_CANDIDATES = (
    ("/System/Library/Fonts/SFNSRounded.ttf", None),
    ("/System/Library/Fonts/Avenir.ttc", 4),       # Avenir Black
    ("/System/Library/Fonts/HelveticaNeue.ttc", 8),  # Helvetica Neue Black
    ("/System/Library/Fonts/Helvetica.ttc", 1),
)


def _load_font(point_size: int) -> ImageFont.FreeTypeFont:
    for path, index in _FONT_CANDIDATES:
        try:
            if index is not None:
                return ImageFont.truetype(path, point_size, index=index)
            return ImageFont.truetype(path, point_size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _gradient_rounded_square(size: int) -> tuple[Image.Image, Image.Image]:
    """Return (image, mask) — the gradient backdrop and the rounded
    rectangle alpha mask, so callers can clip extra layers (e.g. the
    long-shadow streak) to the same silhouette."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        r = int(TOP_RGB[0] * (1 - t) + BOT_RGB[0] * t)
        g = int(TOP_RGB[1] * (1 - t) + BOT_RGB[1] * t)
        b = int(TOP_RGB[2] * (1 - t) + BOT_RGB[2] * t)
        gd.line([(0, y), (size, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=int(size * 0.22),
        fill=255,
    )
    img.paste(grad, (0, 0), mask)
    return img, mask


def _glyph_layer(
    size: int,
    *,
    text: str = "μ",
    point_frac: float = 0.78,
) -> tuple[Image.Image, int, int]:
    """Render the μ glyph centered on a transparent layer. Returns the
    layer plus the (tx, ty) draw origin so the shadow streak can stamp
    the same glyph at incremental offsets."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = _load_font(int(size * point_frac))
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=GLYPH_RGB)
    return layer, tx, ty


def _shadow_layer(
    size: int,
    tx: int,
    ty: int,
    *,
    text: str = "μ",
    point_frac: float = 0.78,
    streak_frac: float = 0.55,
) -> Image.Image:
    """Long-shadow streak: stamp the glyph at diagonal offsets from
    1 px through ``streak_frac * size`` px, fading the alpha so the
    shadow trails into the gradient instead of sitting as a hard
    silhouette."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = _load_font(int(size * point_frac))
    steps = int(size * streak_frac)
    for i in range(1, steps + 1):
        # Per-step alpha: starts at 80, fades to ~8 at the end of the
        # streak so the tail dissolves into the gradient.
        alpha = max(8, 80 - int(i * 80 / steps))
        d.text(
            (tx + i, ty + i),
            text,
            font=font,
            fill=(*SHADOW_RGB, alpha),
        )
    return layer


def make_icon(size: int = 1024) -> Image.Image:
    """Render at 4x supersample and downscale with LANCZOS for clean
    glyph edges and a smooth shadow tail."""
    ss = 4
    sup = size * ss
    bg, rounded_mask = _gradient_rounded_square(sup)
    glyph, tx, ty = _glyph_layer(sup)
    shadow = _shadow_layer(sup, tx, ty)

    # Clip the shadow streak to the rounded silhouette so it doesn't
    # bleed past the icon's corners.
    shadow_alpha = ImageChops.multiply(shadow.split()[3], rounded_mask)
    shadow.putalpha(shadow_alpha)

    composed = Image.alpha_composite(bg, shadow)
    composed = Image.alpha_composite(composed, glyph)
    return composed.resize((size, size), Image.LANCZOS)


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
