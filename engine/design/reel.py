"""Reel aus einem Post-Paket: feste Schiene, Fotos mit Dauer-Zoom, Satz-Kästen hängen als Zug
am Träger, Pausen vor den Pointen, harter Schnitt auf die Endkarte. Kein Ton (Musik später).

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
    words = text.split(" ")
    n, cur = 1, ""
    for w_ in words:
        t_ = (cur + " " + w_).strip()
        if cur and cd.tracked_len(t_, f, track) > maxw:
            n, cur = n + 1, w_
        else:
            cur = t_
    if n == 1:
        return [text]
    best, best_score = None, 1e9
    for cuts in itertools.combinations(range(1, len(words)), n - 1):
        parts = [" ".join(words[a:b]) for a, b in zip((0,) + cuts, cuts + (len(words),))]
        ws = [cd.tracked_len(p, f, track) for p in parts]
        if max(ws) > maxw:
            continue
        if max(ws) - min(ws) < best_score:
            best, best_score = parts, max(ws) - min(ws)
    return best or [text]


def headline_c(lines, size, color, hcolor):
    f = cd.brico(size)
    blocks = [cd.Block([ln], f, color) for ln in lines]
    lead = int(size * 0.86)
    wmax = max(b.im.width for b in blocks)
    lay = Image.new("RGBA", (wmax + 80, cd.HANG + lead * (len(lines) - 1) + blocks[-1].im.height + 60), (0, 0, 0, 0))
    xs = [40 + (wmax - b.im.width) // 2 for b in blocks]
    b0 = blocks[0]
    lt = b0.letters(0) or [0]
    d = ImageDraw.Draw(lay)
    for ci in (lt[0], lt[-1]):
        ax, ay = b0.anchor(0, ci, "top")
        d.line((xs[0] + ax, 0, xs[0] + ax, cd.HANG + ay + int(size * 0.12)), fill=hcolor, width=cd.STROKE)
        cd.bracket(lay, xs[0] + ax, 0, hcolor)
    for i, b in enumerate(blocks):
        lay.paste(b.im, (xs[i], cd.HANG + lead * i), b.im)
    bl = blocks[-1]
    last = bl.anchor(*cd.last_char(bl), "bottom")
    return lay, (lay.width / 2, 0), (xs[-1] + last[0], cd.HANG + lead * (len(lines) - 1) + last[1])


STYLE = {"head": (112, (800, 75, 96), CREME, INK, (24, 34), 0.92),
         "line": (96, (700, 90, 48), INK, CREME, (24, 34), 1.14),
         "pop": (128, (800, 75, 96), INK, ZITRONE, (26, 38), 0.92)}


def make_box(kind, text):
    size, ax, fg, bgc, pad, lead = STYLE[kind]
    f = cd.brico(size, *ax)
    track = 0.0 if kind == "line" else cd.track_for(size)
    lines = [ln for part in text.split("\n") for ln in bwrap(part, f, MAXW - 2 * pad[1], track)]
    bs = [cd.Block([ln], f, fg, track=0.0 if kind == "line" else None) for ln in lines]
    step = int(size * lead)
    wmax = max(b.im.width for b in bs)
    hh = step * (len(bs) - 1) + bs[-1].im.height
    box = Image.new("RGBA", (wmax + 2 * pad[1], hh + 2 * pad[0]), bgc + (255,))
    for i, b in enumerate(bs):
        box.paste(b.im, (pad[1] + (wmax - b.im.width) // 2, pad[0] + step * i), b.im)
    return box


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
            self.head, self.head_piv, self.head_last = headline_c(hook, self._hook_size(hook), CREME, CREME)
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
        for i, tr in enumerate(spec[:5]):
            items = []
            if tr.get("head"):
                items.append(("head", tr["head"].lower(), ""))
            items += [("line", l, "") for l in tr.get("lines", []) if l][:3]
            if tr.get("gag"):
                last = i == len(spec[:5]) - 1
                items.append(("pop" if last else "line", tr["gag"], "punch" if last else "beat"))
            if not items:
                continue
            boxes = [make_box(k, s) for k, s, _ in items]
            # nicht höher als bis kurz über die Caption-Zone
            while len(boxes) > 2 and RY0 + cd.RAIL_H + cd.HANG + sum(b.height + COUPLE for b in boxes) > 1620:
                drop_i = 1 if items[0][0] == "head" else 0
                items.pop(drop_i + 1 if len(items) > drop_i + 2 else drop_i)
                boxes = [make_box(k, s) for k, s, _ in items]
            out.append({"items": items, "boxes": boxes,
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
        wmax = max(b.width for b in boxes) + 140
        lay = Image.new("RGBA", (wmax, cd.HANG + sum(b.height + COUPLE for b in boxes) + 120), (0, 0, 0, 0))
        cx = wmax / 2
        d = ImageDraw.Draw(lay)
        tops, y = [], cd.HANG
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
            d.line((gx, 0, gx, cd.HANG + 10), fill=CREME, width=cd.STROKE)
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
                if tr["t_in"] <= t < tr["t_out"] + 0.6:
                    xc, ang = self.train_pos(tr, t)
                    lay, piv = self.train_layer(tr, t)
                    place(fr, lay, piv, xc - piv[0], ry, ang)
            return fr.convert("RGB")

    def end_card(self, tl):
        with canvas(W, H):
            fr = Image.new("RGBA", (W, H), KIRSCHE + (255,))
            rail = Image.new("RGBA", (W, cd.RAIL_H + 40), (0, 0, 0, 0))
            cd.rail(rail, CREME, "stadtwuppertal", KIRSCHE, y0=0)
            fr.paste(rail, (0, RY0), rail)
            ry = RY0 + cd.RAIL_H
            lay, piv, last = headline_c(["nächster", "halt:"], 230, CREME, CREME)
            sw = cd.schild_block("@stadtwuppertal", 104).width
            x = CX - max(lay.width - 40, last[0] + sw / 2) / 2
            place(fr, lay, piv, x, ry, swing(tl + 0.35, amp=2.5))
            hanging_schild(fr, x + last[0], ry + last[1] - 4, "@stadtwuppertal", 104, tl + 0.1, drop=False)
            return fr.convert("RGB")

    def cover_frame(self):
        """Titelbild fürs Reel: der Hook, wenn er steht."""
        return self.frame(2.6)

    def render(self, out_path: str):
        tmp = out_path + ".part.mp4"
        p = subprocess.Popen([self.ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i",
                              "anullsrc=channel_layout=stereo:sample_rate=44100", "-shortest",
                              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                              "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
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


def render_reel(pkg, photos, out_path=None):
    out_path = out_path or tempfile.mktemp(suffix=".mp4")
    r = Reel(pkg, photos, ffmpeg_exe())
    r.render(out_path)
    return out_path, r.cover_frame(), r.total
