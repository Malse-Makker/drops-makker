from PIL import Image, ImageDraw


def icoon_maken(maat=64):
    """Paars vlak met een witte druppel: een drop."""
    img = Image.new("RGBA", (maat, maat), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = maat / 64
    d.rounded_rectangle((2 * s, 2 * s, 62 * s, 62 * s), radius=14 * s, fill=(145, 70, 255, 255))
    d.ellipse((19 * s, 27 * s, 45 * s, 53 * s), fill="white")
    d.polygon([(32 * s, 9 * s), (20 * s, 36 * s), (44 * s, 36 * s)], fill="white")
    return img
