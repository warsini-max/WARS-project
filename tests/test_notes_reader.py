"""Notes reader (Phase 2b) and the PDF -> M-score pipeline.

Unit tests run everywhere. Document tests need the non-case test PDFs (data/test_documents.csv),
which are not in git; they are skipped unless WARS_TEST_PDF_DIR points to them.
"""
import csv
import hashlib
import os
from pathlib import Path

import pytest

from wars_scanner import engine, golden, pipeline
from wars_scanner.notes_reader import note_lines
from wars_scanner.text import keys_in
from wars_scanner.pdf_reader import Line, Word, read

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = {d["file_name"]: d for d in csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8"))}


def _ln(*tokens, top=0):
    """tokens: (text, x0, x1)."""
    return Line(1, top, [Word(t, a, b, top) for t, a, b in tokens])


HEADER = _ln(("2021", 258, 276), ("2020", 332, 350))       # SIDO 2021 tax table header


# ----------------------------------------------------------------------------- unit tests
def test_article_number_and_bracket_are_label_text():
    ln = _ln(("PPh", 112, 127), ("Pasal", 129, 149), ("4", 151, 155), ("(2)", 158, 167), ("125", 285, 298),
             ("82", 366, 374), ("Income", 445, 471), ("Tax", 474, 487), ("Article", 489, 511), ("4", 514, 518),
             ("(2)", 520, 530))
    note_lines([HEADER, ln])
    assert ln.label == "PPh Pasal 4 (2)" and ln.amounts == {"t": 125, "t1": 82} and ln.method == "column"


def test_nil_comparative_by_column():
    ln = _ln(("Pajak", 112, 131), ("Luar", 134, 150), ("Negeri", 152, 176), ("1", 294, 298), ("-", 372, 374),
             ("Foreign", 487, 514), ("Tax", 517, 530))
    note_lines([HEADER, ln])
    assert ln.amounts == {"t": 1, "t1": 0}


def test_movement_row_is_not_a_two_year_line():
    ln = _ln(("Total", 60, 80), ("599.279", 200, 230), ("96.876", 262, 298), ("(2.342)", 300, 330),
             ("(14.993)", 340, 374), ("678.806", 400, 430))
    note_lines([HEADER, ln])
    assert ln.amounts == {}


def test_reading_order_fallback_when_positions_are_unreliable():
    # SIDO 2020: header at x 94-138, figures printed elsewhere and not aligned
    hdr = _ln(("2020", 94, 111), ("2019", 120, 138))
    ln = _ln(("(Catatan", 105, 140), ("24)", 141, 150), ("88.796", 160, 185), ("77.343", 198, 223), ("(Note", 453, 470),
             ("24)", 471, 480))
    note_lines([hdr, ln])
    assert ln.amounts == {"t": 88796, "t1": 77343} and ln.method == "order"


def test_label_number_with_one_figure_is_not_read_as_a_pair():
    # "Pasal 25 17.833" with the comparative missing must not become t=25, t-1=17.833
    hdr = _ln(("2020", 94, 111), ("2019", 120, 138))
    ln = _ln(("Pasal", 122, 142), ("25", 145, 154), ("17.833", 160, 185), ("Article", 497, 519), ("25", 522, 531))
    note_lines([hdr, ln])
    assert ln.amounts == {}


def test_comparative_first_header_order():
    hdr = _ln(("2020", 258, 276), ("2021", 332, 350))
    ln = _ln(("Total", 60, 80), ("10.000", 262, 298), ("20.000", 340, 374))
    note_lines([hdr, ln])
    assert ln.amounts == {"t": 20000, "t1": 10000}


# ----------------------------------------------------------------------------- document tests
def _pdf(name):
    doc = DOCS[name]
    p = PDF_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not available (set WARS_TEST_PDF_DIR)")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == doc["sha256"]
    return p


_cache = {}


def _read(name):
    if name not in _cache:
        _cache[name] = read(_pdf(name))
    return _cache[name]


def _v(ext, field, col):
    return next(v for v in ext.values if v.field == field and v.column == col)


# Simulated user decision for tests (M-06): NONE_PRESENT for each year, with the notes examined.
NONE_BOTH = {c: {"status": "NONE_PRESENT", "notes": ["(test) notes on fixed assets and other non-current assets"]}
             for c in ("t", "t1")}

DIGITAL = ["LK_SIDO_2020.pdf", "LK_SIDO_2021.pdf", "LK_KLBF_2020.pdf", "LK_KLBF_2021.pdf",
           "LK_KLBF_2023_upload.pdf", "LK_MYOR_2020.pdf"]


@pytest.mark.parametrize("name", DIGITAL)
def test_tax_note_reconciles_to_note_total_and_face(name):
    ext = _read(name)
    tax_checks = [c for c in ext.checks if c[0].key in ("check.tax_components", "check.tax_face")]
    assert len(tax_checks) == 4 and all(ok for _, _, ok, _ in tax_checks)
    for c in ("t", "t1"):
        assert _v(ext, "taxes_payable", c).status == "FOUND"


@pytest.mark.parametrize("name", DIGITAL)
def test_ppe_depreciation_reconciles_to_movement_table(name):
    ext = _read(name)
    for c in ("t", "t1"):
        assert _v(ext, "ppe_depreciation_owned", c).value is not None
        assert any(n.key == "check.alloc_ppe" and col == c and ok
                   for n, col, ok, _ in ext.checks)


@pytest.mark.parametrize("prev,cur", [("LK_SIDO_2020.pdf", "LK_SIDO_2021.pdf"), ("LK_KLBF_2020.pdf", "LK_KLBF_2021.pdf")])
def test_comparatives_agree_with_prior_year_report(prev, cur):
    """The t-1 figures of one report equal the t figures of the previous report (no restatement in
    these documents): an independent check that t and t-1 were not swapped or misread."""
    a, b = _read(prev), _read(cur)
    for f in ("taxes_payable", "ppe_depreciation_owned", "rou_depreciation", "amortization_intangibles"):
        t_prev, t1_cur = _v(a, f, "t"), _v(b, f, "t1")
        if t_prev.value is None and t1_cur.value is None:
            continue
        assert t_prev.value == t1_cur.value, f


def test_klbf_2021_notes_values():
    ext = _read("LK_KLBF_2021.pdf")
    expect = {("taxes_payable", "t"): 270589776948, ("taxes_payable", "t1"): 321499775561,
              ("ppe_depreciation_owned", "t"): 606364268106, ("rou_depreciation", "t"): 45781576843,
              ("amortization_intangibles", "t"): 21663837089, ("ppe_depreciation_disclosed", "t"): 652145844949}
    for (f, c), val in expect.items():
        assert _v(ext, f, c).value == val, f
    # expense notes show more 'Amortisasi' than the intangible note: must be raised for review
    assert any("issue.expense_amort" in keys_in(i) for i in ext.issues)


def test_rou_depreciation_not_disclosed_stays_blank():
    ext = _read("LK_SIDO_2021.pdf")
    for c in ("t", "t1"):
        v = _v(ext, "rou_depreciation", c)
        assert v.value is None and v.status == "NOT DISCLOSED"


def test_pipeline_sido_2021_matches_golden_m_score():
    gp, _ = golden.load(ROOT / "data/golden/SIDO_2021.csv")
    expected = engine.calculate(gp)["m_score_B"]
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    assert r.m_score is None and r.status == "AWAITING NON-PPE STATUS"          # M-06: held
    r = pipeline.apply_non_ppe_decisions(r, NONE_BOTH)                          # simulated user decision
    assert r.m_score == pytest.approx(expected, abs=1e-12)
    for k, v in gp.items():
        if k in r.inputs:
            assert r.inputs[k] == v, k
    assert r.status.startswith("PROVISIONAL") and r.review


def test_pipeline_scanned_report_is_not_calculated():
    r = pipeline.run(_pdf("LK_MYOR_2021.pdf"), "MYOR")
    assert r.m_score is None and r.status == "NOT CALCULATED"
    assert any("OCR" in i for i in r.extraction.issues) and "issue.scanned" in keys_in(r.unreadable)


# ----------------------------------------------------------------------------- M-06 (approved 22 Oct 2026)
def test_non_ppe_status_is_never_set_by_the_machine():
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    assert r.non_ppe_pending == ["t", "t1"] and r.m_score is None
    assert "depreciation_amortization_non_ppe_t" not in r.inputs          # no automatic 0
    assert r.extraction.non_ppe_evidence["groups"] and r.extraction.non_ppe_evidence["notes"]


def test_none_present_requires_notes_examined():
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    with pytest.raises(pipeline.DecisionError):
        pipeline.apply_non_ppe_decisions(r, {"t": {"status": "NONE_PRESENT", "notes": []}})


def test_years_are_decided_separately():
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    one = pipeline.apply_non_ppe_decisions(r, {"t": NONE_BOTH["t"]})
    assert one.non_ppe_pending == ["t1"] and one.m_score is None
    assert "non_ppe_status_t1" not in one.inputs


def test_all_disclosed_needs_an_amount_read():
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    with pytest.raises(pipeline.DecisionError):
        pipeline.apply_non_ppe_decisions(r, {"t": {"status": "ALL_DISCLOSED", "notes": ["x"]}})


def test_partial_undisclosed_is_review():
    r = pipeline.run(_pdf("LK_SIDO_2021.pdf"), "SIDO")
    out = pipeline.apply_non_ppe_decisions(r, {"t": {"status": "PARTIAL_UNDISCLOSED"}, "t1": NONE_BOTH["t1"]})
    assert out.m_score is not None and any(f.code == "r_non_ppe_partial" for f in out.flags)


def test_unused_assets_are_shown_as_evidence_klbf():
    ev = _read("LK_KLBF_2021.pdf").non_ppe_evidence
    unused = next(g for g in ev["groups"] if g["key"] == "unused_assets")
    assert unused["found"] and any(h["with_amount"] for h in unused["hits"])


def test_no_intangibles_found_is_not_zero_myor():
    ext = _read("LK_MYOR_2020.pdf")
    for c in ("t", "t1"):
        v = _v(ext, "amortization_intangibles", c)
        assert v.value is None and v.status == "NOT ASSESSED"                   # M-15 pending


def test_m03_fx_line_excluded_from_amortisation_and_kept_as_evidence():
    """M-03 A (Gail, 23 Oct 2026): the FX translation line inside the 'amortisasi tahun berjalan'
    block (KLBF 2023, p101) is not amortisation; it is excluded, recorded with its page, REVIEW."""
    p = PDF_DIR / "LK_KLBF_2023_upload.pdf"
    if not p.exists():
        pytest.skip("LK_KLBF_2023_upload.pdf not available")
    v = {x.column: x for x in read(p).values if x.field == "amortization_intangibles"}
    assert v["t"].value == 19_612_300_661 + 8_519_222_058          # software + trademarks, without FX
    assert v["t"].status == "REVIEW" and v["t1"].status == "REVIEW"
    assert "note.amort_fx" in keys_in(v["t"].note) and "p. 101: 'Selisih kurs" in v["t"].note.render("en")
    assert "M-03" in v["t"].note.render("en", codes=True)


# ------------------------------------------------------------------ ROU presented within PPE (Keterbatasan 3.7, Gail 23 Oct 2026)
# No test document presents ROU within fixed assets, so the detector is tested on constructed pages;
# the real documents (all with 'Hak Guna Bangunan' land titles in the PPE note) must give no detection.
from wars_scanner.notes_reader import combine_ppe_depreciation, rou_within_ppe
from wars_scanner.pdf_reader import Value


class _Cache:
    def __init__(self, pages, heading="ASET TETAP", text=None):
        self._pages, self._heading = pages, heading
        self.text = text or ["" for _ in pages]

    def lines(self, p):
        return self._pages[p - 1] if 0 < p <= len(self._pages) else []

    def heading_before(self, p, idx):
        return self._heading


def _row(label, *figures, page=1):
    ln = Line(page, 0, [Word(w, 0, 10, 0) for w in label.split()] + [Word(f, 100, 140, 0) for f in figures])
    ln.label = label
    return ln


def test_rou_class_row_in_the_ppe_movement_table_is_detected():
    page = [_row("Aset hak guna", "12.500", "3.000", "(1.200)", "14.300")]
    assert rou_within_ppe(_Cache([page]), {"page": 1})[0] == 1


@pytest.mark.parametrize("label", ["Hak guna bangunan", "Tanah dengan status Hak Guna Bangunan",
                                   "Reklasifikasi ke aset hak guna"])
def test_land_titles_and_reclassifications_are_not_rou(label):
    page = [_row(label, "12.500", "3.000", "(1.200)", "14.300")]
    assert rou_within_ppe(_Cache([page]), {"page": 1}) is None


def test_rou_row_outside_a_ppe_note_is_not_taken():
    page = [_row("Aset hak guna", "12.500", "3.000", "(1.200)", "14.300")]
    assert rou_within_ppe(_Cache([page], heading="ASET HAK GUNA"), {"page": 1}) is None


def test_sentence_fixed_assets_include_rou_is_detected():
    page = [_row("Aset tetap termasuk aset hak guna")]
    text = ["Aset tetap termasuk aset hak guna atas bangunan kantor yang disewa."]
    assert rou_within_ppe(_Cache([page], text=text), {"page": 1}) is not None


def test_no_double_count_when_rou_is_within_ppe():
    own = Value("ppe_depreciation_owned", "t", 1000, "FOUND", [5], ["Total 1.000"])
    rdep = Value("rou_depreciation", "t", 200, "FOUND", [9], ["Total 200"])
    v, _, note, st, added = combine_ppe_depreciation(own, rdep, True)
    assert v == 1000 and st == "REVIEW" and not added and note.key == "note.dep_rou_inside"
    v, _, _, st, added = combine_ppe_depreciation(own, rdep, False)
    assert v == 1200 and added and st == "BUILT FROM DISCLOSED COMPONENTS"


@pytest.mark.parametrize("name", ["LK_SIDO_2020.pdf", "LK_SIDO_2021.pdf", "LK_KLBF_2020.pdf", "LK_KLBF_2021.pdf",
                                  "LK_KLBF_2023_upload.pdf", "LK_MYOR_2020.pdf"])
def test_no_rou_within_ppe_detection_on_the_test_documents(name):
    p = PDF_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not available")
    ex = read(p)
    assert not any("issue.rou_inside" in keys_in(i) for i in ex.issues)
    assert all(v.status != "INCLUDED IN PPE" for v in ex.values)
