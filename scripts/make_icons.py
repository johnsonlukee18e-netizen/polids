"""Ikony PWA i favicon do frontend/icons/.

    pip install pillow
    python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend" / "icons"
GREEN, GREEN_HI, DARK, BG = (58, 154, 42), (95, 210, 58), (13, 15, 13), (0, 0, 0)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="10" fill="#000"/>
  <circle cx="32" cy="32" r="26" fill="#0d0f0d" stroke="#3a9a2a" stroke-width="2.5"/>
  <circle cx="32" cy="32" r="17" fill="none" stroke="#3a9a2a" stroke-width="1.5"/>
  <circle cx="32" cy="32" r="8" fill="none" stroke="#3a9a2a" stroke-width="1.5"/>
  <path d="M32 6V58M6 32H58" stroke="#23601a" stroke-width="1.2"/>
  <path d="M32 32L32 6A26 26 0 0 1 55.4 20.7Z" fill="#5fd23a" fill-opacity=".35"/>
  <path d="M32 32L55.4 20.7" stroke="#5fd23a" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="43" cy="17" r="3" fill="#5fd23a"/>
</svg>
"""


def scope(size: int, scale: float = 1.0, rounded: bool = True) -> Image.Image:
    # rysujemy w 4x i skalujemy w dół (antyaliasing); scale < 1 = margines dla maskable
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 64  # siatka 64x64 jak w icon.svg
    if rounded:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=10 * u, fill=BG)
    else:
        d.rectangle((0, 0, s, s), fill=BG)
    c, k = s / 2, u * scale

    def circle(r, **kw):
        d.ellipse((c - r * k, c - r * k, c + r * k, c + r * k), **kw)

    circle(26, fill=DARK, outline=GREEN, width=round(2.5 * k))
    circle(17, outline=GREEN, width=round(1.5 * k))
    circle(8, outline=GREEN, width=round(1.5 * k))
    d.line((c, c - 26 * k, c, c + 26 * k), fill=(35, 96, 26), width=round(1.2 * k))
    d.line((c - 26 * k, c, c + 26 * k, c), fill=(35, 96, 26), width=round(1.2 * k))
    sweep = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sweep).pieslice((c - 26 * k, c - 26 * k, c + 26 * k, c + 26 * k), -90, -25.8,
                                   fill=GREEN_HI + (90,))
    img = Image.alpha_composite(img, sweep)
    d = ImageDraw.Draw(img)
    d.line((c, c, c + 23.4 * k, c - 11.3 * k), fill=GREEN_HI, width=round(2.5 * k))
    r = 3 * k
    d.ellipse((c + 11 * k - r, c - 15 * k - r, c + 11 * k + r, c - 15 * k + r), fill=GREEN_HI)
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(SVG, "utf-8")
    for size in (192, 512):
        scope(size).save(OUT / f"icon-{size}.png", optimize=True)
    # maskable: rysunek w środkowych ~80%, pełne tło
    scope(512, scale=0.78, rounded=False).save(OUT / "icon-maskable-512.png", optimize=True)
    scope(180, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    scope(64).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("zapisano", OUT)


if __name__ == "__main__":
    main()
