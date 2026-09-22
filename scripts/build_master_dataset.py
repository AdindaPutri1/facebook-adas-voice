"""STEP 5a: Build facebook_master_raw.csv from all existing FB scrapes.

Reads every table under data/raw (run CSVs + append-only JSONL), concatenates
them preserving provenance, and writes MASTER raw with NO deletes. Deduplication
is handled by the next stage (deduplicate_facebook_data.py).
"""
import argparse
import glob
import os
import sys

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402


def collect_raw_sources() -> list:
    files = []
    for dir_ in vc.load_analysis_config().get("master", {}).get("raw_dirs", ["data/raw"]):
        dir_path = os.path.join(vc.PROJECT_ROOT, dir_)
        files += sorted(glob.glob(os.path.join(dir_path, "*.csv"))) \
            + sorted(glob.glob(os.path.join(dir_path, "*.jsonl")))
    return [f for f in files if "backup" not in os.path.basename(f)]


def load_table(path: str) -> pd.DataFrame:
    if path.endswith(".jsonl"):
        rows = [line for line in open(path, "r", encoding="utf-8") if line.strip()]
        import json
        return pd.DataFrame([json.loads(l) for l in rows])
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_csv = os.path.join(vc.MASTER_DIR, "facebook_master_raw.csv")
    if not args.force and os.path.exists(out_csv):
        vc.log("skip build_master_dataset (exists; use --force) -> " + out_csv)
        return 0
    vc.ensure_output_dirs()

    sources = collect_raw_sources()
    if not sources:
        vc.log("no raw sources found")
        return 1
    frames = []
    for path in sources:
        df = load_table(path)
        if set(vc.STD_COLUMNS) - set(df.columns):
            # tolerate older dumps missing a column by filling it, never dropping text
            for c in vc.STD_COLUMNS:
                if c not in df.columns:
                    df[c] = ""
        # keep author_id fallback (pseudonym used when author_id empty)
        df["_origin"] = os.path.basename(path)
        frames.append(df)
    master = pd.concat(frames, ignore_index=True)
    master = master[[c for c in vc.STD_COLUMNS if c in master.columns] + ["_origin"]]

    vc.save_df(master, out_csv)
    vc.log(f"facebook_master_raw written: rows={len(master)} sources={len(sources)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())