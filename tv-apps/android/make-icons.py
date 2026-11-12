"""Draw Guest TV's Android TV icon and banner (Pillow).

    python3 tv-apps/android/make-icons.py

The outputs are committed (app/src/main/res/drawable-*), so you only run this to change the look.
The same house mark as the LG app's icon (tv-apps/lg), in guest-tv's colours: #14161d ground, the
warm #ffd89a mark and #f7f6f3 words. The font is the Antonio Light the Apple TV app carries.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "app", "src", "main", "res")
FONT = os.path.join(os.path.dirname(HERE), "tvos", "GuestTV", "Fonts", "CouchAntonio-Light.ttf")
GROUND = (0x14, 0x16, 0x1D)
WARM = (0xFF, 0xD8, 0x9A)
TEXT = (0xF7, 0xF6, 0xF3)
SS = 4   # drawn four times bigger, then scaled down, for smooth edges


def house(d, cx, cy, size, width):
    """The house outline: a roof, the walls and a door, centred on (cx, cy)."""
    s = size
    roof = [(cx - s * 0.5, cy - s * 0.02), (cx, cy - s * 0.46), (cx + s * 0.5, cy - s * 0.02)]
    d.line(roof, fill=WARM, width=width, joint="curve")
    wall_top = cy - s * 0.12
    left, right, bottom = cx - s * 0.36, cx + s * 0.36, cy + s * 0.42
    d.line([(left, wall_top), (left, bottom), (right, bottom), (right, wall_top)], fill=WARM, width=width, joint="curve")
    dw, dh = s * 0.16, s * 0.24
    d.rounded_rectangle([cx - dw / 2, bottom - dh, cx + dw / 2, bottom], radius=width * 0.4, fill=WARM)


def icon(px, path):
    im = Image.new("RGB", (px * SS, px * SS), GROUND)
    d = ImageDraw.Draw(im)
    house(d, px * SS / 2, px * SS / 2 + px * SS * 0.03, px * SS * 0.58, max(2, int(px * SS * 0.055)))
    im.resize((px, px), Image.LANCZOS).save(path, optimize=True)


def banner(w, h, path):
    W, H = w * SS, h * SS
    im = Image.new("RGB", (W, H), GROUND)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, int(H * 0.36))
    words = "Guest TV"
    box = d.textbbox((0, 0), words, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    mark = H * 0.42
    gap = H * 0.11
    total = mark + gap + tw
    x0 = (W - total) / 2
    house(d, x0 + mark / 2, H / 2 + mark * 0.02, mark, max(2, int(H * 0.035)))
    d.text((x0 + mark + gap - box[0], (H - th) / 2 - box[1]), words, font=font, fill=TEXT)
    im.resize((w, h), Image.LANCZOS).save(path, optimize=True)


def main():
    for folder, size in (("drawable-xhdpi", 96), ("drawable-xxhdpi", 144)):
        os.makedirs(os.path.join(RES, folder), exist_ok=True)
        icon(size, os.path.join(RES, folder, "icon.png"))
    for folder, (w, h) in (("drawable-xhdpi", (320, 180)), ("drawable-xxhdpi", (480, 270))):
        banner(w, h, os.path.join(RES, folder, "banner.png"))
    print("icons written to", RES)


if __name__ == "__main__":
    main()
