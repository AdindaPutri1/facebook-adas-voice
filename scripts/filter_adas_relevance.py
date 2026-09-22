"""STEP 5e: Layered ADAS relevance screening -> adds ADAS relevance columns
onto facebook_master_clean.csv.

A keyword hit is a CANDIDATE only - it never equals "relevant". Three layers:
  layer_a_feature_names  (explicit feature names e.g. PDA/ACC/LKA -> strong)
  layer_b_functional     (English functional terms -> medium)
  layer_c_indonesian     (Indonesian user-language terms -> medium)
  combined_adas          (generic umbrella terms -> weak, uncertain)
Relevance decision + reason + confidence are stored per record.
"""
import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import v2_common as vc  # noqa: E402

from src.config_loader import load_keywords  # noqa: E402
from src.cleaners.text_cleaner import normalize_lower  # noqa: E402
from src.filters.relevance_filter import classify_relevance  # noqa: E402
from src.filters.keyword_filter import _compile_term  # noqa: E402

ADAS_LAYER_ORDER = ["layer_a_feature_names", "layer_b_functional",
                    "layer_c_indonesian", "combined_adas"]

# Tampilan fisik/permukaan — bukan perilaku ACC. Kata seperti "halus" punya dua
# arti: "pengereman halus" (ADAS) vs "baret halus"/"goresan halus" (cosmetic).
MARKETPLACE_NOISE = (
    "baret halus", "goresan halus", "permukaan halus", "hasil halus",
    "kulit halus", "baret", "goresan", "pelindung", "ppf", "paint protection",
    "jasa pasang", "jasa pemasangan", "cat mobil", "poles", "ketok", "klep",
    "kaca film", "modellista",
)

# "izin ACC mas admin" = persetujuan admin marketplace, bukan Adaptive Cruise.
_ADMIN_APPROVAL = re.compile(
    r"\bizin\b[^.\n]{0,30}\bacc\b|\bacc\b[^.\n]{0,20}\b(admin|mas admin)\b",
    re.IGNORECASE)

# Kota/nama tempat yang bertabrakan dengan akronim fitur (BSD/BSM = Blind Spot).
_PLACE_TOKENS = ("bintaro", "pamulang", "ciater", "depok", "ciputat", "tangerang",
                 "jaksel", "jakarta selatan", "bsd dll", "serpong", "bogor", "bsd city")


class LayerScorer:
    def __init__(self, kwcfg: dict):
        self.layers = kwcfg.get("keyword_layers", {})
        self.generic_feature = "ADAS"
        self._arr = {}
        for layer, content in self.layers.items():
            entries = []
            if isinstance(content, dict):
                for feature, terms in content.items():
                    for t in terms:
                        entries.append((str(t).strip(), feature))
            elif isinstance(content, list):
                for t in content:
                    entries.append((str(t).strip(), self.generic_feature))
            self._arr[layer] = [(t, f, _compile_term(t)) for t, f in entries if t]

    def match(self, text: str):
        lowered = normalize_lower(text)
        hits = {}
        matched = []
        for layer in ADAS_LAYER_ORDER:
            arr = self._arr.get(layer, [])
            layer_feats = set()
            for term, feat, pat in arr:
                if pat.search(lowered):
                    layer_feats.add(feat)
                    matched.append(term)
            if layer_feats:
                hits[layer] = sorted(layer_feats)
        return hits, sorted(set(matched))

    def layer_a_features(self, hits: dict) -> list:
        feats = set(hits.get("layer_a_feature_names", []))
        feats.discard(self.generic_feature)
        return sorted(feats)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    clean_csv = os.path.join(vc.MASTER_DIR, "facebook_master_clean.csv")
    if not args.force and _already_done(clean_csv):
        vc.log("skip filter_adas_relevance (columns exist; use --force)")
        return 0

    cfg = vc.load_analysis_config()
    rel_cfg = cfg.get("relevance", {})
    scorer = LayerScorer(load_keywords())
    min_words = int(rel_cfg.get("min_words_for_functional", 6))

    df = vc.load_df(clean_csv)
    rows = df.apply(lambda r: _row(r, scorer, min_words), axis=1)
    for col in ("candidate_adas", "matched_keywords", "layer_hit",
                "feature_names_hit", "generic_adas_only",
                "adas_relevance", "relevance_reason", "relevance_confidence"):
        df[col] = rows.apply(lambda x, c=col: x[c])

    vc.save_df(df, clean_csv)
    rel = df["adas_relevance"].value_counts().to_dict()
    vc.log(f"filter_adas_relevance done: rows={len(df)} relevance={rel}")
    return 0


def _already_done(path: str) -> bool:
    if not os.path.exists(path):
        return False
    df = vc.load_df(path)
    return {"candidate_adas", "adas_relevance"}.issubset(df.columns)


def _row(r, scorer, min_words):
    text = r.get("text_clean", "") or r.get("text_raw", "")
    hits, matched = scorer.match(text)
    layer_a = scorer.layer_a_features(hits)
    generic = hits.get("combined_adas", [])
    has_func = bool(hits.get("layer_b_functional") or hits.get("layer_c_indonesian"))

    candidate = bool(matched)
    if not candidate:
        return {"candidate_adas": "False", "matched_keywords": "",
                "layer_hit": "", "feature_names_hit": "", "generic_adas_only": "False",
                "adas_relevance": "not_relevant", "relevance_reason": "no_adas_keyword",
                "relevance_confidence": ""}

    lowered = normalize_lower(text)
    layer_hit = ",".join(hits.keys())
    feat_names = ",".join(layer_a)

    # 1) "izin ACC mas admin" = marketplace admin approval, bukan Adaptive Cruise.
    if _ADMIN_APPROVAL.search(lowered):
        return _noise_result(matched, layer_hit, "admin_approval_marketplace_noise")
    # 2) Kota "BSD"/"BSM" salah tangkap sebagai Blind Spot Detection.
    layer_a_set = set(layer_a)
    if layer_a_set and layer_a_set.issubset({"BSD", "BSM"}) \
            and any(tok in lowered for tok in _PLACE_TOKENS):
        return _noise_result(matched, layer_hit, "place_name_ambiguous_acronym")

    generic_only = not layer_a and not has_func

    if layer_a:
        rel, conf, reason = "relevant", "high", "explicit_feature_name"
    elif generic_only:
        rel_try = vc.load_analysis_config().get("relevance", {}).get("generic_only_default", "uncertain")
        rel, conf, reason = rel_try, "low", "generic_adas_terms_only"
    elif has_func:
        words = len(text.split())
        ctx = classify_relevance(text, layer_a, True)
        if ctx == "not_relevant" or words < min_words:
            rel, conf, reason = "uncertain", "low", "functional_keywords_no_behavioural_context"
        else:
            rel, conf, reason = "relevant", "medium", "functional_keywords_with_context"
            if any(n in lowered for n in MARKETPLACE_NOISE):
                rel, conf, reason = "uncertain", "low", "possible_marketplace_noise"

    return {"candidate_adas": "True", "matched_keywords": ";".join(matched),
            "layer_hit": layer_hit, "feature_names_hit": feat_names,
            "generic_adas_only": str(generic_only),
            "adas_relevance": rel, "relevance_reason": reason,
            "relevance_confidence": conf}


def _noise_result(matched, layer_hit, reason):
    """A keyword hit that is not about ADAS at all -> kept as not_relevant."""
    return {"candidate_adas": "False", "matched_keywords": ";".join(matched),
            "layer_hit": layer_hit, "feature_names_hit": "",
            "generic_adas_only": "False",
            "adas_relevance": "not_relevant", "relevance_reason": reason,
            "relevance_confidence": ""}


if __name__ == "__main__":
    sys.exit(main())