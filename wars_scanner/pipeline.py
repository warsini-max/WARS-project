"""PDF -> engine input -> M-score, with the review list the user must see.

`run(pdf_path)` is the single call the app makes. It never fills a gap: a field the reader did
not find stays blank, so the engine reports NOT CALCULATED with its reason. Values the reader
flagged (REVIEW, UNDISCLOSED, built by rule) are used, and listed so the result is shown as
provisional until the user has checked them.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace

from . import company, engine, validation
from .parameters import NON_PPE_STATUSES
from .pdf_reader import Extraction, read
from .text import Amt, Msg, Pages, Raw, join

USABLE = {"FOUND", "REVIEW", "UNDISCLOSED", "BUILT FROM DISCLOSED COMPONENTS"}
TEXT_FIELDS = {"amort_status", "non_ppe_status"}
ENGINE_FIELDS = set(engine.REQUIRED_14) | {
    "total_liabilities", "net_income", "cash_flow_from_operations", "depreciation_amortization_non_ppe",
    "ppe_depreciation_disclosed", "rou_assets_net", "rou_depreciation"} | TEXT_FIELDS



@dataclass
class Result:
    extraction: Extraction
    inputs: dict
    calc: dict
    review: list = field(default_factory=list)       # (field, column, status, note)
    missing: list = field(default_factory=list)      # (field, column, status, note)
    assumptions: list = field(default_factory=list)
    unreadable: str = ""                              # why the report could not be read at all
    flags: list = field(default_factory=list)         # validation.Flag (Phase 3 cross-checks)
    passed: list = field(default_factory=list)        # app checks that ran and passed
    decisions: dict = field(default_factory=dict)     # M-06: non-PPE status set by the user, per year
    amort_decisions: dict = field(default_factory=dict)  # M-15: amortisation status set by the user, per year
    assumed: list = field(default_factory=list)       # (field, column, note): provisional assumptions (28 Oct 2026)
    issuer: object = None                             # company.Issuer when the header matches the master list

    @property
    def m_score_raw(self):
        m = self.calc.get("m_score_B")
        return m if isinstance(m, (int, float)) else None

    @property
    def errors(self):
        return [f for f in self.flags if f.severity == "ERROR"]

    @property
    def m_score(self):
        """The score as shown to the user: none when a cross-check is ERROR (workbook m_score_usable = N)."""
        return self.m_score_raw if not self.errors else None

    @property
    def non_ppe_pending(self):
        """Years whose non-PPE status is still NOT ASSESSED (M-06: the score is held)."""
        return [c for c in ("t", "t1") if self.inputs.get(f"non_ppe_status_{c}") not in NON_PPE_STATUSES]

    @property
    def amort_pending(self):
        """Years whose amortisation is still NOT ASSESSED because no intangible assets were read (M-15)."""
        return [v.column for v in self.extraction.values
                if v.field == "amortization_intangibles" and v.status == "NOT ASSESSED"]

    @property
    def status(self):
        if self.m_score_raw is None and self.non_ppe_pending and not self.unreadable:
            return "AWAITING NON-PPE STATUS"
        if self.m_score_raw is None and self.amort_pending and not self.unreadable:
            return "AWAITING AMORTISATION STATUS"
        if self.m_score_raw is None:
            return "NOT CALCULATED"
        if self.errors:
            return "NOT USABLE (cross-check error)"
        if self.review or any(f.severity == "REVIEW" for f in self.flags):
            return "PROVISIONAL (inputs to check)"
        return "CALCULATED"


def _currency(ex: Extraction):
    head = " ".join(ln.text for s in ex.statements.values() for ln in s.lines[:25]).lower()
    if re.search(r"dolar|dollar|us\$", head):
        return None                       # not supported yet: leave blank (basis not specified)
    if "rupiah" in head:
        return "IDR"
    return None


def build_inputs(ex: Extraction, ticker: str = "UPLOAD", doc_version: int = 1):
    p = {"ticker": ticker, "fiscal_year_t": ex.fiscal_year, "doc_version": doc_version,
         "statement_type": ex.statement_type, "reporting_currency": _currency(ex), "unit_scale": ex.unit_scale}
    review, missing = [], []
    for v in ex.values:
        if v.field not in ENGINE_FIELDS:
            continue
        key = f"{v.field}_{v.column}"
        if v.field in TEXT_FIELDS:
            if v.value is not None:
                p[key] = v.value
            if v.status != "FOUND":
                review.append((v.field, v.column, v.status, v.note))
            continue
        if v.value is not None and v.status in USABLE:
            p[key] = v.value
            if v.status != "FOUND":
                review.append((v.field, v.column, v.status, v.note))
        else:
            missing.append((v.field, v.column, v.status, v.note))
    # M-08 package: transition / restated-comparative inputs read from the report (workbook Pair_Inputs fields)
    trans = getattr(ex, "transition", None) or {}
    p.update(trans.get("inputs", {}))
    if trans.get("evidence"):
        p["_transition_evidence"] = trans["evidence"]          # pages for the REVIEW messages; not an engine input
    assumptions = [Msg("assume.first_issue")]          # doc_version = 1 (M-07, PROPOSED)
    for k in ("statement_type", "reporting_currency", "unit_scale"):
        if not p.get(k):
            missing.append((k, "both", "NOT FOUND", Msg("note.basis")))
    return p, review, missing, assumptions


def run(pdf_path, ticker: str = "UPLOAD") -> Result:
    ex = read(pdf_path)
    p, review, missing, assumptions = build_inputs(ex, ticker)
    calc = engine.calculate(p)
    unreadable = ""
    loc = ex.fs_location or {}
    if "position" not in ex.statements or "profit_loss" not in ex.statements:
        scanned = ex.scanned_pages
        parts = [Msg("issue.fs_not_found", n=ex.n_pages)]
        if scanned:
            parts.append(Msg("issue.scanned", k=len(scanned), pages=Pages(tuple(scanned[:10]))))
        unreadable = join(parts, " ")
    elif getattr(ex, "financial_institution", None):
        # approved 28 Oct 2026: the Beneish model does not apply to banks, insurers and finance companies
        unreadable = Msg("issue.financial_institution", items=tuple(
            Msg("issue.cand_item", stmt=Raw(lab), p=pg) for _, pg, lab in ex.financial_institution))
    elif not (loc.get("chosen") or {}).get("notes_start"):
        unreadable = Msg("issue.notes_not_found")
    flags = validation.check(p, ex) if not unreadable else []
    passed = validation.passed_checks(p, ex) if not unreadable else []
    issuer, _ = company.identify(company.header_text(ex.statements))
    return Result(ex, p, calc, review, missing, assumptions, unreadable, flags, passed, issuer=issuer)


# ------------------------------------------------------------------------------ M-06 (approved 22 Oct 2026)

class DecisionError(ValueError):
    """A decision that the approved rule does not allow (the score stays held). args = (column, text.Msg)."""

    @property
    def message(self):
        return self.args[1] if len(self.args) > 1 else self.args[0]


def apply_non_ppe_decisions(r: Result, decisions: dict) -> Result:
    """Apply the non-PPE status the user set, year by year (Q6, M-06), and recalculate.

    decisions: {"t": {"status": "NONE_PRESENT", "notes": ["10. Aset tetap", ...]}, "t1": {...}}.
    A year without a decision stays NOT ASSESSED. Rules:
      - NONE_PRESENT: value 0, and the notes the user examined must be listed (never from a search alone);
      - ALL_DISCLOSED: only when an amount was read from the notes for that year (no manual entry, M-14);
      - PARTIAL_UNDISCLOSED: the amount read for that year, or 0 when none was read; REVIEW.
    Each year is decided separately; nothing is copied from one year to the other.
    """
    ev = r.extraction.non_ppe_evidence or {}
    read_amounts = ev.get("amounts_read", {})
    p = dict(r.inputs)
    values = copy.deepcopy(r.extraction.values)
    review = [x for x in r.review if x[0] not in ("depreciation_amortization_non_ppe", "non_ppe_status",
                                                     "depreciation_amortization_total")]
    missing = [x for x in r.missing if x[0] not in ("depreciation_amortization_non_ppe", "non_ppe_status",
                                                      "depreciation_amortization_total")]
    applied = {}
    for c in ("t", "t1"):
        d = decisions.get(c) or {}
        status = d.get("status")
        if status not in NON_PPE_STATUSES:
            continue
        notes = [n for n in (d.get("notes") or []) if str(n).strip()]
        if status == "NONE_PRESENT":
            if not notes:
                raise DecisionError(c, Msg("err.np_notes"))
            amount, note = 0, Msg("note.np_none", notes=Raw("; ".join(notes)))
        elif status == "ALL_DISCLOSED":
            if c not in read_amounts:
                raise DecisionError(c, Msg("err.np_amount"))
            amount, note = read_amounts[c], Msg("note.np_all", source=ev.get("amount_source", ""))
        else:
            amount = read_amounts.get(c, 0)
            note = (Msg("note.np_partial", source=ev.get("amount_source", ""))
                    if c in read_amounts else Msg("note.np_partial_zero"))
            if notes:
                note = join([note, Msg("note.examined", notes=Raw("; ".join(notes)))])
        p[f"non_ppe_status_{c}"] = status
        p[f"depreciation_amortization_non_ppe_{c}"] = amount
        applied[c] = {"status": status, "notes": notes, "amount": amount}
        vst = "REVIEW" if status == "PARTIAL_UNDISCLOSED" else "FOUND"
        for v in values:
            if v.column != c:
                continue
            if v.field == "non_ppe_status":
                v.value, v.status, v.note = status, "USER SET", note
            elif v.field == "depreciation_amortization_non_ppe":
                v.value, v.status, v.note = amount, "USER SET" if vst == "FOUND" else "REVIEW", note
        if vst == "REVIEW":
            review.append(("depreciation_amortization_non_ppe", c, "REVIEW", note))
        # D&A total, built from disclosed components only (DP-01/02); never from balances (Q2-c)
        ppe, am = p.get(f"ppe_depreciation_disclosed_{c}"), p.get(f"amortization_intangibles_{c}")
        tot = next((v for v in values if v.field == "depreciation_amortization_total" and v.column == c), None)
        if isinstance(ppe, (int, float)) and isinstance(am, (int, float)):
            total = ppe + am + amount
            p[f"depreciation_amortization_total_{c}"] = total
            if tot is not None:
                tot.value, tot.status = total, "BUILT FROM DISCLOSED COMPONENTS"
                tot.components = Msg("comp.dat", a=Amt(ppe), b=Amt(am), c=Amt(amount))
                tot.note = Msg("note.dat_built")
            review.append(("depreciation_amortization_total", c, "BUILT FROM DISCLOSED COMPONENTS", tot.note if tot else ""))
        else:
            missing.append(("depreciation_amortization_total", c, "NOT FOUND", Msg("note.component_missing")))
    for c in ("t", "t1"):
        if c not in applied:
            missing.append(("non_ppe_status", c, "NOT ASSESSED", Msg("note.np_pending")))
    calc = engine.calculate(p)
    flags = validation.check(p, None) + [f for f in r.flags if f.code.startswith(validation.EXTRACTION_ONLY)]
    ex = replace(r.extraction, values=values)
    return replace(r, extraction=ex, inputs=p, calc=calc, review=review, missing=missing, flags=flags,
                   decisions=applied)


# ------------------------------------------------------------------------------ M-15 (approved 23 Oct 2026)

AMORT_CHOICES = {          # wording: text catalogue "am.opt.<choice>" (UI r1 9.12)
    "NONE_PRESENT": "am.opt.NONE_PRESENT",
    "GOODWILL_ONLY": "am.opt.GOODWILL_ONLY",            # PSAK 238 ¶3(f)
    "INDEFINITE_ONLY": "am.opt.INDEFINITE_ONLY",        # PSAK 238 ¶107
    "UNDISCLOSED": "am.opt.UNDISCLOSED",                # G-22
}


def apply_amort_decisions(r: Result, decisions: dict) -> Result:
    """Apply the amortisation status the user set, year by year (M-15), and recalculate.

    Only for a year whose amortisation is NOT ASSESSED (the reader found no intangible assets).
    decisions: {"t": {"status": "GOODWILL_ONLY", "notes": ["12. Goodwill, p 58"]}, "t1": {...}}.
      - NONE_PRESENT / GOODWILL_ONLY / INDEFINITE_ONLY: amortisation 0; amort_status blank;
      - UNDISCLOSED: technical 0 under G-22 (component excluded, not a statement that the charge is
        nil); amort_status UNDISCLOSED -> r_amort_undisclosed REVIEW.
    Every choice requires the notes/pages examined. A year without a valid decision stays NOT
    ASSESSED and the score stays held. Each year is decided separately. If the user found an amount
    the reader missed, nothing here can enter it (no manual correction, M-14): the year stays held.
    """
    pending = set(r.amort_pending)
    p = dict(r.inputs)
    values = copy.deepcopy(r.extraction.values)
    missing = list(r.missing)
    review = list(r.review)
    applied = {}
    for c in ("t", "t1"):
        d = decisions.get(c) or {}
        status = d.get("status")
        if status not in AMORT_CHOICES:
            continue
        if c not in pending:
            raise DecisionError(c, Msg("err.am_read"))
        notes = [n for n in (d.get("notes") or []) if str(n).strip()]
        if not notes:
            raise DecisionError(c, Msg("err.am_notes"))
        note = Msg("note.am_set", choice=Msg(AMORT_CHOICES[status]), notes=Raw("; ".join(notes)))
        p[f"amortization_intangibles_{c}"] = 0
        if status == "UNDISCLOSED":
            p[f"amort_status_{c}"] = "UNDISCLOSED"
            note = join([note, Msg("note.am_g22")], ". ")
        for v in values:
            if v.column != c:
                continue
            if v.field == "amortization_intangibles":
                v.value, v.note = 0, note
                v.status = "UNDISCLOSED" if status == "UNDISCLOSED" else "USER SET"
            elif v.field == "amort_status":
                v.value = "UNDISCLOSED" if status == "UNDISCLOSED" else None
                v.status, v.note = ("REVIEW" if status == "UNDISCLOSED" else "USER SET"), note
        missing = [x for x in missing if not (x[0] in ("amortization_intangibles", "amort_status") and x[1] == c)]
        review = [x for x in review if not (x[0] in ("amortization_intangibles", "amort_status") and x[1] == c)]
        if status == "UNDISCLOSED":
            review.append(("amortization_intangibles", c, "UNDISCLOSED", note))
        applied[c] = {"status": status, "notes": notes}
    calc = engine.calculate(p)
    flags = validation.check(p, None) + [f for f in r.flags if f.code.startswith(validation.EXTRACTION_ONLY)]
    ex = replace(r.extraction, values=values)
    return replace(r, extraction=ex, inputs=p, calc=calc, review=review, missing=missing, flags=flags,
                   amort_decisions=applied)


def apply_provisional(r: Result) -> Result:
    """Gail, 28 Oct 2026 ("untuk saat ini", replaces the in-app M-06 / M-15 choices): the score is shown
    at once as a provisional result. For every year still NOT ASSESSED:
      - amortisation (no intangible assets read, M-15): 0, marked ASSUMED;
      - depreciation/amortisation of other assets (M-06): the amount read from the notes, or 0 when
        none was read, under the workbook rule PARTIAL_UNDISCLOSED (REVIEW, G-22); marked ASSUMED.
    Every assumption is kept in `r.assumptions` and listed in the PDF checklist, where the user
    confirms or rejects it. The engine rules are unchanged: only workbook statuses are entered.
    """
    if r.unreadable:
        return r
    am_years, np_years = list(r.amort_pending), list(r.non_ppe_pending)
    p = dict(r.inputs)
    values = copy.deepcopy(r.extraction.values)
    review = [x for x in r.review if not (x[0] in ("amortization_intangibles", "amort_status") and x[1] in am_years)]
    missing = [x for x in r.missing if not (x[0] in ("amortization_intangibles", "amort_status") and x[1] in am_years)]
    assumed = []
    for c in am_years:
        note = Msg("note.assumed_am")
        p[f"amortization_intangibles_{c}"] = 0
        for v in values:
            if v.column == c and v.field in ("amortization_intangibles", "amort_status"):
                v.value = 0 if v.field == "amortization_intangibles" else None
                v.status, v.note = "ASSUMED", note
        review.append(("amortization_intangibles", c, "ASSUMED", note))
        assumed.append(("amortization_intangibles", c, note))
    ex = replace(r.extraction, values=values)
    r = replace(r, extraction=ex, inputs=p, review=review, missing=missing)
    if np_years:
        r = apply_non_ppe_decisions(r, {c: {"status": "PARTIAL_UNDISCLOSED", "notes": []} for c in np_years})
        read_amounts = (r.extraction.non_ppe_evidence or {}).get("amounts_read", {})
        for c in np_years:
            note = Msg("note.assumed_np", source=(r.extraction.non_ppe_evidence or {}).get("amount_source", "")) \
                if c in read_amounts else Msg("note.assumed_np_zero")
            for v in r.extraction.values:
                if v.column == c and v.field in ("depreciation_amortization_non_ppe", "non_ppe_status"):
                    v.status, v.note = "ASSUMED", note
            r.review[:] = [x for x in r.review if not (x[0] == "depreciation_amortization_non_ppe" and x[1] == c)]
            r.review.append(("depreciation_amortization_non_ppe", c, "ASSUMED", note))
            assumed.append(("depreciation_amortization_non_ppe", c, note))
        r.decisions = {}
    else:
        r = replace(r, calc=engine.calculate(p),
                    flags=validation.check(p, None) + [f for f in r.flags if f.code.startswith(validation.EXTRACTION_ONLY)])
    return replace(r, assumed=assumed)


def apply_user_decisions(r: Result, non_ppe: dict, amort: dict) -> Result:
    """Amortisation first (M-15), then the non-PPE status (M-06), which builds the D&A total from
    the disclosed components (DP-01/02). Both are per year; either may be absent."""
    if amort:
        r = apply_amort_decisions(r, amort)
    return apply_non_ppe_decisions(r, non_ppe or {})
