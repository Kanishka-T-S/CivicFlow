"""SQLite persistence for confirmed civic complaints."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


COMPLAINT_CATEGORIES = (
    "Road Damage",
    "Water Supply",
    "Garbage Collection",
    "Street Light",
    "Drainage",
    "Electricity",
    "Public Sanitation",
    "Other",
)
COMPLAINT_STATUSES = ("Pending", "In Progress", "Resolved", "Rejected")
SCHEMA_VERSION = 1


def hash_tracking_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def new_tracking_code() -> str:
    return secrets.token_urlsafe(32)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ComplaintRepository:
    def __init__(self, database_path: str | Path) -> None:
        configured_path = str(database_path)
        self._uri = configured_path == ":memory:"
        self._anchor: Optional[sqlite3.Connection] = None
        if self._uri:
            self.database_path = (
                f"file:civicflow-{uuid.uuid4().hex}?mode=memory&cache=shared"
            )
            self._anchor = sqlite3.connect(
                self.database_path, uri=True, check_same_thread=False
            )
        else:
            self.database_path = str(Path(configured_path).expanduser())
            Path(self.database_path).resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.database_path, timeout=5, uri=self._uri
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS complaints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    complaint_id TEXT NOT NULL UNIQUE,
                    source_request_id TEXT NOT NULL UNIQUE,
                    citizen_token_hash TEXT NOT NULL,
                    category TEXT NOT NULL CHECK (
                        category IN (
                            'Road Damage', 'Water Supply', 'Garbage Collection',
                            'Street Light', 'Drainage', 'Electricity',
                            'Public Sanitation', 'Other'
                        )
                    ),
                    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
                    location TEXT NOT NULL CHECK (length(trim(location)) > 0),
                    submitted_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('Pending', 'In Progress', 'Resolved', 'Rejected')
                    ),
                    last_updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS complaint_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    complaint_db_id INTEGER NOT NULL
                        REFERENCES complaints(id) ON DELETE CASCADE,
                    previous_status TEXT,
                    new_status TEXT NOT NULL CHECK (
                        new_status IN ('Pending', 'In Progress', 'Resolved', 'Rejected')
                    ),
                    updated_at TEXT NOT NULL,
                    remarks TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_complaints_category
                    ON complaints(category);
                CREATE INDEX IF NOT EXISTS idx_complaints_status
                    ON complaints(status);
                CREATE INDEX IF NOT EXISTS idx_complaints_submitted_at
                    ON complaints(submitted_at);
                CREATE INDEX IF NOT EXISTS idx_complaints_citizen_token
                    ON complaints(citizen_token_hash);
                CREATE INDEX IF NOT EXISTS idx_complaint_updates_complaint
                    ON complaint_updates(complaint_db_id, id);
                """
            )
            if version < SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _complaint_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "complaint_id": row["complaint_id"],
            "category": row["category"],
            "description": row["description"],
            "location": row["location"],
            "submitted_at": row["submitted_at"],
            "status": row["status"],
            "last_updated_at": row["last_updated_at"],
        }

    @staticmethod
    def _update_dict(row: sqlite3.Row) -> dict[str, object]:
        return {
            "previous_status": row["previous_status"],
            "new_status": row["new_status"],
            "updated_at": row["updated_at"],
            "remarks": row["remarks"],
            "updated_by": row["updated_by"],
        }

    def register(
        self,
        *,
        source_request_id: str,
        citizen_token_hash: str,
        category: str,
        description: str,
        location: str,
    ) -> tuple[dict[str, object], bool]:
        """Create a complaint once per workflow request and return it with a created flag."""
        now = utc_timestamp()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM complaints WHERE source_request_id = ?",
                (source_request_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return self._complaint_dict(existing), False

            complaint_id = f"CF-{secrets.token_hex(8).upper()}"
            cursor = connection.execute(
                """
                INSERT INTO complaints (
                    complaint_id, source_request_id, citizen_token_hash, category,
                    description, location, submitted_at, status, last_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
                """,
                (
                    complaint_id,
                    source_request_id,
                    citizen_token_hash,
                    category,
                    description,
                    location,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO complaint_updates (
                    complaint_db_id, previous_status, new_status, updated_at,
                    remarks, updated_by
                ) VALUES (?, NULL, 'Pending', ?, 'Complaint submitted', 'citizen')
                """,
                (cursor.lastrowid, now),
            )
            row = connection.execute(
                "SELECT * FROM complaints WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.commit()
            return self._complaint_dict(row), True

    def list_for_citizen(self, citizen_token_hash: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM complaints
                WHERE citizen_token_hash = ?
                ORDER BY submitted_at DESC, id DESC
                """,
                (citizen_token_hash,),
            ).fetchall()
        return [self._complaint_dict(row) for row in rows]

    def has_citizen_token(self, citizen_token_hash: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM complaints WHERE citizen_token_hash = ? LIMIT 1",
                (citizen_token_hash,),
            ).fetchone()
        return row is not None

    def get_for_citizen(
        self, complaint_id: str, citizen_token_hash: str
    ) -> Optional[dict[str, object]]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM complaints
                WHERE complaint_id = ? AND citizen_token_hash = ?
                """,
                (complaint_id, citizen_token_hash),
            ).fetchone()
        return self._complaint_dict(row) if row is not None else None

    def get(self, complaint_id: str) -> Optional[dict[str, object]]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?",
                (complaint_id,),
            ).fetchone()
        return self._complaint_dict(row) if row is not None else None

    def list_all(
        self,
        *,
        search: str = "",
        category: str = "",
        status: str = "",
    ) -> list[dict[str, object]]:
        clauses = []
        values: list[str] = []
        if search:
            clauses.append("complaint_id LIKE ? ESCAPE '\\'")
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        if category:
            clauses.append("category = ?")
            values.append(category)
        if status:
            clauses.append("status = ?")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM complaints {where}
                ORDER BY submitted_at DESC, id DESC
                """,
                values,
            ).fetchall()
        return [self._complaint_dict(row) for row in rows]

    def history(self, complaint_id: str) -> Optional[list[dict[str, object]]]:
        with self._connection() as connection:
            complaint = connection.execute(
                "SELECT id FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()
            if complaint is None:
                return None
            rows = connection.execute(
                """
                SELECT previous_status, new_status, updated_at, remarks, updated_by
                FROM complaint_updates
                WHERE complaint_db_id = ?
                ORDER BY id ASC
                """,
                (complaint["id"],),
            ).fetchall()
        return [self._update_dict(row) for row in rows]

    def update_status(
        self,
        *,
        complaint_id: str,
        new_status: str,
        remarks: str,
        updated_by: str,
    ) -> Optional[dict[str, object]]:
        now = utc_timestamp()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            previous_status = str(row["status"])
            connection.execute(
                """
                UPDATE complaints
                SET status = ?, last_updated_at = ?
                WHERE id = ?
                """,
                (new_status, now, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO complaint_updates (
                    complaint_db_id, previous_status, new_status, updated_at,
                    remarks, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row["id"], previous_status, new_status, now, remarks, updated_by),
            )
            updated = connection.execute(
                "SELECT * FROM complaints WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.commit()
        return self._complaint_dict(updated)
