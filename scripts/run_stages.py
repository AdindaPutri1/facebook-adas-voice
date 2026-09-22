"""Run pipelines by stage. Wraps the src modules over the stored data layers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.exporters.exporter import (
    load_raw_records,
    load_clean_records,
    load_labeled_records,
    generate_summary,
    generate_customer_voice,
    export_all,
)
from src.config_loader import ensure_dirs

ensure_dirs()


def main():
    import argparse

    p = argparse.ArgumentParser(description="Stage runner")
    p.add_argument("stage", choices=["raw", "clean", "filter", "annotate", "summary", "export"])
    args = p.parse_args()

    raw = load_raw_records()
    clean = load_clean_records()
    labeled = load_labeled_records()

    if args.stage == "raw":
        print(f"raw records: {len(raw)}")
        if not raw.empty:
            print(raw.head().to_string())
    elif args.stage == "clean":
        print(f"clean records: {len(clean)}")
    elif args.stage == "filter":
        print(f"labeled records: {len(labeled)}")
        rel = labeled[labeled["relevant"] == "relevant"]
        print(f"relevant: {len(rel)}")
        print(rel[["vehicle", "feature", "relevant", "evidence_type"]].head().to_string())
    elif args.stage == "annotate":
        print("Annotate stage: review 'uncertain' rows in data/labeled.")
        print(f"uncertain rows: {(labeled['relevant'] == 'uncertain').sum() if not labeled.empty else 0}")
    elif args.stage == "summary":
        s = generate_summary()
        import json
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif args.stage == "export":
        export_all()
        print("Exports written to data/output/")
        for f in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "output")):
            print("  ", f)


if __name__ == "__main__":
    main()