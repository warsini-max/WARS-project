"""Rule 7 (Gail, 28 Oct 2026): a wrong line picked is the worst failure. Every matching rule has a negative test
(what it must NOT match) and the cross-checks that keep a figure from being FOUND are tested here.
Synthetic text only; the shapes are taken from Trial 1 documents (BIRD, BIPP, FASW, SILO, SIDO 2020).
"""
from types import SimpleNamespace

from wars_scanner import notes_reader as nr
from wars_scanner.notes_reader import PageCache
from wars_scanner.pdf_reader import Line, Word, _assign_amounts, _candidates, _section_sums, _value_pair


def _ln(label, t=None, t1=None, page=1, full_label=None):
    ln = Line(page, 0.0, [Word(x, 0, 1, 0) for x in label.split()])
    ln.label, ln.full_label = label, full_label if full_label is not None else label
    ln.amounts = {k: v for k, v in (("t", t), ("t1", t1)) if v is not None}
    return ln


class FakeCache(PageCache):
    """Note pages given as ready-made lines: {page: [Line, ...]}; text is the joined labels."""

    def __init__(self, pages, n=None):
        n = n or max(pages)
        self.fmt, self.fiscal_year, self.notes_start = "dot", 2021, 1
        self._lines = {p: pages.get(p, []) for p in range(1, n + 1)}
        self.text = [" ".join(ln.label or ln.text for ln in self._lines[p]) for p in range(1, n + 1)]

    def lines(self, p):
        return self._lines.get(p, [])


# ----------------------------------------------------------------------------- PPE: face vs note carrying amount

def _words_line(*texts, page=1):
    return Line(page, 0.0, [Word(x, 0, 1, 0) for x in texts])


def test_ppe_face_agrees_with_note_carrying_amount():
    cache = FakeCache({2: [_words_line("Aset", "tetap"), _words_line("Nilai", "tercatat", "4.938.177", "5.668.030", page=2)]})
    out = nr.ppe_note_carrying(cache, 1, {"t": 4938177, "t1": 5668030})
    assert out == {"t": ("ok", 2), "t1": ("ok", 2)}


def test_ppe_face_that_is_another_line_is_a_mismatch():
    """BIRD 2021: 'Uang muka pembelian aset tetap 58.997' read as fixed assets must not pass."""
    cache = FakeCache({2: [_words_line("Aset", "tetap"), _words_line("Nilai", "tercatat", "4.938.177", "5.668.030", page=2)]})
    out = nr.ppe_note_carrying(cache, 1, {"t": 58997, "t1": 95906})
    assert out["t"][0] == "mismatch" and out["t1"][0] == "mismatch"


def test_ppe_check_not_made_without_a_carrying_line():
    cache = FakeCache({2: [_words_line("Aset", "tetap"), _words_line("Saldo", "akhir", "4.938.177", "5.668.030", page=2)]})
    assert nr.ppe_note_carrying(cache, 1, {"t": 4938177})["t"] == ("none", None)


# ----------------------------------------------------------------------------- section sums

def _pos(lines):
    return SimpleNamespace(lines=lines)


def test_section_lines_add_up_to_the_printed_total():
    lines = [_ln("ASET LANCAR"), _ln("Kas", 10, 8), _ln("Piutang usaha", 5, 4), _ln("Jumlah aset lancar", 15, 12)]
    passed, issues = _section_sums(_pos(lines))
    assert len(passed) == 2 and not issues


def test_section_that_does_not_add_up_is_reported():
    """SIDO 2020: a note reference read as a figure shows up here."""
    lines = [_ln("ASET LANCAR"), _ln("Kas", 10, 8), _ln("Piutang usaha", 12, 4), _ln("Jumlah aset lancar", 15, 12)]
    passed, issues = _section_sums(_pos(lines))
    assert len(passed) == 1 and len(issues) == 1


# ----------------------------------------------------------------------------- reading figures off a line

def _line_words(*texts):
    x, words = 10.0, []
    for t in texts:
        words.append(Word(t, x, x + 5, 100.0))
        x += 8
    return Line(1, 100.0, words)


def test_note_reference_between_two_figures_is_not_a_figure():
    ln = _assign_amounts(_line_words("Goodwill", "91.366", "12", "91.366", "Goodwill"))
    assert ln.amounts == {"t": 91366, "t1": 91366}


def test_two_figures_with_separators_are_both_kept():
    ln = _assign_amounts(_line_words("Kas", "1.234", "5.678", "Cash"))
    assert ln.amounts == {"t": 1234, "t1": 5678}


def test_date_in_a_label_is_not_a_figure():
    """BIPP 2021: 'per 31 Desember' inside the label."""
    ln = _assign_amounts(_line_words("Saldo", "per", "31", "Desember", "1.234", "5.678"))
    assert ln.amounts == {"t": 1234, "t1": 5678}
    assert "31" in ln.label


def test_loss_and_cash_outflow_keep_their_sign():
    ln = _ln("Rugi tahun berjalan", -500, -300)
    assert [v.value for v in _value_pair("net_income", ln, "FOUND")] == [-500, -300]
    assert [v.value for v in _value_pair("cash_flow_from_operations", ln, "FOUND")] == [-500, -300]
    assert [v.value for v in _value_pair("cost_of_goods_sold", ln, "FOUND")] == [500, 300]


# ----------------------------------------------------------------------------- ambiguity

def test_two_lines_with_the_same_label_and_different_amounts_are_both_candidates():
    lines = [_ln("Aset tetap", 100, 90), _ln("Aset tetap", 40, 30)]
    assert len(_candidates(lines, r"^aset tetap$")) == 2


def test_tail_of_a_wrapped_label_is_not_a_candidate():
    lines = [_ln("Uang muka pembelian"), _ln("aset tetap", 58997, 95906, full_label="Uang muka pembelian aset tetap"),
             _ln("Aset tetap", 4938177, 5668030)]
    assert [x.amounts["t"] for x in _candidates(lines, r"^aset tetap$")] == [4938177]


# ----------------------------------------------------------------------------- taxes payable (D-03)

def _face(t, t1):
    return _ln("Utang pajak", t, t1)


def test_tax_table_split_into_company_and_subsidiaries_with_a_grand_total():
    """BIPP 2021: 'Perusahaan' table, then 'Entitas anak' table on the next page, then JUMLAH = both."""
    p1 = [_ln("19. PERPAJAKAN"), _ln("b. Utang Pajak"), _ln("Perusahaan"),
          _ln("Pajak Penghasilan Pasal 21", 11, 16, 1), _ln("Pajak Penghasilan Pasal 23", 3, 1, 1),
          _ln("Jumlah", 14, 17, 1)]
    p2 = [_ln("19. PERPAJAKAN (Lanjutan)"), _ln("Entitas Anak"),
          _ln("Pajak Pertambahan Nilai", 700, 2600, 2), _ln("Pajak Penghasilan Pasal 29", 1, 5, 2),
          _ln("Pajak Penghasilan Pasal 25", 11, 10, 2), _ln("Pajak Penghasilan Final", 0, 2, 2),
          _ln("Jumlah", 712, 2617, 2), _ln("JUMLAH", 726, 2634, 2)]
    cache = FakeCache({1: p1, 2: p2})
    values, checks, issues = nr.tax_payable(cache, 1, _face(726, 2634))
    got = {v.column: (v.value, v.status) for v in values}
    assert got == {"t": (12, "FOUND"), "t1": (15, "FOUND")}
    assert all(ok for _, _, ok, _ in checks)


def test_tax_table_that_does_not_agree_with_the_face_is_not_used():
    """Negative test: a table with Article 25/29 lines but another total (e.g. a prepaid-tax or tax-expense
    table) gives NOT FOUND, never a figure."""
    lines = [_ln("Utang pajak"), _ln("Pasal 25", 5, 4), _ln("Pasal 21", 3, 2), _ln("Jumlah", 8, 6)]
    values, _, _ = nr.tax_payable(FakeCache({1: lines}), 1, _face(80, 60))
    assert {v.status for v in values} == {"NOT FOUND"} and all(v.value is None for v in values)


def test_prepaid_tax_table_is_skipped():
    """BIPP 2021: Article 25 credits under 'Pajak dibayar di muka' are not payables."""
    lines = [_ln("Pajak dibayar di muka"), _ln("Pasal 25", 50, 40), _ln("Jumlah", 50, 40),
             _ln("Utang pajak"), _ln("Pasal 29", 7, 6), _ln("Pasal 21", 3, 2), _ln("Jumlah", 10, 8)]
    values, _, _ = nr.tax_payable(FakeCache({1: lines}), 1, _face(10, 8))
    assert {v.column: v.value for v in values} == {"t": 7, "t1": 6}


def test_entity_rows_under_an_article_25_heading_are_corporate_tax():
    """SILO 2021: 'Pasal 25' heading with 'Perusahaan' / 'Entitas anak' rows under it."""
    lines = [_ln("Utang pajak"), _ln("Pasal 25"), _ln("Perusahaan", 7, 0), _ln("Entitas anak", 5, 4),
             _ln("Pasal 21"), _ln("Perusahaan", 3, 3), _ln("Jumlah", 15, 7)]
    values, _, _ = nr.tax_payable(FakeCache({1: lines}), 1, _face(15, 7))
    assert {v.column: v.value for v in values} == {"t": 12, "t1": 4}


def test_grand_total_needs_the_tables_to_add_up():
    closed = [([_ln("Pasal 25", 5, 4)], _ln("Jumlah", 5, 4)), ([_ln("Pasal 21", 3, 2)], _ln("Jumlah", 3, 2))]
    assert nr._grand_total(closed, _ln("JUMLAH", 8, 6)) is not None
    assert nr._grand_total(closed, _ln("JUMLAH", 9, 6)) is None
    assert nr._grand_total(closed[:1], _ln("JUMLAH", 5, 4)) is None      # one table is not a grand total


# ----------------------------------------------------------------------------- depreciation wording

def test_depresiasi_is_a_depreciation_title():
    assert nr.ALLOC_TITLE.search("depresiasi dialokasikan sebagai berikut")


def test_investment_property_depreciation_sentence_is_not_ppe_depreciation():
    txt = "Penyusutan properti investasi dibebankan pada beban pokok masing-masing sebesar Rp 1.234.567 dan Rp 1.100.000"
    assert not nr.PPE_DEP_SENTENCE.search(txt)
    ok = "Penyusutan dibebankan pada beban umum dan administrasi masing-masing sebesar Rp 1.234.567 dan Rp 1.100.000"
    assert nr.PPE_DEP_SENTENCE.search(ok)
