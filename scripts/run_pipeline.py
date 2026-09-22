"""V2 pipeline orchestrator. Run:

    python scripts/run_pipeline.py                 # run all stages
    python scripts/run_pipeline.py --stage clean   # run a single stage
    python scripts/run_pipeline.py --force         # re-run even if outputs exist
"""
import argparse
import glob
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402

STAGE_SCRIPT = {
    "audit_facebook_datasets": "audit_facebook_datasets.py",
    "build_master_dataset": "build_master_dataset.py",
    "deduplicate_facebook_data": "deduplicate_facebook_data.py",
    "clean_facebook_data": "clean_facebook_data.py",
    "classify_vehicle": "classify_vehicle.py",
    "filter_adas_relevance": "filter_adas_relevance.py",
    "classify_experience": "classify_experience.py",
    "split_by_vehicle": "split_by_vehicle.py",
    "generate_summary": "generate_summary.py",
}


def run_stage(name: str, force: bool, quiet_stdout: bool = False) -> int:
    script = os.path.join(SCRIPT_DIR, STAGE_SCRIPT[name])
    cmd = [sys.executable, script]
    if force:
        cmd.append("--force")
    vc.log(f"== stage {name}: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=vc.PROJECT_ROOT, capture_output=True, text=True)
    if not quiet_stdout:
        sys.stdout.write(res.stdout)
    if res.stderr.strip():
        sys.stderr.write(res.stderr)
    return res.returncode


def print_tree() -> None:
    vc.log("outputs under data/output/by_vehicle_v2:")
    for root, _, files in os.walk(vc.OUTPUT_ROOT):
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), vc.OUTPUT_ROOT)
            size = os.path.getsize(os.path.join(root, f))
            print(f"  {rel} [{size:,} B]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", action="append", choices=list(STAGE_SCRIPT),
                        help="run only these stages (repeatable)")
    parser.add_argument("--force", action="store_true",
                        help="re-run stages even if outputs already exist")
    args = parser.parse_args()

    stages = args.stage or vc.load_analysis_config().get("stages", list(STAGE_SCRIPT))
    # audit is a standalone report; include it unless explicitly excluded
    logdir = os.path.join(vc.PROJECT_ROOT, "logs")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, f"pipeline_v2_{datetime.now():%Y%m%d_%H%M%S}.log")
    vc.log(f"pipeline log: {logfile}")

    for name in stages:
        rc = run_stage(name, args.force, quiet_stdout=(name == "audit_facebook_datasets"))
        if rc != 0:
            vc.log(f"STAGE FAILED: {name} (rc={rc})")
            return rc
    print_tree()
    summary = os.path.join(vc.MASTER_DIR, "processing_summary.json")
    if os.path.exists(summary):
        import json
        data = json.load(open(summary, "r", encoding="utf-8"))
        vc.log(f"relevant_records={data['adas']['relevant_records']} "
               f"review={data['unknown_or_review']}")
    vc.log("pipeline v2 finished OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())