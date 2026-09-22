import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import (
    RawRecord, CleanRecord, LabeledRecord,
    RAW_FIELDS, CLEAN_FIELDS, LABELED_FIELDS,
)

RAW_KEYS = {"vehicle", "community", "community_url", "post_id", "comment_id",
            "parent_id", "source_type", "date", "text_raw", "url", "scraped_at"}


def test_raw_schema_fields_present():
    r = RawRecord(vehicle="J5", community="Mock", community_url="",
                  post_id="p1", comment_id=None, parent_id=None,
                  source_type="post", author_id=None, author_pseudonym=None,
                  date="2026-01-01", text_raw="text", url="u")
    row = r.to_row()
    for k in RAW_KEYS:
        assert k in row or k in r.__dict__


def test_raw_fields_list_complete():
    assert set(RAW_FIELDS) == set(RAW_KEYS) | {"record_id", "author_pseudonym"}


def test_clean_schema():
    c = CleanRecord(record_id="r1", vehicle="J5", community="Mock",
                    post_id="p1", comment_id="c1", parent_id=None,
                    source_type="comment", date="2026-01-01",
                    text_clean="clean text", url="u", scraped_at="t")
    row = c.to_row()
    for k in CLEAN_FIELDS:
        assert k in row


def test_labeled_schema_values():
    l = LabeledRecord(record_id="r1", vehicle="J5", text_clean="t",
                      feature="ACC", subfeature="braking", scenario="stop_and_go",
                      evidence_type="direct_experience", relevant="yes",
                      sentiment="negative", expectation_mismatch="no",
                      smoothness="abrupt", confidence="high")
    assert l.feature in ("PDA", "ACC", "unknown", "both")
    assert l.evidence_type in ("direct_experience", "opinion", "question",
                               "hearsay", "specification", "uncertain")
    assert l.sentiment in ("positive", "negative", "neutral", "mixed", "uncertain")
    assert l.smoothness in ("smooth", "slightly_abrupt", "abrupt", "very_abrupt", "not_stated")


def test_record_id_deterministic():
    a = RawRecord(vehicle="J5", community="Mock", community_url="", post_id="p1",
                  comment_id="c1", parent_id="p1", source_type="comment",
                  author_id=None, author_pseudonym=None, date="d", text_raw="t", url="u")
    b = RawRecord(vehicle="J5", community="Mock", community_url="", post_id="p1",
                  comment_id="c1", parent_id="p1", source_type="comment",
                  author_id=None, author_pseudonym=None, date="d", text_raw="t", url="u")
    assert a.record_id == b.record_id


def test_anonymization_never_writes_raw_author_id():
    r = RawRecord(vehicle="J5", community="Mock", community_url="", post_id="p1",
                  comment_id=None, parent_id=None, source_type="post",
                  author_id="REAL_NAME_123", author_pseudonym="USER_001",
                  date="d", text_raw="t", url="u")
    row = r.to_row()
    # downstream rows must not include the real id
    assert row["author_id"] is None
    assert row["author_pseudonym"] == "USER_001"