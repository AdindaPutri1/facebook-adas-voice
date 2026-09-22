"""Deduplication.

Primary key per requirements:
    community + post_id + comment_id

Fallback when identifiers are missing: metadata + hash of text.
"""
import hashlib
import logging
from typing import Dict, List, Tuple

from src.models import RawRecord

log = logging.getLogger(__name__)


def dedup_key(record) -> str:
    """Return the canonical dedup key string."""
    base = f"{record.community}::{record.post_id}"
    if record.comment_id:
        base += f"::{record.comment_id}"
    elif record.source_type == "post":
        base += "::post"
    base += f"::{record.source_type}"
    return base


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deduplicate(records: List[Dict], state=None) -> Tuple[List[Dict], int, int]:
    """Return (unique_records, duplicate_count, skipped_existing_count).

    - duplicate_count: records that collide within the current batch
    - skipped_existing_count: records already present in the state db
    """
    seen = set()
    unique: List[Dict] = []
    duplicates = 0
    skipped = 0

    for rec in records:
        key = dedup_key(rec)
        if key in seen:
            duplicates += 1
            continue
        if state is not None and state.is_seen(rec.record_id):
            skipped += 1
            continue
        seen.add(key)
        if state is not None:
            state.record_seen(rec.record_id, rec.community, content_hash(rec.text_raw))
        unique.append(rec)

    return unique, duplicates, skipped