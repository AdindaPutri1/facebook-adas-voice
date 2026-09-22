"""Driving scenario + sentiment + expectation mismatch + smoothness classifiers."""
import logging
from typing import Dict, List, Optional

from src.config_loader import load_taxonomy
from src.cleaners.text_cleaner import normalize_lower

log = logging.getLogger(__name__)


class ScenarioClassifier:
    def __init__(self, taxonomy_config: Optional[Dict] = None):
        self.tax = taxonomy_config or load_taxonomy()
        self.scenarios = self.tax.get("driving_scenarios", {})

    def classify(self, text: str) -> str:
        if not text or len(text.strip()) < 6:
            return "not_stated"
        lowered = normalize_lower(text)
        hits = []
        for scen, cfg in self.scenarios.items():
            for kw in cfg.get("keywords", []):
                if normalize_lower(kw) in lowered or kw.lower() in lowered:
                    hits.append(scen)
                    break
        if not hits:
            return "not_stated"
        return ",".join(dict.fromkeys(hits))


class SentimentClassifier:
    """Rule-based sentiment: context-aware, returns mixed when both + and - present."""

    NEG_MARKERS = [
        "jelek", "buruk", "ngerem mendadak", "nyentak", "jedug", "kaget", "deg-degan",
        "telat", "lambat", "kurang", "masalah", "nggak berfungsi", "tidak berfungsi",
        "gagal", "susah", "sulit", "maksa", "agresif", "sensitif", "was-was",
        "nggak nyaman", "tidak nyaman", "mengecewakan", "parah", "ngeganggu", "ganggu",
        "agak telat", "lambat", "lelet",
    ]
    POS_MARKERS = [
        "bagus", "mantap", "enak", "halus", "smooth", "nyaman", "amin", "oke", "ok",
        "responsif", "akurat", "keren", "puas", "suka", "senang", "recommended",
        "rekomen", "tidak ada masalah", "ga ada masalah", "aman", "tenang", "pas", "nempel",
        "bantu banget", "sangat membantu", "smooth", "bantu", "membantu", "lumayan",
        "berfungsi baik", "cocok", "puas banget",
    ]

    def classify(self, text: str) -> str:
        lowered = normalize_lower(text)
        neg = sum(1 for m in self.NEG_MARKERS if m in lowered)
        pos = sum(1 for m in self.POS_MARKERS if m in lowered)
        if pos and neg:
            return "mixed"
        if pos:
            return "positive"
        if neg:
            return "negative"
        return "neutral"


class ExpectationMismatchClassifier:
    """Detects explicit expectation vs observed behaviour differences.

    Expectation must be explicitly stated (sangka/kira/kirain/ekspektasi/harap).
    A contrast marker is required to call it a mismatch. If an expectation is stated
    and behaviour matched it, label 'no'; otherwise 'unclear'.
    """
    EXPECT_MARKERS = [
        "ku kira", "kukira", "kirain", "kira", "sangka", "sangkanya",
        "ekspektasi", "harapan", "harap", "dikira", "ngira", "thought", "expect",
    ]
    CONTRAST_MARKERS = ["tapi", "malah", "ternyata", "padahal", "bukannya",
                        "bukan", "namun"]

    def classify(self, text: str) -> str:
        lowered = normalize_lower(text)
        has_expectation = any(m in lowered for m in self.EXPECT_MARKERS)
        has_contrast = any(m in lowered for m in self.CONTRAST_MARKERS)
        if has_expectation and has_contrast:
            return "yes"
        if has_expectation and not has_contrast:
            return "no"
        return "unclear"


class SmoothnessClassifier:
    SMOOTH = ["halus", "smooth", "nggak terasa", "tidak terasa", "mulus"]
    SLIGHT = ["agak kasar", "kurang halus", "sedikit berasa", "sedikit nyentak"]
    ABRUPT = ["nyentak", "jeglek", "sentak", "tidak mulus", "ksetrum"]
    VERY_ABRUPT = ["jedug", "jejedug", "ngentak banget", "keras banget", "tiba-tiba cepet"]
    CONTEXT_BREAK = ["tapi", "namun", "kadang", "kadang-kadang", "when", "pas"]

    def classify(self, text: str) -> str:
        lowered = normalize_lower(text)
        has_very = self._hits(lowered, self.VERY_ABRUPT)
        has_abrupt = self._hits(lowered, self.ABRUPT)
        has_slight = self._hits(lowered, self.SLIGHT)
        has_smooth = self._hits(lowered, self.SMOOTH)
        has_break = any(m in lowered for m in self.CONTEXT_BREAK)

        if has_very:
            return "very_abrupt"
        if has_abrupt:
            if has_smooth and has_break:
                return "slightly_abrupt"
            return "abrupt"
        if has_slight:
            if has_smooth and has_break:
                return "slightly_abrupt"
            return "slightly_abrupt"
        if has_smooth and has_break and (has_abrupt):
            return "slightly_abrupt"
        if has_smooth:
            return "smooth"
        return "not_stated"

    @staticmethod
    def _hits(lowered: str, markers: List[str]) -> int:
        return sum(1 for m in markers if m in lowered)