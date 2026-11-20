# Einrichtung – einmalig

Vier Bausteine, kein Webspace, keine Domain, nirgends ein Name.
Alles, was du einsammelst, kommt in **eine** Notiz. Am Ende fügst du sie einmal bei GitHub ein.

## 1 · Telegram-Bot (Handy, 2 Min.)
@BotFather → `/newbot` → Name `stadtwuppertal engine` → Benutzername z. B. `stadtwuppertal_engine_bot`
→ Schlüssel in die Notiz: `TELEGRAM_TOKEN=…` → beim neuen Bot **Starten** drücken.

## 2 · GitHub (Browser, 5 Min.)
Neues Konto mit neutraler E-Mail-Adresse, Benutzername `stadtwuppertal` (oder `talhaengt`).
Den Rest (Repository, Code, Pages) richtet Claude ein – du loggst dich nur ein.
Bilder liegen später unter `https://<konto>.github.io/stadtwuppertal-engine/…`, das Gedächtnis verschlüsselt im Repo.

## 3 · Instagram & Meta (Handy + Browser, 20 Min.)
1. Instagram → Kontotyp und Tools → professionelles Konto → **Unternehmen**, mit einer (fast leeren) Facebook-Seite verknüpfen
2. Einstellungen → **Verborgene Wörter** an · Nachrichten → Verbundene Tools → **Zugriff auf Nachrichten erlauben**
3. business.facebook.com: Portfolio mit Instagram + Seite · developers.facebook.com: App (Business) anlegen
4. Systemnutzer (Admin) → Assets zuweisen → Token, Ablauf **nie**, Berechtigungen:
   `instagram_basic, instagram_content_publish, instagram_manage_insights, instagram_manage_comments,
   instagram_manage_messages, pages_show_list, pages_read_engagement, pages_manage_metadata,
   pages_messaging, business_management` → Notiz: `IG_TOKEN=…`

## 4 · Claude-Zugang (Terminal am Mac, 3 Min.)
```
curl -fsSL https://claude.ai/install.sh | bash
claude setup-token
```
→ Notiz: `CLAUDE_CODE_OAUTH_TOKEN=…`

## Abschluss
Repository → Settings → Secrets and variables → Actions → New repository secret →
Name `ENGINE_SECRETS`, Wert: die ganze Notiz. Dann Actions → takt → Run workflow → `check`.

```
TELEGRAM_TOKEN=
IG_TOKEN=
CLAUDE_CODE_OAUTH_TOKEN=
```

## Im Alltag
- Telegram: **passt / weg** · `stopp` · `weiter` · `status` · `regel: …` (neue Redaktionsregel)
- Bild-Anfragen: Link tippen (öffnet die DM), Text tippen (kopiert), einfügen, senden – den Rest macht die Engine
- Bio-Vorschlag: „ein tal, ein fluss, ein schwebebus. · dein foto? schick's per DM · markier uns“
- Hashtag-Scout (#meinwuppertal): braucht einmal Metas Freigabe, siehe `APP_REVIEW.md`
