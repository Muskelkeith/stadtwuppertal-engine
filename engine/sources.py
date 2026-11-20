"""Quellen-Scanner: Lokalmedien (RSS mit Auto-Erkennung), Instagram-Accounts (Business Discovery),
Presseportal und DWD-Warnungen. Alles wird auf ein gemeinsames Format gebracht:

    {"id", "source", "kind", "title", "summary", "link", "published"}
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (stadtwuppertal-engine; +https://instagram.com/stadtwuppertal)"}
DWD_URL = "https://www.dwd.de/DWD/warnungen/warnapp/json/warnings.json"


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ── RSS-Auto-Erkennung ──────────────────────────────────────
class _FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and a.get("rel", "").lower() == "alternate" and \
                a.get("type", "") in ("application/rss+xml", "application/atom+xml") and a.get("href"):
            self.feeds.append(a["href"])


def discover_feeds(homepage: str, http=requests) -> list[str]:
    """Findet RSS/Atom-Feeds, die eine Seite im HTML-Kopf ankündigt."""
    r = http.get(homepage, headers=UA, timeout=30)
    r.raise_for_status()
    p = _FeedLinkParser()
    p.feed(r.text)
    return [urljoin(homepage, f) for f in p.feeds]


def fetch_rss(src: dict, cutoff: datetime, http=requests) -> list[dict]:
    urls = [src["url"]] if src.get("url") else discover_feeds(src["homepage"], http)
    items = []
    for url in urls[: src.get("max_feeds", 3)]:
        r = http.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        must = src.get("title_must_contain")
        for e in parsed.entries:
            title = _clean(e.get("title", ""))
            if must and must not in title:
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = datetime.fromtimestamp(calendar.timegm(ts), timezone.utc) if ts else None
            if when and when < cutoff:
                continue
            link = e.get("link", "")
            img = None
            for enc in (e.get("enclosures") or []) + (e.get("media_content") or []):
                if str(enc.get("type", "image")).startswith("image") and (enc.get("href") or enc.get("url")):
                    img = enc.get("href") or enc.get("url")
                    break
            items.append({"id": link or _id(src["name"], title), "source": src["name"], "kind": "rss",
                          "title": title, "summary": _clean(e.get("summary", ""))[:1500], "link": link,
                          "published": when.isoformat() if when else None, "image": img,
                          "image_ok": _image_credit(src) if img else None})
    return items


def fetch_instagram(src: dict, cutoff: datetime, graph) -> list[dict]:
    """Liest öffentliche Beiträge eines Business-/Creator-Accounts über die offizielle Business Discovery API."""
    data = graph.business_discovery(src["handle"], limit=src.get("limit", 15))
    items = []
    for m in data.get("media", {}).get("data", []):
        ts = m.get("timestamp")
        when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") if ts else None
        if when and when < cutoff:
            continue
        cap = (m.get("caption") or "").strip()
        img = m.get("media_url") if m.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM") else None
        items.append({"id": f"ig:{m['id']}", "source": src["name"], "kind": "instagram",
                      "title": cap.split("\n")[0][:160], "summary": cap[:1500], "link": m.get("permalink", ""),
                      "published": when.isoformat() if when else None, "handle": src["handle"],
                      "likes": m.get("like_count"), "comments": m.get("comments_count"), "image": img,
                      "image_ok": _image_credit(src) if img else None, "credits": credit_handles(cap),
                      "ask_source": bool(src.get("anfragen"))})
    return items


CREDIT_RE = re.compile(r"(?:bildquelle|bilder?|fotos?|foto credit|credit|photo|📸|📷)\s*[:\-–]?\s*@([A-Za-z0-9._]{2,30})", re.I)


def credit_handles(text: str) -> list[str]:
    """Wer hat das Foto gemacht? Liest „Bildquelle: @name“, „Foto: @name“, „📸 @name“ aus Captions."""
    return list(dict.fromkeys(h.rstrip(".") for h in CREDIT_RE.findall(text or "")))


def _image_credit(src: dict) -> str | None:
    """Credit-Zeile, wenn die Quelle ihre Bilder freigegeben hat – sonst None (Bild wird nicht benutzt).
    bilder: honorarfrei → Pressebilder (Polizei, Feuerwehr, Stadt) · bilder: freigabe → Fotograf hat zugestimmt"""
    mode = src.get("bilder")
    if mode == "honorarfrei":
        return f"foto: {src.get('credit', src['name'])}"
    if mode == "freigabe" and src.get("handle"):
        return f"bildquelle: @{src['handle']}"
    return None


def fetch_dwd(cfg: dict, http=requests) -> list[dict]:
    d = cfg.get("dwd_warnings", {})
    if not d.get("enabled"):
        return []
    r = http.get(DWD_URL, headers=UA, timeout=30)
    r.raise_for_status()
    raw = r.text
    data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    out = []
    for w in data.get("warnings", {}).get(str(d["warncell_id"]), []):
        if int(w.get("level", 0)) < d.get("min_level", 2):
            continue
        start = datetime.fromtimestamp(w["start"] / 1000, timezone.utc) if w.get("start") else None
        out.append({"id": f"dwd:{w.get('event')}:{w.get('start')}", "source": "Deutscher Wetterdienst",
                    "kind": "warning", "title": w.get("headline", "Wetterwarnung"),
                    "summary": f"{w.get('description', '')} {w.get('instruction', '')}".strip(),
                    "link": "https://www.dwd.de/warnungen", "published": start.isoformat() if start else None})
    return out


def is_relevant(item: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = f"{item['title']} {item['summary']}".lower()
    return any(k.lower() in text for k in keywords)


def collect(sources: list[dict], cfg_news: dict, graph=None, http=requests,
            now: datetime | None = None) -> tuple[list[dict], list[str]]:
    """Sammelt alle Quellen. Gibt (items, fehlerliste) zurück; eine kaputte Quelle stoppt nichts."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg_news.get("lookback_hours", 24))
    items, errors = [], []
    for src in sources:
        try:
            cut = now - timedelta(hours=src["lookback_hours"]) if src.get("lookback_hours") else cutoff
            if src["type"] == "rss":
                got = fetch_rss(src, cut, http)
            elif src["type"] == "instagram":
                if graph is None:
                    continue
                got = fetch_instagram(src, cut, graph)
            else:
                continue
            if src.get("filter_wuppertal", True):
                got = [i for i in got if is_relevant(i, cfg_news.get("relevance_keywords", []))]
            items += got
        except Exception as e:
            errors.append(f"{src.get('name')}: {e}")
    try:
        items = fetch_dwd(cfg_news, http) + items
    except Exception as e:
        errors.append(f"DWD: {e}")
    seen, unique = set(), []
    for i in items:
        if i["id"] not in seen:
            seen.add(i["id"])
            unique.append(i)
    return unique, errors


def username_from_permalink(permalink: str, http=requests) -> str | None:
    """Meta liefert bei Hashtag-Treffern keinen Namen. Die öffentliche Post-Seite nennt ihn im Titel
    („name on Instagram: …“). Ein Abruf pro Kandidat, nur für die paar besten Fotos am Tag."""
    if not permalink:
        return None
    try:
        r = http.get(permalink, headers=UA, timeout=20)
        m = re.search(r'<meta property="og:title" content="[^"]*?\(@([A-Za-z0-9._]{2,30})\)', r.text) or \
            re.search(r'"username":"([A-Za-z0-9._]{2,30})"', r.text)
        return m.group(1) if m else None
    except Exception:
        return None
