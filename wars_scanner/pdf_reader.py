"""Phase 2 (v0): read the primary financial statements of a digital IDX annual report.

Scope of v0: the face of the statement of financial position, the statement of profit or
loss and the statement of cash flows, for the current year (t) and the comparative column
(t-1). Items that live in the notes (tax payable detail, depreciation, amortisation,
right-of-use assets shown inside other assets) are reported as NOT SEARCHED in v0.

Forensic rule: every value comes with its PDF page and the printed line it was read from.
A value that needs judgement is returned with status REVIEW. Nothing is guessed: an item
that is not found is reported as NOT FOUND, never as 0.
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber
import pypdfium2 as pdfium

from .text import Amt, Msg, Pages, Psak, Raw, join

AMOUNT_DOTTED = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})+\)?$")
AMOUNT_SMALL = re.compile(r"^\(?-?\d{1,3}\)?$")
NIL = {"-", "–", "—", "--"}
SCANNED_MIN_CHARS = 20          # a page with fewer non-space characters has no usable text layer
STATEMENT_WINDOW = 15           # the three primary statements lie within this many pages of each other
NOTES_WITHIN = 10               # the notes (CALK) start within this many pages after the last statement
NOTE_REF = re.compile(r"^\d{1,2}(?:\.?[a-z])?(?:\s?[,&.]\s?\d{1,2}(?:\.?[a-z])?)*[,.]?$", re.I)   # "3m.", "3b.3f.4" (MTPS 2021)


@dataclass
class Word:
    text: str                   # as read; figures normalised to the dot-thousands form (see number_format)
    x0: float
    x1: float
    top: float
    raw: str = ""               # the text exactly as printed (quotes always use this)


@dataclass
class Line:
    page: int          # 1-based PDF page
    top: float
    words: list
    label: str = ""
    full_label: str = ""                           # label joined with a preceding label-only line
    amounts: dict = field(default_factory=dict)   # {"t": value, "t1": value}

    @property
    def text(self):
        return " ".join(w.raw or w.text for w in self.words)


@dataclass
class Value:
    field: str
    column: str                 # "t" or "t1"
    value: Optional[int]
    status: str                 # FOUND / REVIEW / NOT FOUND / NOT SEARCHED / SCANNED PAGE
    pages: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    components: str = ""        # text.Msg (how the value was added up) or ""
    note: str = ""              # text.Msg (reads in Indonesian as a str; render(lang) for EN)


@dataclass
class Statement:
    kind: str                   # "position" / "profit_loss" / "cash_flow"
    pages: list
    lines: list


@dataclass
class Extraction:
    file_name: str
    n_pages: int
    scanned_pages: list
    fiscal_year: Optional[int]
    unit_scale: Optional[str]
    statement_type: Optional[str]
    statements: dict
    values: list
    issues: list
    checks: list = field(default_factory=list)   # (name, column, passed, detail)
    non_ppe_evidence: dict = field(default_factory=dict)   # M-06: what was searched/found, never a status
    fs_location: dict = field(default_factory=dict)        # Phase D: where the audited statements and notes were found
    transition: dict = field(default_factory=dict)         # M-08 package: transition / restated-comparative inputs + evidence
    year_labels: dict = field(default_factory=dict)        # P0-2: per statement {year, t_first, page, quote}; year None = not read
    financial_institution: list = field(default_factory=list)  # bank / insurer line items found on the face (page, label)
    number_format: str = "dot"                             # thousands separator of the figures: dot / comma / mixed
    currency: Optional[str] = None                         # IDR / USD from the statement headings; None = not read
    cross_checks: dict = field(default_factory=dict)       # rule 7: face figures found again elsewhere in the report


# ------------------------------------------------------------------------------------- parsing

def parse_amount(text: str) -> Optional[int]:
    t = text.strip()
    if t in NIL:
        return 0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if not (AMOUNT_DOTTED.match(t) or AMOUNT_SMALL.match(t)):
        return None
    v = int(t.replace(".", "").replace("-", "")) if t not in NIL else 0
    return -v if neg or t.startswith("-") else v


DOT_MULTI = re.compile(r"(?<![\d.,])\(?\d{1,3}(?:\.\d{3}){2,}\)?(?![\d.,])")
COMMA_MULTI = re.compile(r"(?<![\d.,])\(?\d{1,3}(?:,\d{3}){2,}\)?(?![\d.,])")
COMMA_AMOUNT = re.compile(r"^(\(?-?)(\d{1,3}(?:,\d{3})+)(\)?)$")
DOT_DECIMAL = re.compile(r"^\(?-?\d+\.\d+\)?$")


def number_format(texts):
    """Thousands separator of the figures in the primary statements (Trial 1, 28 Oct 2026).

    IDX reports print 1.234.567 (Indonesian style) or 1,234,567 (English style). Only figures with
    two or more groups are counted, because "22,31" (note references) or "1.234" are ambiguous.
    Returns "dot", "comma", or "mixed" when neither style clearly dominates (the figures are then
    not read: a wrong separator would multiply or divide every amount by 1,000)."""
    joined = "\n".join(texts)
    dots, commas = len(DOT_MULTI.findall(joined)), len(COMMA_MULTI.findall(joined))
    if commas >= 5 and commas >= 4 * dots:
        return "comma"
    if dots >= 5 and dots >= 4 * commas or commas < 5:
        return "dot"
    return "mixed"


UNBALANCED_CLOSE = re.compile(r"(?<![(\d.,])\d{1,3}(?:[.,]\d{3})+\)")
BALANCED = re.compile(r"\(\d{1,3}(?:[.,]\d{3})+\)")


def paren_artifact(texts):
    """Some PDFs print a closing bracket after every positive figure ("145.027)") because of the
    accounting number format; their text layer then shows unbalanced brackets. Detected per document."""
    joined = re.sub(r"\(\s+(?=\d)", "(", "\n".join(texts))     # "( 385.949)" is a normal negative figure
    un, bal = len(UNBALANCED_CLOSE.findall(joined)), len(BALANCED.findall(joined))
    return un >= 10 and un >= bal


def _normalise(text, fmt):
    """In an English-style report, rewrite figures to the dot form the reader parses: 1,234,567 ->
    1.234.567. A dot there is a decimal point (2.50 per share), so such a token is made unreadable as
    an amount instead of being taken for thousands. The printed text is kept in Word.raw."""
    if fmt.endswith("+paren") and re.match(r"^(-?\d{1,3}(?:[.,]\d{3})*|-)\)$", text):
        text = text[:-1]                              # "145.027)" -> "145.027", "-)" -> "-" (format artefact)
    if not fmt.startswith("comma"):
        return text
    m = COMMA_AMOUNT.match(text)
    if m:
        return m.group(1) + m.group(2).replace(",", ".") + m.group(3)
    if DOT_DECIMAL.match(text):
        return text.replace(".", "·")
    return text


def _open_brackets(raw):
    """Trial 2 (PYFA 2021): a negative figure printed as "( 385.949.260.966)" has its opening bracket as a
    separate word. The bracket is joined to the figure that follows on the same line."""
    out = []
    for w in raw:
        if out and out[-1]["text"] == "(" and re.match(r"^\d[\d.,]*\)?$", w["text"]) and abs(w["top"] - out[-1]["top"]) <= 3 \
                and 0 <= w["x0"] - out[-1]["x1"] < 16:
            prev = out.pop()
            w = dict(w, text="(" + w["text"], x0=prev["x0"])
        out.append(w)
    return out


def _glued(raw):
    """Trial 2 (PZZA 2021): a text layer without spaces between words ("LAPORANPOSISIKEUANGAN",
    "Bebanpenyusutanasettetapyangdialokasikanpada"). Detected by runs of letters longer than Indonesian or
    English words; the page is then read again with a tighter gap between words."""
    alpha = [w["text"] for w in raw if re.fullmatch(r"[A-Za-z(),.:/-]+", w["text"])]
    return len(alpha) >= 8 and (sum(len(a) >= 16 for a in alpha) >= 0.3 * len(alpha)
                                or sum(len(re.sub(r"[^A-Za-z]", "", a)) >= 24 for a in alpha) >= 3)


def _spaced_lines(raw):
    """Trial 2 (WSBP 2021): table lines printed letter by letter ("B e b a n P o k o k"): the tops of the lines
    where most words are single characters."""
    by = {}
    for w in raw:
        by.setdefault(round(w["top"]), []).append(w["text"])
    return {top for top, ws in by.items() if len(ws) >= 8 and sum(len(x) == 1 for x in ws) >= 0.6 * len(ws)}


def page_words(page):
    raw = page.extract_words(keep_blank_chars=False)
    if _glued(raw):
        return page.extract_words(keep_blank_chars=False, x_tolerance=1.5)
    spaced = _spaced_lines(raw)
    if spaced:
        wide = page.extract_words(keep_blank_chars=False, x_tolerance=5)
        near = lambda w: any(abs(round(w["top"]) - t) <= 1 for t in spaced)       # noqa: E731
        raw = [w for w in raw if not near(w)] + [w for w in wide if near(w)]
    return raw


def _lines(page, page_no, fmt="dot"):
    words = [Word(_normalise(w["text"], fmt), w["x0"], w["x1"], w["top"], w["text"])
             for w in _open_brackets(sorted(page_words(page), key=lambda w: (round(w["top"]), w["x0"])))]
    words.sort(key=lambda w: (round(w.top), w.x0))
    out, cur = [], []
    for w in words:
        if cur and abs(w.top - cur[0].top) > 3:
            out.append(Line(page_no, cur[0].top, sorted(cur, key=lambda x: x.x0)))
            cur = []
        cur.append(w)
    if cur:
        out.append(Line(page_no, cur[0].top, sorted(cur, key=lambda x: x.x0)))
    for ln in out:
        ln.words = _merge_split_numbers(ln.words)
    return out


NUMERIC_PIECE = re.compile(r"^[\d.()]+$")


def _merge_split_numbers(words):
    """Re-join a figure that the PDF stores as two text runs, e.g. "2" + "28.563.209.997".

    Only digits/dots/brackets touching each other (gap < 1.5 pt) are joined; the result
    must still be a well-formed amount, otherwise the words are left as they are.
    """
    out = []
    for w in words:
        if out and NUMERIC_PIECE.match(out[-1].text) and NUMERIC_PIECE.match(w.text) and w.x0 - out[-1].x1 < 1.5:
            joined = out[-1].text + w.text
            if AMOUNT_DOTTED.match(joined.strip("()")):
                out[-1] = Word(joined, out[-1].x0, w.x1, out[-1].top, (out[-1].raw or out[-1].text) + (w.raw or w.text))
                continue
        out.append(w)
    return out


def _notes_column_x(lines):
    """x-centre of the "Catatan/Notes" header, if present (used to tell note references from small amounts)."""
    for ln in lines[:40]:
        for w in ln.words:
            if re.match(r"^(catatan|notes)/?$", w.text.strip(), re.I):
                return (w.x0 + w.x1) / 2
    return None


def _is_certain_amount(text):
    t = text.strip()
    return t in NIL or bool(AMOUNT_DOTTED.match(t.strip("()"))) or (t.startswith("(") and t.endswith(")")
                                                                     and parse_amount(t) is not None)


def _amount_left_edge(lines):
    """Left edge of the amount area: where the first unambiguous figure of a line usually starts."""
    xs = []
    for ln in lines:
        for i, w in enumerate(ln.words):
            prev = ln.words[i - 1].text if i else ""
            if AMOUNT_DOTTED.match(w.text.strip("()")) and not prev.lower().startswith("rp"):
                xs.append(w.x0)
                break
    if len(xs) < 5:
        return None
    xs.sort()
    return xs[max(0, len(xs) // 20)]          # 5th percentile: robust to a few stray figures


def _split_label_only(words, gap=40):
    """Indonesian label of a line without figures: words up to the first wide gap (the English text)."""
    out = []
    for w in words:
        if out and w.x0 - out[-1].x1 > gap:
            break
        out.append(w)
    return out


def _assign_amounts(line, notes_x=None, t_first=True, amount_left=None):
    """Read the two figures of a line in reading order: the first is one column, the second the other.

    Column x-positions are not used to pick the columns: in many IDX PDFs the figures are not
    aligned in true columns. Rules:
      - note references ("4,32,33", "15a") are skipped;
      - a figure preceded by "Rp" is part of the label text (e.g. an allowance quoted in the label);
      - a dash inside a label ("Aset tetap - neto") is text, not nil;
      - a bare small integer ("31", "10") is label text when it lies left of the amount area,
        a note reference when it sits under the Notes header, and an amount otherwise.
    """
    label_words, nums, seen_number = [], [], False
    certain = []                                        # parallel to nums: the figure has a thousands separator or is nil
    words = line.words
    for i, w in enumerate(words):
        txt = w.text.strip()
        nxt = words[i + 1].text.strip() if i + 1 < len(words) else ""
        prev = words[i - 1].text.strip().lower() if i else ""
        if txt in NIL and not seen_number and re.match(r"^[A-Za-z(]", nxt):
            label_words.append(w)
            continue
        if txt in NIL and not nxt and re.search(r"[A-Za-z]$", prev) and not nums:
            continue          # a hyphen ending a wrapped English label ("Lease liabilities -", TFAS 2021), not nil
        in_paren = prev.count("(") > prev.count(")") or (txt.endswith(")") and not txt.startswith("(")
                                                         and any("(" in x.text and ")" not in x.text for x in words[max(0, i - 3):i]))
        if (re.search(r"(^|[(:])(rp\.?|usd|us\$)$", prev) or (in_paren and re.search(r"\d{4}|rp|usd", prev))) \
                and parse_amount(txt) is not None:
            if not seen_number:
                label_words.append(w)
            continue
        if re.match(r"^\d{1,2}$", txt) and re.match(r"(?i)^(januari|februari|maret|april|mei|juni|juli|agustus|september|"
                                                   r"oktober|november|desember|january|february|march|may|june|july|"
                                                   r"august|october|december)\b", nxt):
            if not seen_number:
                label_words.append(w)               # a date in the label ("per 31 Desember 2021"), not a figure
            continue
        ambiguous = NOTE_REF.match(txt) and not _is_certain_amount(txt)
        if ambiguous:
            if re.search(r"[,a-z]", txt, re.I):        # "4,32,33", "15a": certainly a note reference
                seen_number = True
                continue
            if notes_x is not None and abs((w.x0 + w.x1) / 2 - notes_x) <= 20:
                seen_number = True
                continue
            if amount_left is not None and w.x1 < amount_left - 2:
                if not seen_number:
                    label_words.append(w)
                continue
        v = parse_amount(txt)
        if v is not None:
            seen_number = True
            nums.append(v)
            certain.append(_is_certain_amount(txt))
            continue
        if not seen_number:
            label_words.append(w)
        elif nums:
            break                                       # the English label starts after the figures
    # a note reference printed between the two figures ("Goodwill 91.366 12 91.366", SIDO 2020): a bare one- or
    # two-digit number between two figures with thousands separators is not a figure (found by the section sums)
    if len(nums) >= 3 and sum(certain) >= 2:
        keep = [k for k in range(len(nums)) if certain[k] or not (0 < k < len(nums) - 1 and abs(nums[k]) < 100)]
        nums = [nums[k] for k in keep]
    amounts = {}
    if len(nums) >= 2:
        amounts = {"t": nums[0], "t1": nums[1]} if t_first else {"t": nums[1], "t1": nums[0]}
    elif len(nums) == 1:
        amounts = {"single": nums[0]}
    if not nums:
        label_words = _split_label_only(label_words)
    line.label = " ".join(w.text for w in label_words).strip()
    line.amounts = amounts
    return line


TITLES = {
    "position": [r"LAPORAN POSISI KEUANGAN", r"NERACA", r"STATEMENTS? OF FINANCIAL POSITION"],
    "profit_loss": [r"LABA RUGI", r"PROFIT OR LOSS", r"STATEMENTS? OF INCOME", r"LAPORAN LABA"],
    "cash_flow": [r"LAPORAN ARUS KAS", r"STATEMENTS? OF CASH FLOWS"],
}
EXCLUDE_TITLES = [r"PERUBAHAN EKUITAS", r"CHANGES IN EQUITY", r"CATATAN ATAS", r"NOTES TO THE", r"DAFTAR ISI",
                  r"TABLE OF CONTENTS", r"SURAT PERNYATAAN", r"LAPORAN AUDITOR"]


def _classify(page_lines, height):
    head = " ".join(ln.text for ln in page_lines if ln.top < height * 0.30).upper()
    if any(re.search(p, head) for p in EXCLUDE_TITLES):
        return None
    for kind in ("cash_flow", "profit_loss", "position"):   # order matters: cash-flow titles mention neither
        if any(re.search(p, head) for p in TITLES[kind]):
            return kind
    return None


def _detect_year_and_side(lines):
    """Fiscal year t and whether t is the first amount column, from the year labels in the header."""
    year, t_first, _ = _year_header(lines)
    return year, t_first


def _year_header(lines):
    """(year t, t is the first column, the header line) from the year labels at the top of a statement."""
    for ln in lines[:40]:
        years = [int(m.group()) for w in ln.words for m in [re.search(r"20\d\d", w.text)] if m]
        if len(set(years)) < 2:          # years printed with spaced digits: "2 0 2 1   2 0 2 0"
            spaced = re.findall(r"(?<!\d)2 0 (\d) (\d)(?!\d)", ln.text)
            years = [2000 + int(a + b) for a, b in spaced] if len(spaced) >= 2 else years
        distinct = list(dict.fromkeys(years))
        if len(distinct) >= 2 and abs(distinct[0] - distinct[1]) == 1:
            return max(distinct[0], distinct[1]), distinct[0] > distinct[1], ln
    return None, True, None


USD = re.compile(r"dolar amerika|dollar amerika|united states dollars?|u\.?s\.? dollars?|\bus\$|\busd\b")


def _currency(text):
    """Presentation currency from the statement headings (P4, Gail 28 Oct 2026: US dollars accepted)."""
    t = text.lower()
    usd, idr = bool(USD.search(t)), "rupiah" in t
    if usd and not idr:
        return "USD"
    if idr and not usd:
        return "IDR"
    return None                      # neither, or both named in the heading: not decided here


def _unit_scale(text):
    t = text.lower()
    if re.search(r"(ribuan|thousands of) (dolar|dollar|us|united states)", t):
        return "Thousands"
    if re.search(r"(jutaan|millions of) (dolar|dollar|us|united states)", t):
        return "Millions"
    if re.search(r"dalam (dolar|dollar) amerika|in (us|united states) dollars?|expressed in (us|united states) dollars?", t):
        return "Units"
    if "jutaan rupiah" in t or "millions of" in t:
        return "Millions"
    if "ribuan rupiah" in t or "thousands of" in t:
        return "Thousands"
    if "miliar" in t or "billions of" in t:
        return "Billions"
    if "dalam rupiah" in t or "in rupiah" in t or "expressed in indonesian rupiah" in t:
        return "Units"
    return None


# ------------------------------------------------------------------------------------- fields

def _norm(s):
    s = re.sub(r"^([A-Z]) ([a-z]{2,})", r"\1\2", s.strip())   # a text-layer split first letter: "N ilai", "U tang"
    s = s.lower().replace("–", "-").replace(",", " ")
    s = re.sub(r"\s+", " ", s).strip(" :")
    return re.sub(r"^-\s+", "", s)                  # "- Pihak Ketiga - Bersih" (list dash)


FACE_RULES = [
    # field, statement, label regex (Indonesian label, normalised), status
    ("revenue", "profit_loss", r"^(penjualan|pendapatan)( neto| bersih| usaha| dari kontrak dengan pelanggan)?$", "FOUND"),
    ("cost_of_goods_sold", "profit_loss", r"^(beban|harga) pokok (penjualan|pendapatan)( neto| bersih)?$", "FOUND"),
    ("net_income", "profit_loss", r"^(laba|rugi|laba \(rugi\)|laba/rugi) (neto |bersih )?tahun berjalan$", "FOUND"),
    ("total_assets", "position", r"^(total|jumlah) aset$", "FOUND"),
    ("current_assets", "position", r"^(total|jumlah) aset lancar$", "FOUND"),
    ("cash_and_cash_equivalents", "position", r"^kas dan (setara kas|bank)$|^kas$", "FOUND"),
    ("property_plant_equipment_net", "position", r"^aset tetap( -)?( neto| bersih)?$|^aset tetap - setelah dikurangi akumulasi", "REVIEW"),
    ("current_liabilities", "position", r"^(total|jumlah) liabilitas jangka pendek$", "FOUND"),
    ("total_liabilities", "position", r"^(total|jumlah) liabilitas$", "FOUND"),
    ("cash_flow_from_operations", "cash_flow",
     r"aktivitas operasi$", "FOUND"),
]

SGA_PARTS = [r"^beban penjualan( dan pemasaran)?$", r"^beban (umum dan administrasi|administrasi dan umum)$",
             r"^beban pemasaran$", r"^beban umum$",
             r"^beban penjualan,? umum,? dan administrasi$"]           # one combined line (ABMM 2021)


def _continuation(lines, i):
    """The line's own label is the tail of a wrapped label ("Uang muka pembelian" / "aset tetap 58.997"):
    it starts in lower case right under a label-only line. Line items in IDX statements start with a
    capital letter, so such a tail must not be matched on its own (Trial 1, BIRD 2021)."""
    ln = lines[i]
    first = ln.label.strip()[:1]
    return bool(first) and first.islower() and i > 0 and not lines[i - 1].amounts and bool(lines[i - 1].label.strip())


def _own_match(rx, lines, i):
    """The line's label matches on its own, or, for the tail of a wrapped label, together with the label-only
    line above it ("Beban umum dan" / "administrasi 30.403.766.317", TFAS 2021). A tail never matches alone
    ("Uang muka pembelian" / "aset tetap", BIRD 2021)."""
    ln = lines[i]
    if not _continuation(lines, i):
        if rx.search(_norm(ln.label)):
            return True
        # an upper-case tail ("PENDAPATAN DARI KONTRAK" / "DENGAN PELANGGAN 1.021.865.474", ABMM 2021) matches only
        # together with its head
        prev = lines[i - 1] if i else None
        return bool(prev is not None and not prev.amounts and prev.label.strip() and ln.label.strip().isupper()
                    and prev.label.strip().isupper() and rx.search(_norm(prev.label + " " + ln.label)))
    return bool(rx.search(_norm(lines[i - 1].label + " " + ln.label)))


def _candidates(lines, pattern):
    """Every line with both years whose label (own or wrapped) matches: used to detect ambiguity (rule 7)."""
    rx = re.compile(pattern)
    out = []
    for i, ln in enumerate(lines):
        if (_own_match(rx, lines, i) or rx.search(_norm(ln.full_label))) and "t" in ln.amounts and "t1" in ln.amounts:
            out.append(ln)
    return out


def _first(lines, pattern, need_both=True):
    rx = re.compile(pattern)
    for i, ln in enumerate(lines):
        if (_own_match(rx, lines, i) or rx.search(_norm(ln.full_label))) and (
                not need_both or ("t" in ln.amounts and "t1" in ln.amounts)):
            return ln
    return None


SIGNED_FIELDS = {"net_income", "cash_flow_from_operations"}      # a loss or a cash outflow keeps its sign


def _value_pair(field_name, ln, status, note=""):
    out = []
    for col in ("t", "t1"):
        v = ln.amounts.get(col)
        if v is not None and field_name not in SIGNED_FIELDS:
            v = abs(v)
        quote = getattr(ln, "quote", "") or ln.text
        head = ln.full_label[:len(ln.full_label) - len(ln.label)].strip() if ln.full_label.endswith(ln.label) else ""
        if not getattr(ln, "quote", "") and head and not ln.label.strip()[:1].isupper():
            quote = head + " / " + ln.text            # the tail of a wrapped label: quote the head printed above it
        out.append(Value(field_name, col, v,
                         status if v is not None else "NOT FOUND", [ln.page], [quote], note=note))
    return out


def _revenue_line(lines, pattern):
    """Revenue on one line, or a 'Pendapatan' heading followed by its components and a subtotal
    ('Subjumlah' / 'Jumlah pendapatan') within eight lines. The gross-profit check confirms it."""
    ln = _first(lines, pattern)
    if ln:
        return ln
    rx = re.compile(pattern)
    for i, h in enumerate(lines):
        if h.amounts or not rx.search(_norm(h.label)):
            continue
        for nxt in lines[i + 1:i + 9]:
            nl = _norm(nxt.label)
            if re.match(r"^(sub ?jumlah|sub ?total|jumlah|total)( pendapatan| penjualan)?( neto| bersih)?$", nl) \
                    and "t" in nxt.amounts and "t1" in nxt.amounts:
                return nxt
            if re.match(r"^(beban|harga) pokok|^laba", nl):
                break
    return None


DIRECT_COST = re.compile(r"^(beban|biaya) langsung$|^(beban|biaya) pokok (jasa|pendapatan jasa)$")
GROSS_PROFIT = re.compile(r"^laba (bruto|kotor)$|^laba \(rugi\) (bruto|kotor)$|^rugi (bruto|kotor)$")


def _direct_cost_line(lines, revenue_ln):
    """P5 (Gail, 28 Oct 2026): 'Beban langsung' counts as cost of sales only when a gross-profit line
    follows within two lines and revenue − direct cost = gross profit in both years."""
    if revenue_ln is None:
        return None
    for i, ln in enumerate(lines):
        if not DIRECT_COST.search(_norm(ln.full_label or ln.label)) or "t" not in ln.amounts or "t1" not in ln.amounts:
            continue
        gp = next((x for x in lines[i + 1:i + 3] if GROSS_PROFIT.search(_norm(x.full_label or x.label))
                   and "t" in x.amounts and "t1" in x.amounts), None)
        if gp and all(abs(revenue_ln.amounts[c]) - abs(ln.amounts[c]) == gp.amounts[c] for c in ("t", "t1")):
            return ln
    return None


def _operating_expenses_line(lines):
    """P5 (Gail, 28 Oct 2026): a single 'Beban usaha' line counts as selling + general and administrative
    expenses only when it lies between the gross-profit line and the operating-profit line and no separate
    selling or general and administrative line exists."""
    gp = next((i for i, x in enumerate(lines) if GROSS_PROFIT.search(_norm(x.full_label or x.label)) and x.amounts), None)
    if gp is None:
        return None
    for j in range(gp + 1, min(gp + 6, len(lines))):
        ln = lines[j]
        if not (re.match(r"^beban usaha$", _norm(ln.label)) or re.match(r"^beban usaha$", _norm(ln.full_label or ""))) \
                or "t" not in ln.amounts or "t1" not in ln.amounts:
            continue
        after = lines[j + 1:j + 6]
        if any(re.match(r"^(laba|rugi|laba \(rugi\)|\(rugi\) laba) (usaha|operasi)\b", _norm(x.full_label or x.label))
               and x.amounts for x in after):
            return ln
    return None


def _net_income_line(lines, pattern):
    """'Laba tahun berjalan', or a bare '(Rugi) laba' / 'Laba (rugi)' line right after the income-tax line."""
    ln = _first(lines, pattern)
    if ln:
        return ln
    after_tax = False
    for ln in lines:
        nl = _norm(ln.full_label or ln.label)
        if re.search(r"(beban|manfaat).{0,20}pajak penghasilan|pajak penghasilan.{0,10}(neto|bersih)?$", nl) and ln.amounts:
            after_tax = True
            continue
        if after_tax and "t" in ln.amounts and "t1" in ln.amounts and re.match(
                r"^(\(rugi\) laba|laba \(rugi\)|laba|rugi)( neto| bersih)?( tahun berjalan)?$", _norm(ln.label)):
            return ln
    return None


def _cfo_line(lines):
    for ln in lines:
        lab = _norm(ln.label)
        if re.search(r"(kas|arus kas) (neto|bersih)", lab) and "operasi" in lab and "t" in ln.amounts:
            return ln
    # labels split over two lines: "Kas Neto Diperoleh dari" / "Aktivitas Operasi 1.199.317"
    for ln in lines:
        if re.search(r"^aktivitas operasi$", _norm(ln.label)) and "t" in ln.amounts:
            return ln
    # Trial 1: "Kas neto dari aktivitas" / "operasi 171.116": the label wrapped anywhere
    for ln in lines:
        full = _norm(ln.full_label)
        if "t" in ln.amounts and re.search(r"(kas|arus kas) (neto|bersih)\b[^.]{0,40}aktivitas operasi$", full):
            return ln
    # Trial 2 (MTPS 2021): the label is printed around the figures: "Jumlah Kas Bersih yang Diperoleh dari" /
    # "(246.072.015.025) 89.153.940.475" / "(Digunakan untuk) Aktivitas Operasi"
    for i, ln in enumerate(lines[1:-1], start=1):
        prev, nxt = lines[i - 1], lines[i + 1]
        if "t" in ln.amounts and "t1" in ln.amounts and not ln.label.strip() and not prev.amounts and not nxt.amounts:
            joined = _norm(prev.label + " " + nxt.label)
            if re.search(r"(kas|arus kas) (neto|bersih)\b[^.]{0,60}aktivitas operasi$", joined):
                ln.quote = " / ".join(x.text for x in (prev, ln, nxt))
                return ln
    return None


PPE_WRAPPED = re.compile(r"(?:^|\s)aset tetap\s*-?\s*(setelah dikurangi|neto|bersih)")
NOT_PPE_BEFORE = re.compile(r"(uang muka|pembelian|untuk dijual|pengampunan|tersedia untuk|dalam penyelesaian)\s*$")


def _ppe_line(lines, pattern):
    """Fixed assets on the face. The label is often wrapped over several lines ("Aset Tetap - Setelah
    Dikurangi / Akumulasi Penyusutan sebesar Rp ... / ... 175.367.937.126"); the figures are on the
    last line. The wrapped label must contain 'aset tetap' followed by net-of-depreciation wording,
    and must not be another item that names fixed assets (advances for, assets held for sale)."""
    ln = _first(lines, pattern)
    if ln:
        return ln
    for i, ln in enumerate(lines):
        if "t" not in ln.amounts or "t1" not in ln.amounts:
            continue
        back, back_lines = [], []
        for prev in reversed(lines[max(0, i - 8):i]):
            if "t" in prev.amounts and "t1" in prev.amounts:     # a stray date ("31") is not a figure line
                break
            back.insert(0, prev.label)
            back_lines.insert(0, prev)
        full = _norm(" ".join(back + [ln.label]))
        m = None
        for m in PPE_WRAPPED.finditer(full):
            pass
        if m and not NOT_PPE_BEFORE.search(full[:m.start()]):
            ln.quote = " / ".join(x.text for x in back_lines[-6:] + [ln])       # the whole wrapped label as printed
            return ln
    return None


def _receivables(lines):
    """Trade receivables: the 'Piutang usaha' block (third parties net + related parties), or one line.

    The block may start with label-only lines (e.g. the allowance quoted in the label) before the
    'Pihak ...' lines that carry the figures.
    """
    for i, ln in enumerate(lines):
        lab = _norm(ln.label)
        if not lab.startswith("piutang usaha"):
            continue
        if "t" in ln.amounts:
            block = [ln]
            if "pihak" in lab:                 # 'Piutang usaha - pihak ketiga' then '- pihak berelasi' on its own line
                for nxt in lines[i + 1:i + 4]:
                    nl = _norm(nxt.label)
                    if "t" in nxt.amounts and (nl.startswith("pihak") or nl.startswith("piutang usaha")) and "pihak" in nl:
                        block.append(nxt)
                    else:
                        break
            return block, ""
        # Trial 2 (APII 2021): an item label can wrap over several lines with the allowance quoted in it
        # ("Pihak ketiga - setelah / dikurangi cadangan / ... / (2020 : Rp2.995.582.842) 52.638.402.581 ...").
        # A label-only 'Pihak ...' line opens an item; its figures are on the next line that has them.
        block, open_at = [], (i if "pihak" in lab else None)    # 'Piutang usaha - pihak ketiga' wrapped (MTPS 2021)
        for k, nxt in enumerate(lines[i + 1:i + 20], start=i + 1):
            nl = _norm(nxt.label)
            if "t" in nxt.amounts:
                if nl.startswith("pihak") or open_at is not None:
                    block.append(nxt)
                    open_at = None
                    continue
                break
            if not nl:
                continue
            if nl.startswith("pihak"):
                open_at = k
                continue
            if open_at is not None and k - open_at <= 8:
                continue                       # wrapped label of the open item
            if block or open_at is not None or nxt.label.strip()[:1].isupper():
                break                          # the next item of the statement
        if block:
            return block, ""
    return [], ""


CONTRACT_ASSET = re.compile(r"aset kontrak|contract assets?")
GROSS_DUE = re.compile(r"^tagihan bruto (kepada|dari) pemberi kerja|^gross amount due from customers")
RETENTION = re.compile(r"^piutang retensi")


def _block(lines, rx):
    """A face item matched by label: its own line when it carries figures, else the 'Pihak ...' lines under it."""
    for i, ln in enumerate(lines):
        if not rx.search(_norm(ln.label)):
            continue
        if "t" in ln.amounts:
            return [ln]
        block = []
        for nxt in lines[i + 1:i + 6]:
            if _norm(nxt.label).startswith("pihak") and "t" in nxt.amounts:
                block.append(nxt)
            elif block or "t" in nxt.amounts:
                break
        return block
    return []


def _contract_assets(lines, ar_lines):
    """G-06 A (approved 23 Oct 2026; PSAK 115 ¶105-108): contract assets are not trade receivables.

    Returns (separate, combined): separate = face lines for contract assets presented on their own
    (excluded from accounts_receivable, recorded, REVIEW); combined = the receivable lines whose own
    label also names contract assets (cannot be separated from the face: REVIEW, nothing guessed).
    """
    combined = [ln for ln in ar_lines if CONTRACT_ASSET.search(_norm(ln.full_label or ln.label))]
    separate = [ln for ln in lines if ln not in ar_lines and "t" in ln.amounts
                and CONTRACT_ASSET.search(_norm(ln.label)) and not _norm(ln.label).startswith(("liabilitas", "contract liabilit"))]
    return separate, combined


def _sum_values(field_name, parts, status, note):
    out = []
    for col in ("t", "t1"):
        vals = [p.amounts.get(col) for p in parts]
        if parts and all(v is not None for v in vals):
            out.append(Value(field_name, col, sum(abs(v) for v in vals), status, [p.page for p in parts],
                             [p.text for p in parts],
                             components=join([Amt(abs(v)) for v in vals], " + "), note=note))
        else:
            out.append(Value(field_name, col, None, "NOT FOUND", note=note))
    return out


def _debt(lines):
    """Interest-bearing debt candidates on the face, by section. Always REVIEW (D-01, D-02).

    Non-current section: every interest-bearing line -> long_term_debt.
    Current section: current portions of long-term debt and current lease liabilities ->
    current maturities. Short-term (working-capital) bank loans are excluded (D-02).
    """
    lt, cm, excluded, section = [], [], [], None
    interest = re.compile(r"(utang|pinjaman) bank|pinjaman|obligasi|sukuk|liabilitas sewa|utang sewa|wesel bayar|medium term notes|mtn"
                          r"|(utang|liabilitas) aset hak[ -]guna")
    figs = lambda x: "t" in x.amounts or "t1" in x.amounts                    # noqa: E731
    seen = {"current": False, "noncurrent": False}
    for i, ln in enumerate(lines):
        lab = _norm(ln.full_label or ln.label)
        # section headings may wrap: "LIABILITAS JANGKA" / "PENDEK" (BIRD 2021)
        own = _norm(ln.label)
        if not figs(ln) and re.search(r"^liabilitas jangka$", own) and i + 1 < len(lines) and not figs(lines[i + 1]):
            own = own + " " + _norm(lines[i + 1].label)
        if re.search(r"^liabilitas jangka pendek\b", own) and not figs(ln):
            section = "current"
            seen["current"] = True
            continue
        if re.search(r"^liabilitas jangka panjang\b", own) and not figs(ln):
            nxt = " ".join(_norm(x.label) for x in lines[i + 1:i + 3] if not figs(x))
            heading = _norm(ln.label) + " " + nxt
            if section == "current" and re.search(r"jatuh tempo dalam (waktu )?(satu|1) tahun|bagian (lancar|jangka pendek)", heading) \
                    and "setelah dikurangi" not in heading:
                section = "current_maturities"        # sub-heading of current liabilities
            else:
                section = "noncurrent"
                seen["noncurrent"] = True
            continue
        if re.search(r"^(total|jumlah) liabilitas", _norm(ln.full_label or ln.label)) and figs(ln) \
                or re.search(r"^ekuitas", _norm(ln.label)):
            section = None
            continue
        if section is None or not ("t" in ln.amounts or "t1" in ln.amounts) or not interest.search(lab):
            continue
        if section == "noncurrent":
            lt.append(ln)
        elif section == "current_maturities":
            cm.append(ln)
        elif re.search(r"bagian (lancar|yang jatuh tempo|jangka pendek)|jatuh tempo dalam (waktu )?(satu|1) tahun|sewa", lab):
            cm.append(ln)
        else:
            excluded.append(ln)
    return lt, cm, excluded, seen


BORROWING_NOTE = re.compile(r"(?im)^\s*\d{1,2}[a-z]?\.\s+.*(pinjaman|utang bank) jangka panjang|^\s*\d{1,2}[a-z]?\.\s+.*"
                            r"(obligasi|sukuk|wesel bayar|medium term notes|liabilitas sewa|utang sewa|pinjaman jangka panjang)")


def _nil_by_absence(values, checks, sections, text, notes_start):
    """G-24 (S2, approved): long-term debt or its current portion may be 0 only when (1) the balance
    sheet adds up in both years, (2) the section was read and holds no interest-bearing line, (3) no note
    heading names long-term borrowings, bonds or leases, and (4) the evidence is recorded. Otherwise the
    field stays blank. Always REVIEW."""
    bal = [ok for name, c, ok, _ in checks if getattr(name, "key", "") == "check.balance"]
    if len(bal) < 2 or not all(bal) or not notes_start:
        return values
    notes = "\n".join(text[notes_start - 1:])
    if BORROWING_NOTE.search(notes):
        return values
    out = []
    for v in values:
        sec = {"long_term_debt": "noncurrent", "current_maturities_long_term_debt": "current"}.get(v.field)
        if sec and v.value is None and sections.get(sec):
            v = Value(v.field, v.column, 0, "REVIEW", [], [], note=Msg("note.debt_nil_g24"))
        out.append(v)
    return out


SECTIONS = [("check.section_ca", r"^aset lancar$", r"^(total|jumlah) aset lancar$"),
            ("check.section_nca", r"^aset tidak lancar$", r"^(total|jumlah) aset tidak lancar$"),
            ("check.section_cl", r"^liabilitas jangka pendek$", r"^(total|jumlah) liabilitas jangka pendek$")]


def _section_sums(pos):
    """Rule 7: the lines of a section of the statement of financial position must add up to its printed total.
    Confirms that every figure in the section was read (and read at the right scale). Returns
    (passed checks, issues); a section that does not add up is reported, never corrected."""
    passed, issues = [], []
    lines = pos.lines
    for key, head_rx, total_rx in SECTIONS:
        start = next((i for i, ln in enumerate(lines) if re.search(head_rx, _norm(ln.label))
                      and not ("t" in ln.amounts or "t1" in ln.amounts)), None)
        if start is None:
            continue
        parts, total = [], None
        for ln in lines[start + 1:start + 60]:
            if "t" in ln.amounts and "t1" in ln.amounts:
                if re.search(total_rx, _norm(ln.full_label or ln.label)):
                    total = ln
                    break
                parts.append(ln)
        if total is None or not parts:
            continue
        for c in ("t", "t1"):
            got = sum(x.amounts[c] for x in parts)
            if got == total.amounts[c]:
                passed.append((Msg(key), c, True, Msg("check.detail_vs", a=Amt(got), b=Amt(total.amounts[c]))))
            else:
                issues.append(Msg("issue.section_sum", sec=Msg(key), col=c, a=Amt(got), b=Amt(total.amounts[c]),
                                  p=total.page))
    return passed, issues


# ------------------------------------------------------------------------------------- rule 7 cross-checks
# Rule 7 (Gail, 28 Oct 2026): every face figure the score uses needs an independent cross-check before it can
# be FOUND; a figure that cannot be cross-checked stays REVIEW. Trial 2 (APII, TFAS 2021) showed two figures
# FOUND without one.

SCORE_FACE_FIELDS = ("revenue", "cost_of_goods_sold", "net_income", "total_assets", "current_assets",
                     "cash_and_cash_equivalents", "current_liabilities", "total_liabilities",
                     "cash_flow_from_operations", "selling_general_administrative_expenses", "accounts_receivable")
PBT = r"^(laba|rugi|laba \(rugi\)|\(rugi\) laba|rugi \(laba\)|laba/rugi) sebelum (beban |manfaat )?(\(beban\) )?(\(manfaat\) )?pajak"
TOTAL_OPEX = r"^(total|jumlah) beban (usaha|operasi|operasional)$"
NET_CHANGE_CASH = (r"^(kenaikan|penurunan|peningkatan|\(penurunan\)|\(kenaikan\))\b(?![^.]*(awal|akhir|dibatasi|saldo|"
                   r"piutang|persediaan|utang|aset|liabilitas|beban|uang muka))[^.]{0,60}(kas|neto|bersih)\b")


def pair_in_text(text, first_page, t, t1):
    """Page of the first text line (from first_page on) that shows both figures, in either thousands style.
    Figures below 1.000 are not distinctive and are not searched. None when not found."""
    pats = []
    for v in (t, t1):
        if not v:
            continue
        a = abs(v)
        if a < 1000:
            return None
        forms = {f"{a:,}", f"{a:,}".replace(",", ".")}
        pats.append(re.compile(r"(?<![\d.,])(" + "|".join(re.escape(f) for f in forms) + r")(?![\d]|[.,]\d)"))
    if not pats or first_page is None:
        return None
    for i in range(first_page, len(text) + 1):
        for line in text[i - 1].splitlines():
            if all(p.search(line) for p in pats):
                return i
    return None


def _between(lines, a, b):
    return [x for x in lines[lines.index(a) + 1:lines.index(b)] if x.amounts]


def _net_income_check(pl, ni):
    """Profit before tax and the lines below it add up to profit for the year (either sign convention for tax)."""
    pbt = _first(pl.lines, PBT)
    if pbt is None:
        return {}
    ni_ln = next((x for x in pl.lines[pl.lines.index(pbt) + 1:] if "t" in x.amounts and "t1" in x.amounts
                  and x.amounts["t"] == ni.get("t") and x.amounts["t1"] == ni.get("t1")), None)
    if ni_ln is None:
        return {}
    mid = _between(pl.lines, pbt, ni_ln)
    if any("t" not in x.amounts or "t1" not in x.amounts for x in mid):
        return {}
    out = {}
    for c in ("t", "t1"):
        ways = {pbt.amounts[c] + sum(x.amounts[c] for x in mid), pbt.amounts[c] - sum(abs(x.amounts[c]) for x in mid)}
        if mid:                                # current + deferred tax followed by their total
            ways |= {pbt.amounts[c] + mid[-1].amounts[c], pbt.amounts[c] - abs(mid[-1].amounts[c])}
        out[c] = ni[c] in ways
    return out


def _cfo_check(cf, cfo):
    """Operating + investing + financing cash flows = net change in cash."""
    inv, fin = _first(cf.lines, r"aktivitas investasi$"), _first(cf.lines, r"aktivitas pendanaan$")
    net = _first(cf.lines, NET_CHANGE_CASH)
    if not (inv and fin and net):
        return {}
    fx = _first(cf.lines, r"^(pengaruh|efek|dampak)\b[^.]{0,60}(kurs|selisih)")
    out = {}
    for c in ("t", "t1"):
        base = cfo.get(c) is not None and cfo[c] + inv.amounts[c] + fin.amounts[c]
        out[c] = base is not False and (base == net.amounts[c] or (fx is not None and c in fx.amounts
                                                                    and base + fx.amounts[c] == net.amounts[c]))
    return out


def _sga_total(pl, parts):
    """SGA lines against a printed 'Total beban usaha'. Returns (status per column, other lines) where status is
    'ok', 'other' (the total also holds other items printed on their own lines) or 'mismatch' (a line of the
    block was not read as an item, e.g. the tail of a wrapped label). {} when no total is printed."""
    total = _first(pl.lines, TOTAL_OPEX)
    if total is None or not parts:
        return {}, []
    start = _first(pl.lines, r"^laba (bruto|kotor)$")
    first = min(pl.lines.index(p) for p in parts)
    if start is None or pl.lines.index(start) > first:
        start_i = first - 1
    else:
        start_i = pl.lines.index(start)
    end_i = pl.lines.index(total)
    if end_i < first:
        return {}, []
    others = [x for x in pl.lines[start_i + 1:end_i] if x.amounts and x not in parts]
    out = {}
    for c in ("t", "t1"):
        got = sum(abs(p.amounts.get(c, 0)) for p in parts)
        if got == abs(total.amounts[c]):
            out[c] = "ok"
        elif others and all(x.label.strip()[:1].isupper() and c in x.amounts for x in others) and \
                got + sum(abs(x.amounts[c]) for x in others) == abs(total.amounts[c]):
            out[c] = "other"
        else:
            out[c] = "mismatch"
    return out, others


def _rule7(values, checks, statements, text, notes_start, cross_checks, issues):
    """Collect the cross-checks each score field passed; FOUND figures without one become REVIEW."""
    get = {(v.field, v.column): v.value for v in values}
    ok = set()
    by_key = {"check.balance": ("total_assets", "total_liabilities"), "check.section_ca": ("current_assets",),
              "check.section_cl": ("current_liabilities",), "check.gross_profit": ("revenue", "cost_of_goods_sold")}
    for name, c, passed, _ in checks:
        if passed and getattr(name, "key", None) in by_key:
            ok.update((f, c) for f in by_key[name.key])
    new = []
    pos = statements.get("position")
    if pos:
        # total assets = total liabilities and equity; total liabilities = current + non-current liabilities
        tle = _first(pos.lines, r"^(total|jumlah) liabilitas dan ekuitas\b")
        ncl = _first(pos.lines, r"^(total|jumlah) liabilitas jangka panjang$|^(total|jumlah) liabilitas tidak lancar$")
        for c in ("t", "t1"):
            ta, tl, cl = (get.get((f, c)) for f in ("total_assets", "total_liabilities", "current_liabilities"))
            if tle and ta is not None and abs(tle.amounts[c]) == ta and ("total_assets", c) not in ok:
                ok.add(("total_assets", c))
                new.append((Msg("check.ta_tle"), c, True, ""))
            if ncl and None not in (tl, cl) and cl + abs(ncl.amounts[c]) == tl:
                ok.update({("total_liabilities", c), ("current_liabilities", c)})
                new.append((Msg("check.tl_parts"), c, True, ""))
    pl, cf = statements.get("profit_loss"), statements.get("cash_flow")
    ni = {c: get.get(("net_income", c)) for c in ("t", "t1")}
    if pl and None not in ni.values():
        for c, passed in _net_income_check(pl, ni).items():
            if passed:
                ok.add(("net_income", c))
                new.append((Msg("check.net_income"), c, True, ""))
    cfo = {c: get.get(("cash_flow_from_operations", c)) for c in ("t", "t1")}
    if cf and None not in cfo.values():
        for c, passed in _cfo_check(cf, cfo).items():
            if passed:
                ok.add(("cash_flow_from_operations", c))
                new.append((Msg("check.cfo"), c, True, ""))
    cash = {c: get.get(("cash_and_cash_equivalents", c)) for c in ("t", "t1")}
    if cf and None not in cash.values() and any(
            "t" in x.amounts and "t1" in x.amounts and abs(x.amounts["t"]) == cash["t"] and abs(x.amounts["t1"]) == cash["t1"]
            for x in cf.lines):
        ok.update({("cash_and_cash_equivalents", "t"), ("cash_and_cash_equivalents", "t1")})
        new += [(Msg("check.cash_cf"), c, True, "") for c in ("t", "t1")]
    # SGA against the printed total of operating expenses
    if pl:
        parts = [ln for pat in SGA_PARTS for ln in [_first(pl.lines, pat)] if ln]
        st, others = _sga_total(pl, parts)
        if st:
            bad = [c for c, x in st.items() if x == "mismatch"]
            if bad:
                cross_checks["sga_total"] = {c: ("mismatch", sum(abs(p.amounts.get(c, 0)) for p in parts)) for c in bad}
            for c, x in st.items():
                if x == "ok":
                    ok.add(("selling_general_administrative_expenses", c))
                    new.append((Msg("check.sga_total"), c, True, ""))
            if any(x == "other" for x in st.values()):
                issues.append(Msg("issue.sga_other", lines=Raw("; ".join(o.text[:50] for o in others))))
    # the same figures again in the notes (cash, revenue, cost of sales, SGA lines, trade receivables)
    for f in ("cash_and_cash_equivalents", "revenue", "cost_of_goods_sold", "accounts_receivable",
              "selling_general_administrative_expenses"):
        if all((f, c) in ok for c in ("t", "t1")):
            continue
        vs = [v for v in values if v.field == f and v.value is not None]
        if len(vs) != 2:
            continue
        pair = {v.column: v.value for v in vs}
        page = pair_in_text(text, notes_start, pair["t"], pair["t1"])
        if page is None and f in ("accounts_receivable", "selling_general_administrative_expenses"):
            parts = _parts(statements, f)
            pages = [pair_in_text(text, notes_start, p.amounts.get("t"), p.amounts.get("t1")) for p in parts]
            if parts and all(pages):
                page = min(pages)
        if page is not None:
            ok.update({(f, "t"), (f, "t1")})
            new += [(Msg("check.in_notes", item=Msg(f"label.{f}"), p=page), c, True, "") for c in ("t", "t1")]
    checks += new
    for v in values:
        if v.field in SCORE_FACE_FIELDS and v.status == "FOUND" and (v.field, v.column) not in ok:
            v.status = "REVIEW"
            v.note = join([v.note, Msg("note.no_crosscheck")]) if v.note else Msg("note.no_crosscheck")
    return values


def _parts(statements, f):
    if f == "accounts_receivable" and statements.get("position"):
        return _receivables(statements["position"].lines)[0]
    if f == "selling_general_administrative_expenses" and statements.get("profit_loss"):
        pl = statements["profit_loss"]
        return [ln for pat in SGA_PARTS for ln in [_first(pl.lines, pat)] if ln]
    return []


def _checks(pos, pl, values):
    """Arithmetic cross-checks on the face figures. A failed check means a figure was misread."""
    get = {(v.field, v.column): v.value for v in values}
    out = []
    eq = _first(pos.lines, r"^(total|jumlah) ekuitas$")
    gp = _first(pl.lines, r"^laba (bruto|kotor)$") if pl else None
    for c in ("t", "t1"):
        ta, tl, ca, cl = (get.get((f, c)) for f in ("total_assets", "total_liabilities", "current_assets", "current_liabilities"))
        if eq and None not in (ta, tl) and c in eq.amounts:
            ok = ta == tl + eq.amounts[c]
            out.append((Msg("check.balance"), c, ok, Msg("check.detail_eq", a=Amt(ta), b=Amt(tl), c=Amt(eq.amounts[c]))))
        if None not in (ca, ta):
            out.append((Msg("check.ca_ta"), c, ca <= ta, ""))
        if None not in (cl, tl):
            out.append((Msg("check.cl_tl"), c, cl <= tl, ""))
        rev, cogs = get.get(("revenue", c)), get.get(("cost_of_goods_sold", c))
        if gp and None not in (rev, cogs) and c in gp.amounts:
            out.append((Msg("check.gross_profit"), c, rev - cogs == gp.amounts[c],
                        Msg("check.detail_gp", a=Amt(rev), b=Amt(cogs), c=Amt(gp.amounts[c]))))
    return out


# ------------------------------------------------------------------------------------- main

HEAD_EXCLUDE = EXCLUDE_TITLES + [r"IKHTISAR", r"HIGHLIGHTS", r"ANALISIS DAN PEMBAHASAN", r"MANAGEMENT DISCUSSION",
                                  r"TINJAUAN KEUANGAN", r"FINANCIAL REVIEW", r"KINERJA KEUANGAN"]
NOTES_HEAD = re.compile(r"CATATAN ATAS LAPORAN\s+KEUANGAN|NOTES TO THE\s+(CONSOLIDATED\s+)?FINANCIAL STATEMENTS")
NOTES_COLUMN = re.compile(r"(?im)^\s*(catatan|notes?)\s*/?\s*$|\bcatatan\s*/")
INTEGRAL_FOOTER = re.compile(r"(?i)merupakan bagian (yang )?integral|form(s)? an integral part|accompanying notes")


def locate_financial_statements(pdf_path) -> dict:
    """Find the audited primary statements and the start of the notes anywhere in the document.

    Works on a fast text index of every page (pypdfium2), so a 300+ page annual report is cheap.
    A page counts as a primary statement only when (1) its heading (top 30% of the page) carries a
    statement title and none of the excluded titles (notes, equity changes, contents, auditor's
    report, financial highlights, management discussion), and (2) the page itself shows that it is
    part of a statement set: a "Catatan/Notes" column or the "notes form an integral part" footer.
    Financial highlights and management-discussion tables fail (1) or (2) and are never used.
    The three statements must lie within STATEMENT_WINDOW pages of each other, and the notes must
    start within NOTES_WITHIN pages after them. Nothing is guessed: what is not found is reported.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    n = len(doc)
    text, heads, scanned = [], [], []
    for i in range(n):
        page = doc[i]
        w, h = page.get_size()
        tp = page.get_textpage()
        full = tp.get_text_range().replace("\ufffe", "").replace("\uffff", "")
        head = tp.get_text_bounded(0, h * 0.70, w, h)
        text.append(full)
        heads.append(re.sub(r"\s+", " ", head).upper())
        if len(re.sub(r"\s", "", full)) < SCANNED_MIN_CHARS:
            scanned.append(i + 1)
    doc.close()

    cand = {k: [] for k in TITLES}
    for i, head in enumerate(heads, start=1):
        if any(re.search(p, head) for p in HEAD_EXCLUDE):
            continue
        kind = next((k for k in ("cash_flow", "profit_loss", "position") if any(re.search(p, head) for p in TITLES[k])), None)
        if kind and (NOTES_COLUMN.search(text[i - 1]) or INTEGRAL_FOOTER.search(text[i - 1])):
            cand[kind].append(i)

    def runs(pages):
        out = []
        for p in pages:
            if out and p == out[-1][-1] + 1:
                out[-1].append(p)
            else:
                out.append([p])
        return out

    blocks = []
    for pos in runs(cand["position"]):
        pl = next((r for r in runs(cand["profit_loss"]) if abs(r[0] - pos[0]) <= STATEMENT_WINDOW), None)
        cf = next((r for r in runs(cand["cash_flow"]) if abs(r[0] - pos[0]) <= STATEMENT_WINDOW), None)
        if pl and cf:
            last = max(pos[-1], pl[-1], cf[-1])
            notes = next((j for j in range(last + 1, min(n, last + NOTES_WITHIN) + 1)
                          if NOTES_HEAD.search(heads[j - 1]) and not re.search(r"DAFTAR ISI|TABLE OF CONTENTS", heads[j - 1])),
                         None)
            blocks.append({"position": pos, "profit_loss": pl, "cash_flow": cf, "notes_start": notes})
    chosen = next((b for b in blocks if b["notes_start"]), blocks[0] if blocks else None)
    return {"n_pages": n, "scanned": scanned, "candidates": cand, "blocks": blocks, "chosen": chosen,
            "text": text}


def read(pdf_path) -> Extraction:
    issues = []
    loc = locate_financial_statements(pdf_path)
    n, scanned, chosen = loc["n_pages"], loc["scanned"], loc["chosen"]
    fs_location = {"blocks": [{k: v for k, v in b.items()} for b in loc["blocks"]], "chosen": chosen,
                   "candidates": loc["candidates"], "scanned_count": len(scanned)}
    wanted = sorted({p for k in ("position", "profit_loss", "cash_flow") for p in (chosen or {}).get(k, [])})
    pages = {}
    stmt_text = [loc["text"][i - 1] for i in range(wanted[0], wanted[-1] + 1)] if wanted else []
    fmt = number_format(stmt_text) if wanted else "dot"
    if fmt != "mixed" and paren_artifact(stmt_text):
        fmt += "+paren"
    if fmt == "mixed":
        issues.append(Msg("issue.number_format"))
        wanted = []                                       # nothing is read rather than read at the wrong scale
    if wanted:
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(wanted[0], wanted[-1] + 1):       # the statement block only, word by word
                pages[i] = (_lines(pdf.pages[i - 1], i, fmt), pdf.pages[i - 1].height)
    else:
        issues.append(_not_found_message(loc))
    if chosen and not chosen.get("notes_start"):
        issues.append(Msg("issue.notes_not_found"))

    kinds = {}
    for i, (lines, h) in pages.items():
        k = _classify(lines, h)
        if k:
            kinds.setdefault(k, []).append(i)

    statements, fiscal_year, unit, stype, currency = {}, None, None, None, None
    year_labels = {}
    for kind, pnos in kinds.items():
        # keep the first contiguous run of pages (the statement itself, not later references)
        run = [pnos[0]]
        for p in pnos[1:]:
            if p == run[-1] + 1:
                run.append(p)
            else:
                break
        all_lines = [ln for p in run for ln in pages[p][0]]
        year, t_first, head_ln = _year_header(all_lines)
        year_labels[kind] = {"year": year, "t_first": t_first, "page": head_ln.page if head_ln else run[0],
                             "quote": head_ln.text if head_ln else ""}
        if year is None:
            issues.append(Msg("issue.year_labels", stmt=Msg(f"stmt.{kind}")))
        fiscal_year = fiscal_year or year
        notes_x = _notes_column_x(all_lines)
        amount_left = _amount_left_edge(all_lines)
        for ln in all_lines:
            _assign_amounts(ln, notes_x, t_first, amount_left)
        pending = []                                   # label-only lines since the last line with figures
        for ln in all_lines:
            if ln.amounts:
                ln.full_label = " ".join([p.label for p in pending[-5:]] + [ln.label]).strip()
                pending = []
            elif ln.label:
                pending.append(ln)
        statements[kind] = Statement(kind, run, all_lines)
        head = " ".join(ln.text for ln in all_lines[:25])
        unit = unit or _unit_scale(head)
        currency = currency or _currency(head)
        if stype is None and re.search(r"KONSOLIDASIAN|CONSOLIDATED", head.upper()):
            stype = "Consolidated"

    # Trial 2 (MTPS, WSBP 2021): a company without subsidiaries presents statements that are not consolidated. When
    # all three statement titles were read and none says consolidated, the basis is the workbook's 'Parent-only'.
    if stype is None and all(k in statements for k in ("position", "profit_loss", "cash_flow")) and all(
            any(re.search(p, " ".join(ln.text for ln in statements[k].lines[:12]).upper()) for p in TITLES[k])
            for k in ("position", "profit_loss", "cash_flow")):
        stype = "Parent-only"

    for k in ("position", "profit_loss", "cash_flow"):
        if wanted and k not in statements:
            issues.append(Msg("issue.stmt_missing", stmt=Msg(f"stmt.{k}"), a=wanted[0], b=wanted[-1]))
    if unit is None:
        issues.append(Msg("issue.unit"))

    values = []
    for field_name, kind, pattern, status in FACE_RULES:
        st = statements.get(kind)
        if field_name == "cash_flow_from_operations":
            ln = _cfo_line(st.lines) if st else None
        elif field_name == "property_plant_equipment_net":
            ln = _ppe_line(st.lines, pattern) if st else None
        elif field_name == "revenue":
            ln = _revenue_line(st.lines, pattern) if st else None
        elif field_name == "net_income":
            ln = _net_income_line(st.lines, pattern) if st else None
        else:
            ln = _first(st.lines, pattern) if st else None
        if ln:
            note = Msg("note.ppe_face_only") if field_name == "property_plant_equipment_net" else ""
            values += _value_pair(field_name, ln, status, note)
        else:
            values += [Value(field_name, c, None, "NOT FOUND" if st else "STATEMENT NOT FOUND") for c in ("t", "t1")]

    # rule 7: a single-line field with several candidate lines of different amounts is ambiguous: REVIEW
    for field_name, kind, pattern, status in FACE_RULES:
        st = statements.get(kind)
        if not st or field_name == "cash_flow_from_operations":
            continue
        cands = _candidates(st.lines, pattern)
        amounts = {(abs(x.amounts["t"]), abs(x.amounts["t1"])) for x in cands}
        if len(amounts) > 1:
            issues.append(Msg("issue.ambiguous", item=Msg(f"label.{field_name}"),
                              lines=join([Msg("rep.trace_item", item=Raw(x.text[:50].strip()), p=x.page) for x in cands[:4]],
                                         "; ")))
            for v in values:
                if v.field == field_name and v.status == "FOUND":
                    v.status = "REVIEW"
                    v.note = join([v.note, Msg("note.ambiguous_line")]) if v.note else Msg("note.ambiguous_line")

    pl = statements.get("profit_loss")
    if pl:
        parts = [ln for pat in SGA_PARTS for ln in [_first(pl.lines, pat)] if ln]
        opex = None if parts else _operating_expenses_line(pl.lines)
        if opex is not None:
            values += _sum_values("selling_general_administrative_expenses", [opex], "REVIEW", Msg("note.sga_opex"))
        else:
            values += _sum_values("selling_general_administrative_expenses", parts, "FOUND", Msg("note.sga"))
        cogs = next((v for v in values if v.field == "cost_of_goods_sold" and v.column == "t"), None)
        if cogs is not None and cogs.value is None:
            rev_ln = _revenue_line(pl.lines, FACE_RULES[0][2])
            direct = _direct_cost_line(pl.lines, rev_ln)
            if direct is not None:
                values = [v for v in values if v.field != "cost_of_goods_sold"]
                values += _value_pair("cost_of_goods_sold", direct, "REVIEW", Msg("note.cogs_direct"))
    pos = statements.get("position")
    if pos:
        ar, _ = _receivables(pos.lines)
        ca_sep, ca_comb = _contract_assets(pos.lines, ar)
        if ca_comb:
            values += _sum_values("accounts_receivable", ar, "REVIEW", Msg("note.ar_combined"))
        else:
            values += _sum_values("accounts_receivable", ar, "FOUND" if not ca_sep else "REVIEW", Msg("note.ar"))
        # P7 (Gail, 28 Oct 2026): construction contracts. 'Tagihan bruto kepada pemberi kerja' is a contract
        # asset (G-06); 'piutang retensi' is not yet unconditional. Both stay out of trade receivables, REVIEW.
        gross_due, retention = _block(pos.lines, GROSS_DUE), _block(pos.lines, RETENTION)
        ca_sep = ca_sep + [x for x in gross_due if x not in ca_sep]
        if ca_sep:
            ca_note = Msg("note.contract_assets", p=Pages(tuple(sorted({x.page for x in ca_sep}))))
            values += _sum_values("contract_assets", ca_sep, "REVIEW", ca_note)
            issues.append(ca_note)
        if retention:
            issues.append(Msg("issue.retention", p=Pages(tuple(sorted({x.page for x in retention})))))
        if ca_sep or retention:
            for v in values:
                if v.field == "accounts_receivable" and v.value is not None:
                    v.status = "REVIEW"
                    v.note = join([v.note, Msg("note.ar_construction")]) if retention else v.note
        lt, cm, excl, debt_sections = _debt(pos.lines)
        if excl:
            issues.append(Msg("issue.short_term_loans", lines=Raw("; ".join(e.text[:60] for e in excl))))
        values += _sum_values("long_term_debt", lt, "REVIEW", Msg("note.debt")) if lt \
            else [Value("long_term_debt", c, None, "REVIEW", note=Msg("note.ltd_none")) for c in ("t", "t1")]
        values += _sum_values("current_maturities_long_term_debt", cm, "REVIEW", Msg("note.debt")) if cm \
            else [Value("current_maturities_long_term_debt", c, None, "REVIEW", note=Msg("note.cm_none")) for c in ("t", "t1")]

    checks = []
    cross_checks = {}
    face_rou = None
    extra_non_ppe = {}
    if pos:
        face_rou = _first(pos.lines, r"^aset hak guna\b|^aset hak-guna|hak untuk menggunakan aset|^aset hak pakai")
        if face_rou:
            values += _value_pair("rou_assets_net", face_rou, "REVIEW", Msg("note.rou_face"))
        checks += _checks(pos, statements.get("profit_loss"), values)
        sec_ok, sec_issues = _section_sums(pos)
        checks += sec_ok
        issues += sec_issues
        section_fields = {"check.section_ca": ("cash_and_cash_equivalents", "accounts_receivable"),
                          "check.section_nca": ("property_plant_equipment_net", "rou_assets_net")}
        for i_ in sec_issues:                      # a section that does not add up: its line items are not FOUND
            fields = section_fields.get(i_.params["sec"].key, ())
            for v in values:
                if v.field in fields and v.column == i_.params["col"] and v.status == "FOUND":
                    v.status = "REVIEW"
        values = _nil_by_absence(values, checks, debt_sections, loc["text"], (chosen or {}).get("notes_start"))

    # ---- notes (Phase 2b); only when the notes (CALK) were located after the statements
    if pos and chosen and chosen.get("notes_start"):
        from .notes_reader import PageCache, ppe_note_carrying, read_notes
        with pdfplumber.open(pdf_path) as pdf:
            cache = PageCache(pdf, pdf_path, fiscal_year, text=loc["text"], notes_start=chosen["notes_start"], fmt=fmt)
            face_ppe = {v.column: v.value for v in values if v.field == "property_plant_equipment_net" and v.value is not None}
            if face_ppe:
                cross_checks["ppe_note"] = ppe_note_carrying(cache, chosen["notes_start"], face_ppe)
            n_values, n_checks, n_issues, _, non_ppe_ev = read_notes(cache, statements, values)
        values += n_values
        checks += n_checks
        extra_non_ppe = non_ppe_ev
        issues += n_issues
        # D-08: PPE includes right-of-use assets, wherever they are presented
        rou_vals = {v.column: v for v in values if v.field == "rou_assets_net"}
        for v in values:
            if v.field != "property_plant_equipment_net" or v.value is None:
                continue
            r = rou_vals.get(v.column)
            where = "face" if face_rou else "notes"
            if r is not None and r.value == 0 and r.status == "FOUND":
                # no right of use assets anywhere in the report: PPE alone; FOUND when the PPE note agrees (rule 7)
                v.note = Msg("note.ppe_no_rou")
                ok = (cross_checks.get("ppe_note") or {}).get(v.column, ("none",))[0] == "ok"
                v.status = "FOUND" if ok else "REVIEW"
            elif r is not None and r.value is not None:
                v.components = Msg("comp.ppe_rou", a=Amt(v.value), b=Amt(r.value), where=Msg(f"where.{where}"))
                v.value += r.value
                v.pages += r.pages
                v.quotes += r.quotes
                v.note = Msg(f"note.ppe_plus_rou_{where}")
            elif r is not None and r.status == "INCLUDED IN PPE":
                v.note = Msg("note.ppe_rou_inside", psak116=Psak("116", "73", fiscal_year, "¶47(a)(i)"))
                v.status = "REVIEW"
            elif r is not None and r.status == "NOT FOUND":
                v.note = Msg("note.ppe_only")
                v.status = "REVIEW"
    else:
        for f in ("taxes_payable", "depreciation_amortization_total", "amortization_intangibles",
                  "ppe_depreciation_disclosed", "rou_depreciation"):
            values += [Value(f, c, None, "NOT SEARCHED",
                             note=Msg("note.notes_not_read_calk" if pos else "note.notes_not_read_fs"))
                       for c in ("t", "t1")]

    if statements:
        values = _rule7(values, checks, statements, loc["text"], (chosen or {}).get("notes_start"), cross_checks, issues)

    # ---- M-08 package (approved 23 Oct 2026): transition and restated comparatives, from the report itself
    from .transition import detect as _detect_transition
    trans = _detect_transition(loc["text"], (chosen or {}).get("notes_start"), fiscal_year, statements) if statements else {}
    issues += (trans or {}).get("gaps", [])

    return Extraction(Path(pdf_path).name, n, scanned, fiscal_year, unit, stype, statements, values,
                      issues, checks, extra_non_ppe, fs_location, trans, year_labels,
                      _financial_institution(statements), fmt, currency, cross_checks)


# Bank / insurer / finance-company line items (labels on the face of the statements). The Beneish model
# does not apply to financial institutions (approved 28 Oct 2026: block the score, explain why).
FI_MARKERS = [
    ("bank", r"^kredit yang diberikan|^pinjaman yang diberikan"),
    ("bank", r"^simpanan (dari )?nasabah|^giro, tabungan dan deposito"),
    ("bank", r"^giro wajib minimum|^giro pada bank indonesia|^penempatan pada bank indonesia"),
    ("bank", r"^(cadangan )?kerugian penurunan nilai (kredit|pinjaman)"),
    ("insurer", r"^liabilitas manfaat polis|^cadangan teknis|^liabilitas kontrak asuransi"),
    ("insurer", r"^pendapatan premi|^premi bruto|^pendapatan asuransi"),
    ("insurer", r"^beban klaim|^klaim dan manfaat"),
    ("finance", r"^piutang pembiayaan (konsumen|multiguna)|^piutang sewa pembiayaan|^investasi sewa neto"),
]


def _financial_institution(statements):
    """Distinct bank / insurer / finance-company items found on the face: [(kind, page, label)].
    Two or more distinct items mean the report is treated as a financial institution's."""
    found = {}
    for kind in ("position", "profit_loss"):
        st = statements.get(kind)
        for ln in (st.lines if st else []):
            lab = _norm(ln.full_label or ln.label)
            for i, (k, rx) in enumerate(FI_MARKERS):
                if i not in found and re.search(rx, lab):
                    found[i] = (k, ln.page, ln.label.strip()[:60])
    return list(found.values()) if len(found) >= 2 else []


def _not_found_message(loc):
    found = {k: v for k, v in loc["candidates"].items() if v}
    parts = [Msg("issue.fs_not_found", n=loc["n_pages"])]
    if found:
        parts.append(Msg("issue.fs_candidates", list=tuple(
            Msg("issue.cand_item", stmt=Msg(f"stmt.{k}"), p=Pages(tuple(v) if isinstance(v, (list, tuple)) else (v,)))
            for k, v in found.items())))
    if loc["scanned"]:
        sc = loc["scanned"]
        parts.append(Msg("issue.scanned", k=len(sc), pages=Pages(tuple(sc[:10]))))
    return join(parts, " ")
