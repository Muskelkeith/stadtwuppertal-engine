"""Sprachnachrichten aus Telegram in Text verwandeln – kostenlos, direkt im GitHub-Lauf (faster-whisper, CPU).

Großes Modell (large-v3-turbo) mit Wuppertal-Wortschatz, damit Ortsnamen und Dialekt nicht verhört werden.
Fällt auf „small“ zurück, falls das große Modell nicht lädt."""
from __future__ import annotations

import tempfile

_model = None
VOCAB = ("Wuppertal, Schwebebahn, Elberfeld, Barmen, Vohwinkel, Ronsdorf, Cronenberg, Langerfeld, Beyenburg, "
         "Oberbarmen, Unterbarmen, Ölberg, Luisenviertel, Arrenberg, Mirker Bahnhof, Utopiastadt, Nordbahntrasse, "
         "Döppersberg, Neumarkt, Von der Heydt, Toelleturm, Hardt, Kiesberg, Zoo-Stadion, WSV, WSW, Talzeit, "
         "Wuppertaler Rundschau, Pina Bausch, Engels, Bayer, Aspirin, Kaiserwagen, Wupper, Tal, watt, dat, hasse, ne, Reel, Post, Caption.")


def _load():
    global _model
    from faster_whisper import WhisperModel      # erst laden, wenn wirklich eine Sprachnachricht da ist
    for name in ("large-v3-turbo", "small"):
        try:
            _model = WhisperModel(name, device="cpu", compute_type="int8")
            return
        except Exception:      # noqa: BLE001
            continue
    raise RuntimeError("kein Spracherkennungs-Modell ladbar")


def transcribe(data: bytes, suffix: str = ".ogg") -> str:
    if _model is None:
        _load()
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        segments, _ = _model.transcribe(f.name, language="de", vad_filter=True, beam_size=5,
                                        initial_prompt=VOCAB, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()
