"""M-08 package (approved by Gail, 23 Oct 2026): workbook checks r_standard_transition,
r_standard_transition_other and r_comparative_label, with inputs read from the report.

Evidence must come from the disclosures or the column label, never from the year alone.
"""
import csv
import hashlib
import os
from pathlib import Path

import pytest

from wars_scanner.text import keys_in

from wars_scanner import pipeline, transition, validation
from wars_scanner.pdf_reader import Line, Statement, Word

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = {d["file_name"]: d for d in csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8"))}
_cache = {}


def _run(name):
    if name not in _cache:
        p = PDF_DIR / name
        if not p.exists():
            pytest.skip(f"{name} not available")
        assert hashlib.sha256(p.read_bytes()).hexdigest() == DOCS[name]["sha256"]
        _cache[name] = pipeline.run(p, "TEST")
    return _cache[name]


def _codes(r):
    return {f.code for f in r.flags}


# ------------------------------------------------------------------ the workbook conditions (synthetic inputs)
@pytest.mark.parametrize("t,t1,expected", [("Y", "N", True), ("Y", "Y", False), ("N", "N", False), ("Y", "", False)])
def test_r_standard_transition_condition_matches_workbook(t, t1, expected):
    flags = validation.check({"psak73_applied_t": t, "psak73_applied_t1": t1})
    assert ("r_standard_transition" in {f.code for f in flags}) == expected


@pytest.mark.parametrize("value,expected", [("PSAK 71; PSAK 72", True), ("", False), ("  ", False)])
def test_r_standard_transition_other_condition_matches_workbook(value, expected):
    flags = validation.check({"standards_first_applied_t": value})
    assert ("r_standard_transition_other" in {f.code for f in flags}) == expected


@pytest.mark.parametrize("label,expected", [("RESTATED", True), ("RECLASSIFIED", True),
                                            ("RESTATED_AND_RECLASSIFIED", True), ("NONE", False)])
def test_r_comparative_label_condition_matches_workbook(label, expected):
    flags = validation.check({"comparative_label_t1": label})
    assert ("r_comparative_label" in {f.code for f in flags}) == expected
    assert all(f.severity == "REVIEW" for f in flags)


# ------------------------------------------------------------------ detection from text (synthetic)
def test_first_application_found_with_date_close_to_the_mention():
    page = ("Grup menerapkan PSAK 73 dengan metode retrospektif yang dimodifikasi dengan tanggal penerapan awal "
            "1 Januari 2020. Grup tidak menyajikan kembali informasi komparatif.")
    fa = transition.first_applied(["cover", page], 2, 2020)
    assert fa["73"]["page"] == 2 and fa["73"]["t1_restated"] == "N"


def test_amendments_are_not_first_application():
    page = ("Standar yang berlaku efektif 1 Januari 2021: Amendemen PSAK 71, PSAK 55, PSAK 60, PSAK 62 dan PSAK 73 "
            "tentang reformasi acuan suku bunga tahap 2. Penerapan awal amendemen ini tidak berdampak material.")
    assert transition.first_applied([page], 1, 2021) == {}


def test_the_year_alone_is_not_evidence():
    page = "Grup menerapkan PSAK 73 sejak tanggal penerapan awal 1 Januari 2020."
    assert transition.first_applied([page], 1, 2021) == {}          # report year 2021, date 2020: no flag


def test_restated_column_label_is_read_from_the_header():
    def ln(text, amounts=None):
        x = Line(5, 0, [Word(w, 0, 10, 0) for w in text.split()])
        x.amounts = amounts or {}
        return x
    st = Statement("position", [5], [ln("31 Desember 2021"), ln("2020 (Disajikan kembali)"),
                                     ln("Kas dan setara kas", {"t": 1, "t1": 2})])
    assert transition.comparative_label({"position": st}) == ("RESTATED", [5])


# ------------------------------------------------------------------ real test documents
def test_klbf_2020_transition_year_flags_with_pages():
    r = _run("LK_KLBF_2020.pdf")
    assert {"r_standard_transition", "r_standard_transition_other"} <= _codes(r)
    assert r.inputs["standards_first_applied_t"] == "PSAK 71; PSAK 72"
    msg = next(f.message for f in r.flags if f.code == "r_standard_transition")
    assert "hal. 37" in msg


@pytest.mark.parametrize("name", ["LK_KLBF_2021.pdf", "LK_SIDO_2021.pdf", "LK_KLBF_2023_upload.pdf"])
def test_no_transition_flag_after_the_transition_year(name):
    # KLBF 2021 p148 has a table footnote "Dampak penerapan PSAK 73" for the 2020 column: not a first application
    r = _run(name)
    assert not ({"r_standard_transition", "r_standard_transition_other", "r_comparative_label"} & _codes(r))


def test_sido_2020_restatement_unknown_is_reported_not_guessed():
    r = _run("LK_SIDO_2020.pdf")
    assert r.inputs.get("psak73_applied_t") == "Y" and "psak73_applied_t1" not in r.inputs
    assert any("issue.transition_gap" in keys_in(i) for i in r.extraction.issues)


def test_transition_flags_do_not_change_the_score():
    r = _run("LK_KLBF_2020.pdf")
    dec = {c: {"status": "NONE_PRESENT", "notes": ["(test)"]} for c in ("t", "t1")}
    r2 = pipeline.apply_non_ppe_decisions(r, dec)
    assert round(r2.m_score_raw, 4) == -2.8835
    assert "r_standard_transition" in {f.code for f in r2.flags}      # still raised after the user decision
