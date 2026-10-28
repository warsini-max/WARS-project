"""Presentation layer: screening language only, drivers in the right direction."""
import re
from types import SimpleNamespace

from wars_scanner import report
from wars_scanner.pipeline import Result
from wars_scanner.text import Msg, t

FORBIDDEN = re.compile(r"fraud (detected|terdeteksi|terbukti)|terbukti (fraud|curang|manipulasi)|"
                       r"melakukan (fraud|manipulasi)|is a fraud|committed", re.I)


def _result(m, idx, review=()):
    calc = {"m_score_B": m, "not_ready_reason": "" if m is not None else "missing or non-numeric required input (fiscal year t)"}
    calc.update(idx)
    ex = SimpleNamespace(values=[], checks=[], issues=[])
    assessed = {"non_ppe_status_t": "NONE_PRESENT", "non_ppe_status_t1": "NONE_PRESENT"}
    return Result(ex, assessed, calc, list(review), [], [])


NEUTRAL = {"DSRI": 1, "GMI": 1, "AQI": 1, "SGI": 1, "DEPI": 1, "SGAI": 1, "LVGI": 1, "TATA": 0}


def test_verdict_levels_and_language():
    """M-09 A (Gail, 23 Oct 2026): one threshold (−1.78) on screen; no 'medium' band."""
    for m, level in ((-1.2, "high"), (-1.6, "high"), (-2.5, "low"), (None, "none")):
        for lang in ("id", "en"):
            head, detail, lv = report.verdict(_result(m, NEUTRAL), lang=lang)
            assert lv == level
            assert not FORBIDDEN.search(head + detail)
            assert "1,49" not in head + detail and "1.49" not in head + detail
    head, _, _ = report.verdict(_result(-1.6, NEUTRAL), lang="en")
    assert head == "M-score −1.60: crosses the −1.78 threshold"
    head, detail, _ = report.verdict(_result(-2.5, NEUTRAL))
    assert head == "M-score −2,50: tidak melewati batas −1,78" and "Bukan jaminan" in detail
    assert not FORBIDDEN.search(t("app.disclaimer")) and not FORBIDDEN.search(t("app.disclaimer", "en"))
    assert "bukan bukti kecurangan" in t("app.disclaimer") and "not evidence of fraud" in t("app.disclaimer", "en")


def test_not_calculated_never_shows_a_score():
    head, detail, _ = report.verdict(_result(None, {}))
    assert "tidak dihitung" in head.lower() and "Tidak ada angka yang ditebak" in detail
    assert "kosong atau bukan angka (tahun berjalan)" in detail          # engine reason, from the catalogue
    _, detail, _ = report.verdict(_result(None, {}), lang="en")
    assert "missing or not a number (current year)" in detail and "No figure was guessed" in detail


def test_provisional_when_inputs_need_checking():
    _, detail, _ = report.verdict(_result(-2.5, NEUTRAL, review=[("x", "t", "REVIEW", "")]))
    assert "Sementara: 1 dari 1 hal kuning belum diperiksa." in detail


def test_drivers_follow_coefficient_sign_and_b_r1_rule():
    """B r1 §3: only DSRI, GMI, AQI, SGI and TATA become findings (K7); push must exceed 0.005."""
    idx = dict(NEUTRAL, DSRI=1.5, LVGI=0.8, SGAI=1.3, GMI=1.004)
    names = [d["index"] for d in report.drivers(_result(-2.0, idx))]
    assert names == ["DSRI"]                # LVGI raises M but is not significant; GMI push 0.002 too small
    rows = {d["index"]: d for d in report.index_rows(_result(-2.0, idx))}
    assert rows["LVGI"]["push_vs_neutral"] > 0 and rows["SGAI"]["push_vs_neutral"] < 0
    assert "Tidak signifikan" in rows["LVGI"]["note"]
    assert "Not significant" in report.index_rows(_result(-2.0, idx), "en")[6]["note"]


def test_decimal_format_per_language():
    assert report.dec(-2.31617) == "−2,316" and report.dec(-2.31617, 3, "en") == "−2.316"
    assert report.amount(1304100) == "1.304.100" and report.amount(1304100, "en") == "1,304,100"


def test_unreadable_report_explains_why():
    r = _result(None, {})
    r.unreadable = Msg("issue.scanned", k=10, pages=(1, 2, 3))
    head, detail, lv = report.verdict(r)
    assert lv == "none" and "pindai" in detail and "ticker" not in detail
    _, detail, _ = report.verdict(r, lang="en")
    assert "scanned images" in detail


def test_confirmation_states():
    items = [{"key": "a", "title": "A", "column": "t", "why": ""}, {"key": "b", "title": "B", "column": "t1", "why": ""}]
    s = report.confirmation_summary(items, {})
    assert s["state"] == "pending" and s["pending"] == 2
    s = report.confirmation_summary(items, {"a": report.OK_ANSWER, "b": report.OK_ANSWER})
    assert s["state"] == "confirmed"
    s = report.confirmation_summary(items, {"a": report.OK_ANSWER, "b": report.BAD_ANSWER})
    assert s["state"] == "bad" and s["bad"] == 1
    assert report.confirmation_summary([], {})["state"] == "none"


def test_rejected_input_withholds_the_reading():
    r = _result(-2.5, NEUTRAL, review=[("revenue", "t", "REVIEW", "")])
    items = report.review_items(r)
    bad = report.confirmation_summary(items, {items[0]["key"]: report.BAD_ANSWER})
    head, detail, lv = report.verdict(r, bad, reviewer="Gail")
    assert head == "M-score tidak dapat dipakai" and lv == "none" and detail.startswith("Gail menandai 1 hal")
    ok = report.confirmation_summary(items, {items[0]["key"]: report.OK_ANSWER})
    _, detail, _ = report.verdict(r, ok, reviewer="Gail")
    assert "bukan verifikasi independen" in detail and "Sementara" not in detail
    _, detail, _ = report.verdict(r, ok, "en", "Gail")
    assert "not independent verification" in detail


def test_awaiting_non_ppe_status_holds_the_score():
    r = _result(None, {})
    r.inputs = {}
    head, detail, lv = report.verdict(r)
    assert r.status == "AWAITING NON-PPE STATUS" and head == "M-score ditahan" and lv == "none"
    assert "tahun berjalan dan tahun pembanding" in detail and "Q6" not in detail      # codes only in detail views


def test_review_item_keys_do_not_depend_on_the_language():
    r = _result(-2.5, NEUTRAL, review=[("revenue", "t", "REVIEW", Msg("note.debt"))])
    a, b = report.review_items(r, "id"), report.review_items(r, "en")
    assert [i["key"] for i in a] == [i["key"] for i in b]
    assert a[0]["why"] == "Perlu diperiksa. Dipilih berdasarkan nama akun; periksa klasifikasinya [D-01, D-02]"
    assert b[0]["why"] == "Needs review. Selected by line-item label; check the classification [D-01, D-02]"


def test_financial_institution_is_not_scored_and_says_why():
    r = _result(None, {})
    r.unreadable = Msg("issue.financial_institution", items=("Kredit yang diberikan (hal. 5)",))
    head, detail, lv = report.verdict(r, lang="en")
    assert head == "M-score not calculated" and "does not apply to financial institutions" in detail and lv == "none"
