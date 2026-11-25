"""Kleine Piktogramme, die die Engine selbst zeichnet (keine fremden Bilder nötig)."""
from PIL import Image, ImageDraw

S = 4  # Supersampling


def _rr(d, box, r, fill):
    d.rounded_rectangle([int(v * S) for v in box], radius=int(r * S), fill=fill)


def _hand(step: int, ink, bg, w=300, h=380):
    """Piktogramm einer Hand, Handfläche zum Betrachter.
    1 = offene Hand, 2 = Daumen in die Handfläche geklappt, 3 = Finger über den Daumen geschlossen."""
    im = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    _rr(d, (108, 300, 192, 372), 16, ink)                          # Handgelenk
    if step in (1, 2):
        for x0, top in ((70, 78), (110, 50), (150, 58), (190, 96)):  # Zeige-, Mittel-, Ring-, kleiner Finger
            _rr(d, (x0, top, x0 + 32, 215), 16, ink)
        _rr(d, (70, 180, 222, 322), 40, ink)                       # Handfläche
    if step == 1:
        th = Image.new("RGBA", im.size, (0, 0, 0, 0))
        _rr(ImageDraw.Draw(th), (50, 190, 88, 306), 19, ink)
        th = th.rotate(26, center=(88 * S, 306 * S), resample=Image.BICUBIC)   # Daumen abgespreizt, hängt an der Hand
        im.alpha_composite(th)
    if step == 2:
        th = Image.new("RGBA", im.size, (0, 0, 0, 0))              # Daumen schräg in die Handfläche geklappt
        td = ImageDraw.Draw(th)
        _rr(td, (66, 236, 200, 280), 22, bg)
        _rr(td, (72, 242, 194, 274), 16, ink)
        th = th.rotate(14, center=(70 * S, 270 * S), resample=Image.BICUBIC)
        im.alpha_composite(th)
    if step == 3:
        _rr(d, (68, 172, 224, 322), 40, ink)                       # geschlossene Faust
        for y in (206, 240, 274):                                  # Fugen der eingeklappten Finger
            d.rectangle([int(60 * S), int(y * S), int(232 * S), int((y + 5) * S)], fill=bg)
    return im.resize((w, h), Image.LANCZOS)


def signal_for_help(ink, bg, width=900):
    """Drei Schritte des internationalen Handzeichens „Signal for Help“ mit Nummern."""
    from . import cd
    hw, hh = 260, 330
    gap = 40
    img = Image.new("RGBA", (3 * hw + 2 * gap, hh + 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = cd.brico(54, 800, 80, 24)
    except Exception:      # noqa: BLE001
        font = None
    for i in range(3):
        hand = _hand(i + 1, ink, bg).resize((hw, hh), Image.LANCZOS)
        x = i * (hw + gap)
        img.alpha_composite(hand, (x, 0))
        label = str(i + 1)
        if font:
            tw = d.textlength(label, font=font)
            d.text((x + hw / 2 - tw / 2, hh + 18), label, font=font, fill=ink)
    scale = width / img.width
    return img.resize((width, int(img.height * scale)), Image.LANCZOS)
