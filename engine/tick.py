"""Ein Takt der Engine (läuft alle 10 Minuten über GitHub Actions).

Ablauf: Gedächtnis laden → Telegram lesen → sammeln & sichten → planen → produzieren → posten
→ Tagesaufgaben (Radar, Statistik, Bericht) → Gedächtnis speichern. Jeder Schritt ist für sich
abgesichert: Wenn eine Quelle oder ein Schritt hakt, läuft der Rest weiter und du bekommst einen Alarm.
"""
from __future__ import annotations

import random
import re
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml
from PIL import Image

from . import commons, radar, sources
from .brain import Brain, stub
from .design import render
from .graph import GraphClient
from .llm import LLM
from .store import Store
from .telegram import Telegram

STATE = "_engine/state.json"
AD = re.compile(r"#(ad|anzeige|werbung|sponsored|gifted|kooperation)\b|\b(anzeige|werbung|rabattcode|gutscheincode)\b", re.I)
RULES = "_engine/regeln.md"


def _fp(token) -> str:
    """Fingerabdruck des ganzen Schlüssels (die ersten Zeichen sind bei Meta-Schlüsseln oft gleich)."""
    import hashlib
    return "h" + hashlib.sha256((token or "").encode()).hexdigest()[:16]


def make_store(secrets, root):
    """Auf GitHub: alles in GitHub (Pages + verschlüsseltes Gedächtnis). Lokal: Ordner local_store/."""
    import os
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if repo and token:
        from .gitstore import GitStore
        key = secrets.STATE_KEY or secrets.TELEGRAM_TOKEN or secrets.IG_TOKEN or "stadtwuppertal"
        return GitStore(repo, token, key, pages_dir=root / "pages")
    return Store(secrets, root / "local_store")


def default_state():
    return {"v": 3, "ig_user_id": None, "chat_id": None, "tg_offset": 0, "paused": False, "seen": {}, "items": {},
            "stories": {}, "queue": [], "posted": [], "done": {}, "radar": [], "accounts": {}, "stats": {},
            "used": [], "used_photos": [], "log": [], "alerts": {}, "followers": {}, "bildfreigaben": {},
            "angefragt": {}, "anfragen": {}, "dm_seen": {}, "ratings": {}, "abgelehnt": {}}


class Engine:
    def __init__(self, cfg, secrets, *, store=None, graph=None, llm=None, telegram=None, http=requests,
                 now: datetime | None = None, dry=False):
        self.cfg, self.s, self.http, self.dry = cfg, secrets, http, dry
        self.root = Path(cfg["_root"])
        self.tz = ZoneInfo(cfg.get("timezone", "Europe/Berlin"))
        self._now = now
        self.store = store or make_store(secrets, self.root)
        self.st = {**default_state(), **self.store.read_json(STATE, {})}
        if graph is not None:
            self.graph = graph
        elif secrets.IG_TOKEN:
            # verlängerter Token aus dem Gedächtnis hat Vorrang, solange er zum Secret gehört
            tok = secrets.IG_TOKEN
            if self.st.get("ig_token") and self.st.get("ig_token_from") == _fp(secrets.IG_TOKEN):
                tok = self.st["ig_token"]
            self.graph = GraphClient(tok, self.st.get("ig_user_id"), cfg["account"]["graph_api_version"])
        else:
            self.graph = None
        live_llm = secrets.CLAUDE_CODE_OAUTH_TOKEN or secrets.ANTHROPIC_API_KEY
        self.llm = llm or LLM(secrets, cfg["llm"], stub=None if (live_llm and not dry) else stub)
        rules = (self.root / "data/redaktion.md").read_text(encoding="utf-8")
        learned = (self.store.get(RULES) or b"").decode("utf-8")
        self.brain = Brain(self.llm, cfg, rules + ("\n" + learned if learned else ""))
        self.tg = telegram or Telegram(secrets.TELEGRAM_TOKEN, self.st, http=http, dry=dry)
        self.errors: list[str] = []
        self.k = cfg["takt"]

    # ── Hilfen ──────────────────────────────────────────────
    def now(self):
        return (self._now or datetime.now(timezone.utc)).astimezone(self.tz)

    def ts(self):
        return self.now().timestamp()

    def today(self):
        return self.now().date().isoformat()

    def log(self, msg):
        self.st["log"].append(f"{self.now():%m-%d %H:%M} {msg}")
        self.st["log"] = self.st["log"][-400:]

    def step(self, name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:      # noqa: BLE001 – ein Schritt darf den Takt nicht stoppen
            self.errors.append(f"{name}: {e}")
            self.log(f"FEHLER {name}: {e}")
            if self.dry:
                traceback.print_exc()

    def at(self, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        return self.now().replace(hour=h, minute=m, second=0, microsecond=0)

    def once(self, key) -> bool:
        """True genau einmal pro Tag und Schlüssel."""
        k = f"{self.today()}:{key}"
        if self.st["done"].get(k):
            return False
        self.st["done"][k] = True
        return True

    def feed_today(self):
        return [p for p in self.st["posted"] if p["day"] == self.today() and p["kind"] in ("feed", "reel")]

    # ── Takt ────────────────────────────────────────────────
    def tick(self):
        self.step("setup", self.setup)
        self.step("telegram", self.read_telegram)
        h = self.now().hour + self.now().minute / 60
        active = self.k["active_hours"][0] <= h < self.k["active_hours"][1]
        bound = self.st.get("chat_id") or not self.tg.live      # ohne verbundenen Chat wird nichts gepostet
        if not bound and self.once("hinweis-start"):
            self.log("warte auf /start im Telegram-Bot")
        if not self.st["paused"] and active and bound:
            self.step("sammeln", self.collect)
            self.step("planen", self.plan)
            self.step("postfach", self.check_dms)
            self.step("hashtags", self.scout_hashtags)
            self.step("produzieren", self.produce)
            self.step("posten", self.publish_due)
        self.step("tagesaufgaben", self.daily)
        self.alarm()
        self.cleanup()
        self.store.write_json(STATE, self.st)
        self.store.close()
        return self.errors

    def setup(self):
        new_secret = _fp(self.s.IG_TOKEN) != self.st.get("ig_token_from") and not self.st.get("ig_direct")
        if self.graph is not None and (not self.st.get("ig_user_id") or new_secret):
            if new_secret:                    # neuer Schlüssel im Secret → frisch verbinden, alten Seiten-Token vergessen
                self.graph.token, self.st["page_id"] = self.s.IG_TOKEN, None
                self.graph.page_token = None
            if self.s.APP_SECRET and not getattr(self.graph, "ig_login", False):
                self.graph.exchange_long_lived(str(self.cfg["account"].get("meta_app_id", "")), self.s.APP_SECRET)
            ig, name = self.graph.discover_ig_user()
            self.st["ig_user_id"] = ig
            self.st["ig_direct"] = bool(getattr(self.graph, "ig_login", False))
            self.st["ig_token"], self.st["ig_token_from"] = None, _fp(self.s.IG_TOKEN)
            if getattr(self.graph, "page_token", None) and not self.st["ig_direct"]:
                # Nutzer-Token läuft nach 60 Tagen ab, der Seiten-Token daraus nie → ab jetzt den nehmen
                self.st["page_id"] = self.graph.page_id
                self.st["ig_token"], self.st["ig_token_from"] = self.graph.page_token, _fp(self.s.IG_TOKEN)
                self.graph.token = self.graph.page_token
            self.log(f"Instagram verbunden: @{name} ({ig})")
            self.tg.say(f"instagram verbunden: @{name}")
        if self.graph is not None:
            self.graph.ig = self.st["ig_user_id"]
            if self.st.get("page_id") and not getattr(self.graph, "page_token", None):
                self.graph.page_id, self.graph.page_token = self.st["page_id"], self.graph.token
            if self.st.get("ig_direct") and not getattr(self.graph, "ig_login", True):
                self.graph.ig_login = True        # Portfolio-Schlüssel: direkt über graph.instagram.com
                self.graph.base = "https://graph.instagram.com/" + self.graph.base.rsplit("/", 1)[1]
        if hasattr(self.store, "ensure_pages") and self.once("pages"):
            if not self.store.ensure_pages():
                self.log("GitHub Pages ist aus – bitte in Settings → Pages einschalten (Branch gh-pages)")

    # ── Telegram ────────────────────────────────────────────
    def read_telegram(self):
        for ev in self.tg.poll():
            if ev["type"] == "command":
                if ev["cmd"] == "stopp":
                    self.st["paused"] = True
                    self.tg.say("pausiert. nichts wird mehr gepostet, bis du „weiter“ schreibst.")
                elif ev["cmd"] == "weiter":
                    self.st["paused"] = False
                    self.tg.say("läuft wieder.")
                elif ev["cmd"] == "regel":
                    old = (self.store.get(RULES) or b"").decode("utf-8")
                    self.store.put(RULES, (old + f"- {ev['text'].strip()} ({self.today()})\n").encode("utf-8"))
                    self.brain.rules += f"\n- {ev['text'].strip()}"
                    self.tg.say("regel gemerkt. gilt ab dem nächsten text.")
                else:
                    self.tg.say(self.status_text())
                continue
            if ev["code"] in ("fa", "fn"):
                if ev["code"] == "fa":
                    self.st["bildfreigaben"][ev["item"]] = self.today()
                    self.tg.say(f"freigabe von @{ev['item']} gemerkt. ihre bilder nutzen wir ab jetzt mit credit.")
                continue
            item = next((q for q in self.st["queue"] if q["id"] == ev["item"]), None)
            if not item or item["status"] != "waiting":
                continue
            if ev["code"] == "ok":
                item.update(status="ready", label=False, approved=True)
                self.tg.mark(item.get("tg"), "freigegeben ✓")
            else:
                item["status"] = "dropped"
                self.tg.mark(item.get("tg"), "verworfen")
                self.log(f"verworfen von dir: {item['id']}")

    def status_text(self):
        q = [x for x in self.st["queue"] if x["status"] in ("new", "ready", "waiting")]
        return (f"{'PAUSIERT · ' if self.st['paused'] else ''}heute gepostet: {len(self.feed_today())} · "
                f"in arbeit: {len(q)} · letzte meldung: {self.st['log'][-1] if self.st['log'] else '–'}")

    # ── 1. Sammeln & sichten ────────────────────────────────
    def collect(self):
        last = self.st["done"].get("collect_ts", 0)
        if self.ts() - last < self.k["collect_every_min"] * 60:
            return
        self.st["done"]["collect_ts"] = self.ts()
        srcs = self.cfg["sources"] + self.cfg.get("event_sources", [])
        if self.graph is not None and getattr(self.graph, "ig_login", False):
            srcs = [x for x in srcs if x["type"] != "instagram"]   # Account-Beobachtung erst mit Facebook-Weg
        items, errs = sources.collect(srcs, self.cfg["news"], self.graph, self.http, now=self.now())
        if errs:
            self.st["done"]["source_errors"] = errs[-20:]
        self.step("markierungen", self.scout_tags)
        new = [i for i in items if i["id"] not in self.st["seen"]]
        for i in new:
            self.st["seen"][i["id"]] = self.ts()
            self.st["items"][i["id"]] = {k: i.get(k) for k in ("id", "source", "title", "summary", "link",
                                                              "published", "likes", "comments", "kind", "image", "image_ok", "handle", "credits", "ask_source")}
            self.st["items"][i["id"]]["summary"] = (i.get("summary") or "")[:900]
            if any(i["source"] == e["name"] for e in self.cfg.get("event_sources", [])):
                self.st["items"][i["id"]]["event"] = True
        if not new:
            return
        recent_hooks = [" ".join(p.get("hook", [])) for p in self.st["posted"][-20:]]
        for chunk in range(0, len(new), 40):
            res = self.brain.triage(new[chunk:chunk + 40], self.st["stories"], self.st["radar"], recent_hooks)
            for r in res or []:
                if r.get("id") not in self.st["items"]:
                    continue
                slug = re.sub(r"[^a-z0-9-]", "", str(r.get("story", "x")).lower())[:40] or "x"
                s = self.st["stories"].setdefault(slug, {"title": r.get("title", ""), "score": 0, "items": [],
                                                         "first": self.ts(), "posted": False, "followup": None,
                                                         "breaking": False, "risk": "gruen", "rubric": "news"})
                s["items"] = list(dict.fromkeys(s["items"] + [r["id"]]))[-8:]
                s["score"] = max(s["score"], float(r.get("score", 0)))
                s["breaking"] = s["breaking"] or bool(r.get("breaking"))
                s["rubric"] = r.get("rubric", s["rubric"])
                if r.get("risk") == "rot" or s["risk"] == "rot":
                    s["risk"] = "rot"
                s["last"] = self.ts()
        self.log(f"{len(new)} neue Meldungen gesichtet")

    # ── 2. Planen ───────────────────────────────────────────
    def enqueue(self, mode, kind="feed", story=None, idea=None, due=None, priority=False, base=None, note=""):
        qid = f"{int(self.ts())}-{mode}-{random.randint(100, 999)}"
        self.st["queue"].append({"id": qid, "mode": mode, "kind": kind, "story": story, "idea": idea,
                                 "due": due or self.ts(), "priority": priority, "status": "new",
                                 "created": self.ts(), "base": base, "note": note})
        if story:
            self.st["stories"][story]["queued"] = True
        return qid

    def plan(self):
        now = self.ts()
        stories = self.st["stories"]
        # Eilmeldung
        for slug, s in stories.items():
            fresh = now - s.get("first", now) < 6 * 3600
            if s["breaking"] and s["score"] >= self.k["breaking_score"] and fresh and not s.get("queued"):
                self.enqueue("meldung", story=slug, priority=True)
                if s["score"] >= 7:
                    s["followup"] = now + self.k["followup_after_h"] * 3600
        # Nachdreh fällig
        for slug, s in stories.items():
            if s.get("posted") and s.get("followup") and now >= s["followup"] and not s.get("followed"):
                s["followed"] = True
                self.enqueue("nachdreh", story=slug)
        # feste Slots
        for hhmm, name in self.k["slots"].items():
            start = self.at(hhmm)
            if not (start <= self.now() < start + timedelta(minutes=90)) or not self.once(f"slot:{name}"):
                continue
            self.plan_slot(name)
        # Story und Reel des Tages
        if self.at(self.k["reel_slot"]) <= self.now() and self.once("reel"):
            base = next((p for p in reversed(self.st["posted"])
                         if p["day"] == self.today() and p["kind"] == "feed" and p.get("reel_ok")), None)
            if base:
                self.enqueue("reel", kind="reel", base=base["qid"])
            else:
                idea = self.pick_idea(prefer="history")
                if idea:
                    self.enqueue("rubrik", kind="reel", idea=idea)

    def plan_slot(self, name):
        now = self.ts()
        if any(q.get("priority") and q["kind"] == "feed" and q["status"] in ("new", "waiting", "ready")
               and now - q.get("created", 0) < 2 * 3600 for q in self.st["queue"]):
            return                    # eine Eilmeldung füllt den Slot
        cands = sorted([(s["score"], k) for k, s in self.st["stories"].items()
                        if not s.get("queued") and now - s.get("last", now) < 26 * 3600 and s["score"] >= 6],
                       reverse=True)
        weekday = ["mo", "di", "mi", "do", "fr", "sa", "so"][self.now().weekday()]
        plan = self.k["rotation"].get(name, {})
        rubric = plan.get(weekday) if isinstance(plan, dict) else plan
        if rubric == "events":
            ev = [i for i in self.st["items"].values() if i.get("event")]
            if len(ev) >= 3:
                self.enqueue("events", idea={"events": ev[-40:]})
                return
        if cands and (name == "morgen" or cands[0][0] >= 7.5 or not rubric):
            self.enqueue("meldung", story=cands[0][1])
            return
        if rubric == "warum":
            hot = [k for sc, k in cands if self.st["stories"][k]["score"] >= 6]
            if hot:
                self.enqueue("warum", story=hot[0])
                return
            idea = self.pick_idea(prefer="poll")
            if idea:
                self.enqueue("warum", idea=idea)
                return
        if rubric == "damals":
            self.enqueue("damals")
            return
        idea = self.pick_idea(prefer=rubric or "history")
        if idea:
            self.enqueue("rubrik", idea=idea)
        elif cands:
            self.enqueue("meldung", story=cands[0][1])

    def pick_idea(self, prefer="history"):
        used = set(self.st["used"])
        ideas = yaml.safe_load((self.root / "data/ideas.yaml").read_text(encoding="utf-8")).get("ideas", [])
        hist = yaml.safe_load((self.root / "data/history.yaml").read_text(encoding="utf-8")).get("history", [])
        today = self.now().strftime("%m-%d")
        pool = []
        for h in hist:
            if h.get("status") not in ("geprueft", "tag_pruefen") or f"h:{h['date']}:{h['year']}" in used:
                continue
            exact = h["date"] == today and h["status"] == "geprueft"
            pool.append((3 if exact else (1 if prefer == "history" else 0), {**h, "type": "history",
                                                                              "id": f"h:{h['date']}:{h['year']}",
                                                                              "jahrestag": exact}))
        for i in ideas:
            if i.get("status") != "geprueft" or i["id"] in used:
                continue
            t = i.get("type", "fact")
            pool.append((2 if t == prefer else 0.5, {**i, "type": t}))
        if not pool:
            return None
        top = max(p for p, _ in pool)
        choice = random.choice([x for p, x in pool if p == top])
        self.st["used"].append(choice["id"])
        return choice

    # ── 3. Produzieren ──────────────────────────────────────
    def material(self, q):
        if q["mode"] == "damals":
            if "_damals" not in q:
                hit = commons.historical(set(self.st["used_photos"]), self.http)
                q["_damals"] = hit or {}
            hit = q["_damals"]
            if not hit:
                return {}
            self.st["used_photos"].append(hit["page"])
            return {"historisches_foto": {k: hit[k] for k in ("title", "description", "date", "page")},
                    "_bild": commons.fetch(hit, self.http), "_credit": commons.credit(hit)}
        if q.get("story"):
            s = self.st["stories"][q["story"]]
            return {"geschichte": s["title"],
                    "meldungen": [self.st["items"][i] for i in s["items"] if i in self.st["items"]]}
        return q.get("idea") or {}

    def produce(self):
        for q in [x for x in self.st["queue"] if x["status"] == "new"][:2]:   # max 2 pro Takt, damit es flott bleibt
            self.step(f"produktion {q['id']}", self.produce_one, q)
            if q["status"] == "new":
                q["status"] = "dropped"

    def produce_one(self, q):
        if q["mode"] == "reel" and q.get("base"):
            base = next((x for x in self.st["queue"] if x["id"] == q["base"]), None)
            if not base or not base.get("pkg", {}).get("reel"):
                q["status"] = "dropped"
                return
            q["pkg"], q["caption"] = base["pkg"], base["caption"]
            q["label"] = base.get("label", False)
            return self.render_reel(q)
        if q["mode"] == "foto":
            return self.produce_submission(q)
        mat = self.material(q)
        if q["mode"] == "damals" and not mat:
            q["status"] = "dropped"
            return
        text_mat = {k: v for k, v in mat.items() if not k.startswith("_")} if isinstance(mat, dict) else mat
        recent = [" ".join(p.get("hook", [])) for p in self.st["posted"][-15:]]
        pkg = self.brain.write(q["mode"], text_mat, note=self.learned_note(), recent_hooks=recent)
        rev = self.brain.review(pkg, text_mat)
        pkg.update(rev.get("fixes") or {})
        pkg["risk"] = max(pkg.get("risk", "gruen"), rev.get("risk", "gruen"), key=["gruen", "gelb", "rot"].index)
        pkg["public_interest"] = bool(rev.get("public_interest", pkg.get("public_interest")))
        if not rev.get("ok", True):
            q["status"] = "dropped"
            self.tg.say(f"nicht veröffentlicht ({q['mode']}): {rev.get('note', '')}")
            return
        q["pkg"] = pkg
        if q["mode"] == "damals":
            q.pop("_damals", None)
            return self.produce_damals(q, pkg, mat)
        photo, credit = self.pick_photo(q, pkg)
        q["credit"] = credit
        seed = q["id"]
        wagnis = random.Random(seed).random() < self.cfg.get("wagnis_rate", 0.1)
        if q["kind"] == "reel":
            q["caption"] = self.caption(pkg, credit)
            return self.render_reel(q, photo)
        imgs = render.carousel(pkg, photo, wagnis=wagnis, seed=seed)
        q["media"] = [self.store.media(f"{int(self.ts())}-{q['id']}-{n}.jpg", render.jpeg(im)) for n, im in enumerate(imgs)]
        q["cover_jpeg"] = None
        self._cover = getattr(self, "_cover", {})
        self._cover[q["id"]] = render.jpeg(imgs[0], 85)
        self.decide(q, pkg, credit)

    def pick_photo(self, q, pkg):
        """Reihenfolge: freigegebenes Bild aus der Meldung → freies Foto (Commons) → keins (Typo).
        Hat ein Account ein passendes Bild ohne Freigabe, kommt eine Foto-Anfrage an dich."""
        import io
        items = self.material(q).get("meldungen", []) if q.get("story") else []
        for it in items:
            ok = it.get("image_ok") or (f"bildquelle: @{it['handle']}" if it.get("handle") in self.st["bildfreigaben"] else None)
            if it.get("image") and ok:
                try:
                    r = self.http.get(it["image"], timeout=60)
                    r.raise_for_status()
                    return Image.open(io.BytesIO(r.content)).convert("RGB"), ok
                except Exception:
                    pass
        story = self.st["stories"].get(q.get("story") or "", {})
        if story.get("score", 0) >= 7:
            asked = False
            for it in items:
                if asked or not it.get("image"):
                    continue
                for h in (it.get("credits") or []) + ([it["handle"]] if it.get("ask_source") else []):
                    r = self.judge(f"news:{it['id']}", it["image"], {"handle": h, "caption": it.get("summary")}, "news")
                    if self.worth_asking(h, r, self.cfg["photos"]["news_min"]):
                        self.ask(h, {"story": q.get("story"), "qid": q["id"], "link": it.get("link"),
                                     "title": story.get("title", ""), "rating": r}, it, story.get("title", ""))
                        asked = True
                        break
        if pkg.get("photo_query"):
            photo, credit, page = commons.find_photo(pkg["photo_query"], set(self.st["used_photos"]), self.http)
            if page:
                self.st["used_photos"].append(page)
                return photo, credit
        return None, None

    # ── Bildredaktion & Anfragen ────────────────────────────
    def fetch_bytes(self, url):
        r = self.http.get(url, timeout=60)
        r.raise_for_status()
        return r.content

    def judge(self, key, url, meta, purpose):
        """Claude schaut sich das Foto an. Ergebnis wird gemerkt, jedes Bild nur einmal bewertet."""
        if key in self.st["ratings"]:
            return self.st["ratings"][key]
        try:
            raw = self.fetch_bytes(url)
            r = self.brain.rate_photo(raw, meta, purpose)
        except Exception as e:      # noqa: BLE001
            self.log(f"bildbewertung {key}: {str(e)[:80]}")
            r = {"score": 0, "ask": False, "why": "nicht bewertbar"}
        r["purpose"] = purpose
        self.st["ratings"][key] = r
        return r

    def worth_asking(self, handle, r, minimum):
        """Lohnt die Anfrage? Starkes Bild, passender Account, keine Werbung, nicht zu oft fragen."""
        p = self.cfg["photos"]
        today = int(self.st["done"].get(f"{self.today()}:anfragen", 0))
        return (handle and r.get("ask") and r.get("score", 0) >= minimum and not r.get("ad") and not r.get("watermark")
                and r.get("account_type") in ("person", "fotograf", "verein", "initiative")
                and handle not in self.st["bildfreigaben"] and handle not in self.st["abgelehnt"]
                and self.ts() - self.st["angefragt"].get(handle, 0) > p["ask_again_days"] * 86400
                and today < p["max_requests_per_day"])

    def ask(self, handle, req, item, title):
        self.st["angefragt"][handle] = self.ts()
        self.st["anfragen"][handle] = {**req, "ts": self.ts()}
        k = f"{self.today()}:anfragen"
        self.st["done"][k] = int(self.st["done"].get(k, 0)) + 1
        self.photo_request(handle, item, title)

    def scout_tags(self):
        """Wer @stadtwuppertal markiert: bewerten. Nur Top-Fotos → Anfrage; mit Freigabe → Vorschau an dich."""
        if self.graph is None:
            return
        p = self.cfg["photos"]
        try:
            tagged = self.graph.tagged_media(limit=10)
        except Exception:      # noqa: BLE001 – beim Instagram-Login-Weg gibt es diese Liste ggf. nicht
            return
        for t in tagged:
            key, h = f"tag:{t['id']}", (t.get("username") or "")
            if key in self.st["seen"] or not h or t.get("media_type") not in ("IMAGE", "CAROUSEL_ALBUM") \
                    or not t.get("media_url") or AD.search(t.get("caption") or ""):
                self.st["seen"].setdefault(key, self.ts())
                continue
            self.st["seen"][key] = self.ts()
            r = self.judge(key, t["media_url"], {"handle": h, "caption": t.get("caption")}, "community")
            if h in self.st["bildfreigaben"] and r.get("score", 0) >= p["community_min"] and not r.get("people"):
                self.enqueue("foto", idea={"tag": {"user": h, "image": t["media_url"], "text": (t.get("caption") or "")[:300],
                                                   "rating": r}})
            elif self.worth_asking(h, r, p["community_min"]):
                self.ask(h, {"tag": True, "image": t["media_url"], "text": (t.get("caption") or "")[:300],
                             "link": t.get("permalink"), "rating": r}, t, "dein Foto, auf dem du uns markiert hast")

    def scout_hashtags(self):
        """#meinwuppertal & Co.: die stärksten Fotos finden, bewerten, Fotograf ermitteln, Anfrage vorbereiten.
        Braucht Metas Freigabe „Public Content Access“ – bis dahin schläft dieser Teil still."""
        if self.graph is None or self.st["done"].get("hashtag_off_until", 0) > self.ts():
            return
        last = self.st["done"].get("hashtag_ts", 0)
        if self.ts() - last < self.cfg["photos"]["hashtag_every_min"] * 60:
            return
        self.st["done"]["hashtag_ts"] = self.ts()
        p = self.cfg["photos"]
        cands = []
        for tag in p["hashtags"][:6]:
            try:
                media = self.graph.hashtag_media(tag, "top_media") + self.graph.hashtag_media(tag, "recent_media")
            except Exception as e:      # noqa: BLE001
                if "permission" in str(e).lower() or "(#10)" in str(e) or "(#200)" in str(e):
                    self.st["done"]["hashtag_off_until"] = self.ts() + 86400
                    self.log("hashtag-scout: noch keine Meta-Freigabe (Public Content Access)")
                    return
                raise
            for m in media:
                key = f"ht:{m['id']}"
                if key in self.st["seen"] or m.get("media_type") not in ("IMAGE", "CAROUSEL_ALBUM") or not m.get("media_url"):
                    continue
                self.st["seen"][key] = self.ts()
                if AD.search(m.get("caption") or ""):
                    continue
                cands.append((m.get("like_count") or 0, key, m))
        for _, key, m in sorted(cands, key=lambda x: -x[0])[:p["rate_per_run"]]:
            h = sources.username_from_permalink(m.get("permalink", ""), self.http)
            r = self.judge(key, m["media_url"], {"handle": h, "caption": m.get("caption")}, "community")
            if r.get("score", 0) < p["community_min"] or r.get("people"):
                continue
            if h and h in self.st["bildfreigaben"]:
                self.enqueue("foto", idea={"tag": {"user": h, "image": m["media_url"], "text": (m.get("caption") or "")[:300],
                                                   "rating": r}})
            elif self.worth_asking(h or f"post:{m['id']}", r, p["community_min"]):
                self.ask(h or f"post:{m['id']}", {"tag": True, "image": m["media_url"], "text": (m.get("caption") or "")[:300],
                                                  "link": m.get("permalink"), "rating": r},
                         m, "dein Foto unter #" + p["hashtags"][0])

    def photo_request(self, handle, item, title=""):
        """Meta lässt die erste DM nur von Menschen zu: Die Engine macht alles fertig, du tippst einmal und fügst ein.
        Antwort, Dank, Bild abholen und einbauen erledigt sie danach selbst."""
        dm = (f"Hey! Wir sind @stadtwuppertal. Dein Foto zu „{title[:60]}“ ist richtig stark. "
              f"Dürfen wir es mit Credit (@{handle}) bei uns zeigen? Gern auch künftig bei Wuppertal-Themen. Danke dir!")
        r = (self.st["anfragen"].get(handle) or {}).get("rating") or {}
        why = f"\nbildredaktion: {r.get('score')}/10 – {r.get('why', '')}" if r else ""
        if handle.startswith("post:"):
            dm = dm.replace(f" (@{handle})", "")
            step1 = f"1 · post öffnen, auf den namen tippen, „nachricht“: {item.get('permalink') or item.get('link', '')}"
            head = "unbekannt (meta liefert keinen namen)"
        else:
            step1 = f"1 · tippen: https://ig.me/m/{handle}"
            head = "@" + handle
        html = (f"📸 <b>bild-anfrage</b> · {head}\n{title[:80]}{why}\n{item.get('permalink') or item.get('link', '')}\n\n"
                f"{step1}\n2 · text tippen = kopiert, dann einfügen:\n<code>{dm}</code>\n\n"
                f"den rest mache ich: antwort lesen, danken, bild holen.")
        if self.tg.live and self.tg.chat:
            self.tg._call("sendMessage", chat_id=self.tg.chat, text=html, parse_mode="HTML",
                          disable_web_page_preview="true")
        else:
            self.tg.outbox.append(("foto-anfrage", handle))

    YES = re.compile(r"\b(ja|jo|jap|klar|gern|gerne|okay|ok|sicher|logo|natürlich|na klar|darfst|dürft|mach|passt)\b|👍|✅|🙏|❤", re.I)
    NO = re.compile(r"\b(nein|nö|lieber nicht|nicht|kein)\b", re.I)

    def check_dms(self):
        """Liest Antworten auf Bild-Anfragen: ja → Freigabe merken, danken, Bild holen und nachschieben."""
        if self.graph is None:
            return
        for conv in self.graph.conversations():
            msgs = (conv.get("messages") or {}).get("data", [])
            for m in reversed(msgs):                      # älteste zuerst
                frm = m.get("from") or {}
                handle = (frm.get("username") or "").lower()
                if frm.get("id") == self.st.get("ig_user_id") or m["id"] in self.st["dm_seen"]:
                    continue
                self.st["dm_seen"][m["id"]] = self.ts()
                text = m.get("message") or ""
                imgs = [a.get("image_data", {}).get("url") or a.get("file_url")
                        for a in (m.get("attachments") or {}).get("data", [])]
                imgs = [u for u in imgs if u]
                req = next((v | {"h": k} for k, v in self.st["anfragen"].items() if k.lower() == handle), None)
                if not req:
                    open_posts = [k for k in self.st["anfragen"] if k.startswith("post:")]
                    if len(open_posts) == 1 and handle:
                        self.st["anfragen"][handle] = self.st["anfragen"].pop(open_posts[0])
                        req = self.st["anfragen"][handle] | {"h": handle}
                    elif imgs and handle:
                        self.dm_submission(frm, handle, imgs[0], text)
                        continue
                    else:
                        continue
                h = req["h"]
                if imgs or (self.YES.search(text) and not self.NO.search(text)):
                    h = handle if h.startswith("post:") else h
                    first = h not in self.st["bildfreigaben"]
                    self.st["bildfreigaben"][h] = self.today()
                    if first:
                        self.graph.reply(frm["id"], "Mega, danke dir! Wir nennen dich als @" + h +
                                         ". Wenn du magst, schick uns das Foto hier gern in voller Größe.")
                        self.tg.say(f"✓ @{h} hat ja gesagt. freigabe gemerkt.")
                    if req.get("tag"):
                        self.enqueue("foto", idea={"tag": {"user": h, "image": (imgs or [req.get("image")])[0],
                                                           "text": req.get("text", "")}})
                        self.st["anfragen"].pop(h, None)
                    elif imgs:
                        self.push_update(h, req, imgs[0])
                elif self.NO.search(text):
                    self.st["anfragen"].pop(h, None)
                    self.st["abgelehnt"][h] = self.today()
                    self.tg.say(f"@{h} möchte nicht. alles gut, ist vermerkt.")
                else:
                    import json as _j
                    kb = {"inline_keyboard": [[{"text": "als freigabe werten", "callback_data": f"fa:{h}"},
                                               {"text": "nein", "callback_data": f"fn:{h}"}]]}
                    if self.tg.live and self.tg.chat:
                        self.tg._call("sendMessage", chat_id=self.tg.chat, reply_markup=_j.dumps(kb),
                                      text=f"@{h} hat geantwortet: „{text[:300]}“")

    def dm_submission(self, frm, handle, url, text):
        """Jemand schickt uns ein Foto per DM: bewerten, bei starkem Bild nach dem Okay fragen
        (die Person hat zuerst geschrieben, also dürfen wir antworten)."""
        r = self.judge(f"dm:{handle}:{url[-40:]}", url, {"handle": handle, "caption": text}, "community")
        p = self.cfg["photos"]
        if r.get("score", 0) >= p["community_min"] - 0.5 and not r.get("ad") and not r.get("people"):
            self.st["anfragen"][handle] = {"tag": True, "image": url, "text": text[:300], "ts": self.ts(), "rating": r}
            self.graph.reply(frm["id"], f"Danke dir, richtig schönes Foto! Dürfen wir es mit Nennung (@{handle}) "
                                        "bei uns zeigen? Antworte einfach mit „ja“.")
        else:
            self.graph.reply(frm["id"], "Danke dir fürs Schicken! Wir schauen es uns an.")

    def push_update(self, handle, req, url):
        """Bild ist da: als Story-Update zur Geschichte posten (mit sichtbarem Credit). Läuft die Meldung noch nicht,
        wird das Bild direkt eingebaut."""
        import io
        r = self.http.get(url, timeout=60)
        r.raise_for_status()
        photo = Image.open(io.BytesIO(r.content)).convert("RGB")
        q = next((x for x in self.st["queue"] if x["id"] == req.get("qid")), None)
        pkg = (q or {}).get("pkg") or {"rubric": "news", "hook": ["update."], "schild": ""}
        credit = f"bildquelle: @{handle}"
        upd = {**pkg, "schild": credit[:22]}
        img = render.story(upd, photo, seed=handle)
        url_st = self.store.media(f"{int(self.ts())}-upd-{handle}.jpg", render.jpeg(img))
        self.st["queue"].append({"id": f"upd-{handle}-{int(self.ts())}", "mode": "update", "kind": "story",
                                 "status": "ready", "due": self.ts(), "media": [url_st], "priority": True,
                                 "created": self.ts(), "pkg": upd, "caption": ""})
        self.st["anfragen"].pop(handle, None)

    def produce_damals(self, q, pkg, mat):
        """damals/heute: historisches Foto (Public Domain) oben, derselbe Ort heute unten."""
        old_img, old_credit = mat.get("_bild"), mat.get("_credit")
        if old_img is None:
            q["status"] = "dropped"
            return
        new_img, new_credit, page = commons.find_photo(pkg.get("heute_query") or "", set(self.st["used_photos"]), self.http)
        if page:
            self.st["used_photos"].append(page)
        imgs = render.damals(pkg, old_img, new_img)
        imgs += [render.follow(pkg, s, more=i < len(pkg.get("slides", [])) - 1)
                 for i, s in enumerate(pkg.get("slides", [])[:4])]
        q["media"] = [self.store.media(f"{int(self.ts())}-{q['id']}-{n}.jpg", render.jpeg(im)) for n, im in enumerate(imgs)]
        self._cover = getattr(self, "_cover", {})
        self._cover[q["id"]] = render.jpeg(imgs[0], 85)
        credit = " · ".join(c for c in (old_credit, new_credit) if c)
        q["caption"] = self.caption(pkg, credit)
        # Bildauswahl braucht ein Auge: Vorschau, ohne Antwort geht es nach 2 Stunden raus
        q.update(status="waiting", on_timeout="post", timeout=self.ts() + 2 * 3600)
        q["tg"] = self.tg.preview(self._cover[q["id"]], "damals/heute – passen die bilder zusammen?\n\n"
                                  + q["caption"][:700], q["id"])

    def render_reel(self, q, photo=None):
        from .design.reel import render_reel
        photos = [photo] if photo else []
        if not photos and q.get("pkg", {}).get("photo_query"):
            p, _, page = commons.find_photo(q["pkg"]["photo_query"], set(), self.http)
            photos = [p] if p else []
        path, cover_img, dur = render_reel(q["pkg"], photos)
        stamp = int(self.ts())
        q["media"] = [self.store.media(f"{stamp}-{q['id']}.mp4", Path(path).read_bytes())]
        q["cover"] = self.store.media(f"{stamp}-{q['id']}-cover.jpg", render.jpeg(cover_img))
        Path(path).unlink(missing_ok=True)
        self._cover = getattr(self, "_cover", {})
        self._cover[q["id"]] = render.jpeg(cover_img, 85)
        if q.get("base"):
            q["status"] = "ready"
        else:
            self.decide(q, q["pkg"], q.get("credit"))

    def produce_submission(self, q):
        import io
        if "tag" in q["idea"]:
            t = q["idea"]["tag"]
            r = self.http.get(t["image"], timeout=60)
            r.raise_for_status()
            meta, raw = {"insta": t["user"], "text": t.get("text"), "consent": True}, r.content
        else:
            meta = self.store.read_json(f"einreichen/fotos/{q['idea']['submission']}", {})
            raw = self.store.get(f"einreichen/fotos/{meta.get('file', '')}")
        if not raw or not meta.get("consent"):
            q["status"] = "dropped"
            return
        if "tag" not in q["idea"]:
            r = self.brain.rate_photo(raw, {"handle": meta.get("insta"), "caption": meta.get("text")}, "community")
            if r.get("score", 0) < self.cfg["photos"]["community_min"] - 1.5 or r.get("ad") or r.get("people"):
                q["status"] = "dropped"
                self.log(f"einreichung verworfen ({r.get('score')}/10): {r.get('why', '')}")
                return
            q["idea"]["tag"] = {"rating": r, "user": meta.get("insta"), "image": None}
        img = render.community(Image.open(io.BytesIO(raw)), meta.get("name", ""))
        pkg = self.brain.write("rubrik", {"typ": "community-foto", "ort": meta.get("ort"), "text": meta.get("text"),
                                          "hinweis": "Nur Caption schreiben: 2–3 Zeilen über Ort/Stimmung, "
                                                     "nichts über Personen behaupten, Frage am Ende."})
        handle = (meta.get("insta") or "").lstrip("@")
        credit = f"foto: {('@' + handle) if handle else meta.get('name', 'eingereicht')}"
        pkg.update(rubric="photo", hook=[], slides=[], reel=[])
        q["pkg"] = pkg
        q["media"] = [self.store.media(f"{int(self.ts())}-{q['id']}.jpg", render.jpeg(img))]
        self._cover = getattr(self, "_cover", {})
        self._cover[q["id"]] = render.jpeg(img, 85)
        q["caption"] = self.caption(pkg, credit)
        rating = (q["idea"].get("tag") or {}).get("rating") or {}
        auto = self.cfg["photos"].get("autopost_min")
        strong = bool(auto) and rating.get("score", 0) >= auto
        q.update(status="waiting", timeout=self.ts() + 3 * 3600, on_timeout="post" if strong else "drop")
        note = (f"bildredaktion: {rating.get('score')}/10 – {rating.get('why', '')}\n" if rating else "")
        q["tg"] = self.tg.preview(self._cover[q["id"]], f"community-foto – posten?\n{note}"
                                  f"{'ohne antwort geht es in 3 h raus.' if strong else 'ohne antwort wird es nicht gepostet.'}"
                                  f"\n\n{q['caption'][:600]}", q["id"])

    def decide(self, q, pkg, credit):
        """Freigabe-Logik: rot → nur mit deinem Tipp. Nachrichten → Vorschau, nach Ablauf mit KI-Hinweis.
        Alles andere → läuft allein."""
        q["caption"] = self.caption(pkg, credit)
        news_like = pkg.get("public_interest") and q["kind"] in ("feed", "reel") and self.graph is not None
        if pkg.get("risk") == "rot":
            q.update(status="waiting", on_timeout="drop", timeout=self.ts() + 3 * 3600)
            head = "⚠️ heikel – nur mit deinem ok:\n" + (pkg.get("risk_reason") or "")
        elif news_like:
            q.update(status="waiting", on_timeout="post", timeout=self.ts() + self.k["approval_timeout_min"] * 60)
            head = (f"meldung – prüfen? ohne antwort geht sie in {self.k['approval_timeout_min']} min "
                    f"mit ki-hinweis raus.")
        else:
            q["status"] = "ready"
            return
        src = "\n".join(f"· {x.get('name')}: {x.get('url', '')}" for x in pkg.get("sources", [])[:4])
        q["tg"] = self.tg.preview(self._cover[q["id"]], f"{head}\n\n{q['caption'][:600]}\n\nquellen:\n{src}", q["id"])

    def caption(self, pkg, credit, label=False):
        parts = [pkg.get("caption", "").strip()]
        via = [s["name"] for s in pkg.get("sources", []) if s.get("name")]
        if via:
            parts.append("quelle: " + ", ".join(dict.fromkeys(via)))
        if credit:
            parts.append(credit)
        tags = list(dict.fromkeys(self.cfg["voice"]["always_hashtags"] + pkg.get("hashtags", [])))[:5]
        parts.append(" ".join("#" + t.lstrip("#").replace(" ", "") for t in tags))
        return "\n\n".join(p for p in parts if p)

    def learned_note(self):
        first = min((p["ts"] for p in self.st["posted"]), default=self.ts())
        if self.ts() - first < self.k["learn_after_days"] * 86400:
            return ""
        by = {}
        for p in self.st["posted"][-120:]:
            s = self.st["stats"].get(p.get("ig", ""), {})
            if s:
                by.setdefault(p.get("rubric", "?"), []).append(s.get("total_interactions") or 0)
        ranked = sorted(((sum(v) / len(v), k) for k, v in by.items() if len(v) >= 3), reverse=True)
        return ("Was bei uns zuletzt am besten lief (Interaktionen im Schnitt): " +
                ", ".join(f"{k} {int(a)}" for a, k in ranked[:5])) if ranked else ""

    # ── 4. Posten ───────────────────────────────────────────
    def publish_due(self):
        now = self.ts()
        for q in [x for x in self.st["queue"] if x["status"] == "waiting"]:
            if now >= q.get("timeout", now + 1):
                if q.get("on_timeout") == "post":
                    q.update(status="ready", label=True)
                    self.tg.mark(q.get("tg"), "läuft mit ki-hinweis")
                else:
                    q["status"] = "dropped"
                    self.tg.mark(q.get("tg"), "verfallen")
        for _ in range(2):            # zweiter Durchgang: Stories, die beim Posten gerade entstanden sind
            self._publish_pass(now)

    def _publish_pass(self, now):
        ready = sorted([x for x in self.st["queue"] if x["status"] == "ready" and x["due"] <= now],
                       key=lambda x: (not x.get("priority"), x["due"]))
        for q in ready:
            if q["kind"] in ("feed", "reel") and not q.get("priority"):
                today = self.feed_today()
                if len(today) >= self.k["max_feed_per_day"]:
                    continue
                if today and now - today[-1]["ts"] < self.k["min_gap_min"] * 60:
                    continue
            self.step(f"veröffentlichen {q['id']}", self.publish_one, q)

    def publish_one(self, q):
        caption = q["caption"]
        if q.get("label"):
            caption = caption.replace("\n\nquelle:", "\n\ntext mit ki erstellt · quelle:", 1) \
                if "\n\nquelle:" in caption else caption + "\n\ntext mit ki erstellt"
        if hasattr(self.store, "flush_media"):
            self.store.flush_media()          # Dateien müssen öffentlich sein, bevor Instagram/Telegram sie abholt
        if self.graph is None:                # Übergabe-Modus: du postest selbst, also prüft ein Mensch → kein KI-Hinweis
            self.tg.handover(q["media"], q["kind"], q["caption"])
            ig = None
        elif q["kind"] == "story":
            ig = self.graph.story(image_url=q["media"][0])
        elif q["kind"] == "reel":
            ig = self.graph.reel(q["media"][0], caption, q.get("cover"))
        elif len(q["media"]) > 1:
            ig = self.graph.carousel(q["media"], caption)
        else:
            ig = self.graph.image(q["media"][0], caption)
        q.update(status="published", ig=ig)
        pkg = q.get("pkg", {})
        self.st["posted"].append({"qid": q["id"], "ig": ig, "ts": self.ts(), "day": self.today(), "kind": q["kind"],
                                  "mode": q["mode"], "rubric": pkg.get("rubric"), "hook": pkg.get("hook", []),
                                  "reel_ok": bool(pkg.get("reel")), "label": bool(q.get("label"))})
        if q.get("story"):
            self.st["stories"][q["story"]]["posted"] = True
        self.log(f"gepostet {q['kind']} {q['mode']}: {' '.join(pkg.get('hook', []))}")
        if ig is None:
            return self._story_after(q, pkg)
        link = ""
        try:
            link = self.graph.permalink(ig)
        except Exception:
            pass
        self.tg.say(f"gepostet: {' '.join(pkg.get('hook', [])) or q['mode']} {link}".strip())
        self._story_after(q, pkg)

    def _story_after(self, q, pkg):
        # Nachrichten zusätzlich als Story anschieben
        if q["kind"] == "feed" and q["mode"] in ("meldung", "nachdreh", "warum") and pkg.get("hook"):
            st_img = render.story(pkg, None, seed=q["id"])
            url = self.store.media(f"{int(self.ts())}-{q['id']}-story.jpg", render.jpeg(st_img))
            self.st["queue"].append({"id": q["id"] + "-s", "mode": "story", "kind": "story", "status": "ready",
                                     "due": self.ts(), "media": [url], "priority": True, "created": self.ts(),
                                     "pkg": pkg, "caption": ""})

    # ── 5. Tagesaufgaben ────────────────────────────────────
    def daily(self):
        now = self.now()
        if self.graph is not None and getattr(self.graph, "ig_login", False) and \
                self.ts() - self.st["done"].get("token_refreshed", 0) > 7 * 86400:
            got = self.graph.refresh_token()
            if got:
                self.st["ig_token"], self.st["ig_token_from"] = got[0], _fp(self.s.IG_TOKEN)
                self.st["done"]["token_refreshed"] = self.ts()
        if self.graph is not None and not getattr(self.graph, "ig_login", False) and now.hour >= 6 and self.once("radar"):
            hits, accounts, errs = radar.scan(self.graph, self.cfg["radar"])
            self.st["radar"], self.st["accounts"] = hits, accounts
        if self.graph is not None and now.hour >= 22 and self.once("insights"):
            self.insights()
        if now >= self.at(self.k["report_at"]) and self.once("bericht"):
            self.tg.say(self.report())
            self.st["followers"][self.today()] = self.st.get("_followers_now")
        if now.weekday() == 6 and now >= self.at(self.k["report_at"]) and self.once("woche"):
            self.weekly()

    def insights(self):
        cutoff = self.ts() - 7 * 86400
        for p in [p for p in self.st["posted"] if p["ts"] >= cutoff and p["kind"] != "story"]:
            try:
                self.st["stats"][p["ig"]] = self.graph.insights(p["ig"], "REELS" if p["kind"] == "reel" else "FEED")
            except Exception as e:      # noqa: BLE001
                self.log(f"insights {p['ig']}: {str(e)[:80]}")

    def report(self):
        try:
            acc = self.graph.account_stats() if self.graph else {}
        except Exception:
            acc = {}
        f_now = acc.get("followers_count")
        self.st["_followers_now"] = f_now
        prev = self.st["followers"].get((self.now() - timedelta(days=1)).date().isoformat())
        delta = f" ({f_now - prev:+d})" if (f_now and prev) else ""
        posts = [p for p in self.st["posted"] if p["day"] == self.today()]
        lines = [f"tagesbericht · follower: {f_now or '?'}{delta}", ""]
        for p in posts:
            s = self.st["stats"].get(p["ig"], {})
            lines.append(f"· {p['kind']} {p.get('rubric') or p['mode']}: {' '.join(p['hook'])[:40]}"
                         + (f" – {s.get('total_interactions')} interaktionen" if s else ""))
        if self.st["radar"]:
            lines += ["", "läuft woanders gerade:"]
            lines += [f"· @{h['handle']} ({h['x']}×): {h['text'][:70]}" for h in self.st["radar"][:3]]
        errs = self.st["done"].get("source_errors") or []
        if errs:
            lines += ["", f"{len(errs)} quellen hakten (läuft trotzdem)."]
        return "\n".join(lines)

    def weekly(self):
        week = self.now().strftime("%G-W%V")
        posts = [p for p in self.st["posted"] if self.ts() - p["ts"] < 7 * 86400 and p["kind"] != "story"]
        rows = []
        for p in posts:
            s = self.st["stats"].get(p["ig"], {})
            rows.append(f"| {p['day']} | {p['kind']} | {p.get('rubric') or p['mode']} | {' '.join(p['hook'])[:40]} | "
                        f"{s.get('reach', '')} | {s.get('total_interactions', '')} |")
        md = (f"# Woche {week}\n\nFollower: {self.st.get('_followers_now')}\n\n| Tag | Format | Rubrik | Hook | "
              f"Reichweite | Interaktionen |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
        out = self.root / "reports" / f"{week}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(md, encoding="utf-8")

    # ── Aufräumen & Alarm ───────────────────────────────────
    def alarm(self):
        if not self.errors:
            return
        key = f"{self.now():%Y-%m-%d %H}"
        if self.st["alerts"].get(key):
            return
        self.st["alerts"] = {key: True}
        self.tg.say("⚠️ es hakt:\n" + "\n".join(e[:200] for e in self.errors[:5]))

    def cleanup(self):
        cut = self.ts() - 4 * 86400
        self.st["seen"] = {k: v for k, v in self.st["seen"].items() if v > self.ts() - 14 * 86400}
        self.st["items"] = {k: v for k, v in self.st["items"].items() if self.st["seen"].get(k, 0) > cut}
        self.st["stories"] = {k: v for k, v in self.st["stories"].items() if v.get("last", v["first"]) > cut}
        self.st["queue"] = [q for q in self.st["queue"] if q["status"] in ("new", "ready", "waiting")
                            or q.get("created", 0) > cut][-80:]
        for q in self.st["queue"]:
            q.pop("cover_jpeg", None)
        self.st["posted"] = self.st["posted"][-500:]
        self.st["done"] = {k: v for k, v in self.st["done"].items()
                           if not re.match(r"\d{4}-\d{2}-\d{2}", k) or k[:10] >= (self.now() - timedelta(days=3)).date().isoformat()}
        self.st["used_photos"] = self.st["used_photos"][-300:]
        self.st["anfragen"] = {k: v for k, v in self.st["anfragen"].items() if v["ts"] > self.ts() - 3 * 86400}
        self.st["dm_seen"] = {k: v for k, v in self.st["dm_seen"].items() if v > self.ts() - 7 * 86400}
        self.st["ratings"] = dict(list(self.st["ratings"].items())[-400:])
        self.st["used"] = self.st["used"][-600:]
        if self.once("prune"):
            self.store.prune_media(10)
