"""Lokale Ablage für Tests und Trockenläufe (Ordner local_store/). Im Betrieb nutzt die Engine gitstore.py."""
from __future__ import annotations

import json
from pathlib import Path


class Store:
    def __init__(self, secrets, local_dir: str | Path):
        self.local = True
        self.root = Path(local_dir)

    def get(self, rel: str) -> bytes | None:
        p = self.root / rel
        return p.read_bytes() if p.exists() else None

    def put(self, rel: str, data: bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def list(self, rel_dir: str) -> list[str]:
        p = self.root / rel_dir
        return sorted(x.name for x in p.iterdir()) if p.exists() else []

    def delete(self, rel: str):
        (self.root / rel).unlink(missing_ok=True)

    def read_json(self, rel, default):
        raw = self.get(rel)
        return json.loads(raw) if raw else default

    def write_json(self, rel, data):
        self.put(rel, json.dumps(data, ensure_ascii=False, indent=1).encode())

    def media(self, name: str, data: bytes) -> str:
        self.put(f"m/{name}", data)
        return (self.root / "m" / name).resolve().as_uri()

    def prune_media(self, keep_days=10):
        pass

    def close(self):
        pass
