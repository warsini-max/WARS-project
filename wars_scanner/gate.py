"""Score gate (P0-1; Gail 13 Nov 2026 16.46, decisions K1-K8 and authorisation of P0).

The control that every M-score the user sees rests on inputs that are either verified or put in front of the
user: CLAUDE.md rules 1 and 7, target B (risk fields always on the review screen, Gail 8 Nov 2026), and the
invariants INV-1 to INV-4 and INV-10 of `WARS_Invariant_and_Regression_Test_Plan_r0.md`.

  INV-3  a value of None never carries a status that claims a value (REVIEW / FOUND / ASSUMED / UNDISCLOSED):
         `normalize` turns it into NOT FOUND and lists it as missing, so it is completed like any missing line
         (XBRL stage 9: HOPE 2025, PPE depreciation 2025 was REVIEW without a value and had no card).
  INV-1  every engine input is FOUND or set by the user, or it has a card, or the score is withheld;
  INV-2  every input that needs the user's action has a card (risk fields always, target B);
  INV-10 a score whose inputs are not covered is never shown: `enforce` records the uncovered inputs in
         `r.gate_block`, and `pipeline.Result.m_score` is then None (the report says which items).

The gate never changes a source value, the Beneish formulas or the indices. It only changes the status of a
value that has none (INV-3) and withholds the score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# the engine inputs the review step covers (check.CHECK_FIELDS); kept here so that the gate has no import cycle
GATE_FIELDS = (
    "revenue", "cost_of_goods_sold", "selling_general_administrative_expenses", "accounts_receivable",
    "total_assets", "current_assets", "property_plant_equipment_net", "current_liabilities", "total_liabilities",
    "long_term_debt", "current_maturities_long_term_debt", "cash_and_cash_equivalents", "taxes_payable",
    "ppe_depreciation_disclosed", "amortization_intangibles", "depreciation_amortization_non_ppe",
    "net_income", "cash_flow_from_operations",
)
RISK_FIELDS = ("long_term_debt", "current_maturities_long_term_debt", "taxes_payable",
               "ppe_depreciation_disclosed", "amortization_intangibles", "depreciation_amortization_non_ppe")
USER_STATUSES = {"USER CONFIRMED", "USER AMENDED", "USER SET"}
VERIFIED_STATUSES = {"FOUND"} | USER_STATUSES
NO_VALUE_STATUSES = {"NOT FOUND", "NOT ASSESSED", "NOT DISCLOSED", "STATEMENT NOT FOUND", "NOT SEARCHED",
                     "INCLUDED IN PPE"}
COLUMNS = ("t", "t1")


@dataclass
class GateResult:
    uncovered: list = field(default_factory=list)     # (field, column, status): needs the user, no card
    normalized: list = field(default_factory=list)    # (field, column, old status): INV-3 repairs
    withheld: bool = False                            # the score was already withheld for another reason

    @property
    def ok(self):
        return not self.uncovered or self.withheld


def _values(r):
    return {(v.field, v.column): v for v in (getattr(r.extraction, "values", None) or [])
            if v.column in COLUMNS}


def normalize(r):
    """INV-3. A value of None with a status that claims a value becomes NOT FOUND (the note is kept) and is listed
    as missing, on the reading and on the XBRL items. Returns [(field, column, old status)]."""
    fixed = []
    missing = list(getattr(r, "missing", None) or [])
    have = {(m[0], m[1]) for m in missing}
    for v in getattr(r.extraction, "values", None) or []:
        if v.field in GATE_FIELDS and v.column in COLUMNS and v.value is None and v.status not in NO_VALUE_STATUSES:
            fixed.append((v.field, v.column, v.status))
            v.status = "NOT FOUND"
            if (v.field, v.column) not in have:
                missing.append((v.field, v.column, "NOT FOUND", v.note))
                have.add((v.field, v.column))
    xb = getattr(r, "xbrl", None) or {}
    for it in xb.get("items") or []:
        if it.field in GATE_FIELDS and it.value is None and it.status not in NO_VALUE_STATUSES:
            if (it.field, it.column, it.status) not in fixed:
                fixed.append((it.field, it.column, it.status))
            it.status = "NOT FOUND"
            if (it.field, it.column) not in have:
                missing.append((it.field, it.column, "NOT FOUND", it.note))
                have.add((it.field, it.column))
    if fixed:
        r.missing = missing
        r.review = [x for x in (getattr(r, "review", None) or []) if (x[0], x[1]) not in {(f, c) for f, c, _ in fixed}]
    r.gate_normalized = list(getattr(r, "gate_normalized", None) or []) + fixed
    return fixed


def needs_user(field_name, status):
    """True when the value may enter the score only after the user has seen it (INV-1/INV-2)."""
    if status in USER_STATUSES:
        return False
    if field_name in RISK_FIELDS:
        return True                                    # target B: risk fields are always reviewed
    return status not in VERIFIED_STATUSES


def withheld_otherwise(r):
    """The score is not shown for a reason of its own (not computed, cross-check error, unreadable, skipped)."""
    if getattr(r, "unreadable", "") or getattr(r, "verification_skipped", False):
        return True
    m = (getattr(r, "calc", None) or {}).get("m_score_B")
    if not isinstance(m, (int, float)):
        return True
    return any(getattr(f, "severity", "") == "ERROR" for f in (getattr(r, "flags", None) or []))


def evaluate(r, checks):
    """INV-1/INV-2 for one result and the cards built for it (check.items)."""
    cards = {it.field for it in checks or []}
    vals = _values(r)
    out = GateResult(normalized=list(getattr(r, "gate_normalized", None) or []))
    for f in GATE_FIELDS:
        for c in COLUMNS:
            v = vals.get((f, c))
            used = (getattr(r, "inputs", None) or {}).get(f"{f}_{c}") is not None
            if v is None and not used:
                continue                               # no reading and no input (e.g. a field the path never reads)
            status = v.status if v is not None else "NOT FOUND"
            if needs_user(f, status) and f not in cards:
                out.uncovered.append((f, c, status))
    out.withheld = withheld_otherwise(r)
    return out


def enforce(r, checks):
    """Evaluate and record the gate on the result. An uncovered input withholds the score (INV-10)."""
    g = evaluate(r, checks)
    r.gate = g
    r.gate_block = [] if g.ok else list(g.uncovered)
    return g
