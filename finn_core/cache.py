"""Small local cache. Keyed so a later Supabase store can use the same calls."""

import json
import sqlite3
from pathlib import Path


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
