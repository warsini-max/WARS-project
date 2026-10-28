"""M-15 C, four choices (approved by Gail, 23 Oct 2026).

When the reader finds no intangible assets, amortisation stays NOT ASSESSED and the score is held
until the user sets the status per year, with the notes/pages examined. Never 0 by the machine.
"""
import csv
import hashlib
import os
from pathlib import Path

import pytest

from wars_scanner.text import keys_in
from wars_scanner import pipeline, report

ROOT = Path(__file__).parents[1]
PDF_DIR = Path(os.environ.get("WARS_TEST_PDF_DIR", "/home/claude/s3core/docs"))
DOCS = {d["file_name"]: d for d in csv.DictReader(open(ROOT / "data" / "test_documents.csv", encoding="utf-8"))}
NP = {c: {"status": "NONE_PRESENT", "notes": ["(test) aset tetap; aset tidak lancar lainnya"]} for c in ("t", "t1")}
_cache = {}


def _run(name):
    if name not in _cache:
        p = PDF_DIR / name
        if not p.exists():
            pytest.skip(f"{name} not available")
        assert hashlib.sha256(p.read_bytes()).hexdigest() == DOCS[name]["sha256"]
        _cache[name] = pipeline.run(p, "TEST")
    return _cache[name]


def _am(status, notes=("(test) catatan 2, 10, 11",), cols=("t", "t1")):
    return {c: {"status": status, "notes": list(notes)} for c in cols}


def test_no_intangibles_found_holds_the_score_and_never_enters_zero():
    r = pipeline.apply_non_ppe_decisions(_run("LK_MYOR_2020.pdf"), NP)
    assert r.amort_pending == ["t", "t1"]
    assert r.m_score is None and r.status == "AWAITING AMORTISATION STATUS"
    assert all(v.value is None for v in r.extraction.values if v.field == "amortization_intangibles")
    head, detail, _ = report.verdict(r)
    assert head == "M-score ditahan" and "Aset takberwujud tidak ditemukan" in detail


@pytest.mark.parametrize("choice", ["NONE_PRESENT", "GOODWILL_ONLY", "INDEFINITE_ONLY"])
def test_three_zero_choices_give_the_same_score_without_review(choice):
    r = pipeline.apply_user_decisions(_run("LK_MYOR_2020.pdf"), NP, _am(choice))
    assert round(r.m_score_raw, 4) == -2.8994
    assert not r.amort_pending and r.amort_decisions["t"]["status"] == choice
    assert "r_amort_undisclosed" not in {f.code for f in r.flags}
    v = next(v for v in r.extraction.values if v.field == "amortization_intangibles" and v.column == "t")
    assert v.value == 0 and v.status == "USER SET" and "note.am_set" in keys_in(v.note)
    assert "notes examined: (test)" in v.note.render("en")


def test_undisclosed_is_flagged_and_not_shown_as_an_actual_zero():
    r = pipeline.apply_user_decisions(_run("LK_MYOR_2020.pdf"), NP, _am("UNDISCLOSED"))
    assert round(r.m_score_raw, 4) == -2.8994
    assert "r_amort_undisclosed" in {f.code for f in r.flags}
    v = next(v for v in r.extraction.values if v.field == "amortization_intangibles" and v.column == "t")
    assert v.status == "UNDISCLOSED" and "not a statement that the charge is nil" in v.note.render("en")
    row = next(x for x in report.input_rows(r) if x["field"] == "amortization_intangibles")
    assert row["status_t"] == "Tidak diungkapkan (dihitung 0)"          # Gail, 28 Oct 2026


def test_each_year_is_set_separately():
    r = pipeline.apply_user_decisions(_run("LK_MYOR_2020.pdf"), NP, _am("NONE_PRESENT", cols=("t",)))
    assert r.amort_pending == ["t1"] and r.m_score is None


def test_a_choice_needs_the_notes_examined():
    with pytest.raises(pipeline.DecisionError):
        pipeline.apply_amort_decisions(_run("LK_MYOR_2020.pdf"), _am("GOODWILL_ONLY", notes=()))


def test_choice_not_applicable_when_amortisation_was_read():
    r = _run("LK_SIDO_2021.pdf")                 # intangibles present: the reader already set G-22 UNDISCLOSED
    assert not r.amort_pending
    with pytest.raises(pipeline.DecisionError):
        pipeline.apply_amort_decisions(r, _am("NONE_PRESENT"))
