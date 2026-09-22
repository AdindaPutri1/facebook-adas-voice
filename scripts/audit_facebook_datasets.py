"""STEPS 1-4: Audit every existing Facebook scrape dataset BEFORE building the master.

Nothing is written, deleted or modified. Produces:
  - printed per-dataset table
  - data/audit/facebook_datasets_audit.csv  (rows = one table per dataset)
  - data/audit/facebook_datasets_audit.json (same, machine readable)
  - data/audit/master_union_report.json     (union/dedup numbers across raw sources)

Usage:
  python scripts/audit_facebook_datasets.py
"""
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
AUDIT_DIR = os.path.join(DATA_DIR, "audit")

EXCLUDE_DIRS = {"browser_profiles", "llm_cache", "cache", "cookies", "__pycache__"}
EXCLUDE_NAME_PARTS = ("llm_cache", "cookies", "state_db", "browser_profile")

CANONICAL_VEHICLES = {
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


def _is_excluded(root: str, path: str) -> bool:
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if any(p in EXCLUDE_DIRS or any(s in p.lower() for s in EXCLUDE_NAME_PARTS) for p in parts[:-1]):
        return True
    name = os.path.basename(path).lower()
    if any(s in name for s in EXCLUDE_NAME_PARTS):
        return True
    return False


def _safe(df):
    """NaN -> '' for hashed keys."""
    if df is None or df.empty:
        return df
    return df.fillna("")


def _null_count(series) -> int:
    return int(series.isna().sum()) if not series.empty else 0


def _date_range(df) -> str:
    for col in ("date", "scraped_at"):
        if col in df.columns:
            vals = pd.to_datetime(df[col], errors="coerce", format="mixed")
            vals = vals.dropna()
            if not vals.empty:
                return f"{vals.min():%Y-%m-%d}..{vals.max():%Y-%m-%d}"
    return "N/A"


def _load_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if ext == ".jsonl":
        return pd.DataFrame([json.loads(l) for l in open(path, "r", encoding="utf-8") if l.strip()])
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return pd.DataFrame(data)
        if isinstance(data, dict) and any(isinstance(v, list) for v in data.values()):
            for key, val in data.items():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    return pd.DataFrame(val).assign(_sheet=key)
        return pd.DataFrame([])  # metadata, not a table
    if ext == ".xlsx":
        return pd.read_excel(path, dtype=str, keep_default_na=False)
    raise ValueError(f"unsupported ext {ext}")


def audit_file(path: str, root: str) -> Dict[str, Any]:
    st = os.stat(path)
    report = {
        "file": os.path.relpath(path, PROJECT_ROOT).replace("\\", "/"),
        "path": path,
        "format": os.path.splitext(path)[1].lstrip(".").lower(),
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }
    try:
        df = _load_table(path)
    except Exception as e:  # noqa: BLE001
        report.update({"status": "error", "error": str(e)[:200]})
        return report
    if df is None or df.empty:
        report.update({"status": "metadata_or_empty", "rows": 0, "columns": 0})
        return report

    df = _safe(df)
    n = len(df)
    uniq = {c: _null_count(df[c]) if c in df.columns else n
            for c in ("post_id", "comment_id", "record_id")}
    report.update({
        "status": "ok",
        "rows": n,
        "columns": int(df.shape[1]),
        "unique_record_id": _uniq(df, "record_id"),
        "unique_post_id": _uniq(df, "post_id"),
        "unique_comment_id": _uniq(df, "comment_id"),
        "null_record_id": uniq.get("record_id", n),
        "null_post_id": uniq.get("post_id", n),
        "null_comment_id": uniq.get("comment_id", n),
        "date_range": _date_range(df),
        "duplicate_estimate_pct": _dup_estimate(df),
        "has_text_raw": "text_raw" in df.columns,
        "has_text_clean": "text_clean" in df.columns,
        "has_vehicle": "vehicle" in df.columns,
    })
    if "vehicle" in df.columns:
        counts = df["vehicle"].value_counts(dropna=False).head(20)
        report["vehicle_counts"] = {str(k): int(v) for k, v in counts.items()}
    if "community" in df.columns:
        report["community_count"] = int(df["community"].nunique())
    return report


def _uniq(df, col) -> int:
    if col not in df.columns:
        return 0
    s = df[col].astype(str).str.strip()
    valid = s[(s != "") & (s != "nan") & (s != "None")]
    return int(valid.nunique())


def _dup_estimate(df) -> float:
    total = len(df) or 1
    key = None
    if "record_id" in df.columns:
        rid = df["record_id"].astype(str).str.strip()
        if rid.ne("").any():
            key = rid.where(rid.ne(""))
    if key is None and {"community", "post_id", "comment_id"}.issubset(df.columns):
        key = df[["community", "post_id", "comment_id"]].astype(str).agg("|".join, axis=1)
    if key is None:
        return 0.0
    valid = key.dropna()
    if valid.empty:
        return 0.0
    return round(100.0 * int(valid.duplicated().sum()) / total, 1)


def collect_files() -> List[str]:
    out = []
    for root, dirs, files in os.walk(DATA_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in sorted(files):
            path = os.path.join(root, f)
            if _is_excluded(DATA_DIR, path):
                continue
            if os.path.splitext(f)[1].lower() in (".csv", ".jsonl", ".json", ".xlsx", ".parquet"):
                out.append(path)
    return sorted(out)


def master_union_report(report_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    raw_files = [r for r in report_rows
                 if r.get("status", "") == "ok"
                 and r["file"].startswith("data/raw/")
                 and r["format"] in ("csv", "jsonl")]
    frames = []
    for r in raw_files:
        df = _load_table(r["path"])
        df = _safe(df)
        if set(STD_COLUMNS) - set(df.columns) == set():
            df["_src"] = r["file"]
            frames.append(df)
    if not frames:
        return {"error": "no raw union sources found"}
    union = pd.concat(frames, ignore_index=True)
    total = len(union)
    rid = union["record_id"].astype(str).str.strip().replace("", pd.NA)
    rid_key = rid.fillna(union["community"].astype(str) + "|" + union["post_id"].astype(str) + "|" + union["comment_id"].astype(str))
    meta = union[["community", "post_id", "comment_id"]].astype(str).agg("|".join, axis=1)
    report = {
        "sources": [r["file"] for r in raw_files],
        "source_count": len(raw_files),
        "raw_rows_union": int(total),
        "rows_with_record_id": int(rid.notna().sum()),
        "unique_record_id": int(rid_key.nunique()),
        "rows_removed_by_record_id": int(total - rid_key.nunique()),
        "dup_by_record_id_pct": round(100.0 * (total - rid_key.nunique()) / max(total, 1), 2),
        "unique_meta_key": int(meta.nunique()),
        "additional_removed_by_meta": int(meta.nunique() - rid_key.nunique()),
    }
    if "vehicle" in union.columns:
        report["unique_by_vehicle"] = {str(k): int(v) for k, v in
                                       union.drop_duplicates("record_id").groupby("vehicle").size().to_dict().items()}
    return report


def main() -> int:
    os.makedirs(AUDIT_DIR, exist_ok=True)
    files = collect_files()
    rows = [audit_file(f, PROJECT_ROOT) for f in files]
    audit_df = pd.DataFrame(rows)
    os.makedirs(AUDIT_DIR, exist_ok=True)
    union = master_union_report(rows)
    for r in rows:
        r.pop("path", None)
        r.pop("error", None)
    audit_df.to_csv(os.path.join(AUDIT_DIR, "facebook_datasets_audit.csv"), index=False)
    with open(os.path.join(AUDIT_DIR, "facebook_datasets_audit.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(AUDIT_DIR, "master_union_report.json"), "w", encoding="utf-8") as f:
        json.dump(union, f, indent=2, ensure_ascii=False)

    cols = ["file", "format", "rows", "columns", "unique_record_id", "unique_post_id",
            "unique_comment_id", "date_range", "duplicate_estimate_pct", "status"]
    show = audit_df[[c for c in cols if c in audit_df]].copy()
    print(show.to_string(index=False))
    print("\nMASTER UNION (all data/raw run CSVs + raw_data_all.jsonl):")
    print(json.dumps(union, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())