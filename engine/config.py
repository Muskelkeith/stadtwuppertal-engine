"""Einstellungen (config.yaml) und Zugangsdaten.

Zugangsdaten kommen aus EINEM GitHub-Secret namens ENGINE_SECRETS, Zeile für Zeile:
    TELEGRAM_TOKEN=…
    IG_TOKEN=…
    CLAUDE_CODE_OAUTH_TOKEN=…
Bilder und Gedächtnis liegen in GitHub selbst (siehe gitstore.py) – kein Webspace nötig.
Einzelne Umgebungsvariablen mit gleichem Namen gehen auch (für lokale Tests).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["IG_TOKEN", "TELEGRAM_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "STATE_KEY",
        "FTP_HOST", "FTP_USER", "FTP_PASS", "FTP_DIR", "PUBLIC_URL"]


@dataclass
class Secrets:
    values: dict = field(default_factory=dict)

    def __getattr__(self, k):
        return self.__dict__["values"].get(k.upper()) or None

    def missing(self, needed=("TELEGRAM_TOKEN",)):   # ohne IG_TOKEN läuft die Übergabe per Telegram
        llm = self.values.get("CLAUDE_CODE_OAUTH_TOKEN") or self.values.get("ANTHROPIC_API_KEY")
        return [k for k in needed if not self.values.get(k)] + ([] if llm else ["CLAUDE_CODE_OAUTH_TOKEN"])


def load_secrets(env=os.environ) -> Secrets:
    vals, last = {}, None
    for line in (env.get("ENGINE_SECRETS") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k = line.split("=", 1)[0].strip().upper() if "=" in line else ""
        if k and re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
            v = line.split("=", 1)[1]
            last = k
        elif last:                      # umgebrochener Schlüssel: Rest gehört zur Zeile davor
            k, v = last, vals[last] + line
        else:
            continue
        vals[k] = re.sub(r"\s+", "", v).strip('"').strip("'")
    for k in KEYS:
        if env.get(k):
            vals[k] = env[k]
    return Secrets(vals)


def load_config(path: Path | None = None) -> dict:
    cfg = yaml.safe_load((path or ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["_root"] = str(ROOT)
    return cfg
