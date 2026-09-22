"""Keyword engine: loads keyword config and provides candidate matching.

IMPORTANT: a keyword hit only produces 'keyword_candidate = True'. It does NOT
establish relevance. Relevance is handled by RelevanceFilter separately.

Design notes:
- Terms compiled with left/right non-alphanumeric boundaries so "ACC" matches
  Indonesian possessive "ACC-nya" but not the middle of a word.
- Generic ADAS terms live under 'combined_adas' and carry feature label 'ADAS'
  purely for candidate detection; the FeatureClassifier downgrades them to
  feature='unknown' unless PDA/ACC are also present.
"""
import re
import logging
from typing import Dict, List, Optional, Tuple

from src.config_loader import load_keywords
from src.cleaners.text_cleaner import normalize_lower

log = logging.getLogger(__name__)

# Alternative regexes for fuzzy/off-by-one spellings
_ALT_RE = {
    "cut-in": r"cut[ -]?in",
    "cut out": r"cut[ -]?out",
    "cut-out": r"cut[ -]?out",
    "stop and go": r"stop[ -]?and[ -]?go",
    "stop-and-go": r"stop[ -]?and[ -]?go",
    "corner": r"corner",
    "turn": r"turn|belok",
}

_BOUNDARY_LEFT = r"(?<![a-z0-9])"
_BOUNDARY_RIGHT = r"(?![a-z0-9])"


def _compile_term(term: str) -> re.Pattern:
    lowered = normalize_lower(term)
    core = _ALT_RE.get(lowered) or re.escape(lowered)
    return re.compile(_BOUNDARY_LEFT + core + _BOUNDARY_RIGHT, re.IGNORECASE)


class KeywordEngine:
    """Builds compiled keyword matchers from keywords.yaml (configurable)."""

    GENERIC_FEATURE = "ADAS"

    def __init__(self, keywords_config: Optional[Dict] = None):
        self.cfg = keywords_config or load_keywords()
        self.layers = self.cfg.get("keyword_layers", {})
        self.min_text_length = int(self.cfg.get("min_text_length", 5))
        self._build()

    def _build(self):
        # flat list of (pattern, feature_label, matched_term)
        self._matchers: List[Tuple[re.Pattern, str, str]] = []
        self._generic_terms: List[str] = []
        for layer_name, layer in self.layers.items():
            if isinstance(layer, dict):
                for feature, terms in layer.items():
                    for t in terms:
                        t = str(t).strip()
                        if not t:
                            continue
                        self._matchers.append((_compile_term(t), feature, t))
            elif layer_name == "combined_adas" and isinstance(layer, list):
                for t in layer:
                    t = str(t).strip()
                    if not t:
                        continue
                    self._generic_terms.append(normalize_lower(t))
                    self._matchers.append((_compile_term(t), self.GENERIC_FEATURE, t))

    def passes_min_length(self, text: str) -> bool:
        return len(text or "") >= self.min_text_length

    def match(self, text: str) -> List[Tuple[str, str]]:
        """Return list of (matched_phrase, feature_label) tuples."""
        if not text:
            return []
        lowered = normalize_lower(text)
        results: List[Tuple[str, str]] = []
        for pat, feature, term in self._matchers:
            if pat.search(lowered):
                results.append((term, feature))
        # dedupe preserving order
        seen = set()
        out = []
        for phrase, feature in results:
            k = (phrase.lower(), feature)
            if k not in seen:
                seen.add(k)
                out.append((phrase, feature))
        return out

    def is_candidate(self, text: str) -> bool:
        return len(self.match(text)) > 0


def build_global_keyword_set() -> set:
    """Collect all keywords across layers for reporting."""
    cfg = load_keywords()
    out = set()
    for layer in cfg.get("keyword_layers", {}).values():
        if isinstance(layer, dict):
            for terms in layer.values():
                for t in terms:
                    out.add(t.lower())
        elif isinstance(layer, list):
            for t in layer:
                out.add(t.lower())
    return out