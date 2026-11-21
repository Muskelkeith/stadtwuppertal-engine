"""Redaktion: sichten (triage), schreiben (write), prüfen (review). Drei getrennte Rollen,
damit der Text nicht von dem geprüft wird, der ihn geschrieben hat."""
from __future__ import annotations

import json

VOICE = """Du bist die Redaktion von @stadtwuppertal: ein unabhängiger Instagram-Account von und für Leute aus
Wuppertal (nicht die Stadtverwaltung). Ziel: richtig viele Wuppertaler erreichen – der Kanal, dem man im Tal einfach folgt.

WIE EIN GUTES RADIO
- Das Programm ist gemischt: die großen Themen, die alle betreffen (Verkehr, Wetter, Blaulicht, Stadtpolitik,
  Schwebebahn, Feste), und dazwischen immer wieder die interessanten Sachen, auf die wir aufmerksam machen:
  freie Szene, Tanz, Kultur, Leute und Projekte, Geschichte, Kurioses.
- Niveau einen Tick über dem Durchschnitt, aber immer für alle verständlich. Nie elitär, nie stumpfes Nachrichten-Reposten.
- Vielfalt ist Normalfall, nicht Sonderthema: Viertel, migrantische Communities, Uni, Szene.

TON
- Locker, warm, mit Humor – wie jemand aus dem Tal, der gut informiert ist und gern erzählt. Keine Pressestelle.
- Witz steckt in der Sprache, nicht in erzwungenen Pointen: eine lockere Formulierung, ein trockener Halbsatz,
  ein Augenzwinkern. Nicht jeder Post braucht einen Gag; wenn einer kommt, steht das komische Wort am Ende.
- Wuppertaler Dialekt dort, wo es passt und nicht missverständlich wird: „watt“, „dat“, „ne?“, „wa?“, „hasse“,
  „hasste“, „kannze“, „getz“, „sach ma“. Dosiert, damit es wohlig warm wird, nicht Klamauk. Bei ernsten Meldungen
  Hochdeutsch.
- Selbstironie über Wuppertal ja (Regen, Treppen, Schwebebahn-Ausfälle), Herablassung über Menschen oder Viertel nie.
- Kritik an Stadt, Politik, Unternehmen darf hart und zugespitzt sein, auch mal polemisch, um Reaktionen zu
  bekommen – aber immer an Fakten und Zahlen, nie an Personen.
- Keine KI-Floskeln: kein „spannend“, „tauche ein“, „mehr als nur“, „in einer Welt“, keine Dreierketten,
  keine Gedankenstriche-Kaskaden, keine Emoji-Ketten (höchstens eins, wenn es wirklich sitzt).

WITZ
- Lieber kein Witz als ein flacher. Nicht erklären. Callbacks erlaubt.
- Kein Witz bei Unglücken, Verletzten, Opfern, Gefährdung. Harmlose, absurde Vorfälle, bei denen niemand zu Schaden
  kam (z. B. jemand klaut etwas völlig Absurdes), dürfen dagegen ruhig lustig erzählt werden.

HOOK (große Headline auf der Kachel)
- 1–3 Zeilen, klein geschrieben, je Zeile höchstens ~11 Zeichen, endet meist mit Punkt oder Fragezeichen.
- Muss im Feed in 1 Sekunde wirken: konkret, überraschend, ein Bild im Kopf. Kein Clickbait, das nicht hält.
- Schild: optional, max. 16 Zeichen (Datum, Ort, Zahl, Pointe).

HARTE REGELN
- Fakten NUR aus dem mitgelieferten Material. Nichts erfinden, keine erfundenen Zitate, keine Zahlen raten.
- Keine Namen, Fotos oder erkennbaren Details von Verdächtigen, Opfern, Minderjährigen.
- Absolut keine diskriminierenden Inhalte (Rassismus, Antisemitismus, Queer-, Ausländer-, Behindertenfeindlichkeit).
- Fremde Texte nie übernehmen: komplett neu formulieren. Quelle immer nennen.
Antworte ausschließlich mit dem verlangten JSON."""

PACKAGE = """{
 "rubric": "news|history|events|poll|warum|fact|platt|quiz|kurios|spotlight",
 "hook": ["zeile 1", "zeile 2"],
 "schild": "kurz oder leer",
 "options": ["a", "b"]   // nur bei poll/warum/quiz: zwei Antworten statt Schild, sonst []
 "slides": [{"head": "kurze unterzeile (eine Frage oder ein Versprechen)", "body": "2–5 Sätze, die genau das einlösen: konkret, mit Mehrwert, normale Groß-/Kleinschreibung"}],  // 0–5
 "reel": [{"head": "unter-hook klein", "lines": ["Satz mit Fakt", "Satz, der erklärt warum / was daraus wurde"], "gag": "Pointe oder leer"},
          {"bild": "Commons-Suchbegriff für ein großes Foto, z. B. 'Felix Hoffmann' oder 'Bayer Elberfeld 1900'", "text": "Bildunterschrift mit Info, 8–20 Wörter"}],
          // 4–6 Züge, nur wenn als Reel geeignet, sonst []. Text-Zug: head + 2–3 kurze Sätze, zusammen ~120–200 Zeichen, + optional gag.
          // Der überraschendste Fakt zuerst (Aufmacher). Einfache, kurze Sätze, kein Fachchinesisch.
          // Bild-Zug: großes Foto statt Text – bei Geschichte mindestens einer, gern zwei. Jeder Zug = ein konkreter,
          // überraschender Fakt (Name, Jahr, Ort, Zahl, Firma). Nischenwissen schlägt Allgemeinplatz.
 "caption": "Caption: erste Zeile = Gefühl des Hooks, dann 2–4 kurze Zeilen, am Ende EINE Frage zum Mitmachen. KEINE Links, keine URLs",
 "hashtags": ["3–4 ohne #"],
 "sources": [{"name": "…", "url": "…"}],
 "photo_query": "Suchbegriff für ein freies Wikimedia-Foto (z. B. 'Schwebebahn Vohwinkel') oder leer",
 "visual": "foto|damals_heute|typo",   // was fürs Auge: Foto, damals/heute-Vergleich oder reine Typo
 "damals_query": "nur bei damals/heute", "heute_query": "nur bei damals/heute",
 "public_interest": true,   // informiert über eine Angelegenheit von öffentlichem Interesse (Nachrichten, Politik, Verkehr, Sicherheit)?
 "risk": "gruen|gelb|rot",  // rot = Personen erkennbar/Vorwürfe/Minderjährige/unbestätigt
 "risk_reason": "kurz",
 "ton": 1   // Stufe der Tonleiter aus dem Sprachkonzept (1 ernst … 4 Spaß) – bestimmt Witz, Dialekt, Wärme
}"""


class Brain:
    def __init__(self, llm, cfg, rules: str = ""):
        self.llm = llm
        self.cfg = cfg
        self.rules = rules

    @property
    def system(self):
        from pathlib import Path
        lang = Path(__file__).resolve().parent.parent / "data" / "sprache.md"
        sprache = lang.read_text(encoding="utf-8") if lang.exists() else ""
        return (VOICE + ("\n\nSPRACHKONZEPT (verbindlich, wichtiger als alles andere zum Ton)\n" + sprache if sprache else "")
                + ("\n\nREDAKTIONSREGELN (verbindlich)\n" + self.rules if self.rules else ""))

    # ── 1. Sichten ──────────────────────────────────────────
    def triage(self, items: list[dict], stories: dict, radar: list[dict], recent_hooks: list[str]) -> list[dict]:
        if not items:
            return []
        open_st = [{"story": k, "title": v["title"]} for k, v in list(stories.items())[-60:]]
        mat = [{"id": i["id"], "source": i["source"], "title": i["title"], "text": i.get("summary", "")[:500],
                "published": i.get("published"), "likes": i.get("likes"), "comments": i.get("comments")}
               for i in items[:60]]
        prompt = f"""Sichte neue Meldungen für @stadtwuppertal.
Bekannte Geschichten (gleiche Geschichte → gleichen story-Schlüssel wiederverwenden):
{json.dumps(open_st, ensure_ascii=False)}
Was gerade bei großen Kanälen gut läuft (Orientierung, nicht kopieren):
{json.dumps(radar[:8], ensure_ascii=False)}
Neue Meldungen:
{json.dumps(mat, ensure_ascii=False)}

Bewerte jede Meldung. score 0–10 = Wie sehr interessiert das möglichst viele Leute in Wuppertal JETZT
(Betroffenheit, Gesprächswert, Neuigkeit, Kommentarpotenzial)? breaking = muss sofort raus (Sperrung, Unwetter,
Ausfall Schwebebahn, Großeinsatz mit Folgen, große Stadt-News). Unwichtiges, Werbung, Doppeltes: score ≤ 3.
rubric kurios = harmlose, absurde Meldung, bei der niemand zu Schaden kam (kurioser Diebstahl, tierischer Einsatz).
JSON: {{"items": [{{"id": "…", "story": "kurzer-slug", "title": "neutraler Titel der Geschichte",
"score": 0-10, "breaking": bool, "rubric": "news|events|history|fact|warum|kurios", "risk": "gruen|gelb|rot"}}]}}"""
        res = self.llm.ask("triage", VOICE, prompt, tier="triage")
        return res.get("items", []) if isinstance(res, dict) else res

    # ── 2. Schreiben ────────────────────────────────────────
    def write(self, mode: str, material: list[dict] | dict, note: str = "", recent_hooks=()) -> dict:
        modes = {
            "meldung": "Schnelle Meldung: Was ist passiert, was bedeutet es für mich, was kann ich tun? Kachel plus so viele "
                       "Folgeslides, wie es braucht, um wirklich zu informieren (meist 1–3) – keine, wenn es selbsterklärend ist. "
                       "Gag nur, wenn die Lage es erlaubt (nie bei Unglücken).",
            "nachdreh": "Nachdreh zu einer Geschichte, die schon gemeldet wurde: Einordnung, Hintergrund, Zahlen, "
                        "offene Frage oder Quiz (rubric quiz, options = 2 plausible Antworten, Auflösung auf der letzten Slide). "
                        "Ziel: Kommentare. Karussell mit 3–5 Slides. Gern auch als Reel.",
            "warum": "Rubrik „warum so, wuppertal?“: eine Meinungs-/Streitfrage, die Wuppertal spaltet, mit zwei "
                     "Antwortoptionen (options). Kurz anteasern, Fakten aus dem Material, dann die Frage. Ziel: Kommentare.",
            "rubrik": "Rubrik-Post aus der Ideen-Bank (history, fact, platt, poll). Material ist geprüft. "
                      "Mach daraus etwas, das man teilen will. history und fact: Karussell + Reel-Züge. "
                      "fact: Nischenwissen und Kuriositäten statt Bekanntes herunterbeten, aber auch für Auswärtige verständlich.",
            "damals": "„was war, wuppertal?“ als damals/heute: ein Ort, wie er früher aussah und heute aussieht. "
                      "damals_query = Suchbegriff für ein historisches Foto (Ort + Jahrzehnt, z. B. 'Elberfeld Neumarkt 1910'), "
                      "heute_query = derselbe Ort heute. schild = Jahr des alten Fotos. Caption: was hat sich verändert, "
                      "eine überraschende Geschichte zum Ort, Frage („Wer kennt das noch?“).",
            "kurios": "„kurios, wuppertal.“ Eine harmlose, absurde Meldung, bei der niemand zu Schaden kam. Hier darf der "
                      "Witz tragen: locker, trocken, gern mit einem Schuss Dialekt. Fakten bleiben Fakten, keine Namen. rubric kurios.",
            "frag": "„sach ma, wuppertal?“: eine Frage zum Mitmachen, die Reaktionen auslöst – Ranking, Ortsfrage, Streitfrage "
                    "(z. B. „Wo liegt bei euch am meisten illegal abgeladener Müll?“). Darf zuspitzen und triggern, wertet aber "
                    "nie Menschen oder Gruppen ab. Keine Zahlen erfinden. Nicht wiederholen, was in letzte_fragen steht. "
                    "Gern an ein Thema aus zuletzt_gepostet anknüpfen (zweite Frage zur selben Geschichte, anderer Winkel). "
                    "Kachel + höchstens 1 Slide, Caption mit klarer Aufforderung zu kommentieren. rubric poll.",
            "spotlight": "„wer macht wat, wuppertal?“: Stell einen Account oder ein Projekt aus der Stadt vor, das gerade "
                         "Interessantes macht – nur mit dem, was im Material steht. Account mit @ in Caption und Slide nennen, "
                         "Lust machen, vorbeizuschauen. Keine fremden Fotos: visual typo. rubric spotlight.",
            "idee": "Eine Content-Idee vom Chef, eingesprochen oder getippt (idee_von_jd). Mach daraus den passenden Post und wähl "
                    "das Format selbst (Frage, Karussell, Fakt, Meinung). Was nicht im Material steht, nicht als Tatsache "
                    "behaupten – lieber als Frage an die Community formulieren.",
            "events": "„was geht, wuppertal?“: die 3–5 besten Termine fürs Wochenende aus dem Material. Mainstream genug "
                      "für viele, aber nicht altbacken; freie Szene, Tanz, Konzerte, Märkte. Je Termin eine Slide "
                      "(head = Name klein, body = wann, wo, warum hingehen). Nur Termine aus dem Material!",
        }
        prompt = f"""Auftrag: {modes[mode]}
{('Hinweis: ' + note) if note else ''}
Letzte Hooks (nicht wiederholen): {json.dumps(list(recent_hooks)[-12:], ensure_ascii=False)}
Material:
{json.dumps(material, ensure_ascii=False)[:9000]}

Liefere genau ein Paket als JSON:
{PACKAGE}"""
        return self.llm.ask(mode, self.system, prompt, tier="write")

    # ── 3. Prüfen ───────────────────────────────────────────
    def review(self, pkg: dict, material) -> dict:
        system = self.system + """

Du bist jetzt NICHT die Autorin, sondern die strenge Schlussredaktion. Du prüfst jeden Punkt der
Redaktionsregeln und reparierst selbst, statt nur zu meckern."""
        prompt = f"""Prüfe dieses Paket gegen Material und Redaktionsregeln. Nicht jeder Test passt zu jedem Post:
wende nur an, was zum Format gehört (FUTTER nur bei Meinung/Frage, GAG nur wenn ein Witz drin ist, LÜCKEN vor allem
bei Nachrichten). Tests, die nicht passen, bekommen in tests den Wert null. Gehe die passenden Tests durch:
1. FAKTEN: Stimmt jede Tatsache mit dem Material? Erfundenes streichen.
2. RECHT: Personen erkennbar, Vorwürfe gegen Einzelne, Minderjährige, Unbestätigtes, Diskriminierung? → risk.
3. MEHRWERT: Löst jede Folgeslide ihre Überschrift konkret ein (was, seit wann, warum, wer, was heißt das für mich)?
   Fehlt Kontext, der im Material steht? Telegrammstil? Füll-Slides bei Selbsterklärendem? → umschreiben/streichen.
4. LÜCKEN: Wird Unklares offen benannt statt geraten? Witz in Lücken nur erkennbar absurd, nie bei Unglücken.
5. SPRACHE: Zeitform und Logik korrekt? Klingt es nach Sprachkonzept (wie man redet, warm, Tonstufe passend)?
   Behördendeutsch, KI-Floskeln, Sätze über fehlende Infos, Aufforderungen Instagram zu verlassen, Links → raus.
6. TON/GAG: Klingt es locker und nach Wuppertal statt nach Pressestelle? Ist ein Witz erzwungen oder offensichtlich?
   Dann streichen oder lockerer formulieren. Dialekt nur, wo er nicht missverständlich ist; bei ernsten Meldungen Hochdeutsch.
7. FUTTER (bei warum/poll/quiz): Gibt es erst Fakten, konkret Betroffene, beide Seiten, dann eine persönliche Frage?
8. AUGE: Gibt es etwas fürs Auge (visual, photo_query, starke Zahl)? Hook in 1 Sekunde verständlich, Zeilen ≤ ~11 Zeichen?
Material: {json.dumps(material, ensure_ascii=False)[:7000]}
Paket: {json.dumps(pkg, ensure_ascii=False)}
JSON: {{"ok": bool (false NUR bei rechtlichen Problemen oder wenn das Material nichts hergibt), "fixes": {{geänderte Paket-Felder}},
"risk": "gruen|gelb|rot", "public_interest": bool, "tests": {{"mehrwert": 1-5|null, "sprache": 1-5|null, "gag": 1-5|null, "futter": 1-5|null, "auge": 1-5|null}},
"note": "ein Satz, was du geändert hast"}}"""
        return self.llm.ask("review", system, prompt, tier="write")


    # ── 3b. Bildkontrolle (fertige Bilder ansehen) ──────────
    def visual_check(self, sheet_jpeg: bytes, pkg: dict, kind: str) -> dict:
        system = self.system + """

Du bist jetzt die Bildkontrolle. Du siehst die FERTIGEN Bilder eines Posts als Kontaktbogen
(Reihenfolge links→rechts, oben→unten). Nichts geht raus, was peinlich aussieht oder nicht lesbar ist."""
        prompt = f"""Format: {kind}. Prüfe streng:
1. LAYOUT: Ist irgendwo Text abgeschnitten, läuft aus dem Bild oder aus seinem Kasten, überlappt, ist zu klein
   oder kontrastarm? Leere oder kaputte Bilder? Hängt Text unschön tief oder bleibt riesig viel Platz ungenutzt?
2. INHALT: Hält jedes Bild, was es verspricht? Nischenwissen statt Allgemeinplatz, keine Nicht-Info, keine
   Floskeln, Sprachkonzept eingehalten, keine Tipp- oder Grammatikfehler, keine Wiederholungen?
3. WIRKUNG: Würde man beim Scrollen anhalten und es zu Ende lesen?
Text des Pakets zum Abgleich: {json.dumps({k: pkg.get(k) for k in ("hook", "slides", "reel")}, ensure_ascii=False)[:3000]}
JSON: {{"ok": bool (false bei JEDEM Lesbarkeits- oder Layoutfehler und bei klaren Inhaltsfehlern),
"score": 1-10, "probleme": ["kurz und konkret"], "technisch": bool (true, wenn es am Layout liegt, nicht am Text),
"lehre": "EINE allgemeine Regel für künftige Posts, die diesen Fehler verhindert – oder leer"}}"""
        return self.llm.ask_image("bildkontrolle", system, prompt, sheet_jpeg, tier="write", side=1600)

    def distill(self, lessons: list[str], critiques: list[str], current: str) -> dict:
        system = self.system + "\n\nDu pflegst jetzt das Regelheft der Redaktion. Knapp, konkret, ohne Doppelungen."
        prompt = f"""Bisher gelernte Regeln:
{current or '(noch keine)'}

Neue Beobachtungen der Bildkontrolle:
{chr(10).join('- ' + x for x in lessons[-40:]) or '(keine)'}

Kritik vom Chef an einzelnen Posts:
{chr(10).join('- ' + x for x in critiques[-30:]) or '(keine)'}

Mach daraus ein aktualisiertes Regelheft mit höchstens 15 allgemeinen Regeln (je ein Satz, umsetzbar).
Kritik des Chefs hat Vorrang. Nur was für künftige Posts gilt – Einzelfall-Korrekturen weglassen.
Nichts übernehmen, was dem Sprachkonzept widerspricht.
JSON: {{"regeln": ["…"], "neu": ["die Regeln, die wirklich neu dazugekommen sind, in Kurzform"]}}"""
        return self.llm.ask("lernen", system, prompt, tier="write")

    # ── 4. Bildredaktion ────────────────────────────────────
    def rate_photo(self, jpeg: bytes, meta: dict, purpose: str) -> dict:
        """purpose: news (Bild zu einer Meldung) | community (Foto für den Feed)."""
        system = VOICE + "\n\nDu bist jetzt die Bildredaktion. Streng: Nur wirklich starke Bilder kommen bei uns rein."
        prompt = f"""Bewerte dieses Foto für @stadtwuppertal. Zweck: {purpose}.
Account: @{meta.get('handle', '?')} · Follower: {meta.get('followers', 'unbekannt')} · Name/Bio: {meta.get('bio', '')[:200]}
Caption: «{(meta.get('caption') or '')[:600]}»
Kriterien:
- Qualität: Schärfe, Licht, Bildaufbau. Wow: Würde man beim Scrollen anhalten? (Handy-Schnappschuss ≠ stark)
- Bei news: Zeigt es das Ereignis klar und ist es vertretbar (keine Verletzten, keine Opfer, keine Kennzeichen/Gesichter im Fokus)?
- Bei community: Wuppertal erkennbar oder fühlbar? Erkennbare Personen im Vordergrund → nicht nehmen.
- Werbung/Anzeige/Produkt, Screenshot, Wasserzeichen, Text-Overlay, Meme → nicht nehmen.
- Lohnt eine Anfrage bei diesem Account? Sinnvoll: Privatperson, Hobby-/Profifotograf, Verein, Initiative.
  Nicht sinnvoll: Medium/Nachrichtenseite, Unternehmen/Werbeaccount, Behörde (die haben eigene Pressebilder),
  Accounts, die erkennbar nur Fremdes reposten.
JSON: {{"score": 0-10, "wow": 0-10, "wuppertal": bool, "ad": bool, "watermark": bool, "people": bool,
"account_type": "person|fotograf|verein|initiative|medium|unternehmen|behoerde|repost|unklar",
"ask": bool, "why": "ein Satz"}}"""
        return self.llm.ask_image("rate", system, prompt, jpeg, tier="write")


# ── Testmodus: feste, plausible Antworten ───────────────────
def stub(task: str, prompt: str):
    if task == "triage":
        ids = []
        for line in prompt.splitlines():
            if line.startswith("[") and '"id"' in line:
                try:
                    ids = [x["id"] for x in json.loads(line)]
                except Exception:
                    pass
        return {"items": [{"id": i, "story": f"story-{n % 3}", "title": f"Geschichte {n % 3}",
                           "score": 8.5 if n == 0 else 5, "breaking": n == 0, "rubric": "news",
                           "risk": "gruen"} for n, i in enumerate(ids)]}
    if task == "rate":
        hi = "TOP" in prompt or "semih" in prompt
        return {"score": 8.8 if hi else 5.0, "wow": 8 if hi else 4, "wuppertal": True, "ad": False, "watermark": False,
                "people": False, "account_type": "fotograf" if hi else "person", "ask": hi, "why": "test"}
    if task == "review":
        return {"ok": True, "fixes": {}, "risk": "gruen", "note": "passt"}
    rubric = {"events": "events", "warum": "warum", "rubrik": "history", "nachdreh": "quiz", "damals": "history"}.get(task, "news")
    return {"rubric": rubric, "hook": ["schwebe-", "bahn steht."], "schild": "bis 18 uhr",
            "options": ["ja", "nö"] if rubric in ("warum", "quiz") else [],
            "slides": [{"head": "was los ist", "body": "Zwischen Vohwinkel und Oberbarmen fährt heute nichts. Busse ersetzen."},
                       {"head": "und jetzt?", "body": "Die WSW rechnen mit Betrieb ab 18 Uhr."}],
            "reel": [{"head": "was los?", "lines": ["Heute steht die Schwebebahn.", "Busse fahren als Ersatz."],
                      "gag": "Kennt man ja."},
                     {"head": "wie lange?", "lines": ["Bis etwa 18 Uhr."], "gag": "Sagen sie."}],
            "caption": "schwebebahn steht.\n\nHeute fährt zwischen Vohwinkel und Oberbarmen nichts.\n\nWie kommt ihr heute rum?",
            "hashtags": ["wuppertal", "schwebebahn", "wsw"], "sources": [{"name": "WSW", "url": "https://wsw-online.de"}],
            "photo_query": "", "public_interest": rubric == "news", "risk": "gruen", "risk_reason": ""}
