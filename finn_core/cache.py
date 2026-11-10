"""Local sqlite cache, or Supabase when CACHE_BACKEND=supabase.

Extracted text, model outputs, and verdicts go to Supabase. Raw XBRL stays local.
Keys are read from the environment or .env and are never printed.

Create the table once in the Supabase SQL editor:

    create table if not exists public.cache_entries (
      key text primary key,
      kind text not null,
      symbol text not null,
      payload jsonb not null,
      created_at timestamptz not null default now()
    );

    alter table public.cache_entries enable row level security;
"""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import httpx

RAW_KINDS = {"xbrl_xml"}


class FileCache:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(".finn_cache") / "finn.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (source, symbol, start, end)
            )
            """
        )
        self._db.commit()

    def get(self, source: str, symbol: str, start: str, end: str):
        row = self._db.execute(
            "SELECT payload FROM cache WHERE source = ? AND symbol = ? AND start = ? AND end = ?",
            (source, symbol, start, end),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, source: str, symbol: str, start: str, end: str, payload) -> None:
        self._db.execute(
            """
            INSERT INTO cache (source, symbol, start, end, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source, symbol, start, end) DO UPDATE SET payload = excluded.payload
            """,
            (source, symbol, start, end, json.dumps(payload)),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()


class SupabaseCache:
    """cache_entries via the REST API. The secret key is a header, never a log line."""

    def __init__(self):
        self._base = _rest_base()
        self._key = _setting("SUPABASE_SECRET_KEY")
        if not self._base or not self._key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY are required")
        self._client = httpx.Client(timeout=60.0)

    def get(self, source: str, symbol: str, start: str, end: str):
        response = self._client.get(
            f"{self._base}/cache_entries",
            params={"key": f"eq.{_entry_key(source, symbol, start, end)}", "select": "payload"},
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise RuntimeError(_safe_status("cache read", response))
        rows = response.json()
        if not rows:
            return None
        return rows[0].get("payload")

    def put(self, source: str, symbol: str, start: str, end: str, payload) -> None:
        response = self._client.post(
            f"{self._base}/cache_entries",
            headers={**self._headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            json={
                "key": _entry_key(source, symbol, start, end),
                "kind": source,
                "symbol": symbol,
                "payload": payload,
            },
        )
        if response.status_code not in (200, 201, 204):
            raise RuntimeError(_safe_status("cache write", response))

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }


class HybridCache:
    """Supabase for text and model output. Raw XBRL stays in sqlite."""

    def __init__(self):
        self.local = FileCache()
        self.remote = SupabaseCache()

    @property
    def path(self) -> Path:
        """PDF bytes stay beside the local sqlite file. Supabase stores the extracted text."""
        return self.local.path

    def get(self, source: str, symbol: str, start: str, end: str):
        store = self.local if source in RAW_KINDS else self.remote
        return store.get(source, symbol, start, end)

    def put(self, source: str, symbol: str, start: str, end: str, payload) -> None:
        store = self.local if source in RAW_KINDS else self.remote
        store.put(source, symbol, start, end, payload)

    def close(self) -> None:
        self.local.close()
        self.remote.close()


def open_cache():
    """CACHE_BACKEND=supabase selects Supabase. Anything else is the local sqlite file."""
    if _setting("CACHE_BACKEND").lower() == "supabase":
        return HybridCache()
    return FileCache()


def _safe_status(action: str, response) -> str:
    """Status and the server message, with any URL or key removed."""
    message = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            message = str(body.get("message") or body.get("hint") or body.get("error") or "")
    except (json.JSONDecodeError, ValueError):
        message = ""
    message = re.sub(r"https?://\S+", "[url]", message)
    message = re.sub(r"sb_secret_\S+", "[key]", message)
    message = " ".join(message.split())
    if message:
        return f"{action} HTTP {response.status_code}: {message[:180]}"
    return f"{action} HTTP {response.status_code}"


def _entry_key(source: str, symbol: str, start: str, end: str) -> str:
    raw = "\n".join((source, symbol, start, end))
    return source + ":" + hashlib.sha256(raw.encode()).hexdigest()


def _rest_base() -> str:
    url = _setting("SUPABASE_URL").rstrip("/")
    if not url:
        return ""
    if url.endswith("/rest/v1"):
        return url
    return url + "/rest/v1"


def _setting(name: str) -> str:
    found = os.environ.get(name, "").strip().strip('"').strip("'")
    if found:
        return found
    for candidate in (Path(".env"), Path(__file__).resolve().parents[1] / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
