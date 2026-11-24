"""Schlanker Client für die offizielle Instagram-Schnittstelle (Graph API, Facebook-Login-Variante)."""
from __future__ import annotations

import json
import time

import requests

BASE = "https://graph.facebook.com"
IG_BASE = "https://graph.instagram.com"
MEDIA_FIELDS = "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count"


class GraphError(RuntimeError):
    pass


class GraphClient:
    def __init__(self, token: str, ig_user_id: str | None = None, version: str = "v25.0", session=None):
        self.token = token
        self.ig = ig_user_id
        # Zwei Wege bei Meta: Instagram-Login (Token beginnt mit „IG“, keine Facebook-Seite nötig)
        # oder Facebook-Login (Token „EAA…“, mit Seite – dann gehen auch Account-Beobachtung und Hashtag-Suche).
        self.ig_login = token.startswith("IG")
        self.base = f"{IG_BASE if self.ig_login else BASE}/{version}"
        self.http = session or requests.Session()

    def _req(self, method: str, path: str, **params):
        params["access_token"] = self.token
        url = f"{self.base}/{path.lstrip('/')}"
        r = self.http.request(method, url, params=params if method == "GET" else None,
                              data=params if method != "GET" else None, timeout=90)
        data = r.json() if r.content else {}
        if r.status_code >= 400 or "error" in data:
            raise GraphError(f"{method} {path}: {data.get('error', r.text)}")
        return data

    # ── Einrichtung ─────────────────────────────────────────
    def discover_ig_user(self) -> tuple[str, str]:
        """Findet den Instagram-Account hinter dem Token."""
        if self.ig_login:
            me = self._req("GET", "me", fields="user_id,username")
            self.ig = me.get("user_id") or me.get("id")
            return self.ig, me.get("username", "")
        try:
            pages = self._req("GET", "me/accounts",
                              fields="id,name,access_token,instagram_business_account{id,username}").get("data", [])
        except GraphError:
            pages = []
        if not any(p.get("instagram_business_account") for p in pages):
            # Unified Login (Systemnutzer-Token aus dem Business-Portfolio): kein Facebook-Seiten-Umweg,
            # der Token spricht direkt mit graph.instagram.com
            try:
                me = self.http.get(f"{IG_BASE}/{self.base.rsplit('/', 1)[1]}/me", timeout=60,
                                   params={"fields": "user_id,username", "access_token": self.token}).json()
            except Exception:       # noqa: BLE001
                me = {}
            if me.get("username"):
                self.ig_login = True
                self.base = f"{IG_BASE}/{self.base.rsplit('/', 1)[1]}"
                self.ig = me.get("user_id") or me.get("id")
                return self.ig, me["username"]
        if not pages:
            # Seiten-Token (läuft nie ab, wenn aus einem verlängerten Nutzer-Token abgeleitet)
            try:
                me = self._req("GET", "me", fields="id,instagram_business_account{id,username}")
                if me.get("instagram_business_account"):
                    pages = [{**me, "access_token": self.token}]
            except GraphError:
                pass
        for p in pages:
            ig = p.get("instagram_business_account")
            if ig:
                self.ig = ig["id"]
                self.page_id, self.page_token = p["id"], p.get("access_token")
                return ig["id"], ig.get("username", "")
        raise GraphError("Kein Instagram-Business-Account an einer Facebook-Seite gefunden. "
                         "Ist @stadtwuppertal ein Business-Account und mit der Seite verknüpft?")

    # ── Lesen ───────────────────────────────────────────────
    def business_discovery(self, username: str, limit: int = 15) -> dict:
        if self.ig_login:
            raise GraphError("Account-Beobachtung braucht den Facebook-Login-Weg")
        u = username.lstrip("@")
        fields = (f"business_discovery.username({u}){{username,name,followers_count,media_count,"
                  f"media.limit({limit}){{id,caption,like_count,comments_count,timestamp,permalink,media_type,media_url}}}}")
        return self._req("GET", self.ig, fields=fields).get("business_discovery", {})

    def oembed_author(self, permalink: str) -> str | None:
        """Wer hat den Post gemacht? Metas oEmbed liefert den Namen, den die Hashtag-Suche verschweigt."""
        try:
            d = self._req("GET", "instagram_oembed", url=permalink, fields="author_name")
            a = (d.get("author_name") or "").strip().lstrip("@")
            return a if re.fullmatch(r"[A-Za-z0-9._]{2,30}", a) else None
        except Exception:      # noqa: BLE001
            return None

    def hashtag_media(self, tag: str, edge: str = "top_media", limit: int = 30) -> list[dict]:
        """Öffentliche Beiträge zu einem Hashtag (braucht Metas Freigabe „Instagram Public Content Access“).
        Meta liefert keinen Nutzernamen, aber den Link zum Post. Max. 30 verschiedene Hashtags pro 7 Tage."""
        if self.ig_login:
            raise GraphError("(#10) Hashtag-Suche braucht den Facebook-Login-Weg")
        hid = self._req("GET", "ig_hashtag_search", user_id=self.ig, q=tag.lstrip("#"))["data"][0]["id"]
        return self._req("GET", f"{hid}/{edge}", user_id=self.ig, limit=limit,
                         fields="id,caption,media_type,media_url,permalink,like_count,comments_count,timestamp").get("data", [])

    def tagged_media(self, limit: int = 25) -> list[dict]:
        return self._req("GET", f"{self.ig}/tags", fields=MEDIA_FIELDS + ",username", limit=limit).get("data", [])

    def own_media(self, limit: int = 30) -> list[dict]:
        return self._req("GET", f"{self.ig}/media", fields=MEDIA_FIELDS + ",media_product_type",
                         limit=limit).get("data", [])

    def insights(self, media_id: str, product: str = "FEED") -> dict:
        metrics = "reach,likes,comments,saved,shares,total_interactions"
        if product == "REELS":
            metrics = "reach,likes,comments,saved,shares,total_interactions,views"
        try:
            data = self._req("GET", f"{media_id}/insights", metric=metrics).get("data", [])
        except GraphError:
            data = self._req("GET", f"{media_id}/insights", metric="reach,total_interactions").get("data", [])
        return {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
                for d in data}

    def account_stats(self) -> dict:
        return self._req("GET", self.ig, fields="followers_count,media_count,username")

    def comments(self, media_id: str) -> list[dict]:
        return self._req("GET", f"{media_id}/comments", fields="id,text,username,hidden,timestamp",
                         limit=50).get("data", [])

    def reply_comment(self, comment_id: str, text: str):
        self._req("POST", f"{comment_id}/replies", message=text[:900])

    def hide_comment(self, comment_id: str):
        self._req("POST", comment_id, hide="true")

    def quota(self) -> dict:
        data = self._req("GET", f"{self.ig}/content_publishing_limit", fields="quota_usage,config")
        return (data.get("data") or [{}])[0]

    # ── Postfach (nur Antworten – die erste Nachricht schickt ein Mensch, so will es Meta) ──
    def _page(self):
        if self.ig_login:                      # Instagram-Login: Postfach hängt direkt am Instagram-Account
            return self.ig, self.token
        if not getattr(self, "page_token", None):
            self.discover_ig_user()
        return self.page_id, self.page_token

    def exchange_long_lived(self, app_id: str, app_secret: str) -> bool:
        """Kurzer Explorer-Schlüssel (1–2 h) → 60-Tage-Schlüssel. Der Seiten-Schlüssel daraus läuft nie ab."""
        r = self.http.request("GET", f"{BASE}/{self.base.rsplit('/', 1)[1]}/oauth/access_token", timeout=60, data=None,
                              params={"grant_type": "fb_exchange_token", "client_id": app_id,
                                      "client_secret": app_secret, "fb_exchange_token": self.token}).json()
        if r.get("access_token"):
            self.token = r["access_token"]
            return True
        raise GraphError(f"Schlüssel verlängern ging nicht: {r.get('error', {}).get('message', r)}")

    def refresh_token(self) -> tuple[str, int] | None:
        """Instagram-Login-Tokens laufen nach 60 Tagen ab – die Engine verlängert sie selbst."""
        if not self.ig_login:
            return None
        r = self.http.get(f"{IG_BASE}/refresh_access_token", timeout=60,
                          params={"grant_type": "ig_refresh_token", "access_token": self.token}).json()
        if r.get("access_token"):
            self.token = r["access_token"]
            return self.token, int(r.get("expires_in", 0))
        return None

    def conversations(self, limit=8) -> list[dict]:
        pid, ptok = self._page()
        # Meta lehnt große Abfragen ab – erst nur die Liste, dann die Nachrichten je Unterhaltung einzeln
        r = self.http.get(f"{self.base}/{pid}/conversations", timeout=60, params={
            "platform": "instagram", "access_token": ptok, "limit": min(limit, 5), "fields": "updated_time,participants"})
        data = r.json()
        if "error" in data:
            raise GraphError(f"conversations: {data['error']}")
        out = []
        for c in data.get("data", []):
            m = self.http.get(f"{self.base}/{c['id']}", timeout=60, params={
                "access_token": ptok, "fields": "messages.limit(3){id,from,message,created_time,attachments}"}).json()
            if "error" in m:
                continue
            c["messages"] = m.get("messages", {"data": []})
            out.append(c)
        return out

    def reply(self, igsid: str, text: str):
        pid, ptok = self._page()
        r = self.http.post(f"{self.base}/{pid}/messages", timeout=60, data={
            "recipient": json.dumps({"id": igsid}), "message": json.dumps({"text": text[:900]}),
            "messaging_type": "RESPONSE", "access_token": ptok})
        if "error" in (r.json() if r.content else {}):
            raise GraphError(f"reply: {r.text[:200]}")

    # ── Veröffentlichen ─────────────────────────────────────
    def _wait(self, container: str, max_wait=600, step=6):
        waited = 0
        while waited <= max_wait:
            st = self._req("GET", container, fields="status_code,status").get("status_code")
            if st == "FINISHED":
                return
            if st in ("ERROR", "EXPIRED"):
                raise GraphError(f"Container {container}: {st}")
            time.sleep(step)
            waited += step
        raise GraphError(f"Container {container}: Zeitüberschreitung")

    def _publish(self, container: str) -> str:
        self._wait(container)
        return self._req("POST", f"{self.ig}/media_publish", creation_id=container)["id"]

    def image(self, url: str, caption: str, alt: str = "", tag_user: str = "") -> str:
        p = {"image_url": url, "caption": caption}
        if alt:
            p["alt_text"] = alt[:1000]
        if tag_user:      # im Bild markieren → Instagram benachrichtigt die Person automatisch
            try:
                return self._publish(self._req("POST", f"{self.ig}/media", **p, user_tags=json.dumps(
                    [{"username": tag_user, "x": 0.5, "y": 0.92}]))["id"])
            except GraphError:
                pass      # z. B. privates Profil: dann ohne Markierung, die @-Nennung in der Caption bleibt
        return self._publish(self._req("POST", f"{self.ig}/media", **p)["id"])

    def delete_media(self, media_id: str):
        self._req("DELETE", media_id)

    def carousel(self, urls: list[str], caption: str) -> str:
        kids = [self._req("POST", f"{self.ig}/media", image_url=u, is_carousel_item="true")["id"] for u in urls[:10]]
        for k in kids:
            self._wait(k)
        c = self._req("POST", f"{self.ig}/media", media_type="CAROUSEL", children=",".join(kids), caption=caption)
        return self._publish(c["id"])

    def reel(self, video_url: str, caption: str, cover_url: str | None = None) -> str:
        p = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
        if cover_url:
            p["cover_url"] = cover_url
        return self._publish(self._req("POST", f"{self.ig}/media", **p)["id"])

    def story(self, image_url: str | None = None, video_url: str | None = None) -> str:
        p = {"media_type": "STORIES"}
        p.update({"image_url": image_url} if image_url else {"video_url": video_url})
        return self._publish(self._req("POST", f"{self.ig}/media", **p)["id"])

    def permalink(self, media_id: str) -> str:
        return self._req("GET", media_id, fields="permalink").get("permalink", "")


class FakeGraph:
    """Für Tests und Trockenläufe: postet nichts, merkt sich nur, was es tun würde."""

    def __init__(self, discovery: dict | None = None):
        self.ig = "1784-test"
        self.done = []
        self.discovery = discovery or {}
        self.inbox, self.replies = [], []

    def discover_ig_user(self):
        return self.ig, "stadtwuppertal"

    def business_discovery(self, username, limit=15):
        return self.discovery.get(username, {"username": username, "followers_count": 1000, "media": {"data": []}})

    def tagged_media(self, limit=25):
        return getattr(self, "tags", [])

    def hashtag_media(self, tag, edge="top_media", limit=30):
        return getattr(self, "hashtag", {}).get(tag, []) if edge == "top_media" else []

    def oembed_author(self, permalink):
        return getattr(self, "authors", {}).get(permalink)

    def own_media(self, limit=30):
        return [{"id": x[1], "timestamp": "2026-11-20T10:00:00+0000", "media_product_type": "FEED"} for x in self.done]

    def insights(self, media_id, product="FEED"):
        return {"reach": 1200, "likes": 80, "comments": 12, "saved": 9, "shares": 14, "total_interactions": 115}

    def account_stats(self):
        return {"followers_count": 1234, "media_count": len(self.done)}

    def comments(self, media_id):
        return getattr(self, "comment_box", {}).get(media_id, [])

    def reply_comment(self, comment_id, text):
        self.done.append(("comment_reply", comment_id, text))

    def conversations(self, limit=25):
        return self.inbox

    def reply(self, igsid, text):
        self.replies.append((igsid, text))

    def hide_comment(self, cid):
        self.done.append(("hide", cid))

    def quota(self):
        return {"quota_usage": len(self.done)}

    def _rec(self, kind, *a):
        mid = f"ig-{len(self.done) + 1}"
        self.done.append((kind, mid, a))
        return mid

    def image(self, url, caption, alt="", tag_user=""):
        return self._rec("image", url, caption, tag_user)

    def delete_media(self, media_id):
        self.done.append(("delete", media_id))

    def carousel(self, urls, caption):
        return self._rec("carousel", urls, caption)

    def reel(self, video_url, caption, cover_url=None):
        return self._rec("reel", video_url, caption)

    def story(self, image_url=None, video_url=None):
        return self._rec("story", image_url or video_url)

    def permalink(self, media_id):
        return f"https://instagram.com/p/{media_id}"


def dumps(o):
    return json.dumps(o, ensure_ascii=False)
