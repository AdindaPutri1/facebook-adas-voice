"""Full pipeline: collect -> dedup -> clean -> identify -> filter -> classify ->
label -> store -> export."""
import logging
import os
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.config_loader import (
    load_settings,
    load_communities,
    load_vehicles,
    load_keywords,
    load_taxonomy,
    resolve_path,
    ensure_dirs,
    config_info,
    LOGS_DIR,
)
from src.models import (
    RawRecord,
    CleanRecord,
    LabeledRecord,
)
from src.storage.state_db import StateDB
from src.storage.data_store import DataStore
from src.parsers.text_parser import parse_raw_item
from src.cleaners.text_cleaner import clean_text
from src.deduplication.deduplicator import deduplicate
from src.filters.keyword_filter import KeywordEngine
from src.filters.relevance_filter import classify_relevance, classify_evidence
from src.classifiers.feature_classifier import VehicleIdentifier, FeatureClassifier
from src.classifiers.experience_classifier import (
    ScenarioClassifier,
    SentimentClassifier,
    ExpectationMismatchClassifier,
    SmoothnessClassifier,
)

log = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, config: Dict, mode: str = "scrape",
                 vehicle: Optional[str] = None,
                 data_source: Optional[str] = None,
                 headless: bool = True, max_posts: Optional[int] = None,
                 state_db_path: Optional[str] = None):
        self.settings = load_settings()
        self.project = self.settings.get("project", {})
        self.collection_cfg = self.settings.get("collection", {})
        self.pilot_cfg = self.settings.get("pilot", {})
        self.processing_cfg = self.settings.get("processing", {})

        if data_source is None:
            # Research/production default is the real Facebook source. Mock is only
            # used when EXPLICITLY requested (--data-source mock / unit tests).
            data_source = self.collection_cfg.get("data_source", "facebook")
        self.data_source = data_source
        self.mode = mode
        self.vehicle_filter = vehicle
        self.max_posts = max_posts
        self.headless = headless

        effective_cfg = dict(self.collection_cfg)
        if mode == "pilot":
            effective_cfg.update(self.pilot_cfg)
        if self.max_posts:
            effective_cfg["max_posts"] = self.max_posts
        self.collector_config = effective_cfg

        ensure_dirs()
        self.state_db_path = state_db_path or os.path.join(
            resolve_path("data_dir"), "scraper_state.db")
        self.state = StateDB(self.state_db_path)
        self.store = DataStore()

        # components
        self.keyword_engine = KeywordEngine(load_keywords())
        self.vehicles = VehicleIdentifier(load_vehicles())
        self.features = FeatureClassifier(load_keywords(), load_taxonomy())
        self.scenarios = ScenarioClassifier()
        self.sentiments = SentimentClassifier()
        self.mismatch = ExpectationMismatchClassifier()
        self.smoothness = SmoothnessClassifier()

        self.run_id = None
        self.stats = {
            "raw_posts": 0,
            "raw_comments": 0,
            "raw_replies": 0,
            "unique": 0,
            "duplicates": 0,
            "skipped": 0,
            "candidates": 0,
            "relevant": 0,
            "pda": 0,
            "acc": 0,
            "noise_dropped": 0,
            "date_skipped": 0,
            "errors": 0,
        }

    # ── run management ──────────────────────────────────────────────────────
    def _begin_run(self, community_name: str) -> None:
        self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        info = config_info()
        self.state.start_run(self.run_id, {
            "vehicle": self.vehicle_filter or "all",
            "community": community_name,
            "data_source": self.data_source,
            "mode": self.mode,
            "start_time": datetime.now(timezone.utc).isoformat(),
            **info,
        })
        log.info("Run started: %s | vehicle=%s | source=%s | mode=%s",
                 self.run_id, self.vehicle_filter or "all", self.data_source, self.mode)

    def _finish_run(self, status: str) -> None:
        self.state.finish_run(
            self.run_id,
            status=status,
            records_collected=self.stats["unique"],
            records_duplicated=self.stats["duplicates"],
            records_skipped=self.stats["skipped"],
            errors=self.stats["errors"],
        )
        log.info("Run finished: %s | status=%s | stats=%s", self.run_id, status, self.stats)

    # ── collection ──────────────────────────────────────────────────────────
    def _build_collector(self):
        if self.data_source == "facebook":
            from src.collectors.facebook_collector import FacebookCollector
            return FacebookCollector(self.collector_config, headless=self.headless)
        if self.data_source == "mock":
            from src.collectors.synthetic_collector import SyntheticCollector
            return SyntheticCollector(self.collector_config)
        raise ValueError(f"Unsupported data_source: {self.data_source}")

    def collect_community(self, community: Dict, collector) -> List[RawRecord]:
        records: List[RawRecord] = []
        post_stats = {"post": 0, "comment": 0, "reply": 0}
        try:
            for post_dict in collector.iter_posts(community):
                post_id = str(post_dict.get("post_id", ""))
                # checkpoint skip
                if self.state.is_post_processed(community.get("community_name", ""), post_id):
                    self.stats["skipped"] += 1
                    continue
                try:
                    post_rec = parse_raw_item(post_dict, community)
                except Exception as e:
                    self._record_error("post", post_id, e)
                    continue
                records.append(post_rec)
                post_stats["post"] += 1

                try:
                    for cdict in collector.iter_comments(post_dict):
                        crec = parse_raw_item(cdict, community)
                        records.append(crec)
                        post_stats["comment"] += 1
                        try:
                            for rdict in collector.iter_replies(cdict):
                                rrec = parse_raw_item(rdict, community)
                                records.append(rrec)
                                post_stats["reply"] += 1
                        except Exception as e:
                            self._record_error("reply", cdict.get("comment_id", ""), e)
                except Exception as e:
                    self._record_error("post", post_id, e)

                self.state.mark_post_processed(
                    community.get("community_name", ""), post_id, "done", self.run_id)
        except Exception as e:
            self._record_error("community", community.get("community_name", ""), e)
            raise

        self.stats["raw_posts"] += post_stats["post"]
        self.stats["raw_comments"] += post_stats["comment"]
        self.stats["raw_replies"] += post_stats["reply"]
        self.stats["noise_dropped"] += getattr(collector, "noise_dropped", 0)
        self.stats["date_skipped"] += getattr(collector, "date_skipped", 0)
        reasons = getattr(collector, "noise_reasons", None)
        if reasons:
            log.info("Community %s: noise dropped=%d, reasons=%s",
                     community.get("community_name", ""), collector.noise_dropped,
                     dict(reasons))
        return records

    def run_scrape(self) -> Dict:
        collector = self._build_collector()
        try:
            collector.check_access()
        except Exception as e:
            log.error("Access check failed: %s", e)
            self._record_error("access", "", e)
            self._finish_run("failed")
            collector.close()
            # Fail loudly: a failed/blocked real source must never silently fall
            # back to synthetic (mock) data.
            raise RuntimeError(
                f"Facebook access check failed ({type(e).__name__}). "
                f"No synthetic fallback used; fix the session/network and retry.") from e

        selected = self._select_communities()

        if self.data_source == "facebook":
            selected = [c for c in selected if (c.get("url") or "").strip()]
            dropped = [c.get("community_name", "?") for c in self._select_communities()
                       if not (c.get("url") or "").strip()]
            for name in dropped:
                log.warning("Skipping community %s: no URL configured (facebook source).", name)

        if not selected:
            if self.data_source == "facebook":
                log.error(
                    "No enabled communities WITH a URL for %s. Add real community URLs to "
                    "config/communities.yaml (set enabled: true) before scraping Facebook.",
                    self.vehicle_filter or "pilot")
                self._record_error("community", "", ValueError("no enabled community with URL"))
                self._finish_run("failed")
                collector.close()
                raise RuntimeError(
                    f"No enabled Facebook community with a URL for '{self.vehicle_filter or 'pilot'}'. "
                    f"Configure real communities in config/communities.yaml and retry. "
                    f"No synthetic fallback used.")
            # mock is only used when explicitly requested (--data-source mock / dev)
            if self.data_source != "mock":
                log.error(
                    "No enabled communities for %s and data_source=%s is not mock.",
                    self.vehicle_filter or "pilot", self.data_source)
                self._record_error("community", "", ValueError("no enabled community"))
                self._finish_run("failed")
                collector.close()
                raise RuntimeError("No enabled communities configured; refusing to run.")
            log.info("No enabled communities found; using synthetic community for %s.",
                     self.vehicle_filter or "pilot")
            selected = [self._mock_community()]

        try:
            for community in selected:
                self._begin_run(community.get("community_name", ""))
                try:
                    records = self.collect_community(community, collector)
                    community_ok = True
                    # Headless Chrome sometimes crashes mid-scrape (session death).
                    # If the session died and nothing was collected, retry ONCE with a
                    # fresh driver instead of silently recording an empty community.
                    if (self.data_source == "facebook" and not records
                            and getattr(collector, "_session_died", False)):
                        log.warning("Session died before collecting from %s; retrying once.",
                                    community.get("community_name", ""))
                        collector._session_died = False
                        time.sleep(5)
                        self._record_error("community", community.get("community_name", ""),
                                           RuntimeError("session died; retried"))
                        retried_records = self.collect_community(community, collector)
                        records = list(retried_records) + list(records)
                except Exception as e:
                    community_ok = False
                    log.error("Community failed (%s): %s",
                              community.get("community_name", ""), e)
                    self._record_error("community", community.get("community_name", ""), e)
                    records = []
                self._persist_and_process(records, community)
                self._finish_run("completed" if community_ok else "failed")
        finally:
            collector.close()

        return self.stats

    def _mock_community(self) -> Dict:
        vehicle = self.vehicle_filter or "Jaecoo J5"
        return {
            "community_name": f"{vehicle} (Mock)",
            "name": f"{vehicle} (Mock)",
            "url": "https://mock.local/community",
            "vehicle": vehicle,
            "type": "mock",
            "enabled": True,
        }

    def _select_communities(self) -> List[Dict]:
        """Pick enabled communities for the target vehicle(s)."""
        communities_cfg = load_communities()
        vehicles_cfg = load_vehicles().get("vehicles", {})
        key_by_canonical = {v.get("canonical_name"): k for k, v in vehicles_cfg.items()}

        selected = []
        for vehicle_key, comms in communities_cfg.get("communities", {}).items():
            canonical = vehicles_cfg.get(vehicle_key, {}).get("canonical_name", vehicle_key)
            if self.vehicle_filter and canonical != self.vehicle_filter:
                continue
            if self.vehicle_filter and str(self.vehicle_filter).lower() not in (
                canonical.lower(), vehicle_key.lower(), str(canonical).lower()):
                continue
            for c in comms:
                c = dict(c)
                c.setdefault("community_name", c.get("name", "unknown"))
                c.setdefault("vehicle", canonical)
                if c.get("enabled", False):
                    selected.append(c)
        return selected

    def _record_error(self, scope: str, ref: str, error: Exception) -> None:
        self.stats["errors"] += 1
        log.error("Error [%s|%s]: %s", scope, ref, error)

    def _clean_and_label(self, records: List[RawRecord]) -> List[LabeledRecord]:
        """Deterministic clean+label pass used for both live collection and
        regeneration of artifacts from raw JSONL (no state-dedup gate)."""
        labeled = []
        for r in records:
            try:
                clean = CleanRecord(
                    record_id=r.record_id, vehicle=r.vehicle, community=r.community,
                    post_id=r.post_id, comment_id=r.comment_id, parent_id=r.parent_id,
                    source_type=r.source_type, date=r.date,
                    text_clean=clean_text(r.text_raw),
                    url=r.url, scraped_at=r.scraped_at,
                )
                lab = self._label(clean)
                labeled.append(lab)
            except Exception as e:
                self._record_error("label", getattr(r, "record_id", "?"), e)
        return labeled

    def rebuild_artifacts_from_raw(self) -> Dict:
        """Regenerate clean/filtered/labeled artifacts from raw_data_all.jsonl.

        Deterministic and independent of the state-dedup gate, so exports can be
        (re)produced even after intermediate per-run CSV files are purged.
        """
        raw_path = os.path.join(resolve_path("raw_dir"), "raw_data_all.jsonl")
        if not os.path.exists(raw_path):
            raise FileNotFoundError(f"raw JSONL not found: {raw_path}")

        records: List[RawRecord] = []
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                import json as _json
                try:
                    item = _json.loads(line)
                    text = str(item.get("text_raw") or "").strip()
                    if not text:
                        continue
                    comment_id = item.get("comment_id")
                    records.append(RawRecord(
                        vehicle=item.get("vehicle") or "",
                        community=item.get("community") or "",
                        community_url=item.get("community_url") or "",
                        post_id=item.get("post_id") or "",
                        comment_id=str(comment_id) if comment_id else None,
                        parent_id=str(item.get("parent_id")) if item.get("parent_id") else None,
                        source_type=(item.get("source_type") or "post").strip().lower(),
                        author_id=None,
                        author_pseudonym=item.get("author_pseudonym"),
                        date=item.get("date"),
                        text_raw=text,
                        url=item.get("url"),
                        scraped_at=item.get("scraped_at"),
                        record_id=item.get("record_id"),
                    ))
                except Exception as e:
                    self._record_error("raw", "regen", e)

        # inline dedup by record_id (community::post_id::comment_id)
        seen = set()
        unique = []
        for r in records:
            if r.record_id in seen:
                continue
            seen.add(r.record_id)
            unique.append(r)
        log.info("Rebuilding artifacts from %d raw records (%d unique).",
                 len(records), len(unique))

        self.run_id = f"regen_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clean_recs = [CleanRecord(
            record_id=r.record_id, vehicle=r.vehicle, community=r.community,
            post_id=r.post_id, comment_id=r.comment_id, parent_id=r.parent_id,
            source_type=r.source_type, date=r.date,
            text_clean=clean_text(r.text_raw),
            url=r.url, scraped_at=r.scraped_at,
        ) for r in unique]
        clean_rows = [c.to_row() for c in clean_recs]
        self.store.write_rows_csv("clean_dir", f"clean_data_{self.run_id}.csv", clean_rows)

        labeled = self._clean_and_label(unique)
        lab_rows = [l.to_row() for l in labeled]
        self.store.write_rows_csv(
            "filtered_dir", f"relevant_adas_{self.run_id}.csv",
            [r for r in lab_rows if r["relevant"] == "relevant"])
        self.store.write_rows_csv("labeled_dir", f"labeled_experience_{self.run_id}.csv", lab_rows)
        log.info("Rebuild done: clean=%d labeled=%d", len(clean_rows), len(lab_rows))
        return {"clean": len(clean_rows), "labeled": len(lab_rows)}

    # ── LLM enhance ─────────────────────────────────────────────────────────
    def _load_raw_live_records(self) -> List[RawRecord]:
        """All unique live records from the canonical JSONL (mock excluded)."""
        raw_path = os.path.join(resolve_path("raw_dir"), "raw_data_all.jsonl")
        if not os.path.exists(raw_path):
            raise FileNotFoundError(f"raw JSONL not found: {raw_path}")
        import json as _json

        records: List[RawRecord] = []
        with open(raw_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = _json.loads(line)
                    text = str(item.get("text_raw") or "").strip()
                    if not text:
                        continue
                    community = str(item.get("community") or "")
                    source = str(item.get("url") or "") + str(item.get("community_url") or "")
                    if "(mock)" in community.lower() or "mock.local" in source.lower():
                        continue
                    comment_id = item.get("comment_id")
                    records.append(RawRecord(
                        vehicle=item.get("vehicle") or "",
                        community=community,
                        community_url=item.get("community_url") or "",
                        post_id=item.get("post_id") or "",
                        comment_id=str(comment_id) if comment_id else None,
                        parent_id=str(item.get("parent_id")) if item.get("parent_id") else None,
                        source_type=(item.get("source_type") or "post").strip().lower(),
                        author_id=None,
                        author_pseudonym=item.get("author_pseudonym"),
                        date=item.get("date"),
                        text_raw=text,
                        url=item.get("url"),
                        scraped_at=item.get("scraped_at"),
                        record_id=item.get("record_id"),
                    ))
                except Exception as e:
                    self._record_error("raw", "enhance", e)
        seen = set()
        unique = []
        for r in records:
            if r.record_id in seen:
                continue
            seen.add(r.record_id)
            unique.append(r)
        log.info("Loaded %d unique live raw records for enhance (from %d lines).",
                 len(unique), len(records))
        return unique

    def _llm_label(self, record: CleanRecord, classifier, labels: Dict) -> LabeledRecord:
        """Build a LabeledRecord from validated LLM labels (rule fallbacks kept)."""
        text = record.text_clean
        vehicle = self.vehicles.identify(text, record.vehicle)
        feature = labels.get("feature", "unknown")
        if feature == "unknown":
            subfeature = "not_stated"
        else:
            subfeature = labels.get("subfeature", "not_stated")
        scenario = labels.get("scenario", "not_stated")
        evidence = labels.get("evidence_type", "uncertain")
        sentiment = labels.get("sentiment", "uncertain")
        relevant = labels.get("relevant", "uncertain")
        mismatch = labels.get("expectation_mismatch", "unclear")
        smooth = labels.get("smoothness", "not_stated")
        confidence = labels.get("confidence") or (
            "high" if evidence == "direct_experience" and relevant == "relevant"
            else "medium" if relevant in ("relevant", "uncertain") else "low")
        summary = labels.get("experience_summary") or text[:240]
        _, matched = self.features.classify(text)
        keyword_candidate = self.keyword_engine.is_candidate(text) or relevant == "relevant"
        return LabeledRecord(
            record_id=record.record_id,
            vehicle=vehicle,
            text_clean=text,
            feature=feature,
            subfeature=subfeature,
            scenario=scenario,
            experience_summary=summary[:500],
            sentiment=sentiment,
            evidence_type=evidence,
            relevant=relevant,
            expectation_mismatch=mismatch,
            smoothness=smooth,
            confidence=confidence,
            keyword_candidate=keyword_candidate,
            matched_keywords=matched,
            source_type=record.source_type,
            date=record.date,
            community=record.community,
            source_reference=record.url or "",
            author_pseudonym=self._pseudonym(record.record_id),
            labeler="llm",
        )

    def run_enhance(self) -> Dict:
        """Re-label the full live raw JSONL with the LLM classifier (cached).

        Writes a labeled_experience_enhance_<timestamp>.csv artifact. Every
        failure to reach/parse the LLM falls back to the rule-based labeler and
        is recorded via the labeler column, so research provenance stays explicit.
        """
        llm_cfg = self.settings.get("llm", {}) or {}
        if not llm_cfg.get("enabled", False):
            raise RuntimeError(
                "LLM enhance is disabled. Set llm.enabled: true and configure "
                "llm.endpoint / llm.deployment (config/settings.yaml); provide the "
                "API key via env var (llm.api_key_env). No synthetic or dummy "
                "labels were produced.")

        logger = logging.getLogger("pipeline")
        from src.classifiers.llm_classifier import LLMClassifier, LLMError
        classifier = LLMClassifier(llm_cfg)
        self.run_id = f"enhance_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        raw_records = self._load_raw_live_records()
        clean_recs: List[CleanRecord] = []
        for r in raw_records:
            try:
                clean_recs.append(CleanRecord(
                    record_id=r.record_id, vehicle=r.vehicle, community=r.community,
                    post_id=r.post_id, comment_id=r.comment_id, parent_id=r.parent_id,
                    source_type=r.source_type, date=r.date,
                    text_clean=clean_text(r.text_raw),
                    url=r.url, scraped_at=r.scraped_at,
                ))
            except Exception as e:
                self._record_error("clean", r.record_id, e)

        # Scope: 'candidates' (default) labels only records the rules already flag
        # (keyword candidate or relevant); everything else keeps the rule-based
        # label in the exported merge. 'all' labels the entire live dataset.
        scope = str(llm_cfg.get("scope") or "candidates").lower()
        scoped = [
            c for c in clean_recs
            if scope == "all" or self.keyword_engine.is_candidate(c.text_clean)
        ]
        log.info("Enhance scope=%s: %d of %d live records will be LLM-labeled.",
                 scope, len(scoped), len(clean_recs))

        results = {}
        try:
            results = classifier.classify_many(scoped)
        except LLMError as e:
            # Quota exhausted / endpoint down: do NOT let one failed run abort the
            # enhancement. Records without LLM labels fall back to the rule-based
            # labeler (provenance kept via labeler=rule), and the run still writes
            # its artifact so exports keep working. Re-running later upgrades the
            # missing ones from cache.
            logger.warning("LLM enhance unavailable (%s); %d scoped records will "
                           "use rule-based labels this run.", e, len(scoped))
        labeled: List[LabeledRecord] = []
        n_llm = 0
        n_rule = 0
        for c in scoped:
            labels = results.get(c.record_id)
            if labels is None:
                logger.warning("LLM labeling failed for %s; using rule-based.", c.record_id)
                lab = self._label(c)
                n_rule += 1
            else:
                lab = self._llm_label(c, classifier, labels)
                n_llm += 1
            labeled.append(lab)

        rows = [l.to_row() for l in labeled]
        self.store.write_rows_csv("labeled_dir", f"labeled_experience_{self.run_id}.csv", rows)
        stats = {
            "total_live": len(clean_recs),
            "scoped_records": len(labeled),
            "llm_labeled": n_llm,
            "rule_fallback": n_rule,
            "relevant_records": sum(1 for l in labeled if l.relevant == "relevant"),
            "feature_counts": dict(Counter(l.feature for l in labeled)),
        }
        logger.info("Enhance done: %s", stats)
        return stats

    # ── processing ──────────────────────────────────────────────────────────
    def _persist_and_process(self, records: List[RawRecord], community: Dict) -> None:
        if not records:
            return

        # 1) raw storage (always preserved)
        raw_rows = [r.to_row() for r in records]
        self.store.write_rows_csv("raw_dir", f"raw_data_{self.run_id}.csv", raw_rows)
        self.store.append_rows_jsonl("raw_dir", "raw_data_all.jsonl", raw_rows)

        # 2) dedup
        unique, dups, skipped = deduplicate(records, state=self.state)
        self.stats["duplicates"] += dups
        self.stats["skipped"] += skipped
        self.stats["unique"] += len(unique)

        # 3) clean
        clean_recs = []
        for r in unique:
            try:
                clean_recs.append(CleanRecord(
                    record_id=r.record_id, vehicle=r.vehicle, community=r.community,
                    post_id=r.post_id, comment_id=r.comment_id, parent_id=r.parent_id,
                    source_type=r.source_type, date=r.date,
                    text_clean=clean_text(r.text_raw),
                    url=r.url, scraped_at=r.scraped_at,
                ))
            except Exception as e:
                self._record_error("clean", r.record_id, e)
        clean_rows = [c.to_row() for c in clean_recs]
        self.store.write_rows_csv("clean_dir", f"clean_data_{self.run_id}.csv", clean_rows)

        # 4) filter + classify + label
        labeled = []
        for c in clean_recs:
            try:
                lab = self._label(c)
                if lab.keyword_candidate:
                    self.stats["candidates"] += 1
                if lab.relevant == "relevant":
                    self.stats["relevant"] += 1
                    if lab.feature in ("PDA", "both"):
                        self.stats["pda"] += 1
                    if lab.feature in ("ACC", "both"):
                        self.stats["acc"] += 1
                labeled.append(lab)
            except Exception as e:
                self._record_error("label", c.record_id, e)

        lab_rows = [l.to_row() for l in labeled]
        self.store.write_rows_csv("filtered_dir", f"relevant_adas_{self.run_id}.csv",
                                  [r for r in lab_rows if r["relevant"] == "relevant"])
        self.store.write_rows_csv("labeled_dir", f"labeled_experience_{self.run_id}.csv", lab_rows)

    def _label(self, record: CleanRecord) -> LabeledRecord:
        text = record.text_clean
        vehicle = self.vehicles.identify(text, record.vehicle)

        feature, matched = self.features.classify(text)
        keyword_candidate = self.keyword_engine.is_candidate(text)
        relevant = classify_relevance(text, [m[1] for m in self.features.kw.match(text)],
                                      keyword_candidate)
        evidence = classify_evidence(text)
        scenario = self.scenarios.classify(text)
        sentiment = self.sentiments.classify(text)
        mismatch = self.mismatch.classify(text)
        smooth = self.smoothness.classify(text)
        subfeature = self.features.classify_subfeature(text, feature)

        # Confidence heuristic
        if evidence == "direct_experience" and relevant == "relevant":
            confidence = "high"
        elif relevant in ("relevant", "uncertain"):
            confidence = "medium"
        else:
            confidence = "low"

        return LabeledRecord(
            record_id=record.record_id,
            vehicle=vehicle,
            text_clean=text,
            feature=feature,
            subfeature=subfeature,
            scenario=scenario,
            experience_summary=text[:240],
            sentiment=sentiment,
            evidence_type=evidence,
            relevant=relevant,
            expectation_mismatch=mismatch,
            smoothness=smooth,
            confidence=confidence,
            keyword_candidate=keyword_candidate,
            matched_keywords=matched,
            source_type=record.source_type,
            date=record.date,
            community=record.community,
            source_reference=record.url or "",
            author_pseudonym=self._pseudonym(record.record_id),
        )

    @staticmethod
    def _pseudonym(record_id: str) -> str:
        import hashlib
        return "USER_" + hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:8]