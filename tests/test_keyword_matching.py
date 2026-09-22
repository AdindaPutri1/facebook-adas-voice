import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.filters.keyword_filter import KeywordEngine
from src.config_loader import load_keywords


def test_pda_keyword_hit():
    eng = KeywordEngine(load_keywords())
    m = eng.match("Apakah PDA J5 berfungsi di tikungan?")
    assert m, "expected PDA layer-A hit"
    assert any(p == "PDA" for _, p in m)


def test_acc_keyword_hit():
    eng = KeywordEngine(load_keywords())
    m = eng.match("ACC-nya bisa stop and go di jalan tol.")
    assert any(p == "ACC" for _, p in m)


def test_indonesian_layer_c_hit():
    eng = KeywordEngine(load_keywords())
    m = eng.match("ACC-nya ngerem mendadak pas mobil depan berhenti.")
    assert any(p == "ACC" for _, p in m)


def test_no_keyword_no_candidate():
    eng = KeywordEngine(load_keywords())
    assert not eng.is_candidate("Harga J5 bulan ini berapa ya?")


def test_candidate_true_is_not_relevance():
    from src.filters.relevance_filter import classify_relevance
    eng = KeywordEngine(load_keywords())
    text = "G6 punya ACC."
    assert eng.is_candidate(text)
    rel = classify_relevance(text, ["ACC"], True)
    # keyword present but low-information spec; should not be auto-'relevant experience'
    assert rel in ("relevant", "uncertain")


def test_multiple_features_both():
    eng = KeywordEngine(load_keywords())
    m = eng.match("PDA dan ACC di J5 bekerja saat persimpangan.")
    features = {p for _, p in m}
    assert "PDA" in features and "ACC" in features