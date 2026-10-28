"""Phase 3: cross-checks on the engine input (green / yellow / red).

Two kinds of checks, kept apart on purpose:

* WORKBOOK checks, ported from WARS_TrackB_v0_6.xlsx (`Pair_Validation`, `Validation_Checks`,
  parameter `yoy_change_threshold`). Same rule, same severity.
* APP checks, added for automatic reading (the workbook assumed a person typed the numbers):
  they look for the errors a PDF reader makes - wrong unit, swapped columns, a digit slip.
  They never change a number; they only raise REVIEW or ERROR. Approved as M-12 A (Gail, 23 Oct
  2026): an ERROR is about the figures as read, never a statement about the issuer, and every
  app-check message says so ("Angka yang dibaca: ...").

Severity, as in the workbook: ERROR = structurally wrong (the M-score is not usable,
`m_score_usable` = N); REVIEW = may be legitimate, needs a person; WARNING = incomplete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .pdf_reader import _norm, parse_amount
from .text import Amt, Money, Msg, Pages, Pct, Psak, Raw, join, unit_msg

YOY_CHANGE_THRESHOLD = 1.0      # workbook Parameters: yoy_change_threshold (1.0 = 100%)
YOY_FIELDS = ["revenue", "accounts_receivable", "cost_of_goods_sold", "selling_general_administrative_expenses",
              "total_assets", "property_plant_equipment_net"]          # workbook Validation_Checks AB..AG
JUMP_RATIO = 5.0                # app check: one year 5x the other (either direction) = possible digit/unit slip
SCALE = {"Units": 1, "Thousands": 1_000, "Millions": 1_000_000, "Billions": 1_000_000_000}
TA_MIN_RP, TA_MAX_RP = 10 ** 9, 3 * 10 ** 15     # Rp1 miliar .. Rp3.000 triliun (largest IDX issuer, a bank, is below Rp2.500 triliun)
TA_MIN_USD, TA_MAX_USD = 5 * 10 ** 4, 2 * 10 ** 11   # the same range in US dollars at about Rp15.000/USD (P4; chosen by Claude)


@dataclass
class Flag:
    code: str
    severity: str        # ERROR / REVIEW / WARNING
    source: str          # "workbook" or "app"
    message: str         # text.Msg (reads in Indonesian as a str; render(lang) for EN)
    fields: tuple = ()
    column: str = ""


def _g(p, f, c):
    v = p.get(f"{f}_{c}")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _cash_flow_closing_cash(ex):
    """'Kas dan setara kas akhir tahun' from the cash-flow statement, {t, t1}."""
    cf = ex.statements.get("cash_flow") if ex.statements else None
    if not cf:
        return None, None
    for ln in cf.lines:
        lab = _norm(ln.full_label or ln.label)
        if re.search(r"(kas dan setara kas|kas dan bank).*akhir (tahun|periode)|akhir (tahun|periode)$", lab) \
                and "t" in ln.amounts and "t1" in ln.amounts and "awal" not in _norm(ln.label):
            # A note reference between the figures ("AKHIR TAHUN 1.031.954 4 864.824") is dropped:
            # a bare one- or two-digit number next to dotted figures is not a closing balance.
            words = [w.text.strip() for w in ln.words]
            nums = [parse_amount(w) for w in words]
            vals = [v for w, v in zip(words, nums) if v is not None]
            dotted = [v for w, v in zip(words, nums) if v is not None and not re.fullmatch(r"\d{1,2}", w)]
            if len(vals) > 2 and len(dotted) >= 2 and not {ln.amounts["t"], ln.amounts["t1"]} <= set(dotted):
                t_first = ln.amounts["t"] == vals[0]
                a, b = dotted[0], dotted[1]
                return ({"t": a, "t1": b} if t_first else {"t": b, "t1": a}), ln
            return ln.amounts, ln
    return None, None


def check(p: dict, ex=None) -> list:
    flags = []
    cols = ("t", "t1")

    # ---------------------------------------------------------------- app: rule 7 cross-check, fixed assets (ERROR)
    ppe_x = (getattr(ex, "cross_checks", None) or {}).get("ppe_note", {}) if ex is not None else {}
    for c in cols:
        st = ppe_x.get(c)
        if st and st[0] == "mismatch":
            flags.append(Flag("a_ppe_note", "ERROR", "app",
                              Msg("flag.ppe_note", seen=join([Amt(x) for x in st[1]], ", ")),
                              ("property_plant_equipment_net",), c))

    # ---------------------------------------------------------------- workbook: e_impossible_values (ERROR)
    for c in cols:
        cl, tl = _g(p, "current_liabilities", c), _g(p, "total_liabilities", c)
        if cl is not None and tl is not None and cl > tl:
            flags.append(Flag("e_impossible_values", "ERROR", "workbook", Msg("flag.cl_gt_tl"),
                              ("current_liabilities", "total_liabilities"), c))
        am, da = _g(p, "amortization_intangibles", c), _g(p, "depreciation_amortization_total", c)
        if am is not None and da is not None and am > da:
            flags.append(Flag("e_impossible_values", "ERROR", "workbook", Msg("flag.amort_gt_da"),
                              ("amortization_intangibles", "depreciation_amortization_total"), c))
        nonppe = _g(p, "depreciation_amortization_non_ppe", c)
        if nonppe is not None and nonppe < 0:
            flags.append(Flag("e_impossible_values", "ERROR", "workbook", Msg("flag.nonppe_neg"),
                              ("depreciation_amortization_non_ppe",), c))
        if None not in (nonppe, da, am) and nonppe > da - am:
            flags.append(Flag("e_impossible_values", "ERROR", "workbook",
                              Msg("flag.nonppe_gt"),
                              ("depreciation_amortization_non_ppe",), c))
        ca, ppe, ta = _g(p, "current_assets", c), _g(p, "property_plant_equipment_net", c), _g(p, "total_assets", c)
        if None not in (ca, ppe, ta) and ca + ppe > ta:
            flags.append(Flag("e_impossible_values", "ERROR", "workbook", Msg("flag.ca_ppe_gt_ta"),
                              ("current_assets", "property_plant_equipment_net", "total_assets"), c))

    # ---------------------------------------------------------------- workbook: r_negative_values (REVIEW)
    neg_fields = ["revenue", "accounts_receivable", "cost_of_goods_sold", "selling_general_administrative_expenses",
                  "total_assets", "current_assets", "property_plant_equipment_net", "depreciation_amortization_total",
                  "amortization_intangibles", "current_liabilities", "long_term_debt",
                  "current_maturities_long_term_debt", "cash_and_cash_equivalents", "taxes_payable", "total_liabilities"]
    for c in cols:
        neg = [f for f in neg_fields if (_g(p, f, c) or 0) < 0]
        rev, cogs = _g(p, "revenue", c), _g(p, "cost_of_goods_sold", c)
        if neg or (rev is not None and cogs is not None and rev - cogs < 0):
            flags.append(Flag("r_negative_values", "REVIEW", "workbook",
                              Msg("flag.negative", items=tuple(Msg(f"label.{f}") for f in neg)) if neg
                              else Msg("flag.negative_gp"),
                              tuple(neg), c))

    # ---------------------------------------------------------------- workbook: r_unusual_yoy_change (REVIEW)
    for f in YOY_FIELDS:
        a, b = _g(p, f, "t"), _g(p, f, "t1")
        if a is not None and b not in (None, 0) and abs(a / b - 1) > YOY_CHANGE_THRESHOLD:
            flags.append(Flag("r_unusual_yoy_change", "REVIEW", "workbook",
                              Msg("flag.yoy", x=Pct(a / b - 1, 0, True), thr=Pct(YOY_CHANGE_THRESHOLD, 0)),
                              (f,), "both"))

    # ---------------------------------------------------------------- workbook: G-22 / G-23 reviews
    for c in cols:
        if p.get(f"non_ppe_status_{c}") == "PARTIAL_UNDISCLOSED":
            flags.append(Flag("r_non_ppe_partial", "REVIEW", "workbook",
                              Msg("flag.nonppe_partial"),
                              ("depreciation_amortization_non_ppe",), c))
    if any(str(p.get(f"amort_status_{c}", "")).strip() == "UNDISCLOSED" for c in cols):
        flags.append(Flag("r_amort_undisclosed", "REVIEW", "workbook",
                          Msg("flag.amort_undisclosed"),
                          ("amortization_intangibles",), "both"))
    for c in cols:
        rou, rdep = _g(p, "rou_assets_net", c), _g(p, "rou_depreciation", c)
        if rou is not None and rou > 0 and (rdep is None or rdep == 0):
            flags.append(Flag("r_rou_dep_missing", "REVIEW", "workbook",
                              Msg("flag.rou_dep_missing"), ("rou_depreciation",), c))

    # ---------------------------------------------------------------- workbook: transition / comparatives (REVIEW)
    # M-08 package (approved 23 Oct 2026): Pair_Validation r_standard_transition, r_standard_transition_other,
    # r_comparative_label, same conditions as the workbook. Inputs come from transition.detect().
    ev_list = ((getattr(ex, "transition", None) or {}).get("evidence") if ex is not None else None) \
        or p.get("_transition_evidence") or []
    ev = {e["standard"]: e for e in ev_list}

    fy = p.get("fiscal_year_t")

    def _pg(std):
        return Msg("flag.page", p=ev[std]["page"]) if std in ev and ev[std].get("page") else ""

    def _std(s_):                 # "PSAK 73" as printed in the report year (R-05: old number, new in brackets)
        new = {"PSAK 71": "109", "PSAK 72": "115", "PSAK 73": "116"}.get(s_)
        return Psak(new, s_.split()[-1], fy) if new else Raw(s_)
    if p.get("psak73_applied_t") == "Y" and p.get("psak73_applied_t1") == "N":
        flags.append(Flag("r_standard_transition", "REVIEW", "workbook",
                          Msg("flag.transition73", std=_std("PSAK 73"), pg=_pg("PSAK 73")),
                          ("property_plant_equipment_net", "depreciation_amortization_total"), "both"))
    other = str(p.get("standards_first_applied_t") or "").strip()
    if other:
        listed = tuple(Msg("flag.std_page", std=_std(s_.strip()), p=ev[s_.strip()]["page"])
                       if s_.strip() in ev and ev[s_.strip()].get("page") else _std(s_.strip())
                       for s_ in other.split(";") if s_.strip())
        flags.append(Flag("r_standard_transition_other", "REVIEW", "workbook",
                          Msg("flag.transition_other", listed=listed),
                          ("accounts_receivable", "revenue"), "both"))
    if p.get("comparative_label_t1") in ("RESTATED", "RECLASSIFIED", "RESTATED_AND_RECLASSIFIED"):
        flags.append(Flag("r_comparative_label", "REVIEW", "workbook",
                          Msg("flag.comparative", word=Msg(f"label.{p['comparative_label_t1']}"),
                              pg=_pg("comparative label"), psak208=Psak("208", "25", fy, "¶49")), (), "t1"))

    # ---------------------------------------------------------------- app: unit plausibility (ERROR)
    unit = p.get("unit_scale")
    ta = _g(p, "total_assets", "t")
    if unit in SCALE and ta:
        ccy = p.get("reporting_currency")
        lo, hi = (TA_MIN_USD, TA_MAX_USD) if ccy == "USD" else (TA_MIN_RP, TA_MAX_RP)
        rp = ta * SCALE[unit]
        if not lo <= rp <= hi:
            flags.append(Flag("a_unit_implausible", "ERROR", "app",
                              Msg("flag.unit", unit=unit_msg(unit, ccy), x=Money(rp, None, currency=ccy)),
                              ("total_assets",), "t"))

    # ---------------------------------------------------------------- app: parts within totals (ERROR)
    for c in cols:
        ca, ta = _g(p, "current_assets", c), _g(p, "total_assets", c)
        cl, tl = _g(p, "current_liabilities", c), _g(p, "total_liabilities", c)
        for part, whole, total_name in (("accounts_receivable", ca, "current_assets"),
                                        ("cash_and_cash_equivalents", ca, "current_assets"),
                                        ("taxes_payable", cl, "current_liabilities"),
                                        ("current_maturities_long_term_debt", cl, "current_liabilities")):
            v = _g(p, part, c)
            if v is not None and whole is not None and v > whole:
                flags.append(Flag("a_part_exceeds_total", "ERROR", "app",
                                  Msg("flag.part_gt_total", part=Msg(f"label.{part}"), total=Msg(f"label.{total_name}")),
                                  (part,), c))
        ltd = _g(p, "long_term_debt", c)
        if None not in (ltd, tl, cl) and ltd > tl - cl:
            flags.append(Flag("a_part_exceeds_total", "ERROR", "app",
                              Msg("flag.part_gt_total", part=Msg("label.long_term_debt"),
                                  total=Msg("label.noncurrent_liabilities")), ("long_term_debt",), c))
        sga, rev = _g(p, "selling_general_administrative_expenses", c), _g(p, "revenue", c)
        if sga is not None and rev is not None and sga > rev:
            flags.append(Flag("a_part_exceeds_total", "REVIEW", "app", Msg("flag.sga_gt_rev"),
                              ("selling_general_administrative_expenses",), c))

    # ---------------------------------------------------------------- app: digit / unit slip between years (REVIEW)
    jump_fields = sorted({k.rsplit("_", 1)[0] for k in p if k.endswith(("_t", "_t1"))})
    for f in jump_fields:
        a, b = _g(p, f, "t"), _g(p, f, "t1")
        if a and b and max(abs(a), abs(b)) / min(abs(a), abs(b)) >= JUMP_RATIO:
            flags.append(Flag("a_year_jump", "REVIEW", "app",
                              Msg("flag.jump", r=f"{JUMP_RATIO:.0f}"),
                              (f,), "both"))

    # ---------------------------------------------------------------- app: year labels of the statements (ERROR)
    # P0-2 (approved by Gail, 28 Oct 2026): the year columns come from the year labels printed in each
    # statement's heading. If a statement has no readable year labels, or the statements disagree on
    # the year, the columns cannot be assigned with certainty: the score is withheld. The year is never
    # taken from the column position alone.
    if ex is not None and getattr(ex, "year_labels", None):
        yl = {k: v for k, v in ex.year_labels.items() if k in (ex.statements or {}) or not ex.statements}
        missing = [k for k, v in yl.items() if v.get("year") is None]
        if missing:
            flags.append(Flag("a_year_labels_missing", "ERROR", "app",
                              Msg("flag.year_missing", stmts=tuple(Msg(f"stmt.{k}") for k in missing)), (), "both"))
        years = {v["year"] for v in yl.values() if v.get("year") is not None}
        if len(years) > 1:
            flags.append(Flag("a_year_labels_mismatch", "ERROR", "app",
                              Msg("flag.year_mismatch", list=tuple(
                                  Msg("flag.year_item", stmt=Msg(f"stmt.{k}"), y=v["year"], p=v["page"])
                                  for k, v in yl.items() if v.get("year") is not None)), (), "both"))

    # ---------------------------------------------------------------- app: cash-flow closing cash = balance-sheet cash
    if ex is not None:
        closing, ln = _cash_flow_closing_cash(ex)
        if closing:
            for c in cols:
                bs = _g(p, "cash_and_cash_equivalents", c)
                if bs is None:
                    continue
                if closing[c] != bs:
                    other = "t1" if c == "t" else "t"
                    swapped = closing.get(other) == bs
                    flags.append(Flag("a_cash_tie", "ERROR" if swapped else "REVIEW", "app",
                                      Msg("flag.cash_swapped") if swapped else Msg("flag.cash_diff"),
                                      ("cash_and_cash_equivalents",), c))
        else:
            flags.append(Flag("a_cash_tie_unavailable", "WARNING", "app",
                              Msg("flag.cash_unavailable")))
    return flags


EXTRACTION_ONLY = ("a_cash", "a_year_labels", "a_ppe_note")   # checks that need the extraction; kept when the inputs are recalculated


def passed_checks(p: dict, ex=None) -> list:
    """Names of the app checks that ran and passed (for the report)."""
    out = []
    if ex is not None:
        closing, _ = _cash_flow_closing_cash(ex)
        if closing and all(closing[c] == _g(p, "cash_and_cash_equivalents", c) for c in ("t", "t1")):
            out.append(Msg("check.cash"))
        ppe_x = (getattr(ex, "cross_checks", None) or {}).get("ppe_note", {})
        if ppe_x and all(v[0] == "ok" for v in ppe_x.values()):
            out.append(Msg("check.ppe_note", p=Pages(tuple(sorted({v[1] for v in ppe_x.values()})))))
        yl = getattr(ex, "year_labels", None) or {}
        if yl and all(v.get("year") is not None for v in yl.values()) and len({v["year"] for v in yl.values()}) == 1:
            out.append(Msg("check.year_labels", list=tuple(
                Msg("flag.year_item", stmt=Msg(f"stmt.{k}"), y=v["year"], p=v["page"]) for k, v in yl.items())))
    return out
