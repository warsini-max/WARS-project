"""P0-1 score gate (Gail 13 Nov 2026 16.46). Invariants INV-1 to INV-4 and INV-10 of
WARS_Invariant_and_Regression_Test_Plan_r0.md, with positive and negative cases (CLAUDE.md rule 7), and the
property test INV-P over at least 10,000 random combinations of status, value, field and column."""
import random
from types import SimpleNamespace as NS

from wars_scanner import check, engine, gate, pipeline, report
from wars_scanner.pdf_reader import Extraction, Value

FIELDS = gate.GATE_FIELDS


def _result(values, calc_m=-2.5, review=None, missing=None, xbrl=None, unreadable="", flags=None):
    ex = Extraction("test.pdf", 10, [], 2025, "Full", "Consolidated", {}, values, [])
    inputs = {f"{v.field}_{v.column}": v.value for v in values if v.value is not None}
    r = pipeline.Result(ex, inputs, {"m_score_B": calc_m}, review=list(review or []), missing=list(missing or []),
                        unreadable=unreadable, flags=list(flags or []))
    if xbrl is not None:
        r.xbrl = xbrl
    return r


def _all_found(over=None):
    over = over or {}
    vals = []
    for f in FIELDS:
        for c in ("t", "t1"):
            st, v = over.get((f, c), ("FOUND", 100))
            vals.append(Value(f, c, v, st))
    return vals


# ------------------------------------------------------------------ INV-3 / INV-4

def test_review_without_value_becomes_not_found_and_missing():
    vals = _all_found({("ppe_depreciation_disclosed", "t"): ("REVIEW", None)})
    r = _result(vals, review=[("ppe_depreciation_disclosed", "t", "REVIEW", "")])
    fixed = gate.normalize(r)
    assert fixed == [("ppe_depreciation_disclosed", "t", "REVIEW")]
    v = next(x for x in r.extraction.values if (x.field, x.column) == ("ppe_depreciation_disclosed", "t"))
    assert v.status == "NOT FOUND" and v.value is None
    assert ("ppe_depreciation_disclosed", "t") in {(m[0], m[1]) for m in r.missing}
    assert ("ppe_depreciation_disclosed", "t") not in {(x[0], x[1]) for x in r.review}


def test_normalize_leaves_valid_states_alone():
    # must NOT: change a value, a NOT FOUND, a zero, or a text field
    vals = _all_found({("taxes_payable", "t"): ("NOT FOUND", None), ("long_term_debt", "t"): ("FOUND", 0),
                         ("amortization_intangibles", "t"): ("ASSUMED", 0)})
    vals.append(Value("amort_status", "t", None, "FOUND"))
    before = [(v.field, v.column, v.value, v.status) for v in vals]
    r = _result(vals)
    assert gate.normalize(r) == []
    assert [(v.field, v.column, v.value, v.status) for v in r.extraction.values] == before


def test_xbrl_item_review_without_value_is_normalized():
    it = NS(field="ppe_depreciation_disclosed", column="t", value=None, status="REVIEW", note="n", source="")
    r = _result(_all_found({("ppe_depreciation_disclosed", "t"): ("REVIEW", None)}), xbrl={"items": [it]})
    gate.normalize(r)
    assert it.status == "NOT FOUND"


def test_items_never_drops_a_line_without_a_value():
    # HOPE 2025: one year read, the other None -> a 'missing' card asking for the amount (depreciation cannot be nil)
    vals = _all_found({("ppe_depreciation_disclosed", "t"): ("NOT FOUND", None)})
    r = _result(vals, missing=[("ppe_depreciation_disclosed", "t", "NOT FOUND", "")])
    cards = {i.field: i for i in check.items(r)}
    assert cards["ppe_depreciation_disclosed"].mode == "missing"
    assert cards["ppe_depreciation_disclosed"].reason.key == "chk.r.missing_val"


def test_items_missing_card_even_when_the_line_is_not_listed_as_missing():
    # the defensive branch of items(): a REVIEW line with one year None and not in r.missing still gets a card
    vals = _all_found({("revenue", "t1"): ("REVIEW", None)})
    r = _result(vals, review=[("revenue", "t", "REVIEW", "x")])
    cards = {i.field: i for i in check.items(r)}
    assert cards["revenue"].mode == "missing"


# ------------------------------------------------------------------ INV-1 / INV-2 / INV-10

def test_gate_passes_when_every_input_is_found_or_carded():
    r = _result(_all_found())
    g = gate.enforce(r, check.items(r))            # risk fields FOUND -> carded by target B
    assert g.ok and not r.gate_block and r.m_score == -2.5


def test_gate_blocks_an_uncovered_review_input():
    vals = _all_found({("selling_general_administrative_expenses", "t"): ("REVIEW", 100)})
    r = _result(vals)                               # REVIEW not listed in r.review -> items() builds no card for it
    g = gate.enforce(r, check.items(r))
    assert ("selling_general_administrative_expenses", "t", "REVIEW") in g.uncovered
    assert r.gate_block and r.m_score is None
    head, detail, _ = report.verdict(r, None, "id", provisional_note=False)
    assert "ditahan" in head.lower() and "Beban penjualan" in detail


def test_gate_blocks_an_uncovered_risk_field_even_when_found():
    vals = _all_found()
    r = _result(vals)
    cards = [i for i in check.items(r) if i.field != "taxes_payable"]       # card removed: target B violated
    g = gate.enforce(r, cards)
    assert ("taxes_payable", "t", "FOUND") in g.uncovered and r.m_score is None


def test_user_statuses_need_no_card():
    over = {(f, c): ("USER CONFIRMED", 100) for f in FIELDS for c in ("t", "t1")}
    r = _result(_all_found(over))
    assert gate.enforce(r, []).ok and r.m_score == -2.5


def test_gate_does_not_block_a_score_that_is_withheld_anyway():
    vals = _all_found({("revenue", "t"): ("REVIEW", 100)})
    r = _result(vals, calc_m="")                     # not calculated: nothing is shown
    g = gate.enforce(r, [])
    assert g.withheld and g.ok and not r.gate_block
    r2 = _result(vals, unreadable="scanned")
    assert gate.enforce(r2, []).ok


def test_apply_runs_the_gate_and_a_complete_review_releases_the_score():
    vals = _all_found({("ppe_depreciation_disclosed", "t"): ("NOT FOUND", None)})
    r = _result(vals, missing=[("ppe_depreciation_disclosed", "t", "NOT FOUND", "")])
    r.inputs.update({"fiscal_year_t": 2025, "doc_version": 1})
    its = check.items(r)
    ans = {}
    for i in its:
        if i.mode == "missing" and i.field in check.NIL_FIELDS:
            ans[i.field] = {"choice": "nil", "note": "Catatan 10"}
        elif i.mode == "missing":
            ans[i.field] = {"choice": "enter", "t": "120", "t1": "100", "page": "45"}
        else:
            ans[i.field] = {"choice": "ok"}
    r2 = check.apply(r, its, ans)
    assert r2.gate.ok and not r2.gate_block
    v = next(x for x in r2.extraction.values if (x.field, x.column) == ("ppe_depreciation_disclosed", "t"))
    assert v.value == 120 and v.status == check.AMENDED


# ------------------------------------------------------------------ INV-P (property test)

STATUSES = ["FOUND", "REVIEW", "ASSUMED", "UNDISCLOSED", "NOT FOUND", "NOT ASSESSED", "USER CONFIRMED",
            "USER AMENDED", "USER SET", "BUILT FROM DISCLOSED COMPONENTS"]


def _random_result(rng):
    vals, review, missing = [], [], []
    for f in FIELDS:
        for c in ("t", "t1"):
            st = rng.choice(STATUSES)
            v = rng.choice([None, 0, 1_000, 2_500_000])
            vals.append(Value(f, c, v, st))
            if st in ("REVIEW", "ASSUMED", "UNDISCLOSED") and v is not None and rng.random() < 0.8:
                review.append((f, c, st, ""))
            if v is None and rng.random() < 0.7:
                missing.append((f, c, st, ""))
    calc_m = rng.choice([-2.5, -1.2, ""])
    xbrl = None
    if rng.random() < 0.3:
        xbrl = {"items": [NS(field=v.field, column=v.column, value=v.value, status=v.status, note="", source="")
                          for v in vals if rng.random() < 0.3]}
    return _result(vals, calc_m=calc_m, review=review, missing=missing, xbrl=xbrl)


def test_inv_p_random_combinations():
    rng = random.Random(20261113)
    n = 10_000
    for _ in range(n):
        r = _random_result(rng)
        gate.normalize(r)
        # INV-3: no value of None carries a status that claims a value
        for v in r.extraction.values:
            if v.field in FIELDS and v.value is None:
                assert v.status in gate.NO_VALUE_STATUSES, (v.field, v.status)
        its = check.items(r)
        g = gate.enforce(r, its)
        cards = {i.field for i in its}
        shown = r.m_score is not None
        for v in r.extraction.values:
            if v.field not in FIELDS:
                continue
            if gate.needs_user(v.field, v.status) and shown:
                # INV-1/INV-2/INV-10: a shown score never rests on an input that needs the user and has no card
                assert v.field in cards, (v.field, v.column, v.status)
        # INV-4: every line in r.missing whose input is absent has a card unless the score is withheld anyway
        for m in r.missing:
            if m[0] in FIELDS and shown:
                assert m[0] in cards, m
        # INV-10: the report never shows a score while the gate blocks
        if r.gate_block:
            assert r.m_score is None
