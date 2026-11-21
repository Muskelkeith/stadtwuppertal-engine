"""Werkstatt: Einmal pro Woche repariert Claude, was die Bildkontrolle als technisches Problem gesammelt hat.

Sicherungen:
- darf nur an engine/design/ und tests/ arbeiten (alles andere wird verworfen)
- übernimmt nur, wenn alle Tests grün sind UND die Probe-Posts nach der Reparatur mindestens so gut sind wie vorher
- danach wacht die Engine 48 Stunden: Häufen sich Fehler, springt sie automatisch auf den alten Stand zurück
- die Werkstatt schreibt nie ins Gedächtnis der Engine (eigene Datei _engine/werkstatt.json)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

WERKSTATT = "_engine/werkstatt.json"
ALLOWED = ("engine/design/", "tests/")

LONG = "Donaudampfschifffahrtsgesellschaft"
PROBES = [
    {"rubric": "fact", "hook": ["aspirin", "und heroin."], "reel": [
        {"head": "elf tage später", "lines": ["Kurz nach Aspirin hat derselbe Bayer-Chemiker in Elberfeld Heroin hergestellt."]},
        {"head": "und dann?", "lines": ["Heroin kam zuerst auf den Markt. Aspirin wirkte nicht vielversprechend genug."]},
        {"head": "der name", "lines": ["A für Acetyl. Spirin von Spiraea, einer Pflanzengattung."], "gag": "Tabletten kamen später."}]},
    {"rubric": "history", "hook": ["die längste", "treppe der stadt."], "reel": [
        {"head": "wie lang?", "lines": [f"Ein sehr langes Wort wie {LONG}skapitän darf nie aus dem Kasten laufen.",
                                        "Und auch geschützte Leerzeichen müssen umbrechen können."]},
        {"head": "viel text", "lines": ["Erster Satz mit Inhalt, der etwas länger ist als sonst.",
                                        "Zweiter Satz, der noch etwas erklärt.", "Dritter Satz.", "Vierter Satz zum Schluss."]}]},
]


def probe(brain=None) -> dict:
    """Rendert feste Probe-Posts. Ergebnis: Zahl der Vermessungs-Probleme und (mit Claude) Noten der Bildkontrolle."""
    from .design.reel import Reel
    from .tick import Engine
    problems, scores = 0, []
    for pkg in PROBES:
        r = Reel(pkg, [Image.new("RGB", (1080, 1920), (120, 110, 100))])
        problems += len(r.problems)
        if brain is not None and not r.problems:
            try:
                res = brain.visual_check(Engine.contact_sheet(r.qa_frames()), pkg, "reel")
                scores.append(float(res.get("score") or 0))
            except Exception:      # noqa: BLE001
                pass
    return {"problems": problems, "score": (sum(scores) / len(scores)) if scores else None}


def _git(root, *a, check=True):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=check).stdout.strip()


def run(cfg, secrets):
    from .brain import Brain
    from .llm import LLM
    from .telegram import Telegram
    from .tick import STATE, make_store
    root = Path(cfg["_root"])
    store = make_store(secrets, root)
    st = store.read_json(STATE, {})
    w = store.read_json(WERKSTATT, {})
    todo = [t for t in st.get("technik", []) if isinstance(t, dict) and t.get("ts", 0) > w.get("erledigt_bis", 0)]
    if not todo:
        print("werkstatt: nichts zu reparieren")
        return
    llm = LLM(secrets, cfg["llm"])
    brain = Brain(llm, cfg)
    before = probe(brain)
    liste = "\n".join(f"- {t.get('kind')}: {t.get('text')}" for t in todo[-25:])
    prompt = f"""Du bist in der Werkstatt der stadtwuppertal-engine (Python). Die Bildkontrolle hat diese technischen
Probleme an fertigen Posts gefunden:
{liste}

Aufgabe: Finde die Ursachen im Gestaltungs-Code und behebe sie dauerhaft.
Regeln:
- Ändere NUR Dateien unter engine/design/ und tests/. Alles andere wird verworfen.
- Der Look (Farben, Schriften, Schiene, Kästen) bleibt. Reparieren, nicht umgestalten.
- Schreib für jedes behobene Problem einen Test in tests/, der es künftig abfängt.
- Prüfe mit: python -m pytest -q   und   python -m engine probe
- Wenn ein Problem am Text lag statt am Code, lass es.
Antworte am Ende nur mit JSON: {{"zusammenfassung": "ein kurzer deutscher Satz, was repariert wurde, oder leer"}}"""
    exe = shutil.which("claude") or "claude"
    out = ""
    for model in (cfg["llm"].get("code", "opus"), cfg["llm"].get("write", "sonnet")):
        r = subprocess.run([exe, "-p", "--output-format", "json", "--model", model, "--permission-mode", "acceptEdits",
                            "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(python -m pytest:*),Bash(python -m engine probe:*)"],
                           input=prompt, capture_output=True, text=True, cwd=root, env=llm.env, timeout=3600)
        try:
            outer = json.loads(r.stdout)
            if not outer.get("is_error"):
                out = outer.get("result", "")
                break
        except ValueError:
            pass
    from .llm import extract_json
    try:
        summary = (extract_json(out) or {}).get("zusammenfassung", "").strip()
    except Exception:      # noqa: BLE001
        summary = ""
    changed = [f for f in _git(root, "status", "--porcelain").splitlines() if f.strip()]
    paths = [f[3:].strip() for f in changed]
    verdict, why = True, ""
    if not paths or not summary:
        verdict, why = False, "keine Änderung"
    elif any(not p.startswith(ALLOWED) for p in paths):
        verdict, why = False, "hat Dateien außerhalb der Gestaltung angefasst"
    else:
        t = subprocess.run(["python", "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True)
        if t.returncode != 0:
            verdict, why = False, "Tests rot"
        else:
            after = probe(brain)
            if after["problems"] > before["problems"] or after["problems"] > 0:
                verdict, why = False, f"Probe-Posts mit {after['problems']} Layout-Problemen"
            elif before["score"] is not None and after["score"] is not None and after["score"] < before["score"] - 0.5:
                verdict, why = False, f"Probe-Posts sehen schlechter aus ({after['score']:.1f} statt {before['score']:.1f})"
    w["versuch"] = int(time.time())
    if not verdict:
        _git(root, "checkout", "--", ".", check=False)
        _git(root, "clean", "-fd", "engine/design", "tests", check=False)
        print(f"werkstatt: nicht übernommen ({why})")
        w["zuletzt_abgelehnt"] = why
        store.write_json(WERKSTATT, w)
        store.close()
        return
    _git(root, "config", "user.name", "stadtwuppertal-werkstatt")
    _git(root, "config", "user.email", "engine@users.noreply.github.com")
    _git(root, "add", *ALLOWED)
    _git(root, "commit", "-m", f"werkstatt: {summary}")
    _git(root, "pull", "--rebase", "-q", "origin", "main", check=False)
    _git(root, "push", "-q", "origin", "HEAD:main")
    sha = _git(root, "rev-parse", "HEAD")
    w.update(sha=sha, ts=int(time.time()), erledigt_bis=max(t["ts"] for t in todo), zusammenfassung=summary)
    store.write_json(WERKSTATT, w)
    store.close()
    Telegram(secrets.TELEGRAM_TOKEN, dict(st)).say(
        f"🔧 Werkstatt: {summary}\nGilt ab dem nächsten Neustart. Geht danach etwas schief, springe ich automatisch zurück.")
    print("werkstatt: übernommen", sha)
