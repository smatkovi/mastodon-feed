#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Builds the launcher icon: Mastodon's mark in MeeGo's own icon shape.

Harmattan launcher icons are not free-form -- every stock icon is cut to the
same rounded-square "squircle", and an icon that ignores it (a plain circle,
say) reads as foreign on the home screen. So the silhouette is taken
literally from a stock icon's alpha channel rather than approximated:
/usr/share/themes/blanco/meegotouch/icons/icon-l-*.png all carry it, pixel
for pixel.

Everything is drawn at 4x and scaled down at the end; the squircle's curve
and the glyph's shoulders both alias badly at 80 px otherwise.
"""
from PIL import Image, ImageFilter

HERE = __file__.rsplit("/", 1)[0]
MASK_SOURCE = HERE + "/mask-icon-l.png"   # a stock icon, kept beside the script
GLYPH_SOURCE = HERE + "/icon-80-rund.png" # the round icon we started with; kept
                                          # separate so the script stays
                                          # repeatable -- it writes icon-80.png

S = 320                                   # working size, 4x the largest output
TOP = (0x9B, 0x9D, 0xFF)                  # Mastodon purple, lightened
BOTTOM = (0x44, 0x3D, 0xC8)               # and darkened, for the usual top-lit look


def squircle():
    """MeeGo's icon silhouette, straight out of a stock icon's alpha."""
    stock = Image.open(MASK_SOURCE).convert("RGBA")
    return stock.split()[3].resize((S, S), Image.LANCZOS)


# The round icon is purple (darkest channel around 57) with a white mark
# (255). Reading the mark out on a ramp between the two, rather than with a
# yes/no threshold, keeps the source's own antialiasing -- threshold it and
# the 80-pixel staircase gets baked in and survives every later resize.
INK_LOW, INK_HIGH = 90.0, 230.0


def glyph():
    """The white "m" out of the round icon, as a soft mask."""
    src = Image.open(GLYPH_SOURCE).convert("RGBA")
    px = src.load()
    out = Image.new("L", src.size, 0)
    op = out.load()
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            r, g, b, a = px[x, y]
            if a < 100:
                continue
            level = (min(r, g, b) - INK_LOW) / (INK_HIGH - INK_LOW)
            op[x, y] = max(0, min(255, int(level * 255)))
    box = out.point(lambda v: 255 if v > 40 else 0).getbbox()
    return out.crop(box).resize((S, S), Image.LANCZOS)


def build():
    mask = squircle()

    # Body: a plain vertical gradient. Flat colour looks dead next to the
    # stock icons, which are all lit from the top.
    body = Image.new("RGB", (S, S))
    bp = body.load()
    for y in range(S):
        t = y / float(S - 1)
        colour = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(S):
            bp[x, y] = colour

    # Gloss across the top third, the way the blanco icons carry it.
    gloss = Image.new("L", (S, S), 0)
    gp = gloss.load()
    for y in range(int(S * 0.46)):
        value = int(70 * (1.0 - y / (S * 0.46)) ** 1.6)
        for x in range(S):
            gp[x, y] = value
    body = Image.composite(Image.new("RGB", (S, S), (255, 255, 255)), body, gloss)

    icon = body.convert("RGBA")
    icon.putalpha(mask)

    # The mark, centred and sized so it keeps the margin stock icons keep.
    mark = glyph()
    width = int(S * 0.47)
    height = int(width * mark.size[1] / float(mark.size[0]))
    mark = mark.resize((width, height), Image.LANCZOS)
    white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    white.putalpha(mark)
    icon.paste(white, ((S - width) // 2, (S - height) // 2), white)

    # Cut once more: the paste must not spill over the silhouette's edge.
    icon.putalpha(Image.composite(icon.split()[3], Image.new("L", (S, S), 0), mask))
    return icon


def main():
    icon = build()
    for size in (80, 64):
        icon.resize((size, size), Image.LANCZOS).save("%s/icon-%d.png" % (HERE, size))
        print("icon-%d.png geschrieben" % size)


if __name__ == "__main__":
    main()
