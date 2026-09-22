import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.experience_classifier import SmoothnessClassifier


def test_smooth():
    s = SmoothnessClassifier()
    assert s.classify("ACC-nya cukup halus di jalan tol.") == "smooth"


def test_very_abrupt():
    s = SmoothnessClassifier()
    assert s.classify("Waktu mobil depan berhenti, ACC-nya jedug keras banget.") == "very_abrupt"


def test_abrupt():
    s = SmoothnessClassifier()
    assert s.classify("Pas stop and go ACC-nya suka nyentak.") == "abrupt"


def test_not_stated():
    s = SmoothnessClassifier()
    assert s.classify("ACC-nya fungsional.") == "not_stated"


def test_context_does_not_override_very_abrupt():
    s = SmoothnessClassifier()
    # even with 'halus' elsewhere, jedug dominates
    assert s.classify("Biasanya halus tapi pas macet kadang jedug.") == "very_abrupt"