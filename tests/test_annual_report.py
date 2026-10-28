"""Phase D: the audited statements and notes are found anywhere in a long document.

No real annual report (Laporan Tahunan) is available in the build environment, so the documents
are assembled by tools/build_composite_annual_report.py: 255 generated front-matter pages (cover,
contents, narrative, image-only pages, a financial-highlights page and a highlights page headed
"Laporan Posisi Keuangan Konsolidasian" without a Notes column: both traps) + a real non-case
financial-statement PDF, unchanged + generated back matter. The statements therefore start beyond
page 255 of a 300+ page document. Nothing built here is committed.
"""
import csv
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

from wars_scanner.text import keys_in

from wars_scanner import engine, golden, pipeline
from wars_scanner.pdf_reader import read

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = {d["file_name"]: d for d in csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8"))}
NONE_BOTH = {c: {"status": "NONE_PRESENT", "notes": ["(test) notes on fixed assets and other non-current assets"]}
             for c in ("t", "t1")}

_spec = importlib.util.spec_from_file_location("builder", ROOT / "tools" / "build_composite_annual_report.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def _src(name):
    p = PDF_DIR / name
    if not p.exists():
        pytest.skip(f"{name} not available (set WARS_TEST_PDF_DIR)")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == DOCS[name]["sha256"]
    return p


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = {}
    d = tmp_path_factory.mktemp("annual_reports")
    for name, fy in (("LK_SIDO_2021.pdf", 2021), ("LK_KLBF_2021.pdf", 2021)):
        src = _src(name)
        for variant in ("full", "front_only", "no_notes"):
            path = d / f"AR_{name[:-4]}_{variant}.pdf"
            info = builder.build(src, path, variant, fiscal_year=fy)
            out[(name, variant)] = (path, info, src)
    return out


@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_statements_found_beyond_page_255_with_same_values_and_shifted_pages(built, name):
    path, info, src = built[(name, "full")]
    assert info["pages"] > 300 and info["offset"] == 255
    ar, alone = read(path), read(src)
    off = info["offset"]
    assert {k: v.pages for k, v in ar.statements.items()} == \
        {k: [p + off for p in v.pages] for k, v in alone.statements.items()}
    assert ar.fs_location["chosen"]["notes_start"] == alone.fs_location["chosen"]["notes_start"] + off
    a = {(v.field, v.column): v for v in alone.values}
    for v in ar.values:
        w = a[(v.field, v.column)]
        assert (v.value, v.status) == (w.value, w.status), v.field
        assert v.pages == [p + off for p in w.pages], v.field          # source page = same page, shifted
        assert v.quotes == w.quotes, v.field                           # same printed line
    assert all(ok for _, _, ok, _ in ar.checks)


def test_highlights_pages_are_never_taken_as_statements(built):
    path, info, _ = built[("LK_SIDO_2021.pdf", "full")]
    loc = read(path).fs_location
    for kind, pages in loc["candidates"].items():
        assert all(p > info["offset"] for p in pages), (kind, pages)   # front-matter traps p10/p11 rejected


def test_full_annual_report_gives_the_same_m_score_as_the_standalone_statements(built):
    path, _, _ = built[("LK_SIDO_2021.pdf", "full")]
    r = pipeline.apply_non_ppe_decisions(pipeline.run(path, "SIDO"), NONE_BOTH)
    gp, _ = golden.load(ROOT / "data/golden/SIDO_2021.csv")
    assert r.m_score == pytest.approx(engine.calculate(gp)["m_score_B"], abs=1e-12)


@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_document_without_statements_fails_explicitly(built, name):
    path, _, _ = built[(name, "front_only")]
    r = pipeline.run(path, "X")
    assert not r.extraction.statements and r.m_score is None and r.status == "NOT CALCULATED"
    assert "tidak ditemukan" in r.unreadable and "Ikhtisar" in r.unreadable
    assert all(v.value is None for v in r.extraction.values)          # nothing read from the highlights


@pytest.mark.parametrize("name", ["LK_SIDO_2021.pdf", "LK_KLBF_2021.pdf"])
def test_statements_without_notes_fail_explicitly(built, name):
    path, _, _ = built[(name, "no_notes")]
    r = pipeline.run(path, "X")
    assert r.extraction.statements and r.m_score is None and r.status == "NOT CALCULATED"
    assert "CALK" in r.unreadable
    for v in r.extraction.values:
        if v.field in ("taxes_payable", "depreciation_amortization_total", "ppe_depreciation_disclosed"):
            assert v.value is None and v.status == "NOT SEARCHED"


def test_scanned_statements_still_refused():
    r = pipeline.run(_src("LK_MYOR_2021.pdf"), "MYOR")
    assert not r.extraction.statements and r.m_score is None
    assert "issue.scanned" in keys_in(r.unreadable) and "OCR" in r.unreadable


# ------------------------------------------------------------------ acceptance tool (real annual report)
_aspec = importlib.util.spec_from_file_location("accept", ROOT / "tools" / "accept_real_annual_report.py")
accept = importlib.util.module_from_spec(_aspec)
_aspec.loader.exec_module(accept)


def test_acceptance_tool_passes_assembled_document_and_fails_front_only(built):
    """Self-test of tools/accept_real_annual_report.py before it is used on the real KLBF 2021 report."""
    path, _, src = built[("LK_KLBF_2021.pdf", "full")]
    ok, md = accept.run(path, src, "PT Kalbe Farma Tbk", 2021)
    assert ok, md
    bad, _, _ = built[("LK_KLBF_2021.pdf", "front_only")]
    ok, md = accept.run(bad, src, "PT Kalbe Farma Tbk", 2021)
    assert not ok and "statements located | **FAIL**" in md


def test_real_klbf_2021_annual_report_acceptance():
    """Phase D acceptance (Gail, 23 Oct 2026): the REAL KLBF 2021 Laporan Tahunan, read unchanged,
    against the audited LK. Skipped until the file is supplied (AR_KLBF_2021.pdf in WARS_TEST_PDF_DIR)."""
    ar = PDF_DIR / "AR_KLBF_2021.pdf"
    if not ar.exists():
        pytest.skip("real annual report AR_KLBF_2021.pdf not available: Phase D acceptance PENDING")
    assert hashlib.sha256(ar.read_bytes()).hexdigest() == DOCS["AR_KLBF_2021.pdf"]["sha256"]
    ok, md = accept.run(ar, _src("LK_KLBF_2021.pdf"), "PT Kalbe Farma Tbk", 2021)
    assert ok, md
