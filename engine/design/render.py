"""Macht aus einem Post-Paket (JSON vom Redaktions-Modul) fertige Bilder im CD „hängt.“.

Paket-Felder, die hier zählen:
  rubric   news | history | events | poll | warum | fact | platt | quiz | photo
  hook     1–3 kurze Zeilen, klein geschrieben (die große Headline)
  schild   kurzer Text am gelben Schild (optional)
  options  zwei Antworten bei poll/warum (statt Schild)
  slides   [{head, body}] → Karussell-Folgeseiten
"""
from __future__ import annotations

import re

import contextlib
import io
import random

from PIL import Image, ImageDraw, ImageOps

from . import cd

C = cd.C
PALETTES = {      # Hintergrund, Schrift
    "news": ("creme", "kirsche"), "history": ("kirsche", "creme"), "events": ("brombeer", "bubblegum"),
    "poll": ("bubblegum", "brombeer"), "warum": ("bubblegum", "brombeer"), "fact": ("creme", "brombeer"),
    "platt": ("kirsche", "creme"), "quiz": ("zitrone", "brombeer"), "photo": ("creme", "brombeer"),
}
# Alle Candy-Paare, die gut lesbar sind – die Engine wechselt sie ab, damit das Raster knallt
CANDY = [("creme", "kirsche"), ("kirsche", "creme"), ("bubblegum", "brombeer"), ("brombeer", "bubblegum"),
         ("zitrone", "brombeer"), ("brombeer", "zitrone"), ("creme", "brombeer"), ("bubblegum", "kirsche"),
         ("kirsche", "zitrone")]
# Ausreißer: erlaubte Paare, die im System bleiben, aber überraschen
WAGNIS = [("zitrone", "kirsche"), ("brombeer", "zitrone"), ("kirsche", "zitrone"), ("bubblegum", "kirsche"),
          ("zitrone", "brombeer"), ("creme", "bubblegum")]


@contextlib.contextmanager
def canvas(w, h):
    old = cd.W, cd.H
    cd.W, cd.H = w, h
    try:
        yield
    finally:
        cd.W, cd.H = old


def palette(rubric: str, wagnis: bool = False, rnd: random.Random | None = None, farbe=None):
    if farbe and len(farbe) == 2 and farbe[0] in C and farbe[1] in C:
        return C[farbe[0]], C[farbe[1]]
    if wagnis:
        bgk, ink = (rnd or random).choice(WAGNIS)
    else:
        bgk, ink = PALETTES.get(rubric, PALETTES["news"])
    return C[bgk], C[ink]


def schild_colors(bg, ink):
    """Das Schild ist zitronengelb – außer die Kachel ist selbst gelb, dann dreht es sich um."""
    if bg == C["zitrone"]:
        return bg, ink        # fg, bg
    return cd.SCHILD_TXT, cd.SCHILD


def fit_size(lines, max_w, max_h, top=300, low=110):
    for size in range(top, low - 1, -6):
        b = cd.Block(lines, cd.brico(size), (0, 0, 0))
        if b.im.width <= max_w and b.im.height <= max_h:
            return size
    return low


def _hook(img, lines, ink, ry, hcolor=None, max_h=None, schild=None):
    """Größte Headline, die passt – inklusive Schild, das am letzten Zeichen hängt und nicht aus dem Bild darf."""
    lines = [l for l in lines if l.strip()][:3] or ["wuppertal."]
    size = fit_size(lines, cd.W - 2 * cd.M - 40, max_h or int(cd.H * 0.48))
    while schild and size > 110:
        b = cd.Block(lines, cd.brico(size), (0, 0, 0))
        ax, _ = b.anchor(*cd.last_char(b), "bottom")
        sw = cd.schild_block(schild, max(84, min(128, int(size * 0.6)))).width
        if cd.M + ax + sw / 2 + 48 <= cd.W:
            break
        size -= 6
    return cd.headline(img, lines, ink, ry, size, hcolor=hcolor), size


def cover(pkg: dict, photo: Image.Image | None = None, more: bool = False, wagnis=False, rnd=None, w=1080, h=1350):
    rubric = pkg.get("rubric", "news")
    with canvas(w, h):
        bg, ink = palette(rubric, wagnis, rnd, pkg.get("farbe"))
        label = cd.LABELS.get(rubric, cd.LABELS["news"])
        if photo is not None:
            light = bg if bg != C["creme"] else C["bubblegum"]
            img = cd.duotone(ImageOps.fit(photo.convert("RGB"), (w, h), Image.LANCZOS), C["brombeer"], light, hi=0.8)
            rail_ink, text_c = C["brombeer"], C["creme"]
            ry = cd.rail(img, rail_ink, label, light, y0=_rail_y(h))
            hb, size = _hook(img, pkg["hook"], text_c, ry, hcolor=rail_ink, schild=_sch(pkg))
            fg, sbg = schild_colors(light, rail_ink)
            hint_bg, plate = rail_ink, light
        else:
            img = Image.new("RGB", (w, h), bg)
            ry = cd.rail(img, ink, label, bg, y0=_rail_y(h))
            hb, size = _hook(img, pkg["hook"], ink, ry, schild=_sch(pkg))
            rail_ink = ink
            fg, sbg = schild_colors(bg, ink)
            hint_bg, plate = bg, (ink if bg in (C["bubblegum"], C["zitrone"]) else None)
        hook_txt = " ".join(pkg.get("hook") or []).lower()
        def doppelt(t):      # Schild wiederholt nur, was in der Überschrift schon steht → weglassen
            w = [x for x in re.findall(r"[a-zäöüß0-9]+", (t or "").lower()) if len(x) > 2]
            return bool(w) and all(x in hook_txt for x in w)
        opts = [o for o in (pkg.get("options") or []) if o][:2]
        if any(doppelt(o) for o in opts):
            opts = []
        if doppelt(pkg.get("schild")):
            pkg = {**pkg, "schild": ""}
        ssize = max(84, min(128, int(size * 0.6)))
        if len(opts) == 2 and len(hb[0].lines) >= 1:
            b = hb[0]
            li = len(b.lines) - 1
            first = b.letters(li)[0] if b.letters(li) else 0
            a = cd.chain(img, hb, li, first, opts[0].lower(), rail_ink, size=ssize - 20, angle=4, fg=fg, bg=sbg)
            cd.chain(img, hb, *cd.last_char(b), opts[1].lower(), rail_ink, size=ssize - 20, angle=-5,
                     fg=sbg, bg=rail_ink, length=cd.CHAIN + a.height + cd.S["m"])
        elif pkg.get("schild"):
            cd.chain(img, hb, *cd.last_char(hb[0]), pkg["schild"][:22], rail_ink, size=ssize, fg=fg, bg=sbg)
        if more:
            cd.swipe_hint(img, hint_bg, plate=plate, ink=rail_ink)
        return cd.grain(img, 0.015 if photo is not None else 0.025)


def _sch(pkg):
    """Längster Schild-Text, der an der letzten Zeile hängt (Schild oder zweite Antwort)."""
    opts = [o for o in (pkg.get("options") or []) if o][:2]
    return opts[1].lower() if len(opts) == 2 else (pkg.get("schild") or "")[:22] or None


def _rail_y(h):
    return 250 if h > 1500 else cd.RAIL_Y          # Stories/Reels: Schiene unterhalb der Instagram-Kopfzeile


def follow(pkg: dict, slide: dict, more: bool, wagnis=False, rnd=None):
    rubric = pkg.get("rubric", "news")
    with canvas(1080, 1350):
        bg, ink = palette(rubric, wagnis, rnd, pkg.get("farbe"))
        img = Image.new("RGB", (cd.W, cd.H), bg)
        ry = cd.rail(img, ink, cd.LABELS.get(rubric, cd.LABELS["news"]), bg)
        head = (slide.get("head") or "").strip().lower()
        bottom = cd.boxed_hook(img, [head], ink, bg, ry, _boxed_size(head)) if head else ry
        body = (slide.get("body") or "").strip()
        avail = cd.H - bottom - cd.S["xl"] - (150 if more else 90)
        for size in range(64, 37, -2):
            f = cd.brico(size, 600, 90, 24)
            lh = int(size * 1.28)
            paras = [cd.wrap(p, f, cd.W - 2 * cd.M) for p in body.split("\n") if p.strip()]
            need = sum(len(p) * lh for p in paras) + cd.S["m"] * max(0, len(paras) - 1)
            if need <= avail:
                break
        d = ImageDraw.Draw(img)
        y = bottom + cd.S["xl"]
        for p in paras:
            for line in p:
                d.text((cd.M, y), line, font=f, fill=ink)
                y += lh
            y += cd.S["m"]
        if more:
            cd.swipe_hint(img, bg, plate=(ink if bg in (C["bubblegum"], C["zitrone"]) else None), ink=ink)
        return cd.grain(img)


def _boxed_size(head):
    f = 96
    while f > 60 and cd.Block([head], cd.brico(f), (0, 0, 0)).im.width > 1080 - 2 * cd.M - 60:
        f -= 4
    return f


def carousel(pkg: dict, photo=None, wagnis=False, seed=None) -> list[Image.Image]:
    rnd = random.Random(seed)
    slides = [s for s in (pkg.get("slides") or []) if (s.get("body") or s.get("head"))][:6]
    out = [cover(pkg, photo, more=bool(slides), wagnis=wagnis, rnd=random.Random(seed))]
    for i, s in enumerate(slides):
        out.append(follow(pkg, s, more=i < len(slides) - 1, wagnis=wagnis, rnd=random.Random(seed)))
    return out


def story(pkg: dict, photo=None, wagnis=False, seed=None) -> Image.Image:
    return cover(pkg, photo, more=False, wagnis=wagnis, rnd=random.Random(seed), w=1080, h=1920)


def damals(pkg: dict, old: Image.Image, new: Image.Image | None, more=True) -> list[Image.Image]:
    """damals/heute: oben das alte Foto, darunter das neue – beide hängen an der Schiene, wie alles bei uns."""
    with canvas(1080, 1350):
        ink, bg = C["brombeer"], C["creme"]
        img = Image.new("RGB", (cd.W, cd.H), bg)
        ry = cd.rail(img, ink, cd.LABELS["history"], bg)
        gap, couple = cd.HANG, 26
        h_each = (cd.H - ry - gap - couple - cd.S["l"]) // 2
        w = cd.W - 2 * cd.M
        boxes = [(old, f"damals · {pkg.get('schild') or 'früher'}"), (new, "heute")] if new is not None else [(old, f"damals · {pkg.get('schild') or 'früher'}")]
        if new is None:
            h_each = cd.H - ry - gap - cd.S["xl"]
        d = ImageDraw.Draw(img)
        y = ry + gap
        prev_bottom = ry
        for i, (photo, label) in enumerate(boxes):
            ph = ImageOps.fit(photo.convert("RGB"), (w, h_each), Image.LANCZOS)
            for gx in (cd.M + cd.S["l"], cd.M + w - cd.S["l"]):     # Aufhänger hinter dem Foto
                d.line((gx, prev_bottom - (0 if i == 0 else 10), gx, y + 10), fill=ink, width=cd.STROKE)
                if i == 0:
                    cd.bracket(img, gx, ry, ink)
            img.paste(ph, (cd.M, y))
            fg, sbg = (ink, C["zitrone"])
            s = cd.schild_block(label, 72, fg=fg, bg=sbg)
            img.paste(s, (cd.M + cd.S["m"], y + h_each - s.height - cd.S["m"]), s)
            prev_bottom = y + h_each
            y += h_each + couple
        if more and pkg.get("slides"):
            cd.swipe_hint(img, bg, ink=ink)
        return [cd.grain(img, 0.015)]


def community(photo: Image.Image, credit: str) -> Image.Image:
    """Echte Fotos von echten Leuten: kein Filter, nur die Schiene. Credit steht in der Caption."""
    with canvas(1080, 1350):
        img = ImageOps.fit(photo.convert("RGB"), (cd.W, cd.H), Image.LANCZOS)
        cd.rail(img, C["brombeer"], cd.LABELS["photo"], C["creme"])
        return img


def jpeg(img: Image.Image, q=92) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=q, optimize=True)
    return buf.getvalue()
