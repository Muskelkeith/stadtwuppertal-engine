# Einrichtung – was noch fehlt

GitHub steht schon (Konto Muskelkeith, Repository, Code). Nirgends ein Name.
Alles, was du einsammelst, kommt in **eine** Notiz. Am Ende fügst du sie einmal bei GitHub ein.

## Jetzt: zwei Schlüssel, dann läuft die Engine

### 1 · Telegram-Bot (Handy, 2 Min.)
@BotFather öffnen → `/newbot` → Name `stadtwuppertal engine` → Benutzername z. B. `stadtwuppertal_engine_bot`
→ den Schlüssel, den BotFather schickt, in die Notiz: `TELEGRAM_TOKEN=…`
→ den neuen Bot öffnen und **Starten** drücken.

### 2 · Claude-Zugang (Terminal am Mac, 3 Min.)
```
curl -fsSL https://claude.ai/install.sh | bash
claude setup-token
```
Es öffnet sich der Browser, einmal bestätigen. Den langen Schlüssel aus dem Terminal in die Notiz:
`CLAUDE_CODE_OAUTH_TOKEN=…`

### 3 · Einfügen
github.com/Muskelkeith/stadtwuppertal-engine → Settings → Secrets and variables → Actions →
New repository secret → Name `ENGINE_SECRETS`, Wert: die ganze Notiz.
Dann Actions → takt → Run workflow → `check`.

```
TELEGRAM_TOKEN=
CLAUDE_CODE_OAUTH_TOKEN=
```

Ab dann schickt die Engine dir die fertigen Posts per Telegram (Bilder bzw. Reel + Text zum Kopieren).
Du speicherst und lädst sie auf Instagram hoch. Kein Warten, kein KI-Hinweis nötig, weil du sie selbst postest.

## Später: Instagram direkt verbinden (wenn Meta die Sperre aufhebt)
Facebook sperrt dein Konto gerade vorübergehend für neue Seiten und Portfolios.
Wenn das vorbei ist: App „stadtwuppertal engine“ → Instagram API → Business-Portfolio verbinden →
mit @stadtwuppertal anmelden → Schlüssel in die Notiz als `IG_TOKEN=…` → Secret aktualisieren.
Ab da postet die Engine selbst.

## Im Alltag
- Telegram: **passt / weg** · `stopp` · `weiter` · `status` · `regel: …` (neue Redaktionsregel)
- Instagram-Einstellungen: **Verborgene Wörter** an · Nachrichten → Verbundene Tools → **Zugriff auf Nachrichten erlauben**
- Bio-Vorschlag: „ein tal, ein fluss, ein schwebebus. · dein foto? schick's per DM · markier uns“
- Hashtag-Scout (#meinwuppertal): braucht später einmal Metas Freigabe, siehe `APP_REVIEW.md`
