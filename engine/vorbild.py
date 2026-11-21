"""Vorbild-Analyse (Talzeit & Co.) und Abstandsregeln, damit wir lernen statt abkupfern."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def score(m) -> int:
    return (m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0)


def fetch_all(graph, handle: str, max_posts: int = 150) -> tuple[dict, list[dict]]:
    """Holt so viele Posts wie möglich (seitenweise), plus Follower-Zahl."""
    u = handle.lstrip("@")
    media, after, info = [], None, {}
    fields = "id,caption,like_count,comments_count,timestamp,permalink,media_type"
    while len(media) < max_posts:
        page = f".after({after})" if after else ""
        q = (f"business_discovery.username({u}){{username,followers_count,media_count,"
             f"media{page}.limit(50){{{fields}}}}}")
        d = graph._req("GET", graph.ig, fields=q).get("business_discovery", {})
        info = info or {k: d.get(k) for k in ("username", "followers_count", "media_count")}
        block = d.get("media") or {}
        media += block.get("data", [])
        after = ((block.get("paging") or {}).get("cursors") or {}).get("after")
        if not after or not block.get("data"):
            break
    return info, media[:max_posts]


def _when(m):
    try:
        return datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
    except Exception:      # noqa: BLE001
        return None


def stats(media: list[dict], tz, hist: dict | None = None) -> dict:
    """Zahlen statt Bauchgefühl: Was läuft nach Format, Wochentag, Uhrzeit, Länge, Frage, Emojis – und wie schnell."""
    rows = []
    for m in media:
        cap = m.get("caption") or ""
        w = _when(m)
        first = cap.strip().split("\n")[0]
        rows.append({"s": score(m), "typ": m.get("media_type"), "wd": WEEKDAYS[w.astimezone(tz).weekday()] if w else "?",
                     "h": w.astimezone(tz).hour if w else -1, "len": len(cap), "first": len(first),
                     "frage": "?" in cap[-160:], "emoji": len(EMOJI.findall(cap)), "tags": cap.count("#")})
    if not rows:
        return {}
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0      # noqa: E731

    def by(key, fn=lambda v: v):
        g = defaultdict(list)
        for r in rows:
            g[fn(r[key])].append(r["s"])
        return {k: {"schnitt": avg(v), "n": len(v)} for k, v in sorted(g.items(), key=lambda x: -avg(x[1])) if len(v) >= 3}

    rows_sorted = sorted(rows, key=lambda r: -r["s"])
    q = max(1, len(rows) // 4)
    top, flop = rows_sorted[:q], rows_sorted[-q:]
    contrast = {k: {"top": avg([r[k] for r in top]), "flop": avg([r[k] for r in flop])}
                for k in ("len", "first", "emoji", "tags")}
    contrast["frage_am_ende_%"] = {"top": avg([100 * r["frage"] for r in top]), "flop": avg([100 * r["frage"] for r in flop])}
    out = {"posts": len(rows), "schnitt": avg([r["s"] for r in rows]), "median": rows_sorted[len(rows) // 2]["s"],
           "format": by("typ"), "wochentag": by("wd"),
           "uhrzeit": by("h", lambda h: f"{h // 3 * 3:02d}–{h // 3 * 3 + 3:02d} Uhr" if h >= 0 else "?"),
           "caption_laenge": by("len", lambda n: "kurz <300" if n < 300 else "mittel <800" if n < 800 else "lang"),
           "top_vs_flop": contrast}
    if hist:     # Dynamik: wie viel der Endwerte haben Posts nach ~6 h / ~24 h schon?
        early, day = [], []
        for pts in hist.values():
            if len(pts) < 2 or not pts[-1][1]:
                continue
            t0, final = pts[0][0], pts[-1][1]
            for t, v in pts:
                if 4 * 3600 <= t - t0 <= 8 * 3600:
                    early.append(v / final)
                if 20 * 3600 <= t - t0 <= 28 * 3600:
                    day.append(v / final)
        if early or day:
            out["dynamik"] = {"anteil_nach_6h_%": round(100 * sum(early) / len(early)) if early else None,
                              "anteil_nach_24h_%": round(100 * sum(day) / len(day)) if day else None}
    return out


def table(media: list[dict], tz) -> list[dict]:
    """Kompakte Liste aller Posts für die Themen-Analyse."""
    out = []
    for m in sorted(media, key=score, reverse=True):
        w = _when(m)
        out.append({"score": score(m), "typ": (m.get("media_type") or "")[:5],
                    "wann": w.astimezone(tz).strftime("%a %H h") if w else "", "text": (m.get("caption") or "")[:170]})
    return out


# ── Abstand halten ──────────────────────────────────────────
WORD = re.compile(r"[a-zäöüß0-9]+")


def ngrams(text: str, n: int = 4) -> set:
    w = WORD.findall((text or "").lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def overlap(ours: str, theirs: list[str], n: int = 4) -> float:
    """Anteil unserer 4-Wort-Folgen, die wörtlich auch bei ihnen stehen (0–1)."""
    a = ngrams(ours, n)
    if not a:
        return 0.0
    b = set().union(*(ngrams(t, n) for t in theirs)) if theirs else set()
    return len(a & b) / len(a)


def is_model_source(item: dict, models: list[str]) -> bool:
    name = (item.get("source") or "").lower()
    handle = (item.get("handle") or "").lower()
    return handle in models or any(name.startswith(m.split(".")[0]) for m in models)


def age_hours(item: dict, now_ts: float) -> float:
    try:
        return (now_ts - datetime.fromisoformat(item["published"]).timestamp()) / 3600
    except Exception:      # noqa: BLE001
        return 999.0


def pkg_text(pkg: dict) -> str:
    parts = [" ".join(pkg.get("hook") or []), pkg.get("caption") or ""]
    parts += [f"{s.get('head', '')} {s.get('body', '')}" for s in pkg.get("slides") or []]
    parts += [" ".join(t.get("lines") or []) + " " + (t.get("text") or "") for t in pkg.get("reel") or []]
    return " ".join(parts)


_ = timezone
