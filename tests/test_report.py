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
    # disclaimer in professional English in both versions (Gail, 4 Nov 2026)
    assert t("app.disclaimer") == t("app.disclaimer", "en") and "not constitute a conclusion of fraud" in t("app.disclaimer")


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
    # rule codes are never shown to the user (Gail, 28 Oct 2026, report review)
    assert a[0]["why"] == "Perlu diperiksa. Dipilih berdasarkan nama akun; periksa klasifikasinya"
    assert b[0]["why"] == "Needs review. Selected by line-item label; check the classification"


def test_financial_institution_is_not_scored_and_says_why():
    r = _result(None, {})
    r.unreadable = Msg("issue.financial_institution", items=("Kredit yang diberikan (hal. 5)",))
    head, detail, lv = report.verdict(r, lang="en")
    assert head == "M-score not calculated" and "was not designed to assess financial institutions" in detail and lv == "none"


def test_finding_chart_uses_the_figures_behind_the_index():
    """Gail, 29 Oct 2026: one small chart per finding, both years; no chart from an incomplete pair."""
    from wars_scanner.report import compact_money, finding_chart
    r = _result(-2.5, NEUTRAL)
    r.inputs.update({"accounts_receivable_t": 30.0, "accounts_receivable_t1": 10.0, "revenue_t": 100.0, "revenue_t1": 80.0})
    ch = finding_chart(r, "DSRI", "en")
    # Gail 11 Nov 2026 (option A): the accounts as bars, the ratio in the caption
    assert ch["kind"] == "money" and ch["series"][0][1] == {"t": 30.0, "t1": 10.0}
    assert ch["series"][1][1] == {"t": 100.0, "t1": 80.0} and ch["ratio"] == {"t": 0.3, "t1": 0.125}
    assert "12.5%" in ch["caption"] and "30.0%" in ch["caption"]
    r.inputs["revenue_t1"] = None
    assert finding_chart(r, "DSRI", "en") is None
    assert compact_money(252448924906, "Units", "IDR", "id") == "Rp252,4 M"
    assert compact_money(-140738938560, "Units", "IDR", "en") == "−Rp140.7bn"


# ---------------------------------------------------------------- score scale (Gail, 4 Nov 2026: labels overlapped for an extreme score)
def test_scale_is_capped_and_marks_scores_beyond_it():
    from wars_scanner.report import scale_range
    assert scale_range(-19.96) == (-4.5, -0.5, "below")
    assert scale_range(3.13) == (-3.5, 1.5, "above")


def test_scale_unchanged_for_ordinary_scores():
    # negative: a score inside the usual range keeps the usual scale and no arrow
    from wars_scanner.report import scale_range
    assert scale_range(-2.37) == (-3.5, -0.5, "")
    assert scale_range(-3.9) == (-4.0, -0.5, "")
    assert scale_range(None) == (-3.5, -0.5, "")


# ---------------------------------------------------------------- part C from the company's figures (Gail, 8 Nov 2026)
def _dsri(ar_t, ar_t1, rev_t, rev_t1, dsri):
    r = _result(-1.5, {**NEUTRAL, "DSRI": dsri})
    r.inputs.update({"accounts_receivable_t": ar_t, "accounts_receivable_t1": ar_t1, "revenue_t": rev_t, "revenue_t1": rev_t1})
    return r


def _keys(r, k):
    return [s for s, _ in report.c_signals(r, k)]


def test_c_dsri_names_the_mechanism():
    # sales fell 40 %, receivables fell 23 %: the ratio rose because of lower sales
    assert _keys(_dsri(77, 100, 60, 100, 1.28), "DSRI") == ["c.DSRI_denom"]
    # sales fell, receivables rose: both directions
    assert _keys(_dsri(112, 100, 60, 100, 1.87), "DSRI") == ["c.DSRI_both"]
    # sales rose 8 %, receivables rose 56 %: receivables grew faster
    assert _keys(_dsri(156, 100, 108, 100, 1.44), "DSRI") == ["c.DSRI_numer"]


def test_c_dsri_falling_sales_drops_the_general_reasons():
    r = _dsri(77, 100, 60, 100, 1.28)
    for lang in ("id", "en"):
        c = report.c_part(r, "DSRI", lang)
        assert c == t("c.DSRI_denom", lang)
        assert t("c.DSRI", lang) not in c
    # negative: receivables growing faster keeps the general list after the specific sentence
    c = report.c_part(_dsri(156, 100, 108, 100, 1.44), "DSRI", "id")
    assert c.startswith(t("c.DSRI_numer", "id")) and t("c.DSRI", "id") in c


def test_c_falls_back_to_the_general_list():
    # negative: missing or zero figures never produce a specific sentence
    for r in (_dsri(None, 100, 60, 100, 1.3), _dsri(77, 100, 60, 0, 1.3), _dsri(77, 100, 0, 100, 1.3)):
        assert report.c_signals(r, "DSRI") == []
        assert report.c_part(r, "DSRI", "id") == t("drivers.c", "id", items=Msg("c.DSRI"))
    # negative: indices without a data rule keep the general list
    r = _dsri(77, 100, 60, 100, 1.28)
    assert report.c_part(r, "GMI", "en") == t("drivers.c", "en", items=Msg("c.GMI"))


def test_c_small_base_only_when_base_tiny_and_index_high():
    # receivables last year 0.05 % of sales, DSRI 37: small-base sentence
    assert "c.small_base_DSRI" in _keys(_dsri(2010, 52.8, 120000, 105000, 37.1), "DSRI")
    # negative: tiny base but ordinary index
    assert "c.small_base_DSRI" not in _keys(_dsri(1.1, 0.5, 120000, 105000, 1.9), "DSRI")
    # negative: high index but base not small (receivables 20 % of sales)
    assert "c.small_base_DSRI" not in _keys(_dsri(80, 20, 50, 100, 8.0), "DSRI")


def test_c_small_base_aqi():
    r = _result(-1.5, {**NEUTRAL, "AQI": 4.9})
    r.inputs.update({"current_assets_t1": 600.0, "property_plant_equipment_net_t1": 397.0, "total_assets_t1": 1000.0})
    assert _keys(r, "AQI") == ["c.small_base_AQI"]          # soft assets 0.3 % of total assets
    r.inputs["property_plant_equipment_net_t1"] = 300.0
    assert _keys(r, "AQI") == []                             # negative: soft assets 10 %
    r.inputs["property_plant_equipment_net_t1"] = 397.0
    r.calc["AQI"] = 1.5
    assert _keys(r, "AQI") == []                             # negative: index below the limit
