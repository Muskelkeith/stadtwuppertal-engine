"""Ablage komplett in GitHub – kein eigener Webspace, keine Domain, kein Name.

- Bilder/Videos: Branch `gh-pages`, öffentlich über GitHub Pages (https://<konto>.github.io/<repo>/m/…).
  Instagram holt sie dort ab. Es bleiben nur die letzten 3 Tage liegen; der Branch wird jedes Mal neu
  geschrieben, damit das Repository nicht wächst.
- Gedächtnis: Branch `daten`, eine verschlüsselte Datei. Ohne Schlüssel (aus den Secrets) unlesbar.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken

KEEP_DAYS = 3


def fernet_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(("stadtwuppertal-state|" + secret).encode()).digest())


class GitStore:
    def __init__(self, repo: str, token: str, key_material: str, pages_dir: Path | None = None,
                 remote: str | None = None, public: str | None = None, wait_public=True):
        self.repo = repo
        self.remote = remote or f"https://x-access-token:{token}@github.com/{repo}.git"
        owner, name = repo.split("/")
        self.public = (public or f"https://{owner.lower()}.github.io/{name}").rstrip("/")
        self.token = token
        self.f = Fernet(fernet_key(key_material))
        self.pages_dir = pages_dir
        self.wait_public = wait_public
        self.local = False
        self.data: dict[str, bytes] = {}
        self.dirty = False
        self.pending: dict[str, bytes] = {}
        self.fresh: list[str] = []
        self._load()

    # ── git ─────────────────────────────────────────────────
    def _git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)

    def _clone(self, branch: str) -> Path | None:
        d = Path(tempfile.mkdtemp())
        r = self._git("clone", "-q", "--depth", "1", "--branch", branch, self.remote, str(d), check=False)
        if r.returncode != 0:
            shutil.rmtree(d, ignore_errors=True)
            return None
        return d

    def _push_orphan(self, branch: str, files: dict[str, bytes], msg: str):
        d = Path(tempfile.mkdtemp())
        self._git("init", "-q", "-b", branch, cwd=d)
        for rel, data in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self._git("add", "-A", cwd=d)
        self._git("-c", "user.name=stadtwuppertal-engine", "-c", "user.email=engine@users.noreply.github.com",
                  "commit", "-q", "-m", msg, cwd=d)
        self._git("push", "-q", "-f", self.remote, f"{branch}:{branch}", cwd=d)
        shutil.rmtree(d, ignore_errors=True)

    # ── Gedächtnis ──────────────────────────────────────────
    def _load(self):
        d = self._clone("daten")
        if not d:
            return
        try:
            raw = self.f.decrypt((d / "engine.bin").read_bytes())
            self.data = {k: base64.b64decode(v) for k, v in json.loads(raw).items()}
        except (FileNotFoundError, InvalidToken):
            self.data = {}       # anderer Schlüssel → frisch anfangen
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def get(self, rel: str) -> bytes | None:
        return self.data.get(rel)

    def put(self, rel: str, data: bytes):
        self.data[rel] = data
        self.dirty = True

    def delete(self, rel: str):
        if self.data.pop(rel, None) is not None:
            self.dirty = True

    def list(self, rel_dir: str) -> list[str]:
        pre = rel_dir.rstrip("/") + "/"
        return sorted(k[len(pre):] for k in self.data if k.startswith(pre) and "/" not in k[len(pre):])

    def read_json(self, rel, default):
        raw = self.get(rel)
        return json.loads(raw) if raw else default

    def write_json(self, rel, data):
        self.put(rel, json.dumps(data, ensure_ascii=False).encode())

    # ── Medien ──────────────────────────────────────────────
    def media(self, name: str, data: bytes) -> str:
        self.pending[f"m/{name}"] = data
        self.fresh.append(f"{self.public}/m/{name}")
        return f"{self.public}/m/{name}"

    def flush_media(self):
        """Neue Dateien nach gh-pages schieben (alte > 3 Tage fliegen raus) und warten, bis sie öffentlich sind."""
        if not self.pending:
            return
        files = {}
        d = self._clone("gh-pages")
        cutoff = time.time() - KEEP_DAYS * 86400
        if d:
            for p in (d / "m").glob("*") if (d / "m").exists() else []:
                try:
                    if int(p.name.split("-")[0]) >= cutoff:
                        files[f"m/{p.name}"] = p.read_bytes()
                except ValueError:
                    pass
            shutil.rmtree(d, ignore_errors=True)
        if self.pages_dir and self.pages_dir.exists():
            for p in self.pages_dir.rglob("*"):
                if p.is_file():
                    files[str(p.relative_to(self.pages_dir))] = p.read_bytes()
        files[".nojekyll"] = b""
        files.update(self.pending)
        self._push_orphan("gh-pages", files, "medien")
        urls, self.pending, self.fresh = self.fresh, {}, []
        if self.wait_public:
            self.wait(urls)

    def wait(self, urls, max_s=300):
        start = time.time()
        for u in urls:
            while time.time() - start < max_s:
                try:
                    if requests.head(u, timeout=15).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(10)

    def ensure_pages(self):
        """Schaltet GitHub Pages für gh-pages ein, falls noch aus (braucht die Workflow-Berechtigung pages: write)."""
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}
        r = requests.get(f"https://api.github.com/repos/{self.repo}/pages", headers=h, timeout=30)
        if r.status_code == 200:
            return True
        r = requests.post(f"https://api.github.com/repos/{self.repo}/pages", headers=h, timeout=30,
                          json={"source": {"branch": "gh-pages", "path": "/"}})
        return r.status_code in (201, 409)

    def prune_media(self, keep_days=KEEP_DAYS):
        pass                     # passiert beim nächsten flush_media

    def ensure_layout(self, php_form=None):
        pass

    def close(self):
        self.flush_media()
        if self.dirty:
            blob = self.f.encrypt(json.dumps({k: base64.b64encode(v).decode() for k, v in self.data.items()}).encode())
            self._push_orphan("daten", {"engine.bin": blob, "LIESMICH.txt":
                                        "Verschlüsseltes Gedächtnis der stadtwuppertal-engine.\n".encode()}, "gedächtnis")
            self.dirty = False
