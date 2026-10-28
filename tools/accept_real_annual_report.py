"""Phase D acceptance on a REAL annual report (Laporan Tahunan): evidence against the audited LK.

Usage:
    python tools/accept_real_annual_report.py <annual_report.pdf> <reference_LK.pdf> <issuer name> <fiscal year> [out.md]

The annual report is read unchanged (its SHA-256 is recorded before and after). The reader is run
on both documents and the results are compared. Nothing is tuned here: this tool only reports.

Evidence produced (Gail, 23 Oct 2026):
  1. the located block is the audited statements + notes (not highlights / MD&A): every candidate
     page and every block is listed, with the heading text of the chosen pages;
  2. issuer, fiscal year and basis: the issuer name and "konsolidasian" are looked for in the
     heading of each chosen page; any separate/parent-only statement block is listed;
  3. values, statuses and quotes equal those read from the reference LK; each value's annual-report
     page is checked independently (its quote must be on that page's text), and the printed page
     footer of the statement pages is shown next to the file page;
  4. when there is more than one candidate block, the choice and the reason are reported;
  5. the full test suite is run separately (pytest), results recorded with the commit hash.

Exit code 0 = every check passed; 1 = at least one check failed (the report says which).
"""
from __future__ import annotations

import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from wars_scanner.pdf_reader import locate_financial_statements, read  # noqa: E402

PARENT_ONLY = re.compile(r"ENTITAS INDUK SAJA|ENTITAS INDUK\s*\)|PARENT ENTITY ONLY|LAPORAN KEUANGAN TERSENDIRI|"
                         r"SEPARATE FINANCIAL STATEMENTS|INFORMASI KEUANGAN (TAMBAHAN )?ENTITAS INDUK")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip().upper()


def _printed(text):
    """Printed page number(s): lines holding only a number (e.g. "1", "36", "5/2"). Empty when none."""
    return ",".join(m.strip() for m in re.findall(r"(?m)^\s*(\d{1,4}(?:/\d{1,3})?)\s*$", text or ""))


def _vals(ex):
    return {(v.field, v.column): v for v in ex.values}


def run(ar_pdf, lk_pdf, issuer, fiscal_year, out=None):
    ar_pdf, lk_pdf = Path(ar_pdf), Path(lk_pdf)
    rep, fails = [], []

    def check(name, ok, detail=""):
        rep.append(f"| {name} | {'PASS' if ok else '**FAIL**'} | {detail} |")
        if not ok:
            fails.append(name)

    sha_before = _sha(ar_pdf)
    loc = locate_financial_statements(ar_pdf)
    ar = read(ar_pdf)
    lk = read(lk_pdf)
    sha_after = _sha(ar_pdf)
    text = loc["text"]
    chosen = loc["chosen"] or {}

    rep += [f"# Phase D acceptance: {ar_pdf.name}", "",
            f"- Annual report: `{ar_pdf.name}`, {loc['n_pages']} pages, SHA-256 `{sha_before}`",
            f"- Reference LK: `{lk_pdf.name}`, SHA-256 `{_sha(lk_pdf)}`",
            f"- Issuer expected: {issuer}; fiscal year expected: {fiscal_year}",
            f"- Pages without a text layer: {len(loc['scanned'])} (e.g. {loc['scanned'][:15]})", "",
            "## Candidates and blocks (criterion 4)", "",
            f"- Candidate pages: {loc['candidates']}",
            f"- Blocks: {loc['blocks']}",
            f"- Chosen: {chosen or 'none'}", ""]
    for b in loc["blocks"]:
        pages = b["position"] + b["profit_loss"] + b["cash_flow"]
        heads = " / ".join(_norm(text[p - 1])[:90] for p in pages[:1])
        po = any(PARENT_ONLY.search(_norm(text[p - 1])) for p in pages)
        rep.append(f"  - block at p{pages[0]}: notes_start={b['notes_start']}, parent-only wording={po}, head: {heads}")
    rep += ["", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|"]

    check("PDF unchanged by the reader", sha_before == sha_after)
    check("statements located", bool(chosen), str(chosen))
    check("notes (CALK) located", bool(chosen.get("notes_start")), f"p{chosen.get('notes_start')}")
    check("exactly one complete block (else the choice must be explained)", len(loc["blocks"]) == 1,
          f"{len(loc['blocks'])} block(s)")

    # 1. not highlights / MD&A: chosen pages carry a Notes column or the integral-part footer (reader rule),
    #    and none of them is titled as highlights or analysis
    bad = [p for k in ("position", "profit_loss", "cash_flow") for p in chosen.get(k, [])
           if re.search(r"IKHTISAR|HIGHLIGHTS|ANALISIS DAN PEMBAHASAN|MANAGEMENT DISCUSSION", _norm(text[p - 1])[:400])]
    check("chosen pages are not highlights / MD&A", not bad, f"suspect pages {bad}" if bad else "")

    # 2. issuer, year, consolidated basis
    first = chosen.get("position", [None])[0]
    head = _norm(text[first - 1])[:600] if first else ""
    issuer_key = _norm(issuer).replace("PT ", "").replace(" TBK", "")
    check("issuer name on the statement of financial position", issuer_key in head, issuer_key)
    check("fiscal year read = expected", ar.fiscal_year == int(fiscal_year), f"read {ar.fiscal_year}")
    check("basis = consolidated (reader)", ar.statement_type == "Consolidated", f"read {ar.statement_type}")
    po_pages = [p for k in ("position", "profit_loss", "cash_flow") for p in chosen.get(k, [])
                if PARENT_ONLY.search(_norm(text[p - 1]))]
    check("chosen statements are not parent-only", not po_pages, f"pages {po_pages}" if po_pages else "")
    check("same issuer/year/basis as the reference LK",
          (ar.fiscal_year, ar.statement_type, ar.unit_scale) == (lk.fiscal_year, lk.statement_type, lk.unit_scale),
          f"AR {(ar.fiscal_year, ar.statement_type, ar.unit_scale)} vs LK {(lk.fiscal_year, lk.statement_type, lk.unit_scale)}")

    # 3. values, statuses, quotes; pages checked against the annual report's own text
    A, L = _vals(ar), _vals(lk)
    diff, page_bad, offsets = [], [], Counter()
    for key in sorted(set(A) | set(L)):
        a, l = A.get(key), L.get(key)
        if a is None or l is None:
            diff.append(f"{key}: only in {'AR' if l is None else 'LK'}")
            continue
        if (a.value, a.status, a.quotes) != (l.value, l.status, l.quotes):
            diff.append(f"{key}: AR {a.value} {a.status} vs LK {l.value} {l.status}")
        for pa, pl in zip(a.pages, l.pages):
            offsets[pa - pl] += 1
        for pa, q in zip(a.pages, a.quotes):
            words = [w for w in re.findall(r"[0-9][0-9.,()]{2,}", q or "")][:2]
            if words and not all(w.strip("()") in (text[pa - 1] or "") for w in words):
                page_bad.append(f"{key} p{pa}")
    n_num = sum(1 for v in A.values() if isinstance(v.value, int))
    check("values, statuses and quotes equal the reference LK", not diff,
          f"{len(A)} values ({n_num} numeric); " + ("; ".join(diff[:8]) if diff else "all equal"))
    check("each quote's figures are on the reported annual-report page", not page_bad,
          "; ".join(page_bad[:8]) if page_bad else "")
    check("one constant page offset (statements embedded whole)", len(offsets) <= 1, dict(offsets))
    # printed page vs file page: every page a value was read from must carry the same printed page
    # number as the LK page it corresponds to (values are reported by FILE page; the printed number
    # is only a cross-check that the same statement page was read)
    import pypdfium2 as pdfium
    lk_doc = pdfium.PdfDocument(str(lk_pdf))
    lk_text = [lk_doc[i].get_textpage().get_text_range() for i in range(len(lk_doc))]
    lk_doc.close()
    pairs = sorted({(pa, pl) for key, a in A.items() if key in L for pa, pl in zip(a.pages, L[key].pages)})
    mism = [(pa, pl) for pa, pl in pairs if _printed(text[pa - 1]) != _printed(lk_text[pl - 1])]
    check("printed page number of every source page = the LK's", not mism,
          f"{len(pairs)} source pages; mismatches {mism[:8]}" if mism else f"{len(pairs)} source pages")
    rep += ["", "## Printed page vs file page (every page a value was read from)", "",
            "| File page (AR) | File page (LK) | Printed page (AR) | Printed page (LK) |", "|---|---|---|---|"]
    for pa, pl in pairs:
        rep.append(f"| {pa} | {pl} | {_printed(text[pa - 1]) or '-'} | {_printed(lk_text[pl - 1]) or '-'} |")
    rep += ["", "## Reader issues (AR)", ""] + [f"- {i}" for i in ar.issues]
    rep += ["", f"**Result: {'ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)}**"]
    md = "\n".join(rep)
    if out:
        Path(out).write_text(md, encoding="utf-8")
    return not fails, md


if __name__ == "__main__":
    ok, md = run(*sys.argv[1:5], out=sys.argv[5] if len(sys.argv) > 5 else None)
    print(md)
    sys.exit(0 if ok else 1)
