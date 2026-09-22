"""End-to-end pipeline test using the synthetic (mock) collector."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pipeline_mock_end_to_end(monkeypatch):
    from src import config_loader
    from src.config_loader import load_settings
    from src.pipeline import Pipeline
    from src.collectors.synthetic_collector import SyntheticCollector

    with tempfile.TemporaryDirectory() as td:
        # isolate data + state into temp dir
        monkeypatch.setattr(config_loader, "PROJECT_ROOT", td)
        for key in list(config_loader.load_settings.cache_clear() or []) + list(
            config_loader.load_vehicles.cache_clear() or []) + list(
            config_loader.load_keywords.cache_clear() or []) + list(
            config_loader.load_taxonomy.cache_clear() or []) + list(
            config_loader.load_communities.cache_clear() or []):
            pass
        monkeypatch.setattr(config_loader, "CONFIG_DIR",
                            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config"))
        monkeypatch.setattr(config_loader, "DATA_DIR", td)
        monkeypatch.setattr(config_loader, "LOGS_DIR", os.path.join(td, "logs"))

        from src.config_loader import ensure_dirs
        ensure_dirs()

        state_path = os.path.join(td, "scraper_state.db")

        cfg = {"pilot": {"data_source": "mock", "max_posts": 8,
                         "max_comments_per_post": 10, "max_replies_per_comment": 5},
               "collection": {}, "processing": {"min_text_length": 3},
               "paths": {"data_dir": td, "raw_dir": os.path.join(td, "raw"),
                         "clean_dir": os.path.join(td, "clean"),
                         "filtered_dir": os.path.join(td, "filtered"),
                         "labeled_dir": os.path.join(td, "labeled"),
                         "output_dir": os.path.join(td, "output")},
               "project": {"version": "test", "scraper_version": "test",
                           "config_version": "test", "keyword_version": "test",
                           "taxonomy_version": "test"},
               "logging": {"level": "ERROR"},
               }

        pipe = Pipeline(cfg, mode="pilot", vehicle="Jaecoo J5", data_source="mock",
                        max_posts=8, state_db_path=state_path)
        stats = pipe.run_scrape()

        assert stats["raw_posts"] > 0
        assert stats["raw_comments"] > 0
        assert stats["unique"] > 0
        assert stats["candidates"] > 0
        assert stats["relevant"] > 0
        assert stats["pda"] >= 0 and stats["acc"] >= 0

        # Idempotency: run again must not duplicate
        stats2 = pipe.run_scrape()
        assert stats2["duplicates"] >= stats["unique"] or stats2["skipped"] > 0

        pipe.state.close()