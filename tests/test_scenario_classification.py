import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.experience_classifier import ScenarioClassifier


def test_highway():
    sc = ScenarioClassifier()
    out = sc.classify("ACC mantap dipakai di jalan tol.")
    assert "highway_tol" in out


def test_traffic_jam():
    sc = ScenarioClassifier()
    assert "traffic_jam" in sc.classify("Jalanan macet parah, ACC stop and go kepakai.")


def test_cut_in():
    sc = ScenarioClassifier()
    assert "vehicle_cut_in" in sc.classify("Tiba-tiba ada motor cut-in di depan, langsung ngerem.")


def test_multiple_scenarios():
    sc = ScenarioClassifier()
    out = sc.classify("Pas macet di tol, mobil depan pindah jalur.")
    assert "traffic_jam" in out and "highway_tol" in out


def test_not_stated():
    sc = ScenarioClassifier()
    assert sc.classify("ACC-nya menurut saya cukup baik.") == "not_stated"