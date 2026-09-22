"""LLM-based labeling for customer-voice ADAS research.

Provider-agnostic: works against Azure OpenAI (provider='azure'), any
OpenAI-compatible server such as Google Gemini's OpenAI-compatible gateway
(provider='google_gemini') or a local Ollama (provider='openai_compatible').

Offline-safe design:
- Runs only via the explicit 'enhance' mode; the rule-based labeler stays the
  default production path.
- Every LLM output is validated against the same enum constraints the rule-based
  labeler uses (src/models.py) and coerced to safe defaults otherwise, so a
  malformed response can never corrupt downstream aggregations.
- Determinism & cost: temperature=0 plus a persistent per-record cache
  (data/llm_cache.jsonl), so re-running enhance/export never re-calls the API.
- No secrets in source: an API key (Azure only) is read from an environment
  variable.

Credentials are deliberately NOT in code and NOT logged.
"""
import json
import logging
import os
import random
import time
from typing import Dict, List, Optional

from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.config_loader import resolve_path
from src.models import CleanRecord

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClassifier:
    """OpenAI-compatible chat labeler for customer-voice records (local/cloud)."""

    FEATURES = (
        "PDA", "ACC", "LCC", "LKA", "LDW", "LDP", "ELK", "AEB", "FCW",
        "DMS", "ALC", "TSR", "BSD", "RCTA", "RCW", "both", "unknown",
    )
    RELEVANCE = ("relevant", "not_relevant", "uncertain")
    EVIDENCE = (
        "direct_experience", "opinion", "question",
        "hearsay", "specification", "uncertain",
    )
    SENTIMENT = ("positive", "negative", "neutral", "mixed", "uncertain")
    MISMATCH = ("yes", "no", "unclear")
    SMOOTHNESS = ("smooth", "slightly_abrupt", "abrupt", "very_abrupt", "not_stated")
    CONFIDENCE = ("high", "medium", "low")

    # Compact few-shot demos that help small local models (e.g. phi3) stay in
    # schema instead of over-answering "unknown".
    EXAMPLES = (
        ("PDA pas di macet dia juga jalan sendiri ngikuti mobil depan, lumayan.",
         '{"feature": "PDA", "subfeature": "following", "scenario": "traffic_jam", '
         '"evidence_type": "direct_experience", "sentiment": "positive", '
         '"relevant": "relevant", "expectation_mismatch": "no", "smoothness": '
         '"smooth", "confidence": "high", "experience_summary": "PDA bekerja baik '
         'mengikuti mobil depan di kemacetan."}'),
        ("ACC Toyota Zenix ini batas bawahnya 40km/jam, di dalam kota percuma.",
         '{"feature": "ACC", "subfeature": "speed_range", "scenario": "city_stop_'
         'and_go", "evidence_type": "opinion", "sentiment": "negative", '
         '"relevant": "relevant", "expectation_mismatch": "yes", "smoothness": '
         '"not_stated", "confidence": "medium", "experience_summary": "ACC tidak '
         'berguna di dalam kota karena batas kecepatan minimalnya."}'),
        ("Rame banget nih grup, besok mau testdrive.",
         '{"feature": "unknown", "subfeature": "not_stated", "scenario": '
         '"not_stated", "evidence_type": "question", "sentiment": "neutral", '
         '"relevant": "not_relevant", "expectation_mismatch": "unclear", '
         '"smoothness": "not_stated", "confidence": "low", "experience_summary": '
         '"Tidak ada pengalaman yang dilaporkan."}'),
    )

    def __init__(self, config: Dict):
        self.enabled = bool(config.get("enabled", False))
        self.provider = str(config.get("provider") or "azure").lower()
        if self.provider not in ("azure", "openai_compatible", "google_gemini"):
            raise LLMError(f"Unsupported llm.provider '{self.provider}' "
                           "(expected 'azure', 'openai_compatible' or 'google_gemini').")
        self.endpoint = str(config.get("endpoint") or "").rstrip("/")
        if self.provider == "google_gemini" and not self.endpoint:
            self.endpoint = "https://generativelanguage.googleapis.com"
        self.deployment = str(config.get("deployment") or "")
        self.model = str(config.get("model") or self.deployment or "")
        self.api_version = str(config.get("api_version") or "2024-06-01")
        key_env = str(config.get("api_key_env") or "AZURE_OPENAI_API_KEY")
        self.api_key = os.environ.get(key_env, "") or os.environ.get("AZURE_OPENAI_API_KEY", "")
        if self.provider == "google_gemini":
            # prefer the dedicated env var, fall back to a generic bearer key var
            self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        try:
            self.temperature = float(config.get("temperature", 0))
        except (TypeError, ValueError):
            self.temperature = 0.0
        try:
            self.timeout = int(config.get("timeout_seconds", 120))
        except (TypeError, ValueError):
            self.timeout = 120
        try:
            self.batch_size = max(1, int(config.get("batch_size", 4)))
        except (TypeError, ValueError):
            self.batch_size = 4
        try:
            self.max_retries = max(1, int(config.get("max_retries", 7)))
        except (TypeError, ValueError):
            self.max_retries = 7
        try:
            self.retry_base_seconds = max(1.0, float(config.get("retry_base_seconds", 5)))
        except (TypeError, ValueError):
            self.retry_base_seconds = 5.0
        cache_file = str(config.get("cache_file") or "") or os.path.join(
            resolve_path("data_dir"), "llm_cache.jsonl")
        self.cache_file = os.path.abspath(cache_file)
        self._cache: Dict[str, Dict] = self._load_cache()

        if self.enabled:
            missing = [name for name, val in (("endpoint", self.endpoint),
                                              ("deployment", self.deployment))
                       if not val]
            if missing:
                raise LLMError(
                    "LLM enabled but missing required config: llm." +
                    ", llm.".join(missing) +
                    " (config/settings.yaml). No labeler ran.")
            if self.provider in ("azure", "google_gemini") and not self.api_key:
                raise LLMError(
                    f"LLM provider '{self.provider}' requires an API key via env var "
                    f"'{key_env}' (no secrets in source). No labeler ran.")

    # ── cache ──────────────────────────────────────────────────────────────
    def _load_cache(self) -> Dict[str, Dict]:
        """Load previously labeled records from the append-only JSONL cache."""
        cache: Dict[str, Dict] = {}
        if not os.path.exists(self.cache_file):
            return cache
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        rid = entry.get("record_id")
                        if rid and "labels" in entry:
                            cache[rid] = entry["labels"]
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            log.warning("Could not read LLM cache %s: %s", self.cache_file, e)
        return cache

    def _persist(self, record_id: str, labels: Dict) -> None:
        try:
            with open(self.cache_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"record_id": record_id, "labels": labels},
                                   ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("Could not write LLM cache %s: %s", self.cache_file, e)

    # ── classification ─────────────────────────────────────────────────────
    def classify(self, record: CleanRecord) -> Dict:
        """Return validated label fields for a clean record (cached)."""
        return self.classify_many([record])[record.record_id]

    def classify_many(self, records: List[CleanRecord]) -> Dict[str, Dict]:
        """Label several records, batching API calls (deterministic, cached).

        Returns {record_id: labels}. Records already in cache are not re-sent.
        A batch that the model mangles falls back to one call per record inside
        that batch, so a single bad batch never loses labels for the group.
        """
        results: Dict[str, Dict] = {}
        pending = [r for r in records if r.record_id not in self._cache]
        for r in records:
            if r.record_id in self._cache:
                results[r.record_id] = dict(self._cache[r.record_id])
        bs = self.batch_size
        for i in range(0, len(pending), bs):
            batch = pending[i:i + bs]
            got = self._classify_batch(batch)
            for rec in batch:
                labels = got.get(rec.record_id)
                if labels is None:
                    try:
                        labels = self._validate(self._call(self._messages(rec)))
                    except Exception as e:
                        log.warning("Per-record LLM labeling failed for %s (%s); "
                                    "record will fall back to rule-based.", rec.record_id, e)
                        labels = None
                if labels is not None:
                    self._cache[rec.record_id] = labels
                    self._persist(rec.record_id, labels)
                results[rec.record_id] = labels
        return results

    def _classify_batch(self, records: List[CleanRecord]) -> Dict[str, Optional[Dict]]:
        if len(records) == 1:
            content = self._call(self._messages(records[0]))
            try:
                return {records[0].record_id: self._validate(content)}
            except Exception:
                return {records[0].record_id: None}
        try:
            content = self._call(self._messages_many(records))
            parsed = self._parse_batch(content)
        except Exception as e:
            log.warning("Batch of %d failed (%s); falling back per record.",
                        len(records), e)
            return {}
        out: Dict[str, Optional[Dict]] = {}
        for idx, rec in enumerate(records):
            inner = parsed.get(str(idx), parsed.get(idx))
            if isinstance(inner, dict):
                try:
                    out[rec.record_id] = self._validate(json.dumps(inner))
                except Exception:
                    out[rec.record_id] = None
            elif isinstance(inner, str):
                try:
                    out[rec.record_id] = self._validate(inner)
                except Exception:
                    out[rec.record_id] = None
            else:
                out[rec.record_id] = None
        return out

    # ── prompt ─────────────────────────────────────────────────────────────
    def _messages(self, record: CleanRecord) -> List[Dict]:
        system = self._system_prompt()
        user = (
            "Teks:\n{text}\n\n"
            "Vehicle yang didiskusikan: {vehicle}\n\n"
            'Kembalikan JSON: {{"feature": "...", "subfeature": "...", "scenario": '
            '"...", "evidence_type": "...", "sentiment": "...", "relevant": "...", '
            '"expectation_mismatch": "...", "smoothness": "...", "confidence": '
            '"...", "experience_summary": "..."}}'
        ).format(text=record.text_clean[:4000], vehicle=record.vehicle or "unknown")
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _messages_many(self, records: List[CleanRecord]) -> List[Dict]:
        system = self._system_prompt()
        lines = [
            f"[{idx}] (vehicle: {r.vehicle or 'unknown'})\n{r.text_clean[:900]}"
            for idx, r in enumerate(records)
        ]
        user = (
            "Berikut beberapa teks pengguna yang DINOMORI. Beri label untuk setiap "
            "teks secara terpisah.\n\n" + "\n\n".join(lines) + "\n\n"
            'Kembalikan SATU objek JSON dengan satu kunci per nomor, contoh: '
            '{{"0": {{"feature": "...", ...}}, "1": {{"feature": "...", ...}}}}. '
            "Gunakan skema yang sama untuk setiap entri.\n"
            "Hanya JSON, tanpa teks lain, tanpa markdown."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _parse_batch(self, content: str) -> Dict:
        obj = self._extract_json(content)
        if isinstance(obj, list):
            return {str(i): v for i, v in enumerate(obj)}
        if isinstance(obj, dict):
            return obj
        raise LLMError("Batch LLM output is not a JSON object/list.")

    def _system_prompt(self) -> str:
        return (
            "Anda peneliti customer-voice ADAS mobil (grup FB Indonesia). "
            "Berdasarkan SATU teks pengguna. Hanya JSON tanpa teks/markdown lain.\n"
            "Pilih 'feature' satu dari: " + ", ".join(self.FEATURES) + ".\n"
            "Istilah per merek: PDA=Jaecoo proactive driving assist; "
            "ACC/DRCC/ICC=cruise; LCC=lane centering; LKA/LTA=lane keeping; "
            "LDW/LDP/ELK=lane departure; AEB/PCS=pengereman darurat; FCW=fwd "
            "collision warning; DMS=monitor pengemudi; ALC=auto lane change; "
            "TSR=traffic sign; BSD=blind spot; RCTA=rear cross traffic; "
            "RCW=rear collision.\n"
            "'unknown' jika teks tak membahas fitur ADAS.\n"
            "Enumerasi WAJIB:\n"
            "evidence_type: direct_experience|opinion|question|hearsay|specification|uncertain\n"
            "sentiment: positive|negative|neutral|mixed|uncertain\n"
            "relevant: relevant|not_relevant|uncertain\n"
            "expectation_mismatch: yes|no|unclear\n"
            "smoothness: smooth|slightly_abrupt|abrupt|very_abrupt|not_stated\n"
            "confidence: high|medium|low\n"
            "subfeature & scenario: string singkat lowercase, atau 'not_stated'. "
            "Contoh subfeature 'following', scenario 'highway_tol,curve'.\n"
            "experience_summary: ringkasan 1 kalimat Bahasa Indonesia dari "
            "pengalaman user, atau 'Tidak ada pengalaman yang dilaporkan.'"
        ) + "\n\n" + "\n".join(
            f"Contoh:\n{text}\nJawaban benar: {label}"
            for text, label in self.EXAMPLES
        )

    # ── transport ──────────────────────────────────────────────────────────
    def _call(self, messages: List[Dict]) -> str:
        if not self.enabled:
            raise LLMError("LLM labeler is disabled (llm.enabled=false).")
        if self.provider == "azure":
            url = (f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions"
                   f"?api-version={self.api_version}")
            headers = {"Content-Type": "application/json", "api-key": self.api_key}
        elif self.provider == "google_gemini":
            # Gemini ships an OpenAI-compatible gateway (free tier available):
            #   POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
            url = f"{self.endpoint}/v1beta/openai/chat/completions"
            headers = {"Content-Type": "application/json",
                       "Authorization": f"Bearer {self.api_key}"}
        else:  # openai_compatible (Ollama, LM Studio, ...)
            base = self.endpoint
            if not base.endswith("/v1"):
                base += "/v1"
            url = f"{base}/chat/completions"
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
        body = json.dumps({
            "model": self.model or self.deployment,
            "messages": messages,
            "temperature": self.temperature,
        }).encode("utf-8")
        req = Request(url, data=body, headers=headers)
        retryable = (500, 502, 503, 504)
        rate_limited = (429,)
        last_detail = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    break
            except HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                if e.code in rate_limited:
                    msg = detail.lower()
                    quota_done = ("quota" in msg or "billing" in msg or "plan" in msg
                                  or "free tier" in msg or "daily" in msg)
                    if quota_done:
                        # daily quota exhausted -> retrying is pointless today
                        log.warning("LLM quota exhausted (HTTP 429): %s", detail[:200])
                        raise LLMError(f"LLM quota exhausted (HTTP 429): {detail[:200]}") from e
                    if attempt < self.max_retries:
                        # transient rate limit -> backoff, never spin fast
                        delay = self.retry_base_seconds * (2 ** (attempt - 1))
                        delay += random.uniform(0, 0.5 * delay)
                        log.warning("LLM endpoint rate limited (429); retry %d/%d after %.1fs",
                                    attempt, self.max_retries, delay)
                        time.sleep(delay)
                        continue
                    raise LLMError(f"LLM endpoint HTTP {e.code}: {detail}") from e
                if e.code in retryable and attempt < self.max_retries:
                    delay = self.retry_base_seconds * (2 ** (attempt - 1))
                    delay += random.uniform(0, 0.5 * delay)
                    log.warning("LLM endpoint HTTP %s (%s); retry %d/%d after %.1fs",
                                e.code, detail[:120], attempt, self.max_retries, delay)
                    time.sleep(delay)
                    last_detail = detail
                    continue
                raise LLMError(f"LLM endpoint HTTP {e.code}: {detail}") from e
            except URLError as e:
                raise LLMError(f"LLM endpoint unreachable: {e}") from e
            except Exception as e:
                raise LLMError(f"LLM call failed: {e}") from e
        else:
            raise LLMError(f"LLM endpoint still failing after {self.max_retries} retries"
                           f"{f': {last_detail[:200]}' if last_detail else ''}")
        try:
            obj = json.loads(raw)
            return obj["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"Malformed LLM response: {raw[:200]}") from e

    # ── validation ─────────────────────────────────────────────────────────
    @staticmethod
    def _norm(v) -> str:
        return str(v or "").strip().lower()

    @staticmethod
    def _pick(value, allowed, default):
        v = LLMClassifier._norm(value)
        for a in allowed:
            if a.lower() == v:
                return a
        return default

    @classmethod
    def _extract_json(cls, content: str) -> Dict:
        s = content.strip()
        # strip ```json fences if present
        if s.startswith("```"):
            s = s.split("\n", 1)[-1] if "\n" in s else s
            s = s.rstrip("`").strip()
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"No JSON object in LLM output: {content[:200]}")
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"Invalid JSON from LLM: {content[:200]}") from e

    @classmethod
    def _validate(cls, content: str) -> Dict:
        obj = cls._extract_json(content)
        feature = cls._pick(obj.get("feature"), cls.FEATURES, "unknown")
        if feature == "unknown":
            subfeature = "not_stated"
        else:
            subfeature = cls._norm(obj.get("subfeature"))[:80] or "not_stated"
        for label in ("ACC", "PDA", "LKA", "LCC", "LDW", "LDP", "ELK", "AEB",
                      "FCW", "DMS", "ALC", "TSR", "BSD", "RCTA", "RCW"):
            if feature != label and feature != "both" and subfeature == label.lower():
                subfeature = "not_stated"
        scenario = cls._norm(obj.get("scenario"))[:120] or "not_stated"
        evidence = cls._pick(obj.get("evidence_type"), cls.EVIDENCE, "uncertain")
        sentiment = cls._pick(obj.get("sentiment"), cls.SENTIMENT, "uncertain")
        relevant = cls._pick(obj.get("relevant"), cls.RELEVANCE, "uncertain")
        mismatch = cls._pick(obj.get("expectation_mismatch"), cls.MISMATCH, "unclear")
        smoothness = cls._pick(obj.get("smoothness"), cls.SMOOTHNESS, "not_stated")
        confidence = cls._pick(obj.get("confidence"), cls.CONFIDENCE, "low")
        summary = str(obj.get("experience_summary") or "").strip()[:500]
        if not summary:
            summary = "Tidak ada pengalaman yang dilaporkan."
        return {
            "feature": feature,
            "subfeature": subfeature,
            "scenario": scenario,
            "evidence_type": evidence,
            "sentiment": sentiment,
            "relevant": relevant,
            "expectation_mismatch": mismatch,
            "smoothness": smoothness,
            "confidence": confidence,
            "experience_summary": summary,
        }