"""python -m engine [tick | check | demo]

tick   ein Takt (das macht GitHub alle 10 Minuten)
check  prüft alle Verbindungen (Instagram, Telegram, GitHub-Ablage, Claude, Quellen) – postet nichts
demo   rendert Beispiel-Kacheln nach ./out (lokal, ohne Zugangsdaten)
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import load_config, load_secrets


def check(cfg, s):
    from . import sources
    from .graph import GraphClient
    from .llm import LLM
    from .store import Store
    import requests
    lines, ok = [], True

    def row(name, good, info=""):
        nonlocal ok
        ok = ok and good
        lines.append(f"{'✓' if good else '✗'} {name} {info}".strip())

    miss = s.missing()
    row("zugangsdaten", not miss, ("fehlt: " + ", ".join(miss)) if miss else "")
    g = None
    if s.IG_TOKEN:
        try:
            g = GraphClient(s.IG_TOKEN, version=cfg["account"]["graph_api_version"])
            ig, name = g.discover_ig_user()
            row("instagram", True, f"@{name}")
        except Exception as e:      # noqa: BLE001
            row("instagram", False, str(e)[:200])
    else:
        lines.append("· instagram noch nicht verbunden → fertige posts kommen per telegram zum selbst hochladen")
    if s.TELEGRAM_TOKEN:
        try:
            me = requests.get(f"https://api.telegram.org/bot{s.TELEGRAM_TOKEN}/getMe", timeout=30).json()
            row("telegram", me.get("ok"), "@" + me.get("result", {}).get("username", "?"))
        except Exception as e:      # noqa: BLE001
            row("telegram", False, str(e)[:200])
    import os
    if os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_TOKEN"):
        try:
            from .tick import make_store
            st = make_store(s, Path(cfg["_root"]))
            pages = st.ensure_pages()
            url = st.media(f"{int(__import__('time').time())}-check.txt", b"ok")
            st.close()
            ok_pub = requests.get(url, timeout=30).status_code == 200
            row("github-ablage", pages and ok_pub, url if ok_pub else "Pages noch nicht erreichbar")
        except Exception as e:      # noqa: BLE001
            row("github-ablage", False, str(e)[:200])
    try:
        llm = LLM(s, cfg["llm"])
        out = llm.ask("check", "Antworte nur mit JSON.", 'Gib {"ok": true} zurück.', tier="triage")
        row("claude", bool(out.get("ok")))
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (255, 232, 0)).save(buf, "JPEG")
        seen = llm.ask_image("check", "Antworte nur mit JSON.", 'Welche Farbe hat das Bild? {"farbe": "…"}', buf.getvalue())
        row("bildredaktion", "gelb" in str(seen).lower() or "yellow" in str(seen).lower(), str(seen)[:60])
    except Exception as e:      # noqa: BLE001
        tok = s.CLAUDE_CODE_OAUTH_TOKEN or ""
        hint = f" [schlüssel: {len(tok)} zeichen, beginnt {'richtig' if tok.startswith('sk-ant-oat') else 'falsch'}]"
        row("claude", False, str(e)[:160] + hint)
    items, errs = sources.collect(cfg["sources"] + cfg.get("event_sources", []), cfg["news"], g)
    row("quellen", len(items) > 0, f"{len(items)} meldungen, {len(errs)} quellen haken")
    for e in errs[:12]:
        lines.append(f"   · {e[:140]}")
    print("\n".join(lines))
    return ok


def demo(cfg):
    from .brain import stub
    from .design import render
    out = Path("out")
    out.mkdir(exist_ok=True)
    samples = [stub("meldung", ""), {**stub("warum", ""), "hook": ["parken", "kostenlos?"], "options": ["ja", "nö"]},
               {**stub("rubrik", ""), "hook": ["der kaiser", "fuhr zuerst."], "schild": "24.10.1900"}]
    for n, pkg in enumerate(samples):
        for i, im in enumerate(render.carousel(pkg, seed=str(n))):
            im.save(out / f"demo{n}_{i}.jpg", quality=88)
        render.story(pkg, seed=str(n)).save(out / f"demo{n}_story.jpg", quality=88)
    print("ok →", out.resolve())


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "tick"
    cfg, s = load_config(), load_secrets()
    if cmd == "check":
        sys.exit(0 if check(cfg, s) else 1)
    if cmd == "demo":
        return demo(cfg)
    if s.missing() and "--dry" not in argv:
        print("Einrichtung noch nicht fertig – es fehlt: " + ", ".join(s.missing()) + ". Takt übersprungen.")
        return
    from .tick import Engine
    errors = Engine(cfg, s, dry="--dry" in argv).tick()
    print("takt fertig" + (f" mit {len(errors)} fehlern: " + " | ".join(errors) if errors else ""))


if __name__ == "__main__":
    main(sys.argv)
