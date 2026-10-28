"""Reader changes from the cross-sector Trial 1 (28 Oct 2026). Unit tests on synthetic text only; the
Trial 1 PDFs are not in the repository (identified by SHA-256 in the project document
WARS_Trial1_Kekurangan_r0).

* P1 number format: 1,234,567 (English style) is read as 1.234.567; a mix of styles is not read.
* P6 text-layer artefacts: "145.027)" (bracket after positives), "--" for nil, "2 0 2 1" years.
* Sentence amounts: duplicates from interleaved bilingual text are removed by value.
* P8: investment property whose depreciation is not read is never taken as 0.
"""
from wars_scanner import pipeline
from wars_scanner.notes_reader import _year_header as note_year_header
from wars_scanner.notes_reader import sentence_pair
from wars_scanner.pdf_reader import (NIL, Extraction, NOTE_REF, Line, Word, _currency, _normalise, _unit_scale, _year_header,
                                     number_format, paren_artifact, parse_amount)


def test_number_format_detection():
    comma = ["Kas 4 42,350,368,854 117,081,264,745 Cash"] * 6
    dot = ["Kas 4 42.350.368.854 117.081.264.745 Cash"] * 6
    assert number_format(comma) == "comma"
    assert number_format(dot) == "dot"
    assert number_format(comma + dot) == "mixed"
    assert number_format(["Kas 1,234 5,678"]) == "dot"          # one-group figures are not evidence


def test_comma_figures_are_rewritten_and_decimals_are_not_amounts():
    assert _normalise("42,350,368,854", "comma") == "42.350.368.854"
    assert _normalise("(5,764,949)", "comma") == "(5.764.949)"
    assert parse_amount(_normalise("248.17", "comma")) is None         # earnings per share, not 248.170
    assert parse_amount(_normalise("1.250", "comma")) is None          # a decimal in an English-style report
    assert _normalise("42,350", "dot") == "42,350"                     # Indonesian style: untouched


def test_bracket_artefact_and_nil():
    texts = ["Kas 2b 145.027) 102.305) Cash"] * 6
    assert paren_artifact(texts)
    assert not paren_artifact(["Beban (1.234.567) (2.345.678)"] * 6)
    assert parse_amount(_normalise("145.027)", "dot+paren")) == 145027
    assert parse_amount(_normalise("(10.315.504)", "dot+paren")) == -10315504
    assert "--" in NIL


def test_note_references_with_ampersand_and_letters():
    for ref in ("2u,28,33&34", "2m,2o&12", "14.a", "7.c", "4,32,33", "15a"):
        assert NOTE_REF.match(ref), ref
    assert not NOTE_REF.match("1.234.567")


def _line(texts, x=10.0):
    words = []
    for t in texts:
        words.append(Word(t, x, x + 5, 100.0))
        x += 8
    return Line(1, 100.0, words)


def test_spaced_year_headers():
    ln = _line(["Notes", "2", "0", "2", "1", "2", "0", "2", "0"])
    year, t_first, _ = _year_header([ln])
    assert year == 2021 and t_first
    hdr = note_year_header(_line(["2", "0", "2", "1", "2", "0", "2", "0"]), 2021)
    assert hdr["t"][0] == 2021 and hdr["t1"][0] == 2020 and hdr["t_first"]


def test_us_dollar_unit_and_currency():
    head = "(Dinyatakan dalam Dolar Amerika Serikat, kecuali Dinyatakan Lain) (Expressed in United States Dollar)"
    assert _currency(head) == "USD" and _unit_scale(head) == "Units"
    assert _currency("(Disajikan dalam jutaan Rupiah)") == "IDR"
    assert _unit_scale("(Expressed in thousands of US Dollars)") == "Thousands"


def test_sentence_pair_removes_interleaved_duplicates():
    after = (" Rp1.327.297.173 dan Rp1,327,297,173 and Rp702,594,053, respectively Rp702.594.053 (Catatan 31.b)")
    assert sentence_pair(after, "untuk tahun-tahun yang berakhir pada tanggal 31 Desember 2021 dan 2020") == \
        {"t": 1327297173, "t1": 702594053}
    assert sentence_pair(" Rp 4.022.695.983 dan Rp 2.967.824.737", "tahun 2020 dan 2021") == \
        {"t": 2967824737, "t1": 4022695983}
    assert sentence_pair(" Rp 4.022.695.983 saja", "") == {}


def test_unread_investment_property_depreciation_is_not_taken_as_zero():
    """P8: with investment property on the face and no depreciation read, the year stays NOT ASSESSED."""
    ex = Extraction("x.pdf", 1, [], 2021, "Units", "Consolidated", {}, [], [],
                    non_ppe_evidence={"invprop_face": {"page": 6, "text": "Properti investasi"}, "amounts_read": {}})
    r = pipeline.Result(ex, {"non_ppe_status_t": None, "non_ppe_status_t1": None}, {})
    out = pipeline.apply_provisional(r)
    assert out.non_ppe_pending == ["t", "t1"]
    assert not [a for a in out.assumed if a[0] == "depreciation_amortization_non_ppe"]
