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

    def preview(self, jpeg: bytes, text: str, item_id: str, buttons=(("passt", "ok"), ("weg", "no"))):
        kb = {"inline_keyboard": [[{"text": t, "callback_data": f"{code}:{item_id}"} for t, code in buttons]]}
        if not self.live or not self.chat:
            self.outbox.append(("preview", item_id, text))
            return "dry"
        res = self._call("sendPhoto", chat_id=self.chat, caption=text[:1024], reply_markup=json.dumps(kb),
                         files={"photo": ("vorschau.jpg", jpeg, "image/jpeg")})
        return str(res["message_id"])

    def album(self, jpegs: list[bytes], text: str):
        """Mehrere Bilder als Info (ohne Knöpfe), z. B. ein gerade gepostetes Karussell."""
        if not self.live or not self.chat:
            self.outbox.append(("album", len(jpegs), text))
            return
        media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(jpegs[:10]))]
        media[0]["caption"] = text[:1024]
        files = {f"p{i}": (f"p{i}.jpg", j, "image/jpeg") for i, j in enumerate(jpegs[:10])}
        self._call("sendMediaGroup", chat_id=self.chat, media=json.dumps(media), files=files)

    def mark(self, message_id: str, note: str):
        if self.live and self.chat and message_id and message_id != "dry":
            try:
                self._call("editMessageReplyMarkup", chat_id=self.chat, message_id=message_id,
                           reply_markup=json.dumps({"inline_keyboard": [[{"text": note, "callback_data": "x:x"}]]}))
            except Exception:
                pass

    # ── Empfangen ───────────────────────────────────────────
    def poll(self) -> list[dict]:
        """Liefert [{type: decision|command, …}] und merkt sich, was schon gelesen ist."""
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
                self.say("verbunden. ab jetzt kommen hier vorschauen, berichte und alarme.\n"
                         "befehle: stopp · weiter · status · regel: … (neue redaktionsregel)")
                continue
            if chat != str(self.chat):
                continue
            raw = (m.get("text") or "").strip()
            if text.startswith("regel"):
                rule = raw.split(":", 1)[1] if ":" in raw else raw[5:]
                if rule.strip():
                    out.append({"type": "command", "cmd": "regel", "text": rule.strip()})
                continue
            for cmd in ("stopp", "weiter", "status"):
                if text.lstrip("/").startswith(cmd):
                    out.append({"type": "command", "cmd": cmd})
        return out
