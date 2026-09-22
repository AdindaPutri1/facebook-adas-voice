import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from v2_common import clean_text, normalize_lower  # noqa: E402


def test_clean_preserves_meaning():
    assert clean_text("  ACC   mantap  ") == "ACC mantap"


def test_clean_strips_html_and_urls():
    out = clean_text("Belum coba <b>ACC</b> https://fb.com/x nudj")
    assert "<b>" not in out and "http" not in out


def test_clean_empties_none():
    assert clean_text(None) == ""


def test_normalize_lower_collapses_space():
    assert normalize_lower("  ACC   Mantap  ") == "acc mantap"


def test_raw_preserved_in_pipeline_output():
    from v2_common import MASTER_DIR, load_df
    path = os.path.join(MASTER_DIR, "facebook_master_clean.csv")
    if not os.path.exists(path):
        return
    df = load_df(path)
    assert "text_raw" in df.columns and "text_clean" in df.columns
    assert df["text_clean"].fillna("").eq("").sum() == 0