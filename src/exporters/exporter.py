"""Exporters: CSV/XLSX/JSON across data layers, plus summary + customer_voice
generation. Descriptive, not ranking-based."""
import os
import json
import re
import logging
from collections import Counter, defaultdict
from typing import Dict, List, Optional

import pandas as pd

from src.config_loader import resolve_path

log = logging.getLogger(__name__)


class Exporter:
    def __init__(self):
        pass

    def export_dataframe(self, df: pd.DataFrame, layer: str, name: str,
                         formats=("csv", "xlsx", "json")):
        if df is None or df.empty:
            return []
        out = []
        base_dir = resolve_path(layer)
        os.makedirs(base_dir, exist_ok=True)
        base = os.path.join(base_dir, name)
        if "csv" in formats:
            p = base + ".csv"
            df.to_csv(p, index=False, encoding="utf-8-sig")
            out.append(p)
        if "xlsx" in formats:
            p = base + ".xlsx"
            df.to_excel(p, index=False)
            out.append(p)
        if "json" in formats:
            p = base + ".json"
            df.to_json(p, orient="records", force_ascii=False, indent=2)
            out.append(p)
        return out


MOCK_MARKERS = ("(mock)", "mock.local", "(synthetic)")


def _is_mock_record(row) -> bool:
    """True when a record traces back to a synthetic/mock source.

    Real customer-voice research must exclude train/development fixtures such as
    the SyntheticCollector's records (community '... (Mock)', url 'mock.local').
    """
    try:
        community = str(row.get("community") or "")
    except Exception:
        community = ""
    reference = ""
    for key in ("source_reference", "url", "community_url"):
        try:
            if row.get(key):
                reference = str(row.get(key))
                break
        except Exception:
            continue
    haystack = f"{community} {reference}".lower()
    return any(m in haystack for m in MOCK_MARKERS)


def _drop_mock(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    return df[~df.apply(_is_mock_record, axis=1)]


def load_clean_records() -> pd.DataFrame:
    clean_dir = resolve_path("clean_dir")
    os.makedirs(clean_dir, exist_ok=True)
    frames = []
    for f in os.listdir(clean_dir):
        if f.startswith("clean_data_") and f.endswith(".csv"):
            frames.append(pd.read_csv(os.path.join(clean_dir, f), dtype=str))
    if not frames:
        return pd.DataFrame()
    return _drop_mock(pd.concat(frames, ignore_index=True).drop_duplicates(subset=["record_id"]))


def load_labeled_records() -> pd.DataFrame:
    labeled_dir = resolve_path("labeled_dir")
    os.makedirs(labeled_dir, exist_ok=True)
    frames = []
    files = [f for f in os.listdir(labeled_dir)
             if f.startswith("labeled_experience_") and f.endswith(".csv")]
    # LLM enhance artifacts take precedence: their rows override rule-based rows
    # for the same record_id (labeler provenance is kept per row).
    files.sort(key=lambda f: (0 if "enhance" in f else 1, f))
    for f in files:
        frames.append(pd.read_csv(os.path.join(labeled_dir, f), dtype=str))
    if not frames:
        return pd.DataFrame()
    return _drop_mock(pd.concat(frames, ignore_index=True).drop_duplicates(subset=["record_id"]))


def load_raw_records() -> pd.DataFrame:
    raw_dir = resolve_path("raw_dir")
    os.makedirs(raw_dir, exist_ok=True)
    frames = []
    for f in os.listdir(raw_dir):
        if f.startswith("raw_data_") and f.endswith(".csv"):
            frames.append(pd.read_csv(os.path.join(raw_dir, f), dtype=str))
    # raw_data_all.jsonl is the append-only, never-purged canonical raw store.
    # Merge it with any run CSVs (dedup by record_id) so a purge of intermediate
    # run CSVs can never silently drop research records.
    jsonl = os.path.join(raw_dir, "raw_data_all.jsonl")
    if os.path.exists(jsonl):
        frames.append(pd.read_json(jsonl, lines=True, dtype=str))
    if not frames:
        return pd.DataFrame()
    return _drop_mock(pd.concat(frames, ignore_index=True).drop_duplicates(subset=["record_id"]))


def generate_summary() -> Dict:
    raw = load_raw_records()
    clean = load_clean_records()
    labeled = load_labeled_records()

    summary = {
        "raw_posts": 0,
        "raw_comments": 0,
        "raw_replies": 0,
        "unique_records": 0,
        "candidate_adas": 0,
        "relevant_records": 0,
        "pda_records": 0,
        "acc_records": 0,
        "by_vehicle": {},
        "by_subfeature": {},
        "by_scenario": {},
        "by_evidence": {},
        "by_sentiment": {},
        "expectation_mismatch": {},
        "smoothness": {},
        "top_themes": [],
    }
    if not raw.empty:
        summary["raw_posts"] = int((raw["source_type"] == "post").sum())
        summary["raw_comments"] = int((raw["source_type"] == "comment").sum())
        summary["raw_replies"] = int((raw["source_type"] == "reply").sum())
    if not clean.empty:
        summary["unique_records"] = len(clean)
    if not labeled.empty:
        summary["candidate_adas"] = int((labeled["keyword_candidate"] == "True").sum() +
                                        (labeled["keyword_candidate"] == True).sum())
        summary["relevant_records"] = int((labeled["relevant"] == "relevant").sum())
        summary["pda_records"] = int(labeled["feature"].isin(["PDA", "both"]).sum())
        summary["acc_records"] = int(labeled["feature"].isin(["ACC", "both"]).sum())
        summary["by_vehicle"] = dict(Counter(labeled["vehicle"]))
        summary["by_subfeature"] = dict(Counter(
            ele for ele in labeled["subfeature"] if ele != "not_stated"))
        summary["by_scenario"] = dict(Counter(
            ele for ele in labeled["scenario"] if ele != "not_stated"))
        summary["by_evidence"] = dict(Counter(labeled["evidence_type"]))
        summary["by_sentiment"] = dict(Counter(labeled["sentiment"]))
        summary["expectation_mismatch"] = dict(Counter(labeled["expectation_mismatch"]))
        summary["smoothness"] = dict(Counter(labeled["smoothness"]))
        labeler_series = labeled["labeler"] if "labeler" in labeled.columns else pd.Series(["rule"] * len(labeled), dtype=str)
        summary["labeler_by_record"] = dict(Counter(
            "rule" if (not isinstance(v, str) or not v) else v for v in labeler_series
        ))

        # top themes: most common subfeature+scenario combinations
        theme_counter = Counter(
            (r["feature"], r["subfeature"], r["scenario"])
            for _, r in labeled.iterrows()
            if r["subfeature"] != "not_stated"
        )
        summary["top_themes"] = [
            {"feature": f, "subfeature": s, "scenario": sc, "count": n}
            for (f, s, sc), n in theme_counter.most_common(12)
        ]
    return summary


def _build_experience_summary(grp, evidence: str, feature: str, subfeature: str,
                              scenario: str) -> str:
    """Neutral, faithful summary wording derived from the group's evidence mix."""
    n = len(grp)
    n_direct = int((grp["evidence_type"] == "direct_experience").sum())
    n_question = int((grp["evidence_type"] == "question").sum())
    n_hearsay = int((grp["evidence_type"] == "hearsay").sum())
    n_opinion = int((grp["evidence_type"] == "opinion").sum())
    n_spec = int((grp["evidence_type"] == "specification").sum())

    feat_display = "PDA and ACC" if feature == "both" else (feature or "unknown")
    ctx = f"{feat_display} / {subfeature}"
    if scenario != "not_stated":
        ctx += f" (scenario: {scenario})"
    plural = "comments" if n > 1 else "comment"

    parts = [f"The dataset contains {n} collected {plural} discussing {ctx}."]
    if n_direct:
        parts.append(
            ("One collected comment described a direct experience of this behaviour."
             if n_direct == 1 else
             f"A subset of users ({n_direct}) described direct experiences of this behaviour."))
    if n_question:
        n_w = "One raises" if n_question == 1 else f"{n_question} raise"
        parts.append(f"{n_w} questions rather than reporting hands-on experience.")
    if n_hearsay:
        n_w = "One comment passes" if n_hearsay == 1 else f"{n_hearsay} pass"
        parts.append(f"{n_w} along second-hand information (hearsay).")
    if n_opinion:
        n_w = "One comment expresses" if n_opinion == 1 else f"{n_opinion} express"
        parts.append(f"{n_w} general opinions without an explicit experience.")
    if n_spec:
        n_w = "One comment cites" if n_spec == 1 else f"{n_spec} cite"
        parts.append(f"{n_w} specification-level facts without user experience.")
    if not n_direct and not n_question and not n_hearsay and not n_opinion and not n_spec:
        parts.append("These are candidate ADAS mentions that require manual review.")
    return " ".join(parts)


def generate_customer_voice(labeled: pd.DataFrame) -> pd.DataFrame:
    """Produce a customer-voice summary faithful to underlying texts."""
    if labeled.empty:
        return pd.DataFrame(
            columns=["vehicle", "feature", "subfeature", "scenario", "theme",
                     "evidence_type", "sentiment", "experience_summary",
                     "source_count", "representative_examples", "confidence"]
        )
    rows = []
    group_cols = ["vehicle", "feature", "subfeature", "scenario"]
    for keys, grp in labeled[labeled["relevant"] == "relevant"].groupby(group_cols,
                                                                        sort=False):
        vehicle, feature, subfeature, scenario = keys
        evidence = Counter(grp["evidence_type"]).most_common(1)[0][0]
        sentiment = Counter(grp["sentiment"]).most_common(1)[0][0]
        examples = grp.sort_values("evidence_type", ascending=False).head(3)["text_clean"].tolist()
        confidence = "high" if evidence == "direct_experience" and len(grp) >= 3 else \
                     ("medium" if len(grp) >= 1 else "low")
        rows.append({
            "vehicle": vehicle,
            "feature": feature,
            "subfeature": subfeature,
            "scenario": scenario,
            "theme": subfeature,
            "evidence_type": evidence,
            "sentiment": sentiment,
            "experience_summary": _build_experience_summary(
                grp, evidence, feature, subfeature, scenario),
            "source_count": len(grp),
            "representative_examples": "\n---\n".join(str(e) for e in examples),
            "confidence": confidence,
        })
    return pd.DataFrame(rows)


def write_cross_vehicle_snapshot(spans: Optional[Dict] = None) -> str:
    """Descriptive snapshot of per-vehicle collection context. Not a ranking."""
    labeled = load_labeled_records()
    raw = load_raw_records()
    rows = []
    for vehicle in sorted(labeled["vehicle"].unique()) if not labeled.empty else []:
        vlab = labeled[labeled["vehicle"] == vehicle]
        vra = raw[raw["vehicle"] == vehicle] if not raw.empty else pd.DataFrame()
        rows.append({
            "vehicle": vehicle,
            "collected_records": int(len(vra)) if not vra.empty else 0,
            "relevant_records": int((vlab["relevant"] == "relevant").sum()),
            "pda_mentions": int(vlab["feature"].isin(["PDA", "both"]).sum()),
            "acc_mentions": int(vlab["feature"].isin(["ACC", "both"]).sum()),
            "direct_experience": int((vlab["evidence_type"] == "direct_experience").sum()),
            "communities_count": int(vlab["community"].nunique()),
            "note": "Descriptive only - not a quality ranking. Differences reflect "
                    "community size, activity, terminology, and access.",
        })
    df = pd.DataFrame(rows)
    out = resolve_path("output_dir")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "cross_vehicle_descriptive.csv")
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _vehicle_label(vehicle: str) -> str:
    return re.sub(r"[^\w]+", "_", vehicle, flags=re.UNICODE).strip("_")


def export_by_vehicle() -> List[str]:
    """Per-vehicle deliverables under <output>/by_vehicle/<Vehicle_Name>/."""
    from_ = resolve_path("output_dir")
    raw = load_raw_records()
    clean = load_clean_records()
    labeled = load_labeled_records()
    vehicles = sorted(labeled["vehicle"].unique()) if not labeled.empty \
        else sorted(raw["vehicle"].unique())
    exp = Exporter()
    files: List[str] = []
    for v in vehicles:
        label = _vehicle_label(v)
        sub = os.path.join(from_, "by_vehicle", label)
        os.makedirs(sub, exist_ok=True)
        vraw = raw[raw["vehicle"] == v] if not raw.empty else pd.DataFrame()
        vclean = clean[clean["vehicle"] == v] if not clean.empty else pd.DataFrame()
        vlab = labeled[labeled["vehicle"] == v] if not labeled.empty else pd.DataFrame()
        vrel = vlab[vlab["relevant"] == "relevant"] if not vlab.empty else pd.DataFrame()
        vcv = generate_customer_voice(vlab)
        for name, df in [("raw_data", vraw),
                         ("clean_data", vclean),
                         ("labeled_experience", vlab),
                         ("relevant_adas", vrel),
                         ("customer_voice", vcv)]:
            files.extend(exp.export_dataframe(df, sub, name))
        files.append(_write_vehicle_summary(sub, label, vraw, vlab))
    return files


def _write_vehicle_summary(sub: str, label: str, vraw: pd.DataFrame,
                           vlab: pd.DataFrame) -> str:
    summary = {
        "vehicle": label,
        "collected_records": int(len(vraw)) if not vraw.empty else 0,
        "labeled_records": int(len(vlab)) if not vlab.empty else 0,
        "candidate_adas": int((vlab["keyword_candidate"] == "True").sum()
                              + (vlab["keyword_candidate"] == True).sum())
        if not vlab.empty else 0,
        "relevant_records": int((vlab["relevant"] == "relevant").sum()) if not vlab.empty else 0,
        "pda_records": int(vlab["feature"].isin(["PDA", "both"]).sum()) if not vlab.empty else 0,
        "acc_records": int(vlab["feature"].isin(["ACC", "both"]).sum()) if not vlab.empty else 0,
    }
    path = os.path.join(sub, "summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return path


def export_all() -> Dict[str, List[str]]:
    raw = load_raw_records()
    clean = load_clean_records()
    labeled = load_labeled_records()
    relevant = labeled[labeled["relevant"] == "relevant"].copy()
    cv = generate_customer_voice(labeled)
    summary = generate_summary()

    exp = Exporter()
    out = {
        "raw": exp.export_dataframe(raw, "output_dir", "raw_data_final"),
        "clean": exp.export_dataframe(clean, "output_dir", "clean_data_final"),
        "relevant": exp.export_dataframe(relevant, "output_dir", "relevant_adas"),
        "labeled": exp.export_dataframe(labeled, "output_dir", "labeled_experience"),
        "customer_voice": exp.export_dataframe(cv, "output_dir", "customer_voice"),
        "by_vehicle": export_by_vehicle(),
    }

    out_dir = resolve_path("output_dir")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    out["summary"] = [os.path.join(out_dir, "summary.json")]

    xv = write_cross_vehicle_snapshot()
    out["cross_vehicle"] = [xv]
    return out