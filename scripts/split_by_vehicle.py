"""STEP 5g: Split master into per-vehicle folders under data/output/by_vehicle_v2.

Layout (per vehicle): raw.csv | clean.csv | relevant.csv | analyzed.csv
plus combined/*.csv and unknown_or_review.csv at the v2 root for records whose
vehicle could not be assigned confidently.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    clean_csv = os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv")
    if vc.step_guard(os.path.join(vc.OUTPUT_ROOT, "combined", "all_vehicles_analyzed.csv"), args.force):
        vc.log("skip split_by_vehicle (outputs exist; use --force)")
        return 0

    df = vc.load_df(clean_csv)
    vc.ensure_output_dirs()

    clean_mask = df["text_clean"].fillna("").astype(str).str.strip().ne("")
    all_relevant, all_analyzed, all_clean = [], [], []
    rows_per_vehicle = {}

    for canonical, foldername in vc.CANONICAL_TO_DIR.items():
        vdir = os.path.join(vc.OUTPUT_ROOT, foldername)
        os.makedirs(vdir, exist_ok=True)
        vmask = df["vehicle_v2"].eq(canonical)
        sub = df[vmask].copy()
        sub_clean_mask = sub["text_clean"].fillna("").astype(str).str.strip().ne("")
        rows_per_vehicle[canonical] = {
            "raw": int(len(sub)),
            "clean": int(sub_clean_mask.sum()),
            "relevant": int(sub["adas_relevance"].eq("relevant").sum()),
        }
        vc.save_df(sub, os.path.join(vdir, "raw.csv"))
        clean_sub = sub[sub_clean_mask]
        vc.save_df(clean_sub, os.path.join(vdir, "clean.csv"))
        relevant_sub = sub[sub["adas_relevance"].eq("relevant")]
        vc.save_df(relevant_sub, os.path.join(vdir, "relevant.csv"))
        vc.save_df(relevant_sub, os.path.join(vdir, "analyzed.csv"))
        all_clean.append(clean_sub)
        all_relevant.append(relevant_sub)
        all_analyzed.append(relevant_sub)

    full_clean = vc_join(all_clean)
    full_relevant = vc_join(all_relevant)
    full_analyzed = vc_join(all_analyzed)
    vc.save_df(full_clean, os.path.join(vc.COMBINED_DIR, "all_vehicles_clean.csv"))
    vc.save_df(full_relevant, os.path.join(vc.COMBINED_DIR, "all_vehicles_relevant.csv"))
    vc.save_df(full_analyzed, os.path.join(vc.COMBINED_DIR, "all_vehicles_analyzed.csv"))

    review = df[df["vehicle_v2"].eq("unknown")
                | df["vehicle_confidence"].eq("low")
                | df["vehicle_reason"].str.contains("but_context|conflicting")]
    vc.save_df(review, os.path.join(vc.OUTPUT_ROOT, "unknown_or_review.csv"))

    vc.write_json(os.path.join(vc.AUDIT_DIR, "split_report.json"), {
        "rows_per_vehicle": rows_per_vehicle,
        "unknown_or_review": int(len(review)),
        "all_clean": int(len(full_clean)),
        "all_relevant": int(len(full_relevant)),
        "all_analyzed": int(len(full_analyzed)),
    })
    vc.log(f"split_by_vehicle done: {vc.CANONICAL_TO_DIR}")
    vc.log(f"unknown_or_review={len(review)} relevant_total={len(full_relevant)}")
    return 0


def vc_join(frames) -> object:
    import pandas as pd
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    sys.exit(main())