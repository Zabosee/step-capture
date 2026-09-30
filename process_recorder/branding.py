"""Logo des Process Recorders (per Pillow gezeichnet, keine Bilddateien nötig)."""
from __future__ import annotations

from PIL import Image, ImageDraw

TOP = (99, 102, 241)       # Indigo
BOTTOM = (168, 85, 247)    # Violett
RED = (239, 68, 68)


def make_logo(size: int = 256) -> Image.Image:
    """Abgerundetes Quadrat mit Farbverlauf, weißem Ring und rotem Aufnahmepunkt."""
    ss = 4                                   # Supersampling für glatte Kanten
    n = size * ss
    grad = Image.new("RGB", (n, n))
    px = grad.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * n)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.24), fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    c = n / 2
    r_ring, w_ring = n * 0.30, n * 0.055
    d.ellipse((c - r_ring, c - r_ring, c + r_ring, c + r_ring),
              outline=(255, 255, 255, 255), width=int(w_ring))
    r_dot = n * 0.16
    d.ellipse((c - r_dot, c - r_dot, c + r_dot, c + r_dot), fill=RED + (255,))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":      # erzeugt assets/icon.ico für den exe-Build
    import pathlib
    out = pathlib.Path(__file__).resolve().parent.parent / "assets"
    out.mkdir(exist_ok=True)
    make_logo(256).save(out / "icon.ico",
                        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
