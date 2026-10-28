"""The bilingual text catalogue (UI review r1, analysis rules B r1, language rule of 23 Oct 2026).

* every entry exists in both languages with the same placeholders;
* rule codes never sit inside a sentence (they are added only in detail views);
* banned wording (B r1 §2) appears in neither language;
* the EN version contains no Indonesian words; the ID version no English words except fixed terms;
* on the test documents every message renders in both languages with the same numbers.
"""
import re
from pathlib import Path

import pytest

from wars_scanner import pipeline, report
from wars_scanner.text import APPROVED_SRC, CATALOG, LANGS, Msg, keys_in, placeholders, render, review_list

PDF_DIR = Path(__file__).resolve().parents[1].parent / "s3core" / "docs"
ENTRIES = {k: e for k, e in CATALOG.items() if not k.startswith("_")}


def _plain(s):
    """Template text without its placeholders."""
    return re.sub(r"\{[^}]*\}", " ", s)


def test_every_entry_has_both_languages_and_the_same_placeholders():
    for k, e in ENTRIES.items():
        for lang in LANGS:
            assert e[lang].strip(), (k, lang)
        assert placeholders(e["id"]) == placeholders(e["en"]), k
        assert e["src"], k


CODE = re.compile(r"\b(D|G|M|Q|DP|DP-0|D13)-?\d")


def test_rule_codes_are_not_inside_sentences():
    """A2 / K8: codes such as [D-08] are added by render(codes=True) in detail views only."""
    for k, e in ENTRIES.items():
        for lang in LANGS:
            assert not CODE.search(e[lang]), (k, lang, e[lang])


BANNED_ID = [r"fraud terdeteksi", r"terbukti (fraud|curang|memanipulasi)", r"melakukan kecurangan",
             r"manipulasi terbukti", r"\bmemanipulasi\b", r"\b(di)?sengaja\b", r"menyembunyikan", r"merekayasa",
             r"mengelabui", r"(?<!perlu )(?<!belum dapat )(?<!tidak dapat )\bdipastikan\b", r"(?<!kurang )\bpasti\b", r"jelas menunjukkan",
             r"berisiko tinggi", r"skor fraud", r"probabilitas manipulasi", r"direkomendasikan", r"\bsebaiknya\b",
             r"\baman\b", r"bebas red flag", r"tidak ada masalah", r"bukti tunggal", r"terdorong untuk",
             r"mirip perusahaan"]
BANNED_EN = [r"fraud detected", r"proven fraud", r"committed fraud", r"\bmanipulated\b", r"intentionally",
             r"deliberately", r"concealed", r"engineered", r"\bmisled\b", r"\bcertainly\b", r"clearly shows",
             r"\bproves\b", r"high fraud risk", r"fraud score", r"probability of manipulation", r"we recommend",
             r"\bshould\b", r"\bsafe\b", r"free of red flags", r"no issues", r"standalone evidence",
             r"incentivised to", r"resembles companies"]
PRESSURE = {"id": r"menghadapi tekanan", "en": r"(under|face) pressure"}


@pytest.mark.parametrize("lang,banned", [("id", BANNED_ID), ("en", BANNED_EN)])
def test_banned_wording(lang, banned):
    for k, e in ENTRIES.items():
        text = e[lang].lower()
        for b in banned:
            assert not re.search(b, text), (k, b)
        if not k.startswith("why."):           # the model's rationale, written in the model's name (B r1 P1)
            assert not re.search(PRESSURE[lang], text), k


INDONESIAN = r"""dan yang tidak dengan untuk dari atau ini itu ada aset utang piutang laporan catatan halaman hal tahun
beban penyusutan amortisasi pajak kas laba rugi pendapatan penjualan belum sudah perlu diperiksa angka nilai
calk pasal neto berjalan pembanding ditemukan ditetapkan pengguna kuning merah hijau sesuai konsolidasian jutaan
ribuan miliar juta dicek cek bukan skor batas rasio indeks periksa lihat""".split()
FIXED_TERMS = ["red flag", "M-score", "WARS Scanner", "Window-dressing Accounting Red-Flag Scanner", "PDF", "CSV",
               "SHA-256", "OCR", "Beneish", "PSAK", "goodwill", "DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI",
               "TATA", "WARS", "Rp", "IDX", "vs", "Status", "Workbook v0.6", "Window-dressing Accounting Red-Flag Scanner",
               "BENEISH M-SCORE", "Excel", "Track B", "Red Flag"]
# R-06 (Gail 23 Oct 2026): the report footer disclaimer is English in both versions, by decision.
ENGLISH_BY_DECISION = {"rep.footer_disclaimer", "rep.title"}     # report title: Gail, 28 Oct 2026
ENGLISH = r"""the and of not is are was were found review check see with from for only assets asset table notes note page
year current statement statements threshold workbook score screen flag figures read reading value values
total liabilities equity revenue sales depreciation amortisation amortization""".split()


def test_english_version_has_no_indonesian_words():
    for k, e in ENTRIES.items():
        if k == "app.lang":                    # the language switch names both languages on purpose
            continue
        words = set(re.findall(r"[a-zA-Z]+", _plain(e["en"]).lower()))
        assert not words & set(INDONESIAN), (k, words & set(INDONESIAN))


def test_indonesian_version_has_no_english_words_except_fixed_terms():
    for k, e in ENTRIES.items():
        if k in ENGLISH_BY_DECISION:
            continue
        s = _plain(e["id"])
        for term in sorted(FIXED_TERMS, key=len, reverse=True):
            s = s.replace(term, " ")
        words = set(re.findall(r"[a-zA-Z]+", s.lower()))
        allowed = {"total"}                    # 'total aset' is Indonesian usage (PSAK 201)
        assert not (words & set(ENGLISH)) - allowed, (k, (words & set(ENGLISH)) - allowed)


def test_review_list_covers_every_unapproved_entry():
    keys = {k for k, *_ in review_list()}
    for k, e in ENTRIES.items():
        approved = re.match(APPROVED_SRC, e["src"])
        assert (k in keys) != bool(approved), k


# ----------------------------------------------------------------------------- on the test documents

DOCS = ["LK_SIDO_2020.pdf", "LK_KLBF_2021.pdf", "LK_KLBF_2023_upload.pdf", "LK_MYOR_2020.pdf", "LK_MYOR_2021.pdf"]


@pytest.fixture(scope="module")
def results():
    out = {}
    for name in DOCS:
        p = PDF_DIR / name
        if not p.exists():
            continue
        r = pipeline.run(str(p), "X")
        if not r.unreadable:
            am = {c: {"status": "UNDISCLOSED", "notes": ["(test) note 12"]} for c in r.amort_pending}
            np_ = {"t": {"status": "NONE_PRESENT", "notes": ["(test) note 10"]},
                   "t1": {"status": "PARTIAL_UNDISCLOSED", "notes": ["(test) note 11"]}}
            r = pipeline.apply_user_decisions(r, np_, am)
        out[name] = r
    if not out:
        pytest.skip("test documents not available")
    return out


def _messages(r):
    ex = r.extraction
    yield from ex.issues
    for v in ex.values:
        yield v.note
        yield v.components
    for name, _, _, det in ex.checks:
        yield name
        yield det
    for f in r.flags:
        yield f.message
    yield from r.passed
    yield from r.assumptions
    yield r.unreadable
    for f, c, s, note in r.review + r.missing:
        yield note


def _numbers(s):
    return sorted(re.findall(r"\d+", re.sub(r"(?<=\d)[.,](?=\d)", "", s)))


def test_every_message_is_from_the_catalogue_and_renders_in_both_languages(results):
    for name, r in results.items():
        for m in _messages(r):
            if not m:
                continue
            assert isinstance(m, Msg), (name, m)
            for lang in LANGS:
                s = m.render(lang, codes=True)
                assert s and "{" not in s, (name, m.key, lang)
            # same figures and pages in both languages (R-03, R-04)
            assert _numbers(m.render("id")) == _numbers(m.render("en")), (name, m.key)


def test_screen_texts_render_in_both_languages_with_the_same_numbers(results):
    for name, r in results.items():
        for lang in LANGS:
            report.verdict(r, None, lang)
            report.input_rows(r, lang)
            report.review_items(r, lang)
            report.index_rows(r, lang)
            for d in report.drivers(r, lang=lang):
                report.finding(r, d["index"], None, lang)
        h_id, d_id, _ = report.verdict(r, None, "id")
        h_en, d_en, _ = report.verdict(r, None, "en")
        assert _numbers(h_id) == _numbers(h_en)
        for d in report.drivers(r):
            assert _numbers(report.finding(r, d["index"])["a"]) == _numbers(report.finding(r, d["index"], None, "en")["a"])


def test_messages_pickle_for_the_app_cache(results):
    import pickle
    r = next(iter(results.values()))
    r2 = pickle.loads(pickle.dumps(r))
    a = [render(m, "en", True) for m in _messages(r)]
    b = [render(m, "en", True) for m in _messages(r2)]
    assert a == b


def test_disclaimer_is_shown_in_both_languages_without_an_upload():
    from streamlit.testing.v1 import AppTest
    root = Path(__file__).resolve().parents[1]
    for lang in LANGS:
        at = AppTest.from_file(str(root / "app.py"), default_timeout=60)
        at.session_state["lang"] = lang
        at.run()
        shown = " ".join(x.value for x in at.markdown)
        assert CATALOG["app.disclaimer"][lang] in shown, lang
        assert not at.exception
