from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


DEFAULT_DB_PATH = Path("data/style_corpus.sqlite")


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site TEXT NOT NULL,
    post_url TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL CHECK (content_type IN ('post', 'comment')),
    text TEXT NOT NULL,
    clean_text TEXT NOT NULL,
    text_length INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    pii_masked_json TEXT NOT NULL DEFAULT '[]',
    safety_flags_json TEXT NOT NULL DEFAULT '[]',
    collected_at TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_source_site ON documents(source_site);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_collected_at ON documents(collected_at);

CREATE TABLE IF NOT EXISTS collection_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site TEXT NOT NULL,
    post_url TEXT NOT NULL,
    reason TEXT NOT NULL,
    logged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_site TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    discovered_at TEXT NOT NULL,
    fetched_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_queue_status ON crawl_queue(status);

CREATE TABLE IF NOT EXISTS style_profiles (
    profile_name TEXT PRIMARY KEY,
    document_count INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    prompt_rules_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class CorpusStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def upsert_document(self, raw_record: dict, clean_record: dict) -> int:
        now = _utc_now()
        text = str(raw_record.get("text", ""))
        clean_text = str(clean_record.get("text", ""))
        post_url = str(raw_record.get("post_url", ""))
        source_site = str(raw_record.get("source_site", ""))
        content_type = str(raw_record.get("content_type", "post"))
        content_hash = _hash_text(source_site, post_url, clean_text)
        pii_masked = list(raw_record.get("pii_masked_at_collection", [])) + list(clean_record.get("pii_masked", []))
        safety_flags = list(clean_record.get("safety_flags", []))

        cursor = self.connection.execute(
            """
            INSERT INTO documents (
                source_site, post_url, content_type, text, clean_text, text_length, content_hash,
                pii_masked_json, safety_flags_json, collected_at, processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_url) DO UPDATE SET
                text = excluded.text,
                clean_text = excluded.clean_text,
                text_length = excluded.text_length,
                content_hash = excluded.content_hash,
                pii_masked_json = excluded.pii_masked_json,
                safety_flags_json = excluded.safety_flags_json,
                processed_at = excluded.processed_at
            """,
            (
                source_site,
                post_url,
                content_type,
                text,
                clean_text,
                len(clean_text),
                content_hash,
                json.dumps(sorted(set(pii_masked)), ensure_ascii=False),
                json.dumps(sorted(set(safety_flags)), ensure_ascii=False),
                str(raw_record.get("collected_at") or now),
                now,
            ),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT id FROM documents WHERE post_url = ?", (post_url,)).fetchone()
        return int(row["id"] if row else cursor.lastrowid)

    def import_clean_records(self, records: Iterable[dict]) -> int:
        count = 0
        for record in records:
            text = str(record.get("text", ""))
            raw = {
                "source_site": record.get("source_site", ""),
                "post_url": record.get("post_url", f"import://record/{count}"),
                "content_type": record.get("content_type", "post"),
                "text": text,
                "text_length": len(text),
                "pii_masked_at_collection": record.get("pii_masked", []),
                "collected_at": _utc_now(),
            }
            self.upsert_document(raw, record)
            count += 1
        return count

    def iter_clean_records(self, limit: int | None = None) -> Iterator[dict]:
        query = """
            SELECT source_site, post_url, content_type, clean_text AS text, text_length
            FROM documents
            WHERE clean_text <> ''
            ORDER BY id
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        for row in self.connection.execute(query, params):
            yield dict(row)

    def count_documents(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
        return int(row["count"])

    def log_failure(self, source_site: str, post_url: str, reason: str) -> None:
        self.connection.execute(
            """
            INSERT INTO collection_failures (source_site, post_url, reason, logged_at)
            VALUES (?, ?, ?, ?)
            """,
            (source_site, post_url, reason, _utc_now()),
        )
        self.connection.commit()

    def enqueue_urls(self, source_site: str, urls: Iterable[str]) -> int:
        count = 0
        now = _utc_now()
        for url in urls:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO crawl_queue (source_site, url, discovered_at)
                VALUES (?, ?, ?)
                """,
                (source_site, url, now),
            )
            count += cursor.rowcount
        self.connection.commit()
        return count

    def save_style_profile(
        self,
        profile_name: str,
        document_count: int,
        features: dict,
        prompt_rules: dict,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO style_profiles (
                profile_name, document_count, features_json, prompt_rules_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_name) DO UPDATE SET
                document_count = excluded.document_count,
                features_json = excluded.features_json,
                prompt_rules_json = excluded.prompt_rules_json,
                updated_at = excluded.updated_at
            """,
            (
                profile_name,
                document_count,
                json.dumps(features, ensure_ascii=False),
                json.dumps(prompt_rules, ensure_ascii=False),
                _utc_now(),
            ),
        )
        self.connection.commit()

    def get_style_profile(self, profile_name: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM style_profiles WHERE profile_name = ?",
            (profile_name,),
        ).fetchone()
        if row is None:
            return None
        return {
            "profile_name": row["profile_name"],
            "document_count": row["document_count"],
            "features": json.loads(row["features_json"]),
            "prompt_rules": json.loads(row["prompt_rules_json"]),
            "updated_at": row["updated_at"],
        }


def _hash_text(source_site: str, post_url: str, text: str) -> str:
    payload = "\n".join([source_site, post_url, text]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
