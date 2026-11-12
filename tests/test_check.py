"""Review step (Gail, 4 Nov 2026): answers, origin of amounts, reasons. Synthetic data only."""
from types import SimpleNamespace

import pytest

from wars_scanner import check
from wars_scanner.pdf_reader import Value
from wars_scanner.text import Msg, render


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
    r2 = check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "91", "t1": "33", "page": "12"},
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
        check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "91", "t1": "", "page": "12"},
                             "taxes_payable": {"choice": "ok"}})


def test_same_amount_entered_counts_as_agreed_not_amended():
    r = _result()
    its = check.items(r)
    r2 = check.apply(r, its, {"accounts_receivable": {"choice": "edit", "t": "250", "t1": "220", "page": "12"},
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
    r2 = check.apply(r, its, {"amortization_intangibles": {"choice": "edit", "t": "101", "t1": "103", "page": "12"},
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
    assert {i.field: i.reason.key for i in its} == {
        "long_term_debt": "chk.r.risk_debt", "current_maturities_long_term_debt": "chk.r.risk_debt",
        "taxes_payable": "chk.r.risk_tax", "ppe_depreciation_disclosed": "chk.r.risk"}
    # negative: a FOUND line outside the risk list (revenue) is not added; tax payable never gets the lease wording


def test_target_b_counted_zero_amortisation_goes_to_the_review_screen():
    r = _b_result({"amortization_intangibles": "UNDISCLOSED", "depreciation_amortization_non_ppe": "ASSUMED"})
    its = check.items(r)
    assert [i.field for i in its] == ["amortization_intangibles", "depreciation_amortization_non_ppe"]
    by = {i.field: i for i in its}
    # present but undisclosed: zero under the workbook rule, Agree / Amend with the rule named
    assert by["amortization_intangibles"].reason.key == "chk.r.risk_undisclosed"
    assert by["amortization_intangibles"].mode == "review"
    # not found in both years: completed like a missing line (amount with page, or nil with the notes examined);
    # 'Agree' would record a provisional 0 as verified (RUNS FY2025 report review, 12 Nov 2026, item 2.1)
    assert by["depreciation_amortization_non_ppe"].reason.key == "chk.r.risk_zero"
    assert by["depreciation_amortization_non_ppe"].mode == "missing"


def test_target_b_assumed_zero_in_one_year_only_keeps_agree_amend():
    # must NOT: turn a line read in one year into nil for both years
    r = _b_result({"depreciation_amortization_non_ppe": "ASSUMED"})
    v = next(x for x in r.extraction.values if x.column == "t1")
    v.status, v.value = "REVIEW", 90
    r.inputs["depreciation_amortization_non_ppe_t1"] = 90
    its = check.items(r)
    assert [(i.field, i.mode) for i in its] == [("depreciation_amortization_non_ppe", "review")]


def test_assumed_zero_nil_records_the_basis_and_none_present():
    r = _b_result({"depreciation_amortization_non_ppe": "ASSUMED"})
    r.inputs.update(non_ppe_status_t="PARTIAL_UNDISCLOSED", non_ppe_status_t1="PARTIAL_UNDISCLOSED")
    its = check.items(r)
    with pytest.raises(check.AnswerError):          # nil without the notes examined is refused
        check._apply_missing(r, {(v.field, v.column): v for v in r.extraction.values}, r.inputs, its[0], {"choice": "nil"})
    got = check._apply_missing(r, {(v.field, v.column): v for v in r.extraction.values}, r.inputs, its[0],
                               {"choice": "nil", "note": "Catatan 10, 11"})
    assert [g[4] for g in got] == [0, 0]
    assert r.inputs["non_ppe_status_t"] == r.inputs["non_ppe_status_t1"] == "NONE_PRESENT"
    from wars_scanner import report
    assert {report._shown_status(v) for v in r.extraction.values} == {"USER NIL"}


def test_missing_line_text_names_nil_only_where_nil_is_offered():
    r = _b_result({"revenue": "NOT FOUND", "long_term_debt": "NOT FOUND"})
    r.missing = [(f, c, "NOT FOUND", "") for f in ("revenue", "long_term_debt") for c in ("t", "t1")]
    its = {i.field: i.reason.key for i in check.items(r)}
    assert its == {"revenue": "chk.r.missing_val", "long_term_debt": "chk.r.missing"}


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
    r2 = check.apply(r, check.items(r), {"property_plant_equipment_net": {"choice": "edit", "t": "131", "t1": "153", "page": "12"},
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


# ---------------------------------------------------------------- lines WARS did not find (Gail, 8 Nov 2026 16.21)
def _miss_result(field, both=True):
    r = _b_result({"revenue": "FOUND", field: "NOT FOUND"})
    r.missing = [(field, "both" if both else "t", "NOT FOUND", "")]
    return r


def test_not_found_score_line_is_offered_for_completion():
    r = _miss_result("current_maturities_long_term_debt")
    its = check.items(r)
    assert [(i.field, i.mode, i.reason.key) for i in its] == [
        ("current_maturities_long_term_debt", "missing", "chk.r.missing")]
    # negative: a blank amount with no NOT FOUND record (withheld for another reason) is not offered
    r.missing = []
    assert check.items(r) == []


def test_enter_amount_needs_the_source_page():
    r = _miss_result("current_maturities_long_term_debt")
    its = check.items(r)
    with pytest.raises(check.AnswerError):
        check.apply(r, its, {"current_maturities_long_term_debt": {"choice": "enter", "t": "8109", "t1": "5609"}})
    r2 = check.apply(r, its, {"current_maturities_long_term_debt":
                              {"choice": "enter", "t": "8109", "t1": "5609", "page": "45"}})
    assert (r2.inputs["current_maturities_long_term_debt_t"], r2.inputs["current_maturities_long_term_debt_t1"]) == \
        (8109, 5609)
    assert r2.missing == [] and {s for _, _, s, _, _ in r2.user_checked} == {check.AMENDED}
    v = [x for x in r2.extraction.values if x.field == "current_maturities_long_term_debt"][0]
    assert v.note.key == "chk.prov.entered"


def test_nil_needs_the_notes_examined_and_only_where_nil_is_possible():
    r = _miss_result("long_term_debt")
    its = check.items(r)
    with pytest.raises(check.AnswerError):
        check.apply(r, its, {"long_term_debt": {"choice": "nil", "note": " "}})
    r2 = check.apply(r, its, {"long_term_debt": {"choice": "nil", "note": "Catatan 15 dan 18"}})
    assert (r2.inputs["long_term_debt_t"], r2.inputs["long_term_debt_t1"]) == (0, 0)
    # negative: nil is refused for a line that cannot be nil (revenue)
    r = _miss_result("total_assets")
    with pytest.raises(check.AnswerError):
        check.apply(r, check.items(r), {"total_assets": {"choice": "nil", "note": "Catatan 1"}})
    # negative: Agree is not an answer for a line that was not found
    with pytest.raises(check.AnswerError):
        check.apply(r, check.items(r), {"total_assets": {"choice": "ok"}})


# ---------------------------------------------------------------- page extract ignores text outside the page
def _pdf_with_offpage_text():
    import io as _io
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.drawString(300, 700, "Jumlah 1,429,971 1,110,881")
    c.drawString(-370, 160, "1,110,881")            # hidden text left of the page
    c.drawString(100, 160, "Unrelated insurance sentence")
    c.save()
    return buf.getvalue()


def test_extract_ignores_hits_outside_the_page():
    from PIL import Image
    import io as _io
    data = _pdf_with_offpage_text()
    it = check.CheckItem("ppe_depreciation_disclosed", {"t": 1429971, "t1": 1110881}, Msg("chk.r.risk"), [1],
                         [1429971, 1110881], [])
    png, pg = check.extract_png(data, it, scale=1.0)
    assert pg == 1
    h = Image.open(_io.BytesIO(png)).size[1]
    assert h < 300          # the crop stays around the amounts at y=700, not stretched down to y=160


def test_extract_still_finds_amounts_on_the_page():
    # negative: amounts printed on the page are still found
    data = _pdf_with_offpage_text()
    it = check.CheckItem("ppe_depreciation_disclosed", {"t": 1429971, "t1": 1110881}, Msg("chk.r.risk"), [1],
                         [1429971], [])
    png, pg = check.extract_png(data, it, scale=1.0)
    assert png is not None and pg == 1


# ---------------------------------------------------------------- stage 6 finding F: inconsistent columns withhold
def test_layout_flag_empties_the_review_screen_and_survives_apply():
    from wars_scanner.validation import Flag
    r = _b_result({"long_term_debt": "FOUND"})
    r.flags = [Flag(check.LAYOUT_FLAG, "ERROR", "app", Msg("chk.layout_cols", pages="12"))]
    assert check.items(r) == []
    r2 = check.apply(r, [], {})
    assert any(f.code == check.LAYOUT_FLAG for f in r2.flags)
    # negative: without the flag the review screen is unchanged
    r.flags = []
    assert [i.field for i in check.items(r)] == ["long_term_debt"]


# ---------------------------------------------------------------- amended amount needs its source page (Gail 10 Nov)
def _edit_case():
    r = _result()
    return r, check.items(r)


def test_edit_without_page_is_refused():
    r, its = _edit_case()
    f = its[0].field
    ans = {it.field: {"choice": "ok"} for it in its}
    for bad in ("", " ", "0", "p12", "-3", "1.5"):
        ans[f] = {"choice": "edit", "t": "91", "t1": "33", "page": bad}
        with pytest.raises(check.AnswerError) as e:
            check.apply(r, its, ans)
        assert e.value.args[0].key == "chk.err.page"


def test_edit_with_page_replaces_wars_page_and_notes_it():
    r, its = _edit_case()
    f = its[0].field
    ans = {it.field: {"choice": "ok"} for it in its}
    old_t1 = its[0].values["t1"]
    ans[f] = {"choice": "edit", "t": "91", "t1": str(old_t1), "page": "068"}
    r2 = check.apply(r, its, ans)
    by = {(v.field, v.column): v for v in r2.extraction.values}
    assert by[(f, "t")].pages == [68]                      # the user's page, as a PDF-file page number
    assert by[(f, "t")].note.key == "chk.prov.amended"
    assert "68" in render(by[(f, "t")].note, "id") and "250" in render(by[(f, "t")].note, "id")
    old_pages = [v.pages for v in r.extraction.values if v.field == f and v.column == "t1"]
    assert by[(f, "t1")].pages == old_pages[0]            # unchanged amount keeps WARS's page
    rev = {(x[0], x[1]): x for x in r2.review}
    assert rev[(f, "t")][3].key == "chk.prov.amended"


def test_ok_needs_no_page():
    r, its = _edit_case()
    r2 = check.apply(r, its, {it.field: {"choice": "ok"} for it in its})
    assert all(s == check.CONFIRMED for _, _, s, _, _ in r2.user_checked)


# ---------------------------------------------------------------- XBRL stage 7, findings 4, 5, 6 (synthetic)
def test_stage7_located_kind_only_when_one_kind():
    from wars_scanner.pdf_reader import _located_kind
    chosen = {"position": [13, 14], "profit_loss": [15], "cash_flow": [17, 18], "notes_start": 19}
    assert _located_kind(chosen, 13) == "position"
    # negatives: a page outside the located statements, no location at all, a page claimed by two kinds
    assert _located_kind(chosen, 16) is None and _located_kind(None, 13) is None
    assert _located_kind({"position": [13], "profit_loss": [13]}, 13) is None


def _np_result(status, value):
    vals = [Value("depreciation_amortization_non_ppe", c, value, status) for c in ("t", "t1")]
    ex = SimpleNamespace(values=vals, fiscal_year=2022, statements={}, fs_location={})
    p = {"depreciation_amortization_non_ppe_t": value, "depreciation_amortization_non_ppe_t1": value}
    miss = [("depreciation_amortization_non_ppe", c, status, "") for c in ("t", "t1")] if value is None else []
    return SimpleNamespace(extraction=ex, inputs=p, calc={}, flags=[], missing=miss, unreadable="", review=[])


def test_stage7_not_assessed_line_can_be_completed():
    r = _np_result("NOT ASSESSED", None)
    its = [i for i in check.items(r) if i.field == "depreciation_amortization_non_ppe"]
    assert its and its[0].mode == "missing"
    r2 = check.apply(r, its, {"depreciation_amortization_non_ppe": {"choice": "nil", "note": "9. Properti investasi"}})
    assert r2.inputs["non_ppe_status_t"] == "NONE_PRESENT" and r2.inputs["depreciation_amortization_non_ppe_t"] == 0
    r3 = check.apply(r, its, {"depreciation_amortization_non_ppe": {"choice": "enter", "t": "5", "t1": "4", "page": "50"}})
    assert r3.inputs["non_ppe_status_t"] == "PARTIAL_UNDISCLOSED"          # M-14: an entered amount is never ALL_DISCLOSED


def test_stage7_assumed_with_an_amount_is_not_called_zero():
    it = SimpleNamespace(status="ASSUMED", value=83_597_601_132)
    assert check._user_note(it).key == "chk.note.assumed_part"
    assert check._user_note(SimpleNamespace(status="ASSUMED", value=0)).key == "chk.note.assumed"   # negative
    r = _np_result("ASSUMED", 83_597_601_132)
    its = [i for i in check.items(r) if i.field == "depreciation_amortization_non_ppe"]
    assert its[0].reason.key == "chk.r.risk"
    r0 = _np_result("ASSUMED", 0)                                             # negative: a real zero keeps 2A
    assert [i for i in check.items(r0) if i.field == "depreciation_amortization_non_ppe"][0].reason.key == "chk.r.risk_zero"


def test_stage7_da_total_shown_is_the_one_used():
    v = Value("depreciation_amortization_total", "t", 89_819, "FOUND")
    keep = Value("depreciation_amortization_total", "t1", 80_000, "FOUND")
    r = SimpleNamespace(extraction=SimpleNamespace(values=[v, keep]),
                        inputs={"depreciation_amortization_total_t": 99_315, "depreciation_amortization_total_t1": 80_000})
    check._sync_da_total(r)
    assert (v.value, v.status) == (99_315, "BUILT FROM DISCLOSED COMPONENTS")
    assert (keep.value, keep.status) == (80_000, "FOUND")                      # negative: same figure, untouched


# ---------------------------------------------------------------- issuer from a cut master name or the XBRL code (10 Nov)
def test_issuer_cut_master_name_and_negatives():
    from wars_scanner import company
    who, _ = company.identify("PT ASTRINDO NUSANTARA INFRASTRUKTUR Tbk DAN ENTITAS ANAK LAPORAN POSISI KEUANGAN")
    assert who and who.ticker == "BIPI"          # master: 'Astrindo Nusantara Infrastrukt' (cut at 30 characters)
    # negatives: a different last word, a missing word, and a full master name never match by prefix
    assert company.identify("PT ASTRINDO NUSANTARA ENERGI Tbk")[0] is None
    assert company.identify("PT ASTRINDO INFRASTRUKTUR Tbk")[0] is None
    assert company._name_in("Astra Agro Lestari Tbk.", frozenset({"astra", "agro", "lestarian"})) is False


def test_issuer_from_xbrl_entity_code():
    from wars_scanner import company
    assert company.by_ticker("bipi").ticker == "BIPI" and company.by_ticker("ZZZZ") is None


def test_issuer_name_from_xbrl_entity_name():
    from wars_scanner import company
    r = SimpleNamespace(issuer=None)
    x_issuer = company.by_ticker("BIPI")
    # the workbook master cuts the name at 30 characters; Gail's full names (11 Nov) replace the cut ones
    assert x_issuer.name == "Astrindo Nusantara Infrastruktur Tbk."
    assert company.by_ticker("DSFI").name == "Dharma Samudera Fishing Industries Tbk."   # confirmed by Gail 11 Nov 10.45
    import re as _re
    name = _re.sub(r"^\s*PT\.?\s+", "", "PT Astrindo Nusantara Infrastruktur Tbk.").strip()
    assert name == "Astrindo Nusantara Infrastruktur Tbk."
