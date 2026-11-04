"""Review step (Gail, 4 Nov 2026): answers, origin of amounts, reasons. Synthetic data only."""
from types import SimpleNamespace

import pytest

from wars_scanner import check
from wars_scanner.pdf_reader import Value


def test_parse_amount_accepts_both_separators_and_brackets():
    assert check.parse_amount("91.300.000.000") == 91_300_000_000
    assert check.parse_amount("91,300,000,000") == 91_300_000_000
    assert check.parse_amount("(1.234)") == -1234
    assert check.parse_amount("  ") is None


@pytest.mark.parametrize("bad", ["91,3", "1.23.456", "12a", "1.234,56"])
def test_parse_amount_refuses_decimals_and_text(bad):
    with pytest.raises(check.AnswerError):
        check.parse_amount(bad)


def _result():
    vals = [Value("accounts_receivable", "t", 250, "REVIEW"), Value("accounts_receivable", "t1", 220, "REVIEW"),
            Value("taxes_payable", "t", 8, "REVIEW"), Value("taxes_payable", "t1", 7, "REVIEW")]
    ex = SimpleNamespace(values=vals, fiscal_year=2022, statements={}, fs_location={})
    p = {"accounts_receivable_t": 250, "accounts_receivable_t1": 220, "taxes_payable_t": 8, "taxes_payable_t1": 7}
    return SimpleNamespace(extraction=ex, inputs=p, calc={}, flags=[], missing=[], unreadable="",
                           review=[("accounts_receivable", "t", "REVIEW", ""), ("accounts_receivable", "t1", "REVIEW", ""),
                                   ("taxes_payable", "t", "REVIEW", "D-03g PENDEKATAN"),
                                   ("taxes_payable", "t1", "REVIEW", "D-03g PENDEKATAN")])


def test_items_one_per_field_with_reason():
    its = check.items(_result())
    assert [i.field for i in its] == ["accounts_receivable", "taxes_payable"]
    assert its[1].reason.key == "chk.r.tax_proxy"
    assert its[0].reason.key == "chk.r.single"          # negative: no contract-asset line, no specific reason


def test_apply_records_origin_and_replaces_only_amended_amounts():
    r = _result()
    its = check.items(r)
    r2 = check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "91", "t1": "33"},
                              "taxes_payable": {"choice": "ok"}})
    assert r2.inputs["accounts_receivable_t"] == 91 and r2.inputs["taxes_payable_t"] == 8
    st = {(f, c): s for f, c, s, _, _ in r2.user_checked}
    assert st[("accounts_receivable", "t")] == check.AMENDED and st[("taxes_payable", "t1")] == check.CONFIRMED
    assert ("accounts_receivable", "t", check.AMENDED) in {(f, c, s) for f, c, s, _ in r2.review}
    assert r.inputs["accounts_receivable_t"] == 250        # the original reading is not changed


def test_apply_refuses_unanswered_and_missing_amounts():
    r = _result()
    its = check.items(r)
    with pytest.raises(check.AnswerError):
        check.apply(r, its, {"accounts_receivable": {"choice": "ok"}})
    with pytest.raises(check.AnswerError):
        check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "91", "t1": ""},
                             "taxes_payable": {"choice": "ok"}})


def test_same_amount_entered_counts_as_agreed_not_amended():
    r = _result()
    its = check.items(r)
    r2 = check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "250", "t1": "220"},
                              "taxes_payable": {"choice": "ok"}})
    assert {s for f, c, s, _, _ in r2.user_checked} == {check.CONFIRMED}


def test_xbrl_path_reason_comes_from_technical_note_not_user_text():
    r = _result()
    r.review = [(f, c, s, check.Msg("chk.note.single")) for f, c, s, _ in r.review]
    r.xbrl = {"notes": {("taxes_payable", "t"): "D-03g PENDEKATAN (total taxes payable)",
                        ("taxes_payable", "t1"): "D-03g PENDEKATAN (total taxes payable)"}}
    its = check.items(r)
    assert {i.field: i.reason.key for i in its}["taxes_payable"] == "chk.r.tax_proxy"


# ---------------------------------------------------------------- opsi 1 safety fixes (after XBRL stage 6, 4 Nov 2026)
def _amort_result():
    vals = [Value("amortization_intangibles", "t", 0, "REVIEW"), Value("amortization_intangibles", "t1", 0, "REVIEW"),
            Value("ppe_depreciation_disclosed", "t", 50, "FOUND"), Value("ppe_depreciation_disclosed", "t1", 40, "FOUND")]
    ex = SimpleNamespace(values=vals, fiscal_year=2022, statements={}, fs_location={})
    p = {"amortization_intangibles_t": 0, "amortization_intangibles_t1": 0, "ppe_depreciation_disclosed_t": 50,
         "ppe_depreciation_disclosed_t1": 40, "depreciation_amortization_non_ppe_t": 0,
         "depreciation_amortization_non_ppe_t1": 0, "depreciation_amortization_total_t": 50,
         "depreciation_amortization_total_t1": 40}
    return SimpleNamespace(extraction=ex, inputs=p, calc={}, flags=[], missing=[], unreadable="",
                           review=[("amortization_intangibles", "t", "REVIEW", ""),
                                   ("amortization_intangibles", "t1", "REVIEW", "")])


def test_amortisation_in_review_is_shown_and_rebuilds_the_da_total():
    r = _amort_result()
    its = check.items(r)
    assert [i.field for i in its] == ["amortization_intangibles"]     # stage 6: REVIEW here never reached the user
    r2 = check.apply(r, its, {"amortization_intangibles": {"choice": "edit", "t": "101", "t1": "103"}})
    assert (r2.inputs["depreciation_amortization_total_t"], r2.inputs["depreciation_amortization_total_t1"]) == (151, 143)


def test_agreed_amortisation_leaves_the_da_total_alone():
    # negative: confirming the reading changes nothing
    r = _amort_result()
    r2 = check.apply(r, check.items(r), {"amortization_intangibles": {"choice": "ok"}})
    assert r2.inputs["depreciation_amortization_total_t"] == 50


def _merge_inputs(unreadable):
    pr = SimpleNamespace(extraction=SimpleNamespace(values=[], issues=[]), inputs={}, calc={}, flags=[],
                         unreadable=unreadable, review=[], missing=[], assumed=[])
    xres = SimpleNamespace(items=[], inputs={}, calc={"m_score_B": 3.1}, held=[], gate=[], xbrl={}, tax={},
                           warnings=[])
    return pr, xres


def test_xbrl_score_withheld_when_pdf_statements_unreadable():
    pr, xres = _merge_inputs("statement pages are images")
    r = check.merge_xbrl(pr, xres)
    assert r.calc["m_score_B"] == ""


def test_xbrl_score_kept_when_pdf_readable():
    # negative: a readable PDF does not withhold the score
    pr, xres = _merge_inputs("")
    pr.extraction.values = []
    import wars_scanner.validation as V
    orig = V.check
    V.check = lambda p, ex: []
    try:
        r = check.merge_xbrl(pr, xres)
    finally:
        V.check = orig
    assert r.calc["m_score_B"] == 3.1
