"""Shared helpers for the V2 reprocessing pipeline.

Pure functions + I/O, isolated from scraping code. Nothing here writes to
any raw dataset - outputs go exclusively under data/output/by_vehicle_v2 and
reports under data/audit.
"""
import json
import os
import re
import sys
import time

import pandas as pd
import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from src.cleaners.text_cleaner import clean_text, normalize_lower  # noqa: E402

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
OUTPUT_ROOT = os.path.join(DATA_DIR, "output", "by_vehicle_v2")
MASTER_DIR = os.path.join(OUTPUT_ROOT, "master")
COMBINED_DIR = os.path.join(OUTPUT_ROOT, "combined")
AUDIT_DIR = os.path.join(DATA_DIR, "audit")

CANONICAL_TO_DIR = {
    "Jaecoo J5": "Jaecoo_J5",
    "Toyota Yaris": "Toyota_Yaris",
    "Toyota Zenix": "Toyota_Zenix",
    "Toyota Veloz": "Toyota_Veloz",
    "XPeng G6": "XPeng_G6",
    "BYD Sealion 7": "BYD_Sealion_7",
}

STD_COLUMNS = [
    "record_id", "vehicle", "community", "community_url", "post_id", "comment_id",
    "parent_id", "source_type", "author_id", "author_pseudonym", "date",
    "text_raw", "url", "scraped_at",
]

ANALYSIS_COLUMNS = [
    "feature", "subfeature", "driving_scenario", "evidence_type",
    "sentiment", "smoothness", "expectation_mismatch", "feature_confidence",
]


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_analysis_config() -> dict:
    cfg = load_yaml(os.path.join(PROJECT_ROOT, "config", "analysis.yaml"))
    return cfg.get("pipeline", {})


def ensure_output_dirs() -> None:
    for d in (OUTPUT_ROOT, MASTER_DIR, COMBINED_DIR):
        os.makedirs(d, exist_ok=True)


def load_df(path: str) -> pd.DataFrame:
    if path.endswith(".jsonl"):
        rows = [json.loads(l) for l in open(path, "r", encoding="utf-8") if l.strip()]
        return pd.DataFrame(rows)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def save_df(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def log(msg: str) -> None:
    print(f"[pipeline-v2 {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step_guard(next_file: str, force: bool = False) -> bool:
    if force:
        return False
    return os.path.exists(next_file)


def write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Vehicle alias handling
# ---------------------------------------------------------------------------
_AV_RE = r"(?<![a-z0-9]){}(?![a-z0-9])"


def build_vehicle_alias_patterns(vehicles_cfg: dict) -> dict:
    """Return {canonical: {"strong": [re...], "short": [re...]}}."""
    out = {}
    for key, v in vehicles_cfg.get("vehicles", {}).items():
        canonical = v.get("canonical_name", key)
        brand = (v.get("brand") or "").strip().lower()
        model = (v.get("model") or "").strip().lower()
        aliases = [str(a).strip() for a in v.get("aliases", []) if str(a).strip()]
        strong, short = [], []
        names = [v.get("canonical_name", key), v.get("model", "")]
        for n in names:
            n = normalize_lower(n)
            if n:
                strong.append(re.compile(_AV_RE.format(re.escape(n))))
        if brand and model:
            strong.append(re.compile(_AV_RE.format(re.escape(f"{brand} {model}"))))
            strong.append(re.compile(_AV_RE.format(re.escape(f"{brand}-{model}"))))
            strong.append(re.compile(_AV_RE.format(
                re.escape(brand.replace(" ", "")) + r"\s*" + re.escape(model.replace(" ", "")))))
        for a in aliases:
            a_l = normalize_lower(a)
            if not a_l:
                continue
            if brand and a_l.startswith(brand):
                strong.append(re.compile(_AV_RE.format(re.escape(a_l))))
            elif " " in a_l or len(a_l) > 5:
                strong.append(re.compile(_AV_RE.format(re.escape(a_l))))
            else:
                short.append(re.compile(_AV_RE.format(re.escape(a_l))))
        out[canonical] = {"strong": strong, "short": short}
    return out


def detect_vehicle_mentions(text: str, alias_patterns: dict) -> dict:
    """Return {canonical: confidence_hint} for vehicles mentioned in text."""
    if not text:
        return {}
    lowered = normalize_lower(text)
    found = {}
    for canonical, pats in alias_patterns.items():
        strong_hit = any(p.search(lowered) for p in pats["strong"])
        short_hit = any(p.search(lowered) for p in pats["short"])
        if strong_hit or short_hit:
            found[canonical] = "strong" if strong_hit else "short"
    return found


def canonicalise_record_vehicle(value: str, alias_patterns: dict) -> str:
    """Map scraper-provided vehicle label (often community-scoped) to canonical."""
    v = str(value or "").strip()
    if not v or v.lower() in ("unknown", "nan", "none"):
        return ""
    if v in alias_patterns:
        return v
    map_ = {k.lower(): k for k in alias_patterns}
    for label, canon in map_.items():
        if v.lower().startswith(label):
            return canon
    return v


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def classify_vehicle(text: str, record_vehicle: str, alias_patterns: dict,
                     context_prior="medium") -> dict:
    mentions = detect_vehicle_mentions(text, alias_patterns)
    src = canonicalise_record_vehicle(record_vehicle, alias_patterns)

    if len(mentions) == 1:
        (vehicle, hint), = mentions.items()
        confidence = "high" if hint == "strong" else "medium"
        reason = "explicit_text_alias_" + hint
        if src and src != vehicle:
            reason += "_but_context_" + src.replace(" ", "_")
            confidence = "medium"
        return {"vehicle": vehicle, "confidence": confidence, "reason": reason}

    if len(mentions) > 1:
        if src in mentions:
            return {"vehicle": src, "confidence": context_prior,
                    "reason": "multiple_mentions_context_vehicle"}
        return {"vehicle": "unknown", "confidence": "low",
                "reason": "conflicting_multiple_mentions"}

    if src:
        return {"vehicle": src, "confidence": context_prior,
                "reason": "community_context"}
    return {"vehicle": "unknown", "confidence": "low", "reason": "no_signal"}