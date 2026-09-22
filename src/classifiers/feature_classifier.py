"""Vehicle identification + feature (PDA/ACC) + sub-feature classification."""
import logging
from typing import Dict, List, Optional, Tuple

from src.config_loader import load_vehicles
from src.cleaners.text_cleaner import normalize_lower

log = logging.getLogger(__name__)


class VehicleIdentifier:
    def __init__(self, vehicles_config: Optional[Dict] = None):
        self.cfg = vehicles_config or load_vehicles()
        self._by_alias = {}
        for key, v in self.cfg.get("vehicles", {}).items():
            names = [v.get("canonical_name", key), v.get("model", ""),
                     v.get("brand", "")] + list(v.get("aliases", []))
            for n in names:
                n = normalize_lower(n)
                if n:
                    self._by_alias[n] = v.get("canonical_name", key)

    def identify(self, text: str, community_vehicle: Optional[str] = None) -> str:
        if community_vehicle and str(community_vehicle).strip().lower() not in ("", "unknown"):
            return str(community_vehicle).strip()
        if not text:
            return "unknown"
        lowered = normalize_lower(text)
        for alias, canonical in self._by_alias.items():
            if alias and alias in lowered:
                return canonical
        return "unknown"


class FeatureClassifier:
    """Maps text -> feature(s). Uses keyword hits plus taxonomy config."""

    def __init__(self, keywords_config: Optional[Dict] = None,
                 taxonomy_config: Optional[Dict] = None):
        from src.filters.keyword_filter import KeywordEngine

        self.kw = KeywordEngine(keywords_config)
        self.tax = taxonomy_config or __import__(
            "src.config_loader", fromlist=["load_taxonomy"]
        ).load_taxonomy()
        # Deterministic preference order for feature ties, derived from config layout.
        self._feature_order: List[str] = []
        for layer in self.kw.cfg.get("keyword_layers", {}).values():
            if isinstance(layer, dict):
                for feat in layer:
                    if feat != KeywordEngine.GENERIC_FEATURE and feat not in self._feature_order:
                        self._feature_order.append(feat)

    def classify(self, text: str) -> Tuple[str, List[str]]:
        """Return (feature, matched_keywords).

        feature is one of the configured ADAS feature labels (PDA, ACC, LKA, AEB,
        ...) or 'unknown'. Weekly generic 'ADAS' hits are only candidate indicators,
        not proof of a specific feature. 'both' is preserved for PDA+ACC co-mentions.
        """
        matched = self.kw.match(text)
        matched_keywords = [m[0] for m in matched]
        # Strong signals are any non-generic feature-name/functional hits.
        strong: Dict[str, int] = {}
        for _, f in matched:
            if f == self.kw.GENERIC_FEATURE:
                continue
            strong[f] = strong.get(f, 0) + 1
        if not strong:
            return "unknown", matched_keywords
        if "PDA" in strong and "ACC" in strong:
            return "both", matched_keywords
        # Pick the feature with the most keyword hits; break ties by config order.
        order = {f: i for i, f in enumerate(self._feature_order)}
        best = max(strong, key=lambda f: (strong[f], -order.get(f, 0)))
        return best, matched_keywords

    def classify_subfeature(self, text: str, feature: str) -> str:
        """Pick the most indicative subfeature from taxonomy."""
        if feature == "unknown":
            return "not_stated"
        lowered = normalize_lower(text)
        cfg = self.tax.get("feature_taxonomy", {})
        candidates = []
        for feat in ([feature] if feature != "both" else ["PDA", "ACC"]):
            bucket = cfg.get(feat, {})
            for sub, kws in bucket.get("subfeature_keywords", {}).items():
                hits = sum(1 for k in kws if normalize_lower(k) in lowered or k.lower() in lowered)
                if hits:
                    candidates.append((hits, feat, sub))
        if not candidates:
            return "not_stated"
        candidates.sort(key=lambda x: x[0], reverse=True)
        return f"{candidates[0][1]}:{candidates[0][2]}"