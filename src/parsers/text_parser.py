"""Text parsing: converts raw collected dicts into RawRecord objects and
normalises relationship fields (post/comment/reply hierarchy)."""
import logging
from typing import Dict, List, Optional

from src.models import RawRecord, make_record_id
from src.collectors.base import (
    ParserError,
    UnexpectedPageStructureError,
)

log = logging.getLogger(__name__)


def parse_raw_item(item: Dict, community: Optional[Dict] = None) -> RawRecord:
    """Convert a raw collected dict into a validated RawRecord."""
    source_type = (item.get("source_type") or "post").strip().lower()
    if source_type not in ("post", "comment", "reply"):
        raise ParserError(f"Unknown source_type: {source_type}")

    text = (item.get("text") or "").strip()
    if not text:
        raise ParserError("Empty text in raw item")

    vehicle = item.get("vehicle") or (community or {}).get("vehicle") or "unknown"
    comm_name = item.get("community") or (community or {}).get("community_name") or "unknown"
    comm_url = item.get("community_url") or (community or {}).get("url") or ""
    post_id = str(item.get("post_id") or "").strip()
    if not post_id:
        raise ParserError("Missing post_id in raw item")

    comment_id = item.get("comment_id")
    parent_id = item.get("parent_id")
    if source_type in ("comment", "reply") and not comment_id:
        comment_id = f"{post_id}_auto_{abs(hash(text))%100000}"

    author_id = item.get("author_id") or item.get("author_pseudonym")
    date = item.get("date")
    url = item.get("url") or ""

    return RawRecord(
        vehicle=vehicle,
        community=comm_name,
        community_url=comm_url,
        post_id=post_id,
        comment_id=str(comment_id) if comment_id else None,
        parent_id=str(parent_id) if parent_id else None,
        source_type=source_type,
        author_id=author_id,
        author_pseudonym=item.get("author_pseudonym"),
        date=date,
        text_raw=text,
        url=url,
        scraped_at=item.get("scraped_at"),
    )


def validate_hierarchy(records: List[RawRecord]) -> List[str]:
    """Return list of warnings about dangling parent references."""
    warnings = []
    post_ids = {r.post_id for r in records if r.source_type == "post"}
    comment_keys = {
        (r.post_id, r.comment_id)
        for r in records
        if r.source_type in ("comment", "reply")
    }
    for r in records:
        if r.source_type == "reply":
            if (r.post_id, r.parent_id) not in comment_keys:
                warnings.append(
                    f"Reply {r.comment_id} references unknown parent {r.parent_id}"
                )
    return warnings