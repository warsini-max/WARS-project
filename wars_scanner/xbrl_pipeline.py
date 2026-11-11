"""XBRL + PDF -> engine inputs -> M-score (stage-4 freeze candidate; not wired into the app yet).

Face-statement figures come from the XBRL instance, verified against the PDF (`xbrl_reader`). Note items come
from the existing PDF notes reader (`pipeline.run` + `apply_provisional`, the provisional rules approved by Gail
on 28 Oct 2026), anchored by XBRL:
  - PPh 25/29 from the tax table whose total equals the XBRL TaxesPayable pair, else D-03g proxy (31 Oct 2026);
  - PPE depreciation (owned + ROU): the PDF reader's figure when read, cross-checked with the XBRL movement table;
    XBRL only -> REVIEW; conflict -> PDF figure, REVIEW (XBRL additions can include FX, impairment, modifications);
  - investment property on the XBRL face with no depreciation read for a year -> score held (P8), unless the
    notes state the fair-value model;
  - intangible assets on the XBRL face with amortisation not read -> amortisation line read from the notes
    (REVIEW), else the provisional UNDISCLOSED rule;
  - bearer plants / mining properties / concession rights on the XBRL face (rule 4, Gail 30 Oct 2026): their
    depreciation/amortisation is non-PPE; if not read, the year is marked ASSUMED (provisional rule).
Nothing is ever filled with 0 except under an approved rule, which is then listed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pypdfium2 as pdfium

from . import engine, pipeline, xbrl_reader as X

WARN_BAND = 0.15
THRESHOLD = -1.78
FACE_MAP = {  # engine field -> xbrl_reader field
    "revenue": "revenue", "cost_of_goods_sold": "cost_of_goods_sold",
    "selling_general_administrative_expenses": "selling_general_administrative_expenses",
    "accounts_receivable": "accounts_receivable", "total_assets": "total_assets", "current_assets": "current_assets",
    "current_liabilities": "current_liabilities", "total_liabilities": "total_liabilities",
    "long_term_debt": "long_term_debt", "current_maturities_long_term_debt": "current_maturities_long_term_debt",
    "cash_and_cash_equivalents": "cash_and_cash_equivalents", "net_income": "net_income",
    "cash_flow_from_operations": "cash_flow_from_operations",
}
NON_PPE_CONCEPTS = {"InvestmentProperties": "investment property", "PlantationAssetsMature": "bearer plants",
                    "MiningProperties": "mining properties", "TollRoadConcessionRights": "concession rights",
                    # mining long-term costs, workbook M-06 group 3 (XBRL stage 8 finding, ITMG 2025)
                    "NonCurrentDeferredStrippingCosts": "deferred stripping costs",
                    "DeferredChargesOnExplorationAndDevelopmentExpenditures": "deferred exploration and development"}
STRICT_CLASSES = ("NonCurrentDeferredStrippingCosts", "DeferredChargesOnExplorationAndDevelopmentExpenditures")


@dataclass
class Item:
    field: str
    column: str
    value: object
    status: str          # FOUND / REVIEW / ASSUMED / UNDISCLOSED / NOT FOUND / NOT ASSESSED
    source: str
    note: str = ""


@dataclass
class Result:
    gate: list
    inputs: dict
    calc: dict
    items: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    held: list = field(default_factory=list)       # reasons the score is withheld
    tax: dict = field(default_factory=dict)
    xbrl: dict = field(default_factory=dict)
    pdf: object = None                             # pipeline.Result of the PDF reader (metadata, evidence pages)

    @property
    def m_score(self):
        m = self.calc.get("m_score_B")
        return m if isinstance(m, (int, float)) and not self.held and not self.gate else None


def pdf_pages(path) -> list:
    doc = pdfium.PdfDocument(path)
    return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]


def _xbrl_dep(xr, col):
    f = xr["fields"][col]
    own, tot, rou_tab = (f[n].value for n in ("ppe_depreciation_owned", "ppe_table_depreciation_total", "rou_table_depreciation"))
    if own is None:
        return None
    rou = rou_tab if rou_tab is not None else (tot - own if tot is not None and tot > own else 0)
    return own + (rou or 0)


ALLOC_HEAD = re.compile(r"(?i)(penyusutan|beban penyusutan)[^.]{0,40}?(dialokasikan|dibebankan|pembebanan)|"
                        r"pembebanan penyusutan|depreciation (expense )?(was|is|were)? ?(allocated|charged)")
FX_LINE = re.compile(r"(?i)selisih kurs|penjabaran|exchange difference|translation")
AMORT_ROW = re.compile(r"(?i)\bamorti[sz]a(si|tion)\b")   # intangible amortisation inside a depreciation table (EDGE)


def allocation_total(lines, pages, own_t, own_t1, all_t=None, all_t1=None):
    """PPE depreciation allocation table ('Penyusutan dialokasikan sebagai berikut'): the first line whose (t, t-1)
    pair equals the sum of the lines above it. Translation differences inside the table are not depreciation and are
    taken out. Accepted only when both years lie within 15% of the XBRL owned-asset movement, or of owned + ROU
    (tables that include the ROU class, ASII).
    Returns dict(t, t1, fx_t, fx_t1, page) or None."""
    if not own_t or not own_t1:
        return None
    by_page = {}
    for p, ln, n in lines:
        by_page.setdefault(p, []).append(ln)
    for p, pl in by_page.items():
        if p in pages["bs"] or p in pages["pl"]:
            continue
        for i, ln in enumerate(pl):
            if not ALLOC_HEAD.search(ln) or re.search(r"(?i)hak guna|right.of.use|aset takberwujud|intangible|properti investasi", ln):
                continue
            rows, fx = [], [0, 0]
            for k in range(i + 1, min(i + 18, len(pl))):
                lab = pl[k] + " " + (pl[k + 1] if k + 1 < len(pl) else "")
                am = [abs(x) for x in X._amounts(re.sub(r"(?i)\(?\s*(catatan|note)\s*\d{1,2}[a-z]?\s*\)?", " ", pl[k]))]
                if len(am) < 2 or X._is_year_header(am, pl[k]):
                    continue
                pair = am[-2:]
                if len(rows) >= 2 and all(abs(sum(r[j] for r in rows) - pair[j]) <= 1 for j in (0, 1)):
                    t, t1 = pair[0] - fx[0], pair[1] - fx[1]
                    near = lambda a, b: b and abs(a - b) <= 0.15 * b
                    if (near(pair[0], own_t) and near(pair[1], own_t1)) or (near(pair[0], all_t) and near(pair[1], all_t1)):
                        return {"t": float(t), "t1": float(t1), "fx_t": float(fx[0]), "fx_t1": float(fx[1]), "page": p,
                                "total": (float(pair[0]), float(pair[1]))}
                    break
                rows.append(pair)
                here = pl[k] + " " + (pl[k - 1] if k - 1 > i and not [x for x in X._amounts(pl[k - 1]) if x] else "")
                if FX_LINE.search(pl[k]) or (AMORT_ROW.search(here) and not re.search(r"(?i)penyusutan|depreciation", here)):
                    fx = [fx[0] + pair[0], fx[1] + pair[1]]
    return None


AMORT_LINE = re.compile(r"(?i)^\s*(beban\s+)?amorti[sz]a(si|tion)\b(?!.*(akumulasi|accumulated|biaya transaksi|transaction cost|"
                        r"diskonto|discount|premi|premium|ditangguhkan|deferred|sewa|lease|properti|biaya perolehan diamortisasi|amortised cost))")


def _note_ref(lines, pages, value_t, value_t1):
    """Note number printed on the face line of an item (e.g. 'Aset takberwujud - neto 12,28 16.015 14.229')."""
    for p, ln, n in lines:
        if p in pages["bs"] and round(value_t) in n and round(value_t1) in n:
            m = re.search(r"\s(\d{1,2})(?:[a-z])?(?:\s*,\s*\d{1,2}[a-z]?)*\s+[\d(]", ln)
            return m.group(1) if m else None
    return None


def amortisation_from_notes(xr, lines, pages):
    """Intangible amortisation for t and t-1 from one printed line: 'Amortisasi (Catatan N) a b' with N the
    intangible note on the face, or an 'Amortisasi' line in the intangible note itself. REVIEW (single source)."""
    f = xr["fields"]
    inst_vals = [xr["_inst"].plain("IntangibleAssetsOtherThanGoodwill", c, "i") for c in ("t", "t1")]
    if not all(v for v in inst_vals):
        return None
    ref = _note_ref(lines, pages, *inst_vals)
    for p, ln, n in lines:
        if p in pages["bs"] or p in pages["pl"] or not AMORT_LINE.search(ln):
            continue
        refs = re.findall(r"(?i)(?:catatan|note)\s*(\d{1,2})", ln)
        am = [x for x in X._amounts(re.sub(r"(?i)\(?\s*(lihat\s+)?(catatan|note|see note)\s*\d{1,2}[a-z]?\s*\)?", " ", ln)) if x]
        if len(am) < 2:
            continue
        if ref and refs and ref in refs:
            return {"t": float(am[-2]), "t1": float(am[-1]), "page": p, "line": ln.strip()[:100]}
    return None


# XBRL stage 6, finding D (PURI, DIVA): amortisation disclosed only in a sentence of the intangible note,
# 'Beban amortisasi ... masing-masing sebesar Rp101.100.000 dan Rp103.756.250' / '... amounted to Rp X and Rp Y'
AMORT_SENT = re.compile(
    r"(?i)\bamorti[sz]a(?:si|tion)\b(?P<mid>[^.]{0,200}?)(?:sebesar|amounted to|amounting to|of)\s*"
    r"(?:Rp|IDR|US\$|USD|\$)?\s?(?P<a>\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<ua>triliun|miliar|juta|ribu|trillion|billion|million|thousand)?"
    r"\s*(?:dan|and)\s*(?:Rp|IDR|US\$|USD|\$)?\s?(?P<b>\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*"
    r"(?P<ub>triliun|miliar|juta|ribu|trillion|billion|million|thousand)?")
AMORT_SENT_NOT = re.compile(r"(?i)akumulasi|accumulated|biaya transaksi|transaction cost|diskonto|discount|premi|premium|"
                            r"obligasi|bond|ditangguhkan|deferred|sewa|lease|properti|property|biaya perolehan diamortisasi|"
                            r"amortised cost|amortized cost|pinjaman|loan")
INTANGIBLE_PAGE = re.compile(r"(?i)aset tak ?berwujud|intangible|perangkat lunak|software")
UNIT_WORD = {"ribu": 1e3, "thousand": 1e3, "juta": 1e6, "million": 1e6, "miliar": 1e9, "billion": 1e9,
             "triliun": 1e12, "trillion": 1e12}


def _sent_amount(txt, unit):
    g = re.split(r"[.,]", txt)
    if len(g) > 1 and all(len(x) == 3 for x in g[1:]):
        v = float("".join(g))
    else:
        v = float(txt.replace(",", "."))
    return v * UNIT_WORD.get((unit or "").lower(), 1)


YEAR_LIKE = re.compile(r"(?:19|20)\d\d")


def amortisation_from_sentence(pages_txt, carrying, scale, skip_pages=()):
    """Amortisation (t, t-1) from one sentence on a page about intangible assets. The amounts are in Rupiah (or the
    unit word that follows); they are converted to the statement unit and kept only if plausible against the
    intangible carrying amounts (in the statement unit). Two plausible readings, or none, -> None (no guess).
    Never on the face pages (skip_pages, 1-based): a bilingual face line interleaves the two languages and once gave
    'accumulated amortization of 2022 dan Rp635.142.745' (XBRL stage 7, TNCA). A year-like figure (2022) is never
    an amount, and 'akumulasi/accumulated' just before 'amortisasi' marks the carrying-amount wording."""
    cap = 2 * sum(abs(c) for c in carrying if c)
    if not cap:
        return None
    skip = set(skip_pages or ())
    for i, t in enumerate(pages_txt):
        if i + 1 in skip or not INTANGIBLE_PAGE.search(t):
            continue
        flat = re.sub(r"\s+", " ", t)
        for m in AMORT_SENT.finditer(flat):
            if AMORT_SENT_NOT.search(m.group("mid")) or AMORT_SENT_NOT.search(flat[max(0, m.start() - 25):m.start()]):
                continue
            if any(YEAR_LIKE.fullmatch(m.group(g)) and not m.group("u" + g) for g in ("a", "b")):
                continue
            a, b = _sent_amount(m.group("a"), m.group("ua")), _sent_amount(m.group("b"), m.group("ub"))
            if m.group("ua") or m.group("ub"):
                cands = {(a / scale, b / scale)}
            else:
                cands = {(a, b), (a / scale, b / scale)}
            ok = [c for c in cands if 0 < c[0] <= cap and 0 < c[1] <= cap and c[0] >= 1 and c[1] >= 1]
            if len(ok) == 1:
                return {"t": round(ok[0][0]), "t1": round(ok[0][1]), "page": i + 1, "line": m.group(0)[:100]}
    return None


def amortisation_from_movement(lines, carrying, pages):
    """Intangible amortisation (t, t-1) from the intangible movement tables, anchored by the XBRL carrying amounts
    (XBRL stage 7, finding 2: BIPI, SIPD). Both years must be read, else None (no guess)."""
    if not carrying or not all(carrying):
        return None
    mt, mt1 = movement_charge(lines, carrying[0], pages, True), movement_charge(lines, carrying[1], pages, True)
    if mt and mt1:
        return {"t": mt[0], "t1": mt1[0], "page": mt[1], "line": "movement table"}
    yc = year_column_charge(lines, carrying, pages)
    if yc:
        return {"t": yc[0], "t1": yc[1], "page": yc[2][0], "line": "movement table"}
    return None


DEFERRED_CONCEPTS = ("OtherDeferredCharges", "DeferredChargesOnLandrights")


def deferred_charge_amortisation(lines, inst, pages):
    """Amortisation (t, t-1) of deferred charges / land rights on the XBRL face (workbook M-06 group 3, long-term
    costs) from their movement tables (XBRL stage 7, finding 2: FAST). Every class present must be read, both
    years; else None and the provisional rule stays. Returns dict(t, t1, pages, classes) or None."""
    out = {"t": 0.0, "t1": 0.0, "pages": [], "classes": []}
    for cn in DEFERRED_CONCEPTS:
        pair = [inst.plain(cn, c, "i") for c in ("t", "t1")]
        if not any(pair):
            continue
        if not all(pair):
            return None
        mt, mt1 = movement_charge(lines, pair[0], pages, True), movement_charge(lines, pair[1], pages, True)
        if mt and mt1:
            got = (mt[0], mt1[0], [mt[1]])
        else:
            yc = year_column_charge(lines, pair, pages)
            if not yc:
                return None
            got = yc
        out["t"] += got[0]
        out["t1"] += got[1]
        out["pages"] = sorted(set(out["pages"]) | set(got[2]))
        out["classes"].append(cn)
    return out if out["classes"] else None


def run(instance_source, pdf_path, ticker: str | None = None) -> Result:
    pages_txt = pdf_pages(pdf_path)
    xr = X.read(instance_source, pages_txt, ticker)
    inst = X.read_instance(instance_source)
    xr["_inst"] = inst
    lines = X.pdf_lines(pages_txt)
    items, warnings, held = [], [], []
    gate = list(xr["gate"])
    pr = pipeline.apply_provisional(pipeline.run(pdf_path, ticker or "UPLOAD"))
    p = dict(pr.inputs)
    p.update({"ticker": ticker or inst.dei.get("EntityCode", "UPLOAD"),
              "fiscal_year_t": int((inst.dei.get("CurrentPeriodEndDate") or "0000")[:4] or 0) or p.get("fiscal_year_t"),
              "statement_type": "Consolidated" if re.search(r"grup|group", inst.dei.get(
                  "WhetherTheFinancialStatementsAreOfAnIndividualEntityOrAGroupOfEntities", ""), re.I) else "Separate",
              "reporting_currency": "USD" if re.search(r"USD|dollar", inst.dei.get("DescriptionOfPresentationCurrency", ""), re.I) else "IDR",
              "unit_scale": {1: "Full", 10**3: "Thousands", 10**6: "Millions", 10**9: "Billions"}[inst.scale]})
    pdf_status = {(v.field, v.column): v.status for v in pr.extraction.values}

    # ---- face statements: XBRL (verified); not tagged -> PDF reader value as REVIEW; else missing
    for c in ("t", "t1"):
        for ef, xf in FACE_MAP.items():
            fx = xr["fields"][c][xf]
            if fx.value is not None and fx.status in ("FOUND", "REVIEW"):
                p[f"{ef}_{c}"] = abs(fx.value) if ef not in ("net_income", "cash_flow_from_operations") else fx.value
                items.append(Item(ef, c, p[f"{ef}_{c}"], fx.status, "XBRL " + "+".join(fx.concepts), "; ".join(fx.notes)))
            elif pr.inputs.get(f"{ef}_{c}") is not None:
                items.append(Item(ef, c, pr.inputs[f"{ef}_{c}"], "REVIEW", "PDF reader (not available from XBRL)",
                                  "; ".join(fx.notes)))
            else:
                p.pop(f"{ef}_{c}", None)
                items.append(Item(ef, c, None, "NOT FOUND", "", "; ".join(fx.notes)))
        # PPE + ROU (D-08)
        ppe, rou = xr["fields"][c]["ppe_face"], xr["fields"][c]["rou_assets_net"]
        if ppe.value is not None:
            p[f"property_plant_equipment_net_{c}"] = ppe.value + (rou.value or 0)
            p[f"rou_assets_net_{c}"] = rou.value if rou.value is not None else pr.inputs.get(f"rou_assets_net_{c}", 0)
            st = "FOUND" if ppe.status == "FOUND" and rou.status in ("FOUND", "NOT FOUND") and rou.value is not None else "REVIEW"
            items.append(Item("property_plant_equipment_net", c, p[f"property_plant_equipment_net_{c}"], st,
                              "XBRL PPE" + (" + ROU" if rou.value else ""),
                              # the ROU notes are about the ROU line, not the PPE line (XBRL stage 8 finding, TRIN)
                              "; ".join(ppe.notes + [f"right-of-use assets: {n}" for n in rou.notes])))
        else:
            p.pop(f"property_plant_equipment_net_{c}", None)
            items.append(Item("property_plant_equipment_net", c, None, "NOT FOUND", ""))

    # ---- taxes payable (D-03 / D-03g)
    tax = xr["tax"]
    for c in ("t", "t1"):
        if tax.get(c) is not None:
            p[f"taxes_payable_{c}"] = tax[c]
            items.append(Item("taxes_payable", c, tax[c], tax["status"],
                              "D-03g PENDEKATAN (total taxes payable)" if tax.get("proxy") else
                              f"{'face' if tax.get('face') else 'tax note'} p{tax.get('page')}",
                              "; ".join(tax["notes"])))
        else:
            p.pop(f"taxes_payable_{c}", None)
            items.append(Item("taxes_payable", c, None, "NOT FOUND", "", "; ".join(tax["notes"])))

    # ---- PPE depreciation (owned + ROU)
    rou_untagged = any(f.get("family") == "rou" for f in xr.get("face_findings") or [])
    own = {c: xr["fields"][c]["ppe_depreciation_owned"].value for c in ("t", "t1")}
    xall = {c: _xbrl_dep(xr, c) for c in ("t", "t1")}
    alloc = allocation_total(lines, xr["face_pages"], own["t"], own["t1"], xall["t"], xall["t1"])
    for c in ("t", "t1"):
        pdf_dep = pr.inputs.get(f"ppe_depreciation_disclosed_{c}")
        x_dep = _xbrl_dep(xr, c)
        if alloc and x_dep is not None:
            tot_c = alloc["total"][0 if c == "t" else 1]
            with_rou = abs(tot_c - x_dep) < abs(tot_c - own[c])   # the table covers owned + ROU (ASII, ARII)
            a_dep = alloc[c] if with_rou else x_dep - own[c] + alloc[c]
            same = abs(tot_c - (x_dep if with_rou else own[c])) <= 1
            fxv = alloc["fx_" + c]
            if pdf_dep is not None and abs(pdf_dep - a_dep) <= 1 and (same or abs(pdf_dep - x_dep) <= 1):
                st, src, note = "FOUND", "PDF notes = allocation table", ""
            elif pdf_dep is not None and abs(pdf_dep - a_dep) <= 1:
                st, src, note = "REVIEW", "PDF notes = allocation table", f"XBRL movement table gives {x_dep:,.0f}"
            elif same and not fxv and (pdf_dep is None or abs(pdf_dep - x_dep) <= 1):
                pdf_dep, st, src, note = x_dep, "FOUND", "XBRL movement = PDF allocation table", ""
            else:
                note = (f"allocation table p{alloc['page']}" + (f", translation difference {fxv:,.0f} taken out" if fxv else "")
                        + (f"; XBRL movement {(x_dep if with_rou else own[c]):,.0f}" if not same else "")
                        + (f"; PDF reader {pdf_dep:,.0f}" if pdf_dep is not None else ""))
                pdf_dep, st, src = a_dep, "REVIEW", "PDF allocation table"
        elif pdf_dep is not None and x_dep is not None and abs(pdf_dep - x_dep) <= 1:
            st, src, note = "FOUND", "PDF notes = XBRL movement", ""
        elif pdf_dep is not None and x_dep is not None:
            st, src, note = "REVIEW", "PDF notes", f"XBRL movement table gives {x_dep:,.0f}"
        elif pdf_dep is not None:
            st, src, note = pdf_status.get(("ppe_depreciation_disclosed", c), "REVIEW"), "PDF notes", "no XBRL movement table"
        elif x_dep is not None:
            pdf_dep, st, src, note = x_dep, "REVIEW", "XBRL movement table only", "not read from the PDF"
        else:
            st, src, note = "NOT FOUND", "", ""
        if pdf_dep is not None:
            old = p.get(f"ppe_depreciation_disclosed_{c}")
            p[f"ppe_depreciation_disclosed_{c}"] = pdf_dep
            if old is None or abs(old - pdf_dep) > 1 or p.get(f"depreciation_amortization_total_{c}") is None:
                am = p.get(f"amortization_intangibles_{c}") or 0
                npp = p.get(f"depreciation_amortization_non_ppe_{c}") or 0
                p[f"depreciation_amortization_total_{c}"] = pdf_dep + am + npp
        if st == "FOUND" and rou_untagged:
            st, note = "REVIEW", "right-of-use assets on the face are not tagged in XBRL; their depreciation may be missing"
        items.append(Item("ppe_depreciation_disclosed", c, pdf_dep, st, src, note))

    # ---- intangible amortisation: XBRL says intangibles exist, PDF reader did not read the amount
    am_x = None
    for c in ("t", "t1"):
        if p.get(f"amort_status_{c}") in ("UNDISCLOSED", None) or pdf_status.get(("amortization_intangibles", c)) in (
                "NOT ASSESSED", "UNDISCLOSED", "ASSUMED"):
            am_x = am_x or amortisation_from_notes(xr, lines, xr["face_pages"]) or amortisation_from_sentence(
                pages_txt, [inst.plain("IntangibleAssetsOtherThanGoodwill", cc, "i") for cc in ("t", "t1")], inst.scale,
                set(xr["face_pages"].get("bs", [])) | set(xr["face_pages"].get("pl", []))) or \
                amortisation_from_movement(lines, [inst.plain("IntangibleAssetsOtherThanGoodwill", cc, "i")
                                                   for cc in ("t", "t1")], xr["face_pages"])
            if am_x:
                old = p.get(f"amortization_intangibles_{c}") or 0
                p[f"amortization_intangibles_{c}"] = am_x[c]
                p[f"amort_status_{c}"] = ""
                p[f"depreciation_amortization_total_{c}"] = (p.get(f"depreciation_amortization_total_{c}") or 0) - old + am_x[c]
                items.append(Item("amortization_intangibles", c, am_x[c], "REVIEW",
                                  f"PDF p{am_x['page']}: {am_x['line']}", "single printed line or sentence; one source"))
                continue
        st = pdf_status.get(("amortization_intangibles", c))
        if p.get(f"amortization_intangibles_{c}") is None or st in ("NOT SEARCHED", "NOT ASSESSED", None):
            has_int = any(inst.plain("IntangibleAssetsOtherThanGoodwill", cc, "i") for cc in ("t", "t1"))
            # provisional rule (Gail 28 Oct 2026): not read -> 0; intangibles on the XBRL face -> UNDISCLOSED
            p[f"amortization_intangibles_{c}"] = 0
            p[f"amort_status_{c}"] = "UNDISCLOSED" if has_int else ""
            st = "UNDISCLOSED" if has_int else "ASSUMED"
            items.append(Item("amortization_intangibles", c, 0, st,
                              "intangibles on the XBRL face, amount not read" if has_int else "no intangibles on the XBRL face",
                              "provisional rule (28 Oct 2026)"))
            continue
        items.append(Item("amortization_intangibles", c, p.get(f"amortization_intangibles_{c}"), st or "ASSUMED",
                          "PDF notes / provisional rule"))

    # ---- non-PPE (Q2, rule 4, P8): classes from the XBRL face; amounts from the PDF reader or the movement table
    ev = pr.extraction.non_ppe_evidence or {}
    pdf_read = ev.get("amounts_read", {}) or {}
    fv = _ip_fair_value(lines)
    classes = {cn: [inst.plain(cn, c, "i") for c in ("t", "t1")] for cn in NON_PPE_CONCEPTS}
    classes = {cn: v for cn, v in classes.items() if any(v)}
    dc = deferred_charge_amortisation(lines, inst, xr["face_pages"]) if not classes else None
    for i, c in enumerate(("t", "t1")):
        total, unread, srcs = 0.0, [], []
        for cn, vals in classes.items():
            label = NON_PPE_CONCEPTS[cn]
            if cn == "InvestmentProperties" and fv:
                srcs.append("investment property at fair value: 0")
                continue
            if cn == "InvestmentProperties" and c in pdf_read:
                total += pdf_read[c]
                srcs.append(f"investment property {pdf_read[c]:,.0f} (PDF reader)")
                continue
            mv = movement_charge(lines, vals[i], xr["face_pages"], cn in STRICT_CLASSES)
            if mv is not None:
                total += mv[0]
                srcs.append(f"{label} {mv[0]:,.0f} (movement table p{mv[1]})")
            else:
                unread.append(label)
        if not classes and dc and not pdf_read.get(c):
            # deferred charges read from their movement tables; other classes not on the XBRL face (REVIEW)
            amt = dc[c]
            p[f"depreciation_amortization_non_ppe_{c}"], p[f"non_ppe_status_{c}"] = amt, "PARTIAL_UNDISCLOSED"
            items.append(Item("depreciation_amortization_non_ppe", c, amt, "REVIEW",
                              f"deferred charges {amt:,.0f} (movement table p{', p'.join(map(str, dc['pages']))})",
                              "single source"))
        elif not classes:
            amt = pdf_read.get(c, 0.0)
            p[f"depreciation_amortization_non_ppe_{c}"], p[f"non_ppe_status_{c}"] = amt, "PARTIAL_UNDISCLOSED"
            items.append(Item("depreciation_amortization_non_ppe", c, amt, "ASSUMED",
                              "no non-PPE class on the XBRL face; amount read" if amt else "no non-PPE class on the XBRL face",
                              "provisional rule (28 Oct 2026)"))
        elif "investment property" in unread:
            p.pop(f"depreciation_amortization_non_ppe_{c}", None)
            p[f"non_ppe_status_{c}"] = ""
            held.append(f"investment property on the face and no depreciation read for {c} (P8)")
            items.append(Item("depreciation_amortization_non_ppe", c, None, "NOT ASSESSED", "; ".join(srcs),
                              "unread: " + ", ".join(unread)))
        else:
            p[f"depreciation_amortization_non_ppe_{c}"] = total
            p[f"non_ppe_status_{c}"] = "ALL_DISCLOSED" if not unread else "PARTIAL_UNDISCLOSED"
            items.append(Item("depreciation_amortization_non_ppe", c, total, "REVIEW" if not unread else "ASSUMED",
                              "; ".join(srcs), ("unread (counted 0): " + ", ".join(unread)) if unread else ""))
        dep = p.get(f"ppe_depreciation_disclosed_{c}")
        if dep is not None and p.get(f"depreciation_amortization_non_ppe_{c}") is not None:
            p[f"depreciation_amortization_total_{c}"] = dep + (p.get(f"amortization_intangibles_{c}") or 0) + \
                p[f"depreciation_amortization_non_ppe_{c}"]

    calc = engine.calculate(p)
    m = calc.get("m_score_B")
    if isinstance(m, (int, float)) and abs(m - THRESHOLD) <= WARN_BAND:
        warnings.append(f"M = {m:.3f} lies within {WARN_BAND} of {THRESHOLD}" +
                        (": the D-03g proxy for taxes payable can change the side of the threshold" if tax.get("proxy") else ""))
    missing = [f"{i.field}_{i.column}" for i in items if i.status in ("NOT FOUND", "NOT ASSESSED")]
    if missing:
        held.append("not found: " + ", ".join(missing))
    return Result(gate, p, calc, items, warnings, held, tax, xr, pr)


IP_FV = re.compile(r"(?i)properti investasi[^.]{0,80}?(dicatat|diukur|dinyatakan|disajikan)[^.]{0,60}?nilai wajar|"
                   r"investment propert[^.]{0,80}?(carried|measured|stated|recorded)[^.]{0,40}?at fair value|"
                   r"properti investasi[^.]{0,40}?model nilai wajar|investment propert[^.]{0,40}?fair value model")
IP_COST = re.compile(r"(?i)properti investasi(?! dalam penyelesaian)[^.]{0,60}?(dicatat|dinyatakan|diukur|disajikan) "
                     r"(sebesar|pada|berdasarkan) biaya perolehan[^.]{0,40}?(dikurangi|setelah dikurangi) akumulasi penyusutan")


def _ip_fair_value(lines) -> bool:
    """Fair-value model stated in the policy (ASII, KBAG, UNTR) or a fair-value-change column in the IP movement table
    (WOWS); a cost-model statement for completed investment property overrides (TOTL)."""
    text = re.sub(r"\s+", " ", " ".join(ln for _, ln, _ in lines))
    if IP_COST.search(text):
        return False
    return bool(IP_FV.search(text)) or bool(re.search(r"(?i)properti investasi.{0,600}?perubahan nilai wajar", text))


_SIGNED = re.compile(r"\(\s*\d{1,3}(?:[.,]\d{3})+\s*\)|\(\s*\d+\s*\)|-?\d{1,3}(?:[.,]\d{3})+|(?<![\w.,])\d+(?![\w.,])|(?<!\S)-(?!\S)")
YC_END = re.compile(r"(?i)^\s*(total|jumlah|nilai tercatat|carrying amount)\b")
YC_STOP = re.compile(r"^\s*\d{1,2}\.\s+[A-Z](?!.*\((?i:lanjutan|continued)\))")  # the next numbered note, not its continuation
YC_CHARGE = re.compile(r"(?i)amorti[sz]a(si|tion)|beban tahun berjalan|current year expense")
YC_NOT = re.compile(r"(?i)akumulasi|accumulated|penurunan nilai|impairment|biaya transaksi|transaction cost|diskonto|discount")


def _signed_pair(ln):
    """The last two amounts of a line, signed ('(4.745.528)' is negative); None if fewer than two."""
    lab = re.sub(r"(?i)\(\s*(catatan|note)\s*\d{1,2}[a-z]?\s*\)", " ", ln)
    toks = [m.group(0) for m in _SIGNED.finditer(lab)]
    vals = [0 if t.strip() == "-" else (-1 if t.startswith("(") else 1) * int(re.sub(r"[^\d]", "", t)) for t in toks]
    return vals[-2:] if len(vals) >= 2 else None


def _labelled(ln):
    return bool(re.search(r"[A-Za-z]{3}", _SIGNED.sub(" ", ln)))


def year_column_charge(lines, pair, pages):
    """Amortisation (t, t-1) of a class whose movement tables put the two years in columns and the movements in
    rows ('Saldo awal / Penambahan / Pengurangan / Amortisasi tahun berjalan / Saldo akhir', FAST deferred charges).
    pair: the XBRL carrying amounts (t, t-1). A table counts only when (1) every 'Saldo awal ... Saldo akhir' run
    rolls in both columns from its labelled rows, (2) its run ends add up to its 'Total' line and (3) the 'Total'
    lines of the tables used add up to the XBRL pair, one way only. Charge rows are labelled amortisation, never
    accumulated amortisation or impairment. Returns (t, t1, pages) or None. Single source: REVIEW."""
    from itertools import combinations
    if not pair or any(v is None for v in pair):
        return None
    target = [round(abs(pair[0])), round(abs(pair[1]))]
    seq = [(p, ln) for p, ln, _ in lines if p not in pages["bs"] and p not in pages["pl"]]
    tables = []
    for k, (p, ln) in enumerate(seq):
        tot = _signed_pair(ln) if YC_END.search(ln) else None
        if not tot or not any(tot):
            continue
        j, block = k - 1, []
        while j >= 0 and k - j <= 60 and not YC_STOP.search(seq[j][1]) and not (
                YC_END.search(seq[j][1]) and _signed_pair(seq[j][1])):
            block.append(seq[j][1])
            j -= 1
        block = block[::-1]
        runs, cur, ok = [], None, True
        for r in block:
            if re.match(r"(?i)\s*(saldo awal|opening balance|beginning balance)", r):
                cur = {"begin": _signed_pair(r), "rows": [], "charge": [0, 0]}
                ok = ok and cur["begin"] is not None
                continue
            if cur is None:
                continue
            if re.match(r"(?i)\s*(saldo akhir|ending balance|closing balance)", r):
                end = _signed_pair(r)
                if not end or not cur["begin"]:
                    ok = False
                    break
                rolled = [cur["begin"][c] + sum(x[c] for x in cur["rows"]) for c in (0, 1)]
                if any(abs(rolled[c] - end[c]) > 1 for c in (0, 1)):
                    ok = False
                    break
                runs.append((end, cur["charge"]))
                cur = None
                continue
            v = _signed_pair(r)
            if v is None or not _labelled(r):
                continue                    # unlabelled subtotal ('646.609.950 588.010.852') or a label-only line
            cur["rows"].append(v)
            if YC_CHARGE.search(r) and not YC_NOT.search(r):
                cur["charge"] = [cur["charge"][c] + abs(v[c]) for c in (0, 1)]
        if not ok or not runs or cur is not None or not any(any(ch) for _, ch in runs):
            continue
        ends = [sum(e[c] for e, _ in runs) for c in (0, 1)]
        if any(abs(abs(ends[c]) - abs(tot[c])) > 1 for c in (0, 1)):
            continue
        tables.append(((abs(tot[0]), abs(tot[1])), [sum(ch[c] for _, ch in runs) for c in (0, 1)], p))
    hits = []
    for n in range(1, min(3, len(tables)) + 1):
        for combo in combinations(tables, n):
            if all(abs(sum(t[0][c] for t in combo) - target[c]) <= 1 for c in (0, 1)):
                hits.append(combo)
    if len(hits) != 1:
        return None
    combo = hits[0]
    return (float(sum(t[1][0] for t in combo)), float(sum(t[1][1] for t in combo)), sorted({t[2] for t in combo}))


def movement_charge(lines, carrying, pages, strict=False):
    """Depreciation/amortisation for the year from a movement table, anchored by the XBRL carrying amount.

    The table is the one whose 'nilai buku / nilai tercatat' line ends with the carrying amount. Two layouts:
      A. movement columns (saldo awal | penambahan | ... | saldo akhir): the charge is the 'penambahan' figure of
         the accumulated-depreciation total row (or the sum of the category rows when no total row), checked by
         beginning + charge (+/- other columns) = end; the header must name the movement columns;
      B. classes across columns (ARII mining properties): the 'amortisasi/penyusutan tahun berjalan' line, last
         figure (the total column).
    Returns (charge, page) or None. Single source: REVIEW."""
    from itertools import product
    if not carrying:
        return None
    v = round(abs(carrying))
    book = re.compile(r"(?i)nilai (buku|tercatat)|jumlah tercatat|carrying|book value")
    # 'Akumulasi Accumulated / amortisasi amortisation': a bilingual heading wrapped over two lines (ITMG)
    acc = re.compile(r"(?i)akumulasi\s+(accumulated\s+)?(penyusutan|amortisasi)|"
                     r"accumulated\s+(akumulasi\s+)?(depreciation|amorti[sz]ation)")
    movement_head = re.compile(r"(?i)penambahan|additions?")
    year_line = re.compile(r"(?i)(penyusutan|amortisasi|beban penyusutan|beban amortisasi)\b.{0,40}(tahun|periode) berjalan|"
                           r"(depreciation|amorti[sz]ation) (during|for) the (year|period)|^\s*(penyusutan|amortisasi)\s*\(")
    by_page = {}
    for p, ln, n in lines:
        by_page.setdefault(p, []).append(ln)

    def transposed(block):
        """Rows are movements, columns are classes with the total last: the 'for the year' line, checked by
        (1) its class figures adding up to its total and (2) beginning total + charge = closing total."""
        yb = [r for r in block if year_line.search(r) and [x for x in X._amounts(r) if x]]
        if len(yb) != 1:
            return None
        k = block.index(yb[0])
        sb = [r for r in block[:k] if re.match(r"(?i)\s*(saldo awal|beginning)", r)]
        ends = [r for r in block[k + 1:] if re.match(r"(?i)\s*(jumlah|total|saldo akhir)", r)]
        ch = X._amounts(yb[0])
        if not sb or not ends or len(ch) < 2:
            return None
        cross = abs(sum(ch[:-1]) - ch[-1]) <= 1
        roll = abs(X._amounts(sb[-1])[-1] + ch[-1] - X._amounts(ends[0])[-1]) <= 1
        return float(ch[-1]) if cross and roll and ch[-1] else None

    def balanced(nums):
        if len(nums) < 3:
            return None
        begin, charge, mids, end = nums[0], nums[1], nums[2:-1], nums[-1]
        if not charge:
            return None
        if strict and not begin and abs(charge - end) <= 1:
            return None     # the whole balance arrives in one year (asset first recognised or acquired): not a charge
        for signs in product((1, -1), repeat=len(mids)):
            if abs(begin + charge + sum(s * m for s, m in zip(signs, mids)) - end) <= 1:
                return charge
        return None

    for p, pl in by_page.items():
        if p in pages["bs"] or p in pages["pl"]:
            continue
        for i, ln in enumerate(pl):
            am = [x for x in X._amounts(ln) if x]
            if not (book.search(ln) and am and am[-1] == v):
                continue
            # block above the book line, up to the previous book line
            j, rows, head_j = i - 1, [], None
            while j >= 0 and i - j <= 30 and not book.search(pl[j]):
                joined = pl[j] + " " + (pl[j + 1] if j + 1 < len(pl) else "")
                if head_j is None and acc.search(joined):
                    head_j = j
                rows.append((j, pl[j]))
                j -= 1
            # B: a 'for the year' line (classes across columns)
            if head_j is None:
                ch = transposed([r for _, r in rows][::-1])
                if ch:
                    return ch, p
                continue
            block = [r for jj, r in rows if jj > head_j and r.strip()][::-1]     # blank lines are no rows (ITMG)
            if not block and len([x for x in X._amounts(pl[head_j]) if x]) >= 2:
                # the accumulated-amortisation heading is itself the (only, hence total) row (BIPI, ASII)
                header = " ".join(r for _, r in rows) + " " + " ".join(pl[max(0, j - 12):j + 1])
                ch = balanced(X._amounts(pl[head_j])) if movement_head.search(header) else None
                if ch:
                    return float(abs(ch)), p
                continue
            # B inside the accumulated block: rows are movements, the last column is the total (ARII mining)
            if any(year_line.search(r) for r in block):
                ch = transposed(block)
                if ch:
                    return ch, p
                # 'amortisasi (27,711) (2,220) - (29,931)' as the wrapped tail of a label-only 'Jumlah akumulasi' row
                # (SIPD) is not a 'for the year' line: only then fall through to the movement-column layout
                tails = [k for k, r in enumerate(block) if year_line.search(r)]
                if not all(k > 0 and re.match(r"(?i)\s*(jumlah|total)", block[k - 1])
                           and not [x for x in X._amounts(block[k - 1]) if x] for k in tails):
                    continue
            header = " ".join(r for _, r in rows) + " " + " ".join(pl[max(0, j - 12):j + 1])
            if not movement_head.search(header):
                continue
            # a total row whose label wraps ('Jumlah akumulasi' / 'amortisasi (27,711) (2,220) - (29,931)', SIPD)
            totals = [r if [x for x in X._amounts(r) if x] else (block[k + 1] if k + 1 < len(block) else r)
                      for k, r in enumerate(block) if re.match(r"(?i)\s*(jumlah|total|sub)", r)]
            if totals:
                ch = balanced(X._amounts(totals[-1]))
                if ch:
                    return float(abs(ch)), p
                continue
            if strict:
                # intangibles and deferred charges (XBRL stage 7 regression): adding up the category rows picked
                # wrong lines (ICBP class columns read as movement columns; EXCL '3G' in a label read as an amount).
                # One exception (XBRL stage 8, ITMG exploration): an unlabelled last row that rolls and equals, column
                # by column, the sum of the labelled rows above it is the total row.
                last = block[-1] if block else ""
                cats = [r for r in block[:-1] if re.search(r"[A-Za-z]{3}", r) and X._amounts(r)]
                tot = X._amounts(last)
                if block and not re.search(r"[A-Za-z]{3}", last) and cats and \
                        all(len(X._amounts(r)) == len(tot) for r in cats) and \
                        all(sum(X._amounts(r)[q] for r in cats) == tot[q] for q in range(len(tot))):
                    ch = balanced(tot)
                    if ch:
                        return float(abs(ch)), p
                continue
            valid = [balanced(X._amounts(r)) for r in block if not re.search(r"(?i)penurunan nilai|impairment", r)]
            valid = [x for x in valid if x]
            if valid:
                return float(sum(valid)), p
    return None
