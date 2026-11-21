"""Reel aus einem Post-Paket: feste Schiene, Fotos mit Dauer-Zoom, Satz-Kästen hängen als Zug
am Träger, Pausen vor den Pointen, harter Schnitt auf die Endkarte. Musik aus assets/music, wenn dort Stücke liegen, sonst still.

pkg["reel"] = [{"head": "und alle anderen?", "lines": ["…", "…"], "gag": "Kennt man ja."}, …]
Der Gag des letzten Zugs wird zur gelben Pointe.
"""
from __future__ import annotations

import itertools
import math
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageOps

from . import cd
from .render import canvas

W, H, FPS = 1080, 1920, 30
RY0 = 250
CX = W // 2
MAXW = W - 2 * 80
COUPLE = 26
NB = " "
INK, BG = cd.C["brombeer"], cd.C["bubblegum"]
CREME, ZITRONE, KIRSCHE = cd.C["creme"], cd.C["zitrone"], cd.C["kirsche"]
DROP, DROP_PUNCH = 0.30, 0.20


def eo(x):
    x = min(max(x, 0), 1)
    return 1 - (1 - x) ** 3


def ei(x):
    x = min(max(x, 0), 1)
    return x ** 3


def swing(tau, amp=5.0, freq=0.85, damp=2.4):
    return 0.0 if tau <= 0 else -amp * math.exp(-damp * tau) * math.sin(2 * math.pi * freq * tau)


def place(frame, lay, pivot, x, ry, angle):
    if abs(angle) > 0.03:
        big = Image.new("RGBA", (lay.width * 2, lay.height * 2), (0, 0, 0, 0))
        big.paste(lay, (int(lay.width - pivot[0]), int(lay.height - pivot[1])), lay)
        rot = big.rotate(angle, center=(lay.width, lay.height), resample=Image.BICUBIC)
        frame.paste(rot, (int(x + pivot[0] - lay.width), int(ry - lay.height)), rot)
    else:
        frame.paste(lay, (int(x), int(ry)), lay)


def hanging_schild(frame, ax, ay, text, size, t_rel, line=CREME, drop=True):
    if t_rel < 0:
        return
    s = cd.schild_block(text, size)
    k = eo(t_rel / 0.28) if drop else 1
    length = cd.CHAIN * k
    ang = swing(t_rel - (0.28 if drop else 0), amp=7 if drop else 3, freq=1.1, damp=2.2) if k >= 1 else 0
    big = Image.new("RGBA", (s.width * 3, s.height * 3), (0, 0, 0, 0))
    cx, cy = s.width * 3 // 2, s.height * 3 // 2
    big.paste(s, (int(cx - s.width / 2), cy), s)
    rot = big.rotate(ang, center=(cx, cy), resample=Image.BICUBIC)
    d = ImageDraw.Draw(frame)
    d.line((ax, ay - 6, ax, ay + length), fill=line, width=cd.STROKE)
    if k > 0.15:
        frame.paste(rot, (int(ax - cx), int(ay + length - cy)), rot)
        d.ellipse((ax - 11, ay + length - 11, ax + 11, ay + length + 11), outline=line, width=6)


def bwrap(text, f, maxw, track=0.0):
    """Zeilenumbruch mit ausgeglichenen Zeilen, in linearer Zeit (früher alle Kombinationen – viel zu langsam)."""
    words = [w for w in text.split(" ") if w]
    if not words:
        return [""]
    width = lambda t: cd.tracked_len(t, f, track)            # noqa: E731

    def greedy(limit):
        lines, cur = [], ""
        for w_ in words:
            t_ = (cur + " " + w_).strip()
            if cur and width(t_) > limit:
                lines.append(cur)
                cur = w_
            else:
                cur = t_
        return lines + [cur]

    base = greedy(maxw)
    if len(base) == 1:
        return base
    # so schmal wie möglich bei gleicher Zeilenzahl → gleichmäßige Zeilen
    lo, hi = max(width(w_) for w_ in words), maxw
    best = base
    for _ in range(12):
        mid = (lo + hi) / 2
        cand = greedy(mid)
        if len(cand) <= len(base):
            best, hi = cand, mid
        else:
            lo = mid
    return best


def headline_c(lines, size, color, hcolor, extra=0):
    f = cd.brico(size)
    blocks = [cd.Block([ln], f, color) for ln in lines]
    lead = int(size * 0.86)
    wmax = max(b.im.width for b in blocks)
    hang = cd.HANG + extra
    lay = Image.new("RGBA", (wmax + 80, hang + lead * (len(lines) - 1) + blocks[-1].im.height + 60), (0, 0, 0, 0))
    xs = [40 + (wmax - b.im.width) // 2 for b in blocks]
    b0 = blocks[0]
    lt = b0.letters(0) or [0]
    d = ImageDraw.Draw(lay)
    for ci in (lt[0], lt[-1]):
        ax, ay = b0.anchor(0, ci, "top")
        d.line((xs[0] + ax, 0, xs[0] + ax, hang + ay + int(size * 0.12)), fill=hcolor, width=cd.STROKE)
        cd.bracket(lay, xs[0] + ax, 0, hcolor)
    for i, b in enumerate(blocks):
        lay.paste(b.im, (xs[i], hang + lead * i), b.im)
    bl = blocks[-1]
    last = bl.anchor(*cd.last_char(bl), "bottom")
    return lay, (lay.width / 2, 0), (xs[-1] + last[0], hang + lead * (len(lines) - 1) + last[1])


STYLE = {"head": (100, (800, 75, 96), CREME, INK, (24, 36), 0.92),
         "line": (84, (700, 90, 48), INK, CREME, (26, 38), 1.14),
         "pop": (140, (800, 75, 96), INK, ZITRONE, (28, 40), 0.92),
         "cap": (56, (700, 90, 48), INK, CREME, (18, 28), 1.12)}
SAFE_TOP, SAFE_BOTTOM = RY0 + cd.RAIL_H, 1580       # darunter liegt bei Reels die Instagram-Oberfläche
MID = (SAFE_TOP + SAFE_BOTTOM) // 2


def clean(text):
    return " ".join((text or "").replace("\u00a0", " ").replace("\u202f", " ").split(" ")).strip()


def make_box(kind, text, maxw=MAXW, max_lines=6):
    """Satz-Kasten. Wird so lange kleiner gesetzt, bis jede Zeile sicher ins Bild passt."""
    size0, ax, fg, bgc, pad, lead = STYLE[kind]
    text = "\n".join(clean(t) for t in text.split("\n"))
    for size in range(size0, 39, -4):
        f = cd.brico(size, *ax)
        track = 0.0 if kind in ("line", "cap") else cd.track_for(size)
        lines = [ln for part in text.split("\n") for ln in bwrap(part, f, maxw - 2 * pad[1], track)]
        bs = [cd.Block([ln], f, fg, track=0.0 if kind in ("line", "cap") else None) for ln in lines]
        if max(b.im.width for b in bs) <= maxw - 2 * pad[1] and len(lines) <= max_lines:
            break
    step = int(size * lead)
    wmax = max(b.im.width for b in bs)
    hh = step * (len(bs) - 1) + bs[-1].im.height
    box = Image.new("RGBA", (wmax + 2 * pad[1], hh + 2 * pad[0]), bgc + (255,))
    for i, b in enumerate(bs):
        box.paste(b.im, (pad[1] + (wmax - b.im.width) // 2, pad[0] + step * i), b.im)
    return box


def split_long(text, limit=150):
    """Zu lange Sätze an Komma oder Gedankenstrich teilen, damit jeder Kasten groß bleibt."""
    if len(text) <= limit:
        return [text]
    for sep in (". ", "; ", " – ", ", "):
        if sep in text:
            mid = len(text) // 2
            cut = min((i for i in range(len(text)) if text.startswith(sep, i)), key=lambda i: abs(i - mid))
            a, b = text[:cut + len(sep.rstrip())].strip(), text[cut + len(sep):].strip()
            if a and b:
                return split_long(a, limit) + split_long(b, limit)
    return [text]


def read_time(kind, text):
    return 0.9 if kind == "head" else 0.5 + 0.25 * len(text.replace(NB, " ").replace("\n", " ").split())


class Reel:
    def __init__(self, pkg: dict, photos: list[Image.Image], ffmpeg: str = "ffmpeg"):
        self.ffmpeg = ffmpeg
        self.label = cd.LABELS.get(pkg.get("rubric", "history"), cd.LABELS["history"])
        self.photos = [cd.duotone(ImageOps.fit(p.convert("RGB"), (1296, 2304), Image.LANCZOS), INK, BG, hi=0.8)
                       for p in photos] or [Image.new("RGB", (1296, 2304), BG)]
        with canvas(W, H):
            self.rail = Image.new("RGBA", (W, cd.RAIL_H + 40), (0, 0, 0, 0))
            cd.rail(self.rail, INK, self.label, BG, y0=0)
            hook = [l for l in pkg.get("hook", []) if l][:3] or ["wuppertal."]
            size = self._hook_size(hook)
            probe, _, _ = headline_c(hook, size, CREME, CREME)
            extra = max(0, int(MID - probe.height / 2 - SAFE_TOP - 40))
            self.head, self.head_piv, self.head_last = headline_c(hook, size, CREME, CREME, extra)
        self.schild = (pkg.get("schild") or "")[:22]
        sw = cd.schild_block(self.schild, 120).width if self.schild else 0
        right = max(self.head.width - 40, self.head_last[0] + sw / 2)
        self.hook_x = CX - right / 2
        self.trains = self._trains(pkg.get("reel") or [])
        self.hook_end = 4.3
        t = self.hook_end
        for i, tr in enumerate(self.trains):
            tr["photo"] = self.photos[(i + 1) % len(self.photos)]
            tr["t_in"] = t
            if "bild" in tr:
                tr["drops"] = [t]
                tr["t_out"] = t + 3.4 + (read_time("line", tr["items"][0][1]) * 0.5 if tr["items"] else 0)
                t = tr["t_out"] + 0.3
                continue
            td = t + 0.8
            tr["drops"] = [t]
            for j in range(1, len(tr["items"])):
                k, s, _ = tr["items"][j - 1]
                td += read_time(k, s)
                fl = tr["items"][j][2]
                td += 0.75 if fl == "punch" else 0.55 if fl == "beat" else 0
                tr["drops"].append(td)
            k, s, fl = tr["items"][-1]
            tr["t_out"] = td + DROP + read_time(k, s) + (1.1 if fl == "punch" else 0.6 if fl == "beat" else 0.2)
            t = tr["t_out"] + 0.6
        self.end_t = (self.trains[-1]["t_out"] + 0.15) if self.trains else self.hook_end
        self.total = self.end_t + 3.0

    @staticmethod
    def _hook_size(lines):
        for size in range(220, 120, -6):
            if max(cd.Block([l], cd.brico(size), (0, 0, 0)).im.width for l in lines) <= W - 2 * 80 - 120:
                return size
        return 120

    def _trains(self, spec):
        out = []
        for i, tr in enumerate(spec[:6]):
            if tr.get("_img") is not None:          # Bild-Szene: großes Foto statt Text
                img = ImageOps.fit(tr["_img"].convert("RGB"), (1296, 2304), Image.LANCZOS)
                cap = clean(tr.get("text") or tr.get("head") or "")
                out.append({"bild": img, "items": [("cap", cap, "")] if cap else [],
                            "boxes": [make_box("cap", cap, maxw=W - 2 * 120, max_lines=5)] if cap else [],
                            "credit": tr.get("_credit") or ""})
                continue
            items = []
            if tr.get("head"):
                items.append(("head", tr["head"].lower(), ""))
            for l in [x for x in tr.get("lines", []) if x][:4]:
                items += [("line", part, "") for part in split_long(clean(l))]
            if tr.get("gag"):
                last = i == len(spec[:6]) - 1
                items.append(("pop" if last else "line", tr["gag"], "punch" if last else "beat"))
            if not items:
                continue
            # Passt der Zug nicht in den sicheren Bereich, wird er geteilt – nie wird Text weggeworfen.
            groups, cur = [], []
            room = SAFE_BOTTOM - SAFE_TOP - 60
            for it in items:
                trial = cur + [it]
                if cur and cd.HANG + sum(make_box(k, s_).height + COUPLE for k, s_, _ in trial) > room:
                    groups.append(cur)
                    cur = ([items[0]] if items[0][0] == "head" else []) + [it]
                else:
                    cur = trial
            groups.append(cur)
            for g in groups:
                boxes = [make_box(k, s_) for k, s_, _ in g]
                stack = cd.HANG + sum(b.height + COUPLE for b in boxes)
                out.append({"items": g, "boxes": boxes, "offset": 40,   # oben anhängen, nicht in die Mitte hängen lassen
                           
                            "tilts": [0.0] + [(-1.3 if j % 2 else 1.1) for j in range(1, len(boxes))]})
        return out

    # ── Ebenen ──────────────────────────────────────────────
    def bg_frame(self, img, t_local, dur):
        z = 1 + 0.10 * min(t_local / max(dur, 0.1), 1)
        w, h = int(W * 1.2 / z), int(H * 1.2 / z)
        x0, y0 = (img.width - w) // 2, (img.height - h) // 2
        return img.crop((x0, y0, x0 + w, y0 + h)).resize((W, H), Image.BILINEAR)

    def train_layer(self, tr, t):
        boxes, tilts, items = tr["boxes"], tr["tilts"], tr["items"]
        off = tr.get("offset", 0)
        wmax = max(b.width for b in boxes) + 140
        lay = Image.new("RGBA", (wmax, off + cd.HANG + sum(b.height + COUPLE for b in boxes) + 120), (0, 0, 0, 0))
        cx = wmax / 2
        d = ImageDraw.Draw(lay)
        tops, y = [], cd.HANG + off
        for b in boxes:
            tops.append(y)
            y += b.height + COUPLE
        vis = []
        for i, b in enumerate(boxes):
            td = tr["drops"][i]
            if t < td:
                break
            if i == 0:
                vis.append((0, tops[0], 1.0))
                continue
            dd = DROP_PUNCH if items[i][2] == "punch" else DROP
            vis.append((i, tops[i] - (1 - eo((t - td) / dd)) * (b.height + COUPLE), eo((t - td - dd) / 0.25)))
        ins = cd.S["l"]
        w0 = boxes[0].width
        for gx in (cx - w0 / 2 + ins, cx + w0 / 2 - ins):
            d.line((gx, 0, gx, off + cd.HANG + 10), fill=CREME, width=cd.STROKE)
            cd.bracket(lay, gx, 0, CREME)
        for i, ytop, _ in vis[1:]:
            prev_bot = tops[i - 1] + boxes[i - 1].height
            if ytop + 10 > prev_bot:
                span = min(boxes[i - 1].width, boxes[i].width)
                for gx in (cx - span / 2 + ins, cx + span / 2 - ins):
                    d.line((gx, prev_bot - 10, gx, ytop + 10), fill=CREME, width=cd.STROKE)
        for i, ytop, settle in reversed(vis):
            b = boxes[i]
            if i > 0:
                cut = int(max(0, tops[i - 1] + boxes[i - 1].height - ytop))
                if cut >= b.height:
                    continue
                if cut:
                    b, ytop = b.crop((0, cut, b.width, b.height)), ytop + cut
            ang = tilts[i] * settle
            if abs(ang) > 0.02:
                r = b.rotate(ang, expand=True, resample=Image.BICUBIC)
                lay.paste(r, (int(cx - r.width / 2), int(ytop + b.height / 2 - r.height / 2)), r)
            else:
                lay.paste(b, (int(cx - b.width / 2), int(ytop)), b)
        return lay, (cx, 0)

    def train_pos(self, tr, t):
        x = CX + (W + 200) * (1 - eo((t - tr["t_in"]) / 0.8))
        ang = swing(t - tr["t_in"] - 0.8, amp=4)
        if t >= tr["t_out"]:
            x = CX - (W + 600) * ei((t - tr["t_out"]) / 0.6)
            ang = 2.5 * ei((t - tr["t_out"]) / 0.6)
        for i, td in enumerate(tr["drops"][1:], start=1):
            p = tr["items"][i][2] == "punch"
            ang += swing(t - td - (DROP_PUNCH if p else DROP), amp=3.0 if p else 1.6, freq=1.2, damp=2.6 if p else 3.0)
        return x, ang

    def frame(self, t):
        if t >= self.end_t:
            return self.end_card(t - self.end_t)
        if t < self.hook_end:
            img, t0, dur = self.photos[0], 0, self.hook_end
        else:
            cur = [tr for tr in self.trains if t >= tr["t_in"]][-1]
            if "bild" in cur and t < cur["t_out"] + 0.3:
                return self.photo_scene(cur, t - cur["t_in"])
            img, t0, dur = cur["photo"], cur["t_in"], cur["t_out"] + 0.6 - cur["t_in"]
        with canvas(W, H):
            fr = self.bg_frame(img, t - t0, dur).convert("RGBA")
            fr.paste(self.rail, (0, RY0), self.rail)
            ry = RY0 + cd.RAIL_H
            if t < self.hook_end + 0.1:
                x = self.hook_x + (W + 200) * (1 - eo((t - 0.15) / 0.9))
                ang = swing(t - 1.05)
                if t >= 3.6:
                    x = self.hook_x - (W + 600) * ei((t - 3.6) / 0.7)
                    ang = 2.5 * ei((t - 3.6) / 0.7)
                if t >= 0.15:
                    place(fr, self.head, self.head_piv, x, ry, ang)
                    if self.schild:
                        hanging_schild(fr, x + self.head_last[0], ry + self.head_last[1] - 4, self.schild, 120, t - 1.35)
            for tr in self.trains:
                if "bild" not in tr and tr["t_in"] <= t < tr["t_out"] + 0.6:
                    xc, ang = self.train_pos(tr, t)
                    lay, piv = self.train_layer(tr, t)
                    place(fr, lay, piv, xc - piv[0], ry, ang)
            return fr.convert("RGB")

    def photo_scene(self, tr, tl):
        """Großes Foto (historisch oder aktuell) mit langsamem Zoom, Bildunterschrift unten im sicheren Bereich."""
        dur = tr["t_out"] + 0.3 - tr["t_in"]
        with canvas(W, H):
            fr = self.bg_frame(tr["bild"], tl, dur).convert("RGBA")
            if tl < 0.25:                                  # kurzer Blitz-Übergang von der Farbe des Accounts
                veil = Image.new("RGBA", (W, H), BG + (int(255 * (1 - tl / 0.25)),))
                fr.alpha_composite(veil)
            fr.paste(self.rail, (0, RY0), self.rail)
            if tr["boxes"]:
                b = tr["boxes"][0]
                k = eo((tl - 0.5) / 0.4)
                if k > 0:
                    y = SAFE_BOTTOM - b.height - 110 + int((1 - k) * 60)
                    fr.paste(b, (CX - b.width // 2, y), b)
            if tr.get("credit"):
                cb = make_box("cap", tr["credit"][:80], maxw=W - 2 * 160, max_lines=2)
                cb = cb.resize((int(cb.width * 0.55), int(cb.height * 0.55)), Image.LANCZOS)
                fr.paste(cb, (CX - cb.width // 2, SAFE_BOTTOM - cb.height - 40), cb)
            return fr.convert("RGB")

    def end_card(self, tl):
        with canvas(W, H):
            fr = Image.new("RGBA", (W, H), KIRSCHE + (255,))
            rail = Image.new("RGBA", (W, cd.RAIL_H + 40), (0, 0, 0, 0))
            cd.rail(rail, CREME, "stadtwuppertal", KIRSCHE, y0=0)
            fr.paste(rail, (0, RY0), rail)
            ry = RY0 + cd.RAIL_H
            probe, _, _ = headline_c(["nächster", "halt:"], 230, CREME, CREME)
            lay, piv, last = headline_c(["nächster", "halt:"], 230, CREME, CREME,
                                        max(0, int(MID - probe.height / 2 - SAFE_TOP - 60)))
            sw = cd.schild_block("@stadtwuppertal", 104).width
            x = CX - max(lay.width - 40, last[0] + sw / 2) / 2
            place(fr, lay, piv, x, ry, swing(tl + 0.35, amp=2.5))
            hanging_schild(fr, x + last[0], ry + last[1] - 4, "@stadtwuppertal", 104, tl + 0.1, drop=False)
            return fr.convert("RGB")

    def cover_frame(self):
        """Titelbild fürs Reel: der Hook, wenn er steht."""
        return self.frame(2.6)

    def render(self, out_path: str, music: str | None = None):
        tmp = out_path + ".part.mp4"
        if music:
            audio = ["-stream_loop", "-1", "-i", music, "-t", f"{self.total:.2f}",
                     "-af", f"afade=t=in:d=0.8,afade=t=out:st={max(self.total - 1.8, 0):.2f}:d=1.8,volume=0.85"]
        else:
            audio = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        p = subprocess.Popen([self.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *audio, "-shortest",
                              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                              "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
        for n in range(round(self.total * FPS)):
            p.stdin.write(cd.grain(self.frame(n / FPS), 0.012).tobytes())
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg fehlgeschlagen")
        os.replace(tmp, out_path)
        return out_path


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def render_reel(pkg, photos, out_path=None, music=None):
    out_path = out_path or tempfile.mktemp(suffix=".mp4")
    r = Reel(pkg, photos, ffmpeg_exe())
    r.render(out_path, music)
    return out_path, r.cover_frame(), r.total
