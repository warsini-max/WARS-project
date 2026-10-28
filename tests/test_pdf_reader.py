"""PDF reader tests.

Unit tests run everywhere. Document tests need the test PDFs, which are not in git; they run
when WARS_TEST_PDF_DIR points to a folder holding the files in data/test_documents.csv
(skipped otherwise).
"""
import csv
import hashlib
import os
from pathlib import Path

import pytest

from wars_scanner.pdf_reader import Line, Word, _assign_amounts, _merge_split_numbers, parse_amount, read

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = list(csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8")))


def _line(*tokens):
    """tokens: (text, x0) pairs; widths are approximated."""
    return Line(1, 0, [Word(t, x, x + 6 * len(t), 0) for t, x in tokens])


# ----------------------------------------------------------------------------- unit tests
@pytest.mark.parametrize("text,value", [("1.082.219", 1082219), ("(1.734.948)", -1734948), ("-", 0),
                                        ("80", 80), ("(862)", -862), ("Kas", None), ("2021", None)])
def test_parse_amount(text, value):
    assert parse_amount(text) == value


def test_dash_inside_label_is_text():
    ln = _assign_amounts(_line(("Aset", 65), ("tetap", 83), ("-", 103), ("neto", 108), ("1.588.101", 128),
                               ("10", 177), ("1.568.264", 193)), notes_x=180)
    assert ln.label == "Aset tetap - neto" and ln.amounts == {"t": 1588101, "t1": 1568264}


def test_rp_amount_in_label_is_not_a_figure():
    ln = _assign_amounts(_line(("sebesar", 68), ("Rp", 93), ("5.567.196.018.777", 103), ("dan", 157)))
    assert ln.amounts == {} and "5.567.196.018.777" in ln.label


def test_small_number_left_of_amount_area_is_label_text():
    ln = _assign_amounts(_line(("31", 68), ("Desember", 77), ("2020", 108), ("9", 222),
                               ("6.043.201.970.326", 263), ("4.674.963.819.225", 339)), notes_x=222, amount_left=260)
    assert ln.amounts == {"t": 6043201970326, "t1": 4674963819225}


def test_nil_comparative():
    ln = _assign_amounts(_line(("Liabilitas", 65), ("sewa", 110), ("4.216", 150), ("2b", 180), ("-", 230)), notes_x=185)
    assert ln.amounts == {"t": 4216, "t1": 0}


def test_split_number_is_rejoined():
    words = [Word("2", 268.0, 272.4, 0), Word("28.563.209.997", 272.5, 330, 0)]
    assert [w.text for w in _merge_split_numbers(words)] == ["228.563.209.997"]


def test_order_when_comparative_is_first():
    ln = _assign_amounts(_line(("Kas", 60), ("100", 200), ("200", 260)), t_first=False)
    assert ln.amounts == {"t": 200, "t1": 100}


# ----------------------------------------------------------------------------- document tests
def _pdf(name, sha):
    p = PDF_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not available (set WARS_TEST_PDF_DIR)")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"{name}: SHA-256 differs from the manifest"
    return p


@pytest.mark.parametrize("doc", DOCS, ids=[d["file_name"] for d in DOCS])
def test_document(doc):
    ext = read(_pdf(doc["file_name"], doc["sha256"]))
    if "scanned" in doc["text_layer_note"]:
        assert not ext.statements and any("OCR" in i for i in ext.issues)
        return
    assert set(ext.statements) == {"position", "profit_loss", "cash_flow"}
    assert ext.fiscal_year == int(doc["fiscal_year"])
    assert ext.checks and all(ok for _, _, ok, _ in ext.checks), [c for c in ext.checks if not c[2]]


def test_sido_2021_against_golden_no_silent_error():
    doc = next(d for d in DOCS if d["file_name"] == "LK_SIDO_2021.pdf")
    ext = read(_pdf(doc["file_name"], doc["sha256"]))
    gold = {(r["field"], r["column"]): r for r in csv.DictReader(open(ROOT / "data/golden/SIDO_2021.csv", encoding="utf-8"))}
    match = silent = 0
    for v in ext.values:
        g = gold.get((v.field, v.column))
        if not g or v.value is None or not g["value"].lstrip("-").isdigit():
            continue
        if v.value == int(g["value"]):
            match += 1
        elif v.status != "REVIEW":
            silent += 1
    assert silent == 0
    # 40 fields match the golden; non-PPE D&A and the D&A total (4) are left blank until the user sets the
    # non-PPE status (M-06, approved 22 Oct 2026), so the reader alone matches 36
    assert match >= 36
    for v in ext.values:
        if v.field in ("depreciation_amortization_non_ppe", "non_ppe_status"):
            assert v.value is None and v.status == "NOT ASSESSED"


# ------------------------------------------------------------------ G-06 A (approved 23 Oct 2026)
# No test document presents contract assets, so these tests use constructed lines.
def _face(label, t, t1, page=7):
    ln = Line(page, 0, [Word(w, 0, 10, 0) for w in label.split()])
    ln.label, ln.full_label, ln.amounts = label, label, {"t": t, "t1": t1}
    return ln


def test_g06_separate_contract_assets_are_excluded_and_recorded():
    from wars_scanner.pdf_reader import _contract_assets, _receivables
    lines = [_face("Piutang usaha", 900, 800), _face("Aset kontrak", 120, 0), _face("Persediaan", 500, 400),
             _face("Liabilitas kontrak", 50, 40)]
    ar, _ = _receivables(lines)
    sep, comb = _contract_assets(lines, ar)
    assert [x.label for x in ar] == ["Piutang usaha"]
    assert [x.label for x in sep] == ["Aset kontrak"] and comb == []


def test_g06_combined_line_is_review_not_split():
    from wars_scanner.pdf_reader import _contract_assets, _receivables
    lines = [_face("Piutang usaha dan aset kontrak", 1020, 800), _face("Persediaan", 500, 400)]
    ar, _ = _receivables(lines)
    sep, comb = _contract_assets(lines, ar)
    assert comb == ar and sep == []          # the reader marks it REVIEW and keeps the figure as presented


# ----------------------------------------------------------------------------- P0-2 and bank block (28 Oct 2026)
def test_reversed_column_order_is_read_from_the_heading():
    from wars_scanner.pdf_reader import _year_header
    head = _line(("Catatan", 300), ("2020", 380), ("2021", 460))
    year, t_first, ln = _year_header([head])
    assert year == 2021 and t_first is False and ln is head          # t is the second column here


def test_no_year_heading_is_not_guessed():
    from wars_scanner.pdf_reader import _year_header
    assert _year_header([_line(("Aset", 60), ("lancar", 90))])[0] is None


def _stmt(kind, labels):
    from wars_scanner.pdf_reader import Statement
    lines = []
    for lab in labels:
        ln = _assign_amounts(_line(*[(w, 60 + 40 * i) for i, w in enumerate(lab.split())], ("1.000", 400), ("900", 480)))
        lines.append(ln)
    return Statement(kind, [5], lines)


def test_bank_statements_are_recognised():
    from wars_scanner.pdf_reader import _financial_institution
    st = {"position": _stmt("position", ["Kredit yang diberikan", "Simpanan nasabah", "Total aset"])}
    assert len(_financial_institution(st)) == 2


def test_one_bank_like_line_is_not_enough():
    from wars_scanner.pdf_reader import _financial_institution
    st = {"position": _stmt("position", ["Piutang pembiayaan konsumen", "Persediaan", "Total aset"])}
    assert _financial_institution(st) == []


@pytest.mark.parametrize("doc", [d["file_name"] for d in DOCS])
def test_no_test_document_is_taken_for_a_bank(doc):
    p = PDF_DIR / doc
    if not p.exists():
        pytest.skip(f"{doc} not available")
    assert read(p).financial_institution == []
