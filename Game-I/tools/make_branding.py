"""Draw the game's own logo, backdrop and window icon from the open-licence fonts in assets/fonts. Nothing is copied from anywhere.

    .venv\\Scripts\\python.exe tools\\make_branding.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
OUTPUT = ROOT / "assets" / "branding"
RED, OFF_WHITE = (196, 28, 34, 255), (238, 236, 230, 255)


def stencil(draw: ImageDraw.ImageDraw, width: int, height: int, gap: int) -> None:
    """A single diagonal cut through the block of letters, as if it had been sprayed through a plate."""
    draw.polygon([(width * .60, -10), (width * .60 + gap, -10), (width * .40 + gap, height + 10), (width * .40, height + 10)], fill=(0, 0, 0, 0))


def logo() -> Image.Image:
    width, height = 1400, 640
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    big = ImageFont.truetype(str(FONT), 286)
    draw.text((30, -28), "NO LIMIT", font=big, fill=OFF_WHITE)
    draw.text((30, 262), "TO LARP", font=big, fill=OFF_WHITE)
    stencil(draw, width, height, 16)
    # Worn paint: the letters stay solid at game size, and pick up grain close to.
    pixels = np.array(image)
    rng = np.random.default_rng(7)
    grain = np.array(Image.fromarray((rng.random((height // 3, width // 3)) * 255).astype(np.uint8)).resize((width, height), Image.BILINEAR), dtype=np.float32) / 255.0
    pixels[..., 3] = (pixels[..., 3] * np.clip(1.0 - (grain > .93) * .3, 0, 1)).astype(np.uint8)
    image = Image.fromarray(pixels)
    # A red bar under the block, the full width of its first line.
    measured = ImageDraw.Draw(image)
    right = 30 + measured.textlength("NO LIMIT", font=big)
    measured.polygon([(38, 626), (46, 600), (right, 600), (right - 8, 626)], fill=RED)
    return image.crop(image.getbbox())


def backdrop() -> Image.Image:
    width, height = 1600, 900
    rng = np.random.default_rng(11)
    brushed = rng.normal(0.0, 1.0, (height, width))
    kernel = np.ones(61) / 61.0
    brushed = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), 1, brushed)
    y, x = np.mgrid[0:height, 0:width]
    vignette = np.clip(1.15 - (((x - width * .62) / width) ** 2 + ((y - height * .5) / height) ** 2) * 2.2, .25, 1.0)
    value = (15.0 + brushed * 22.0) * vignette
    pixels = np.dstack((value * 1.02, value, value * .98))
    image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    slash = ImageDraw.Draw(glow)
    slash.polygon([(1180, -20), (1420, -20), (1040, 920), (800, 920)], fill=(90, 12, 16))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    image = Image.fromarray(np.clip(np.asarray(image, dtype=np.int16) + np.asarray(glow, dtype=np.int16), 0, 255).astype(np.uint8), "RGB")
    # Hazard edge along the foot of the screen.
    edge = ImageDraw.Draw(image)
    for left in range(-40, width, 56):
        edge.polygon([(left, height), (left + 26, height), (left + 44, height - 18), (left + 18, height - 18)], fill=(120, 20, 24))
    return image


def icon() -> Image.Image:
    size = 256
    image = Image.new("RGBA", (size, size), (14, 14, 16, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, size - 34, size, size), fill=RED)
    font = ImageFont.truetype(str(FONT), 176)
    box = draw.textbbox((0, 0), "NL", font=font)
    draw.text(((size - box[2] - box[0]) / 2, (size - 34 - box[3] - box[1]) / 2), "NL", font=font, fill=OFF_WHITE)
    return image


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    logo().save(OUTPUT / "logo.png")
    backdrop().save(OUTPUT / "backdrop.jpg", quality=90)
    icon().save(OUTPUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUTPUT)


if __name__ == "__main__":
    main()
