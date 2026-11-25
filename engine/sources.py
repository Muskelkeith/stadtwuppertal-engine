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
def _get(http, url, timeout=30):
    """Erst ehrlich als Engine, bei 403 wie ein normaler Browser."""
    r = http.get(url, headers=UA, timeout=timeout)
    if getattr(r, "status_code", 200) == 403:
        r = http.get(url, headers=UA_BROWSER, timeout=timeout)
    return r


# manche Seiten (z. B. wuppertal.de) sperren alles, was nicht wie ein Browser aussieht
UA_BROWSER = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                            "Version/17.5 Safari/605.1.15", "Accept-Language": "de-DE,de;q=0.9"}
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
    r = _get(http, homepage, 30)
    r.raise_for_status()
    p = _FeedLinkParser()
    p.feed(r.text)
    return [urljoin(homepage, f) for f in p.feeds]


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.cur, self.depth, self.skip = [], [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "aside", "form"):
            self.skip += 1
        if tag == "p":
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside", "form") and self.skip:
            self.skip -= 1
        if tag == "p" and self.depth:
            self.depth -= 1
            t = " ".join("".join(self.cur).split())
            if len(t) > 50:
                self.out.append(t)
            self.cur = []

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.cur.append(data)


def article_photo(html: str, medium: str) -> tuple[str | None, str | None]:
    """Aufmacherbild eines Artikels (og:image) und wer es gemacht hat (Bildunterschrift „Foto: …“/„©“).
    Agenturbilder (dpa, Getty, imago …) bleiben draußen. Ohne Fotografen gilt das Medium als Credit."""
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
    if not m:
        return None, None
    text = re.sub(r"<[^>]+>", " ", html)
    c = re.search(r"(?:Foto|Fotos|Bild|Bildquelle|Credit)\s*:\s*([^\n|]{2,80})|©\s*([^\n|]{2,80})", text)
    who = " ".join((c.group(1) or c.group(2)).split())[:70] if c else ""
    if AGENTUR.search(who) or AGENTUR.search(m.group(1)):
        return None, "AGENTUR"
    who = re.split(r"\s{2,}|\.\s", who)[0].strip(" ,;") if who else ""
    return m.group(1), f"foto: {who} / {medium}" if who and medium.lower() not in who.lower() else f"foto: {who or medium}"


def fetch_article(url: str, http=requests, chars: int = 5000) -> str:
    """Der eigentliche Artikeltext (Absätze), damit Posts aus dem vollen Stoff entstehen statt aus dem Teaser."""
    try:
        r = _get(http, url, 25)
        r.raise_for_status()
        p = _Paragraphs()
        p.feed(r.text)
        fetch_article.last_html = r.text
        return "\n".join(p.out)[:chars]
    except Exception:      # noqa: BLE001
        return ""


def fetch_rss(src: dict, cutoff: datetime, http=requests) -> list[dict]:
    urls = [src["url"]] if src.get("url") else discover_feeds(src["homepage"], http)
    items = []
    for url in urls[: src.get("max_feeds", 3)]:
        r = _get(http, url, 30)
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
                          "image_ok": (_image_credit(src) or f"foto: {src['name']}") if img else None})
    return items


# Medien-Accounts: deren Fotos nie automatisch übernehmen (Redaktionsfotos, Agenturbilder)
MEDIEN = {"talzeit.wuppertal", "wuppertal.aktuell", "radiowuppertal", "wuppertalerrundschau", "wz_wuppertal",
          "wznewsline", "wdr", "wdrlokalzeit", "lokalzeitbergischesland", "bergischeblaulichtnews", "wuppertaltotal",
          "wuppertal_live", "wuppertallive", "rponline", "bild", "express"}


AGENTUR = re.compile(r"\bdpa\b|reuters|\bAP\b|associated press|getty|imago|picture.?alliance|\bAFP\b|shutterstock|"
                     r"istock|adobe ?stock|depositphotos|123rf|alamy|epd-bild|\bKNA\b|\bddp\b|action press", re.I)


def photo_credit(handle: str, src: dict | None = None) -> str | None:
    """Fotos von Instagram-Accounts (auch Medien) dürfen mit @-Nennung übernommen werden."""
    if src is not None and _image_credit(src):
        return _image_credit(src)
    h = (handle or "").lower().lstrip("@")
    return f"foto: @{h}" if h else None


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
                      "image_ok": photo_credit(src["handle"], src) if img else None, "credits": credit_handles(cap),
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


def fetch_autobahn(src: dict, http=requests) -> list[dict]:
    """Sperrungen und Baustellen der Autobahn GmbH (offene Schnittstelle), nur was Wuppertal betrifft und bald gilt."""
    out = []
    now = datetime.now(timezone.utc)
    for road in src.get("roads", ["A46", "A1"]):
        for kind in ("closure", "roadworks"):
            r = http.get(f"https://verkehr.autobahn.de/o/autobahn/{road}/services/{kind}", headers=UA, timeout=30)
            r.raise_for_status()
            for c in r.json().get(kind, []):
                text = " ".join([c.get("title", ""), c.get("subtitle", "")] + (c.get("description") or []))
                if "wuppertal" not in text.lower():
                    continue
                if kind == "roadworks" and "voll" not in text.lower() and "gesperrt" not in text.lower():
                    continue
                start = c.get("startTimestamp")
                try:
                    when = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
                except ValueError:
                    when = None
                if when and when > now + timedelta(days=4):
                    continue        # erst kurz vorher melden
                out.append({"id": f"autobahn:{c.get('identifier')}", "source": "Autobahn GmbH", "kind": "verkehr",
                            "title": f"{road}: {c.get('title', '')} {c.get('subtitle', '')}".strip(),
                            "summary": " ".join(c.get("description") or [])[:1200],
                            "link": "https://www.autobahn.de/", "published": (when or now).isoformat()})
    return out


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
        end = datetime.fromtimestamp(w["end"] / 1000, timezone.utc) if w.get("end") else None
        out.append({"id": f"dwd:{w.get('event')}:{w.get('start')}", "source": "Deutscher Wetterdienst",
                    "gilt_bis": end.isoformat() if end else None,
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
            now: datetime | None = None, paused: set | None = None) -> tuple[list[dict], list[str]]:
    """Sammelt alle Quellen. Gibt (items, fehlerliste) zurück; eine kaputte Quelle stoppt nichts."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg_news.get("lookback_hours", 24))
    items, errors = [], []
    for src in sources:
        if paused and src.get("name") in paused:
            continue
        try:
            cut = now - timedelta(hours=src["lookback_hours"]) if src.get("lookback_hours") else cutoff
            if src["type"] == "rss":
                got = fetch_rss(src, cut, http)
            elif src["type"] == "instagram":
                if graph is None:
                    continue
                got = fetch_instagram(src, cut, graph)
            elif src["type"] == "autobahn":
                got = fetch_autobahn(src, http)
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
