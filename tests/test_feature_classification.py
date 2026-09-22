import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.feature_classifier import FeatureClassifier


def _fc():
    return FeatureClassifier()


def test_acc_following():
    f, m = _fc().classify("ACC-nya kalau mobil depan berhenti ikut berhenti, cukup halus.")
    assert f == "ACC"
    assert m, "should have matched keywords"


def test_acc_acceleration_cut_out():
    f, m = _fc().classify(
        "ACC G6 kalau mobil depan pindah jalur langsung akselerasinya terasa cepat.")
    assert f == "ACC"


def test_pda_terms():
    f, m = _fc().classify("PDA J5 bekerja saat mendekati tikungan, kecepatan dikurangi otomatis.")
    assert f == "PDA"


def test_subfeature_acc_braking():
    fc = _fc()
    sub = fc.classify_subfeature(
        "ACC-nya kalau mobil depan berhenti ikut berhenti, cukup halus.", "ACC")
    assert "braking" in sub or "following" in sub


def test_unknown_text_no_feature():
    f, m = _fc().classify("Harga jual J5 bekas mulus 2025 berapa ya?")
    assert f == "unknown"
    assert not m


def test_spec_text_feature_but_low_info():
    fc = _fc()
    f, m = fc.classify("J5 punya 17 fitur ADAS.")
    from src.filters.relevance_filter import classify_evidence
    assert classify_evidence("J5 punya 17 fitur ADAS.") == "specification"