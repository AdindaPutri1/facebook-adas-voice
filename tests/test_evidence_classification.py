import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.filters.relevance_filter import classify_evidence, classify_relevance
from src.classifiers.feature_classifier import FeatureClassifier


def test_evidence_direct_experience():
    t = "Saya sudah coba ACC-nya, waktu mobil depan berhenti dia ikut berhenti."
    assert classify_evidence(t) == "direct_experience"


def test_evidence_question():
    assert classify_evidence("ACC-nya bisa stop and go nggak?") == "question"


def test_evidence_hearsay():
    assert classify_evidence("Katanya ACC-nya suka ngerem mendadak.") == "hearsay"


def test_evidence_specification():
    assert classify_evidence("J5 punya 17 fitur ADAS.") == "specification"


def test_evidence_opinion():
    assert classify_evidence("Menurut saya ACC Toyota lebih bagus.") == "opinion"


def test_question_is_not_direct_experience():
    t = "ACC-nya bisa stop and go nggak?"
    assert classify_evidence(t) == "question"


def test_keyword_hit_not_direct_experience():
    # Layer A hit but pure spec text must not become direct_experience
    t = "J5 punya 17 fitur ADAS."
    fc = FeatureClassifier()
    feature, matched = fc.classify(t)
    assert matched
    ev = classify_evidence(t)
    assert ev != "direct_experience"