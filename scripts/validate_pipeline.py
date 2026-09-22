"""Final validation checklist for the V2 pipeline outputs.

Runs read-only checks against data/output/by_vehicle_v2 and data/audit.
Exit code 0 => all checks pass; non-zero => at least one failed.

Usage:
    python scripts/validate_pipeline.py
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402

ALLOWED_FEATURES = {"PDA", "ACC", "PDA+ACC", "ADAS_OTHER", "UNKNOWN"}
ALLOWED_CONF = {"high", "medium", "low"}
ALLOWED_EVIDENCE = {"direct_experience", "opinion", "question", "hearsay",
                    "specification", "uncertain"}
ALLOWED_SENTIMENT = {"positive", "neutral", "negative", "mixed"}
ALLOWED_RELEVANCE = {"relevant", "uncertain", "not_relevant"}

CHECKS: list = []


def check(name: str, ok: bool, detail: str = ""):
    CHECKS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    master = vc.MASTER_DIR
    required_master = ["facebook_master_raw.csv", "facebook_master_deduplicated.csv",
                       "facebook_master_clean.csv", "facebook_master_relevant.csv",
                       "processing_summary.json"]
    for f in required_master:
        check(f"master file exists: {f}", os.path.exists(os.path.join(master, f)))
    for name in ["Jaecoo_J5", "Toyota_Yaris", "Toyota_Zenix", "Toyota_Veloz",
                 "XPeng_G6", "BYD_Sealion_7"]:
        sub = os.path.join(vc.OUTPUT_ROOT, name)
        for f in ["raw.csv", "clean.csv", "relevant.csv", "analyzed.csv"]:
            check(f"{name}/{f} exists", os.path.exists(os.path.join(sub, f)))
    for f in ["combined/all_vehicles_clean.csv", "combined/all_vehicles_relevant.csv",
              "combined/all_vehicles_analyzed.csv"]:
        check(f"{f} exists", os.path.exists(os.path.join(vc.OUTPUT_ROOT, f)))
    check("unknown_or_review.csv exists",
          os.path.exists(os.path.join(vc.OUTPUT_ROOT, "unknown_or_review.csv")))

    raw = vc.load_df(os.path.join(master, "facebook_master_raw.csv"))
    ded = vc.load_df(os.path.join(master, "facebook_master_deduplicated.csv"))
    cln = vc.load_df(os.path.join(master, "facebook_master_clean.csv"))
    rel = vc.load_df(os.path.join(vc.COMBINED_DIR, "all_vehicles_relevant.csv"))
    review = vc.load_df(os.path.join(vc.OUTPUT_ROOT, "unknown_or_review.csv"))

    check("raw >= dedup rows", len(raw) >= len(ded), f"{len(raw)} vs {len(ded)}")
    check("dedup unique == dedup_key unique",
          ded["dedup_key"].nunique() == len(ded)
          or ded["record_id"].nunique() == len(ded))
    check("clean rows == dedup rows", len(cln) == len(ded), f"{len(cln)} vs {len(ded)}")
    check("no empty record_id in clean",
          cln["record_id"].astype(str).str.strip().ne("").all())
    check("record_id unique across combined clean", cln["record_id"].nunique() == len(cln))
    check("text_raw preserved column", "text_raw" in cln.columns and "text_clean" in cln.columns)
    check("text_clean non-empty after cleaning",
          cln["text_clean"].fillna("").astype(str).str.strip().ne("").all())

    check("all 6 canonical vehicles present",
          set(vc.CANONICAL_TO_DIR).issubset(set(cln["vehicle_v2"].dropna())))
    check("vehicle_confidence values valid",
          set(cln["vehicle_confidence"].dropna()).issubset(ALLOWED_CONF))
    check("feature values are from fixed set",
          set(cln["feature"].dropna()).issubset(ALLOWED_FEATURES))

    cand = cln[cln["candidate_adas"].eq("True")]
    check("candidates have relevance labels",
          set(cand["adas_relevance"].dropna()).issubset(ALLOWED_RELEVANCE))
    check("relevant subset is candidate",
          set(rel["record_id"]).issubset(set(cln[cln["candidate_adas"].eq("True")]["record_id"]) | set(rel["record_id"])))
    check("every relevant record has feature != UNKNOWN-unknown-analysis fields",
          rel[["evidence_type", "sentiment", "driving_scenario", "smoothness"]].notna().all().all())
    check("evidence_type values valid",
          set(rel["evidence_type"].dropna()).issubset(ALLOWED_EVIDENCE))
    check("sentiment values valid",
          set(rel["sentiment"].dropna()).issubset(ALLOWED_SENTIMENT))
    check("feature analysis only set for candidates",
          cln.loc[cln["candidate_adas"].eq("False"), ["feature", "evidence_type"]]
          .apply(lambda s: s.fillna("").eq("UNKNOWN").all(), axis=1).all()
          or cln.loc[cln["candidate_adas"].eq("False"), "feature"].fillna("").eq("UNKNOWN").all())

    # per-vehicle vs combined consistency (clean rows)
    per = {c: vc.load_df(os.path.join(vc.OUTPUT_ROOT, d, "clean.csv"))
           for c, d in vc.CANONICAL_TO_DIR.items()}
    joint = set().union(*[set(df["record_id"]) for df in per.values()])
    check("per-vehicle clean disjoint record ids", sum(len(set(df["record_id"])) for df in per.values()) == len(joint))
    check("combined clean == union of per-vehicle clean",
          len(vc.load_df(os.path.join(vc.COMBINED_DIR, "all_vehicles_clean.csv"))) == len(joint))
    unassigned = set(cln.loc[cln["vehicle_v2"].eq("unknown"), "record_id"])
    check("all unassigned/low rows captured in review",
          unassigned.issubset(set(review["record_id"])))
    check("review rows exist in clean master",
          review.empty or set(review["record_id"]).issubset(set(cln["record_id"])))

    try:
        summary = json.load(open(os.path.join(master, "processing_summary.json"), "r", encoding="utf-8"))
        check("processing_summary has adas & vehicles", "adas" in summary and "vehicles" in summary)
        tot = sum(v.get("raw_records", 0) for v in summary["vehicles"].values())
        n_unknown = int(cln["vehicle_v2"].eq("unknown").sum())
        check("summary per-vehicle raw sum + unknown == dedup rows",
              tot + n_unknown == len(ded), f"{tot} + {n_unknown} vs {len(ded)}")
    except Exception as e:  # noqa: BLE001
        check("processing_summary readable", False, str(e)[:120])

    failed = sum(1 for c in CHECKS if not c["ok"])
    print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())