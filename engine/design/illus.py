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


# ── Handzeichen „Signal for Help“ als echte Zeichnung ─────────────────────
# Zeichnung: „Signal for Help gesture“ von Belbury, Wikimedia Commons, CC0 1.0 (assets/illus/)
import os
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "illus"


def _tint(path, ink, height):
    im = Image.open(path).convert("RGBA")
    im = im.resize((int(im.width * height / im.height), height), Image.LANCZOS)
    solid = Image.new("RGBA", im.size, tuple(ink) + (255,))
    solid.putalpha(im.getchannel("A"))
    return solid


def _label(d, text, xc, y, font, ink):
    tw = d.textlength(text, font=font)
    d.text((xc - tw / 2, y), text, font=font, fill=ink)


def signal_static(cover, ink, top=730, bottom=1250):
    """Beide Schritte nebeneinander (für Vorschau und als Standbild)."""
    from . import cd
    im = cover.convert("RGBA")
    d = ImageDraw.Draw(im)
    font = cd.brico(46, 800, 80, 24)
    h = bottom - top - 90
    a, b = _tint(ASSETS / "sfh_1.png", ink, h), _tint(ASSETS / "sfh_2.png", ink, int(h * 0.78))
    x1, x2 = im.width // 2 - 40 - a.width, im.width // 2 + 60
    im.alpha_composite(a, (x1, top))
    im.alpha_composite(b, (x2, top + h - b.height))
    _label(d, "1  daumen rein", x1 + a.width / 2, bottom - 70, font, ink)
    _label(d, "2  finger zu", x2 + b.width / 2, bottom - 70, font, ink)
    return im.convert("RGB")


def signal_frames(cover, ink, fps=30, top=725, bottom=1250):
    """Animation: Schritt 1, Überblendung zu Schritt 2, zurück – zweimal, als Schleife. 8 Sekunden."""
    from . import cd
    base = cover.convert("RGBA")
    font = cd.brico(56, 800, 80, 24)
    h = bottom - top - 110
    hands = [_tint(ASSETS / "sfh_1.png", ink, h), _tint(ASSETS / "sfh_2.png", ink, int(h * 0.8))]
    labels = ["1  daumen in die hand", "2  finger darüber schließen"]

    def layer(i, alpha, scale):
        hand = hands[i]
        if scale != 1:
            hand = hand.resize((max(1, int(hand.width * scale)), max(1, int(hand.height * scale))), Image.LANCZOS)
        if alpha < 1:
            hand = hand.copy()
            hand.putalpha(hand.getchannel("A").point(lambda v: int(v * alpha)))
        return hand

    seq = []   # (dauer, typ, i)
    for _ in range(2):     # endet, wie es anfängt: nahtlose Schleife
        seq += [(1.5, "hold", 0), (0.4, "x", 0), (1.7, "hold", 1), (0.4, "x", 1)]
    frames = []
    for dur, typ, i in seq:
        n = max(1, int(dur * fps))
        for k in range(n):
            t = k / n
            im = base.copy()
            d = ImageDraw.Draw(im)
            ease = t * t * (3 - 2 * t)
            if typ == "in":
                parts = [(i, ease, 0.9 + 0.1 * ease)]
                lab = (i, ease)
            elif typ == "hold":
                parts = [(i, 1, 1)]
                lab = (i, 1)
            else:
                j = 1 - i
                parts = [(i, 1 - ease, 1 - 0.06 * ease), (j, ease, 0.94 + 0.06 * ease)]
                lab = (j if t > 0.5 else i, abs(2 * t - 1))
            for idx, a, sc in parts:
                hand = layer(idx, a, sc)
                im.alpha_composite(hand, ((im.width - hand.width) // 2, bottom - 110 - hand.height))
            li, la = lab
            col = tuple(int(c) for c in ink) + (int(255 * la),)
            txt = Image.new("RGBA", im.size, (0, 0, 0, 0))
            _label(ImageDraw.Draw(txt), labels[li], im.width / 2, bottom - 80, font, col)
            im.alpha_composite(txt)
            frames.append(im.convert("RGB"))
    return frames


def write_video(frames, out_path, fps=30, ffmpeg="ffmpeg"):
    w, h = frames[0].size
    tmp = out_path + ".part.mp4"
    p = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                          "-r", str(fps), "-i", "-", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                          "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg fehlgeschlagen")
    os.replace(tmp, out_path)
    return out_path
