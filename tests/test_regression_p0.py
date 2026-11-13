"""P0 regression on real development reports (REG-HOPE25, REG-PURI22, REG-CTTH22 of
WARS_Invariant_and_Regression_Test_Plan_r0.md). The source PDFs are not in git (CLAUDE.md rule 5): the tests are
skipped when the files are absent. Location: $WARS_DATA (default /mnt/user-data/uploads)."""
import os

import pytest

from wars_scanner import check, gate, report, xbrl_pipeline

DATA = os.environ.get("WARS_DATA", "/mnt/user-data/uploads")


def _pair(stage, tk, year):
    d = os.path.join(DATA, f"WARS_Trial_XBRL_{stage}")
    z, p = os.path.join(d, f"{tk}_instance_{year}.zip"), os.path.join(d, f"{tk}_LK_{year}.pdf")
    if not (os.path.exists(z) and os.path.exists(p)):
        pytest.skip(f"{tk} {year} not available")
    x = xbrl_pipeline.run(open(z, "rb").read(), p)
    r = check.merge_xbrl(x.pdf, x)
    its = check.items(r)
    check.annotate(r, its)
    gate.enforce(r, its)
    return r, its


def _answer(its, enter):
    ans = {}
    for i in its:
        if i.field in enter:
            ans[i.field] = {"choice": "enter", **enter[i.field]}
        elif i.mode == "missing" and i.field in check.NIL_FIELDS:
            ans[i.field] = {"choice": "nil", "note": "test"}
        elif i.mode == "missing":
            raise AssertionError(f"unexpected missing card {i.field}")
        else:
            ans[i.field] = {"choice": "ok"}
    return ans


def test_reg_hope25_review_without_value_is_a_card():
    r, its = _pair("Tahap 9", "HOPE", 2025)
    cards = {i.field: i for i in its}
    # the 2025 PPE depreciation (REVIEW without a value at 7cc725e) is now a card asking for the amount
    assert "ppe_depreciation_disclosed" in cards and cards["ppe_depreciation_disclosed"].mode == "missing"
    v = next(x for x in r.extraction.values if (x.field, x.column) == ("ppe_depreciation_disclosed", "t"))
    assert v.value is None and v.status == "NOT FOUND"
    assert r.m_score is None and r.gate.ok
    head, detail, _ = report.verdict(r, None, "id", provisional_note=False)
    assert "penyusutan aset tetap" in detail.lower()    # the reason names the item
    # the user enters the amount from the allocation table (note 11: 7.228.098.640 + ROU 611.406.830)
    r2 = check.apply(r, its, _answer(its, {"ppe_depreciation_disclosed": {"t": "7839505470", "t1": "1674180313",
                                                                         "page": "40"}}))
    assert r2.gate.ok and not r2.gate_block and isinstance(r2.m_score, float)


def test_reg_puri22_unreadable_report_shows_no_score():
    r, its = _pair("Tahap 6", "PURI", 2022)
    assert r.unreadable and its == []
    assert r.m_score is None
    head, _detail, level = report.verdict(r, None, "id", provisional_note=False)
    assert level == "none"


def test_reg_ctth22_not_assessed_line_has_a_card():
    r, its = _pair("Tahap 7", "CTTH", 2022)
    na = {m[0] for m in r.missing if m[2] in ("NOT FOUND", "NOT ASSESSED")}
    cards = {i.field: i for i in its}
    for f in na & set(gate.GATE_FIELDS):
        assert f in cards and cards[f].mode == "missing", f
    assert r.gate.ok


def test_reg_ledger_in_the_app_is_shadow_only():
    """P0-2 (K6): app.analyse attaches the evidence ledger; values, statuses, cards and the score equal the run
    without the ledger."""
    import warnings
    warnings.filterwarnings("ignore")
    r0, its0 = _pair("Tahap 9", "HOPE", 2025)
    import app
    d = os.path.join(DATA, "WARS_Trial_XBRL_Tahap 9")
    r, its = app.analyse.__wrapped__(open(os.path.join(d, "HOPE_LK_2025.pdf"), "rb").read(),
                                     open(os.path.join(d, "HOPE_instance_2025.zip"), "rb").read())
    assert r.ledger and not getattr(r, "ledger_error", None)
    assert {(x["field"], x["column"]) for x in r.ledger} >= {("revenue", "t"), ("long_term_debt", "t1")}
    key = lambda res: [(v.field, v.column, v.value, v.status) for v in res.extraction.values]   # noqa: E731
    assert key(r) == key(r0) and r.m_score == r0.m_score and r.gate_block == r0.gate_block
    assert [(i.field, i.mode) for i in its] == [(i.field, i.mode) for i in its0]


def _ledger(stage, tk, year, path):
    from wars_scanner import ledger
    r, its = _pair(stage, tk, year)
    d = os.path.join(DATA, f"WARS_Trial_XBRL_{stage}")
    pages = xbrl_pipeline.pdf_pages(os.path.join(d, f"{tk}_LK_{year}.pdf"))
    rr = r if path == "X" else xbrl_pipeline.run(open(os.path.join(d, f"{tk}_instance_{year}.zip"), "rb").read(),
                                                 os.path.join(d, f"{tk}_LK_{year}.pdf")).pdf
    return {(x["field"], x["column"]): x for x in ledger.build(rr, pages, path)}


def test_reg_apex25_sga_from_the_tag_is_not_found_in_the_ledger():
    # P0-3 (shadow): selling + G&A from the XBRL tags, printed on 'Beban langsung' / 'Beban usaha' (APEX 2025)
    rows = _ledger("Tahap 9", "APEX", 2025, "X")
    for c in ("t", "t1"):
        x = rows[("selling_general_administrative_expenses", c)]
        assert x["status_old"] == "FOUND" and x["status_proposed"] == "REVIEW", x


def test_reg_mtla25_pdf_partial_sga_and_deferred_tax_rou():
    # P0-4 (shadow): marketing alone, reprinted in its note, is not complete (MTLA 2025, PDF path)
    rows = _ledger("Tahap 9", "MTLA", 2025, "P")
    for c in ("t", "t1"):
        x = rows[("selling_general_administrative_expenses", c)]
        assert x["status_proposed"] == "REVIEW" and x["reason"].startswith("K5-A"), x
    rou = rows.get(("rou_assets_net", "t"))
    assert rou is None or rou["value"] != 598           # must NOT: 'Aset hak guna (598)' of the deferred tax table
