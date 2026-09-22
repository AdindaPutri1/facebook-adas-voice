import json
import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


class StateDB:
    """SQLite-backed checkpoint/resume state store."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    vehicle TEXT,
                    community TEXT,
                    data_source TEXT,
                    mode TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    config_version TEXT,
                    keyword_version TEXT,
                    taxonomy_version TEXT,
                    scraper_version TEXT,
                    records_collected INTEGER DEFAULT 0,
                    records_duplicated INTEGER DEFAULT 0,
                    records_skipped INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_posts (
                    run_id TEXT,
                    community TEXT,
                    post_id TEXT,
                    status TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    processed_at TEXT,
                    PRIMARY KEY (community, post_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_comments (
                    run_id TEXT,
                    community TEXT,
                    post_id TEXT,
                    comment_id TEXT,
                    status TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    processed_at TEXT,
                    PRIMARY KEY (community, post_id, comment_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_records (
                    record_id TEXT PRIMARY KEY,
                    community TEXT,
                    text_hash TEXT,
                    first_seen_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS community_discovery (
                    community_name TEXT PRIMARY KEY,
                    url TEXT,
                    vehicle TEXT,
                    type TEXT,
                    accessibility TEXT,
                    discovery_date TEXT,
                    notes TEXT
                )
                """
            )

    # ── runs ────────────────────────────────────────────────────────────────
    def start_run(self, run_id: str, meta: Dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, vehicle, community, data_source, mode, start_time,
                 config_version, keyword_version, taxonomy_version, scraper_version,
                 records_collected, records_duplicated, records_skipped, errors, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,0,0,0,0,'running')
                """,
                (
                    run_id,
                    meta.get("vehicle", ""),
                    meta.get("community", ""),
                    meta.get("data_source", ""),
                    meta.get("mode", ""),
                    meta.get("start_time", datetime.now(timezone.utc).isoformat()),
                    meta.get("config_version", ""),
                    meta.get("keyword_version", ""),
                    meta.get("taxonomy_version", ""),
                    meta.get("scraper_version", ""),
                ),
            )

    def finish_run(
        self,
        run_id: str,
        status: str = "completed",
        records_collected: int = 0,
        records_duplicated: int = 0,
        records_skipped: int = 0,
        errors: int = 0,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE runs SET end_time=?, status=?, records_collected=?,
                records_duplicated=?, records_skipped=?, errors=?
                WHERE run_id=?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    records_collected,
                    records_duplicated,
                    records_skipped,
                    errors,
                    run_id,
                ),
            )

    def list_runs(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY start_time DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── processed posts ─────────────────────────────────────────────────────
    def mark_post_processed(
        self,
        community: str,
        post_id: str,
        status: str,
        run_id: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO processed_posts
                (run_id, community, post_id, status, error_type, error_message,
                 retry_count, processed_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    community,
                    post_id,
                    status,
                    error_type,
                    error_message,
                    retry_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def post_status(self, community: str, post_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM processed_posts WHERE community=? AND post_id=?",
            (community, post_id),
        ).fetchone()
        return dict(row) if row else None

    def is_post_processed(self, community: str, post_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM processed_posts WHERE community=? AND post_id=?",
            (community, post_id),
        ).fetchone()
        return row is not None and row["status"] in ("done", "skipped")

    def mark_comment_processed(
        self,
        community: str,
        post_id: str,
        comment_id: str,
        status: str,
        run_id: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO processed_comments
                (run_id, community, post_id, comment_id, status, error_type,
                 error_message, retry_count, processed_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    community,
                    post_id,
                    comment_id,
                    status,
                    error_type,
                    error_message,
                    retry_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def comment_status(
        self, community: str, post_id: str, comment_id: str
    ) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM processed_comments WHERE community=? AND post_id=? AND comment_id=?",
            (community, post_id, comment_id),
        ).fetchone()
        return dict(row) if row else None

    def is_comment_processed(self, community: str, post_id: str, comment_id: str) -> bool:
        row = self._conn.execute(
            "SELECT status FROM processed_comments WHERE community=? AND post_id=? AND comment_id=?",
            (community, post_id, comment_id),
        ).fetchone()
        return row is not None and row["status"] in ("done", "skipped", "failed")

    # ── seen records (dedup across threads) ─────────────────────────────────
    def record_seen(self, record_id: str, community: str, text_hash: str) -> bool:
        """Returns True if newly inserted, False if already seen."""
        with self._conn:
            cur = self._conn.execute(
                "SELECT record_id FROM seen_records WHERE record_id=?",
                (record_id,),
            )
            existing = cur.fetchone()
            if existing:
                return False
            self._conn.execute(
                "INSERT OR IGNORE INTO seen_records (record_id, community, text_hash, first_seen_at) VALUES (?,?,?,?)",
                (record_id, community, text_hash, datetime.now(timezone.utc).isoformat()),
            )
            return True

    def is_seen(self, record_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_records WHERE record_id=?", (record_id,)
        ).fetchone()
        return row is not None

    # ── community discovery ─────────────────────────────────────────────────
    def upsert_discovery(self, discovery: Dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO community_discovery
                (community_name, url, vehicle, type, accessibility, discovery_date, notes)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    discovery.get("community_name", ""),
                    discovery.get("url", ""),
                    discovery.get("vehicle", ""),
                    discovery.get("type", ""),
                    discovery.get("accessibility", "unknown"),
                    discovery.get("discovery_date", datetime.now(timezone.utc).date().isoformat()),
                    discovery.get("notes", ""),
                ),
            )

    def list_discoveries(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM community_discovery ORDER BY discovery_date DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if self._conn:
            self._conn.close()


def load_run_meta(run_id: str, db_path: str) -> Optional[Dict[str, Any]]:
    db = StateDB(db_path)
    try:
        for row in db.list_runs():
            if row["run_id"] == run_id:
                return row
        return None
    finally:
        db.close()