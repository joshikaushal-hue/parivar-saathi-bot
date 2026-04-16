"""
Quick unit tests for the speech parsers.
Run with: python -m pytest -q    (or)   python -m unittest
"""
from app.state_machine.validators import (
    parse_age, parse_duration_months, parse_treatment,
)


def test_parse_age_digits():
    assert parse_age("32") == 32
    assert parse_age("main 28 saal ki hoon") == 28
    assert parse_age("mera age thirty five hai") == 35


def test_parse_age_devanagari():
    assert parse_age("३२ साल") == 32
    assert parse_age("तीस") == 30


def test_parse_age_out_of_range():
    assert parse_age("12") is None
    assert parse_age("75") is None
    assert parse_age("") is None


def test_parse_duration_years():
    assert parse_duration_months("2 years") == 24
    assert parse_duration_months("3 saal se") == 36
    assert parse_duration_months("१.५ साल") == 18


def test_parse_duration_months():
    assert parse_duration_months("6 months") == 6
    assert parse_duration_months("9 mahine") == 9


def test_parse_duration_bare_number():
    assert parse_duration_months("2") == 24        # <=20 → years
    assert parse_duration_months("30") == 30       # >20 → months


def test_parse_treatment_yes_ivf():
    r = parse_treatment("haan, IVF kiya tha")
    assert r["prior_ivf"] is True
    assert "IVF" in r["treatments"]


def test_parse_treatment_no():
    r = parse_treatment("nahi, kuch nahi kiya")
    assert r["prior_ivf"] is False
    assert r["treatments"] == []


def test_parse_treatment_iui_only():
    r = parse_treatment("IUI karvaaya tha")
    assert r["prior_ivf"] is False
    assert "IUI" in r["treatments"]


def test_parse_treatment_unclear():
    assert parse_treatment("maybe sometime") is None
    assert parse_treatment("") is None
