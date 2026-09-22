import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.experience_classifier import SentimentClassifier


def test_positive():
    s = SentimentClassifier()
    assert s.classify("ACC-nya halus banget, nyaman dipakai di tol.") == "positive"


def test_negative():
    s = SentimentClassifier()
    assert s.classify("Waktu macet ACC-nya ngerem mendadak, jedug banget.") == "negative"


def test_mixed_context():
    s = SentimentClassifier()
    # positive + negative in one sentence => mixed
    assert s.classify("ACC-nya bagus, tapi pas stop-and-go kadang ngeremnya jedug.") == "mixed"


def test_neutral():
    s = SentimentClassifier()
    assert s.classify("Apakah ACC J5 mendukung stop and go?") == "neutral"