"""STEP 5f: Feature + experience analysis -> adds analysis columns (feature,
subfeature, driving_scenario, evidence_type, sentiment, smoothness,
expectation_mismatch, feature_confidence) onto facebook_master_clean.csv.

Only ADAS candidates are analysed. Feature is restricted to the spec set:
PDA | ACC | PDA+ACC | ADAS_OTHER | UNKNOWN. Direct experience/opinion/question/
hearsay/specification distinction is kept in evidence_type so comment count is
never treated as ADAS quality.
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402

from src.classifiers.feature_classifier import FeatureClassifier  # noqa: E402
from src.classifiers.experience_classifier import (  # noqa: E402
    ScenarioClassifier, SentimentClassifier, SmoothnessClassifier,
    ExpectationMismatchClassifier,
)
from src.filters.relevance_filter import classify_evidence  # noqa: E402


def map_feature(label: str, candidate_text: str) -> str:
    if label == "both":
        return "PDA+ACC"
    if label == "PDA":
        return "PDA"
    if label == "ACC":
        return "ACC"
    if label in vc.load_analysis_config().get("feature", {}).get("other_features", []):
        return "ADAS_OTHER"
    return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    clean_csv = os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv")
    if not args.force and _already_done(clean_csv):
        vc.log("skip classify_experience (columns exist; use --force)")
        return 0

    feats = FeatureClassifier()
    scen = ScenarioClassifier()
    sent = SentimentClassifier()
    smooth = SmoothnessClassifier()
    expect = ExpectationMismatchClassifier()

    df = vc.load_df(clean_csv)
    rows = df.apply(lambda r: _row(r, feats, scen, sent, smooth, expect), axis=1)
    for col in vc.ANALYSIS_COLUMNS:
        df[col] = rows.apply(lambda x, c=col: x[c])

    vc.save_df(df, clean_csv)
    dist = df["feature"].value_counts().to_dict()
    vc.log(f"classify_experience done: rows={len(df)} feature_dist={dist}")
    return 0


def _already_done(path: str) -> bool:
    if not os.path.exists(path):
        return False
    df = vc.load_df(path)
    return {"feature", "evidence_type"}.issubset(df.columns)


def _row(r, feats, scen, sent, smooth, expect):
    text = r.get("text_clean", "") or r.get("text_raw", "")
    candidate = str(r.get("candidate_adas", "False")) == "True"
    if not candidate or not (text or "").strip():
        base = {"feature": "UNKNOWN", "subfeature": "", "driving_scenario": "",
                "evidence_type": "", "sentiment": "", "smoothness": "",
                "expectation_mismatch": "", "feature_confidence": ""}
        return base

    label, matched = feats.classify(text)
    feature = map_feature(label, text)
    lay = str(r.get("layer_hit", ""))
    if "layer_a_feature_names" in lay:
        feature_confidence = "high"
    elif "layer_b" in lay or "layer_c" in lay:
        feature_confidence = "medium"
    else:
        feature_confidence = "low"

    if feature == "UNKNOWN":
        subfeature = "not_stated"
    elif feature == "ADAS_OTHER":
        subfeature = label
    else:
        sf = feats.classify_subfeature(text, "both" if feature == "PDA+ACC" else feature)
        subfeature = sf if sf and sf != "not_stated" else "not_stated"

    return {
        "feature": feature,
        "subfeature": subfeature,
        "driving_scenario": scen.classify(text),
        "evidence_type": classify_evidence(text),
        "sentiment": sent.classify(text),
        "smoothness": smooth.classify(text),
        "expectation_mismatch": expect.classify(text),
        "feature_confidence": feature_confidence,
    }


if __name__ == "__main__":
    sys.exit(main())