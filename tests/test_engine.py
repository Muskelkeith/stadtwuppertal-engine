"""Trockenlauf eines Tages: nichts wird wirklich gepostet (FakeGraph), Claude im Testmodus."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from engine import sources
from engine.config import Secrets, load_config
from engine.graph import FakeGraph
from engine.store import Store
from engine.telegram import Telegram
from engine.tick import Engine

TZ = ZoneInfo("Europe/Berlin")


class FakeTG(Telegram):
    def __init__(self, st):
        super().__init__(None, st, dry=True)
        self.inbox = []

    def poll(self):
        out, self.inbox = self.inbox, []
        return out


def items(n=3, tag="a"):
    return [{"id": f"{tag}{i}", "source": "WZ", "kind": "rss", "title": f"Meldung {i}", "summary": "Text",
             "link": f"https://x/{tag}{i}", "published": None} for i in range(n)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = load_config()
    store = Store(Secrets({}), tmp_path / "store")
    graph = FakeGraph()
    feed = {"items": items()}
    monkeypatch.setattr(sources, "collect", lambda *a, **k: (feed.pop("items", []), []))
    monkeypatch.setattr("engine.commons.find_photo", lambda *a, **k: (None, None, None))

    def run(when, inbox=()):
        e = Engine(cfg, Secrets({}), store=store, graph=graph, now=when, dry=True)
        e.tg = FakeTG(e.st)
        e.tg.inbox = list(inbox)
        errs = e.tick()
        return e, errs
    return run, graph, store, feed


def test_eilmeldung_mit_vorschau_und_timeout(env):
    run, graph, store, feed = env
    t0 = datetime(2026, 11, 23, 7, 40, tzinfo=TZ)
    e, errs = run(t0)
    assert not errs, errs
    waiting = [q for q in e.st["queue"] if q["status"] == "waiting"]
    assert waiting, "Meldung sollte zur Prüfung an Telegram gehen"
    assert any(x[0] == "preview" for x in e.tg.outbox)
    assert graph.done == []
    # 61 Minuten ohne Antwort → geht mit KI-Hinweis raus
    e, errs = run(t0 + timedelta(minutes=61))
    feed_posts = [d for d in graph.done if d[0] in ("carousel", "image")]
    assert feed_posts, graph.done
    assert "text mit ki erstellt" in feed_posts[0][2][-1]
    assert any(d[0] == "story" for d in graph.done), "Meldung wird zusätzlich als Story angeschoben"


def test_freigabe_per_knopf_ohne_label(env):
    run, graph, store, feed = env
    t0 = datetime(2026, 11, 23, 7, 40, tzinfo=TZ)
    e, _ = run(t0)
    qid = next(q["id"] for q in e.st["queue"] if q["status"] == "waiting")
    e, errs = run(t0 + timedelta(minutes=10), inbox=[{"type": "decision", "code": "ok", "item": qid}])
    assert not errs, errs
    post = next(d for d in graph.done if d[0] in ("carousel", "image"))
    assert "text mit ki erstellt" not in post[2][-1]


def test_stopp_pausiert(env):
    run, graph, store, feed = env
    t0 = datetime(2026, 11, 23, 7, 40, tzinfo=TZ)
    e, _ = run(t0, inbox=[{"type": "command", "cmd": "stopp"}])
    assert e.st["paused"]
    assert all(q["status"] == "new" for q in e.st["queue"]) or not e.st["queue"]
    e, _ = run(t0 + timedelta(minutes=90))
    assert graph.done == []
    e, _ = run(t0 + timedelta(minutes=100), inbox=[{"type": "command", "cmd": "weiter"}])
    assert not e.st["paused"]


def test_rubrik_slot_ohne_nachrichten(env):
    run, graph, store, feed = env
    feed.pop("items", None)
    t = datetime(2026, 11, 24, 12, 35, tzinfo=TZ)     # Dienstag mittag → fact
    e, errs = run(t)
    assert not errs, errs
    assert any(q["mode"] == "rubrik" for q in e.st["queue"])
    assert any(d[0] in ("carousel", "image") for d in graph.done), "Rubrik läuft ohne Freigabe"


def test_nachts_wird_nicht_gepostet(env):
    run, graph, store, feed = env
    e, errs = run(datetime(2026, 11, 23, 3, 0, tzinfo=TZ))
    assert graph.done == [] and not e.st["queue"]


def test_reel_abends_aus_dem_karussell(env, monkeypatch):
    run, graph, store, feed = env
    from PIL import Image
    import engine.design.reel as reelmod
    monkeypatch.setattr(reelmod, "render_reel",
                        lambda pkg, photos, out=None, **k: (str(store.root / "x.mp4"), Image.new("RGB", (1080, 1920)), 20.0))
    (store.root).mkdir(parents=True, exist_ok=True)
    (store.root / "x.mp4").write_bytes(b"mp4")
    feed.pop("items", None)
    run(datetime(2026, 11, 24, 12, 35, tzinfo=TZ))              # Rubrik-Karussell mit Reel-Zügen
    (store.root / "x.mp4").write_bytes(b"mp4")
    e, errs = run(datetime(2026, 11, 24, 19, 50, tzinfo=TZ))
    assert not errs, errs
    assert not any(d[0] == "reel" for d in graph.done), "Mindestabstand zum Abend-Post hält das Reel zurück"
    e, errs = run(datetime(2026, 11, 24, 21, 25, tzinfo=TZ))
    assert any(d[0] == "reel" for d in graph.done), graph.done


def test_regel_per_telegram_wird_gemerkt(env):
    run, graph, store, feed = env
    e, _ = run(datetime(2026, 11, 23, 9, 0, tzinfo=TZ),
               inbox=[{"type": "command", "cmd": "regel", "text": "Nie 'Hammer' als Witz zweimal pro Woche"}])
    assert b"Hammer" in store.get("_engine/regeln.md")
    e, _ = run(datetime(2026, 11, 23, 9, 10, tzinfo=TZ))
    assert "Hammer" in e.brain.system, "neue Regel steckt im Prompt"
    assert "Mehrwert vor Kürze" in e.brain.system, "Redaktionsregeln stecken im Prompt"


@pytest.mark.skip(reason="Foto-Anfragen per Telegram abgeschaltet")
def test_bildanfrage_bis_zum_update(env, monkeypatch):
    """Wuppertal Aktuell meldet etwas mit „Bildquelle: @semih.m4“ → Engine fragt an (du: 1 Tipp + Einfügen),
    liest die Antwort, dankt, holt das Bild und schiebt eine Story mit Credit nach."""
    run, graph, store, feed = env
    from PIL import Image
    import io

    class R:
        content = (lambda b: (Image.new("RGB", (1200, 900), (90, 90, 200)).save(b, "JPEG"), b.getvalue())[1])(io.BytesIO())

        def raise_for_status(self):
            pass
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    feed["items"] = [{"id": "ig:1", "source": "Wuppertal Aktuell", "kind": "instagram", "title": "Großbrand",
                      "summary": "Text … Bildquelle: @semih.m4", "link": "https://ig/p/1", "handle": "wuppertal.aktuell",
                      "image": "https://img/1.jpg", "image_ok": None, "credits": ["semih.m4"], "published": None}]
    t0 = datetime(2026, 11, 23, 7, 40, tzinfo=TZ)
    e, errs = run(t0)
    assert ("foto-anfrage", "semih.m4") in e.tg.outbox
    assert "wuppertal.aktuell" not in e.st["angefragt"], "Medien selbst werden nicht angefragt"
    q = next(q for q in e.st["queue"] if q.get("story"))
    assert not q.get("credit"), "ohne Freigabe kein fremdes Bild"
    # Semih antwortet mit ja und schickt das Bild
    graph.inbox = [{"messages": {"data": [{"id": "m1", "from": {"id": "999", "username": "semih.m4"},
                                           "message": "Ja klar, gerne!",
                                           "attachments": {"data": [{"image_data": {"url": "https://dm/1.jpg"}}]}}]}}]
    e, errs = run(t0 + timedelta(minutes=10))
    assert not errs, errs
    assert "semih.m4" in e.st["bildfreigaben"]
    assert graph.replies and "danke" in graph.replies[0][1].lower()
    assert any(d[0] == "story" and "upd-semih" in d[2][0] for d in graph.done), graph.done


def test_damals_heute(env, monkeypatch):
    run, graph, store, feed = env
    from PIL import Image
    import engine.commons as c
    feed.pop("items", None)
    monkeypatch.setattr(c, "historical", lambda used, http=None: {"title": "Elberfeld 1910", "description": "Neumarkt",
                        "date": "1910", "page": "https://commons/x", "url": "u", "artist": "Unbekannt", "license": "Public domain"})
    monkeypatch.setattr(c, "fetch", lambda hit, http=None: Image.new("RGB", (1200, 900), (120, 100, 80)))
    e, errs = run(datetime(2026, 11, 25, 12, 35, tzinfo=TZ))      # Mittwoch mittag → damals
    assert not errs, errs
    q = next(q for q in e.st["queue"] if q["mode"] == "damals")
    assert q["status"] == "waiting" and "Public domain" in q["caption"]


def _img_get(monkeypatch):
    from PIL import Image
    import io
    import requests

    class R:
        content = (lambda b: (Image.new("RGB", (1200, 900), (90, 90, 200)).save(b, "JPEG"), b.getvalue())[1])(io.BytesIO())
        text = ""

        def raise_for_status(self):
            pass
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())


@pytest.mark.skip(reason="Foto-Anfragen per Telegram abgeschaltet")
def test_markierungen_werden_kuratiert(env, monkeypatch):
    run, graph, store, feed = env
    _img_get(monkeypatch)
    feed.pop("items", None)
    graph.tags = [
        {"id": "1", "username": "handyknipser", "media_type": "IMAGE", "media_url": "u1", "caption": "mein balkon"},
        {"id": "2", "username": "cafe_xy", "media_type": "IMAGE", "media_url": "u2", "caption": "TOP neue torte #anzeige"},
        {"id": "3", "username": "nachtfoto", "media_type": "IMAGE", "media_url": "u3", "caption": "TOP schwebebahn bei nacht"},
        {"id": "4", "username": "stammfoto", "media_type": "IMAGE", "media_url": "u4", "caption": "TOP nebel über barmen"},
    ]
    e = Engine(load_config(), Secrets({}), store=store, graph=graph, now=datetime(2026, 11, 23, 10, 0, tzinfo=TZ), dry=True)
    e.st["bildfreigaben"]["stammfoto"] = "2026-11-01"
    e.tg = FakeTG(e.st)
    e.tick()
    asked = [x[1] for x in e.tg.outbox if x[0] == "foto-anfrage"]
    assert asked == ["nachtfoto"], asked               # schwaches Foto & Werbung: nichts
    q = next(q for q in e.st["queue"] if q["mode"] == "foto")
    assert q["status"] == "waiting", "auch mit Freigabe nie direkt in den Feed"
    assert not [d for d in graph.done if d[0] in ("image", "carousel")]


def test_hashtag_scout(env, monkeypatch):
    run, graph, store, feed = env
    _img_get(monkeypatch)
    feed.pop("items", None)
    import engine.sources as src
    monkeypatch.setattr(src, "username_from_permalink", lambda link, http=None: "wupperlicht")
    graph.hashtag = {"meinwuppertal": [
        {"id": "a", "media_type": "IMAGE", "media_url": "x", "permalink": "https://ig/p/a", "like_count": 900,
         "caption": "TOP Abendrot über dem Tal #meinwuppertal"},
        {"id": "b", "media_type": "IMAGE", "media_url": "y", "permalink": "https://ig/p/b", "like_count": 20,
         "caption": "mittagessen #meinwuppertal"}]}
    e, errs = run(datetime(2026, 11, 23, 11, 0, tzinfo=TZ))
    assert not errs, errs
    # Regel: #meinwuppertal wird ohne Anfrage übernommen – mit Credit, und nur das starke Foto
    assert not [x for x in e.tg.outbox if x[0] == "foto-anfrage"]
    fotos = [q for q in e.st["queue"] if q["mode"] == "foto"]
    assert len(fotos) == 1 and "Foto: @wupperlicht" in fotos[0]["caption"]


def test_gitstore_mit_echtem_git(tmp_path):
    """Gedächtnis verschlüsselt im Branch daten, Medien im Branch gh-pages – geprüft gegen ein echtes Git-Repo."""
    import subprocess
    from engine.gitstore import GitStore
    bare = tmp_path / "repo.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    st = GitStore("konto/stadtwuppertal-engine", "x", "geheim", remote=str(bare), wait_public=False)
    st.write_json("_engine/state.json", {"chat_id": "42"})
    url = st.media("1795000000-test.jpg", b"jpg")
    assert url == "https://konto.github.io/stadtwuppertal-engine/m/1795000000-test.jpg"
    st.close()
    # neu laden: Gedächtnis ist da, aber im Repo nur verschlüsselt
    st2 = GitStore("konto/stadtwuppertal-engine", "x", "geheim", remote=str(bare), wait_public=False)
    assert st2.read_json("_engine/state.json", {})["chat_id"] == "42"
    raw = subprocess.run(["git", "--git-dir", str(bare), "show", "daten:engine.bin"], capture_output=True).stdout
    assert b"chat_id" not in raw
    files = subprocess.run(["git", "--git-dir", str(bare), "ls-tree", "-r", "--name-only", "gh-pages"],
                           capture_output=True, text=True).stdout
    assert "m/1795000000-test.jpg" in files and ".nojekyll" in files
    # falscher Schlüssel → leeres Gedächtnis statt Absturz
    st3 = GitStore("konto/stadtwuppertal-engine", "x", "anders", remote=str(bare), wait_public=False)
    assert st3.read_json("_engine/state.json", {}) == {}


def test_foto_per_dm(env, monkeypatch):
    run, graph, store, feed = env
    _img_get(monkeypatch)
    feed.pop("items", None)
    graph.inbox = [{"messages": {"data": [{"id": "d1", "from": {"id": "77", "username": "nebelfan"},
                                           "message": "TOP hier mein foto vom toelleturm",
                                           "attachments": {"data": [{"image_data": {"url": "https://dm/2.jpg"}}]}}]}}]
    t = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)
    e, errs = run(t)
    assert not errs, errs
    assert "nebelfan" in e.st["anfragen"] and "ja" in graph.replies[-1][1]
    graph.inbox = [{"messages": {"data": [{"id": "d2", "from": {"id": "77", "username": "nebelfan"}, "message": "ja klar"}]}}]
    e, errs = run(t + timedelta(minutes=10))
    q = next(q for q in e.st["queue"] if q["mode"] == "foto")
    assert q["status"] == "waiting", "auch per DM: nur mit deinem passt"


def test_uebergabe_ohne_instagram(tmp_path, monkeypatch):
    """Instagram noch nicht verbunden: fertige Posts kommen per Telegram, ohne Wartezeit und ohne KI-Hinweis."""
    cfg = load_config()
    store = Store(Secrets({}), tmp_path / "store")
    feed = {"items": items()}
    monkeypatch.setattr(sources, "collect", lambda *a, **k: (feed.pop("items", []), []))
    monkeypatch.setattr("engine.commons.find_photo", lambda *a, **k: (None, None, None))
    e = Engine(cfg, Secrets({}), store=store, graph=None, now=datetime(2026, 11, 23, 7, 40, tzinfo=TZ), dry=True)
    e.tg = FakeTG(e.st)
    assert e.graph is None
    errs = e.tick()
    assert not errs, errs
    sent = [x for x in e.tg.outbox if x[0] == "handover"]
    assert sent, e.tg.outbox
    assert not any("ki erstellt" in x[3] for x in sent)
    assert any(x[1] == "story" for x in sent)
    assert Secrets({"TELEGRAM_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "c"}).missing() == []


def test_nutzer_token_wird_zum_seiten_token():
    """Graph-Explorer-Token (läuft ab) → Engine findet Tuffi + @stadtwuppertal und nimmt den Seiten-Token."""
    from engine.graph import GraphClient

    class R:
        def __init__(self, d, code=200):
            self.d, self.status_code, self.content = d, code, b"x"

        def json(self):
            return self.d

    class S:
        def request(self, method, url, params=None, data=None, timeout=None):
            if url.endswith("/me/accounts"):
                return R({"data": [{"id": "p1", "name": "Tuffi", "access_token": "EAAseite",
                                    "instagram_business_account": {"id": "ig1", "username": "stadtwuppertal"}}]})
            return R({"error": {"message": "nope"}}, 400)

    g = GraphClient("EAAnutzer", session=S())
    assert g.discover_ig_user() == ("ig1", "stadtwuppertal")
    assert g.page_token == "EAAseite" and not g.ig_login


def test_idee_per_telegram_landet_im_slot(env):
    run, graph, store, feed = env
    feed["items"] = []
    t = datetime(2026, 11, 24, 12, 35, tzinfo=TZ)      # Dienstag Mittag
    e, errs = run(t, inbox=[{"type": "idea", "text": "Wo liegt am meisten illegal abgeladener Müll?"}])
    assert not errs, errs
    assert any(q["mode"] == "idee" for q in e.st["queue"]), [q["mode"] for q in e.st["queue"]]
    assert any("Notiert" in x[1] for x in e.tg.outbox if x[0] == "text")


def test_frag_slot(env):
    run, graph, store, feed = env
    feed["items"] = []
    t = datetime(2026, 11, 26, 12, 35, tzinfo=TZ)      # Donnerstag Mittag → frag
    e, errs = run(t)
    assert not errs, errs
    assert any(q["mode"] == "frag" for q in e.st["queue"]), [q["mode"] for q in e.st["queue"]]


def test_kritik_per_antwort_schreibt_neu(env):
    run, graph, store, feed = env
    t0 = datetime(2026, 11, 23, 7, 40, tzinfo=TZ)
    e, errs = run(t0)
    w = [q for q in e.st["queue"] if q["status"] == "waiting"]
    assert w
    e, errs = run(t0 + timedelta(minutes=10), inbox=[{"type": "revise", "msg": str(w[0]["tg"]), "text": "zu dünn, mehr infos"}])
    assert not errs, errs
    q = next(x for x in e.st["queue"] if x["id"] == w[0]["id"])
    assert q["status"] == "waiting" and q.get("approved_feedback") == "zu dünn, mehr infos"


def test_meinwuppertal_widerspruch_nimmt_post_raus(env):
    run, graph, store, feed = env
    feed.pop("items", None)
    e, errs = run(datetime(2026, 11, 23, 11, 0, tzinfo=TZ))
    e.st.setdefault("reposts", {})["wupperlicht"] = {"ig": "ig-77", "ts": e.ts()}
    graph.inbox = [{"messages": {"data": [{"id": "m1", "from": {"id": "u1", "username": "wupperlicht"},
                                           "message": "Bitte nimm mein Foto raus"}]}}]
    e.check_dms()
    assert ("delete", "ig-77") in graph.done
    assert "wupperlicht" in e.st["abgelehnt"] and "wupperlicht" not in e.st["reposts"]
    assert any("gelöscht" in x[1] for x in e.tg.outbox if x[0] == "text")


def test_widerspruch_per_kommentar(env):
    run, graph, store, feed = env
    feed.pop("items", None)
    e, errs = run(datetime(2026, 11, 23, 11, 0, tzinfo=TZ))
    e.st.setdefault("reposts", {})["wupperlicht"] = {"ig": "ig-88", "ts": e.ts()}
    graph.comment_box = {"ig-88": [{"username": "fremd", "text": "nein wie schön"},
                                   {"username": "wupperlicht", "text": "Bitte löschen, will ich nicht"}]}
    e.check_repost_comments()
    assert ("delete", "ig-88") in graph.done
