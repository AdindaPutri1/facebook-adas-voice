"""STEP 5d: Contextual vehicle identification -> adds vehicle_v2,
vehicle_confidence, vehicle_reason onto facebook_master_clean.csv.

Rules (documented, deterministic):
  - Explicit alias in text -> 'high' (brand+model / full name) or 'medium' (short).
  - Multiple conflicts resolved via community-scoped 'vehicle' prior; else unknown/low.
  - No mention -> community-scoped prior 'medium'; else unknown/low.
Low-confidence / unknown records are collected for manual review in
unknown_or_review.csv during the split stage.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402

from src.config_loader import load_vehicles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    clean_csv = os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv")
    if not args.force and _already_done(clean_csv):
        vc.log("skip classify_vehicle (columns exist; use --force)")
        return 0

    df = vc.load_df(clean_csv)
    patterns = vc.build_vehicle_alias_patterns(load_vehicles())
    prior = vc.load_analysis_config().get("vehicle", {}).get("context_prior_weight", "medium")

    out = df.apply(
        lambda r: _row(r, patterns, prior), axis=1)
    df["vehicle_v2"] = out.apply(lambda x: x["vehicle"])
    df["vehicle_confidence"] = out.apply(lambda x: x["confidence"])
    df["vehicle_reason"] = out.apply(lambda x: x["reason"])

    vc.save_df(df, clean_csv)
    vc.log(f"classify_vehicle done: rows={len(df)}")
    return 0


def _already_done(path: str) -> bool:
    if not os.path.exists(path):
        return False
    df = vc.load_df(path)
    return {"vehicle_v2", "vehicle_confidence", "vehicle_reason"}.issubset(df.columns)


def _row(r, patterns, prior):
    return vc.classify_vehicle(r.get("text_clean", ""), r.get("vehicle", ""), patterns, prior)


if __name__ == "__main__":
    sys.exit(main())