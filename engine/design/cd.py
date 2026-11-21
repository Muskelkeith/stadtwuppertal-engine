"""CD "hängt." v5 – Entwurf. Regeln aus JDs Feedback:
- Aufhänger landen dynamisch auf dem grafischen Scheitel des Buchstabens und gehen in ihn über
- nur EINE Schiene; alles hängt an ihr oder an etwas, das an ihr hängt
- Schilder optional mit runden Ecken wie Schwebebahnwagen
- Themen-Posts sind Karussells, Cover mit kleinem Wisch-Hinweis unten rechts
- Foto-Cover mit Duoton-Filter in Palettenfarben, Credits klein
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageOps

FD = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "assets" / "fonts") + "/"
OUT = "/tmp/cd/"
PH = "/tmp/"
W, H = 1080, 1350

C = {"bubblegum": (255, 140, 206), "kirsche": (236, 18, 52), "creme": (255, 246, 232),
     "brombeer": (56, 10, 66), "zitrone": (255, 232, 0)}
SCHILD, SCHILD_TXT = C["zitrone"], C["brombeer"]

S = {"2xs": 8, "xs": 16, "s": 24, "m": 32, "l": 48, "xl": 64, "2xl": 96, "3xl": 128}
M = 80
RAIL_Y, RAIL_H = 80, 104
HANG = S["l"]
CHAIN = S["xl"]
STROKE = 9      # = Streben im Träger (JD: schmaler ist besser)
CHORD, STRUT, PANEL = 14, 9, 64
TRACK_DISPLAY, TRACK_LABEL = -0.012, 0.010
ROUND = 0.0   # Eckenradius der Schilder als Anteil der Schildhöhe (0 = eckig)


def brico(size, wght=800, wdth=75, opsz=96):
    f = ImageFont.truetype(FD + "Bricolage.ttf", size)
    f.set_variation_by_axes([min(max(opsz, 12), 96), wght, wdth])
    return f


def grain(img, amount=0.025):
    n = Image.effect_noise(img.size, 50).convert("RGB")
    return Image.blend(img, ImageChops.multiply(img, n.point(lambda v: 170 + v // 3)), amount * 4)


def adv(font, a, b, t):
    return font.getlength(a + b) - font.getlength(b) + t


def tracked_len(text, font, track):
    t = track * font.size
    return sum(adv(font, a, b, t) for a, b in zip(text, text[1:])) + font.getlength(text[-1])


def draw_tracked(d, xy, text, font, fill, track=0.0):
    x, y = xy
    t = track * font.size
    for i, ch in enumerate(text):
        d.text((x, y), ch, font=font, fill=fill)
        if i + 1 < len(text):
            x += adv(font, ch, text[i + 1], t)


def track_for(size):
    """Laufweite nach Größe: groß minimal eng, klein offener (optische Größen)."""
    pts = [(60, 0.018), (100, 0.010), (150, 0.0), (200, -0.008), (300, -0.010)]
    if size <= pts[0][0]:
        return pts[0][1]
    for (s0, t0), (s1, t1) in zip(pts, pts[1:]):
        if size <= s1:
            return t0 + (t1 - t0) * (size - s0) / (s1 - s0)
    return pts[-1][1]


TRACK_AUTO = True


class Block:
    """Mehrzeiliger Text als RGBA, auf die Tinte beschnitten. Kennt die Lage jedes Zeichens."""

    def __init__(self, lines, font, fill, lead=0.86, track=None):
        if track is None:
            track = track_for(font.size) if TRACK_AUTO else TRACK_DISPLAY
        self.lines, self.font, self.track = lines, font, track
        self.lh = int(font.size * lead)
        self.pad = font.size // 2
        w = int(max(tracked_len(l, font, track) for l in lines)) + font.size
        h = self.lh * (len(lines) - 1) + int(font.size * 1.4)
        self.size = (w, h)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i, l in enumerate(lines):
            draw_tracked(d, (self.pad, i * self.lh), l, font, fill, track)
        self.bb = im.getchannel("A").getbbox()
        self.im = im.crop(self.bb)

    def char_x(self, li, ci):
        line, t = self.lines[li], self.track * self.font.size
        return self.pad + sum(adv(self.font, a, b, t) for a, b in zip(line[:ci], line[1:ci + 1]))

    def anchor(self, li, ci, side="top"):
        """Grafischer Scheitel (oben) oder Fußpunkt (unten) eines Zeichens, relativ zum Block."""
        ch = self.lines[li][ci]
        m = Image.new("L", self.size, 0)
        ImageDraw.Draw(m).text((self.char_x(li, ci), li * self.lh), ch, font=self.font, fill=255)
        bx = m.getbbox()
        px = m.load()
        rows = range(bx[1], bx[3]) if side == "top" else range(bx[3] - 1, bx[1] - 1, -1)
        band = max(2, int(self.font.size * 0.03))
        for y0 in rows:
            if any(px[x, y0] > 140 for x in range(bx[0], bx[2])):
                break
        ys = range(y0, y0 + band) if side == "top" else range(y0 - band + 1, y0 + 1)
        cols = sorted({x for y in ys for x in range(bx[0], bx[2]) if px[x, y] > 140})
        segs, cur = [], [cols[0]]
        for x in cols[1:]:
            if x == cur[-1] + 1:
                cur.append(x)
            else:
                segs.append(cur)
                cur = [x]
        segs.append(cur)
        cx_glyph = (bx[0] + bx[2]) / 2
        seg = min(segs, key=lambda s: abs((s[0] + s[-1]) / 2 - cx_glyph))
        return ((seg[0] + seg[-1]) / 2 - self.bb[0], y0 - self.bb[1])

    def letters(self, li):
        return [i for i, ch in enumerate(self.lines[li]) if ch.isalnum()]


def schild_block(text, size, fg=SCHILD_TXT, bg=SCHILD, arrow=False, rnd=None):
    rnd = ROUND if rnd is None else rnd
    f = brico(size, 800, 75)
    b = Block([text], f, fg, track=0.0)
    pv, ph = round(size * 0.22), round(size * 0.32)
    if rnd:
        ph = round(size * 0.40)
    extra = round(size * 0.78) if arrow else 0
    w, h = b.im.width + 2 * ph + extra, b.im.height + 2 * pv
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(h * rnd), fill=bg + (255,)) if rnd else d.rectangle((0, 0, w, h), fill=bg + (255,))
    out.paste(b.im, (ph, pv), b.im)
    if arrow:
        draw_arrow(d, ph + b.im.width + round(size * 0.2), pv + b.im.height * 0.55, size, fg)
    return out


def draw_arrow(d, x0, cy, size, fg):
    st = max(3, round(size * 0.13))
    x1 = x0 + round(size * 0.5)
    hd = round(size * 0.24)
    d.line((x0, cy, x1 - st // 2, cy), fill=fg, width=st)
    d.line((x1 - hd, cy - hd, x1, cy), fill=fg, width=st)
    d.line((x1 - hd, cy + hd, x1, cy), fill=fg, width=st)
    d.ellipse((x1 - st / 2, cy - st / 2, x1 + st / 2, cy + st / 2), fill=fg)


def bracket(img, x, y, color):
    ImageDraw.Draw(img).polygon([(x - 26, y - 2), (x + 26, y - 2), (x + STROKE / 2, y + 22), (x - STROKE / 2, y + 22)], fill=color)


def hang(canvas, im, pivot, angle=0.0, length=HANG, color=(0, 0, 0), eyelet=True, on_rail=False):
    d = ImageDraw.Draw(canvas)
    hx = im.width / 2
    big = Image.new("RGBA", (im.width * 3, im.height * 3), (0, 0, 0, 0))
    cx, cy = im.width * 3 // 2, im.height * 3 // 2
    big.paste(im, (int(cx - hx), cy), im)
    rot = big.rotate(angle, center=(cx, cy), resample=Image.BICUBIC)
    px, py = pivot[0], pivot[1] + length
    d.line((pivot[0], pivot[1], px, py), fill=color, width=STROKE)
    canvas.paste(rot, (int(px - cx), int(py - cy)), rot)
    if on_rail:
        bracket(canvas, pivot[0], pivot[1], color)
    if eyelet:
        r = 11
        d.ellipse((px - r, py - r, px + r, py + r), outline=color, width=6)


def truss(img, x0, x1, y, h, ink):
    d = ImageDraw.Draw(img)
    d.rectangle((x0, y, x1, y + CHORD), fill=ink)
    d.rectangle((x0, y + h - CHORD, x1, y + h), fill=ink)
    yt, yb = y + CHORD / 2, y + h - CHORD / 2
    x, i = x0, 0
    while x < x1:
        nx = x + PANEL
        d.line((x, yt, x, yb), fill=ink, width=STRUT)
        d.line((x, yb, nx, yt) if i % 2 == 0 else (x, yt, nx, yb), fill=ink, width=STRUT)
        x, i = nx, i + 1


def rail(img, ink, label, bg, y0=None):
    y0 = RAIL_Y if y0 is None else y0
    d = ImageDraw.Draw(img)
    truss(img, 0, img.width + PANEL, y0, RAIL_H, ink)
    f = brico(60, 800, 80, 48)
    lw = tracked_len(label, f, TRACK_LABEL)
    plate_r = math.ceil((M + lw + S["m"]) / PANEL) * PANEL
    d.rectangle((0, y0, plate_r, y0 + RAIL_H), fill=ink)
    xb = f.getbbox("x")
    y = y0 + RAIL_H / 2 - (xb[1] + f.getmetrics()[0]) / 2
    draw_tracked(d, (M - f.getbbox(label[0])[0], y), label, f, bg, TRACK_LABEL)
    return y0 + RAIL_H


LABELS = {"news": "was los, wuppertal?", "history": "was war, wuppertal?", "events": "was geht, wuppertal?",
          "poll": "sach ma, wuppertal?", "fact": "echt jetzt, wuppertal?", "platt": "wie heißt dat, wuppertal?",
          "photo": "guck ma, wuppertal.", "warum": "warum so, wuppertal?", "quiz": "na, wuppertal?",
          "kurios": "kurios, wuppertal.", "spotlight": "wer macht wat, wuppertal?"}


def headline(img, lines, ink, ry, size=212, hcolor=None, x=M):
    """Headline hängt an zwei Aufhängern: auf dem Scheitel des ersten und des letzten Buchstabens
    der ersten Zeile. Gleiche Farbe → der Strich läuft in den Buchstaben hinein."""
    b = Block(lines, brico(size), ink)
    y = ry + HANG
    hc = hcolor or ink
    lt = b.letters(0)
    d = ImageDraw.Draw(img)
    for ci in (lt[0], lt[-1]):
        ax, ay = b.anchor(0, ci, "top")
        gx = x + ax
        d.line((gx, ry, gx, y + ay + int(size * 0.12)), fill=hc, width=STROKE)  # endet hinter dem Buchstaben
        bracket(img, gx, ry, hc)
    img.paste(b.im, (int(x), int(y)), b.im)  # Schrift liegt immer über den Aufhängern
    return b, (x, y)


def chain(img, hb, li, ci, text, ink, size=128, angle=-6, arrow=False, fg=SCHILD_TXT, bg=SCHILD, length=CHAIN):
    """Schild hängt am Fußpunkt eines Zeichens (meist am Punkt)."""
    b, (x, y) = hb
    ax, ay = b.anchor(li, ci, "bottom")
    s = schild_block(text, size, arrow=arrow, fg=fg, bg=bg)
    hang(img, s, (x + ax, y + ay - int(b.font.size * 0.06)), angle=angle, length=length + int(b.font.size * 0.06), color=ink)
    img.paste(b.im, (int(x), int(y)), b.im)  # Kette beginnt hinter dem Punkt
    return s


def last_char(b, li=-1):
    li = len(b.lines) - 1 if li == -1 else li
    return li, len(b.lines[li]) - 1


def swipe_hint(img, bg, plate=None, size=52, ink=None):
    """Wisch-Schild unten rechts: helle Fläche (auf Creme: Schriftfarbe der Kachel), Schrift ausgestanzt in der Hintergrundfarbe."""
    plate = plate or (C["creme"] if bg != C["creme"] else (ink or C["brombeer"]))
    s = schild_block("wisch", size, fg=bg, bg=plate, arrow=True, rnd=0)
    img.paste(s, (int(W - M - s.width), int(H - S["xl"] - s.height)), s)


def wrap(text, font, width, track=0.0):
    """Gieriger Umbruch auf volle Satzbreite, keine Trennung."""
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if tracked_len(t, font, track) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def texture(img, color, panel, angle=0, offset=(0, 0)):
    """Träger-Muster als leise Textur im Hintergrund."""
    big = Image.new("RGBA", (img.width * 2, img.height * 2), (0, 0, 0, 0))
    h = int(panel * 1.6)
    global PANEL, CHORD, STRUT
    old = (PANEL, CHORD, STRUT)
    PANEL, CHORD, STRUT = panel, max(4, panel // 5), max(3, panel // 8)
    y = 0
    while y < big.height:
        truss(big, 0, big.width, y, h, color + (255,))
        y += h + int(panel * 0.9)
    PANEL, CHORD, STRUT = old
    big = big.rotate(angle, resample=Image.BICUBIC)
    l, t = (big.width - img.width) // 2 + offset[0], (big.height - img.height) // 2 + offset[1]
    big = big.crop((l, t, l + img.width, t + img.height))
    img.paste(big, (0, 0), big)


def tint(c, amt):
    """Leichte Variation der Grundfarbe (amt > 0 dunkler, < 0 heller)."""
    tgt = (0, 0, 0) if amt > 0 else (255, 255, 255)
    a = abs(amt)
    return tuple(int(c[i] * (1 - a) + tgt[i] * a) for i in range(3))


def tile(bgk, inkk, label):
    bg, ink = C[bgk], C[inkk]
    img = Image.new("RGB", (W, H), bg)
    ry = rail(img, ink, label, bg)
    return img, bg, ink, ry


def post(kind):
    if kind == "news":
        img, bg, ink, ry = tile("creme", "kirsche", LABELS["news"])
        hb = headline(img, ["schwebe-", "bahn macht", "blau."], ink, ry)
        chain(img, hb, *last_char(hb[0]), "sa + so", ink)
        swipe_hint(img, bg, ink=ink)
    elif kind == "poll":
        img, bg, ink, ry = tile("bubblegum", "brombeer", LABELS["poll"])
        hb = headline(img, ["wo ist der", "glühwein", "besser?"], ink, ry, 196)
        b = hb[0]
        # beide Antworten hängen an der letzten Zeile: am "b" und am Punkt des "?"
        # gestaffelt wie zwei Wagen: elberfeld kurz, barmen länger darunter
        a = chain(img, hb, 2, 1, "elberfeld", ink, size=100, angle=4)
        chain(img, hb, *last_char(b), "barmen", ink, size=100, angle=-5, fg=bg, bg=ink, length=CHAIN + a.height + S["m"])
    elif kind == "events":
        img, bg, ink, ry = tile("brombeer", "bubblegum", LABELS["events"])
        hb = headline(img, ["wochen-", "ende?", "couch? nö."], ink, ry)
        chain(img, hb, *last_char(hb[0]), "3 tipps", ink, size=120)
        swipe_hint(img, bg)
    elif kind == "fact":
        img, bg, ink, ry = tile("creme", "brombeer", LABELS["fact"])
        hb = headline(img, ["wuppertal", "hat 517", "treppen."], ink, ry)
        chain(img, hb, *last_char(hb[0]), "zähl nach.", ink)
    elif kind == "platt":
        img, bg, ink, ry = tile("kirsche", "creme", LABELS["platt"])
        hb = headline(img, ["kallen."], ink, ry, 300)
        chain(img, hb, *last_char(hb[0]), "= reden", ink, size=140)
    return grain(img)


# ── Karussell: Themen-Post ──────────────────────────────────
def boxed_hook(img, lines, ink, bg, ry, size=110):
    """Kleinere Hook auf Folgeslides: auf einem Schild, das an zwei Aufhängern am Träger hängt."""
    b = Block(lines, brico(size), bg, lead=0.88)
    pv, ph = round(size * 0.20), round(size * 0.26)
    box = Image.new("RGBA", (b.im.width + 2 * ph, b.im.height + 2 * pv), ink + (255,))
    box.paste(b.im, (ph, pv), b.im)
    y = ry + HANG
    d = ImageDraw.Draw(img)
    for gx in (M + S["l"], M + box.width - S["l"]):
        d.line((gx, ry, gx, y + 4), fill=ink, width=STROKE)
        bracket(img, gx, ry, ink)
    img.paste(box, (M, int(y)), box)
    return y + box.height


def body_block(lines, ink, size=66):
    return Block(lines, brico(size, 650, 88, 48), ink, lead=1.18, track=0.0)


def carousel(tex=None):
    slides = []
    def base():
        img, bg, ink, ry = tile("kirsche", "creme", LABELS["history"])
        if tex:
            texture(img, tint(bg, 0.07), tex)
            ry = rail(img, ink, LABELS["history"], bg)
        return img, bg, ink, ry

    img, bg, ink, ry = base()
    hb = headline(img, ["der kaiser", "fuhr zuerst."], ink, ry, 196)
    chain(img, hb, *last_char(hb[0]), "24.10.1900", ink, size=120)
    swipe_hint(img, bg)
    slides.append(grain(img))

    pages = [
        ("kaiserlicher testlauf.",
         ["Am 24. Oktober 1900 fuhren Kaiser Wilhelm II., Kaiserin Auguste Viktoria und ihr Gefolge mit der Schwebebahn vom Döppersberg bis nach Vohwinkel.",
          "Eine Sonderfahrt über rund die Hälfte der späteren Strecke. Eröffnet war die Bahn da noch gar nicht."]),
        ("und alle anderen?",
         ["Für alle anderen ging es am 1. März 1901 los, zuerst nur zwischen Kluse und Zoo. Bis Vohwinkel fuhr man ab dem 24. Mai 1901.",
          "Der Wagen von damals ist als einziger seiner Baureihe erhalten. Heute heißt er Kaiserwagen und fährt noch zu besonderen Anlässen."]),
    ]
    for i, (sub, paras) in enumerate(pages):
        img, bg, ink, ry = base()
        bottom = boxed_hook(img, [sub], C["creme"], C["kirsche"], ry, 96)
        f = brico(50, 600, 90, 24)
        y = bottom + S["xl"]
        d = ImageDraw.Draw(img)
        lh = int(f.size * 1.28)
        for p in paras:
            for line in wrap(p, f, W - 2 * M):
                d.text((M, y), line, font=f, fill=ink)
                y += lh
            y += S["m"]
        if i < len(pages) - 1:
            swipe_hint(img, bg)
        slides.append(grain(img))
    return slides


# ── Fotos ───────────────────────────────────────────────────
def cover(path, w=W, h=H, focus=(0.5, 0.5)):
    return ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS, centering=focus)


def duotone(im, dark, light, lo=0.0, hi=1.0):
    """Duoton in Palettenfarben. lo/hi stauchen den Tonwert, damit Schrift auf dem Foto lesbar bleibt."""
    g = ImageOps.autocontrast(im.convert("L"), cutoff=1).point(lambda v: int(255 * (lo + (hi - lo) * v / 255)))
    return ImageOps.colorize(g, dark, light)


def strip(text, size, ink, bg):
    b = Block([text], brico(size), ink)
    pv, ph = round(size * 0.12), round(size * 0.17)
    st = Image.new("RGBA", (b.im.width + 2 * ph, b.im.height + 2 * pv), (0, 0, 0, 0))
    r = int(st.height * ROUND) if ROUND else 0
    ImageDraw.Draw(st).rounded_rectangle((0, 0, st.width - 1, st.height - 1), radius=r, fill=bg + (255,)) if r else ImageDraw.Draw(st).rectangle((0, 0, st.width, st.height), fill=bg + (255,))
    st.paste(b.im, (ph, pv), b.im)
    return st


def credit(img, ry, name, ink, bg):
    s = schild_block("foto: " + name, 40, fg=ink, bg=bg)
    hang(img, s, (W - M - s.width / 2, ry), angle=-4, length=S["m"], color=ink, on_rail=True)


def photo_post(variant):
    if variant == "community":       # echtes Foto: ohne Filter, nur die Schiene
        img = cover(PH + "svantner.jpg", focus=(0.42, 0.5))
        ink, bg = C["brombeer"], C["creme"]
        ry = rail(img, ink, LABELS["photo"], bg)
    elif variant == "community_pur":  # echtes Foto: ganz ohne Overlay
        img = cover(PH + "svantner.jpg", focus=(0.42, 0.5))
    elif variant == "news":
        img = duotone(cover(PH + "pankiv.jpg", focus=(0.5, 0.62)), C["kirsche"], C["creme"], lo=0.42)
        ink, bg = C["kirsche"], C["creme"]
        ry = rail(img, ink, LABELS["news"], bg)
        hb = headline(img, ["neue bänke", "am wall."], C["brombeer"], ry, 150, hcolor=ink)
        chain(img, hb, *last_char(hb[0]), "ab montag", ink, size=100)
        swipe_hint(img, C["kirsche"])
    elif variant == "history":
        img = duotone(cover(PH + "rurac.jpg", focus=(0.45, 0.5)), C["brombeer"], C["bubblegum"], hi=0.8)
        ink, bg = C["brombeer"], C["bubblegum"]
        ry = rail(img, ink, LABELS["history"], bg)
        hb = headline(img, ["125 jahre", "abhängen."], C["creme"], ry, 196, hcolor=ink)
        chain(img, hb, *last_char(hb[0]), "1901 – 2026", ink, size=104)
        swipe_hint(img, C["brombeer"], plate=C["bubblegum"])
    return grain(img, 0.015)


# ── Boards ──────────────────────────────────────────────────
def sheet(ims, h=900, gap=16, bg=(250, 250, 250)):
    ims = [i.resize((int(i.width * h / i.height), h), Image.LANCZOS) for i in ims]
    c = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) + 1), h + 2 * gap), bg)
    x = gap
    for im in ims:
        c.paste(im, (x, gap))
        x += im.width + gap
    return c


def grad_bg(size, c0, c1, mode="vertical"):
    """Ultraleichter Verlauf. Rauschen danach verhindert Stufen."""
    w, h = size
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    if mode == "vertical":
        t = yy / (h - 1)
    elif mode == "diagonal":
        t = (xx / w + yy / h) / 2
    else:  # radial, Licht von oben links
        t = np.clip(np.hypot(xx - w * 0.15, yy - h * 0.1) / (h * 1.1), 0, 1)
    arr = np.zeros((h, w, 3))
    for i in range(3):
        arr[..., i] = c0[i] + (c1[i] - c0[i]) * t
    return Image.fromarray(arr.clip(0, 255).astype("uint8"))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_test():
    out = []
    k = C["kirsche"]
    variants = [None,
                ("vertical", tint(k, 0.06), tint(k, -0.04)),
                ("diagonal", k, mix(k, C["bubblegum"], 0.16)),
                ("radial", mix(k, C["bubblegum"], 0.12), tint(k, 0.06))]
    for v in variants:
        img, bg, ink, ry = tile("kirsche", "creme", LABELS["history"])
        if v:
            img.paste(grad_bg(img.size, v[1], v[2], v[0]), (0, 0))
            ry = rail(img, ink, LABELS["history"], bg)
        hb = headline(img, ["der kaiser", "fuhr zuerst."], ink, ry, 196)
        chain(img, hb, *last_char(hb[0]), "24.10.1900", ink, size=120)
        swipe_hint(img, bg)
        out.append(grain(img))
    return out


def tracking_test():
    global TRACK_AUTO
    rows = []
    for auto in (False, True):
        TRACK_AUTO = auto
        sl = carousel()
        rows.append(sl[1].crop((0, 120, 1080, 620)))
        rows.append(sl[0].crop((0, 120, 1080, 620)))
    TRACK_AUTO = True
    return rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sheet(tracking_test(), h=500).save(OUT + "laufweite_vorher_nachher.jpg", quality=92)
    sheet(carousel()).save(OUT + "karussell.jpg", quality=92)
    sheet(gradient_test()).save(OUT + "verlauf_test.jpg", quality=92)
    print("ok")
