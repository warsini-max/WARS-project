"""Phase 3 completion criterion: every error deliberately injected into real test data (wrong
unit, swapped columns, missing value, digit slip, wrong sign) is caught as yellow or red.

Document tests need the non-case test PDFs (skipped otherwise). The injected errors are applied
to the reader's output for SIDO 2021 and KLBF 2021, then the checks are run again.
"""
import copy
import csv
import hashlib
import os
from pathlib import Path

import pytest

from wars_scanner import engine, pipeline, validation
from wars_scanner.pdf_reader import _checks

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = {d["file_name"]: d for d in csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8"))}
_cache = {}

BS = ["total_assets", "current_assets", "cash_and_cash_equivalents", "property_plant_equipment_net",
      "current_liabilities", "total_liabilities", "long_term_debt", "current_maturities_long_term_debt",
      "taxes_payable", "accounts_receivable", "rou_assets_net"]


def _run(name):
    if name not in _cache:
        p = PDF_DIR / name
        if not p.exists():
            pytest.skip(f"{name} not available (set WARS_TEST_PDF_DIR)")
        assert hashlib.sha256(p.read_bytes()).hexdigest() == DOCS[name]["sha256"]
        # simulated user decision (M-06): NONE_PRESENT for each year, notes examined listed
        _cache[name] = pipeline.apply_non_ppe_decisions(pipeline.run(p, "TEST"), {
            c: {"status": "NONE_PRESENT", "notes": ["(test) fixed assets; other non-current assets"]} for c in ("t", "t1")})
    return _cache[name]


def _codes(p, ex, severity=None):
    return {(f.code, f.severity) for f in validation.check(p, ex) if severity is None or f.severity == severity}


def _caught(p, ex):
    """Yellow or red: a cross-check flag that is not already raised on the clean data, or the
    engine refuses to calculate."""
    return bool(validation.check(p, ex)) or engine.calculate(p)["not_ready_reason"] != ""


# ----------------------------------------------------------------------------- clean data
@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_clean_data_has_no_error(name):
    r = _run(name)
    assert not r.errors
    assert any(getattr(x, "key", "") == "check.cash" for x in r.passed)


# ----------------------------------------------------------------------------- injected errors
@pytest.mark.parametrize("name,wrong", [("LK_SIDO_2021.pdf", "Units"), ("LK_SIDO_2021.pdf", "Billions"),
                                        ("LK_KLBF_2021.pdf", "Millions")])
def test_wrong_unit_is_red(name, wrong):
    r = _run(name)
    p = dict(r.inputs, unit_scale=wrong)
    assert ("a_unit_implausible", "ERROR") in _codes(p, r.extraction)


@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_swapped_balance_sheet_columns_are_red(name):
    r = _run(name)
    p = dict(r.inputs)
    for f in BS:
        p[f"{f}_t"], p[f"{f}_t1"] = r.inputs.get(f"{f}_t1"), r.inputs.get(f"{f}_t")
    assert ("a_cash_tie", "ERROR") in _codes(p, r.extraction)


def test_one_swapped_line_breaks_the_face_check():
    r = _run("LK_SIDO_2021.pdf")
    vals = copy.deepcopy(r.extraction.values)
    rev = {v.column: v for v in vals if v.field == "revenue"}
    rev["t"].value, rev["t1"].value = rev["t1"].value, rev["t"].value
    ex = pipeline.read(PDF_DIR / "LK_SIDO_2021.pdf")
    checks = _checks(ex.statements["position"], ex.statements["profit_loss"], vals)
    assert not all(ok for name, _, ok, _ in checks if name.key == "check.gross_profit")


@pytest.mark.parametrize("field", ["total_assets", "revenue", "taxes_payable", "depreciation_amortization_total"])
@pytest.mark.parametrize("col", ["t", "t1"])
def test_missing_value_stops_the_score(field, col):
    r = _run("LK_SIDO_2021.pdf")
    p = dict(r.inputs)
    p.pop(f"{field}_{col}")
    out = engine.calculate(p)
    assert out["m_score_B"] == "" and "missing" in out["not_ready_reason"]


@pytest.mark.parametrize("field,factor,col", [
    ("accounts_receivable", 1000, "t"), ("cash_and_cash_equivalents", 1000, "t1"), ("taxes_payable", 10, "t"),
    ("current_maturities_long_term_debt", 1000, "t"), ("long_term_debt", 1000, "t1"),
    ("selling_general_administrative_expenses", 1000, "t"), ("depreciation_amortization_total", 1000, "t"),
    ("revenue", 1000, "t1"), ("cost_of_goods_sold", 1000, "t"), ("property_plant_equipment_net", 1000, "t"),
    ("total_liabilities", 1000, "t1"), ("amortization_intangibles", 1000, "t"),
])
@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_digit_slip_is_caught(name, field, factor, col):
    r = _run(name)
    p = dict(r.inputs)
    v = p.get(f"{field}_{col}")
    if not v:                    # 0 stays 0 (e.g. undisclosed amortisation): not applicable
        pytest.skip(f"{field}_{col} is 0 in {name}")
    p[f"{field}_{col}"] = v * factor
    assert _caught(p, r.extraction), f"{field}_{col} x{factor} not caught"


@pytest.mark.parametrize("field", ["revenue", "total_assets", "taxes_payable"])
def test_wrong_sign_is_flagged(field):
    r = _run("LK_SIDO_2021.pdf")
    p = dict(r.inputs)
    p[f"{field}_t"] = -p[f"{field}_t"]
    assert ("r_negative_values", "REVIEW") in _codes(p, r.extraction)


def test_unusual_yoy_change_uses_workbook_threshold():
    r = _run("LK_SIDO_2021.pdf")
    p = dict(r.inputs)
    p["revenue_t"] = int(p["revenue_t1"] * 2.01)
    assert ("r_unusual_yoy_change", "REVIEW") in _codes(p, r.extraction)
    p["revenue_t"] = int(p["revenue_t1"] * 1.99)
    assert ("r_unusual_yoy_change", "REVIEW") not in _codes(p, r.extraction)


def test_error_withholds_the_score():
    r = _run("LK_SIDO_2021.pdf")
    bad = copy.copy(r)
    bad.flags = r.flags + [validation.Flag("a_unit_implausible", "ERROR", "app", "test")]
    assert bad.m_score_raw is not None and bad.m_score is None
    assert bad.status.startswith("NOT USABLE")


def test_app_check_messages_are_about_the_figures_read_not_the_issuer():
    """M-12 A (Gail, 23 Oct 2026): every app check speaks about the figures as read."""
    r = _run("LK_SIDO_2021.pdf")
    p = dict(r.inputs, unit_scale="Units")
    p["accounts_receivable_t"] = p["current_assets_t"] + 1
    p["revenue_t1"] = p["revenue_t1"] * 10
    flags = [f for f in validation.check(p, r.extraction) if f.source == "app"]
    assert {f.code for f in flags} >= {"a_unit_implausible", "a_part_exceeds_total", "a_year_jump"}
    assert all(f.message.startswith("Angka yang dibaca") for f in flags if f.code.startswith("a_") and f.code != "a_cash_tie_unavailable")
    banned = ("fraud", "kecurangan", "manipulasi", "sengaja", "emiten")
    assert not any(b in f.message.lower() for f in flags for b in banned)


# ----------------------------------------------------------------------------- P0-2 year labels (approved 28 Oct 2026)
def _with_years(ex, **years):
    ex2 = copy.copy(ex)
    ex2.year_labels = {k: dict(v) for k, v in ex.year_labels.items()}
    for k, y in years.items():
        ex2.year_labels[k]["year"] = y
    return ex2


@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_year_labels_agree_on_the_test_documents(name):
    r = _run(name)
    assert {v["year"] for v in r.extraction.year_labels.values()} == {r.extraction.fiscal_year}
    assert not {f.code for f in r.flags} & {"a_year_labels_missing", "a_year_labels_mismatch"}
    assert any(getattr(x, "key", "") == "check.year_labels" for x in r.passed)


def test_missing_year_labels_withhold_the_score():
    r = _run("LK_SIDO_2021.pdf")
    ex = _with_years(r.extraction, cash_flow=None)
    assert ("a_year_labels_missing", "ERROR") in _codes(r.inputs, ex)


def test_statements_disagreeing_on_the_year_withhold_the_score():
    """The whole profit-or-loss statement read with another year (e.g. columns taken from the wrong
    heading): caught from the headings, not from the ratios."""
    r = _run("LK_SIDO_2021.pdf")
    ex = _with_years(r.extraction, profit_loss=2020)
    flags = [f for f in validation.check(r.inputs, ex) if f.code == "a_year_labels_mismatch"]
    assert flags and flags[0].severity == "ERROR"
    assert "2020" in flags[0].message.render("en") and "2021" in flags[0].message.render("en")


def test_year_flag_survives_the_user_decisions():
    r = pipeline.run(PDF_DIR / "LK_SIDO_2021.pdf", "TEST") if (PDF_DIR / "LK_SIDO_2021.pdf").exists() else pytest.skip()
    r = copy.copy(r)
    r.flags = r.flags + [validation.Flag("a_year_labels_missing", "ERROR", "app", "test", (), "both")]
    r2 = pipeline.apply_non_ppe_decisions(r, {c: {"status": "NONE_PRESENT", "notes": ["(test)"]} for c in ("t", "t1")})
    assert "a_year_labels_missing" in {f.code for f in r2.flags} and r2.m_score is None
