"""Phase 2b: read the items the M-score needs from the NOTES of a digital IDX annual report.

Items: corporate income tax payable (D-03), owned-PPE depreciation, right-of-use (ROU)
assets and their depreciation (D-08, G-23 / DP-04), intangible amortisation (G-22 / DP-01/02),
and whether other (non-PPE) depreciation is present (Q2-c).

Approach: a fast text index of every page (pypdfium2) finds candidate pages; only those pages
are parsed word by word (pdfplumber) with the same line reader as the primary statements.
Every value keeps its page and line. Anything that needs judgement is REVIEW; anything not
found is reported as such, never filled in.
"""
from __future__ import annotations

import re

import pypdfium2 as pdfium

from .pdf_reader import AMOUNT_DOTTED, NIL, Value, _is_certain_amount, _lines, _norm, _split_label_only, parse_amount
from .text import Amt, Msg, Pages, Psak, Raw, join

NOTE_HEADING = re.compile(r"(?m)^\s*(\d{1,2})\.\s+([A-Z][A-Z0-9 ,.'’()/&\-]{3,})")


def _num(txt):
    """parse_amount, but a token with unbalanced brackets ("24)", "(Catatan") is never a figure."""
    if txt.count("(") != txt.count(")"):
        return None
    return parse_amount(txt)


HEADER_WORD = re.compile(r"^(\(?20\d\d\)?[/,]?|31,?|30,?|desember|december|juni|june|catatan|notes|/|dalam|in|rupiah|rp|usd|"
                         r"dolar|dollar|as|us|penuh|full)$", re.I)
YEAR = re.compile(r"20\d\d")


def _year_header(ln, fiscal_year=None):
    """{"t"/"t1": (year, x-centre)} when the line is a column header such as '2021 2020' or
    '31 Desember 2021/ 31 Desember 2020/'. A one-year header ('2020', first year of a new
    standard) is accepted when the fiscal year is known."""
    if not ln.words:
        return None
    digits = [w.text.strip() for w in ln.words]
    if len(digits) in (4, 8) and all(re.match(r"^\d$", d) for d in digits):     # "2 0 2 1   2 0 2 0"
        cols, order = {}, []
        for k in range(0, len(digits), 4):
            y = int("".join(digits[k:k + 4]))
            if not 2000 <= y <= 2099:
                return None
            cols.setdefault(y, (ln.words[k].x0 + ln.words[k + 3].x1) / 2)
            order.append(y)
        years = sorted(cols, reverse=True)
        if len(years) == 2 and years[0] - years[1] == 1:
            return {"t": (years[0], cols[years[0]]), "t1": (years[1], cols[years[1]]), "t_first": order[0] == years[0]}
        if len(years) == 1 and fiscal_year in (years[0], years[0] + 1):
            side = "t" if years[0] == fiscal_year else "t1"
            return {side: (years[0], cols[years[0]]), "t_first": True}
        return None
    if not all(HEADER_WORD.match(w.text.strip()) for w in ln.words):
        return None
    cols = {}
    for w in ln.words:
        m = YEAR.search(w.text)
        if m:
            cols.setdefault(int(m.group()), (w.x0 + w.x1) / 2)
    years = sorted(cols, reverse=True)
    if len(years) == 2 and years[0] - years[1] == 1:
        first = int(YEAR.search(next(w.text for w in ln.words if YEAR.search(w.text))).group())
        return {"t": (years[0], cols[years[0]]), "t1": (years[1], cols[years[1]]), "t_first": first == years[0]}
    if len(years) == 1 and fiscal_year in (years[0], years[0] + 1) and sum(bool(YEAR.search(w.text)) for w in ln.words) == 1:
        side = "t" if years[0] == fiscal_year else "t1"
        return {side: (years[0], cols[years[0]]), "t_first": True}
    return None


def _by_column(ln, cols):
    """{t, t1} from figures right-aligned under the year headers, or None (not a year-column line)."""
    centres = {c: cols[c][1] for c in ("t", "t1") if c in cols}
    if len(centres) == 2:
        tol = 0.6 * abs(centres["t"] - centres["t1"])
    else:
        tol = 25.0
    hits = {}
    for i, w in enumerate(ln.words):
        txt = w.text.strip()
        v = _num(txt)
        if v is None:
            continue
        col = next((c for c, x in centres.items() if abs(w.x1 - x) <= tol), None)
        if col is None:
            prev = ln.words[i - 1].text.strip() if i else ""
            if re.match(r"^\(\d{1,2}\)$", txt) and re.match(r"^\d{1,2}$", prev):
                continue            # "Pasal 4 (2)": label text
            if txt not in NIL and (AMOUNT_DOTTED.match(txt.strip("()")) or _num(prev) is not None):
                return None         # a figure in another column: not a year-column line
            continue
        if col in hits:
            return None
        hits[col] = (v, w)
    if not hits:
        return None
    used = [w for _, w in hits.values()]
    left = min(w.x0 for w in used)
    label = " ".join(w.text for w in ln.words if w.x1 < left and not any(w is u for u in used))
    return {c: v for c, (v, _) in hits.items()}, label


LABEL_NUMBER = re.compile(r"^(\d{1,2}|\(\d{1,2}\))$")


def _by_order(ln, cols):
    """Fallback when the text positions in the PDF do not match what is printed: the first run
    of figures, read in order. Leading numbers in the run must look like label text ("Pasal 25",
    "4 (2)"); a bare one- or two-digit number directly before a large figure is not accepted as
    a pair (it may be a label number with one figure missing). Otherwise None."""
    sides = [c for c in ("t", "t1") if c in cols]
    need = len(sides)
    order = sides if cols.get("t_first", True) else sides[::-1]
    words = ln.words
    i = 0
    while i < len(words):
        if _num(words[i].text.strip()) is None:
            i += 1
            continue
        j = i
        while j < len(words) and _num(words[j].text.strip()) is not None:
            j += 1
        run = words[i:j]
        if len(run) >= need:
            extra, pair = run[:-need], run[-need:]
            if not all(LABEL_NUMBER.match(w.text.strip()) for w in extra):
                return None
            vals = [_num(w.text.strip()) for w in pair]
            if need == 2 and re.match(r"^\d{1,2}$", pair[0].text.strip()) and AMOUNT_DOTTED.match(pair[1].text.strip("()")):
                return None
            label = " ".join(w.text for w in words[:i] + extra)
            return dict(zip(order, vals)), label
        i = j
    return None


def note_lines(lines, fiscal_year=None):
    """Assign the year figures of note-table lines.

    Primary method: column position. In the note tables of the test reports the figures are
    right-aligned under (or just right of) the year header, so a figure belongs to a year when its
    right edge lies within 0.6 x the column spacing of that year's header centre. Numbers
    elsewhere on the line ("Pasal 21", "4 (2)", the English label) are label text, and a line with
    figures outside the year columns (a movement table) gets no amounts.

    Fallback, line by line: when the column method finds nothing (text positions in the PDF do
    not match what is printed, as in parts of SIDO 2020), figures are read in order
    (`_by_order`). Each line records the method used (`ln.method`). Every value taken from the
    notes is reconciled to a total or to the face before it is FOUND.
    """
    cols, pending = None, []
    for ln in lines:
        ln.amounts, ln.label, ln.full_label, ln.method, ln.n_cols = {}, "", "", "", 0
        hdr = _year_header(ln, fiscal_year)
        ln.is_header = bool(hdr)
        if hdr:
            cols = hdr
            continue
        got = None
        if cols is not None:
            got = _by_column(ln, cols)
            method = "column"
            if not got or len(got[0]) < len([c for c in ("t", "t1") if c in cols]):
                alt = _by_order(ln, cols)
                if alt and (not got or len(alt[0]) > len(got[0])):
                    got, method = alt, "order"
        ln.n_cols = len([c for c in ("t", "t1") if c in cols]) if cols else 0
        if got:
            ln.amounts, ln.label, ln.method = got[0], got[1], method
            ln.full_label = " ".join([q.label for q in pending[-5:]] + [ln.label]).strip()
            pending = []
        else:
            ln.label = " ".join(w.text for w in _split_label_only(ln.words))
            if ln.label:
                pending.append(ln)
    return lines


class PageCache:
    """Word-level lines of note pages, parsed on demand, with figures assigned to t / t-1."""

    def __init__(self, plumber_pdf, pdf_path, fiscal_year=None, text=None, notes_start=None, fmt="dot"):
        self.pdf = plumber_pdf
        self.fmt = fmt
        self.fiscal_year = fiscal_year
        self.notes_start = notes_start
        if text is None:
            doc = pdfium.PdfDocument(str(pdf_path))
            text = [doc[i].get_textpage().get_text_range().replace("\ufffe", "") for i in range(len(doc))]
            doc.close()
        self.text = text
        self._lines = {}

    def lines(self, p):
        if p not in self._lines:
            self._lines[p] = note_lines(_lines(self.pdf.pages[p - 1], p, self.fmt), self.fiscal_year)
        return self._lines[p]

    def pages_matching(self, *patterns, start=1):
        out = []
        for i, txt in enumerate(self.text, start=1):
            if i >= start and all(re.search(p, txt) for p in patterns):
                out.append(i)
        return out

    def heading_before(self, p, idx):
        """The most recent numbered note heading ("16. ASET HAK GUNA, NETO (lanjutan)") above line idx of page p."""
        rx = re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Za-z0-9 ,.'’()/&\-]{3,60})$")
        for q in range(p, max(0, p - 15), -1):
            lines = self.lines(q)
            stop = idx if q == p else len(lines)
            for ln in reversed(lines[:stop]):
                m = rx.match(ln.label.strip())
                if m and not ln.amounts and len(m.group(2).split()) <= 8 and not m.group(2).rstrip().endswith((".", ":")):
                    return m.group(2).upper()
        return ""


def _pair(field, ln, status, note="", components=""):
    return [Value(field, c, abs(ln.amounts[c]) if c in ln.amounts else None,
                  status if c in ln.amounts else "NOT FOUND", [ln.page], [ln.text], components, note)
            for c in ("t", "t1")]


def _missing(field, status, note):
    return [Value(field, c, None, status, note=note) for c in ("t", "t1")]


def _sum_lines(field, lines, status, note):
    out = []
    for c in ("t", "t1"):
        vals = [ln.amounts.get(c) for ln in lines]
        if lines and all(v is not None for v in vals):
            out.append(Value(field, c, sum(abs(v) for v in vals), status, [ln.page for ln in lines],
                             [ln.text for ln in lines], join([Amt(abs(v)) for v in vals], " + "), note))
        else:
            out.append(Value(field, c, None, "NOT FOUND", note=note))
    return out


# ------------------------------------------------------------------------------ allocation tables

ALLOC_TITLE = re.compile(r"^(beban |pembebanan )?(penyusutan|amortisasi|depresiasi)( dan (penyusutan|amortisasi))?\b.*"
                         r"(dibebankan|dialokasikan|untuk tahun|adalah sebagai berikut|sebagai berikut)"
                         r"|^(beban|pembebanan) (penyusutan|amortisasi|depresiasi)\b")


def _kind(text):
    t = text.upper()
    if re.search(r"HAK GUNA|HAK-GUNA|RIGHT-OF-USE|RIGHT OF USE|HAK UNTUK MENGGUNAKAN|HAK PAKAI", t):
        return "ROU"
    if re.search(r"PROPERTI INVESTASI|INVESTMENT PROPERT", t):
        return "INVESTMENT_PROPERTY"
    if re.search(r"TAK ?BERWUJUD|INTANGIBLE|PERANGKAT LUNAK|SOFTWARE", t):
        return "INTANGIBLE"
    if re.search(r"ASET TETAP|FIXED ASSETS|PROPERTY, PLANT", t):
        return "PPE"
    return None


def _complete(ln):
    """The line carries a figure for every year column of its table header."""
    return bool(ln.amounts) and len(ln.amounts) == getattr(ln, "n_cols", 2) and ln.n_cols > 0


def allocation_tables(cache, first_note_page):
    """Every 'depreciation / amortisation charged (allocated) as follows' table with its total line.

    Returns dicts: kind (PPE / ROU / INTANGIBLE / INVESTMENT_PROPERTY / OTHER), the title text,
    the note heading it sits under, the total line and the component lines. The kind comes from
    the table title when it names the asset class, otherwise from the note heading.
    """
    tables = []
    for p in cache.pages_matching(r"(?i)(penyusutan|amortisasi|depresiasi)", start=first_note_page):
        lines = cache.lines(p)
        for i, ln in enumerate(lines):
            lab = _norm(ln.label)
            if ln.amounts or not ALLOC_TITLE.search(lab) or "akumulasi" in lab:
                continue
            title = " ".join(_norm(x.label) for x in lines[i:i + 3] if not x.amounts)
            comps, total, started = [], None, False
            for k, nxt in enumerate(lines[i + 1:i + 25]):
                nl = _norm(nxt.label)
                if getattr(nxt, "is_header", False):
                    started = True
                    continue
                if not started:
                    if k > 8 or re.match(r"^\d{1,2}\.\s", nxt.label.strip()):
                        break                       # a new note starts before any table (KOIN 2021: a sentence)
                    continue
                if _complete(nxt):
                    if re.match(r"^(total|jumlah)\b", nl):
                        total = nxt
                        break
                    if not nl and len(comps) >= 2 and all(
                            sum(x.amounts.get(c, 0) for x in comps) == nxt.amounts[c] for c in nxt.amounts):
                        total = nxt                     # total line printed without a label (FASW 2021)
                        break
                    comps.append(nxt)
                elif nxt.label and not nxt.amounts and ALLOC_TITLE.search(nl):
                    break
                elif comps and re.match(r"^\d{1,2}\.\s", nxt.label):
                    break
            single = total is None and len(comps) == 1
            if single:
                total, comps = comps[0], []
            if total is None:
                continue
            heading = cache.heading_before(p, i)
            kind = _kind(title) or _kind(heading) or "OTHER"
            sums = {}
            for c in total.amounts:
                if comps:
                    sums[c] = sum(x.amounts.get(c, 0) for x in comps) == total.amounts[c]
            tables.append({"kind": kind, "heading": heading, "page": p, "total": total, "components": comps,
                           "title": title, "single_line": single, "components_sum_ok": sums,
                           "combined": bool(re.search(r"penyusutan dan amortisasi|amortisasi dan penyusutan", title))})
    return tables


def _movement_additions(cache, table, value):
    """Is `value` printed in a movement-table row of accumulated depreciation/amortisation in the
    same note? (A row with four or more figures whose label is a total of accumulated
    depreciation or 'amortisasi tahun berjalan'.) Confirms what the allocation table covers."""
    rx = re.compile(r"^(total|jumlah|sub-?total)?\s*(akumulasi )?(penyusutan|amortisasi|depresiasi)|^(total|jumlah|sub-?total)$", re.I)
    for q in range(max(1, table["page"] - 3), table["page"] + 1):
        lines = cache.lines(q)
        in_acc = False
        for ln in lines:
            low = _norm(" ".join(w.text for w in ln.words))
            if re.search(r"akumulasi (penyusutan|amortisasi|depresiasi)", low) and not ln.amounts:
                in_acc = True
            nums = [_num(w.text.strip()) for w in ln.words]
            nums = [abs(v) for v in nums if v is not None]
            if len(nums) >= 4 and value in nums[1:3] and (in_acc or "akumulasi" in low) and rx.search(_norm(ln.label) or low):
                return ln
    return None


# ------------------------------------------------------------------------------ ROU presented within PPE

ROU_CLASS = re.compile(r"^(aset hak[ -]guna|hak untuk menggunakan aset|right[ -]of[ -]use)")
NOT_ROU_CLASS = re.compile(r"hak guna (bangunan|usaha)|\bhg[bu]\b|reklasifikasi|pengalihan|transfer|dipindahkan")
ROU_IN_PPE_TEXT = re.compile(r"(aset tetap|fixed assets)[^.]{0,80}\b(termasuk|mencakup|includes?|including)\b[^.]{0,40}"
                             r"(aset hak[ -]guna|right[ -]of[ -]use)", re.I)


def rou_within_ppe(cache, ppe_table):
    """PSAK 116 ¶47(a)(i): right-of-use assets may be presented within the PPE line item. Then the
    owned-PPE depreciation read from the fixed-asset note already contains ROU depreciation, and
    the PPE carrying amount already contains the ROU assets; adding the ROU figures again would
    count them twice (Keterbatasan 3.7, approved for closing by Gail 23 Oct 2026).

    Evidence, only inside the fixed-asset note (the note heading above the line must be a PPE
    note): a movement-table row for the ROU asset class (three or more figures), or a sentence
    stating that fixed assets include right-of-use assets. 'Hak Guna Bangunan/Usaha' (land titles)
    and reclassification rows are not ROU classes. Returns (page, text) or None.
    """
    if not ppe_table:
        return None
    p0 = ppe_table["page"]
    for q in range(max(1, p0 - 4), p0 + 2):
        lines = cache.lines(q)
        for i, ln in enumerate(lines):
            lab = _norm(ln.label)
            if not ROU_CLASS.search(lab) or NOT_ROU_CLASS.search(lab):
                continue
            figures = [w for w in ln.words if _num(w.text.strip()) is not None and re.search(r"\d{1,3}(\.\d{3})+", w.text)]
            if len(figures) >= 3 and _kind(cache.heading_before(q, i)) == "PPE":
                return q, ln.text
        txt = re.sub(r"\s+", " ", cache.text[q - 1] if q <= len(cache.text) else "")
        for m in ROU_IN_PPE_TEXT.finditer(txt):
            if not NOT_ROU_CLASS.search(m.group(0).lower()):
                idx = next((k for k, x in enumerate(lines) if "hak guna" in x.text.lower() or "right-of-use" in x.text.lower()), 0)
                if _kind(cache.heading_before(q, idx)) == "PPE":
                    return q, m.group(0)[:160]
    return None


def combine_ppe_depreciation(own, rdep, rou_inside_ppe, fiscal_year=None):
    """ppe_depreciation_disclosed (G-23 / DP-04, M-01), with the ROU-within-PPE guard (PSAK 116 ¶47(a)(i)).

    Returns (value, components, note, status, rou_added). When ROU assets are presented within fixed
    assets, the fixed-asset depreciation already contains ROU depreciation: it is used alone, REVIEW.
    """
    if rou_inside_ppe:
        return (own.value, Msg("comp.ppe_incl_rou", a=Amt(own.value)),
                Msg("note.dep_rou_inside", psak116=Psak("116", "73", fiscal_year, "¶47(a)(i)")),
                "REVIEW", False)
    if rdep is not None and rdep.value is not None:
        st = "BUILT FROM DISCLOSED COMPONENTS"
        if own.status == "REVIEW" or rdep.status == "REVIEW":
            st = "REVIEW"
        return (own.value + rdep.value, Msg("comp.owned_rou", a=Amt(own.value), b=Amt(rdep.value)),
                Msg("note.dep_owned_rou"), st, True)
    st = "REVIEW" if own.status == "REVIEW" or (rdep is not None and rdep.status == "REVIEW") else own.status
    return (own.value, Msg("comp.owned", a=Amt(own.value)), Msg("note.dep_owned_only"), st, False)


# ------------------------------------------------------------------------------ tax payable (D-03)

CORPORATE = re.compile(r"\b(pasal|pph|article)\s*(25|29)\b|pph badan|pajak penghasilan badan|corporate income tax"
                       r"|kurang bayar pajak penghasilan|underpayment of (current )?income tax")
TAX_TOTAL = re.compile(r"^(total|jumlah)\b|^utang pajak penghasilan( badan)?$")
WITHHOLDING_OR_OTHER = re.compile(r"\b(pasal|pph|article)\s*(4\s*\(2\)|4 ayat 2|15\b|21\b|22\b|23\b|26\b)|pertambahan nilai|ppn|"
                                  r"bumi dan bangunan|daerah|restoran|pajak final|lain-lain|lainnya|others|pajak pembangunan"
                                  r"|pajak hotel|pajak air|pajak reklame|pajak penghasilan final|income tax final|final income tax")
FOREIGN = re.compile(r"luar negeri|foreign")


def _tax_blocks(cache, first_note_page):
    """Two-year tables in the tax note: runs of lines ending in a Total/Jumlah line that contain
    at least one Article 25/29 (corporate income tax) line. A table may continue on the next page."""
    pages = sorted(set(cache.pages_matching(r"(?i)(pasal|pph|article)\s*2[59]\b", start=first_note_page))
                   | set(cache.pages_matching(r"(?i)utang pajak|taxes payable", start=first_note_page)))
    seen, out = set(), []
    for p in pages:
        for q in (p, p + 1):
            if q in seen or q > len(cache.text):
                continue
            seen.add(q)
    block, closed = [], []                    # closed: tables of this note already ended by a total
    prev_page = None
    for q in sorted(seen):
        if prev_page is not None and q != prev_page + 1:
            block, closed = [], []
        prev_page = q
        head, prepaid = "", False
        for ln in cache.lines(q):
            own = _norm(ln.label)
            if re.match(r"^\d{1,2}\.\s", ln.label.strip()) and not re.search(r"(lanjutan|continued)", own):
                block, closed = [], []
                head = ""
                continue
            if not ln.amounts and own:
                head = own                    # e.g. "Pasal 25" above "Perusahaan" / "Entitas anak" (SILO 2021)
                if PREPAID_HEAD.search(own):
                    prepaid = True            # a prepaid-tax table is not a payable (BIPP 2021)
                elif re.search(r"utang pajak|taxes payable|kurang bayar|underpayment", own):
                    prepaid = False
                continue
            if prepaid:
                if not own or TAX_TOTAL.search(own):
                    prepaid = False           # the prepaid table ends at its total
                continue
            ln.tax_head = head if ENTITY_ROW.match(own) else ""
            if not ENTITY_ROW.match(own):
                head = ""
            if "t" not in ln.amounts or "t1" not in ln.amounts:
                continue
            unlabelled_total = not own and len(block) >= 2 and all(
                sum(x.amounts[c] for x in block if not re.match(r"^(sub-? ?total|sub jumlah|subjumlah)", _norm(x.label)))
                == ln.amounts[c] for c in ("t", "t1"))
            if TAX_TOTAL.search(own) or unlabelled_total:
                if not block:
                    grand = _grand_total(closed, ln)
                    if grand:
                        out.append((grand, ln))
                    continue
                out.append((_reconciling_suffix(block, ln), ln))   # tax_payable picks the table for the face
                closed.append(out[-1])
                block = []
                continue
            block.append(ln)
    return out


def _grand_total(closed, total):
    """A total straight after other totals (BIPP 2021: 'Perusahaan' table, 'Entitas anak' table, then
    'JUMLAH'): the lines of the last two or more tables of the note, when their totals add up to it in
    both years. Otherwise None."""
    for k in range(2, len(closed) + 1):
        tail = closed[-k:]
        if all(sum(abs(t.amounts[c]) for _, t in tail) == abs(total.amounts[c]) for c in ("t", "t1")):
            return [x for b, _ in tail for x in b]
    return None


def _reconciling_suffix(block, total):
    """A run of lines can carry an earlier table that was not closed by a total (FASW 2021: the prepaid-tax
    credits sit just above the payable lines). Keep the longest run ending at the total whose lines add up to
    it in both years; when none does, keep the whole run (tax_payable then reports the mismatch)."""
    def adds_up(lines):
        rows = [x for x in lines if not re.match(r"^(sub-? ?total|sub jumlah|subjumlah)", _norm(x.label))]
        return rows and all(sum(abs(x.amounts[c]) for x in rows) == abs(total.amounts[c]) for c in ("t", "t1"))
    if adds_up(block):
        return block
    for k in range(1, len(block)):
        if adds_up(block[k:]):
            return block[k:]
    return block


PREPAID_HEAD = re.compile(r"dibayar di ?muka|prepaid|lebih bayar|taksiran tagihan|klaim (restitusi|pengembalian)|"
                          r"estimated claims|tax refund")
ENTITY_ROW = re.compile(r"^(perusahaan|perseroan|entitas (induk|anak)|anak perusahaan|the company|subsidiar(y|ies))$")


def _corporate(ln):
    """Article 25/29 line: by its own label, by the heading it was wrapped from, or an entity row ('Perusahaan',
    'Entitas anak') listed under an Article 25/29 heading."""
    if CORPORATE.search(_norm(ln.label)):
        return True
    if ENTITY_ROW.match(_norm(ln.label)):
        return bool(CORPORATE.search(getattr(ln, "tax_head", "") or ""))
    return bool(CORPORATE.search(_norm(ln.full_label or "")))


def tax_payable(cache, first_note_page, face_tax_line):
    """Corporate income tax payable of the group (D-03) from the taxes-payable table of the tax note.

    The table is the one whose total equals the face 'Utang pajak' line; a table that only
    contains Article 25/29 lines but does not reconcile to the face is REVIEW.
    """
    blocks = _tax_blocks(cache, first_note_page)

    def matches_face(total):
        return face_tax_line is not None and all(
            c in face_tax_line.amounts and abs(total.amounts[c]) == abs(face_tax_line.amounts[c]) for c in ("t", "t1"))

    corp_blocks = [(b, t) for b, t in blocks if any(_corporate(x) for x in b)]
    if not corp_blocks:
        # Trial 1 (NRCA, KOIN 2021): the full taxes-payable table agrees with the face and holds no Article 25/29
        # line (e.g. construction under final tax, or an overpayment). D-03 then gives 0, from evidence. REVIEW.
        face_block = next(((b, t) for b, t in blocks if matches_face(t) and b), None)
        if face_block and all(WITHHOLDING_OR_OTHER.search(_norm(x.label)) or re.match(
                r"^(sub-? ?total|sub jumlah|subjumlah)", _norm(x.label)) for x in face_block[0]):
            b, t = face_block
            return ([Value("taxes_payable", c, 0, "REVIEW", [t.page], [t.text], note=Msg("note.tax_zero_evidence", p=t.page))
                     for c in ("t", "t1")],
                    [(Msg("check.tax_face"), c, True, "") for c in ("t", "t1")], [])
        return _missing("taxes_payable", "NOT FOUND", Msg("note.tax_none")), [], []

    match = next(((b, t) for b, t in corp_blocks if matches_face(t)), None)
    if match is None and face_tax_line is not None:
        # rule 7: a table that does not agree with 'Utang pajak' on the face may be another table (prepaid tax,
        # tax expense); its Article 25/29 lines are not used
        return _missing("taxes_payable", "NOT FOUND", Msg("note.tax_no_face_match")), [], []
    block, total = match or corp_blocks[0]
    issues, corp, excluded, unknown = [], [], [], []
    for ln in block:
        own = _norm(ln.label)
        if re.match(r"^(sub-? ?total|sub jumlah|subjumlah)", own):
            continue
        if _corporate(ln):
            corp.append(ln)
        elif FOREIGN.search(own):
            excluded.append(ln)
            issues.append(Msg("issue.tax_foreign", line=Raw(ln.text[:60])))
        elif WITHHOLDING_OR_OTHER.search(own):
            excluded.append(ln)
        else:
            unknown.append(ln)
    checks = []
    for c in ("t", "t1"):
        parts = sum(abs(ln.amounts[c]) for ln in corp + excluded + unknown)
        checks.append((Msg("check.tax_components"), c, parts == abs(total.amounts[c]),
                       Msg("check.detail_vs", a=Amt(parts), b=Amt(abs(total.amounts[c])))))
        if face_tax_line is not None and c in face_tax_line.amounts:
            checks.append((Msg("check.tax_face"), c,
                           abs(total.amounts[c]) == abs(face_tax_line.amounts[c]), ""))
    status = "FOUND"
    if unknown:
        status = "REVIEW"
        issues.append(Msg("issue.tax_unclassified", lines=Raw("; ".join(u.text[:50] for u in unknown))))
    if not all(ok for _, _, ok, _ in checks) or face_tax_line is None:
        status = "REVIEW"
    note = Msg("note.tax")
    if excluded and any(FOREIGN.search(_norm(x.label)) for x in excluded):
        note = join([note, Msg("note.tax_foreign")])
    return _sum_lines("taxes_payable", corp, status, note), checks, issues


# ------------------------------------------------------------------------------ intangible amortisation

FX_LINE = re.compile(r"selisih kurs|penjabaran|translation")


def intangible_amortisation(cache, first_note_page):
    """Amortisation for the year from the intangible-asset note, if printed.

    Looks, under a note heading that names intangible assets, for a block titled 'Amortisasi
    tahun berjalan' / 'Beban amortisasi' (component lines and a sub-total) or a single line with
    that label. Returns dict(value {t, t1}, lines, sum_ok, fx_excluded) or None. Foreign-currency
    translation lines inside the block are not amortisation and are left out of the value; the
    sub-total check uses all lines with their signs.
    """
    title = re.compile(r"^(amortisasi|beban amortisasi|penambahan amortisasi)( tahun berjalan| periode berjalan)?$")
    for p in cache.pages_matching(r"(?i)amortisasi", r"(?i)tak ?berwujud|intangible", start=first_note_page):
        lines = cache.lines(p)
        for i, ln in enumerate(lines):
            lab = _norm(ln.label)
            if not title.match(lab) or _kind(cache.heading_before(p, i)) != "INTANGIBLE":
                continue
            if _complete(ln):
                return {"value": {c: abs(v) for c, v in ln.amounts.items()}, "lines": [ln], "sum_ok": True, "fx": []}
            comps = []
            for nxt in lines[i + 1:i + 12]:
                nl = _norm(nxt.label)
                if not _complete(nxt):
                    if comps and nxt.amounts:
                        break
                    continue
                if re.match(r"^(sub-? ?total|total|jumlah)\b", nl):
                    ok = all(sum(x.amounts[c] for x in comps) == nxt.amounts[c] for c in nxt.amounts)
                    fx = [x for x in comps if FX_LINE.search(_norm(x.label))]
                    am = [x for x in comps if x not in fx]
                    value = {c: abs(sum(x.amounts[c] for x in am)) for c in nxt.amounts}
                    return {"value": value, "lines": am + [nxt], "sum_ok": ok, "fx": fx}
                comps.append(nxt)
    return None


def _intangibles_present(cache, first_note_page, face_values):
    if any(v.field == "intangible_assets_net" and v.value for v in face_values):
        return next(v for v in face_values if v.field == "intangible_assets_net")
    for p in cache.pages_matching(r"(?i)perangkat lunak|piranti lunak|tak ?berwujud|lisensi", start=first_note_page):
        for ln in cache.lines(p):
            if re.search(r"^(sistem )?(perangkat|piranti) lunak|^aset tak ?berwujud|^lisensi", _norm(ln.label)) and ln.amounts \
                    and any(abs(v) > 0 for v in ln.amounts.values()):
                return ln
    return None


# ------------------------------------------------------------------------------ non-PPE evidence (M-06)

NON_PPE_GROUPS = [
    ("investment_property", "Properti investasi", r"properti investasi|investment propert"),
    ("unused_assets", "Aset yang tidak digunakan / dihentikan penggunaannya",
     r"aset tetap (yang )?tidak digunakan|aset (yang )?tidak digunakan|dihentikan penggunaannya|aset tidak produktif"
     r"|unused (fixed )?assets|idle assets"),
    ("long_term_costs", "Amortisasi biaya jangka panjang (biaya ditangguhkan, hak atas tanah, dll.)",
     r"biaya (yang )?ditangguhkan|beban tangguhan|deferred charges|amortisasi biaya|biaya pengurusan hak"
     r"|biaya perpanjangan hak"),
]
NOTE_LINE = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Za-z0-9 ,.'’()/&\-]{3,80}?)\s*(?=\s\d{1,2}\.\s|$)")


def note_headings(cache, first_note_page):
    """Numbered note headings in order ("10. Aset tetap"), Indonesian part, for the notes-examined list."""
    out = {}
    for i in range(first_note_page, len(cache.text) + 1):
        for raw in cache.text[i - 1].splitlines():
            m = NOTE_LINE.match(raw)
            if not m:
                continue
            title = re.sub(r"\s*\((lanjutan|continued)\)\s*$", "", m.group(2), flags=re.I).strip()
            if len(title.split()) > 8 or title.endswith((".", ":", ",")):
                continue
            num = int(m.group(1))
            if num not in out:
                out[num] = (f"{num}. {title}", i)
    return [{"heading": h, "page": p} for _, (h, p) in sorted(out.items())]


INVPROP_FACE = re.compile(r"^properti investasi\b")
INVPROP_SENTENCE = re.compile(
    r"(?:beban\s+)?penyusutan\s+(?:atas\s+|untuk\s+)?properti\s+investasi[^;]{0,400}?(?:sebesar|adalah)", re.I | re.S)
INVPROP_FAIR_VALUE = re.compile(r"properti investasi[^.]{0,250}?(model nilai wajar|fair value model|diukur (?:pada|sebesar|dengan) "
                                r"nilai wajar)", re.I | re.S)


MONEY_TOKEN = re.compile(r"(?<![\d.,])\(?\d{1,3}(?:[.,]\d{3})+\)?(?![\d,]|\.\d)")


def sentence_pair(after, context=""):
    """The two amounts of a disclosure sentence ("... masing-masing sebesar Rp X dan Rp Y ..."), read from
    the text that follows 'sebesar'. Bilingual pages interleave the Indonesian and English sentences, so
    the same amount can appear twice (1.327.297.173 and 1,327,297,173): figures are compared by value
    and the first two distinct values are taken. Dots or commas both read as thousands separators,
    because only figures with at least one full group of three digits are taken. The years named in
    the sentence decide the order (default: current year first). Returns {"t": x, "t1": y} or {}."""
    vals = []
    for tok in MONEY_TOKEN.findall(after):
        t = tok.strip("()")
        sep = "." if "." in t else ","
        if ("." in t) and ("," in t):
            continue
        v = int(t.replace(sep, ""))
        if v not in vals:
            vals.append(v)
        if len(vals) == 2:
            break
    if len(vals) < 2:
        return {}
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", context)]
    first_older = len(years) >= 2 and years[0] < years[1] and years[1] - years[0] == 1
    return {"t": vals[1], "t1": vals[0]} if first_older else {"t": vals[0], "t1": vals[1]}


AMORT_SENTENCE = re.compile(r"amortisasi\b[^.]{0,60}(aset tak ?berwujud|perangkat lunak|piranti lunak)[^.]{0,300}?sebesar",
                            re.I | re.S)


def amortisation_sentence(cache, first_note_page, total_assets):
    """Trial 1 (KOIN 2021): intangible amortisation given only in a sentence ("Beban amortisasi aset tak berwujud -
    perangkat lunak ... masing-masing sebesar Rp X dan Rp Y"). Accepted only below 20% of total assets for each
    year (a figure in another unit fails). Returns (values {t, t1}, page, quote) or None. REVIEW."""
    for i in range(first_note_page, len(cache.text) + 1):
        txt = " ".join(cache.text[i - 1].split())
        for m in AMORT_SENTENCE.finditer(txt):
            got = sentence_pair(txt[m.end():m.end() + 260], txt[m.start():m.end()])
            if got and all(total_assets.get(c) and 0 < got[c] <= 0.2 * total_assets[c] for c in got):
                return got, i, txt[m.start():m.end() + 80]
    return None


PPE_DEP_SENTENCE = re.compile(r"penyusutan\b(?![^.]{0,60}(properti investasi|hak guna|hak-guna|tak ?berwujud))"
                              r"[^.]{0,250}?(?:dibebankan|dialokasikan|dicatat)[^.]{0,300}?sebesar", re.I | re.S)


def ppe_depreciation_sentence(cache, first_note_page, face_ppe):
    """Trial 1 (KOIN 2021): owned-PPE depreciation given only in a sentence of the fixed-asset note,
    "Penyusutan dibebankan pada beban umum dan administrasi masing-masing sebesar Rp X dan Rp Y".
    Accepted only when each amount lies between 0,05% and 100% of the fixed assets on the face for
    that year (a figure in another unit fails). Returns (values {t, t1}, page, quote) or None."""
    for i in range(first_note_page, len(cache.text) + 1):
        raw = cache.text[i - 1]
        if not re.search(r"(?i)aset tetap", raw):
            continue
        txt = " ".join(raw.split())
        for rx, needs_ppe_note in ((PPE_DEP_SENTENCE, False), (PPE_DEP_SENTENCE_B, True)):
            for m in rx.finditer(txt):
                if needs_ppe_note:            # the sentence must sit in the fixed-asset note (not the lease note)
                    lines = cache.lines(i)
                    at = next((k for k, ln in enumerate(lines) if re.search(r"(?i)beban penyusutan", ln.text)), len(lines))
                    if not PPE_NOTE_HEAD.search(cache.heading_before(i, at) or ""):
                        continue
                got = sentence_pair(txt[m.end():m.end() + 260], txt[m.start():m.end()])
                ok = got and all(face_ppe.get(c) and 0.0005 * face_ppe[c] <= got[c] <= face_ppe[c] for c in got)
                if ok:
                    return got, i, txt[m.start():m.end() + 80]
    return None


# Trial 2 (TFAS 2021): "Beban penyusutan untuk tahun-tahun ... masing-masing sebesar Rp X dan Rp Y dialokasikan ke beban
# umum dan administrasi": the amounts come before the verb. Accepted only inside the fixed-asset note.
PPE_DEP_SENTENCE_B = re.compile(r"beban penyusutan\b(?![^.]{0,80}(properti investasi|hak guna|hak-guna|tak ?berwujud|"
                                r"right[- ]of[- ]use))[^.]{0,200}?sebesar(?=.{0,200}?(dibebankan|dialokasikan))",
                                re.I | re.S)
PPE_NOTE_HEAD = re.compile(r"ASET TETAP|PROPERTY|FIXED ASSETS|PROPERTI, PABRIK", re.I)


CARRYING = re.compile(r"^(nilai|jumlah) (tercatat|buku)\b|^nilai buku (neto|bersih)|^carrying (amount|value)|^net book value"
                      r"|^book value", re.I)


def ppe_note_carrying(cache, first_note_page, face_ppe):
    """Rule 7 cross-check (28 Oct 2026, after BIRD 2021): the fixed assets read from the face must appear as a
    carrying amount ('Nilai tercatat' / 'Jumlah tercatat' / 'Nilai buku') in the fixed-asset note.

    Returns {column: ("ok", page) | ("mismatch", [amounts seen]) | ("none", None)}. 'none' means no
    carrying-amount line was found, so the check could not be made (the figure stays REVIEW)."""
    seen, hit = [], {}
    for p in cache.pages_matching(r"(?i)aset tetap|fixed assets|property,? (plant )?and equipment", start=first_note_page):
        for ln in cache.lines(p):
            words = [w.text.strip() for w in ln.words]
            if not CARRYING.search(_norm(" ".join(words[:4]))):
                continue
            nums = {abs(v) for w in words for v in [parse_amount(w)] if v is not None and re.search(r"\d[.,]\d{3}", w)}
            seen.extend(nums)
            for c, v in face_ppe.items():
                if v in nums and c not in hit:
                    hit[c] = p
    out = {}
    for c in face_ppe:
        if c in hit:
            out[c] = ("ok", hit[c])
        elif seen:
            out[c] = ("mismatch", sorted(set(seen))[-6:])
        else:
            out[c] = ("none", None)
    return out


INVPROP_COST = re.compile(r"properti investasi[^.]{0,250}?(model biaya|cost model|biaya perolehan dikurangi akumulasi)", re.I | re.S)


def invprop_face_line(statements):
    """Investment property on the face of the statement of financial position (any year above 0)."""
    pos = statements.get("position")
    lines = pos.lines if pos else []
    for i, ln in enumerate(lines):
        if "t" not in ln.amounts or "t1" not in ln.amounts or not any(abs(ln.amounts[c]) > 0 for c in ("t", "t1")):
            continue
        back = []
        for prev in reversed(lines[max(0, i - 8):i]):           # the label may wrap over several lines (BIPP 2021)
            if "t" in prev.amounts and "t1" in prev.amounts:     # a stray date ("31") is not a figure line
                break
            back.insert(0, prev.label)
        lab = _norm(" ".join(back + [ln.label]))
        if INVPROP_FACE.search(_norm(ln.label)) or re.search(r"(?:^|\s)properti investasi\b", lab):
            ln.wrapped = lab
            return ln
    return None


def invprop_depreciation(cache, first_note_page, face_ln):
    """Trial 1, P8 (approved 28 Oct 2026): read the depreciation of investment property when no
    allocation table gives it. Two sources, both REVIEW:
      - the policy says investment property is measured at fair value: no depreciation (PSAK 213), 0;
      - a sentence "Beban penyusutan properti investasi ... sebesar Rp X dan Rp Y".
    A sentence amount is accepted only when it lies between 0,1% and 20% of the carrying amount on
    the face for that year: a figure written in another unit (full Rupiah against statements in
    thousands) fails this test and is not used. Returns ({column: amount}, source Msg) or ({}, "")."""
    cost_on_face = bool(face_ln is not None and "akumulasi penyusutan" in (getattr(face_ln, "wrapped", "")
                                                                         or _norm(face_ln.full_label or face_ln.label)))
    for i in range(first_note_page, len(cache.text) + 1):
        txt = " ".join(cache.text[i - 1].split())
        m = INVPROP_FAIR_VALUE.search(txt)
        if m and not cost_on_face and not INVPROP_COST.search(txt):
            return {"t": 0, "t1": 0}, Msg("np.source_fv", p=i, text=Raw(txt[m.start():m.end()][:90]))
    for i in range(first_note_page, len(cache.text) + 1):
        txt = " ".join(cache.text[i - 1].split())
        for m in INVPROP_SENTENCE.finditer(txt):
            pair = sentence_pair(txt[m.end():m.end() + 260], txt[m.start():m.end()])
            got = {}
            for c, v in pair.items():
                carrying = abs(face_ln.amounts.get(c) or 0) if face_ln else 0
                if carrying and 0.001 * carrying <= v <= 0.2 * carrying:
                    got[c] = v
            if got:
                return got, Msg("np.source", p=i, text=Raw(txt[m.start():m.end() + 80][:110]))
    return {}, ""


def non_ppe_evidence(cache, first_note_page, invprop_table, statements=None):
    """What the machine searched and found for the three non-PPE groups of Q6. Never a status."""
    groups = []
    for key, label, rx in NON_PPE_GROUPS:
        hits = []
        for p in cache.pages_matching("(?i)" + rx, start=first_note_page):
            for raw in cache.text[p - 1].splitlines():
                if re.search(rx, raw, re.I):
                    has_amount = bool(re.search(r"\d{1,3}([.,]\d{3}){1,}", raw))
                    hits.append({"page": p, "text": raw.strip()[:160], "with_amount": has_amount})
        groups.append({"key": key, "label": label, "found": bool(hits), "hits": hits[:8], "n_hits": len(hits)})
    amounts, source = {}, ""
    if invprop_table:
        amounts = {c: abs(v) for c, v in invprop_table["total"].amounts.items()}
        source = Msg("np.source", p=invprop_table["page"], text=Raw(invprop_table["total"].text[:80]))
    face = invprop_face_line(statements or {})
    if face is not None and not amounts:
        amounts, source = invprop_depreciation(cache, first_note_page, face)
    return {"groups": groups, "amounts_read": amounts, "amount_source": source,
            "invprop_face": {"page": face.page, "text": face.text[:90]} if face is not None else None,
            "notes": note_headings(cache, first_note_page)}


# ------------------------------------------------------------------------------ main entry

ROU_WORDS = re.compile(r"(?i)hak[ -]guna|hak untuk menggunakan aset|hak pakai|right[ -]of[ -]use")


def _val(values, f, c):
    return next((v for v in values if v.field == f and v.column == c), None)


def read_notes(cache, statements, face_values):
    """Read the note items; return (values, checks, issues, tables).

    Also builds, by rule, the two engine fields that are not printed as such:
      ppe_depreciation_disclosed = owned-PPE depreciation + ROU depreciation when the ROU
        depreciation is disclosed; owned-PPE depreciation only when it is not (G-23 / DP-04);
      depreciation_amortization_total = ppe_depreciation_disclosed + disclosed intangible
        amortisation + non-PPE D&A (DP-01/02), status BUILT FROM DISCLOSED COMPONENTS.
    """
    values, checks, issues = [], [], []
    last_stmt_page = max((p for s in statements.values() for p in s.pages), default=0)
    first_note = cache.notes_start or (last_stmt_page + 1)

    pos = statements.get("position")
    face_tax = None
    if pos:
        face_tax = next((ln for ln in pos.lines if re.match(r"^utang pajak( penghasilan)?$", _norm(ln.label))
                         and "t" in ln.amounts), None)

    # --- taxes payable (D-03)
    v, c, i = tax_payable(cache, first_note, face_tax)
    values += v
    checks += c
    issues += list(dict.fromkeys(i))

    # --- depreciation allocation tables
    tables = allocation_tables(cache, first_note)

    def pick(kind):
        return next((t for t in tables if t["kind"] == kind), None)

    check_key = {"ppe_depreciation_owned": "check.alloc_ppe", "rou_depreciation": "check.alloc_rou",
                 "amortization_intangibles": "check.alloc_intang"}

    def table_values(field, t, label):
        """Values of an allocation table total, FOUND only when reconciled. `label` is the catalogue key
        base: "<label>_ok" is used when the total was agreed to the movement schedule for both years."""
        status, notes = "FOUND", []
        if t["components"] and not all(t["components_sum_ok"].values()):
            status = "REVIEW"
            notes.append(Msg("note.alloc_components"))
        moved = {c: _movement_additions(cache, t, abs(t["total"].amounts[c])) for c in t["total"].amounts}
        for c, ln in moved.items():
            if ln is not None:          # not finding the row is "not reconciled", not a contradiction
                checks.append((Msg(check_key[field]), c, True, Msg("check.detail_page", p=ln.page)))
        reconciled = bool(moved) and all(moved.values())
        notes.insert(0, Msg(label + ("_ok" if reconciled else "")))
        if t["single_line"] and not any(moved.values()):
            status = "REVIEW"
            notes.append(Msg("note.alloc_single"))
        if t["combined"]:
            if all(moved.values()):
                notes.append(Msg("note.alloc_combined_ok"))
            else:
                status = "REVIEW"
                notes.append(Msg("note.alloc_combined"))
        if any(ln.method == "order" for ln in [t["total"]] + t["components"]):
            notes.append(Msg("note.order"))
        out = _pair(field, t["total"], status, join(notes))
        for x in out:
            x.pages = [t["page"]]
        return out

    ppe, rou, intang_t, invprop = pick("PPE"), pick("ROU"), pick("INTANGIBLE"), pick("INVESTMENT_PROPERTY")
    face_ppe = {v.column: v.value for v in face_values if v.field == "property_plant_equipment_net" and v.value}
    sent = None if ppe else ppe_depreciation_sentence(cache, first_note, face_ppe)
    if ppe:
        values += table_values("ppe_depreciation_owned", ppe, "note.alloc_ppe")
    elif sent:
        got, pg, quote = sent
        for c in ("t", "t1"):
            values.append(Value("ppe_depreciation_owned", c, got[c], "REVIEW", [pg], [quote],
                                note=Msg("note.ppe_dep_sentence")))
    else:
        values += _missing("ppe_depreciation_owned", "NOT FOUND", Msg("note.alloc_none"))
    if rou:
        values += table_values("rou_depreciation", rou, "note.alloc_rou")
    else:
        values += _missing("rou_depreciation", "NOT DISCLOSED", Msg("note.rou_dep_none"))
    for t in tables:
        if t["kind"] == "OTHER":
            issues.append(Msg("issue.table_unlinked", p=t["page"], title=Raw(t["title"][:60])))

    # --- ROU presented within PPE (PSAK 116 ¶47(a)(i)): never count it twice
    inside = rou_within_ppe(cache, ppe) if ppe else None
    face_rou = [x for x in face_values if x.field == "rou_assets_net" and x.value is not None]
    if inside and not face_rou:
        p116 = Psak("116", "73", cache.fiscal_year, "¶47(a)(i)")
        issues.append(Msg("issue.rou_inside", p=inside[0], quote=Raw(inside[1][:70]), psak116=p116))
        values += [Value("rou_assets_net", c, None, "INCLUDED IN PPE", [inside[0]], [inside[1]], "",
                         Msg("note.rou_inside", psak116=p116)) for c in ("t", "t1")]
    elif not face_rou:
        found = None
        for p in cache.pages_matching(r"(?i)hak untuk menggunakan aset|aset hak guna|aset hak-guna|right-of-use", start=first_note):
            for ln in cache.lines(p):
                if re.search(r"^(hak untuk menggunakan aset|aset hak guna|aset hak-guna)", _norm(ln.label)) and _complete(ln):
                    found = ln
                    break
            if found:
                break
        if found:
            values += _pair("rou_assets_net", found, "REVIEW", Msg("note.rou_notes"))
        elif not any(ROU_WORDS.search(txt) for txt in cache.text):
            # Gail, 28 Oct 2026: not every company has leases. When the whole report never mentions right of use
            # assets, they are taken as nil from that evidence (as G-24 for debt), and no review item is raised.
            values += [Value("rou_assets_net", c, 0, "FOUND", [], [], "", Msg("note.rou_absent")) for c in ("t", "t1")]
        else:
            values += _missing("rou_assets_net", "NOT FOUND", Msg("note.rou_none"))

    # --- intangible amortisation (G-22, DP-01/02)
    am = intangible_amortisation(cache, first_note)
    present = _intangibles_present(cache, first_note, face_values)
    if am:
        notes_am = [Msg("note.amort")]
        st = "FOUND" if am["sum_ok"] else "REVIEW"
        if not am["sum_ok"]:
            notes_am.append(Msg("note.amort_sum"))
        if am["fx"]:
            st = "REVIEW"
            # M-03 A (approved 23 Oct 2026): translation lines excluded, kept as evidence (page + line)
            notes_am.append(Msg("note.amort_fx",
                                evidence=tuple(Msg("np.source", p=x.page, text=Raw(f"'{x.text[:70]}'")) for x in am["fx"]),
                                psak238=Psak("238", "19", cache.fiscal_year, "¶118(e)(vi)/(vii)")))
        note = join(notes_am)
        for c in ("t", "t1"):
            v = am["value"].get(c)
            values.append(Value("amortization_intangibles", c, v, st if v is not None else "NOT FOUND",
                                [x.page for x in am["lines"]], [x.text for x in am["lines"]],
                                join([Amt(abs(x.amounts[c])) for x in am["lines"][:-1] if c in x.amounts], " + ")
                                if len(am["lines"]) > 1 else "", note))
        values += [Value("amort_status", c, None, "FOUND", note=Msg("note.amort_disclosed")) for c in ("t", "t1")]
        # Expense notes that show a larger 'Amortisasi' line point to other amortisation (Q2-c)
        exp = {"t": 0, "t1": 0}
        hits = []
        for p in cache.pages_matching(r"(?im)^\s*amortisasi\s+[\d(]", start=first_note):
            for ln in cache.lines(p):
                if re.match(r"^amortisasi$", _norm(ln.label)) and _complete(ln):
                    hits.append(ln)
                    for c in exp:
                        exp[c] += abs(ln.amounts.get(c, 0))
        if hits and any(exp[c] > (am["value"].get(c) or 0) for c in exp):
            issues.append(Msg("issue.expense_amort", x=join([Amt(exp[c]) for c in ("t", "t1")], " / "),
                              p=Pages(tuple(h.page for h in hits)),
                              y=join([Amt(am["value"].get(c) or 0) for c in ("t", "t1")], " / ")))
    elif intang_t:
        values += table_values("amortization_intangibles", intang_t, "note.alloc_intang")
        values += [Value("amort_status", c, None, "FOUND", note=Msg("note.amort_disclosed")) for c in ("t", "t1")]
    elif (am_sent := amortisation_sentence(cache, first_note, {v.column: v.value for v in face_values
                                                                if v.field == "total_assets" and v.value})):
        got, pg, quote = am_sent
        for c in ("t", "t1"):
            values.append(Value("amortization_intangibles", c, got[c], "REVIEW", [pg], [quote],
                                note=Msg("note.amort_sentence")))
        values += [Value("amort_status", c, None, "FOUND", note=Msg("note.amort_disclosed")) for c in ("t", "t1")]
    elif present is not None:
        q = present.quotes[0] if isinstance(present, Value) and present.quotes else getattr(present, "text", "")
        pg = present.pages if isinstance(present, Value) else [present.page]
        values += [Value("amortization_intangibles", c, 0, "UNDISCLOSED", pg, [q], Msg("comp.zero_undisclosed"),
                         Msg("note.amort_undisclosed"))
                   for c in ("t", "t1")]
        values += [Value("amort_status", c, "UNDISCLOSED", "REVIEW", pg, [q]) for c in ("t", "t1")]
    else:
        # Not found is not nil (CLAUDE.md rule 1). M-15 C (approved 23 Oct 2026): the user sets the
        # status per year (pipeline.apply_amort_decisions); until then the score is held.
        values += [Value("amortization_intangibles", c, None, "NOT ASSESSED",
                         note=Msg("note.amort_not_assessed")) for c in ("t", "t1")]
        values += [Value("amort_status", c, None, "NOT ASSESSED") for c in ("t", "t1")]

    # --- other (non-PPE) depreciation: evidence only (M-06, approved 22 Oct 2026)
    # The machine never sets the status and never enters 0 because nothing was found. It reports
    # what it searched and found; the user sets the status per year (Q6). Until then: NOT ASSESSED.
    evidence = non_ppe_evidence(cache, first_note, invprop, statements)
    for c in ("t", "t1"):
        values.append(Value("depreciation_amortization_non_ppe", c, None, "NOT ASSESSED",
                            note=Msg("note.nonppe_not_assessed")))
        values.append(Value("non_ppe_status", c, None, "NOT ASSESSED"))

    # --- fields built by rule
    for c in ("t", "t1"):
        own, rdep = _val(values, "ppe_depreciation_owned", c), _val(values, "rou_depreciation", c)
        amort, nonppe = _val(values, "amortization_intangibles", c), _val(values, "depreciation_amortization_non_ppe", c)
        if own is None or own.value is None:
            values.append(Value("ppe_depreciation_disclosed", c, None, "NOT FOUND", note=Msg("note.ppe_dep_none")))
            values.append(Value("depreciation_amortization_total", c, None, "NOT FOUND", note=Msg("note.dat_cannot")))
            continue
        ppe_v, comp, note, st, add_rou = combine_ppe_depreciation(own, rdep, bool(inside and not face_rou),
                                                                  cache.fiscal_year)
        values.append(Value("ppe_depreciation_disclosed", c, ppe_v, st, own.pages + (rdep.pages if add_rou else []),
                            own.quotes + (rdep.quotes if add_rou else []), comp, note))
        parts = [ppe_v, amort.value if amort else None, nonppe.value if nonppe else None]
        if None in parts:
            why = Msg("note.dat_wait") if parts[2] is None else Msg("note.component_missing")
            values.append(Value("depreciation_amortization_total", c, None, "NOT ASSESSED", note=why))
            continue
        tot_st = "BUILT FROM DISCLOSED COMPONENTS" if st != "REVIEW" else "REVIEW"
        values.append(Value("depreciation_amortization_total", c, sum(parts), tot_st, [],
                            [], Msg("comp.dat", a=Amt(ppe_v), b=Amt(parts[1]), c=Amt(parts[2])),
                            Msg("note.dat_built")))
    return values, checks, issues, tables, evidence
