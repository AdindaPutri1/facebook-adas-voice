import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from filter_adas_relevance import LayerScorer, _ADMIN_APPROVAL, MARKETPLACE_NOISE  # noqa: E402
from src.config_loader import load_keywords  # noqa: E402

SCORER = LayerScorer(load_keywords())


def _match(text):
    return SCORER.match(text)


def test_explicit_acc_layer_a():
    hits, matched = _match("Adaptive Cruise Control-nya berfungsi")
    assert "layer_a_feature_names" in hits
    assert "ACC" in hits["layer_a_feature_names"]


def test_indonesian_functional_layer_c():
    hits, matched = _match("kereta otomatis ngerem sendiri di tikungan")
    assert "layer_c_indonesian" in hits or "layer_b_functional" in hits


def test_generic_adas_only():
    hits, matched = _match("mobil ini punya fitur ADAS banyak")
    assert "combined_adas" in hits


def test_admin_approval_noise_detected():
    assert _ADMIN_APPROVAL.search("izin ACC mas admin")
    assert not _ADMIN_APPROVAL.search("ACC-nya mantap saat ngerem")


def test_marketplace_noise_contains_ppf_phrases():
    assert any(n in "baret halus di goresan" for n in MARKETPLACE_NOISE)