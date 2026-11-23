"""Ideenpool: zeitlose, starke Wuppertal-Themen aus Recherche – belegt mit Wikipedia, geprüft vor dem Schreiben.

Alle 2 Tage (oder wenn der Pool leer wird) schlägt Claude Themen vor (Kurioses, Nischenwissen, Damals, Menschen &
Orte). Zu jedem Vorschlag holt die Engine den passenden Wikipedia-Artikel als Faktengrundlage. Nur was belegt ist
und die harte Themenprüfung besteht, kommt in den Pool."""
from __future__ import annotations

import requests

UA = {"User-Agent": "stadtwuppertal-engine/1.0 (Lokaljournalismus-Bot; github.com/Muskelkeith)"}
API = "https://de.wikipedia.org/w/api.php"


def wiki(title: str, chars: int = 8000) -> dict | None:
    """Artikeltext (Klartext) zu einem Wikipedia-Titel, oder None, wenn es den Artikel nicht gibt."""
    try:
        r = requests.get(API, headers=UA, timeout=20, params={
            "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "format": "json",
            "titles": title, "exchars": chars})
        pages = r.json().get("query", {}).get("pages", {})
        for p in pages.values():
            if p.get("missing") is not None or not p.get("extract"):
                return None
            return {"titel": p["title"], "text": p["extract"],
                    "url": f"https://de.wikipedia.org/wiki/{p['title'].replace(' ', '_')}"}
    except Exception:      # noqa: BLE001
        return None
    return None


def refill(brain, st, now_ts, vorbild_note: str = "", heute: str = "") -> int:
    """Pool auffüllen. Gibt die Zahl der neu aufgenommenen Themen zurück."""
    pool = st.setdefault("pool", [])
    used = set(st.setdefault("pool_used", []))
    ideas = brain.pool_ideas({"schon_gemacht": list(used)[-60:] + [p["titel"] for p in pool],
                              "vorbild": vorbild_note[:1500], "heute": heute})
    cands = []
    for i, it in enumerate(ideas.get("themen") or []):
        src = None
        for t in (it.get("wiki") or [])[:2]:      # beide Artikel lesen: oft steht die Auflösung erst im zweiten
            w = wiki(t)
            if w and not src:
                src = w
            elif w:
                src = {**src, "text": src["text"] + "\n\n" + w["titel"] + ":\n" + w["text"][:5000]}
        if it.get("rubrik") == "kreativ":       # Community-Frage: braucht keine Fakten
            src = {"titel": "", "text": "", "url": ""}
        if not src:
            continue
        cands.append({"id": f"p{int(now_ts)}-{i}", "titel": it.get("titel", ""), "rubrik": it.get("rubrik", "fact"),
                      "dreh": it.get("dreh", ""), "datum": it.get("datum", ""), "quelle": src})
    if not cands:
        return 0
    verdict = {v.get("id"): v for v in (brain.topic_gate([{"id": c["id"], "titel": c["titel"], "rubrik": c["rubrik"],
                                                            "dreh": c["dreh"], "fakten": c["quelle"]["text"][:600]}
                                                           for c in cands]).get("urteile") or [])}
    added = 0
    for c in cands:
        v = verdict.get(c["id"]) or {}
        if (v.get("score") or 0) >= 7:
            c.update(score=v["score"], dreh=v.get("dreh") or c["dreh"], ts=now_ts)
            pool.append(c)
            added += 1
    st["pool"] = sorted(pool, key=lambda p: -p.get("score", 0))[:40]
    return added


def take(st, rubriken, today_mmdd: str = "") -> dict | None:
    """Bestes Pool-Thema für eine der Rubriken nehmen (und als benutzt markieren). Ein Jahrestag von heute geht vor."""
    pool = st.get("pool", [])
    for p in pool:
        if today_mmdd and p.get("rubrik") == "jahrestag" and p.get("datum") == today_mmdd:
            pool.remove(p)
            st.setdefault("pool_used", []).append(p["titel"])
            return p
    for p in pool:
        if p["rubrik"] == "jahrestag":
            continue          # Jahrestage nur an ihrem Tag
        if p["rubrik"] in rubriken:
            pool.remove(p)
            st.setdefault("pool_used", []).append(p["titel"])
            st["pool_used"] = st["pool_used"][-200:]
            return p
    return None
