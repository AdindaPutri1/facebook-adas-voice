"""CLI entry point.

Research/production scraping uses the real Facebook source by default. Synthetic
(mock) data is ONLY available via an explicit --data-source mock flag and is
excluded from all exports.

Examples:
    python -m src.main --mode scrape --vehicle "Jaecoo J5" --data-source facebook
    python -m src.main --mode scrapetest --vehicle "Jaecoo J5" --data-source mock   # dev only
    python -m src.main --mode scrape --vehicle "Toyota Zenix" --data-source facebook --max-posts 10
    python -m src.main --mode enhance   # re-label the full live dataset via Azure OpenAI (labeler=llm)
    python -m src.main --export
"""
import argparse
import logging
import os
import sys
from datetime import datetime

from src.config_loader import (
    ensure_dirs,
    LOGS_DIR,
    load_settings,
)
from src.storage.state_db import StateDB
from src.exporters.exporter import export_all
from src.pipeline import Pipeline

LOG_SETUP_DONE = False


def setup_logging(run_tag: str = "main") -> None:
    global LOG_SETUP_DONE
    if LOG_SETUP_DONE:
        return
    ensure_dirs()
    settings = load_settings()
    level = getattr(logging, str(settings.get("logging", {}).get("level", "INFO")).upper(), logging.INFO)
    fmt = settings.get("logging", {}).get(
        "format", "%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = os.path.join(LOGS_DIR, f"{run_tag}_{stamp}.log")

    handlers = [logging.StreamHandler(sys.stdout)]
    if hasattr(sys.stdout, "reconfigure"):  # py3.7+ TextIOWrapper
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
    LOG_SETUP_DONE = True
    logging.getLogger("pipeline").info("Log initialized at %s", logfile)


def cmd_scrape(args) -> int:
    setup_logging("scrape")
    pipeline = Pipeline(
        load_settings(),
        mode=args.mode,
        vehicle=args.vehicle,
        data_source=args.data_source,
        headless=not args.headed,
        max_posts=args.max_posts,
    )
    stats = pipeline.run_scrape()
    print("=== SCRAPE COMPLETE ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


def cmd_resume(args) -> int:
    setup_logging("resume")
    from src.config_loader import resolve_path
    import os as _os
    db_path = _os.path.join(resolve_path("data_dir"), "scraper_state.db")
    db = StateDB(db_path)
    runs = db.list_runs()
    if not runs:
        print("No previous runs found. Nothing to resume.")
        db.close()
        return 0

    # pick the latest run that isn't completed
    target = None
    for r in runs:
        if r["status"] in ("running", "failed"):
            target = r
            break
    if target is None:
        target = runs[0]

    print(f"Resuming from run {target['run_id']} (status={target['status']}, "
          f"vehicle={target['vehicle']}, source={target['data_source']})")
    pipeline = Pipeline(
        load_settings(),
        mode=target.get("mode", "scrape"),
        vehicle=target.get("vehicle") or None,
        data_source=target.get("data_source"),
        headless=not args.headed,
    )
    # resume semantics: same collector, state DB already knows processed posts
    stats = pipeline.run_scrape()
    print("=== RESUME COMPLETE ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    db.close()
    return 0


def cmd_enhance(args) -> int:
    setup_logging("enhance")
    pipeline = Pipeline(load_settings(), mode="enhance")
    stats = pipeline.run_enhance()
    print("=== ENHANCE COMPLETE ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("Run the export to fold LLM labels into the report: python -m src.main --mode export")
    return 0


def cmd_export(args) -> int:
    setup_logging("export")
    from src.config_loader import resolve_path
    from src.exporters.exporter import load_raw_records, load_clean_records, load_labeled_records

    labeled_dir = os.path.join(resolve_path("labeled_dir"), "")
    if not any(f.startswith("labeled_experience_") and f.endswith(".csv")
               for f in os.listdir(labeled_dir)):
        print("No labeled artifacts found; rebuilding from raw JSONL...")
        Pipeline(load_settings(), mode="export").rebuild_artifacts_from_raw()

    raw = load_raw_records()
    clean = load_clean_records()
    labeled = load_labeled_records()
    print(f"raw={len(raw)} clean={len(clean)} labeled={len(labeled)}")
    out = export_all()
    for k, paths in out.items():
        print(f"  {k}: {paths}")
    return 0


def cmd_login(args) -> int:
    setup_logging("login")
    from src.collectors.facebook_session import interactive_login
    try:
        interactive_login()
    except RuntimeError as e:
        print(f"Login flow aborted: {e}")
        return 1
    return 0


def cmd_discover(args) -> int:
    setup_logging("discover")
    from src.config_loader import resolve_path, load_communities
    import os as _os
    db = StateDB(_os.path.join(resolve_path("data_dir"), "scraper_state.db"))
    cfg = load_communities()
    count = 0
    for vehicle_key, comms in cfg.get("communities", {}).items():
        for c in comms:
            db.upsert_discovery({
                "community_name": c.get("name") or c.get("community_name", "unknown"),
                "url": c.get("url", ""),
                "vehicle": c.get("vehicle") or vehicle_key,
                "type": c.get("type", "unknown"),
                "accessibility": c.get("accessibility", "unknown"),
                "discovery_date": datetime.now().date().isoformat(),
                "notes": c.get("notes", ""),
            })
            count += 1
    print(f"Recorded {count} communities in discovery log (SQLite).")
    db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Facebook ADAS customer-voice research pipeline",
    )
    p.add_argument("--mode", choices=["pilot", "scrape", "export", "enhance", "resume", "discover", "login"],
                   default="pilot", help="Operation mode")
    p.add_argument("--vehicle", default=None, help="Canonical vehicle name filter")
    p.add_argument("--data-source", choices=["facebook", "mock"], default=None,
                   help="Override data source")
    p.add_argument("--max-posts", type=int, default=None,
                   help="Bounded maximum posts for this run")
    p.add_argument("--headed", action="store_true",
                   help="Do not use headless browser (facebook source only)")
    return p


def main():
    args = build_parser().parse_args()
    if args.mode == "login":
        return cmd_login(args)
    if args.mode == "export":
        return cmd_export(args)
    if args.mode == "enhance":
        return cmd_enhance(args)
    if args.mode == "resume":
        return cmd_resume(args)
    if args.mode == "discover":
        return cmd_discover(args)
    return cmd_scrape(args)


if __name__ == "__main__":
    sys.exit(main())