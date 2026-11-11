"""Items the user verifies in the app before the score is shown (Gail, 4 Nov 2026).

Approved 4 Nov 2026 09.07 (register 4f):
  1. the app has a verification step: the score is withheld while a score item is REVIEW;
  2. the user may type an amount, but only for an item that is marked for verification
     ("Agree" keeps the WARS reading without typing);
  3. the XBRL instance can be uploaded with the PDF (FY2022+); without it the PDF reader is used.

Every amount the user agrees or amends is recorded with its origin (WARS reading, agreed by the user,
amended by the user) and listed in the downloadable reports. Amended amounts go through the same
cross-checks as read amounts; an ERROR keeps the score withheld.
"""
from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field

from . import company, engine, validation
from .pdf_reader import Value
from .text import Amt, Msg, Raw

# Score inputs the user verifies. Amortisation and non-PPE depreciation keep the provisional rules of 28 Oct 2026
# (listed in the report checklist, not verified here).
CHECK_FIELDS = [
    "revenue", "cost_of_goods_sold", "selling_general_administrative_expenses", "accounts_receivable",
    "total_assets", "current_assets", "property_plant_equipment_net", "current_liabilities", "total_liabilities",
    "long_term_debt", "current_maturities_long_term_debt", "cash_and_cash_equivalents", "taxes_payable",
    "ppe_depreciation_disclosed", "amortization_intangibles", "depreciation_amortization_non_ppe",
    "net_income", "cash_flow_from_operations",
]
# the components of the D&A total (workbook: depreciation_expense = D&A - amortisation - non-PPE)
DA_PARTS = ("ppe_depreciation_disclosed", "amortization_intangibles", "depreciation_amortization_non_ppe")
SIGNED = {"net_income", "cash_flow_from_operations"}
CONFIRMED, AMENDED = "USER CONFIRMED", "USER AMENDED"

# Labels searched in the PDF when the amount itself is not printed (it is a sum, or a mis-tag)
LABELS = {
    "accounts_receivable": ["Piutang usaha", "Trade receivables", "Accounts receivable"],
    "property_plant_equipment_net": ["Aset tetap", "Fixed assets", "Property and equipment"],
    "long_term_debt": ["Liabilitas sewa", "Lease liabilities", "Pinjaman bank", "Bank loans"],
    "current_maturities_long_term_debt": ["Liabilitas sewa", "Lease liabilities", "jatuh tempo", "Current maturities"],
    "taxes_payable": ["Pasal 25", "Pasal 29", "Article 29", "Utang pajak"],
    "ppe_depreciation_disclosed": ["Penyusutan aset hak", "Depreciation of right", "dialokasikan", "allocated"],
    "amortization_intangibles": ["Amortisasi", "Amortization", "Amortisation"],
    "depreciation_amortization_non_ppe": ["Penyusutan", "Depreciation", "Amortisasi", "Amortization"],
}
ROU_DEP_LABELS = ["Penyusutan aset hak guna", "Penyusutan aset hak-guna", "Depreciation of right-of-use",
                  "Depreciation of right of use", "Right-of-use assets depreciation"]
XBRL_FIELD = {"property_plant_equipment_net": "ppe_face"}
PDF_READING_CHECKS = {"a_ppe_note", "a_sga_total"}
CONTRACT_ASSET = re.compile(r"(?i)tagihan bruto|aset kontrak|contract assets?|gross amounts? due from")


@dataclass
class CheckItem:
    field: str
    values: dict                      # {"t": WARS reading, "t1": WARS reading}
    reason: Msg
    pages: list = field(default_factory=list)
    numbers: list = field(default_factory=list)   # amounts to highlight on the page extract
    labels: list = field(default_factory=list)    # labels to highlight when the amount is not printed
    second: list = field(default_factory=list)    # labels for a second extract (e.g. right-of-use depreciation)
    mode: str = "review"                          # "review": Agree / Amend; "missing": Enter amount / Nil
    second_ref: tuple = None                      # (page, amounts) of the second extract, when known


# ----------------------------------------------------------------------------------- XBRL + PDF merge

def merge_xbrl(pr, xres):
    """One pipeline.Result for the app and the reports: XBRL face figures and the XBRL-anchored note items
    replace the PDF reader's values; the PDF reading keeps the metadata, statements and evidence pages."""
    r = copy.deepcopy(pr)
    ex = r.extraction
    by = {(v.field, v.column): v for v in ex.values}
    for it in xres.items:
        v = by.get((it.field, it.column))
        if v is None:
            v = Value(it.field, it.column, None, "NOT FOUND")
            ex.values.append(v)
            by[(it.field, it.column)] = v
        v.value = None if it.value is None else (it.value if it.field in SIGNED else abs(it.value))
        v.status = it.status
        pg = re.findall(r"\bp(\d{1,4})\b", f"{it.source} {it.note}")
        xf = (((xres.xbrl or {}).get("fields") or {}).get(it.column) or {}).get(XBRL_FIELD.get(it.field, it.field))
        ev = [e[0] for e in (getattr(xf, "evidence", None) or []) if e and isinstance(e[0], int)]
        if pg or ev:
            v.pages = sorted({int(x) for x in pg} | set(ev) | (set(v.pages or []) if it.status != "FOUND" else set()))
            if it.status == "FOUND" and ev:
                line = next((e[1] for e in xf.evidence if len(e) > 1 and e[1]), "")
                v.quotes = [line] if line else []
        v.note = _user_note(it)
        if it.status != "FOUND":
            v.quotes = []
    r.inputs = dict(xres.inputs)
    r.calc = dict(xres.calc)
    _sync_da_total(r)
    # the XBRL EntityCode names the issuer (the XBRL gate checks it); the PDF header match must not contradict it
    dei = (xres.xbrl or {}).get("dei") or {}
    x_issuer = company.by_ticker(dei.get("EntityCode", ""))
    if x_issuer and (r.issuer is None or r.issuer.ticker == x_issuer.ticker):
        # the name the issuer itself filed for this year: never cut at 30 characters, and the name of that year
        # for an issuer renamed since (Gail 11 Nov: 'Astrindo Nusantara Infrastrukt')
        name = re.sub(r"^\s*PT\.?\s+", "", str(dei.get("EntityName") or "")).strip()
        r.issuer = company.Issuer(x_issuer.ticker, name, x_issuer.status) if name else x_issuer
    elif x_issuer:
        r.issuer = None                    # PDF header and XBRL name different issuers: not identified (T-1)
    r.review = [(it.field, it.column, it.status, _user_note(it))
                for it in xres.items if it.status in ("REVIEW", "ASSUMED", "UNDISCLOSED") and it.value is not None]
    r.missing = [(it.field, it.column, it.status, _user_note(it)) for it in xres.items
                 if it.status in ("NOT FOUND", "NOT ASSESSED")]
    r.assumed = [(it.field, it.column, _user_note(it)) for it in xres.items if it.status == "ASSUMED"]
    if xres.held:
        r.calc["m_score_B"] = ""          # P8 / not found: withheld, the reasons are in r.missing
    if pr.unreadable:
        # the PDF statements could not be read (e.g. image pages): the XBRL figures cannot be reconciled to the
        # face of the report and the review step has nothing to show, so the score is withheld (rule 7;
        # XBRL stage 6, 4 Nov 2026: a score was shown with REVIEW inputs unchecked)
        r.calc["m_score_B"] = ""
    if xres.gate:
        r.unreadable = Msg("chk.gate", why=Raw("; ".join(str(g) for g in xres.gate)))
    try:
        r.flags = validation.check(r.inputs, ex) if not r.unreadable else []
    except Exception:                                   # noqa: BLE001  validation needs the PDF statements
        r.flags = [f for f in r.flags if f.severity == "ERROR"]
    # the PPE-note and SGA-total cross-checks compare the PDF reader's own reading; an amount XBRL has FOUND
    # (reconciled to the PDF as a printed pair) replaces that reading
    found = {(it.field, it.column) for it in xres.items if it.status == "FOUND"}
    r.flags = _drop_pdf_reading_checks(r.flags, found)
    order = (xres.xbrl or {}).get("column_order") or {}
    if order.get("inconsistent"):
        # XBRL stage 6, finding F; target B (Gail, 8 Nov 2026): an unknown layout withholds the score
        pages = sorted({p for p, _ in order.get("reversed", [])})
        r.flags.append(validation.Flag(LAYOUT_FLAG, "ERROR", "app",
                                       Msg("chk.layout_cols", pages=Raw(", ".join(map(str, pages))))))
    ex.issues = [Msg("issue.xbrl_path")]            # the PDF reader's notes on the face statements no longer apply
    r.xbrl = {"items": xres.items, "found": found,
              "notes": {(it.field, it.column): _xbrl_note(it) for it in xres.items}, "face_findings": (xres.xbrl or {}).get("face_findings", []),
              "face_pages": (xres.xbrl or {}).get("face_pages", {}), "tax": xres.tax, "warnings": xres.warnings,
              "dep_parts": (xres.xbrl or {}).get("dep_parts") or {}}
    return r


def _sync_da_total(r):
    """The D&A total the engine uses is built from its parts; the figure shown in the reading and the checklist
    must be that same figure (XBRL stage 7, finding 6: SIPD showed the PDF reader's 89,819 while 99,315 was used)."""
    for c in ("t", "t1"):
        new = r.inputs.get(f"depreciation_amortization_total_{c}")
        v = next((x for x in r.extraction.values if x.field == "depreciation_amortization_total" and x.column == c), None)
        if new is None or v is None or (v.value is not None and abs(v.value - new) <= 1):
            continue
        v.value, v.status, v.note, v.quotes = new, "BUILT FROM DISCLOSED COMPONENTS", Msg("note.dat_built"), []


def _drop_pdf_reading_checks(flags, found):
    return [fl for fl in flags if not (fl.code in PDF_READING_CHECKS and fl.fields
                                       and all((x, fl.column) in found for x in fl.fields))]


def _user_note(it):
    """What the user reads about an XBRL-path item: catalogue text only (the technical note stays in it.note).
    Items verified in the review step get their reason from annotate()."""
    if it.status == "FOUND":
        return ""
    if it.status in ("ASSUMED", "UNDISCLOSED"):
        # a read amount with unread parts counted 0 is not 'counted as 0' (XBRL stage 7, finding 6: RDTX 83.6 bn)
        return Msg("chk.note.assumed_part") if it.value else Msg("chk.note.assumed")
    if it.status in ("NOT FOUND", "NOT ASSESSED"):
        return Msg("chk.note.not_found")
    return Msg("chk.note.single")


def annotate(r, checks):
    """Put each verification reason on the item in the reading, so the report checklist shows it (also when
    the review step is skipped)."""
    reasons = {it.field: it.reason for it in checks}
    r.review = [(f, c, s_, reasons.get(f, n)) if s_ == "REVIEW" else (f, c, s_, n) for f, c, s_, n in r.review]
    for v in r.extraction.values:
        if v.field in reasons and v.status == "REVIEW":
            v.note = reasons[v.field]
    return r


def _xbrl_note(it) -> str:
    return " · ".join(x for x in (it.source if it.status != "FOUND" else "", it.note) if x).strip()


# ----------------------------------------------------------------------------------- items to verify

# v1.0 target B (Gail, 8 Nov 2026 12.02): the line items that were read wrongly in XBRL stages 4-6 are always
# verified by the user, whatever their status (FOUND, or a zero counted because nothing was found).
LAYOUT_FLAG = "x_column_order"     # year columns in inconsistent order on the PDF text layer (stage 6, finding F)
RISK_FIELDS = ("long_term_debt", "current_maturities_long_term_debt", "taxes_payable",
               "ppe_depreciation_disclosed", "amortization_intangibles", "depreciation_amortization_non_ppe")
ZERO_STATUSES = ("ASSUMED", "UNDISCLOSED")
# A score line WARS did not find at all can be completed by the user (Gail, 8 Nov 2026 16.21): the amount with
# its source page, or "nil" with the notes checked. Nil only where nil is a real possibility for the line.
NIL_FIELDS = ("long_term_debt", "current_maturities_long_term_debt", "taxes_payable", "amortization_intangibles",
              "depreciation_amortization_non_ppe")


RISK_REASON = {"taxes_payable": "chk.r.risk_tax", "long_term_debt": "chk.r.risk_debt",
               "current_maturities_long_term_debt": "chk.r.risk_debt"}


def _risk_status(r, f):
    """Statuses of a risk field (t, t1) that are not REVIEW and not yet checked by the user."""
    st = {v.column: v.status for v in r.extraction.values if v.field == f and v.column in ("t", "t1")}
    return {c: s for c, s in st.items() if s not in ("REVIEW", CONFIRMED, AMENDED, "NOT FOUND", "NOT ASSESSED")}


def items(r) -> list:
    """Score items to verify, one per field (both years), in the order of CHECK_FIELDS: every REVIEW reading,
    and the risk fields always (target B)."""
    if r.unreadable or any(f.code == LAYOUT_FLAG for f in (getattr(r, "flags", None) or [])):
        return []                      # nothing the user can verify against a text layer in the wrong order
    by = {(v.field, v.column): v for v in r.extraction.values}
    xb = getattr(r, "xbrl", None) or {}
    tech = xb.get("notes") or {}           # XBRL path: the technical note decides the reason, the user reads catalogue text
    rev = {(f, c): tech.get((f, c), note) for f, c, s, note in r.review if s == "REVIEW"}
    findings = xb.get("face_findings", [])
    face_text = " ".join(f.get("line", "") for f in findings)
    out = []
    # NOT ASSESSED too (XBRL stage 7, finding 5: CTTH investment property with no depreciation read, P8)
    missing = {f for f, c, s, _ in (getattr(r, "missing", None) or []) if s in ("NOT FOUND", "NOT ASSESSED")}
    for f in CHECK_FIELDS:
        vals = {c: r.inputs.get(f"{f}_{c}") for c in ("t", "t1")}
        if f in missing and any(v is None for v in vals.values()):
            pages = sorted({pg for v in r.extraction.values if v.field == f for pg in (getattr(v, "pages", None) or [])})
            out.append(CheckItem(f, vals, Msg("chk.r.missing"), pages, [], [], mode="missing"))
            continue
        cols = [c for c in ("t", "t1") if (f, c) in rev]
        risk = _risk_status(r, f) if f in RISK_FIELDS else {}
        if not cols and not risk:
            continue
        vals = {c: r.inputs.get(f"{f}_{c}") for c in ("t", "t1")}
        if any(v is None for v in vals.values()):
            continue                                   # handled below as a missing line
        if cols:
            note = " ".join(str(rev[(f, c)]) for c in cols)
            reason, labels = _reason(f, note, findings, r)
        elif any(s in ZERO_STATUSES and not vals.get(c) for c, s in risk.items()):
            reason, labels = Msg("chk.r.risk_zero"), []
        else:   # the lease / right of use wording fits debt and depreciation, not tax payable (Gail 8 Nov 16.06);
            # debt also names interest-bearing related-party loans (XBRL stage 7, finding 3: CTTH)
            reason, labels = Msg(RISK_REASON.get(f, "chk.r.risk")), []
        pages = sorted({p for c in ("t", "t1") for p in ((by.get((f, c)).pages if by.get((f, c)) else []) or [])})
        if not pages or f in FACE_FIELDS:
            pages = sorted(set(pages) | set(_face_pages(r, f)))
        second = ROU_DEP_LABELS if f == "ppe_depreciation_disclosed" else []
        numbers, second_ref = [vals["t"], vals["t1"]], None
        dp = ((getattr(r, "xbrl", None) or {}).get("dep_parts") or {}) if f == "ppe_depreciation_disclosed" else {}
        if dp.get("rou_page") and all(vals[c] is not None and abs(vals[c] - dp["own"][k] - dp["rou"][k]) <= 1
                                      for k, c in enumerate(("t", "t1"))):
            # the reading is a sum of two printed components on two pages: say so and show both pages (LRNA 2025,
            # Gail 11 Nov 13.11). Shown only when the components add up to the reading in both years.
            reason = Msg("chk.r.dep_parts", own_t=Amt(dp["own"][0]), rou_t=Amt(dp["rou"][0]), own_t1=Amt(dp["own"][1]),
                         rou_t1=Amt(dp["rou"][1]), p1=Raw(str(dp["own_page"])), p2=Raw(str(dp["rou_page"])))
            pages = [dp["own_page"]] + [x for x in pages if x != dp["own_page"]]
            numbers, second_ref = list(dp["own"]), (dp["rou_page"], list(dp["rou"]))
        out.append(CheckItem(f, vals, reason, pages, numbers, labels + LABELS.get(f, []), second, "review", second_ref))
    return out


FACE_FIELDS = {"revenue", "cost_of_goods_sold", "selling_general_administrative_expenses", "accounts_receivable",
               "total_assets", "current_assets", "property_plant_equipment_net", "current_liabilities",
               "total_liabilities", "long_term_debt", "current_maturities_long_term_debt",
               "cash_and_cash_equivalents", "net_income"}
BS_FIELDS = {"accounts_receivable", "total_assets", "current_assets", "property_plant_equipment_net",
             "current_liabilities", "total_liabilities", "long_term_debt", "current_maturities_long_term_debt",
             "cash_and_cash_equivalents", "taxes_payable"}


def _face_pages(r, f):
    xb = (getattr(r, "xbrl", None) or {}).get("face_pages") or {}
    key = "bs" if f in BS_FIELDS else "pl"
    if xb.get(key):
        return list(xb[key])
    loc = ((r.extraction.fs_location or {}).get("chosen") or {})
    return list(loc.get("position" if f in BS_FIELDS else "profit_loss") or [])


def _reason(f, note, findings, r):
    note_l = note.lower()
    fam = {"long_term_debt": "debt", "current_maturities_long_term_debt": "debt",
           "property_plant_equipment_net": "rou", "ppe_depreciation_disclosed": "rou"}
    line = next((x.get("line", "") for x in findings if x.get("family") == fam.get(f)), "")
    label = re.sub(r"[\d.,()\s-]+$", "", re.sub(r"\s\d[\d.,a-z]*\s.*$", "", line)).strip() if line else ""
    if f == "taxes_payable" and ("pendekatan" in note_l or "d-03g" in note_l):
        return Msg("chk.r.tax_proxy"), []
    if f == "accounts_receivable" and _contract_assets_on_face(r):
        return Msg("chk.r.ar_contract"), ["Tagihan bruto", "Gross amount", "Aset kontrak", "Contract assets"]
    if f in ("long_term_debt", "current_maturities_long_term_debt") and label:
        return Msg("chk.r.debt_untagged", line=Raw(label)), [label]
    if f == "property_plant_equipment_net" and label:
        return Msg("chk.r.ppe_rou", line=Raw(label)), [label]
    if f == "ppe_depreciation_disclosed" and "right-of-use" in note_l:
        return Msg("chk.r.dep_rou"), []
    if f == "ppe_depreciation_disclosed" and "xbrl movement" in note_l:
        m = re.search(r"xbrl movement(?: table gives)? ([\d,]+)", note_l)
        return Msg("chk.r.dep_conflict", x=Amt(float(m.group(1).replace(",", ""))) if m else Raw("—")), []
    if "not found as a (t, t-1) pair" in note_l:
        return Msg("chk.r.not_printed"), []
    return Msg("chk.r.single"), []


def _contract_assets_on_face(r) -> bool:
    st = (r.extraction.statements or {}).get("position")
    if st is not None:
        return any(CONTRACT_ASSET.search(ln.text) for ln in st.lines)
    return bool(getattr(r, "_contract_assets", False))


# ----------------------------------------------------------------------------------- answers

class AnswerError(ValueError):
    """args[0] = text.Msg for the user."""


def parse_amount(s) -> int | None:
    """'91.300.000.000', '91,300,000,000', '(1.234)', '-1.234' -> int; '' -> None. Decimals are refused."""
    if s is None:
        return None
    s = str(s).strip().replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-") or s.startswith("−") or (s.startswith("(") and s.endswith(")"))
    body = s.strip("-−()")
    if not re.fullmatch(r"\d{1,3}([.,]\d{3})*|\d+", body):
        raise AnswerError(Msg("chk.err.format"))
    v = int(re.sub(r"[.,]", "", body))
    return -v if neg else v


def apply(r, checks, answers):
    """answers: {field: {"choice": "ok" | "edit", "t": str, "t1": str}}. Returns a new Result with the
    user's answers applied, the origin of every verified amount recorded, the score recalculated and the
    cross-checks run again. Raises AnswerError when an answer is missing or not an amount."""
    r2 = copy.deepcopy(r)
    by = {(v.field, v.column): v for v in r2.extraction.values}
    p = r2.inputs
    checked = []
    filled = set()
    notes = {}
    for it in checks:
        a = answers.get(it.field) or {}
        if it.mode == "missing":
            got = _apply_missing(r2, by, p, it, a)
            checked += [x[:5] for x in got]
            notes.update({(x[0], x[1]): x[5] for x in got})
            filled.add(it.field)
            continue
        if a.get("choice") not in ("ok", "edit"):
            raise AnswerError(Msg("chk.err.pending", item=Msg(f"label.{it.field}")))
        page = None
        if a["choice"] == "edit":                       # an amended amount needs its source page (Gail 10 Nov)
            page = _page(a, Msg(f"label.{it.field}"))
        for c in ("t", "t1"):
            old = it.values[c]
            if a["choice"] == "edit":
                new = parse_amount(a.get(c))
                if new is None:
                    raise AnswerError(Msg("chk.err.missing", item=Msg(f"label.{it.field}"), y=Raw(_year(r2, c))))
                if it.field not in SIGNED and new < 0:
                    raise AnswerError(Msg("chk.err.negative", item=Msg(f"label.{it.field}")))
            else:
                new = old
            status = AMENDED if (a["choice"] == "edit" and new != old) else CONFIRMED
            p[f"{it.field}_{c}"] = new
            v = by.get((it.field, c))
            note = Msg("chk.prov.amended", old=Amt(old), p=Raw(page)) if status == AMENDED else ""
            if v is not None:
                v.value, v.status, v.note = new, status, note
                if status == AMENDED:                   # the user's page replaces WARS's page for this amount
                    v.pages = [int(page)]
            notes[(it.field, c)] = note
            checked.append((it.field, c, status, old, new))
    # the D&A total is built from its components (workbook: depreciation_expense = D&A - amortisation - non-PPE)
    for c in ("t", "t1"):
        if any(f in DA_PARTS and cc == c and s == AMENDED for f, cc, s, _, _ in checked):
            p[f"depreciation_amortization_total_{c}"] = sum(p.get(f"{f}_{c}") or 0 for f in DA_PARTS)
    _sync_da_total(r2)
    done = {(f, c) for f, c, *_ in checked}
    r2.review = [x for x in r2.review if (x[0], x[1]) not in done] + \
        [(f, c, s, notes.get((f, c), "")) for f, c, s, o, _ in checked]
    r2.missing = [x for x in (getattr(r2, "missing", None) or []) if x[0] not in filled]
    r2.calc = engine.calculate(p)
    if getattr(r, "calc", {}).get("m_score_B") == "" and r2.missing:
        r2.calc["m_score_B"] = ""
    try:
        r2.flags = validation.check(p, r2.extraction)
    except Exception:                                   # noqa: BLE001
        r2.flags = list(r.flags)
    # the PPE-note / SGA-total checks test the PDF reader's own reading; an amount the user has verified replaces
    # that reading just as an XBRL FOUND amount does (XBRL stage 6, finding E: HITS stayed withheld after checking)
    replaced = set((getattr(r2, "xbrl", None) or {}).get("found", set())) | done
    r2.flags = _drop_pdf_reading_checks(r2.flags, replaced) + [f for f in (r.flags or []) if f.code == LAYOUT_FLAG]
    r2.user_checked = checked
    return r2


def _apply_missing(r2, by, p, it, a):
    """A line WARS did not find: the user's amount (with its source page) or nil (with the notes checked)."""
    item = Msg(f"label.{it.field}")
    choice = a.get("choice")
    if choice not in ("enter", "nil") or (choice == "nil" and it.field not in NIL_FIELDS):
        raise AnswerError(Msg("chk.err.pending", item=item))
    if choice == "enter":
        page = _page(a, item)
        note = Msg("chk.prov.entered", p=Raw(page))
    else:
        checked_notes = str(a.get("note") or "").strip()
        if not checked_notes:
            raise AnswerError(Msg("chk.err.note", item=item))
        note = Msg("chk.prov.nil", note=Raw(checked_notes))
    out = []
    for c in ("t", "t1"):
        old = it.values[c]
        if choice == "nil":
            new = 0
        else:
            new = parse_amount(a.get(c))
            if new is None:
                raise AnswerError(Msg("chk.err.missing", item=item, y=Raw(_year(r2, c))))
            if it.field not in SIGNED and new < 0:
                raise AnswerError(Msg("chk.err.negative", item=item))
        status = CONFIRMED if (old is not None and new == old) else AMENDED
        p[f"{it.field}_{c}"] = new
        if it.field == "depreciation_amortization_non_ppe":
            # M-06/M-14: nil with the notes examined = none present; an entered amount is never 'all disclosed'
            p[f"non_ppe_status_{c}"] = "NONE_PRESENT" if choice == "nil" else "PARTIAL_UNDISCLOSED"
        if it.field == "amortization_intangibles":
            p[f"amort_status_{c}"] = ""
        v = by.get((it.field, c))
        if v is not None:
            v.value, v.status, v.note = new, status, note
            if choice == "enter":
                v.pages = [int(page)]
        out.append((it.field, c, status, old, new, note))
    return out


def _page(a, item):
    """The source page the user gave: a page number of the PDF file (1 = the first page of the file)."""
    page = str(a.get("page") or "").strip()
    if not page.isdigit() or int(page) < 1:
        raise AnswerError(Msg("chk.err.page", item=item))
    return str(int(page))


def _year(r, c):
    fy = getattr(r.extraction, "fiscal_year", None)
    return (str(fy) if c == "t" else str(fy - 1)) if fy else c


# ----------------------------------------------------------------------------------- page extract

def _variants(v):
    n = int(round(abs(v)))
    if n < 1000:
        return []
    dots = f"{n:,}".replace(",", ".")
    return [dots, f"{n:,}"]


def extract_png(pdf_bytes: bytes, item: CheckItem, scale: float = 4.0):
    """PNG of the part of a page that holds the item's amounts (or labels), the hits highlighted.
    Returns (png bytes, page number) or (None, None)."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    doc = pdfium.PdfDocument(pdf_bytes)
    n = len(doc)
    own = [p - 1 for p in item.pages if 0 < p <= n]

    def hits_on(i, with_labels):
        tp = doc[i].get_textpage()
        pw, ph = doc[i].get_size()
        # text outside the visible page (hidden or clipped objects) is never evidence: it once matched an amount
        # and stretched the extract down to an unrelated sentence (PTBA 2022 p. 90, Gail 8 Nov)
        on = lambda b: b[2] > 0 and b[0] < pw and b[3] > 0 and b[1] < ph                  # noqa: E731
        hits = [hh for v in item.numbers for s in _variants(v or 0) for hh in _find(tp, s) if on(hh)]
        n_num = len(hits)
        if with_labels:
            hits += [hh + ("label",) for lab in item.labels for hh in _find(tp, lab) if on(hh)]
        return n_num, hits

    best = None
    for i in own:                                   # the evidence pages first: amounts and labels
        n_num, hits = hits_on(i, True)
        if hits and (best is None or (n_num, len(hits)) > best[0]):
            best = ((n_num, len(hits)), i, hits)
    if best is None:                                # elsewhere only the amounts themselves
        for i in range(n):
            if i in own:
                continue
            n_num, hits = hits_on(i, False)
            if n_num and (best is None or (n_num, len(hits)) > best[0]):
                best = ((n_num, len(hits)), i, hits)
                if n_num >= 2:
                    break
    if best is None:
        return None, None
    _, i, hits = best
    page = doc[i]
    w, h = page.get_size()
    num_hits = [x for x in hits if len(x) == 4] or hits
    top = max(y1 for _, _, _, y1, *_ in num_hits)
    bot = max(min(y0 for _, y0, _, _, *_ in num_hits), top - 300)
    y_hi = min(h, top + 70)
    y_lo = max(0, min(bot - 110, y_hi - 160))
    img = page.render(scale=scale).to_pil().convert("RGB")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for x0, y0, x1, y1, *_ in hits:
        if y1 < y_lo or y0 > y_hi:
            continue
        d.rectangle([(0, (h - y1 - 2) * scale), (w * scale, (h - y0 + 2) * scale)], fill=(255, 214, 102, 90))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    img = img.crop((0, int((h - y_hi) * scale), int(w * scale), int((h - y_lo) * scale)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), i + 1


def _find(tp, text):
    out = []
    try:
        s = tp.search(text, match_case=False, match_whole_word=False)
    except Exception:                                   # noqa: BLE001
        return out
    while True:
        m = s.get_next()
        if not m:
            break
        start, count = m
        boxes = [tp.get_charbox(j) for j in range(start, start + count)]
        out.append((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)))
        if len(out) > 20:
            break
    return out


def second_extract_png(pdf_bytes: bytes, item: CheckItem, skip_page=None, scale: float = 4.0):
    """A second extract for the item: the first line, outside the accounting-policy pages, that carries one of
    item.second followed by two amounts (e.g. right-of-use depreciation in the expense note)."""
    if item.second_ref:
        page, nums = item.second_ref
        return extract_png(pdf_bytes, CheckItem(item.field, {}, item.reason, [page], nums, []), scale)
    if not item.second:
        return None, None
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    for i in range(len(doc)):
        if skip_page and i + 1 == skip_page:
            continue
        txt = doc[i].get_textpage().get_text_range()
        for ln in txt.splitlines():
            if any(lab.lower() in ln.lower() for lab in item.second) and \
                    len(re.findall(r"\d{1,3}(?:[.,]\d{3})+", ln)) >= 2:
                nums = [int(re.sub(r"[.,]", "", x)) for x in re.findall(r"\d{1,3}(?:[.,]\d{3})+", ln)][-2:]
                sub = CheckItem(item.field, {}, item.reason, [i + 1], nums, [])
                return extract_png(pdf_bytes, sub, scale)
    return None, None
