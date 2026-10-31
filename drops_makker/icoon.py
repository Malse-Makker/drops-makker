from PIL import Image, ImageDraw

PAARS = (145, 70, 255, 255)
GRIJS = (130, 130, 140, 255)
# Stip rechtsonder: rood = kijkt live, groen = ingelogd en wacht, oranje = er
# is iets mis.
STIP = {
    "kijken": (235, 20, 20, 255),
    "wachten": (0, 190, 90, 255),
    "niet-ingelogd": (255, 150, 0, 255),
    "fout": (255, 150, 0, 255),
    "netwerkfout": (255, 150, 0, 255),
}
# Grijs zolang hij (nog) niet ingelogd is.
GRIJZE_STATEN = {"opstarten", "niet-ingelogd", "inloggen", "gestopt"}


def icoon_maken(maat=64, staat=None):
    """Paars vlak met een witte druppel (een drop), met een stip voor de status."""
    img = Image.new("RGBA", (maat, maat), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = maat / 64
    kleur = GRIJS if staat in GRIJZE_STATEN else PAARS
    d.rounded_rectangle((2 * s, 2 * s, 62 * s, 62 * s), radius=14 * s, fill=kleur)
    d.ellipse((19 * s, 27 * s, 45 * s, 53 * s), fill="white")
    d.polygon([(32 * s, 9 * s), (20 * s, 36 * s), (44 * s, 36 * s)], fill="white")
    if staat in STIP:
        d.ellipse((36 * s, 36 * s, 63 * s, 63 * s), fill=STIP[staat], outline="white", width=max(1, round(4 * s)))
    return img
