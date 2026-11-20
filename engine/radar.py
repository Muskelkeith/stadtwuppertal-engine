"""Radar: Was läuft gerade bei den großen Kanälen? Einmal am Tag über die offizielle Schnittstelle
(Business Discovery). Ausreißer = Posts mit mindestens doppeltem Engagement des Account-Medians.
Ergebnis fließt in die Themenwahl und in den Tagesbericht."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone


def scan(graph, handles: list[str], hours=72, factor=2.0) -> tuple[list[dict], dict, list[str]]:
    now = datetime.now(timezone.utc)
    hits, accounts, errors = [], {}, []
    for h in handles:
        try:
            d = graph.business_discovery(h, limit=25)
        except Exception as e:      # noqa: BLE001
            errors.append(f"{h}: {str(e)[:120]}")
            continue
        media = d.get("media", {}).get("data", [])
        eng = [(m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0) for m in media]
        if not eng:
            continue
        med = statistics.median(eng) or 1
        accounts[h] = {"followers": d.get("followers_count"), "median": med}
        for m, e in zip(media, eng):
            ts = m.get("timestamp")
            when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") if ts else now
            if when < now - timedelta(hours=hours) or e < factor * med:
                continue
            cap = (m.get("caption") or "").strip().replace("\n", " ")
            hits.append({"handle": h, "x": round(e / med, 1), "likes": m.get("like_count"),
                         "comments": m.get("comments_count"), "type": m.get("media_type"),
                         "text": cap[:220], "link": m.get("permalink")})
    hits.sort(key=lambda x: -x["x"])
    return hits[:15], accounts, errors
