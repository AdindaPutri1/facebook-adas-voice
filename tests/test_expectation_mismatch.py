import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.experience_classifier import ExpectationMismatchClassifier


def test_mismatch_yes():
    e = ExpectationMismatchClassifier()
    t = "Saya kira pas mobil depan pindah jalur dia langsung ngerem, ternyata malah akselerasi."
    assert e.classify(t) == "yes"


def test_mismatch_unclear_contrast_without_expectation():
    e = ExpectationMismatchClassifier()
    assert e.classify("Tapi ternyata ACC-nya jalannya agak pelan.") == "unclear"


def test_mismatch_no():
    e = ExpectationMismatchClassifier()
    assert e.classify("ACC bekerja sesuai harapan, mobil depan berhenti ikut berhenti.") == "no"


def test_not_from_sentiment_alone():
    e = ExpectationMismatchClassifier()
    # negative sentiment but no stated expectation => not mismatch
    assert e.classify("ACC-nya jelek banget, sering ngerem mendadak.") == "no" or \
           e.classify("ACC-nya jelek banget, sering ngerem mendadak.") == "unclear"