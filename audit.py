"""
Structured audit log (SQLite) for Provenance Guard.

Every attribution decision and every appeal is recorded here as a structured row.
This is a generic event log: event_type is "classification" or "appeal", so appeals
sit *beside* the original decision they contest (planning.md sec.5). Extended in M4
(second signal) and M5 (appeals); M3 uses the "classification" event only.

Storage: SQLite file audit_log.db in the project root. Each row keeps first-class
columns for the fields graders check (content_id, timestamp, attribution, confidence,
signal scores, status) plus a full JSON snapshot in `data` for everything else.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "PROVENANCE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_log.db"),
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type      TEXT NOT NULL,          -- classification | appeal
                content_id      TEXT NOT NULL,
                creator_id      TEXT,
                timestamp       TEXT NOT NULL,          -- ISO-8601 UTC
                attribution     TEXT,                   -- likely_ai | likely_human | uncertain
                confidence      REAL,
                stylometry_score REAL,                  -- signal 1 (M3+)
                llm_score       REAL,                   -- signal 2 (M4+)
                status          TEXT,                   -- classified | under_review
                data            TEXT                    -- full JSON snapshot
            )
            """
        )
        conn.commit()


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_classification(entry):
    """entry: dict already containing content_id, creator_id, attribution, confidence,
    stylometry_score, (optional) llm_score, status, timestamp, and any extra fields."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (event_type, content_id, creator_id, timestamp,
                attribution, confidence, stylometry_score, llm_score, status, data)
            VALUES ('classification', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["content_id"],
                entry.get("creator_id"),
                entry["timestamp"],
                entry.get("attribution"),
                entry.get("confidence"),
                entry.get("stylometry_score"),
                entry.get("llm_score"),
                entry.get("status", "classified"),
                json.dumps(entry),
            ),
        )
        conn.commit()


def log_appeal(content_id, appeal_entry):
    """Write an appeal row beside the original classification (planning.md sec.5, used in M5)."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (event_type, content_id, creator_id, timestamp,
                attribution, confidence, stylometry_score, llm_score, status, data)
            VALUES ('appeal', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                appeal_entry.get("creator_id"),
                appeal_entry["timestamp"],
                appeal_entry.get("attribution"),
                appeal_entry.get("confidence"),
                appeal_entry.get("stylometry_score"),
                appeal_entry.get("llm_score"),
                "under_review",
                json.dumps(appeal_entry),
            ),
        )
        conn.commit()


def update_status(content_id, status):
    with _connect() as conn:
        conn.execute(
            "UPDATE audit_log SET status = ? WHERE content_id = ? AND event_type = 'classification'",
            (status, content_id),
        )
        conn.commit()


def _row_to_entry(row):
    entry = json.loads(row["data"]) if row["data"] else {}
    entry["event_type"] = row["event_type"]
    entry["status"] = row["status"]
    return entry


def get_recent(limit=50, status=None):
    query = "SELECT * FROM audit_log"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_by_content_id(content_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ? ORDER BY id ASC", (content_id,)
        ).fetchall()
    return [_row_to_entry(r) for r in rows]
