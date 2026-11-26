"""Telegram: Vorschau mit Knöpfen schicken, Tipps und Befehle einsammeln.

Der Bot verbindet sich mit dem ersten Chat, der ihm /start schreibt, und hört danach nur noch auf diesen.
Befehle: stopp · weiter · status · regel: <text>
"""
from __future__ import annotations

import json

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str | None, state: dict, http=requests, dry=False):
        self.token, self.st, self.http = token, state, http
        self.live = bool(token) and not dry
        self.outbox = []          # Trockenlauf: was geschickt worden wäre

    @property
    def chat(self):
        return self.st.get("chat_id")

    def _call(self, method, files=None, **data):
        r = self.http.post(API.format(token=self.token, method=method), data=data, files=files, timeout=60)
        r.raise_for_status()
        return r.json()["result"]

    # ── Senden ──────────────────────────────────────────────
    def say(self, text: str):
        if not self.live or not self.chat:
            self.outbox.append(("text", text))
            return None
        return self._call("sendMessage", chat_id=self.chat, text=text[:4000], disable_web_page_preview="true")

    def preview(self, jpeg: bytes, text: str, item_id: str, buttons=(("Passt", "ok"), ("Weg damit", "no"))):
        kb = {"inline_keyboard": [[{"text": t, "callback_data": f"{code}:{item_id}"} for t, code in buttons]]}
        if not self.live or not self.chat:
            self.outbox.append(("preview", item_id, text))
            return "dry"
        res = self._call("sendPhoto", chat_id=self.chat, caption=text[:1024], reply_markup=json.dumps(kb),
                         files={"photo": ("vorschau.jpg", jpeg, "image/jpeg")})
        return str(res["message_id"])

    def photo(self, jpeg: bytes, text: str):
        """Ein Bild mit Text, ohne Knöpfe. Langer Text geht als zweite Nachricht hinterher."""
        if not self.live or not self.chat:
            self.outbox.append(("photo", text))
            return
        self._call("sendPhoto", chat_id=self.chat, caption=text[:1024],
                   files={"photo": ("kontrolle.jpg", jpeg, "image/jpeg")})
        if len(text) > 1024:
            self.say(text[1024:])

    def album(self, jpegs: list[bytes], text: str):
        """Mehrere Bilder als Info (ohne Knöpfe), z. B. ein gerade gepostetes Karussell."""
        if not self.live or not self.chat:
            self.outbox.append(("album", len(jpegs), text))
            return
        media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(jpegs[:10]))]
        media[0]["caption"] = text[:1024]
        files = {f"p{i}": (f"p{i}.jpg", j, "image/jpeg") for i, j in enumerate(jpegs[:10])}
        res = self._call("sendMediaGroup", chat_id=self.chat, media=json.dumps(media), files=files)
        return [str(m.get("message_id")) for m in (res or []) if isinstance(m, dict)]

    def video(self, data: bytes, caption: str = ""):
        if not self.live or not self.chat:
            self.outbox.append(("video", caption))
            return None
        try:
            r = self._call("sendVideo", chat_id=self.chat, caption=caption[:1024],
                           files={"video": ("cover.mp4", data, "video/mp4")})
            return str((r or {}).get("message_id", ""))
        except Exception:      # noqa: BLE001
            return None

    def handover(self, urls: list[str], kind: str, caption: str):
        """Übergabe-Modus (Instagram noch nicht verbunden): fertiger Post zum selbst Hochladen.
        Erst die Datei(en) zum Speichern, dann der Text als eigene Nachricht zum Kopieren."""
        what = {"story": "story", "reel": "reel", "feed": "post" if len(urls) == 1 else "karussell"}.get(kind, kind)
        if not self.live or not self.chat:
            self.outbox.append(("handover", what, len(urls), caption))
            return
        head = f"📦 Fertiger {what} zum Posten: Datei speichern und auf Instagram hochladen. Der Text kommt in der nächsten Nachricht."
        if kind == "reel":
            self._call("sendVideo", chat_id=self.chat, video=urls[0], caption=head)
        elif len(urls) == 1:
            self._call("sendPhoto", chat_id=self.chat, photo=urls[0], caption=head)
        else:
            media = [{"type": "photo", "media": u} for u in urls[:10]]
            media[0]["caption"] = head
            self._call("sendMediaGroup", chat_id=self.chat, media=json.dumps(media))
        if caption.strip():
            self._call("sendMessage", chat_id=self.chat, text=caption[:4000], disable_web_page_preview="true")

    def mark(self, message_id: str, note: str):
        if self.live and self.chat and message_id and message_id != "dry":
            try:
                self._call("editMessageReplyMarkup", chat_id=self.chat, message_id=message_id,
                           reply_markup=json.dumps({"inline_keyboard": [[{"text": note, "callback_data": "x:x"}]]}))
            except Exception:
                pass

    # ── Empfangen ───────────────────────────────────────────
    def waiting(self, seconds: int = 25) -> bool:
        """Wartet bis zu `seconds` auf eine neue Nachricht (Long-Polling), ohne sie als gelesen zu markieren."""
        if not self.live:
            return False
        try:
            r = self.http.post(API.format(token=self.token, method="getUpdates"), timeout=seconds + 15,
                               data={"offset": self.st.get("tg_offset", 0), "timeout": seconds, "limit": 1,
                                     "allowed_updates": json.dumps(["message", "callback_query"])})
            return bool(r.json().get("result"))
        except Exception:      # noqa: BLE001 – Netz hakt: kurz warten statt Dauerschleife
            import time
            time.sleep(min(seconds, 20))
            return False

    def poll(self) -> list[dict]:
        """Liefert [{type: decision|command, …}] und merkt sich, was schon gelesen ist."""
        inj = getattr(self, "_inject", None)
        if inj:                     # Befehl, der aus einem normalen Satz verstanden wurde
            self._inject = None
            return inj
        if not self.live:
            return []
        upd = self._call("getUpdates", offset=self.st.get("tg_offset", 0), timeout=0,
                         allowed_updates=json.dumps(["message", "callback_query"]))
        out = []
        for u in upd:
            self.st["tg_offset"] = u["update_id"] + 1
            if "callback_query" in u:
                cq = u["callback_query"]
                chat = str(cq.get("message", {}).get("chat", {}).get("id"))
                try:
                    self._call("answerCallbackQuery", callback_query_id=cq["id"], text="angekommen")
                except Exception:
                    pass
                if chat == str(self.chat) and ":" in cq.get("data", ""):
                    code, item = cq["data"].split(":", 1)
                    out.append({"type": "decision", "code": code, "item": item})
                continue
            m = u.get("message") or {}
            chat = str(m.get("chat", {}).get("id", ""))
            text = (m.get("text") or "").strip().lower()
            if not self.chat and text.startswith("/start"):
                self.st["chat_id"] = chat
                self.say("Verbunden. Hier kommen Vorschauen, Berichte und Meldungen.\n"
                         "Schreib mir ganz normal: Ideen, Fragen oder was ich tun soll. Kurzbefehle: stopp · weiter · "
                         "status · ideen · verworfen · regel: …\nKritik an einer Vorschau: einfach darauf antworten.")
                continue
            if chat != str(self.chat):
                continue
            raw = (m.get("text") or "").strip()
            if text.startswith("regel"):
                rule = raw.split(":", 1)[1] if ":" in raw else raw[5:]
                if rule.strip():
                    out.append({"type": "command", "cmd": "regel", "text": rule.strip()})
                continue
            hit = False
            for cmd in ("stopp", "weiter", "status", "ideen", "vorbild", "tipps", "verworfen", "jetzt", "neu", "details"):
                if text.lstrip("/").strip(" .!?") == cmd:      # nur das Wort allein; ganze Sätze versteht die Engine
                    out.append({"type": "command", "cmd": cmd})
                    hit = True
            if hit or text.startswith("/"):
                continue
            voice = m.get("voice") or m.get("audio")
            reply = (m.get("reply_to_message") or {}).get("message_id")
            pic = (m.get("photo") or [None])[-1] or (m.get("document") if str((m.get("document") or {}).get("mime_type", "")).startswith("image/") else None)
            if reply and pic:            # Foto als Antwort auf eine Vorschau = dieses Bild nehmen
                out.append({"type": "revise", "msg": str(reply), "text": (m.get("caption") or "").strip(),
                            "photo_id": pic["file_id"], "file_id": None})
                continue
            if reply and (raw or voice):
                out.append({"type": "revise", "msg": str(reply), "text": raw,
                            "file_id": voice["file_id"] if voice else None})
            elif voice:
                out.append({"type": "voice", "file_id": voice["file_id"]})
            elif raw:
                out.append({"type": "idea", "text": raw.split(":", 1)[1].strip() if text.startswith("idee:") else raw})
        return out

    def download(self, file_id: str) -> bytes:
        info = self._call("getFile", file_id=file_id)
        r = self.http.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=120)
        r.raise_for_status()
        return r.content
