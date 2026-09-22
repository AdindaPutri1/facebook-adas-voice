import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cleaners.text_cleaner import clean_text, normalize_lower, clean_record
from src.models import RawRecord


def test_whitespace_normalised():
    assert clean_text("  ACC   mantap  \n  banget  ") == "ACC mantap banget"


def test_html_removed():
    assert clean_text("<b>ACC</b> bekerja halus") == "ACC bekerja halus"


def test_url_replaced():
    out = clean_text("lihat https://example.com/abc di sini")
    assert "https://example.com/abc" not in out


def test_meaning_preserved():
    assert clean_text("ACC-nya ngerem mendadak, tapi masih aman.") == \
           "ACC-nya ngerem mendadak, tapi masih aman."


def test_lower_normalise_for_matching():
    assert normalize_lower("  ACC dan   PDA  ") == "acc dan pda"


def test_clean_record_keeps_raw():
    raw = RawRecord(vehicle="J5", community="c", community_url="", post_id="p1",
                    comment_id=None, parent_id=None, source_type="post",
                    author_id=None, author_pseudonym=None, date="2026-01-01",
                    text_raw="<p>ACC halus</p>   ", url="u")
    cleaned = clean_record(raw)
    # raw untouched (separate field), cleaned normalised
    assert raw.text_raw == "<p>ACC halus</p>   "
    assert cleaned.text_clean == "ACC halus"