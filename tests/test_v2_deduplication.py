import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import v2_common as vc  # noqa: E402
from deduplicate_facebook_data import build_dedup_key  # noqa: E402


def _frame():
    return pd.DataFrame({
        "record_id": ["a", "a", "b", "", ""],
        "community": ["X", "X", "X", "Y", "Y"],
        "post_id": ["1", "1", "2", "3", "3"],
        "comment_id": ["", "", "", "9", "9"],
        "text_raw": ["x", "x", "y", "z", "z"],
        "date": ["2026-01-01"] * 5,
    })


def test_duplicate_record_ids_collapse():
    df = _frame()
    key = build_dedup_key(df)
    assert key.iloc[0] == key.iloc[1]
    assert key.iloc[1] == "a"


def test_meta_key_fallback_for_missing_record_id():
    df = _frame()
    key = build_dedup_key(df)
    assert key.iloc[3] == key.iloc[4]          # community|post|comment fallback
    assert key.iloc[3] == "Y|3|9"


def test_master_dedup_file_exists_and_counts():
    path = os.path.join(vc.MASTER_DIR, "facebook_master_deduplicated.csv")
    if os.path.exists(path):
        df = vc.load_df(path)
        assert len(df) > 0
        assert df["dedup_key"].nunique() == len(df)