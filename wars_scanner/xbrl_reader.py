"""IDX XBRL reader with PDF verification (stage-3 freeze candidate; not wired into the app).

Source of the face-statement figures: the issuer's IDX XBRL instance (taxonomy idx 2020). Every figure is
verified against the annual-report PDF (rule 7): a value is FOUND only when its pair (t, t-1) is printed on
one line of the PDF, or each component pair is. Otherwise REVIEW. A concept that is not tagged is never 0
(rule 1), except under the zero rule approved by Gail on 30 Oct 2026 (see `zero_allowed`).

Rules approved by Gail, 30 Oct 2026 10.42 (register 4e):
  1. bank-loan rule (temporary, formulated after seeing the stage-2 data): long-term bank loans and short-term
     bank loans tagged, no current maturities of bank loans -> REVIEW;
  2. face-completeness check, limited to lines the score uses: a face line whose label names a score item must
     pair with an XBRL fact of the matching concept family, otherwise REVIEW;
  3. untagged is not zero: 0 only if the XBRL subtotals add up and no such line exists on the PDF face;
  4. bearer plants / mining properties / concession rights presented outside PPE: their depreciation is non-PPE
     (handled where the notes are read; not in this module).
Note items that XBRL does not carry (PPh 25/29, non-PPE D&A, amortisation) are not read here.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from lxml import etree

XI = "http://www.xbrl.org/2003/instance"
XDI = "http://xbrl.org/2006/xbrldi"

CTX_T = ("CurrentYearInstant", "CurrentYearDuration")
CTX_T1 = ("PriorEndYearInstant", "PriorYearDuration")

LTD = ["LongTermBankLoans", "LongTermNon-BankFinancialInstitutionsLoan", "LongTermStepLoans", "LongTermSecuredLoans",
       "LongTermUnsecuredLoans", "LongTermLoansFromGovernmentOfTheRepublicOfIndonesia", "LongTermSubordinatedLoans",
       "LongTermConsumerFinancingPayables", "LongTermFinanceLeaseLiabilities", "LongTermNotesPayable",
       "LongTermMediumTermNotes", "LongTermBondsPayable", "LongTermSukuk", "LongTermSubordinatedBonds",
       "LongTermOtherBorrowings", "ConvertibleBonds"]
CMLTD = ["CurrentMaturitiesOfBankLoans", "CurrentMaturitiesOfNon-BankFinancialInstitutionsLoan",
         "CurrentMaturitiesOfSecuredLoans", "CurrentMaturitiesOfUnsecuredLoans", "CurrentMaturitiesOfStepLoans",
         "CurrentMaturitiesOfLoansFromGovernmentOfTheRepublicOfIndonesia", "CurrentMaturitiesOfSubordinatedLoans",
         "CurrentMaturitiesOfConsumerFinancingPayables", "CurrentMaturitiesOfFinanceLeaseLiabilities",
         "CurrentMaturitiesOfNotesPayable", "CurrentMaturitiesOfMediumTermNotes", "CurrentMaturitiesOfBondsPayable",
         "CurrentMaturitiesOfSukuk", "CurrentMaturitiesOfSubordinatedBonds", "CurrentMaturitiesOfOtherBorrowings"]
SGA = ["SellingExpenses", "GeneralAndAdministrativeExpenses"]
AR = ["TradeReceivablesThirdParties", "TradeReceivablesRelatedParties"]

# concept families for the face-completeness check (rule 2). Only score items.
FAMILY_LABEL = {
    "debt": re.compile(r"\b(pinjaman|utang bank|utang pembiayaan|liabilitas sewa|sewa guna|sewa pembiayaan|"
                       r"utang obligasi|obligasi|sukuk|wesel bayar|medium term notes?|bank loans?|borrowings?|"
                       r"lease liabilit|financing payables?|bonds payable)\b", re.I),
    "rou": re.compile(r"\b(hak[- ]guna|right[- ]of[- ]use)\b", re.I),
    "receivable": re.compile(r"\b(piutang usaha|trade receivables?)\b", re.I),
    "sga": re.compile(r"\b(beban penjualan|beban umum|beban usaha|beban pemasaran|selling expenses|"
                      r"general and administrative|operating expenses)\b", re.I),
}
FAMILY_CONCEPTS = {
    "debt": set(LTD) | set(CMLTD) | {"ShortTermBankLoans", "TrustReceiptsPayables"},
    "rou": {"RightOfUseAssets", "PropertyPlantAndEquipment"},
    "receivable": set(AR) | {"TradeReceivablesNet", "UnbilledReceivablesThirdParties",
                             "UnbilledReceivablesRelatedParties", "RetentionReceivablesThirdParties",
                             "RetentionReceivablesRelatedParties", "NonCurrentCustomerReceivablesThirdParties",
                             "NonCurrentCustomerReceivablesRelatedParties"},
    "sga": set(SGA),
}
# labels that look like a family but are not score items for it
NOT_FAMILY = {
    "debt": re.compile(r"\b(biaya pinjaman|beban bunga|pembayaran|penerimaan|proceeds|payments?|repayment|"
                       r"uang muka|advances?|piutang|investasi|investments?|laba|rugi|keuntungan|kerugian|gain|loss|selisih kurs|"
                       r"kepada|loans? to)\b", re.I),
    "rou": re.compile(r"\b(sertifikat|hak guna bangunan|hgb|building rights|liabilitas|liabilities|sewa|lease|uang muka|advances?)\b", re.I),
    "receivable": re.compile(r"\b(penyisihan|allowance|lain-lain|other)\b", re.I),
    "sga": re.compile(r"\b(laba|rugi|profit|loss|income|lain|lainnya|other)\b", re.I),
}


@dataclass
class Fact:
    concept: str
    ns: str
    ctx: str
    date: str
    dims: tuple
    unit: str | None
    decimals: str | None
    value: str


@dataclass
class Instance:
    facts: list
    dei: dict
    scale: int

    def plain(self, concept, column, kind):
        ctx = (CTX_T if column == "t" else CTX_T1)[0 if kind == "i" else 1]
        for f in self.facts:
            if f.concept == concept and f.ctx == ctx and not f.dims and f.unit and f.value not in ("", None):
                return float(f.value) / self.scale
        return None


@dataclass
class Field:
    name: str
    column: str
    value: float | None
    concepts: list
    status: str = "NOT FOUND"           # FOUND / REVIEW / NOT FOUND
    evidence: list = field(default_factory=list)   # (page, line)
    notes: list = field(default_factory=list)


def read_instance(source) -> Instance:
    """`source`: path or bytes of instance.xbrl, or of a zip that contains it. No DTD, no network, no entities."""
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".xbrl", ".xml")) and "taxonomy" not in n.lower()]
            if len(names) != 1:
                raise ValueError(f"expected one XBRL instance in the zip, found {names}")
            data = z.read(names[0])
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
    root = etree.fromstring(data, parser)
    ctx = {}
    for c in root.findall(f"{{{XI}}}context"):
        p = c.find(f"{{{XI}}}period")
        inst, end = p.find(f"{{{XI}}}instant"), p.find(f"{{{XI}}}endDate")
        dims = tuple(sorted((m.get("dimension").split(":")[-1], (m.text or "").split(":")[-1])
                            for m in c.iter(f"{{{XDI}}}explicitMember")))
        ctx[c.get("id")] = ((inst if inst is not None else end).text, dims)
    facts = []
    for el in root:
        if not isinstance(el.tag, str) or not el.get("contextRef"):
            continue
        ns, name = el.tag[1:].split("}")
        d, dims = ctx[el.get("contextRef")]
        facts.append(Fact(name, ns.rsplit('/', 1)[-1], el.get("contextRef"), d, dims, el.get("unitRef"), el.get("decimals"),
                          (el.text or "").strip()))
    dei = {f.concept: f.value for f in facts if f.ns == "dei"}
    lvl = dei.get("LevelOfRoundingUsedInFinancialStatements", "")
    scale = (10**9 if re.search(r"miliar|billion", lvl, re.I) else 10**6 if re.search(r"jutaan|million", lvl, re.I)
             else 10**3 if re.search(r"ribuan|thousand", lvl, re.I) else 1)
    return Instance(facts, dei, scale)


def document_gate(inst: Instance, ticker: str | None = None) -> list:
    """Reasons the instance cannot be used. Empty list = usable. Annual and audited only (BYAN lesson)."""
    d, out = inst.dei, []
    if not re.search(r"tahunan|annual", d.get("PeriodOfFinancialStatementsSubmissions", ""), re.I):
        out.append("not an annual report")
    if not re.search(r"diaudit|audited", d.get("TypeOfReportOnFinancialStatements", ""), re.I) or \
            re.search(r"tidak diaudit|unaudited", d.get("TypeOfReportOnFinancialStatements", ""), re.I):
        out.append("not audited")
    if ticker and d.get("EntityCode", "").upper() != ticker.upper():
        out.append(f"entity code {d.get('EntityCode')} is not {ticker}")
    if not d.get("CurrentPeriodEndDate") or not d.get("PriorYearEndDate"):
        out.append("period dates missing")
    return out


def _movement(inst, axis, year_end, cls=None, concept_prefix="AdditionIn"):
    """Addition to accumulated depreciation in a movement table: total row (cls None) or one class member."""
    for f in inst.facts:
        dm = dict(f.dims)
        if (f.concept.startswith(concept_prefix) and f.date == year_end and f.value and f.unit
                and dm.get(axis) == "CarryingAmountAccumulatedDepreciationMember"):
            classes = [v for k, v in dm.items() if k.startswith("Classes")]
            if (cls is None and not classes) or classes == [cls]:
                return float(f.value) / inst.scale
    return None


def extract(inst: Instance) -> dict:
    """Fields per column with the concepts used. Values in the presentation unit. Untagged -> None."""
    years = {"t": inst.dei.get("CurrentPeriodEndDate"), "t1": inst.dei.get("PriorYearEndDate")}
    out = {}
    for c in ("t", "t1"):
        g = lambda name, kind, c=c: inst.plain(name, c, kind)

        def total(names, kind, c=c):
            parts = [(n, inst.plain(n, c, kind)) for n in names]
            parts = [(n, v) for n, v in parts if v is not None]
            return (sum(v for _, v in parts), [n for n, _ in parts]) if parts else (None, [])

        f = {}
        def put(name, value, concepts):
            f[name] = Field(name, c, value, list(concepts))
        put("revenue", g("SalesAndRevenue", "d"), ["SalesAndRevenue"])
        put("cost_of_goods_sold", g("CostOfSalesAndRevenue", "d"), ["CostOfSalesAndRevenue"])
        put("selling_general_administrative_expenses", *total(SGA, "d"))
        v, cs = total(AR, "i")
        if v is None:
            v, cs = g("TradeReceivablesNet", "i"), ["TradeReceivablesNet"]
        put("accounts_receivable", v, cs)
        for name, concept in (("total_assets", "Assets"), ("current_assets", "CurrentAssets"),
                              ("ppe_face", "PropertyPlantAndEquipment"), ("rou_assets_net", "RightOfUseAssets"),
                              ("current_liabilities", "CurrentLiabilities"), ("total_liabilities", "Liabilities"),
                              ("cash_and_cash_equivalents", "CashAndCashEquivalents"), ("taxes_payable_total", "TaxesPayable")):
            put(name, g(concept, "i"), [concept])
        put("net_income", g("ProfitLoss", "d"), ["ProfitLoss"])
        put("cash_flow_from_operations", g("NetCashFlowsReceivedFromUsedInOperatingActivities", "d"),
            ["NetCashFlowsReceivedFromUsedInOperatingActivities"])
        put("long_term_debt", *total(LTD, "i"))
        put("current_maturities_long_term_debt", *total(CMLTD, "i"))
        ax = "CarryingAmountPropertyPlantEquipmentAxis"
        put("ppe_depreciation_owned", _movement(inst, ax, years[c], "DirectlyOwnedMember"), ["PPE table, DirectlyOwned"])
        put("ppe_table_depreciation_total", _movement(inst, ax, years[c]), ["PPE table, total"])
        put("rou_table_depreciation", _movement(inst, "CarryingAmountRightofUseAssetsAxis", years[c]), ["ROU table, total"])
        out[c] = f
    return out


def internal_checks(inst: Instance) -> dict:
    res = {}
    for c in ("t", "t1"):
        g = lambda n, k="i": inst.plain(n, c, k)
        def eq(a, b):
            return None if a is None or b is None else abs(a - b) <= 1
        A, CA, NCA = g("Assets"), g("CurrentAssets"), g("NonCurrentAssets")
        L, CL, NCL, E, LE = g("Liabilities"), g("CurrentLiabilities"), g("NonCurrentLiabilities"), g("Equity"), g("LiabilitiesAndEquity")
        res[c] = {"A=CA+NCA": eq(A, None if CA is None or NCA is None else CA + NCA), "L+E=A": eq(LE, A),
                  "L=CL+NCL": eq(L, None if CL is None or NCL is None else CL + NCL)}
    return res


# ---------------------------------------------------------------------------- PDF side
NUM = re.compile(r"\(?-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?\)?|\(?-?\d+\)?")


def numbers(line: str) -> set:
    out = set()
    for m in NUM.findall(line):
        g = re.split(r"[.,]", m.strip("()-"))
        if len(g) > 1 and len(g[-1]) <= 2:
            g = g[:-1]
        try:
            out.add(int("".join(g)))
        except ValueError:
            pass
    return out


def pdf_lines(pages: list) -> list:
    """pages: list of page texts -> [(page_no, line, numbers)]"""
    return [(i + 1, ln, numbers(ln)) for i, t in enumerate(pages) for ln in t.split("\n")]


def _pair_lines(lines, a, b):
    A, B = round(abs(a)), round(abs(b))
    return [(p, ln) for p, ln, n in lines if A in n and B in n and (A or B)]


def verify(inst: Instance, fields: dict, lines: list) -> None:
    """Rule 7 for XBRL: FOUND only if the pair (t, t-1) is printed on one PDF line, or every component pair is."""
    for name in fields["t"]:
        ft, f1 = fields["t"][name], fields["t1"][name]
        if ft.value is None and f1.value is None:
            continue
        concepts = sorted(set(ft.concepts) | set(f1.concepts))
        ok, ev = False, []
        if ft.value is not None and f1.value is not None:
            ev = _pair_lines(lines, ft.value, f1.value)
            ok = bool(ev)
        if not ok and name.startswith(("ppe_depreciation", "ppe_table", "rou_table")):
            dep = re.compile(r"penyusutan|depreciation|jumlah|total|sub", re.I)
            hits = [[(p, ln) for p, ln, n in lines if v is not None and round(abs(v)) in n and dep.search(ln)]
                    for v in (ft.value, f1.value)]
            ok = all(h for h, v in zip(hits, (ft.value, f1.value)) if v is not None)
            ev = [h[0] for h in hits if h]
        if not ok and len(concepts) > 1:
            kind = "d" if name == "selling_general_administrative_expenses" else "i"
            ok, ev = True, []
            for cname in concepts:
                a, b = inst.plain(cname, "t", kind), inst.plain(cname, "t1", kind)
                if a and b:
                    hit = _pair_lines(lines, a, b)
                else:
                    one = a or b
                    hit = [(p, ln) for p, ln, n in lines if one and round(abs(one)) in n]
                if not hit:
                    ok = False
                    break
                ev += hit[:1]
        for f in (ft, f1):
            f.evidence = ev[:2]
            if f.value is not None:
                f.status = "FOUND" if ok else "REVIEW"
                if not ok:
                    f.notes.append("XBRL value not found as a (t, t-1) pair in the PDF")


def face_pages(fields: dict, lines: list) -> dict:
    """Pages of the balance sheet ('bs') and the P&L ('pl'), found from the pairs XBRL says must be printed there."""
    out = {"bs": set(), "pl": set()}
    for kind, names in (("bs", ("total_assets", "current_liabilities", "total_liabilities")),
                        ("pl", ("revenue", "net_income"))):
        for name in names:
            a, b = fields["t"][name].value, fields["t1"][name].value
            if a is not None and b is not None:
                hit = _pair_lines(lines, a, b)
                if hit:
                    out[kind].add(hit[0][0])
    return {k: sorted(v) for k, v in out.items()}


def face_check(inst: Instance, lines: list, pages: dict) -> list:
    """Rule 2: a face line naming a score item must pair with a fact of that family. Returns REVIEW findings."""
    facts = {}
    for f in inst.facts:
        if f.dims or not f.unit or f.value in ("", None):
            continue
        col = "t" if f.ctx in CTX_T else "t1" if f.ctx in CTX_T1 else None
        if col:
            facts.setdefault(f.concept, {})[col] = round(abs(float(f.value) / inst.scale))
    findings = []
    for p, ln, n in lines:
        if p not in pages["bs"] and p not in pages["pl"]:
            continue
        if not any(x >= 100 for x in n):
            continue   # small figures alone are note references or years, not amounts
        nums = set(n)
        for fam, rx in FAMILY_LABEL.items():
            if (fam == "sga") != (p in pages["pl"] and p not in pages["bs"]):
                continue   # SGA lines on the P&L only; debt, ROU, receivables on the balance sheet only
            if not rx.search(ln) or NOT_FAMILY[fam].search(ln):
                continue
            def on_line(d):
                a, b = d.get("t") or 0, d.get("t1") or 0
                return (a or b) and (not a or a in nums) and (not b or b in nums)
            hits = [c for c, d in facts.items() if on_line(d)]
            if fam == "sga" and on_line({k: sum(facts.get(c, {}).get(k) or 0 for c in SGA) for k in ("t", "t1")}):
                continue
            if fam == "debt" and _subset_sum_match(facts, FAMILY_CONCEPTS["debt"], nums):
                continue
            if sum(x >= 100 for x in nums) == 1 and len(re.findall(r"(?<!\S)-(?!\S)", ln)) >= 2:
                continue   # third column only (e.g. 1 January of the comparative year); t and t-1 are '-'

            if not any(c in FAMILY_CONCEPTS[fam] for c in hits):
                findings.append({"page": p, "line": ln.strip()[:120], "family": fam, "tagged_as": hits[:3]})
    return findings


def _subset_sum_match(facts: dict, family: set, nums: set) -> bool:
    """A face line may present two or three tagged debt items as one amount (ASII 'bank loans and other loans').
    The same combination must match in both years."""
    from itertools import combinations
    items = [(d.get("t") or 0, d.get("t1") or 0) for c, d in facts.items() if c in family and (d.get("t") or d.get("t1"))]
    for r in (2, 3):
        for cmb in combinations(items, r):
            a, b = sum(x[0] for x in cmb), sum(x[1] for x in cmb)
            if (a or b) and (not a or a in nums) and (not b or b in nums):
                return True
    return False


def bank_loan_rule(inst: Instance) -> list:
    """Rule 1 (temporary): long-term + short-term bank loans tagged, no current maturities of bank loans -> REVIEW."""
    out = []
    for c in ("t", "t1"):
        lt, st, cm = (inst.plain(n, c, "i") for n in ("LongTermBankLoans", "ShortTermBankLoans", "CurrentMaturitiesOfBankLoans"))
        other = "t1" if c == "t" else "t"
        lt_any = lt or inst.plain("LongTermBankLoans", other, "i")
        cm_ever = cm is not None or inst.plain("CurrentMaturitiesOfBankLoans", other, "i") is not None
        if lt_any and st and not cm_ever:   # ZYRX (stage 3): issuer uses the current-maturity concept in the other year
            out.append({"column": c, "message": "short-term bank loans tagged while long-term bank loans exist and no "
                                                "current maturities are tagged: check whether part is a current portion"})
    return out


def zero_allowed(inst: Instance, family_findings: list, face_lines_found: bool, family: str) -> bool:
    """Rule 3: an untagged item may be 0 only if the XBRL subtotals add up and the PDF face has no such line."""
    checks = internal_checks(inst)
    subtotals_ok = all(v is True for col in checks.values() for v in col.values())
    return bool(face_lines_found and subtotals_ok and not any(f["family"] == family for f in family_findings))


def read(instance_source, pdf_pages: list, ticker: str | None = None) -> dict:
    """Full stage: gate, extract, verify, face check, rules. Returns a dict for the harness / later the pipeline."""
    inst = read_instance(instance_source)
    gate = document_gate(inst, ticker)
    fields = extract(inst)
    lines = pdf_lines(pdf_pages)
    verify(inst, fields, lines)
    pages = face_pages(fields, lines)
    findings = face_check(inst, lines, pages)
    bank = bank_loan_rule(inst)
    for fam, names in (("debt", ("long_term_debt", "current_maturities_long_term_debt")), ("rou", ("rou_assets_net",))):
        for c in ("t", "t1"):
            for nm in names:
                f = fields[c][nm]
                if f.value is None or (f.value == 0 and f.status != "FOUND"):
                    if zero_allowed(inst, findings, bool(pages["bs"]), fam):
                        f.value, f.status = 0.0, "FOUND"
                        f.notes.append("not tagged; subtotals add up and no such line on the PDF face (rule 3)")
                    else:
                        f.notes.append("not tagged and zero not proven (rule 3)")
    for fd in findings:
        targets = {"debt": ("long_term_debt", "current_maturities_long_term_debt"), "rou": ("rou_assets_net", "ppe_face"),
                   "receivable": ("accounts_receivable",), "sga": ("selling_general_administrative_expenses",)}[fd["family"]]
        for c in ("t", "t1"):
            for nm in targets:
                f = fields[c][nm]
                if f.status == "FOUND":
                    f.status = "REVIEW"
                f.notes.append(f"face line p{fd['page']} '{fd['line'][:50]}' not tagged as {fd['family']} (rule 2)")
    for b in bank:
        f = fields[b["column"]]["current_maturities_long_term_debt"]
        if f.status == "FOUND" or f.value is None:
            f.status = "REVIEW"
        f.notes.append(b["message"] + " (rule 1)")
    fi = financial_institution(lines, pages)
    if fi:
        gate.append("financial institution: " + "; ".join(f"{k} p{p} {lab}" for k, p, lab in fi))
    tax = corporate_tax_payable(inst, lines, pages)
    return {"gate": gate, "tax": tax, "dei": inst.dei, "scale": inst.scale, "fields": fields, "face_pages": pages,
            "face_findings": findings, "bank_rule": bank, "internal_checks": internal_checks(inst)}


# ---------------------------------------------------------------------------- finance-company gate
def financial_institution(lines: list, pages: dict) -> list:
    """Same rule as the PDF reader (Gail, 28 Oct 2026): two or more distinct bank / insurer / finance-company
    items on the face -> not scored. Uses the PDF face pages located from the XBRL pairs."""
    from .pdf_reader import FI_MARKERS
    found = {}
    face = set(pages["bs"]) | set(pages["pl"])
    for p, ln, _ in lines:
        if p not in face:
            continue
        lab = re.sub(r"\s+", " ", re.split(r"\s\(?-?\d", ln.strip().lower(), maxsplit=1)[0]).strip(" -")
        for i, (kind, rx) in enumerate(FI_MARKERS):
            if i not in found and re.search(rx, lab):
                found[i] = (kind, p, ln.strip()[:60])
    return list(found.values()) if len(found) >= 2 else []


# ---------------------------------------------------------------------------- corporate income tax payable (D-03)
CORPORATE = re.compile(r"pasal 25|pasal 29|article 25|article 29|pph 25|pph 29|pph badan|pajak penghasilan badan|"
                       r"corporate income tax|25/29|artical 25", re.I)
NOT_CORPORATE = re.compile(r"pasal (4|15|21|22|23|26)\b|article (4|15|21|22|23|26)\b|pph (4|15|21|22|23|26)\b|"
                           r"pertambahan nilai|value[- ]added|\bppn\b|bumi dan bangunan|\bpbb\b|pembangunan|"
                           r"\bstp\b|skpkb|final|luar negeri|foreign|barang mewah|luxury|lain|other|daerah|cukai|excise", re.I)
SUBTOTAL = re.compile(r"^(jumlah|total|sub[- ]?total|sub[- ]?jumlah|subjumlah)\b", re.I)
TAX_HEAD = re.compile(r"utang pajak|taxes payable|tax payables?", re.I)
STOP_HEAD = re.compile(r"pajak dibayar di ?muka|prepaid tax|beban pajak|tax expense|manfaat .*pajak", re.I)


def _amounts(line: str) -> list:
    """Ordered amounts on a table line, after removing article numbers in the label (Pasal 4(2), Article 25/29)."""
    lab = re.sub(r"(?i)(pasal|article|artical|pph)\s*\d+(\s*\(\s*\d\s*\))?(\s*(/|dan|and)\s*\d+)*", " ", line)
    lab = re.sub(r"\b\d+[a-z]\b|\b\d{1,2}[a-z]?,\s?\d", " ", lab)       # note references 13.b, 2,32
    out = []
    for m in re.finditer(r"\(?-?\d{1,3}(?:[.,]\d{3})+\)?|\(?-?\d+\)?|(?<!\S)-(?!\S)|--", lab):
        tok = m.group(0)
        out.append(0 if tok.strip("()") in ("-", "--") else int(re.sub(r"[^\d]", "", tok) or 0))
    return out


def _despace(s: str) -> str:
    """'T o t a l' -> 'Total' (letter-spaced headings in some reports)."""
    return re.sub(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b", lambda m: m.group(0).replace(" ", ""), s)


DATE = re.compile(r"(?i)\b(januari|january|februari|february|maret|march|april|mei|may|juni|june|juli|july|agustus|"
                  r"august|september|oktober|october|november|desember|december)\b")


def _is_year_header(am: list, line: str = "") -> bool:
    return (len(am) >= 2 and all(1990 <= x <= 2035 for x in am[-2:])) or bool(DATE.search(line))


def corporate_tax_payable(inst: Instance, lines: list, pages: dict) -> dict:
    """D-03: PPh 25/29 of the group from the taxes-payable table whose total equals the XBRL TaxesPayable pair.
    FOUND only if the detail lines add up to that total; unclassified lines -> REVIEW. No table -> NOT FOUND."""
    a, b = inst.plain("TaxesPayable", "t", "i"), inst.plain("TaxesPayable", "t1", "i")
    res = {"t": None, "t1": None, "status": "NOT FOUND", "page": None, "lines": [], "notes": []}
    if a is None or b is None:
        res["notes"].append("TaxesPayable not tagged")
        return res
    A, B = round(abs(a)), round(abs(b))
    by_page = {}
    for p, ln, n in lines:
        by_page.setdefault(p, []).append((ln, n))
    for p, plines in by_page.items():
        if p in pages["bs"]:
            continue
        for i, (ln, n) in enumerate(plines):
            lab = _despace(ln.strip())
            if not (A in n and B in n and (SUBTOTAL.search(lab) or not re.search(r"[A-Za-z]{3}", lab))):
                continue
            tot = [x for x in _amounts(ln) if x in (A, B)]
            swap = len(tot) >= 2 and tot[-2] == B and tot[-1] == A and A != B
            detail, j, head = [], i - 1, None
            while j >= 0 and i - j <= 40:
                lj = plines[j][0].strip()
                if STOP_HEAD.search(lj) and len([x for x in _amounts(lj) if x]) < 2:
                    head = "other"
                    break
                if TAX_HEAD.search(lj) and len([x for x in _amounts(lj) if x]) < 2:
                    head = "tax"
                    break
                am = _amounts(lj)
                if len(am) >= 2 and not SUBTOTAL.search(_despace(lj)) and not _is_year_header(am, lj):
                    detail.append((lj, am[-1], am[-2]) if swap else (lj, am[-2], am[-1]))
                j -= 1
            if not detail or head == "other":
                continue   # a prepaid-tax or tax-expense table with the same totals is not the payable table
            st, s1 = sum(x[1] for x in detail), sum(x[2] for x in detail)
            conflict = (st, s1) != (A, B) and (s1, st) == (A, B)
            if conflict:
                # PTPW 2022: the detail columns add up to the totals of the other year. The printed column order
                # is kept and the figure is REVIEW (rule 7: a conflict is never resolved by guessing)
                st, s1 = A, B
                res["notes"].append(f"p{p}: detail columns add up to the other year's total; printed order kept")
            corp = [x for x in detail if CORPORATE.search(x[0]) and not NOT_CORPORATE.search(x[0].split("Article")[0])]
            unknown = [x for x in detail if not CORPORATE.search(x[0]) and not NOT_CORPORATE.search(x[0])]
            res.update(page=p, lines=[x[0][:80] for x in detail])
            if st != A or s1 != B:
                res["notes"].append(f"p{p}: detail lines {st}/{s1} do not add up to {A}/{B}")
                continue
            res["t"], res["t1"] = float(sum(x[1] for x in corp)), float(sum(x[2] for x in corp))
            res["status"] = "REVIEW" if unknown or not corp or conflict or head != "tax" else "FOUND"
            if head != "tax":
                res["notes"].append("table heading 'utang pajak / taxes payable' not found above the table")
            if unknown:
                res["notes"].append("unclassified lines: " + "; ".join(x[0][:40] for x in unknown))
            if not corp:
                res["notes"].append("no Article 25/29 line in a table that adds up: 0 from evidence")
            return res
    res["notes"].append("no taxes-payable table found whose total equals the face")
    return res
