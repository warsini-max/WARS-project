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
    # stage 6: REVIEW here never reached the user; target B (8 Nov) adds the FOUND depreciation as a risk field
    assert [i.field for i in its] == ["ppe_depreciation_disclosed", "amortization_intangibles"]
    r2 = check.apply(r, its, {"amortization_intangibles": {"choice": "edit", "t": "101", "t1": "103"},
                              "ppe_depreciation_disclosed": {"choice": "ok"}})
    assert (r2.inputs["depreciation_amortization_total_t"], r2.inputs["depreciation_amortization_total_t1"]) == (151, 143)


def test_agreed_amortisation_leaves_the_da_total_alone():
    # negative: confirming the reading changes nothing
    r = _amort_result()
    r2 = check.apply(r, check.items(r), {"amortization_intangibles": {"choice": "ok"},
                                         "ppe_depreciation_disclosed": {"choice": "ok"}})
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


# ---------------------------------------------------------------- v1.0 target B (Gail, 8 Nov 2026 12.02)
def _b_result(statuses):
    """statuses: {field: status}; values 100 (t) and 90 (t1); review lists only REVIEW items."""
    vals, p, rev = [], {}, []
    for f, s in statuses.items():
        for c, x in (("t", 100), ("t1", 90)):
            x = 0 if s in ("ASSUMED", "UNDISCLOSED") else x
            vals.append(Value(f, c, x, s))
            p[f"{f}_{c}"] = None if s == "NOT FOUND" else x
            if s == "REVIEW":
                rev.append((f, c, s, ""))
    ex = SimpleNamespace(values=vals, fiscal_year=2022, statements={}, fs_location={})
    return SimpleNamespace(extraction=ex, inputs=p, calc={}, flags=[], missing=[], unreadable="", review=rev)


def test_target_b_found_risk_fields_go_to_the_review_screen():
    r = _b_result({"revenue": "FOUND", "long_term_debt": "FOUND", "current_maturities_long_term_debt": "FOUND",
                   "taxes_payable": "FOUND", "ppe_depreciation_disclosed": "FOUND"})
    its = check.items(r)
    assert [i.field for i in its] == ["long_term_debt", "current_maturities_long_term_debt", "taxes_payable",
                                      "ppe_depreciation_disclosed"]
    assert all(i.reason.key == "chk.r.risk" for i in its)
    # negative: a FOUND line outside the risk list (revenue) is not added


def test_target_b_counted_zero_amortisation_goes_to_the_review_screen():
    r = _b_result({"amortization_intangibles": "UNDISCLOSED", "depreciation_amortization_non_ppe": "ASSUMED"})
    its = check.items(r)
    assert [i.field for i in its] == ["amortization_intangibles", "depreciation_amortization_non_ppe"]
    assert all(i.reason.key == "chk.r.risk_zero" for i in its)


def test_target_b_not_found_and_already_checked_are_not_listed():
    # negative: NOT FOUND withholds the score elsewhere; it has no amount to verify
    assert check.items(_b_result({"long_term_debt": "NOT FOUND"})) == []
    # negative: once the user has verified a risk field it is not asked again
    r = _b_result({"long_term_debt": "FOUND"})
    r2 = check.apply(r, check.items(r), {"long_term_debt": {"choice": "ok"}})
    assert check.items(r2) == []
    assert {s for f, c, s, _, _ in r2.user_checked} == {check.CONFIRMED}


def test_target_b_review_reason_is_kept_for_review_items():
    # negative: a REVIEW risk item keeps its specific reason (here the tax proxy), not the general risk text
    r = _b_result({"taxes_payable": "REVIEW"})
    r.review = [("taxes_payable", c, "REVIEW", "D-03g PENDEKATAN") for c in ("t", "t1")]
    assert check.items(r)[0].reason.key == "chk.r.tax_proxy"


# ---------------------------------------------------------------- stage 6 finding E (HITS)
def _ppe_flag_result():
    from wars_scanner.validation import Flag
    r = _b_result({"property_plant_equipment_net": "REVIEW", "revenue": "REVIEW"})
    fl = Flag("a_ppe_note", "ERROR", "app", "x", ("property_plant_equipment_net",), "t")
    r.flags = [fl]
    return r, fl


def test_user_checked_ppe_drops_the_pdf_reading_check(monkeypatch):
    import wars_scanner.validation as V
    r, fl = _ppe_flag_result()
    monkeypatch.setattr(V, "check", lambda p, ex: [fl])
    r2 = check.apply(r, check.items(r), {"property_plant_equipment_net": {"choice": "edit", "t": "131", "t1": "153"},
                                         "revenue": {"choice": "ok"}})
    assert all(f.code != "a_ppe_note" for f in r2.flags)


def test_pdf_reading_check_kept_for_unchecked_field(monkeypatch):
    # negative: the PPE check stays when PPE itself was not verified by the user
    import wars_scanner.validation as V
    from wars_scanner.validation import Flag
    r = _b_result({"revenue": "REVIEW"})
    fl = Flag("a_ppe_note", "ERROR", "app", "x", ("property_plant_equipment_net",), "t")
    monkeypatch.setattr(V, "check", lambda p, ex: [fl])
    r2 = check.apply(r, check.items(r), {"revenue": {"choice": "ok"}})
    assert any(f.code == "a_ppe_note" for f in r2.flags)
