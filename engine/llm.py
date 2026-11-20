"""Claude über das eigene Abo: ruft die Claude-Code-Kommandozeile im Druckmodus auf
(CLAUDE_CODE_OAUTH_TOKEN). Ohne Token: Testmodus mit festen Antworten (stub)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess


def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise ValueError(f"Kein JSON in Antwort: {text[:300]}")
    return json.loads(m.group(0))


class LLM:
    def __init__(self, secrets, models: dict, stub=None):
        self.models = models
        self.env = dict(os.environ)
        if secrets.CLAUDE_CODE_OAUTH_TOKEN:
            self.env["CLAUDE_CODE_OAUTH_TOKEN"] = secrets.CLAUDE_CODE_OAUTH_TOKEN
        if secrets.ANTHROPIC_API_KEY:
            self.env["ANTHROPIC_API_KEY"] = secrets.ANTHROPIC_API_KEY
        self.live = bool(secrets.CLAUDE_CODE_OAUTH_TOKEN or secrets.ANTHROPIC_API_KEY) and stub is None
        self.stub = stub
        self.calls = 0

    def ask(self, task: str, system: str, prompt: str, tier="write"):
        """Gibt geparstes JSON zurück. task benennt den Auftrag (für den Testmodus)."""
        self.calls += 1
        if not self.live:
            if self.stub is None:
                raise RuntimeError("Kein Claude-Zugang (CLAUDE_CODE_OAUTH_TOKEN fehlt)")
            return self.stub(task, prompt)
        exe = shutil.which("claude") or "claude"
        cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--model", self.models.get(tier, "sonnet"),
               "--system-prompt", system]
        last = None
        for attempt in range(2):
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=self.env, timeout=420)
            try:
                outer = json.loads(r.stdout)
                if outer.get("is_error"):
                    raise RuntimeError(outer.get("result") or outer.get("terminal_reason"))
                return extract_json(outer.get("result", ""))
            except Exception as e:      # noqa: BLE001 – einmal neu versuchen, dann aufgeben
                last = f"{e} | {r.stderr[-300:]}"
        raise RuntimeError(f"Claude-Aufruf fehlgeschlagen ({task}): {last}")


def small_jpeg(img_bytes: bytes, side=1024) -> bytes:
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _ask_image(self, task: str, system: str, prompt: str, jpeg: bytes, tier="triage"):
    """Wie ask(), aber Claude sieht dazu ein Bild (Bildredaktion)."""
    import base64
    self.calls += 1
    if not self.live:
        if self.stub is None:
            raise RuntimeError("Kein Claude-Zugang")
        return self.stub(task, prompt)
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(small_jpeg(jpeg)).decode()}},
        {"type": "text", "text": prompt}]}}
    exe = shutil.which("claude") or "claude"
    cmd = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--tools", "", "--model", self.models.get(tier, "sonnet"), "--system-prompt", system]
    r = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True, env=self.env, timeout=300)
    for line in r.stdout.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "result":
            if obj.get("is_error"):
                raise RuntimeError(obj.get("result"))
            return extract_json(obj.get("result", ""))
    raise RuntimeError(f"Bildbewertung fehlgeschlagen: {r.stderr[-300:]}")


LLM.ask_image = _ask_image
