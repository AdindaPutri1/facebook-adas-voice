import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.deduplication.deduplicator import deduplicate, dedup_key
from src.models import RawRecord
from src.storage.state_db import StateDB


def _rec(post_id, comment_id=None, text="halo halo bandung", source_type="post"):
    return RawRecord(
        vehicle="Jaecoo J5", community="Mock", community_url="",
        post_id=post_id, comment_id=comment_id, parent_id=None,
        source_type=source_type, author_id=None, author_pseudonym=None,
        date="2026-01-01", text_raw=text, url="",
    )


def test_dedup_same_post():
    recs = [_rec("p1"), _rec("p1")]
    unique, dups, _ = deduplicate(recs)
    assert len(unique) == 1 and dups == 1


def test_dedup_comment_distinct():
    recs = [_rec("p1", "c1"), _rec("p1", "c2")]
    unique, dups, _ = deduplicate(recs)
    assert len(unique) == 2 and dups == 0


def test_dedup_identity_invariance():
    r1 = _rec("p1", "c1", text="A", source_type="comment")
    r2 = _rec("p1", "c1", text="A", source_type="comment")
    assert dedup_key(r1) == dedup_key(r2)


def test_dedup_e2e_with_state_db():
    with tempfile.TemporaryDirectory() as td:
        db = StateDB(os.path.join(td, "state.db"))
        recs = [_rec("p1", "c1"), _rec("p1", "c1")] * 2
        unique, dups, skipped = deduplicate(recs, state=db)
        assert len(unique) == 1
        assert dups == 3
        # second call should treat existing as skipped
        unique2, dups2, skipped2 = deduplicate(recs, state=db)
        assert skipped2 >= 1
        db.close()