"""STEP 5h: Generate processing_summary.json + vehicle_summary.csv.

Pure aggregation over already-written v2 outputs; no data is modified.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402


def dist(df, col):
    if col not in df.columns:
        return {}
    return {str(k): int(v) for k, v in df[col].dropna().astype(str).value_counts().items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = os.path.join(vc.MASTER_DIR, "processing_summary.json")
    if not args.force and os.path.exists(out):
        vc.log("skip generate_summary (exists; use --force)")
        return 0

    clean = vc.load_df(os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv"))
    raw_master = vc.load_df(os.path.join(vc.MASTER_DIR, "facebook_master_raw.csv"))
    relevant = vc.load_df(os.path.join(vc.COMBINED_DIR, "all_vehicles_relevant.csv"))
    review = vc.load_df(os.path.join(vc.OUTPUT_ROOT, "unknown_or_review.csv"))
    try:
        dedup = vc_load_yaml_file(os.path.join(vc.AUDIT_DIR, "dedup_report.json"))
    except Exception:
        dedup = {}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spec": "v2 reprocessing - no re-scraping; raw inputs untouched",
        "master": {
            "raw_union_rows": int(len(raw_master)),
            "deduplicated_rows": int(len(clean)),
            "dedup_report": dedup,
        },
        "vehicles": {c: {} for c in vc.CANONICAL_TO_DIR},
        "vehicle_confidence": dist(clean, "vehicle_confidence"),
        "adas": {
            "candidate_records": int((clean["candidate_adas"].eq("True")).sum()),
            "relevance": dist(clean, "adas_relevance"),
            "relevant_records": int(len(relevant)),
            "relevance_confidence": dist(clean, "relevance_confidence"),
        },
        "analysis": {
            "feature": dist(clean, "feature"),
            "evidence_type": dist(relevant, "evidence_type") if not relevant.empty else {},
            "sentiment": dist(relevant, "sentiment") if not relevant.empty else {},
            "driving_scenario": dist(relevant, "driving_scenario") if not relevant.empty else {},
            "smoothness": dist(relevant, "smoothness") if not relevant.empty else {},
            "expectation_mismatch": dist(relevant, "expectation_mismatch") if not relevant.empty else {},
        },
        "unknown_or_review": int(len(review)),
        "output_layout": {
            "master": "master/{facebook_master_raw,facebook_master_deduplicated,facebook_master_clean,facebook_master_relevant,processing_summary}",
            "per_vehicle": "<Vehicle>/{raw,clean,relevant,analyzed}.csv",
            "combined": "combined/{all_vehicles_clean,all_vehicles_relevant,all_vehicles_analyzed}.csv",
        },
    }

    for canonical, foldername in vc.CANONICAL_TO_DIR.items():
        vdir = os.path.join(vc.OUTPUT_ROOT, foldername)
        sub = clean[clean["vehicle_v2"].eq(canonical)]
        rel = relevant[relevant["vehicle_v2"].eq(canonical)] if not relevant.empty else pd_empty()
        summary["vehicles"][canonical] = {
            "raw_records": int(len(sub)),
            "clean_records": int(sub["text_clean"].fillna("").astype(str).str.strip().ne("").sum()),
            "relevant_records": int(len(rel)),
            "candidate_records": int(sub["candidate_adas"].eq("True").sum()),
            "features": dist(sub, "feature"),
            "communities": int(sub["community"].nunique()) if "community" in sub else 0,
            "unique_posts": int(sub["post_id"].nunique()) if "post_id" in sub else 0,
            "unique_comments": int(sub["comment_id"].astype(str).str.len().gt(0).sum()),
        }

    # facebook_master_relevant.csv - the spec master file (all relevant records)
    master_relevant = clean[clean["adas_relevance"].eq("relevant")] \
        if not clean.empty else clean
    vc.save_df(master_relevant, os.path.join(vc.MASTER_DIR, "facebook_master_relevant.csv"))

    # vehicle_summary.csv
    veh_rows = []
    for c, m in summary["vehicles"].items():
        row = {"vehicle": c, "vehicle_dir": vc.CANONICAL_TO_DIR[c]}
        row.update(m)
        if not m.get("features"):
            for f in ("PDA", "ACC", "PDA+ACC", "ADAS_OTHER", "UNKNOWN"):
                row[f] = 0
        veh_rows.append(row)
    import pandas as pd
    vc.save_df(pd.DataFrame(veh_rows).fillna(0), os.path.join(vc.OUTPUT_ROOT, "vehicle_summary.csv"))

    vc.write_json(out, summary)
    vc.log("generate_summary done -> " + out)
    vc.log(f"candidate={summary['adas']['candidate_records']} relevant={len(relevant)} "
           f"review={len(review)}")
    return 0


def vc_load_yaml_file(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pd_empty():
    import pandas as pd
    return pd.DataFrame()


if __name__ == "__main__":
    sys.exit(main())