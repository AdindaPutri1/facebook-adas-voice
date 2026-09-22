"""STEP 5b: Deduplicate facebook_master_raw -> facebook_master_deduplicated.csv.

Primary key: record_id. If record_id is empty, fallback to
community|post_id|comment_id. Keeps the FIRST occurrence (deterministic because
sources are processed in ascending original filename order). Raw inputs are not
touched; a dedup report is written to data/audit/dedup_report.json.
"""
import argparse
import json
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402
from v2_common import normalize_lower  # noqa: E402


def build_dedup_key(df: pd.DataFrame) -> pd.Series:
    rid = df["record_id"].astype(str).str.strip()
    meta = (df["community"].fillna("").astype(str) + "|"
            + df["post_id"].fillna("").astype(str) + "|"
            + df["comment_id"].fillna("").astype(str))
    has_rid = rid.ne("") & rid.ne("nan")
    key = rid.where(has_rid)
    key = key.fillna(meta.where(meta.ne("||")))
    return key.fillna("hashed:" + df.index.astype(str) + ":" + df["text_raw"].fillna("").astype(str)
                      + ":" + df["date"].fillna("").astype(str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    raw_csv = os.path.join(vc.MASTER_DIR, "facebook_master_raw.csv")
    out_csv = os.path.join(vc.MASTER_DIR, "facebook_master_deduplicated.csv")
    if not args.force and os.path.exists(out_csv):
        vc.log("skip deduplicate (exists; use --force) -> " + out_csv)
        return 0

    df = vc.load_df(raw_csv)
    n_raw = len(df)

    key = build_dedup_key(df)
    df["dedup_key"] = key
    mask_dup = key.duplicated(keep="first")
    df["is_duplicate"] = mask_dup.astype(str)
    kept = df[~mask_dup].copy()
    n_dup = int(mask_dup.sum())

    report = {
        "input_rows": n_raw,
        "duplicate_rows_removed": n_dup,
        "unique_rows_kept": int(len(kept)),
        "dedup_rate_pct": round(100.0 * n_dup / max(n_raw, 1), 2),
        "rows_with_record_id": int(df["record_id"].astype(str).str.strip().ne("").sum()),
        "primary_key": "record_id",
        "fallback_key": ["community", "post_id", "comment_id"],
    }
    vc.write_json(os.path.join(vc.AUDIT_DIR, "dedup_report.json"), report)
    vc.save_df(kept, out_csv)
    vc.log(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())