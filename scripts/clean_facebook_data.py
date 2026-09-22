"""STEP 5c: Clean facebook_master_deduplicated -> facebook_master_clean.csv.

Preserves text_raw verbatim. Adds text_clean (normalised whitespace, HTML/URL/
mention tokens removed) and text_normalized (case-folded for matching). Cleaning
never removes or rewrites any source file.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402
from v2_common import clean_text, normalize_lower  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strip-emojis", action="store_true")
    args = parser.parse_args()

    in_csv = os.path.join(vc.MASTER_DIR, "facebook_master_deduplicated.csv")
    out_csv = os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv")
    if not args.force and os.path.exists(out_csv):
        vc.log("skip clean (exists; use --force) -> " + out_csv)
        return 0

    df = vc.load_df(in_csv)
    raw = df["text_raw"].fillna("").astype(str)
    strip = bool(args.strip_emojis or vc.load_analysis_config().get("cleaning", {}).get("strip_emojis", False))
    df["text_clean"] = raw.map(lambda t: clean_text(t, strip_emojis=strip))
    df["text_normalized"] = df["text_clean"].map(normalize_lower)
    # sanity: raw column must be untouched
    assert (df["text_raw"].fillna("").astype(str) == raw).all(), "text_raw was mutated!"

    empty_clean = int(df["text_clean"].str.strip().eq("").sum())
    vc.save_df(df, out_csv)
    vc.log(f"clean written: rows={len(df)} empty_after_clean={empty_clean}")
    return 0


if __name__ == "__main__":
    sys.exit(main())