"""Cleaning pipeline.

Allowed operations only (per requirements):
- whitespace normalisation
- HTML removal
- URL normalisation (text form)
- irrelevant character normalisation
- case normalisation for matching is handled separately in keyword engine
- basic emoji stripping is optional and OFF by default (raw preserved anyway)
"""
import re
import html
import logging
from typing import Dict, Optional

from src.models import RawRecord, CleanRecord

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MENTION_RE = re.compile(r"@\w+")
_HASH_RE = re.compile(r"#\w+")


def clean_text(text: str, strip_emojis: bool = False) -> str:
    """Return a cleaned version of text without changing its meaning."""
    if text is None:
        return ""
    s = html.unescape(text)
    s = _HTML_TAG_RE.sub(" ", s)
    s = _URL_RE.sub(" [url] ", s)
    s = _MENTION_RE.sub(" [mention] ", s)
    s = s.replace("\\n", " ").replace("\\r", " ")
    s = _WHITESPACE_RE.sub(" ", s)
    s = s.strip()
    if strip_emojis:
        try:
            import emoji

            s = emoji.replace_emoji(s, " ")
            s = _WHITESPACE_RE.sub(" ", s).strip()
        except ImportError:
            log.debug("emoji lib not installed; skipping emoji stripping")
    return s


def clean_record(raw: RawRecord, strip_emojis: bool = False) -> CleanRecord:
    return CleanRecord(
        record_id=raw.record_id,
        vehicle=raw.vehicle,
        community=raw.community,
        post_id=raw.post_id,
        comment_id=raw.comment_id,
        parent_id=raw.parent_id,
        source_type=raw.source_type,
        date=raw.date,
        text_clean=clean_text(raw.text_raw, strip_emojis=strip_emojis),
        url=raw.url,
        scraped_at=raw.scraped_at,
    )


def normalize_lower(text: str) -> str:
    """Case-fold a string for matching purposes. Does not alter stored text."""
    return " ".join(text.lower().split())