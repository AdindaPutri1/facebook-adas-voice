import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.classifiers.feature_classifier import VehicleIdentifier


def test_identify_jaecoo():
    vi = VehicleIdentifier()
    assert vi.identify("Sudah coba J5 di tol, ACC mantap.") == "Jaecoo J5"


def test_identify_g6_alias():
    vi = VehicleIdentifier()
    assert vi.identify("G6 ACC-nya halus banget.") == "XPeng G6"


def test_identify_community_context():
    vi = VehicleIdentifier()
    assert vi.identify("ACC-nya enak.", community_vehicle="BYD Sealion 7") == "BYD Sealion 7"


def test_identify_unknown():
    vi = VehicleIdentifier()
    assert vi.identify("Motor matic saya irit.") == "unknown"


def test_all_six_vehicles_registered():
    from src.config_loader import load_vehicles
    cfg = load_vehicles()
    names = {v["canonical_name"] for v in cfg["vehicles"].values()}
    assert {"Jaecoo J5", "Toyota Yaris", "Toyota Zenix", "Toyota Veloz",
            "XPeng G6", "BYD Sealion 7"} <= names