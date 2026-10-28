"""Track B calculation engine: Beneish M-score of year t from ONE annual report.

This module is a line-by-line port of two sheets of WARS_TrackB_v0_6.xlsx:
  - the derived (grey) columns of Pair_Inputs, and
  - Beneish_Pair_Calculation.
The workbook is the specification. The tests compare this module with values that
LibreOffice calculated in the workbook for synthetic pairs.

Spreadsheet semantics are reproduced on purpose, because they decide edge cases:
  - a blank input cell is "blank": it counts as 0 in arithmetic and comparisons, but
    ISNUMBER / COUNT do not count it;
  - a formula that returns "" produces an empty TEXT value; arithmetic on it is an
    error (#VALUE!);
  - an error propagates through arithmetic and comparisons, and ISNUMBER(error) is
    FALSE.

Not ported here (see docs/engine_spec.md): Pair_Validation and m_score_usable (Phase 3),
duplicate detection across many rows (an app run has one row; a caller may pass a
count), the sensitivity sheets, and Track A.
"""
from __future__ import annotations

from dataclasses import dataclass

from .parameters import ABOVE, BELOW, COEFFICIENTS, NON_PPE_STATUSES, THRESHOLDS

# The 14 inputs that must be numbers in each year column (Pair_Inputs AN:BA and BH:BU).
REQUIRED_14 = [
    "revenue", "accounts_receivable", "cost_of_goods_sold", "selling_general_administrative_expenses",
    "total_assets", "current_assets", "property_plant_equipment_net", "depreciation_amortization_total",
    "amortization_intangibles", "current_liabilities", "long_term_debt", "current_maturities_long_term_debt",
    "cash_and_cash_equivalents", "taxes_payable",
]

INDICES = ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA"]


@dataclass(frozen=True)
class Err:
    """A spreadsheet error value (for example #VALUE! or #DIV/0!)."""
    code: str = "#VALUE!"


BLANK = None  # an empty input cell


def isnumber(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v):
    """Value of v inside arithmetic: blank -> 0; text -> error; error -> error."""
    if v is BLANK:
        return 0
    if isnumber(v):
        return v
    if isinstance(v, Err):
        return v
    return Err("#VALUE!")


def add(*vals):
    xs = [_num(v) for v in vals]
    for x in xs:
        if isinstance(x, Err):
            return x
    return sum(xs)


def sub(a, b):
    x, y = _num(a), _num(b)
    if isinstance(x, Err):
        return x
    if isinstance(y, Err):
        return y
    return x - y


def mul(a, b):
    x, y = _num(a), _num(b)
    if isinstance(x, Err):
        return x
    if isinstance(y, Err):
        return y
    return x * y


def div(a, b):
    x, y = _num(a), _num(b)
    if isinstance(x, Err):
        return x
    if isinstance(y, Err):
        return y
    if y == 0:
        return Err("#DIV/0!")
    return x / y


def le0(v):
    """v <= 0 as a spreadsheet evaluates it. Returns True/False or an Err."""
    if isinstance(v, Err):
        return v
    if v is BLANK:
        return True
    if isnumber(v):
        return v <= 0
    return False  # text compares greater than any number


def trim_text(v) -> str:
    return "" if v is BLANK else str(v).strip()


def count_numbers(*vals) -> int:
    return sum(1 for v in vals if isnumber(v))


# ---------------------------------------------------------------------------------------
# Pair_Inputs derived columns
# ---------------------------------------------------------------------------------------

def derive_pair_columns(p: dict) -> dict:
    """Grey columns of Pair_Inputs for one row. `p` maps column names to cell values."""
    g = p.get
    d = {}
    ticker = trim_text(g("ticker"))
    d["obs_key"] = (f"{ticker.upper()}|{_fmt(g('fiscal_year_t'))}|v{_fmt(g('doc_version'))}"
                    if ticker and isnumber(g("fiscal_year_t")) and isnumber(g("doc_version")) else "")
    d["row_active"] = "Y" if any(v not in (BLANK, "") for k, v in p.items() if k in _COUNTA_COLUMNS) else "N"
    d["is_primary"] = "Y" if g("doc_version") == 1 else "N"
    d["basis_specified"] = ("Y" if all(trim_text(g(k)) for k in ("statement_type", "reporting_currency", "unit_scale"))
                            else "N")
    for s in ("t", "t1"):
        rev, cogs = g(f"revenue_{s}"), g(f"cost_of_goods_sold_{s}")
        d[f"gross_profit_{s}"] = rev - cogs if count_numbers(rev, cogs) == 2 else ""

        da, am, nonppe = g(f"depreciation_amortization_total_{s}"), g(f"amortization_intangibles_{s}"), \
            g(f"depreciation_amortization_non_ppe_{s}")
        disclosed = g(f"ppe_depreciation_disclosed_{s}")
        if not isnumber(disclosed):
            check = "NOT PROVIDED"
        elif count_numbers(da, am, nonppe) < 3:
            check = "NOT CHECKABLE"
        else:
            check = "OK" if abs((da - am - nonppe) - disclosed) <= 1 else "MISMATCH"
        d[f"ppe_dep_check_{s}"] = check

        status = g(f"non_ppe_status_{s}")
        d[f"depreciation_expense_{s}"] = (da - am - nonppe
                                         if status in NON_PPE_STATUSES and check != "MISMATCH"
                                         and count_numbers(da, am, nonppe) == 3 else "")

        complete14 = count_numbers(*(g(f"{f}_{s}") for f in REQUIRED_14)) == 14
        rou, rou_dep = g(f"rou_assets_net_{s}"), g(f"rou_depreciation_{s}")
        g23 = isnumber(rou) and rou > 0 and (not isnumber(rou_dep) or rou_dep == 0)
        undisclosed = trim_text(g(f"amort_status_{s}")) == "UNDISCLOSED"  # case-sensitive, as EXACT()
        ok = complete14 and (isnumber(disclosed) or (not undisclosed and not g23))
        d[f"required_inputs_complete_{s}"] = "Y" if ok else "N"
    return d


def _fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# Pair_Inputs columns B..CL (ticker .. debt_nil_basis_t1) counted by row_active's COUNTA.
_COUNTA_COLUMNS = None  # set below from the column list


def _set_counta_columns(columns):
    global _COUNTA_COLUMNS
    i, j = columns.index("ticker"), columns.index("debt_nil_basis_t1")
    _COUNTA_COLUMNS = set(columns[i:j + 1])


PAIR_INPUT_COLUMNS = [
    "pair_id", "ticker", "fiscal_year_t", "reporting_period_end_t", "doc_version", "doc_type", "substitute_reason",
    "search_log_ref", "source_id", "document_name", "document_ref", "file_hash", "submission_date",
    "public_availability_date", "date_source", "date_status", "auditor_name", "auditor_report_date",
    "statement_type", "reporting_currency", "unit_scale", "psak73_applied_t", "psak73_applied_t1",
    "crossfoot_bs_t", "crossfoot_is_t", "crossfoot_cf_t", "crossfoot_bs_t1doc", "crossfoot_is_t1doc",
    "crossfoot_cf_t1doc", "mixed_source_fields", "data_status", "notes", "pages_pdf_t", "pages_printed_t",
    "field_notes_t", "pages_pdf_t1", "pages_printed_t1", "comparative_label_t1", "field_notes_t1",
    *[f"{f}_t" for f in REQUIRED_14], "total_liabilities_t", "net_income_t", "cash_flow_from_operations_t",
    "income_before_extraordinary_items_t", "depreciation_amortization_non_ppe_t", "non_ppe_status_t",
    *[f"{f}_t1" for f in REQUIRED_14], "total_liabilities_t1", "net_income_t1", "cash_flow_from_operations_t1",
    "income_before_extraordinary_items_t1", "depreciation_amortization_non_ppe_t1", "non_ppe_status_t1",
    "ppe_depreciation_disclosed_t", "ppe_depreciation_disclosed_t1", "rou_assets_net_t", "rou_assets_net_t1",
    "rou_depreciation_t", "rou_depreciation_t1", "ar_related_t", "ar_related_t1", "ar_third_t", "ar_third_t1",
    "standards_first_applied_t", "amort_status_t", "amort_status_t1", "debt_nil_basis_t", "debt_nil_basis_t1",
]
_set_counta_columns(PAIR_INPUT_COLUMNS)


# ---------------------------------------------------------------------------------------
# Beneish_Pair_Calculation
# ---------------------------------------------------------------------------------------

def not_ready_reason(p: dict, d: dict, duplicate_count: int = 1) -> str:
    """Column I of Beneish_Pair_Calculation, for a row that has no other rows around it.

    `duplicate_count` is the number of rows with the same obs_key (1 in a single app run).
    The prior-year checks of the workbook compare the row with itself on Track B, so they
    cannot fail once the ticker and fiscal year are valid.
    """
    g = p.get
    if d["row_active"] != "Y":
        return "inactive row"
    if d["is_primary"] != "Y":
        return "not the first-issued document version (doc_version<>1): sensitivity only"
    if trim_text(g("mixed_source_fields")):
        return "MIXED_SOURCE value present in a primary pair (not allowed, D13-2)"
    if g("ticker") in (BLANK, "") or not isnumber(g("fiscal_year_t")):
        return "missing or invalid ticker / fiscal_year"
    if d["obs_key"] and duplicate_count > 1:
        return "duplicate ticker + fiscal_year"
    if d["basis_specified"] != "Y":
        return "statement_type / currency / unit_scale not specified (t or t-1)"
    if d["required_inputs_complete_t"] != "Y":
        return "missing or non-numeric required input (fiscal year t)"
    if d["required_inputs_complete_t1"] != "Y":
        return "missing or non-numeric required input (fiscal year t-1)"
    if g("non_ppe_status_t") not in NON_PPE_STATUSES:
        return "non-PPE D&A not assessed (fiscal year t)"
    if g("non_ppe_status_t1") not in NON_PPE_STATUSES:
        return "non-PPE D&A not assessed (fiscal year t-1)"
    if d["ppe_dep_check_t"] == "MISMATCH":
        return "PPE depreciation check failed (fiscal year t)"
    if d["ppe_dep_check_t1"] == "MISMATCH":
        return "PPE depreciation check failed (fiscal year t-1)"
    return ""


def _ratio_if_pos(den, num_expr):
    """IF(den<=0,"",num_expr()) with error propagation."""
    c = le0(den)
    if isinstance(c, Err):
        return c
    return "" if c else num_expr()


def _index_ratio(a, b):
    """=IF(OR(NOT(ISNUMBER(a)),NOT(ISNUMBER(b))),"",IF(b=0,"",a/b))"""
    if not isnumber(a) or not isnumber(b):
        return ""
    return "" if b == 0 else a / b


def calculate(p: dict, duplicate_count: int = 1) -> dict:
    """Evaluate one Track B pair. Returns the workbook columns by name.

    `p` maps Pair_Inputs input column names to values (blank = missing key or None).
    """
    d = derive_pair_columns(p)
    v = lambda k: d[k] if k in d else p.get(k)  # noqa: E731  (INDEX(tblPair[k]) on this row)
    out = dict(d)
    out["ticker"] = trim_text(p.get("ticker"))
    out["fiscal_year"] = p.get("fiscal_year_t") if p.get("fiscal_year_t") is not None else ""
    out["row_active"] = d["row_active"]
    reason = not_ready_reason(p, d, duplicate_count)
    out["not_ready_reason"] = reason if d["row_active"] == "Y" else "inactive row"

    keys = ["dsr_t", "dsr_t1", "gm_t", "gm_t1", "aq_t", "aq_t1", "depr_rate_t", "depr_rate_t1",
            "sga_ratio_t", "sga_ratio_t1", "lev_ratio_t", "lev_ratio_t1", "delta_current_assets", "delta_cash",
            "delta_current_liabilities", "delta_current_maturities_ltd", "delta_taxes_payable", "da_total_t",
            "tata_numerator", "SGI", "TATA", "m_score_B", "tata_alt_ni_cfo", "tata_alt_ibei_cfo"]
    if reason:
        out.update({k: "" for k in keys})
    else:
        for s in ("t", "t1"):
            out[f"dsr_{s}"] = _ratio_if_pos(v(f"revenue_{s}"), lambda s=s: div(v(f"accounts_receivable_{s}"), v(f"revenue_{s}")))
            out[f"gm_{s}"] = _ratio_if_pos(v(f"revenue_{s}"), lambda s=s: div(v(f"gross_profit_{s}"), v(f"revenue_{s}")))
            out[f"aq_{s}"] = _ratio_if_pos(
                v(f"total_assets_{s}"),
                lambda s=s: sub(1, div(add(v(f"current_assets_{s}"), v(f"property_plant_equipment_net_{s}")),
                                       v(f"total_assets_{s}"))))
            dep, ppe = v(f"depreciation_expense_{s}"), v(f"property_plant_equipment_net_{s}")
            out[f"depr_rate_{s}"] = _ratio_if_pos(add(dep, ppe), lambda dep=dep, ppe=ppe: div(dep, add(dep, ppe)))
            out[f"sga_ratio_{s}"] = _ratio_if_pos(
                v(f"revenue_{s}"), lambda s=s: div(v(f"selling_general_administrative_expenses_{s}"), v(f"revenue_{s}")))
            out[f"lev_ratio_{s}"] = _ratio_if_pos(
                v(f"total_assets_{s}"),
                lambda s=s: div(add(v(f"long_term_debt_{s}"), v(f"current_liabilities_{s}")), v(f"total_assets_{s}")))
        out["delta_current_assets"] = sub(v("current_assets_t"), v("current_assets_t1"))
        out["delta_cash"] = sub(v("cash_and_cash_equivalents_t"), v("cash_and_cash_equivalents_t1"))
        out["delta_current_liabilities"] = sub(v("current_liabilities_t"), v("current_liabilities_t1"))
        out["delta_current_maturities_ltd"] = sub(v("current_maturities_long_term_debt_t"),
                                                  v("current_maturities_long_term_debt_t1"))
        out["delta_taxes_payable"] = sub(v("taxes_payable_t"), v("taxes_payable_t1"))
        out["da_total_t"] = _num(v("depreciation_amortization_total_t"))
        out["tata_numerator"] = sub(
            sub(sub(out["delta_current_assets"], out["delta_cash"]),
                sub(sub(out["delta_current_liabilities"], out["delta_current_maturities_ltd"]),
                    out["delta_taxes_payable"])),
            out["da_total_t"])

        rev_t, rev_t1 = v("revenue_t"), v("revenue_t1")
        c1, c2 = le0(rev_t), le0(rev_t1)
        if isinstance(c1, Err) or isinstance(c2, Err):
            out["SGI"] = c1 if isinstance(c1, Err) else c2
        else:
            out["SGI"] = "" if (c1 or c2) else div(rev_t, rev_t1)
        ta = v("total_assets_t")
        if not isnumber(out["tata_numerator"]):
            out["TATA"] = ""
        else:
            c = le0(ta)
            out["TATA"] = c if isinstance(c, Err) else ("" if c else div(out["tata_numerator"], ta))

    # Index columns are computed even when the row is not ready (they then see "").
    out["DSRI"] = _index_ratio(out.get("dsr_t"), out.get("dsr_t1"))
    out["GMI"] = _index_ratio(out.get("gm_t1"), out.get("gm_t"))
    out["AQI"] = _index_ratio(out.get("aq_t"), out.get("aq_t1"))
    out["DEPI"] = _index_ratio(out.get("depr_rate_t1"), out.get("depr_rate_t"))
    out["SGAI"] = _index_ratio(out.get("sga_ratio_t"), out.get("sga_ratio_t1"))
    out["LVGI"] = _index_ratio(out.get("lev_ratio_t"), out.get("lev_ratio_t1"))

    if not reason:
        idx = [out[k] for k in ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA"]]
        if count_numbers(*idx) < 8:
            out["m_score_B"] = ""
        else:
            c = COEFFICIENTS
            out["m_score_B"] = (c["const"] + c["DSRI"] * out["DSRI"] + c["GMI"] * out["GMI"] + c["AQI"] * out["AQI"]
                                + c["SGI"] * out["SGI"] + c["DEPI"] * out["DEPI"] + c["SGAI"] * out["SGAI"]
                                + c["TATA"] * out["TATA"] + c["LVGI"] * out["LVGI"])
        for name, key in (("ni", "net_income_t"), ("ibei", "income_before_extraordinary_items_t")):
            a, cfo, c = p.get(key), p.get("cash_flow_from_operations_t"), le0(ta)
            if isinstance(c, Err):  # OR() with an error argument returns the error
                out[f"tata_alt_{name}_cfo"] = c
            elif not isnumber(a) or not isnumber(cfo) or c:
                out[f"tata_alt_{name}_cfo"] = ""
            else:
                out[f"tata_alt_{name}_cfo"] = (a - cfo) / ta

    m = out.get("m_score_B")
    for flag in ("a", "b", "c"):
        thr = THRESHOLDS[flag][0]
        out[f"screen_flag_{flag}"] = "" if not isnumber(m) else (ABOVE if m > thr else BELOW)

    if d["row_active"] != "Y":
        out["calc_status"] = ""
    elif reason:
        out["calc_status"] = "NOT CALCULATED: " + reason
    else:
        out["calc_status"] = "OK" if isnumber(m) else "NOT CALCULATED: invalid or zero denominator"
    out["doc_version"] = p.get("doc_version") if d["row_active"] == "Y" else ""
    out["is_primary"] = d["is_primary"] if d["row_active"] == "Y" else ""
    out["track"] = "B (primary screening basis)" if d["row_active"] == "Y" else ""
    return out
