"""Freie Fotos von Wikimedia Commons: nur Lizenzen, die Bearbeitung und Nutzung erlauben
(CC0, Public Domain, CC BY, CC BY-SA). Urheber + Lizenz kommen automatisch in die Caption."""
from __future__ import annotations

import io
import re

import requests
from PIL import Image

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "stadtwuppertal-engine/3 (https://instagram.com/stadtwuppertal)"}
OK = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? [0-9.]+( de)?)", re.I)


def _clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


PD = re.compile(r"^(public domain|pd|cc0)", re.I)
HIST_QUERIES = ["Elberfeld 1900", "Barmen 1900", "Elberfeld Neumarkt historisch", "Barmen Werth historisch",
                "Wuppertaler Schwebebahn 1903", "Elberfeld Postkarte", "Barmen Postkarte", "Vohwinkel historisch",
                "Elberfeld Wall historisch", "Ronsdorf historisch", "Cronenberg historisch", "Beyenburg historisch",
                "Wuppertal 1930", "Elberfeld Bahnhof historisch", "Barmen Rathaus historisch", "Ölberg Elberfeld alt",
                "Langerfeld historisch", "Elberfeld Stadthalle historisch", "Wuppertal Zoo historisch",
                "Nordbahn Wuppertal historisch"]


def search(query: str, n=6, http=requests, pd_only=False) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 20, "prop": "imageinfo",
              "iiprop": "url|extmetadata|size", "iiurlwidth": 1600}
    r = http.get(API, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for p in (r.json().get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = _clean(meta.get("LicenseShortName", {}).get("value", ""))
        if not (PD if pd_only else OK).match(lic) or ii.get("width", 0) < (700 if pd_only else 1000):
            continue
        artist = _clean(meta.get("Artist", {}).get("value", "")) or "Unbekannt"
        out.append({"url": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
                    "artist": artist[:60], "license": lic, "title": p.get("title", "").replace("File:", ""),
                    "description": _clean(meta.get("ImageDescription", {}).get("value", ""))[:600],
                    "date": _clean(meta.get("DateTimeOriginal", {}).get("value", ""))[:40]})
        if len(out) >= n:
            break
    return out


def fetch(hit: dict, http=requests) -> Image.Image:
    r = http.get(hit["url"], headers=UA, timeout=60)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def credit(hit: dict) -> str:
    return f"foto: {hit['artist']} / Wikimedia Commons, {hit['license']}"


OPENVERSE = "https://api.openverse.org/v1/images/"


def openverse(query: str, n=8, http=requests) -> list[dict]:
    """Freie Fotos (Creative Commons, Bearbeitung erlaubt) aus Flickr, Wikimedia & Co. über Openverse – ohne Schlüssel."""
    r = http.get(OPENVERSE, params={"q": query, "license_type": "commercial,modification", "page_size": 20,
                                    "mature": "false"}, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for x in r.json().get("results", []):
        if (x.get("width") or 0) < 1000 or not x.get("url"):
            continue
        lic = (x.get("license") or "").lower()
        lic_txt = "CC0" if lic in ("cc0", "pdm") else f"CC {lic.upper()} {x.get('license_version') or ''}".strip()
        out.append({"url": x["url"], "page": x.get("foreign_landing_url") or x["url"],
                    "artist": (x.get("creator") or "Unbekannt")[:60], "license": lic_txt,
                    "source": (x.get("source") or x.get("provider") or "Openverse").capitalize(),
                    "title": x.get("title") or ""})
        if len(out) >= n:
            break
    return out


ORTE = re.compile(r"wuppertal|elberfeld|barmen|vohwinkel|cronenberg|ronsdorf|beyenburg|langerfeld|oberbarmen|"
                  r"nrw|bergisch|deutschland|germany", re.I)


def passt(hit: dict, query: str) -> bool:
    """Zeigt das Foto wirklich das Motiv? Mindestens ein Motiv-Wort (ohne Ortsnamen) muss in Titel/Beschreibung stehen –
    sonst liefert „Fahrräder Wuppertal“ irgendein Straßenfoto aus Wuppertal."""
    words = [w.lower()[:5] for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", ORTE.sub(" ", query))]
    if not words:
        return True
    text = hit.get('title', '').lower()        # Titel, nicht Beschreibung: sonst passt jedes Foto, das das Wort nebenbei erwähnt
    return any(w in text for w in words)


def candidates(query, used: set, http=requests, n=4) -> list[dict]:
    """Bis zu n passende Kandidaten aus Commons und Openverse (Titel enthält das Motiv)."""
    queries = [q for q in ([query] if isinstance(query, str) else list(query or [])) if q]
    out, seen = [], set(used)
    for src in (search, openverse):
        for q in queries:
            try:
                for hit in src(q, http=http):
                    if hit["page"] in seen or not passt(hit, q):
                        continue
                    seen.add(hit["page"])
                    hit["credit"] = credit(hit) if src is search else \
                        f"foto: {hit['artist']} / {hit['source']}, {hit['license']}"
                    out.append(hit)
                    if len(out) >= n:
                        return out
            except Exception:
                pass
    return out


def find_photo(query, used: set, http=requests):
    """Erstes passendes, noch nicht benutztes Foto: (Image, Credit, Seite) oder (None, None, None).
    `query` darf ein Begriff oder eine Liste sein (erst konkret mit Wuppertal, dann allgemein).
    Erst Wikimedia Commons, dann Openverse (Flickr & Co., nur Lizenzen, die Bearbeitung erlauben)."""
    queries = [q for q in ([query] if isinstance(query, str) else list(query or [])) if q]
    for q in queries:
        try:
            for hit in search(q, http=http):
                if hit["page"] not in used and passt(hit, q):
                    return fetch(hit, http), credit(hit), hit["page"]
        except Exception:
            pass
    for q in queries:
        try:
            for hit in openverse(q, http=http):
                if hit["page"] not in used and passt(hit, q):
                    return fetch(hit, http), f"foto: {hit['artist']} / {hit['source']}, {hit['license']}", hit["page"]
        except Exception:
            pass
    return None, None, None


def historical(used: set, http=requests, rnd=None):
    """Ein historisches Wuppertal-Foto in Public Domain, das noch nicht dran war."""
    import random
    qs = HIST_QUERIES[:]
    (rnd or random).shuffle(qs)
    for q in qs[:6]:
        try:
            for hit in search(q, n=10, http=http, pd_only=True):
                if hit["page"] not in used:
                    return hit
        except Exception:
            continue
    return None
