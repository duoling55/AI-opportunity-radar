from __future__ import annotations

import sqlite3
from pathlib import Path


class StateStore:
    """Persist the last successfully processed content hash for each policy."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS policies "
            "(policy_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, dedupe_key TEXT)"
        )
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(policies)")
        }
        if "dedupe_key" not in columns:
            self.connection.execute("ALTER TABLE policies ADD COLUMN dedupe_key TEXT")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS policies_dedupe_key ON policies(dedupe_key)"
        )

    def is_changed(
        self,
        policy_id: str,
        content_hash: str,
        dedupe_key: str | None = None,
    ) -> bool:
        if dedupe_key:
            row = self.connection.execute(
                "SELECT content_hash FROM policies "
                "WHERE policy_id = ? OR dedupe_key = ? "
                "ORDER BY CASE WHEN policy_id = ? THEN 0 ELSE 1 END LIMIT 1",
                (policy_id, dedupe_key, policy_id),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT content_hash FROM policies WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        return row is None or row[0] != content_hash

    def record_success(
        self,
        policy_id: str,
        content_hash: str,
        dedupe_key: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO policies(policy_id, content_hash, dedupe_key) VALUES (?, ?, ?) "
            "ON CONFLICT(policy_id) DO UPDATE SET "
            "content_hash=excluded.content_hash, dedupe_key=excluded.dedupe_key",
            (policy_id, content_hash, dedupe_key),
        )
        self.connection.commit()
