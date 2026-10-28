"""Turn a pipeline Result into the tables and sentences the app shows, in ID or EN.

No Streamlit here, so it can be tested. Every sentence comes from the text catalogue
(`wars_scanner.text`); this module only chooses the entry and fills in the figures.

Language rule (CLAUDE.md): red flag / needs closer examination; never a fraud verdict.
Sentence rules: WARS_Analysis_Text_Rules_r1 (B r1, approved by Gail 23 Oct 2026).
"""
from __future__ import annotations

from .parameters import COEFFICIENTS, THRESHOLDS
from .pipeline import Result
from .text import Money, Msg, Num, Pct, Psak, Raw, engine_reason, fmt_number, join, render, t

INDEX_ORDER = ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA"]
SIGNIFICANT = ("DSRI", "GMI", "AQI", "SGI", "TATA")       # B r1 §3 / K7: only these get a finding
DRIVER_MIN_PUSH = 0.005                                    # B r1 §3
M_CONSTANT = -4.84
THRESHOLD = THRESHOLDS["a"][0]                             # -1.78: the only threshold shown (M-09 A)

FIELD_ORDER = [
    "revenue", "cost_of_goods_sold", "selling_general_administrative_expenses", "accounts_receivable",
    "contract_assets", "total_assets", "current_assets", "cash_and_cash_equivalents",
    "property_plant_equipment_net", "rou_assets_net", "current_liabilities", "total_liabilities", "long_term_debt",
    "current_maturities_long_term_debt", "taxes_payable", "ppe_depreciation_disclosed", "rou_depreciation",
    "amortization_intangibles", "depreciation_amortization_non_ppe", "depreciation_amortization_total",
    "net_income", "cash_flow_from_operations",
]
SUB_ROWS = {"rou_assets_net", "rou_depreciation"}          # shown indented under their parent

GREEN, YELLOW, RED = "green", "yellow", "red"
STATUS_COLOUR = {"FOUND": GREEN, "USER SET": GREEN, "REVIEW": YELLOW, "UNDISCLOSED": YELLOW,
                 "BUILT FROM DISCLOSED COMPONENTS": YELLOW, "ASSUMED": YELLOW}
NEUTRAL_M = M_CONSTANT + sum(v for k, v in COEFFICIENTS.items() if k not in ("const", "TATA"))   # all indices 1, TATA 0: -2.48

# Confirmation answers are stored as codes, so switching the language keeps the user's answers.
PENDING_ANSWER, OK_ANSWER, BAD_ANSWER = "PENDING", "OK", "BAD"
ANSWERS = (PENDING_ANSWER, OK_ANSWER, BAD_ANSWER)


def dec(v, n=3, lang="id"):
    """Decimal per language (R-04), e.g. −2,316 / −2.316."""
    return fmt_number(v, lang, n)


def amount(v, lang="id"):
    return "" if v is None else fmt_number(v, lang, 0)


def label(field, lang="id"):
    key = f"label.{field}"
    return t(key, lang) if key in _labels() else field


def _labels():
    from .text import CATALOG
    return CATALOG


def title(field, lang="id"):
    """Label without the 'of which' prefix, capitalised (for lists and confirmation items)."""
    s = label(field, lang).strip()
    for pre in ("di antaranya: ", "of which: "):
        if s.startswith(pre):
            s = s[len(pre):]
            return s[:1].upper() + s[1:]
    return s


def status_label(status, lang="id"):
    key = f"status.{status}"
    return t(key, lang) if key in _labels() else str(status)


# ----------------------------------------------------------------------------------- input table

def input_rows(r: Result, lang="id"):
    """One row per field: value t, value t-1, colour per column, status text, pages, source line, remarks.

    Rule codes are not shown to the user (Gail 28 Oct 2026, report review)."""
    by = {(v.field, v.column): v for v in r.extraction.values}
    rows = []
    for f in FIELD_ORDER:
        cells = {c: by.get((f, c)) for c in ("t", "t1")}
        if not any(cells.values()):
            continue
        row = {"field": f, "label": ("  " if f in SUB_ROWS else "") + label(f, lang)}
        for c, v in cells.items():
            usable = v is not None and v.value is not None and v.status in STATUS_COLOUR
            row[f"value_{c}"] = amount(v.value, lang) if v is not None else ""
            row[f"colour_{c}"] = STATUS_COLOUR.get(v.status, RED) if usable else (
                YELLOW if v is not None and v.status in ("NOT DISCLOSED", "INCLUDED IN PPE") else RED)
            row[f"status_{c}"] = status_label(v.status, lang) if v is not None else status_label("NOT SEARCHED", lang)
        vt = cells["t"] or cells["t1"]
        row["pages"] = ", ".join(str(p) for p in sorted({p for v in cells.values() if v for p in v.pages}))
        row["source"] = (vt.quotes[0] if vt and vt.quotes else "")
        row["components_t"] = render(cells["t"].components, lang) if cells["t"] else ""
        notes = list(dict.fromkeys(render(v.note, lang) for v in cells.values() if v and v.note))
        row["note"] = " | ".join(notes)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------------------- indices and findings

def index_rows(r: Result, lang="id"):
    """Index value, its contribution to M, and the push relative to a neutral company (index 1, TATA 0)."""
    g23 = any(f.code == "r_rou_dep_missing" for f in getattr(r, "flags", []))
    out = []
    for k in INDEX_ORDER:
        v = r.calc.get(k)
        num = isinstance(v, (int, float)) and not isinstance(v, bool)
        neutral = 0.0 if k == "TATA" else 1.0
        push = COEFFICIENTS[k] * (v - neutral) if num else None
        if k in SIGNIFICANT:
            note = t(f"why.{k}", lang)
        else:
            note = t("why.minor", lang) + (" " + t("why.DEPI_g23", lang) if k == "DEPI" and g23 else "")
        out.append({"index": k, "name": t(f"idx.name.{k}", lang), "value": v if num else None,
                    "coefficient": COEFFICIENTS[k], "contribution": COEFFICIENTS[k] * v if num else None,
                    "push_vs_neutral": push, "note": note})
    return out


def drivers(r: Result, n=3, lang="id"):
    """B r1 §3: computed, significant in Beneish (1999), push above 0.005; largest first, at most 3."""
    rows = [x for x in index_rows(r, lang) if x["index"] in SIGNIFICANT and x["push_vs_neutral"] is not None
            and x["push_vs_neutral"] > DRIVER_MIN_PUSH]
    return sorted(rows, key=lambda x: -x["push_vs_neutral"])[:n]


INDEX_FIELDS = {
    "DSRI": ("accounts_receivable", "revenue"),
    "GMI": ("revenue", "cost_of_goods_sold"),
    "AQI": ("current_assets", "property_plant_equipment_net", "total_assets"),
    "SGI": ("revenue",),
    "DEPI": ("ppe_depreciation_disclosed", "property_plant_equipment_net"),
    "SGAI": ("selling_general_administrative_expenses", "revenue"),
    "LVGI": ("current_liabilities", "long_term_debt", "total_assets"),
    "TATA": ("current_assets", "cash_and_cash_equivalents", "current_liabilities", "current_maturities_long_term_debt",
             "taxes_payable", "depreciation_amortization_total", "total_assets"),
}


def index_sources(r: Result, k: str, lang="id"):
    """The line items behind an index with their PDF pages, so the user can trace it (Gail 28 Oct 2026)."""
    out = []
    for f in INDEX_FIELDS.get(k, ()):
        pages = sorted({p for v in r.extraction.values if v.field == f for p in v.pages})
        item = t(f"short.{f}", lang)
        out.append(t("rep.trace_item", lang, item=item, p=", ".join(str(p) for p in pages)) if pages else item)
    return "; ".join(out)


FINDING_FIELDS = {
    "DSRI": ("accounts_receivable", "revenue"),
    "GMI": ("revenue", "cost_of_goods_sold"),
    "AQI": ("current_assets", "property_plant_equipment_net", "total_assets"),
    "SGI": ("revenue",),
    "TATA": ("current_assets", "cash_and_cash_equivalents", "current_liabilities", "current_maturities_long_term_debt",
             "taxes_payable", "depreciation_amortization_total"),
}
TRANSITION_AFFECTS = {"r_standard_transition": ("DEPI", "AQI", "LVGI"),          # PSAK 73 (B r1 §6)
                      "r_standard_transition_other": ("DSRI", "SGI", "GMI")}    # PSAK 71 / 72


def _val(r, f, c):
    v = r.inputs.get(f"{f}_{c}")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _page(r, f, c="t"):
    v = next((x for x in r.extraction.values if x.field == f and x.column == c), None)
    return v.pages[0] if v is not None and v.pages else "—"


def _status(r, f, c):
    v = next((x for x in r.extraction.values if x.field == f and x.column == c), None)
    return v.status if v is not None else None


def _chg(a, b):
    if a is None or not b:
        return Raw("—")
    g = a / b - 1
    return Msg("chg.up" if g >= 0 else "chg.down", pct=Pct(abs(g)))


def finding(r: Result, k: str, confirm=None, lang="id"):
    """B r1 §4: A (figures and pages), C (possible explanations), D (areas for examination), and the
    model's rationale for the 'About this index' fold. Returns dict(a, c, d, why, caveats)."""
    unit = getattr(r.extraction, "unit_scale", None)
    ccy = getattr(r.extraction, "currency", None) or "IDR"
    fy = getattr(r.extraction, "fiscal_year", None)
    m = lambda v: Money(v, unit, currency=ccy) if v is not None else Raw("—")        # noqa: E731
    push = next(x["push_vs_neutral"] for x in index_rows(r, lang) if x["index"] == k)
    idx, pu = Num(r.calc.get(k), 2), Num(push, 2, True)
    g = lambda f, c="t": _val(r, f, c)                                   # noqa: E731
    if k == "DSRI":
        a = Msg("f.DSRI", chg_ar=_chg(g("accounts_receivable"), g("accounts_receivable", "t1")),
                chg_rev=_chg(g("revenue"), g("revenue", "t1")), ar_t1=m(g("accounts_receivable", "t1")),
                ar_t=m(g("accounts_receivable")), p_ar=_page(r, "accounts_receivable"), p_rev=_page(r, "revenue"),
                idx=idx, push=pu)
    elif k == "GMI":
        gm = {c: (g("revenue", c) - g("cost_of_goods_sold", c)) / g("revenue", c)
              if g("revenue", c) and g("cost_of_goods_sold", c) is not None else None for c in ("t", "t1")}
        a = Msg("f.GMI", gm_t1=Pct(gm["t1"]) if gm["t1"] is not None else Raw("—"),
                gm_t=Pct(gm["t"]) if gm["t"] is not None else Raw("—"), p_rev=_page(r, "revenue"), idx=idx, push=pu)
    elif k == "AQI":
        aq = {c: 1 - (g("current_assets", c) + g("property_plant_equipment_net", c)) / g("total_assets", c)
              if None not in (g("current_assets", c), g("property_plant_equipment_net", c)) and g("total_assets", c)
              else None for c in ("t", "t1")}
        a = Msg("f.AQI", aq_t1=Pct(aq["t1"]) if aq["t1"] is not None else Raw("—"),
                aq_t=Pct(aq["t"]) if aq["t"] is not None else Raw("—"), p_ta=_page(r, "total_assets"), idx=idx, push=pu)
    elif k == "SGI":
        a = Msg("f.SGI", chg_rev=_chg(g("revenue"), g("revenue", "t1")), rev_t1=m(g("revenue", "t1")),
                rev_t=m(g("revenue")), p_rev=_page(r, "revenue"), idx=idx, push=pu)
    else:  # TATA
        def d(f):
            a_, b_ = g(f), g(f, "t1")
            return (a_ or 0) - (b_ or 0)
        d_ca = d("current_assets") - d("cash_and_cash_equivalents")
        d_cl = d("current_liabilities") - d("current_maturities_long_term_debt") - d("taxes_payable")
        common = dict(tata=Pct(r.calc.get("TATA")), d_ca=Money(d_ca, unit, True, ccy), d_cl=Money(d_cl, unit, True, ccy),
                      da=m(g("depreciation_amortization_total")), p_ca=_page(r, "current_assets"))
        ni, cfo = g("net_income"), g("cash_flow_from_operations")
        if ni is not None and cfo is not None:
            a = Msg("f.TATA", ni=m(ni), cfo=m(cfo), p_ni=_page(r, "net_income"),
                    p_cfo=_page(r, "cash_flow_from_operations"), **common)
        else:
            a = Msg("f.TATA_nocmp", **common)
    a_text = a.render(lang)
    confirmed = bool(confirm) and confirm.get("state") == "confirmed"
    if not confirmed and any(_status(r, f, c) in ("REVIEW", "UNDISCLOSED", "BUILT FROM DISCLOSED COMPONENTS")
                             for f in FINDING_FIELDS[k] for c in ("t", "t1")):
        a_text += " " + t("drivers.unconfirmed", lang)
    if k == "DSRI":
        ca = next((v for v in r.extraction.values if v.field == "contract_assets" and v.pages), None)
        if ca is not None:
            a_text += " " + t("drivers.ca_note", lang, p=ca.pages[0])
    p115, p238 = Psak("115", "72", fy, "¶31, ¶38" if k == "DSRI" else "¶114"), Psak("238", "19", fy, "¶54, ¶57, ¶69")
    c_text = t("drivers.c", lang, items=Msg(f"c.{k}"))
    d_text = t("drivers.d", lang, items=Msg(f"d.{k}", **({"psak115": p115} if k in ("DSRI", "SGI") else
                                                          {"psak238": p238} if k == "AQI" else {})))
    caveats = []
    for fl in getattr(r, "flags", []):
        if k in TRANSITION_AFFECTS.get(fl.code, ()):
            std = Psak("116", "73", fy) if fl.code == "r_standard_transition" else \
                join([Psak(n, o, fy) for n, o in (("109", "71"), ("115", "72"))], " / ")
            caveats.append(t("drivers.caveat_transition", lang, t=fy or "t", std=std))
        if fl.code == "r_comparative_label":
            caveats.append(t("drivers.caveat_restated", lang))
    return {"index": k, "a": a_text, "c": c_text, "d": d_text, "why": t(f"why.{k}", lang),
            "caveats": list(dict.fromkeys(caveats))}


# ----------------------------------------------------------------------------------- confirmation

def confirmation_summary(items, answers):
    """answers: {item key: answer code}. Returns dict(state, ok, bad, pending, bad_items).

    state: "none" (nothing to confirm), "pending", "bad" (at least one item rejected),
    "confirmed" (every item confirmed). Confirmation by the user is not independent verification.
    """
    ok = [i for i in items if answers.get(i["key"]) == OK_ANSWER]
    bad = [i for i in items if answers.get(i["key"]) == BAD_ANSWER]
    pending = [i for i in items if i not in ok and i not in bad]
    state = "none" if not items else "bad" if bad else "pending" if pending else "confirmed"
    return {"state": state, "ok": len(ok), "bad": len(bad), "pending": len(pending), "bad_items": bad}


def review_items(r: Result, lang="id"):
    """Everything the user must confirm, one item per (field, column) or per cross-check flag.

    Returns dicts: key (stable id, same in both languages), title, year column, why. Engine-input
    values marked REVIEW / UNDISCLOSED / BUILT and cross-check flags of severity REVIEW. Status
    fields (amort_status, non_ppe_status) are folded into their amount field.
    """
    items, seen = [], set()
    fold = {"amort_status": "amortization_intangibles", "non_ppe_status": "depreciation_amortization_non_ppe"}
    for f, c, s, note in r.review:
        f2 = fold.get(f, f)
        key = f"in:{f2}:{c}"
        if key in seen:
            continue
        seen.add(key)
        st_txt, note_txt = status_label(s, lang), render(note, lang)
        # the status and the note may say the same thing (e.g. "Sum of disclosed components"): say it once
        why = note_txt if note_txt.startswith(st_txt) else (
            t("confirm.why", lang, status=Raw(st_txt), note=Raw(note_txt)) if note_txt else st_txt)
        items.append({"key": key, "title": title(f2, lang), "column": c, "why": why.strip()})
    covered = {k.split(":")[1] for k in seen}
    for fl in getattr(r, "flags", []):
        if fl.severity != "REVIEW":
            continue
        if fl.fields and all(f in covered for f in fl.fields) and fl.code.startswith(("r_amort", "r_non_ppe")):
            continue        # same point as the input item already listed
        key = f"chk:{fl.code}:{','.join(fl.fields)}:{fl.column}"
        if key in seen:
            continue
        seen.add(key)
        name = ", ".join(title(x, lang) for x in fl.fields) or fl.code
        items.append({"key": key, "title": name, "column": fl.column, "why": render(fl.message, lang)})
    return items


# ----------------------------------------------------------------------------------- verdict

def _years(cols, lang):
    names = [t(f"years.{c}", lang) for c in cols]
    return names[0] if len(names) == 1 else t("years.and", lang, a=names[0], b=names[1])


def _reason(r):
    raw = r.calc.get("not_ready_reason") or ""
    if not raw:
        cs = str(r.calc.get("calc_status") or "")
        raw = cs.split(":", 1)[1].strip() if cs.startswith("NOT CALCULATED:") else ""
    return engine_reason(raw)


def verdict(r: Result, confirm=None, lang="id", reviewer="", provisional_note=True):
    """(headline, detail, level) in screening language only (B r1 §6). level: high / low / none.

    `confirm` is the result of confirmation_summary(); without it the result counts as unconfirmed.
    Only the −1.78 threshold is shown (M-09 A).
    """
    who = reviewer.strip() or t("v.someone", lang)
    if confirm and confirm["state"] == "bad" and r.m_score is not None:
        names = "; ".join(i["title"] for i in confirm["bad_items"])
        return (t("v.unusable", lang),
                t("v.rejected_detail", lang, name=Raw(who), n=confirm["bad"], items=Raw(names)), "none")
    m = r.m_score
    inv = (getattr(r.extraction, "non_ppe_evidence", None) or {}).get("invprop_face")
    if m is None and r.status == "AWAITING NON-PPE STATUS" and inv:
        return (t("v.withheld", lang), t("v.held_invprop", lang, p=inv["page"], years=_years(r.non_ppe_pending, lang)),
                "none")
    if m is None and r.status == "AWAITING NON-PPE STATUS":
        return (t("v.withheld", lang), t("v.held_nonppe", lang, years=_years(r.non_ppe_pending, lang),
                                         section=t("np.title", lang)), "none")
    if m is None and r.status == "AWAITING AMORTISATION STATUS":
        return (t("v.withheld", lang), t("v.held_amort", lang, years=_years(r.amort_pending, lang),
                                         section=t("am.title", lang)), "none")
    if m is None and getattr(r, "unreadable", ""):
        return t("v.not_calc", lang), t("v.unreadable_detail", lang, why=r.unreadable), "none"
    if m is None and r.m_score_raw is not None and r.errors:
        why = "; ".join(dict.fromkeys(render(f.message, lang) for f in r.errors))
        return t("v.unusable", lang), t("v.unusable_detail", lang, checks=Raw(why)), "none"
    if m is None:
        miss = sorted({title(f, lang) for f, c, st_, _ in getattr(r, "missing", []) if f"label.{f}" in _labels()})
        if miss:          # Gail 28 Oct 10.32: say which values the system could not trace
            return t("v.not_calc", lang), t("ui.not_traced", lang, items=Raw(", ".join(miss))), "none"
        return t("v.not_calc", lang), t("v.not_calc_detail", lang, reason=_reason(r)), "none"
    thr = Num(THRESHOLD, 2)
    if m > THRESHOLD:
        head, level = t("v.above", lang, m=Num(m, 2), thr=thr), "high"
        drv = [d["index"] for d in drivers(r, lang=lang)]
        detail = t("v.above_detail_idx", lang, indices=Raw(", ".join(drv))) if drv else t("v.above_detail", lang)
    else:
        head, level = t("v.below", lang, m=Num(m, 2), thr=thr), "low"
        detail = t("v.below_detail", lang)
    fy = getattr(r.extraction, "fiscal_year", None)
    for fl in getattr(r, "flags", []):
        if fl.code == "r_standard_transition":
            detail += " " + t("v.transition", lang, t=fy or "t", std=Psak("116", "73", fy),
                              indices=Raw(", ".join(TRANSITION_AFFECTS[fl.code])))
        elif fl.code == "r_standard_transition_other":
            std = join([Psak(n, o, fy) for n, o in (("109", "71"), ("115", "72"))
                        if f"PSAK {o}" in str(r.inputs.get("standards_first_applied_t", ""))], " / ")
            detail += " " + t("v.transition", lang, t=fy or "t", std=std,
                              indices=Raw(", ".join(TRANSITION_AFFECTS[fl.code])))
        elif fl.code == "r_comparative_label":
            detail += " " + t("v.restated", lang, psak208=Psak("208", "25", fy, "¶49"))
    n = len(review_items(r, lang))
    if not provisional_note:
        return head, detail, level
    if confirm and confirm["state"] == "confirmed":
        detail += " " + t("v.confirmed", lang, m=n, name=Raw(who))
    elif n:
        left = confirm["pending"] if confirm else n
        detail += " " + t("v.provisional", lang, n=left, m=n)
    return head, detail, level


def status_text(r: Result, confirm=None, lang="id"):
    if confirm and r.m_score is not None:
        if confirm["state"] == "bad":
            return t("st.bad", lang)
        if confirm["state"] == "confirmed":
            return t("st.confirmed", lang)
    key = f"st.{r.status}"
    return t(key, lang) if key in _labels() else r.status


# ----------------------------------------------------------------------------------- header and source lines

def issuer_line(r: Result, lang="id"):
    """(ticker, name) from the master list (R-16, T-1); not identified -> ("", text). Never guessed."""
    who = getattr(r, "issuer", None)
    if who is None:
        return "", t("ui.res.issuer_unknown", lang)
    return who.ticker, who.name


AMOUNT = r"\(?-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\)?"


def _drop_note_refs(label: str) -> str:
    """'PENJUALAN NETO 20' → 'PENJUALAN NETO'; 'Pihak berelasi 6,23' → 'Pihak berelasi'. A number that belongs to
    the label ('Pasal 25', 'Article 4(2)') stays."""
    import re
    words = label.split()
    while len(words) > 1 and re.fullmatch(r"\d{1,2}[a-z]?(?:[.,&]\d{1,2}[a-z]?)*[,&]?", words[-1]) \
            and not re.fullmatch(r"(?i)pasal|article|ayat|pph|no\.?|nomor", words[-2]):
        words.pop()
    return " ".join(words)


def source_label(quote: str, lang="id"):
    """The label part of a source line in the chosen language (Gail 28 Oct, item 4).

    Bilingual reports print "Indonesian label  amounts  English label" on one line: the Indonesian
    label is the text before the first amount, the English label the text after the last one. A line
    without an English part (Indonesian-only report) is returned in full. The full line is always
    kept next to it in the downloads, so nothing of the quote is lost."""
    import re
    q = re.sub(r"\([^()]*\b[Rr]p\s?[\d.,]+[^()]*\)", " ", (quote or "").strip())     # "(2020 : Rp2.995.582.842)"
    q = re.sub(r"\b[Rr]p\s?\d[\d.,]*", " ", q)                                      # an allowance quoted in the label
    q = re.sub(r"\s+", " ", q).strip()
    hits = list(re.finditer(AMOUNT, q))
    if not hits:
        return q
    left = _drop_note_refs(q[:hits[0].start()].strip())
    right = re.sub(r"^(-\s+)+", "", q[hits[-1].end():].strip()).strip()
    left = left.strip(" /")
    if lang == "en":
        return right or left or q
    return left or q


def checklist_rows(r: Result, lang="id"):
    """The PDF / Excel checklist (Gail 28 Oct: confirmation moves from the app to the report).

    One row per review item with the value as read, its pages and its source line, so the user can
    open the page and tick Matches / Does not match."""
    by = {(v.field, v.column): v for v in r.extraction.values}
    fy = getattr(r.extraction, "fiscal_year", None)
    years = {"t": str(fy) if fy else "t", "t1": str(fy - 1) if fy else "t−1"}
    rows = []
    for n, i in enumerate(review_items(r, lang), 1):
        kind, rest = i["key"].split(":", 1)
        f = rest.split(":")[0] if kind == "in" else (rest.split(":")[1].split(",")[0] if rest.count(":") >= 2 else "")
        cols = [i["column"]] if i["column"] in ("t", "t1") else ["t", "t1"]
        vals = [by.get((f, c)) for c in cols]
        value = " / ".join(amount(v.value, lang) if v is not None and v.value is not None else "—" for v in vals)
        pages = ", ".join(str(p) for p in sorted({p for v in vals if v for p in v.pages})) or "—"
        quote = next((v.quotes[0] for v in vals if v is not None and v.quotes), "")
        year = years.get(i["column"]) or t("col.both", lang, a=years["t"], b=years["t1"])
        rows.append({"no": n, "key": i["key"], "item": i["title"], "year": year, "value": value, "pages": pages,
                     "why": i["why"], "source": source_label(quote, lang), "quote": quote,
                     "assumed": any(v is not None and v.status == "ASSUMED" for v in vals)})
    return rows


def fmt_push(v, lang="id"):
    """A push with its sign, e.g. +0,183 / −0.157."""
    return fmt_number(v, lang, 3, sign=True)
