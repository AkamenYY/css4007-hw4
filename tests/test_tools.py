import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import calculate, lookup  # noqa: E402


# ------------------------------------------------------------------ lookup

def test_lookup_finds_2025_population():
    r = lookup("Ossbridge", "population_2025")
    assert r["value"] == 52904 and r["source"] == "NR-01"


def test_lookup_misspelled_name_suggests():
    r = lookup("Ossbrige", "population_2025")
    assert "error" in r and "Ossbridge" in r["error"]


def test_lookup_similar_names_are_kept_apart():
    a, b = lookup("Ossbridge", "area_km2"), lookup("Ossford", "area_km2")
    assert (a["value"], a["source"]) == (1284.6, "NR-01")
    assert (b["value"], b["source"]) == (846.2, "NR-02")


def test_lookup_ignores_archived_profile():
    r = lookup("Tarnvale", "water_2025")
    assert r["value"] == 5207 and r["source"] == "NR-03"   # not 4,980 from NR-13
    assert "NR-13" in r["note"]


def test_lookup_applies_correction():
    r = lookup("Brightwater", "area_km2")
    assert r["value"] == 921.4 and "NR-16" in r["source"]


def test_lookup_converts_cubic_metres():
    r = lookup("Lindenmoor", "water_2025")
    assert r["value"] == 2151.4 and r["unit"] == "megalitres"


def test_lookup_unknown_field():
    assert "error" in lookup("Redfen", "rainfall")


def test_lookup_tariff():
    r = lookup("", "water_tariff_2025")
    assert r["value"] == 142.35 and r["source"] == "NR-15"


# --------------------------------------------------------------- calculate

def test_calculate_multiplication():
    assert abs(calculate("48317 * 1.0947")["result"] - 52892.6199) < 1e-6


def test_calculate_density():
    assert abs(calculate("44675 / 921.4")["result"] - 48.48605) < 1e-4


def test_calculate_refuses_import():
    r = calculate("__import__('os').system('echo hi')")
    assert "error" in r


def test_calculate_refuses_attribute():
    assert "error" in calculate("(1).__class__")


def test_calculate_refuses_huge_power_quickly():
    t = time.time()
    r = calculate("9**9**9")
    assert "error" in r and time.time() - t < 1


def test_calculate_division_by_zero():
    assert calculate("1 / 0") == {"error": "division by zero"}


def test_calculate_garbage():
    assert "error" in calculate("two plus two")
