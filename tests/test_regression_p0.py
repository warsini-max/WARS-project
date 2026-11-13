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
