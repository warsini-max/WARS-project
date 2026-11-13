"""Evidence ledger and shadow mode (P0-2; Gail 13 Nov 2026 16.46: K1 = B, K2 = B, K5 = A, K6 approved).

For every score input (field x year) the ledger records what the value is and why it is believed: where it came
from (derivation A-DIR / A-MAP / A-AGG / A-INF / A-USR), the document, page, printed label, XBRL concepts and
components, and the corroboration found (C-PRES / C-LAB / C-REC / C-XDOC / C-HUM) with the kinds of error each one
can catch (E-ID identity, E-CMP completeness, E-PER period, E-MAG magnitude, E-SGN sign and scale). It then derives
the status the evidence policy (WARS_Evidence_Policy_Matrix_r0.md) would give, and the reason when it differs.

SHADOW ONLY. The ledger never changes a value, a status, a card, the score or a report: it is written to
`r.ledger` and nowhere else. The operational status stays the old one (K6).

K2 = B is recorded here only. ROU-0 (Gail 28 Oct 2026) and rule 3 (Gail 30 Oct 2026, zero from absence) stay the
operational behaviour until their revision is authorised explicitly (WARS_K2_Conflict_Map_r0.md).
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------------------------------- definitions
DERIVATIONS = ("A-DIR", "A-MAP", "A-AGG", "A-INF", "A-USR")
CORROBORATIONS = {          # what each kind of corroboration can catch (Evidence Policy Matrix 2.2)
    "C-PRES": ("E-MAG", "E-PER"),
    "C-LAB": ("E-ID", "E-PER", "E-MAG"),
    "C-REC": ("E-CMP", "E-ID", "E-MAG"),
    "C-XDOC": ("E-MAG", "E-PER"),
    "C-HUM": ("E-ID", "E-CMP", "E-PER", "E-MAG", "E-SGN"),
}
SINGLE = ("revenue", "cost_of_goods_sold", "total_assets", "current_assets", "current_liabilities",
          "total_liabilities", "cash_and_cash_equivalents", "net_income", "cash_flow_from_operations")
COMPOSITE = ("selling_general_administrative_expenses", "accounts_receivable", "property_plant_equipment_net")
RISK = ("long_term_debt", "current_maturities_long_term_debt", "taxes_payable", "ppe_depreciation_disclosed",
        "amortization_intangibles", "depreciation_amortization_non_ppe")
FIELDS = SINGLE + COMPOSITE + RISK + ("rou_assets_net",)     # the right-of-use component of PPE (D-08)
KIND = {"revenue": "profit_loss", "cost_of_goods_sold": "profit_loss", "selling_general_administrative_expenses": "profit_loss",
        "net_income": "profit_loss", "cash_flow_from_operations": "cash_flow"}
USER = {"USER CONFIRMED", "USER AMENDED", "USER SET"}

# controlled vocabularies (Evidence Policy Matrix 3): (include, exclude), matched on the label with its English side
V = {
    "revenue": (r"\b(pendapatan|penjualan|revenues?|sales)\b",
                r"\b(lain|other|keuangan|finance|bunga|interest|pokok|cost|diterima di muka|unearned|komprehensif|comprehensive)\b"),
    "cost_of_goods_sold": (r"\b(beban pokok|harga pokok|cost of (sales|revenues?|goods))\b", r"\b(laba|gross|profit)\b"),
    "sga_selling": (r"\b(beban penjualan|beban pemasaran|beban distribusi|beban usaha|selling|marketing|distribution|operating expenses?)\b",
                    r"\b(lain|other|keuangan|finance|pokok|cost of|langsung|direct)\b"),
    "sga_ga": (r"\b(beban umum|administrasi|general|administrative|beban usaha|operating expenses?)\b",
               r"\b(lain|other|keuangan|finance|pokok|cost of|langsung|direct)\b"),
    "accounts_receivable": (r"\b(piutang usaha|trade receivables?|accounts receivables?)\b",
                            r"\b(lain|other|non-?trade|retensi|retention|tagihan bruto)\b"),
    "total_assets": (r"\b(jumlah|total) aset\b|\btotal assets\b", r"\b(lancar|current|tidak lancar|non-?current)\b"),
    "current_assets": (r"\b(jumlah|total) aset lancar\b|\btotal current assets\b", r"\btidak lancar\b|\bnon-?current\b"),
    "current_liabilities": (r"\b(jumlah|total) liabilitas\b.*\b(jangka pendek|lancar)\b|\btotal current\b.*\bliabilities\b",
                            r"\bnon-?current\b|jangka panjang|tidak lancar"),
    "total_liabilities": (r"\b(jumlah|total) liabilitas\b|\btotal liabilities\b", r"\b(jangka|lancar|current|dan ekuitas|and equity)\b"),
    "cash_and_cash_equivalents": (r"\bkas\b|\bcash\b", r"\b(dibatasi|restricted|arus|flows?|neto|net|akhir|awal|end|beginning)\b"),
    "net_income": (r"\b(laba|rugi|profit|loss)\b",
                   r"\b(sebelum|before|kotor|bruto|gross|usaha|operasi|operating|komprehensif|comprehensive|saham|share|"
                   r"diatribusikan|attributable|nonpengendali|non-?controlling|selisih|kurs|penjualan|disposal|lain|other)\b"),
    "cash_flow_from_operations": (r"\b(aktivitas operasi|operating activities)\b", r"\b(investasi|investing|pendanaan|financing)\b"),
    "ppe": (r"\baset tetap\b|\bfixed assets\b|\bproperty,? (plant )?and equipment\b",
            r"\b(uang muka|advance|dimiliki untuk dijual|held for sale|penjualan|disposal|pinjaman|utang|liabilitas|loans?|"
            r"payables?|perolehan|acquisition|purchase|surplus|revaluasi|revaluation)\b"),
    "rou": (r"\bhak[- ]guna\b|\bright[- ]of[- ]use\b|\bhak untuk menggunakan\b|\bhak pakai\b",
            r"\b(liabilitas|liabilities|utang|pajak tangguhan|deferred tax|uang muka|advance)\b"),
    "bearer": (r"\btanaman (produktif|perkebunan|menghasilkan|belum menghasilkan|telah menghasilkan)\b|\bbearer plants?\b",
               r"\b(semusim|industri|uang muka|advance)\b"),
}
NON_SGA = re.compile(r"\b(lain|lainnya|other|keuangan|finance|bunga|interest|bagian (atas )?(laba|rugi)|share (in|of)|selisih kurs|"
                     r"foreign exchange|penurunan nilai|impairment|nilai wajar|fair value|pajak final|final tax|penjualan aset|"
                     r"disposal|pendapatan|income|keuntungan|kerugian|gain|loss|dividen|ventura|joint venture|associate|asosiasi|"
                     r"penyisihan|provision)\b", re.I)
GP = re.compile(r"\b(laba|rugi) (kotor|bruto)\b|\bgross (profit|loss)\b", re.I)
OP_OR_PBT = re.compile(r"\b(laba|rugi)( \(rugi\)| \(laba\))? (usaha|operasi|sebelum)\b|"
                       r"\b(operating (profit|loss|income)|(profit|loss|income) before)\b", re.I)
NUMRX = re.compile(r"\(?-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?\)?|\(?-?\d{4,}\)?")
ABSENCE_WORDS = {"debt": re.compile(r"(?i)liabilitas sewa|lease liabilit|pinjaman|borrowing|obligasi|bonds payable|"
                                    r"utang bank|bank loan"),
                 "rou": re.compile(r"(?i)hak[- ]guna|right[- ]of[- ]use|hak untuk menggunakan")}


# ------------------------------------------------------------------------------------------- text helpers
def _numbers(line):
    out = set()
    for m in NUMRX.findall(line):
        g = re.split(r"[.,]", m.strip("()-"))
        if len(g) > 1 and len(g[-1]) <= 2:
            g = g[:-1]
        try:
            out.add(int("".join(g)))
        except ValueError:
            pass
    return out


def raw_lines(page_texts):
    """[(page, line, numbers)] for the page texts of the PDF (1-based pages)."""
    return [(i + 1, ln, _numbers(ln)) for i, t in enumerate(page_texts or []) for ln in t.split("\n")]


def statement_lines(st):
    """The PDF reader's statement lines (word coordinates, wrapped labels joined) as raw-like lines."""
    out = []
    fmt = lambda v: "-" if v is None else f"{round(abs(v)):,}".replace(",", ".")   # noqa: E731
    for ln in getattr(st, "lines", None) or []:
        lab = (getattr(ln, "full_label", "") or getattr(ln, "label", "") or "").strip()
        a = getattr(ln, "amounts", None) or {}
        t = f"{lab} {fmt(a.get('t'))} {fmt(a.get('t1'))}" if ("t" in a or "t1" in a) else lab
        if t:
            out.append((ln.page, t, _numbers(t)))
    return out


def _own(ln):
    t = NUMRX.sub(" ", ln)
    t = re.sub(r"\b\d{1,3}[a-z]?\b(,\s*\d{1,3}[a-z]?)*", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _real(ln):
    """(position, amount >= 100) of a line's amounts that are not quoted inside the label ('Rp 2.429.785.811')."""
    out = []
    for m in NUMRX.finditer(ln):
        if re.search(r"(rp|us\$|usd)\.?\s*$", ln[:m.start()], re.I):
            continue
        x = int(re.sub(r"\D", "", m.group()) or 0)
        year = re.fullmatch(r"\(?-?\d{4}\)?", m.group()) and 1900 <= x <= 2100     # '2025', not '2.025'
        if x >= 100 and not year:
            out.append((m.start(), x))
    return out


def _amt(n, ln=None):
    if ln is not None:
        return {x for _p, x in _real(ln)}
    return {x for x in n if x >= 100}


def _match(key, text):
    inc, exc = V[key]
    return bool(re.search(inc, text, re.I)) and not re.search(exc, text, re.I)


def _has_pair(n, a, b):
    A = round(abs(a)) if a else 0
    B = round(abs(b)) if b else 0
    if not (A or B):
        return False
    return (not A or A in n) and (not B or B in n)


def _ctx(lines, i):
    p = lines[i][0]
    held, j = [], i - 1
    while j >= 0 and len(held) < 2 and lines[j][0] == p and not _amt(lines[j][2], lines[j][1]):
        if lines[j][1].strip():
            held.insert(0, _own(lines[j][1]))
        j -= 1
    return " ".join(held + [_own(lines[i][1])])


def _two(ln):
    am = _real(ln)
    if len(am) >= 2:
        return am[-2][1], am[-1][1]
    if len(am) == 1:
        pos, x = am[0]
        dash = [m.start() for m in re.finditer(r"(?<![\w.,])-(?![\w.,])", ln)]
        if any(d > pos for d in dash):
            return x, 0
        if any(d < pos for d in dash):
            return 0, x
    return None


# ------------------------------------------------------------------------------------------- corroboration tests
def c_lab(lines, pages, key, a, b):
    """C-LAB: a line on a page of the right primary statement prints the pair and its label (own, or the label-only
    lines above it for wrapped / indented labels; the whole label for the tail of a wrapped label) names the item."""
    first = None
    for i, (p, ln, n) in enumerate(lines):
        if p not in pages or not _has_pair(_amt(n, ln), a, b):     # amounts quoted inside a label do not count
            continue
        own = _own(ln)
        first = first or own[:80]
        cont = ln.strip()[:1].islower()
        if (not cont and _match(key, own)) or _match(key, _ctx(lines, i)):
            return True, own[:80]
        # a label wrapped below the amounts: 'Arus kas bersih yang diperoleh dari 37,342 38,252 ... / aktivitas operasi'
        # (ASII 2022). Only a label-only continuation line on the same page counts.
        if not cont and i + 1 < len(lines) and lines[i + 1][0] == p and not _amt(lines[i + 1][2], lines[i + 1][1]) \
                and lines[i + 1][1].strip()[:1].islower() and _match(key, own + " " + _own(lines[i + 1][1])):
            return True, (own + " " + _own(lines[i + 1][1]))[:80]
    return False, first or "pair not on the statement pages"


def sga_complete(lines, pages, total):
    """C-REC for selling + G&A: every labelled amount line between gross profit and operating profit / profit before
    tax is an SGA line or a recognised non-SGA line, and the SGA lines add up to the value; or a printed subtotal in
    that block equals the value."""
    if not total or total.get("t") is None or total.get("t1") is None:
        return False, "no value"
    T, T1 = round(abs(total["t"])), round(abs(total["t1"]))
    L = [x for x in lines if x[0] in pages]
    gp = next((i for i, x in enumerate(L) if GP.search(_own(x[1])) and _amt(x[2], x[1])), None)
    if gp is None:
        return False, "no gross profit line"
    end = next((i for i in range(gp + 1, len(L)) if OP_OR_PBT.search(_own(L[i][1]))), None)
    if end is None:
        return False, "no operating profit / profit before tax line"
    s_t = s_t1 = 0
    unclassified = []
    for i in range(gp + 1, end):
        p, ln, n = L[i]
        if not _amt(n, ln):
            continue
        own = _own(ln)
        if T in n and T1 in n and (not re.search(r"[a-z]{3}", own) or re.search(r"\b(jumlah|total)\b", own)):
            return True, "printed subtotal equals the value"
        if not re.search(r"[a-z]{3}", own):
            continue
        ctx = _ctx(L, i)
        if ln.strip()[:1].islower():
            own = ctx
        if _match("sga_selling", own) or _match("sga_ga", own) or (not NON_SGA.search(own) and
                                                                    (_match("sga_selling", ctx) or _match("sga_ga", ctx))):
            two = _two(ln)
            if two:
                s_t += two[0]
                s_t1 += two[1]
            continue
        if NON_SGA.search(own) or NON_SGA.search(ctx):
            continue
        unclassified.append(own[:50])
    if unclassified:
        return False, "unclassified: " + "; ".join(unclassified[:3])
    ok = s_t == T and s_t1 == T1
    return ok, ("block adds up" if ok else f"block sum {s_t}/{s_t1} vs {T}/{T1}")


def family_sum(lines, pages, keys, total):
    """C-REC for receivables / PPE: the balance-sheet lines of the family (own label, or sub-lines under a heading that
    names it) add up to the value, or a printed total of the family equals it."""
    if not total or total.get("t") is None or total.get("t1") is None:
        return False, "no value", 0
    T, T1 = round(abs(total["t"])), round(abs(total["t1"]))
    s_t = s_t1 = 0
    used, heads, head = [], [], ""
    for i, (p, ln, n) in enumerate(lines):
        if p not in pages:
            continue
        own = _own(ln)
        if not _amt(n, ln):
            if own:
                heads.append(own)
                head = " ".join(heads[-4:])
            continue
        if re.search(r"^(jumlah|total)\b", own):
            if T in n and T1 in n and any(_match(k, own) for k in keys):
                return True, "printed total equals the value", 1
            head, heads = "", []
            continue
        sub = bool(re.search(r"^(-\s*)?(pihak|third|related|neto|net\b|setelah|after)", own)) or ln.strip()[:1].islower() \
            or ln.strip()[:1] in "-–"
        text = (head + " " + own) if (sub or not re.search(r"[a-z]{3}", own)) else own
        if any(_match(k, text) for k in keys):
            two = _two(ln)
            if two:
                s_t += two[0]
                s_t1 += two[1]
                used.append(own[:30])
        if not sub:
            head, heads = "", []
    ok = bool(used) and s_t == T and s_t1 == T1
    return ok, f"{len(used)} line(s) add up to {s_t}/{s_t1} vs {T}/{T1}", len(used)


# ------------------------------------------------------------------------------------------- the ledger
def _derivation(path, f, v, item):
    st = v.status
    if st in USER:
        return "A-USR"
    if st in ("ASSUMED", "UNDISCLOSED"):
        return "A-INF"
    note = (str(getattr(v, "note", "")) + " " + (getattr(item, "note", "") if item else "")).lower()
    src = (getattr(item, "source", "") if item else "") or ""
    if v.value == 0 and ("rule 3" in note or "tidak menyebut aset hak-guna" in note or "never mentions" in note):
        return "A-INF"
    if "pendekatan" in src.lower() or "d-03g" in src.lower():
        return "A-INF"
    if path == "X" and src.startswith("XBRL"):
        concepts = src.split(" ", 1)[1] if " " in src else ""
        return "A-AGG" if ("+" in concepts or "ROU" in src or "bearer" in src) else "A-MAP"
    if getattr(v, "components", "") or len(getattr(v, "quotes", None) or []) > 1:
        return "A-AGG"
    return "A-DIR"


def _concepts(item):
    src = (getattr(item, "source", "") or "") if item else ""
    if src.startswith("XBRL ") and "movement" not in src.lower():
        return [c for c in src[5:].split("+") if re.match(r"^[A-Za-z][\w-]*$", c)]
    return []


def _absence_ok(r, f, raw, stm_pages):
    """K2 = B (shadow): a zero from absence is acceptable only when the pages of the family were read as text and
    nothing in the notes names the family."""
    fam = "rou" if f in ("rou_assets_net", "property_plant_equipment_net") else "debt"
    if not raw or not stm_pages:
        return False, "pages not available as text"
    if getattr(r, "unreadable", "") or (getattr(r.extraction, "scanned_pages", None) or []):
        return False, "image pages in the report"
    last = max(stm_pages)
    rx = ABSENCE_WORDS[fam]
    hit = next((ln for p, ln, _n in raw if p > last and rx.search(ln)), None)
    if hit:
        return False, f"the notes name the family: '{hit.strip()[:60]}'"
    return True, "pages read as text; no mention of the family in the notes"


def build(r, page_texts=None, path=None):
    """The ledger rows for one result. path: 'X' (XBRL + PDF) when r.xbrl is set, else 'P'. Never mutates r."""
    path = path or ("X" if getattr(r, "xbrl", None) else "P")
    ex = r.extraction
    fy = getattr(ex, "fiscal_year", None)
    stm = getattr(ex, "statements", None) or {}
    raw = raw_lines(page_texts) if page_texts else []
    spages = {k: set(getattr(v, "pages", None) or {ln.page for ln in v.lines}) for k, v in stm.items()}
    alts = {k: statement_lines(v) for k, v in stm.items()}
    items = {(it.field, it.column): it for it in ((getattr(r, "xbrl", None) or {}).get("items") or [])}
    parts = (getattr(r, "xbrl", None) or {}).get("parts") or {}
    checks = {}
    for name, col, passed, _d in getattr(ex, "checks", None) or []:
        if passed:
            checks.setdefault(col, set()).add(getattr(name, "key", str(name)))
    vals = {(v.field, v.column): v for v in ex.values if v.field in FIELDS and v.column in ("t", "t1")}
    inf_zero = {k for k, v in vals.items() if _derivation(path, v.field, v, items.get(k)) == "A-INF" and v.value == 0
                and v.status == "FOUND"}
    rows = []
    cache = {}
    for (f, c), v in sorted(vals.items(), key=lambda kv: (FIELDS.index(kv[0][0]), kv[0][1])):
        item = items.get((f, c))
        der = _derivation(path, f, v, item)
        kind = KIND.get(f, "position")
        pages = spages.get(kind, set())
        a = (vals.get((f, "t")).value if vals.get((f, "t")) else None)
        b = (vals.get((f, "t1")).value if vals.get((f, "t1")) else None)
        cor = []
        if v.status in USER:
            cor.append(("C-HUM", "user check"))
        if path == "X" and item is not None and item.status == "FOUND" and (item.source or "").startswith("XBRL"):
            cor.append(("C-PRES", "XBRL pair printed in the PDF"))
        ck = checks.get(c, set())
        if ck & {"check.balance", "check.section_ca", "check.section_cl", "check.gross_profit", "check.net_income",
                 "check.cfo", "check.cash_cf", "check.tl_parts", "check.ta_tle"} and f in SINGLE:
            cor.append(("C-REC", "statement identity: " + ", ".join(sorted(ck & {"check.balance", "check.section_ca",
                        "check.section_cl", "check.gross_profit", "check.net_income", "check.cfo", "check.cash_cf",
                        "check.tl_parts", "check.ta_tle"}))))
        if f in SINGLE and (a is not None or b is not None):
            key = ("lab", f)
            if key not in cache:
                ok, why = c_lab(raw, pages, f, a, b) if raw else (False, "no page text")
                if not ok and alts.get(kind):
                    ok2, why2 = c_lab(alts[kind], pages, f, a, b)
                    ok, why = (ok2, why2) if ok2 else (False, why + " | " + why2)
                cache[key] = (ok, why)
            ok, why = cache[key]
            cor.append(("C-LAB" if ok else "C-LAB-FAILED", why))
        if f in COMPOSITE and (a is not None and b is not None):
            key = ("rec", f)
            if key not in cache:
                tot = {"t": a, "t1": b}
                if f == "selling_general_administrative_expenses":
                    ok, why = sga_complete(raw, pages, tot) if raw else (False, "no page text")
                    if not ok and alts.get(kind):
                        ok2, why2 = sga_complete(alts[kind], pages, tot)
                        ok, why = (ok2, why2) if ok2 else (False, why + " | " + why2)
                else:
                    keys = ["accounts_receivable"] if f == "accounts_receivable" else ["ppe", "rou", "bearer"]
                    ok, why, n = family_sum(raw, pages, keys, tot) if raw else (False, "no page text", 0)
                    if not ok and n == 0 and alts.get(kind):             # the source that sees the lines decides
                        ok, why, _n = family_sum(alts[kind], pages, keys, tot)
                cache[key] = (ok, why)
            ok, why = cache[key]
            cor.append(("C-REC" if ok else "C-REC-FAILED", why))
        tests = sorted({e for t_, _w in cor for e in CORROBORATIONS.get(t_, ())})
        proposed, reason = v.status, ""
        if v.status == "FOUND":
            if der == "A-INF":
                ok, why = _absence_ok(r, f, raw, spages.get("position", set()))
                if not ok:
                    proposed, reason = "REVIEW", "K2-B: zero from absence without the readability evidence (" + why + ")"
            elif f in SINGLE and "E-ID" not in tests:
                proposed, reason = "REVIEW", "K1-B: identity (E-ID) not corroborated; presence alone (C-PRES) is not identity"
            elif f in COMPOSITE and "E-CMP" not in tests:
                proposed, reason = "REVIEW", "K5-A: completeness (E-CMP) not shown"
        if f == "property_plant_equipment_net" and proposed == "FOUND" and ("rou_assets_net", c) in inf_zero:
            proposed, reason = "REVIEW", "K2-B: PPE relies on a right-of-use zero from absence"
        comps = []
        if path == "X" and parts.get(f):
            comps = [{"label": str(lab), "t": pa, "t1": pb, "page": pg} for lab, pa, pb, pg in parts[f]]
        elif getattr(v, "components", ""):
            comps = [{"text": str(v.components)}]
        rows.append({
            "field": f, "column": c, "year": (fy if c == "t" else (fy - 1 if fy else None)),
            "value": v.value, "derivation": der,
            "source_doc": "XBRL instance + PDF" if (path == "X" and item is not None and (item.source or "").startswith("XBRL"))
            else "PDF", "pages": sorted(set(getattr(v, "pages", None) or [])),
            "label": _own((getattr(v, "quotes", None) or [""])[0])[:120] if getattr(v, "quotes", None) else "",
            "xbrl_concepts": _concepts(item), "components": comps,
            "corroboration": [{"type": t_, "detail": w, "tests": list(CORROBORATIONS.get(t_, ()))} for t_, w in cor],
            "error_kinds_tested": tests, "status_old": v.status, "status_proposed": proposed, "reason": reason,
            "risk": f in RISK,
        })
    return rows


def attach(r, page_texts=None, path=None):
    """Write the ledger to r.ledger (shadow). Returns the rows. Never changes anything else on r."""
    rows = build(r, page_texts, path)
    r.ledger = rows
    return rows


def compare(rows):
    """Old vs proposed status: counts and the rows that differ, with their reasons."""
    diff = [x for x in rows if x["status_old"] != x["status_proposed"]]
    return {"n": len(rows), "differ": len(diff),
            "by_reason": {k: sum(1 for x in diff if x["reason"].startswith(k)) for k in ("K1-B", "K2-B", "K5-A")},
            "rows": diff}
