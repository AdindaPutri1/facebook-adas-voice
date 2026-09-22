import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import v2_common as vc  # noqa: E402
from src.config_loader import load_vehicles  # noqa: E402

PATTERNS = vc.build_vehicle_alias_patterns(load_vehicles())


def _classify(text, src=""):
    return vc.classify_vehicle(text, src, PATTERNS)


def test_explicit_strong_alias_high():
    r = _classify("Sudah coba BYD Sealion 7 di tol, ACC mantap")
    assert r["vehicle"] == "BYD Sealion 7" and r["confidence"] == "high"


def test_short_alias_medium():
    r = _classify("G6 ACC-nya halus", src="XPeng G6")
    assert r["vehicle"] == "XPeng G6"
    assert r["confidence"] in ("high", "medium")


def test_community_context_prior_medium():
    r = _classify("ACC-nya enak", src="Toyota Veloz")
    assert r["vehicle"] == "Toyota Veloz" and r["confidence"] == "medium"


def test_zenix_not_confused_by_brand_toyota():
    r = _classify("Jual Toyota Innova Zenix V Hybrid", src="")
    assert r["vehicle"] == "Toyota Zenix"
    assert "Toyota Yaris" not in r["vehicle"] or r["vehicle"] == "Toyota Zenix"


def test_unknown_when_no_signal():
    r = _classify("motor matic saya irit", src="")
    assert r["vehicle"] == "unknown" and r["confidence"] == "low"