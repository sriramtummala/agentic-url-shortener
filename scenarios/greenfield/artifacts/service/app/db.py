"""SQLite persistence for short URLs.

Opens and closes a connection per call rather than pooling one -- simple and
safe under FastAPI's sync-endpoint threadpool for this prototype's scale.
Documented trade-off, not an oversight: see docs/testing_and_tradeoffs.md.
"""

import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls (
    code TEXT PRIMARY KEY,
    destination_url TEXT NOT NULL,
    owner_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def code_exists(self, code: str) -> bool:
        conn = self._connect()
        try:
            return conn.execute("SELECT 1 FROM urls WHERE code = ?", (code,)).fetchone() is not None
        finally:
            conn.close()

    def insert_url(
        self, code: str, destination_url: str, owner_token: str, created_at: str,
        expires_at: Optional[str],
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO urls (code, destination_url, owner_token, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (code, destination_url, owner_token, created_at, expires_at),
            )
            conn.commit()
        finally:
            conn.close()

    def get_url(self, code: str) -> Optional[sqlite3.Row]:
        conn = self._connect()
        try:
            return conn.execute("SELECT * FROM urls WHERE code = ?", (code,)).fetchone()
        finally:
            conn.close()

    def delete_url(self, code: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM urls WHERE code = ?", (code,))
            conn.commit()
        finally:
            conn.close()
