# @stadtwuppertal · Engine v3

Ein Tal, ein Fluss, ein Schwebebus.

Läuft alle 10 Minuten kostenlos auf GitHub Actions. Sammelt Nachrichten (Lokalmedien, Instagram-Accounts,
Polizei, Stadt, DWD), sichtet und bündelt sie mit Claude, schreibt Posts im CD „hängt.“, lässt sie von einer
zweiten Claude-Rolle prüfen und postet Kacheln, Karussells, Reels und Stories über die offizielle
Instagram-Schnittstelle. Freigaben, Berichte und Alarme laufen über Telegram.

| Teil | Wo | Kosten |
|---|---|---|
| Rechnen, Zeitplan | GitHub Actions (öffentliches Repo) | 0 € |
| Bilder für Instagram | GitHub Pages (Branch gh-pages, nur 3 Tage) | 0 € |
| Gedächtnis | GitHub, verschlüsselt (Branch daten) | 0 € |
| Texte, Prüfung | Claude-Abo (CLAUDE_CODE_OAUTH_TOKEN) | vorhanden |
| Freigaben, Berichte | Telegram-Bot | 0 € |

## Ein Tag
- **07:30 / 12:30 / 18:30** feste Slots: starke Nachricht, sonst Rubrik nach Wochenplan
- **Eilmeldung** (Bewertung ≥ 8): sofort, plus Story; **Nachdreh** (Einordnung, Quiz, Frage) 4 h später
- **19:45** Reel aus dem besten Karussell des Tages · **21:30** Tagesbericht · sonntags Wochenbericht (`reports/`)
- **Radar** täglich: Was läuft bei Wuppertal Aktuell, Talzeit, Radio Wuppertal, 1LIVE, COSMO, Nova?

## Redaktionsregeln
`data/redaktion.md` – Mehrwert vor Kürze, Lücken ehrlich (oder erkennbar absurd witzig), Sprache und Zeitform,
Gags mit Wendung, Futter für Meinungsposts, ballern fürs Auge, Bildrechte. Schreiberin und Prüfer lesen sie bei
jedem Text; der Prüfer geht acht Tests durch und repariert selbst. Neue Regeln per Telegram: `regel: …`

## Bilder (wie bei Wuppertal Aktuell: Netzwerk statt Klauen)
1. Freigegebene Fotos aus dem Bildnetzwerk (Credit „bildquelle: @name“) – Freigabe per Knopf „freigabe da“
2. Honorarfreie Pressebilder von Polizei und Feuerwehr (presseportal)
3. Freie Fotos und historische Bilder (Public Domain) von Wikimedia Commons · Format damals/heute
4. Community-Fotos per DM (Bildredaktion bewertet, Engine fragt nach dem Okay, du gibst frei) · 5. eigene Typo-Kacheln
Hat ein Account ein starkes Bild ohne Freigabe, kommt eine Foto-Anfrage mit fertigem DM-Text zu dir.

## Regeln, die fest eingebaut sind
- Fakten nur aus Quellen, Texte komplett neu, Quelle in jeder Caption
- Fotos nur von Wikimedia Commons (freie Lizenzen, Urheber in der Caption) oder per Upload mit Einverständnis
- Heikles (Personen, Vorwürfe, Minderjährige, Unbestätigtes) nur mit deinem OK
- Nachrichten ohne deine Prüfung tragen „text mit ki erstellt“ (EU AI Act, Art. 50 Abs. 4)
- Keine diskriminierenden Inhalte, Kritik immer an Fakten, nie an Personen
- Ohne verbundenen Telegram-Chat wird nichts gepostet · `stopp` pausiert alles

## Befehle
```
python -m engine tick      # ein Takt
python -m engine check     # alle Verbindungen prüfen (postet nichts)
python -m engine demo      # Beispiel-Kacheln nach ./out
python -m pytest -q        # Trockenlauf eines Tages
```
Einrichtung: siehe [SETUP.md](SETUP.md).
