"""Sprachnachrichten aus Telegram in Text verwandeln – kostenlos, direkt im GitHub-Lauf (faster-whisper, CPU)."""
from __future__ import annotations

import tempfile

_model = None


def transcribe(data: bytes, suffix: str = ".ogg") -> str:
    global _model
    from faster_whisper import WhisperModel      # erst laden, wenn wirklich eine Sprachnachricht da ist
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        segments, _ = _model.transcribe(f.name, language="de", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
