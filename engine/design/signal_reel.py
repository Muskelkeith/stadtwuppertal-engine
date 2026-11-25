"""Orange Day: Reel und Fotokacheln aus einem echten Video der Geste.

Video: „Signal for Help (demonstrative example)“ von GemoWiki, Wikimedia Commons, CC BY 4.0
https://commons.wikimedia.org/wiki/File:Signal_for_Help(_demonstrative_example_).ogg
Wird lokal gerendert, die Engine postet nur das fertige Ergebnis. Optik: Creme-Wand, Brombeer-Schatten, Kirsch-Schrift –
durchgehend, die Infos fliegen als Züge am Träger rein wie in den anderen Reels.

Aufruf: python -m engine.design.signal_reel <video.ogg> <ausgabeordner> [--stills]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import cd, render
from . import reel as R

W, H, FPS = 1080, 1920, 30
C = cd.C
CREDIT = "video: GemoWiki / Wikimedia Commons, CC BY 4.0"
DARK, LIGHT, INK = C["brombeer"], C["creme"], C["kirsche"]
FILTER = "hqdn3d=1.2:1.2:3:3"          # Kompressionsrauschen der Vorlage glätten


# ── Vorlage laden ────────────────────────────────────────────────────────
def _decode(path, extra_vf="", ss=None, t=None):
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    if t is not None:
        cmd += ["-t", str(t)]
    vf = f"{FILTER}{',' + extra_vf if extra_vf else ''},scale={W}:{H}:flags=lanczos"
    raw = subprocess.run(cmd + ["-i", path, "-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    n = len(raw) // (W * H)
    return [np.frombuffer(raw[i * W * H:(i + 1) * W * H], dtype=np.uint8).reshape(H, W) for i in range(n)]


class Source:
    """Echtzeit-Frames (30 fps) plus eine weich interpolierte Zeitlupe (90 fps) für die Schritte."""
    SLOW_FROM, SLOW_LEN = 2.8, 2.3

    def __init__(self, path):
        self.real = _decode(path)
        self.slow = _decode(path, "minterpolate=fps=90:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                            ss=self.SLOW_FROM, t=self.SLOW_LEN)

    def at(self, s):
        """Frame zur Quellzeit s (Sekunden). Im Zeitlupenbereich aus der 90-fps-Fassung."""
        if self.SLOW_FROM <= s < self.SLOW_FROM + self.SLOW_LEN - 0.02 and self.slow:
            return self.slow[min(len(self.slow) - 1, int(round((s - self.SLOW_FROM) * 90)))]
        return self.real[min(len(self.real) - 1, max(0, int(round(s * 30))))]


class Tone:
    """Fester Duoton ohne Helligkeitssprünge: Wand wird Creme, Schatten Brombeer."""

    def __init__(self, frames):
        allpx = np.concatenate([f[::8, ::8].ravel() for f in frames[::10]])
        wall = np.concatenate([f[: H // 4:8, ::8].ravel() for f in frames[::10]])
        lo, hi = np.percentile(allpx, 1), np.percentile(wall, 35)
        d, l = np.array(DARK, float), np.array(LIGHT, float)
        v = np.clip((np.arange(256) - lo) / (hi - lo), 0, 1) ** 1.35
        self.lut = (d[None] + (l - d)[None] * v[:, None]).astype(np.uint8)

    def __call__(self, gray, fade=0.0):
        rgb = self.lut[gray]
        if fade:
            rgb = (rgb * (1 - fade) + np.array(LIGHT) * fade).astype(np.uint8)
        return rgb


def _vignette(size, edge=110):
    m = Image.new("L", size, 255)
    d = ImageDraw.Draw(m)
    for k in range(edge):
        d.rectangle((k, k, size[0] - 1 - k, size[1] - 1 - k), outline=int(255 * k / edge))
    return m


def place_video(rgb, w, h, zoom, cx, cy, src_center=(0.50, 0.42)):
    """Videobild so skalieren und verschieben, dass die Hand bei (cx, cy) steht; Ränder laufen weich in Creme aus."""
    v = Image.fromarray(rgb).resize((int(W * zoom), int(H * zoom)), Image.LANCZOS)
    img = Image.new("RGB", (w, h), LIGHT)
    img.paste(v, (int(cx - v.width * src_center[0]), int(cy - v.height * src_center[1])), _vignette(v.size))
    return img


# ── Reel ─────────────────────────────────────────────────────────────────
def _style():
    """Hausfarben dieses Reels: Kästen Kirsche/Brombeer auf Creme, Aufhänger in Kirsche."""
    R.STYLE.update({"head": (118, (800, 75, 96), LIGHT, INK, (24, 36), 0.92),
                    "line": (80, (700, 90, 48), LIGHT, DARK, (26, 38), 1.14),
                    "pop": (120, (800, 75, 96), DARK, C["zitrone"], (28, 40), 0.92),
                    "cap": (56, (700, 90, 48), LIGHT, DARK, (18, 28), 1.12)})
    R.CREME = INK
    # knapper getaktet als die Erklär-Reels: kurze Sätze, schneller nachgelegt
    R.read_time = lambda kind, text: 0.7 if kind == "head" else 0.35 + 0.2 * len(text.split())


PKG = {
    "rubric": "news",
    "hook": ["dieses zeichen", "heißt: hilfe."],
    "schild": "orange day",
    "reel": [
        {"head": "1  daumen in die hand."},
        {"head": "2  finger drüber."},
        {"head": "siehst du das zeichen?", "lines": ["ruhig bleiben. bei gefahr: 110."]},
        {"head": "hilfetelefon: 116 016", "lines": ["rund um die uhr. anonym."]},
        {"head": "hier im tal", "lines": ["frauenhaus: 0202 71 14 26"], "gag": "alle nummern im post."},
    ],
}


class SignalReel(R.Reel):
    ZOOM, CX, CY = 1.22, 540, 1060      # Hand groß, unterhalb der Überschriften

    def __init__(self, src: Source, tone: Tone):
        _style()
        super().__init__(PKG, [])
        self.src, self.tone = src, tone
        with render.canvas(W, H):
            self.rail = Image.new("RGBA", (W, cd.RAIL_H + 40), (0, 0, 0, 0))
            cd.rail(self.rail, INK, cd.LABELS["news"], LIGHT, y0=0)
            hook = PKG["hook"]
            size = self._hook_size(hook)
            self.head, self.head_piv, self.head_last = R.headline_c(hook, size, INK, INK, 0)
        sw = cd.schild_block(self.schild, 120).width
        self.hook_x = R.CX - max(self.head.width - 40, self.head_last[0] + sw / 2) / 2
        self.credit = cd.strip(CREDIT, 28, LIGHT, DARK)
        self.total = self.end_t + 3.2

    # Quellzeit je Reel-Zeit: Hook = Geste einmal ganz (endet mit offener Hand), Schritt 1 = Hand steht,
    # Schritt 2 = Zeitlupe bis zur Faust, danach läuft die Geste blass im Hintergrund weiter.
    def video_at(self, t):
        s1, s2, info = self.trains[0]["t_in"], self.trains[1]["t_in"], self.trains[2]["t_in"]
        if t < s1:
            return t / s1 * 3.0, 0.0
        if t < s2:
            return 3.0 + 0.6 * (t - s1) / (s2 - s1), 0.0
        if t < info:
            return 3.6 + 1.0 * R.eo(min((t - s2) / (info - s2) / 0.85, 1)), 0.0
        return (4.6 + (t - info)) % 6.6, min(1.0, (t - info) / 0.6) * 0.62

    def frame(self, t):
        if t >= self.end_t:
            return self.end_card(t - self.end_t)
        s, fade = self.video_at(t)
        with render.canvas(W, H):
            k = R.eo((t - 4.0) / 0.6) if t > 4.0 else 0.0     # im Hook kleiner und tiefer: Überschrift verdeckt nichts
            zoom, cy = 1.0 + (self.ZOOM - 1.0) * k, 1210 + (self.CY - 1210) * k
            fr = place_video(self.tone(self.src.at(s), fade), W, H, zoom, self.CX, cy).convert("RGBA")
            fr.paste(self.rail, (0, R.RY0), self.rail)
            ry = R.RY0 + cd.RAIL_H
            if t < self.hook_end + 0.1:
                x = self.hook_x + (W + 200) * (1 - R.eo((t - 0.15) / 0.9))
                ang = R.swing(t - 1.05)
                if t >= 3.6:
                    x = self.hook_x - (W + 600) * R.ei((t - 3.6) / 0.7)
                    ang = 2.5 * R.ei((t - 3.6) / 0.7)
                if t >= 0.15:
                    R.place(fr, self.head, self.head_piv, x, ry, ang)
                    R.hanging_schild(fr, x + self.head_last[0], ry + self.head_last[1] - 4, self.schild, 120,
                                     t - 1.35, line=INK)
            for tr in self.trains:
                if tr["t_in"] <= t < tr["t_out"] + 0.6:
                    xc, ang = self.train_pos(tr, t)
                    lay, piv = self.train_layer(tr, t)
                    R.place(fr, lay, piv, xc - piv[0], ry, ang)
            fr.paste(self.credit, (cd.M, R.SAFE_BOTTOM - self.credit.height - 10), self.credit)
            return fr.convert("RGB")

    def end_card(self, tl):
        with render.canvas(W, H):
            fr = Image.new("RGBA", (W, H), LIGHT + (255,))
            rail = Image.new("RGBA", (W, cd.RAIL_H + 40), (0, 0, 0, 0))
            cd.rail(rail, INK, "stadtwuppertal", LIGHT, y0=0)
            fr.paste(rail, (0, R.RY0), rail)
            ry = R.RY0 + cd.RAIL_H
            lines = ["speichern.", "weiterschicken."]
            sw = cd.schild_block("@stadtwuppertal", 96).width
            size = self._hook_size(lines)
            while size > 110:            # Schild am Punkt muss mit ins Bild
                probe, _, last = R.headline_c(lines, size, INK, INK)
                if max(probe.width - 40, last[0] + sw / 2) <= W - 2 * 70:
                    break
                size -= 6
            lay, piv, last = R.headline_c(lines, size, INK, INK, max(0, int(R.MID - probe.height / 2 - R.SAFE_TOP - 60)))
            x = R.CX - max(lay.width - 40, last[0] + sw / 2) / 2
            R.place(fr, lay, piv, x, ry, R.swing(tl + 0.35, amp=2.5))
            R.hanging_schild(fr, x + last[0], ry + last[1] - 4, "@stadtwuppertal", 96, tl + 0.1, drop=False, line=INK)
            return fr.convert("RGB")

    def qa_frames(self):
        ts = [2.4] + [min(tr["t_out"] - 0.3, tr["drops"][-1] + 1.2) for tr in self.trains] + [self.end_t + 1.5]
        return [(t, self.frame(t)) for t in ts]


# ── Karussell-Kacheln ────────────────────────────────────────────────────
def feed_tile(gray, tone, lines, schild=None, more=True, zoom=0.95, cx=540, cy=900):
    w, h = 1080, 1350
    img = place_video(tone(gray), w, h, zoom, cx, cy)
    with render.canvas(w, h):
        ry = cd.rail(img, INK, cd.LABELS["news"], LIGHT)
        hb, size = render._hook(img, lines, INK, ry, max_h=330, schild=schild)
        if schild:
            cd.chain(img, hb, *cd.last_char(hb[0]), schild, INK, size=max(84, min(116, int(size * 0.6))),
                     fg=C["brombeer"], bg=C["zitrone"])
        s = cd.strip(CREDIT, 26, LIGHT, DARK)
        img.paste(s, (cd.M, h - 64 - s.height), s)
        if more:
            cd.swipe_hint(img, LIGHT, plate=INK)
        return cd.grain(img, 0.012)


def feed_tiles(src, tone):
    a = feed_tile(src.at(3.2), tone, ["dieses zeichen", "heißt: hilfe."], schild="orange day",
                  zoom=0.8, cx=380, cy=1010)
    b = feed_tile(src.at(4.8), tone, ["daumen rein,", "finger drüber."], zoom=0.95, cx=560, cy=690)
    return a, b


if __name__ == "__main__":
    path, outdir = sys.argv[1], Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    src = Source(path)
    tone = Tone(src.real)
    r = SignalReel(src, tone)
    if r.problems:
        print("PROBLEME:", r.problems)
    for t, im in r.qa_frames():
        im.save(outdir / f"qa_{t:05.2f}.jpg", quality=88)
    a, b = feed_tiles(src, tone)
    a.save(outdir / "kachel_1.jpg", quality=93)
    b.save(outdir / "kachel_2.jpg", quality=93)
    if "--stills" not in sys.argv:
        r.render(str(outdir / "orange_day_reel.mp4"))
    print("dauer", round(r.total, 2))
