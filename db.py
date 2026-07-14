"""
SQLite-backed tracking of which messages/videos have already been
handled. This is what makes the downloader safely resumable: if the
script is interrupted (Ctrl+C, crash, power loss, flood wait that you
choose to abort during, etc.) you can re-run it and it will skip
everything already completed and only continue with what's left.
"""

import sqlite3
from datetime import datetime, timezone

import config


def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            message_id INTEGER NOT NULL,
            channel    TEXT NOT NULL,
            filename   TEXT,
            media_type TEXT,            -- 'photo', 'video', 'document'
            size_bytes INTEGER,
            status     TEXT NOT NULL,   -- 'done', 'failed', 'skipped'
            updated_at TEXT NOT NULL,
            PRIMARY KEY (message_id, channel)
        )
        """
    )
    # Backfill media_type column for DBs created before this field existed.
    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(downloads)").fetchall()]
    if "media_type" not in existing_cols:
        conn.execute("ALTER TABLE downloads ADD COLUMN media_type TEXT")
    conn.commit()
    return conn


def is_processed(conn, channel, message_id):
    """Returns True if this message was already downloaded successfully."""
    row = conn.execute(
        "SELECT status FROM downloads WHERE message_id = ? AND channel = ?",
        (message_id, channel),
    ).fetchone()
    return row is not None and row[0] == "done"


def mark_status(conn, channel, message_id, status, filename=None, size_bytes=None, media_type=None):
    conn.execute(
        """
        INSERT INTO downloads (message_id, channel, filename, media_type, size_bytes, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id, channel) DO UPDATE SET
            filename=excluded.filename,
            media_type=excluded.media_type,
            size_bytes=excluded.size_bytes,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (message_id, channel, filename, media_type, size_bytes, status, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_stats(conn, channel):
    rows = conn.execute(
        "SELECT status, COUNT(*), COALESCE(SUM(size_bytes), 0) FROM downloads WHERE channel = ? GROUP BY status",
        (channel,),
    ).fetchall()
    stats = {"done": 0, "failed": 0, "skipped": 0, "total_bytes": 0, "by_type": {}}
    for status, count, total_bytes in rows:
        stats[status] = count
        if status == "done":
            stats["total_bytes"] = total_bytes

    type_rows = conn.execute(
        "SELECT media_type, COUNT(*) FROM downloads WHERE channel = ? AND status = 'done' GROUP BY media_type",
        (channel,),
    ).fetchall()
    for media_type, count in type_rows:
        stats["by_type"][media_type or "unknown"] = count
    return stats


def list_failed(conn, channel):
    rows = conn.execute(
        "SELECT message_id FROM downloads WHERE channel = ? AND status = 'failed'",
        (channel,),
    ).fetchall()
    return [r[0] for r in rows]