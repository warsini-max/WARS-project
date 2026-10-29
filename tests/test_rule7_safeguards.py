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


# ----------------------------------------------------------------------------- Trial 2 (blind, 28 Oct 2026): APII, TFAS

from wars_scanner import pdf_reader as pr                         # noqa: E402


def test_trade_receivables_item_with_a_wrapped_label_is_read():
    """APII 2021: 'Pihak ketiga - setelah / dikurangi cadangan / ... / (2020 : Rp2.995.582.842) 52.638...' was missed."""
    lines = [_ln("Piutang usaha"), _ln("Pihak berelasi", 2115, 1126), _ln("Pihak ketiga - setelah"),
             _ln("dikurangi cadangan"), _ln("sebesar Rp1.829.642.116"), _ln("31 Desember 2021"),
             _ln("(2020 : Rp2.995.582.842)", 52638, 62823), _ln("Piutang lain-lain"), _ln("Pihak berelasi", 5739, 3202)]
    got, _ = pr._receivables(lines)
    assert [x.amounts["t"] for x in got] == [2115, 52638]


def test_other_receivables_are_not_trade_receivables():
    lines = [_ln("Piutang usaha"), _ln("Pihak ketiga", 100, 90), _ln("Piutang lain-lain"), _ln("Pihak ketiga", 7, 6)]
    assert [x.amounts["t"] for x in pr._receivables(lines)[0]] == [100]


def test_receivables_on_two_own_lines():
    lines = [_ln("Piutang usaha - pihak ketiga", 100, 90), _ln("Piutang usaha - pihak berelasi", 5, 4),
             _ln("Persediaan", 50, 40)]
    assert [x.amounts["t"] for x in pr._receivables(lines)[0]] == [100, 5]


def test_wrapped_label_head_and_tail_match_together():
    """TFAS 2021: 'Beban umum dan' / 'administrasi 30.403.766.317' is general and administrative expenses."""
    lines = [_ln("Beban umum dan"), _ln("administrasi", 30403, 26649), _ln("Beban penjualan", 2800, 3310)]
    assert pr._first(lines, r"^beban (umum dan administrasi|administrasi dan umum)$") is lines[1]
    # negative: the tail alone, or under another head, is not matched
    other = [_ln("Uang muka pembelian"), _ln("aset tetap", 58997, 95906, full_label="Uang muka pembelian aset tetap")]
    assert pr._first(other, r"^aset tetap$") is None


def _st(kind, lines):
    return pr.Statement(kind, [1], lines)


def test_sga_parts_against_total_operating_expenses():
    gp = _ln("LABA KOTOR", 900, 800)
    sell, ga = _ln("Beban penjualan", 28, 33), _ln("Beban umum dan administrasi", 304, 266)
    ok = _st("profit_loss", [gp, ga, sell, _ln("Total Beban Usaha", 332, 299)])
    assert pr._sga_total(ok, [ga, sell])[0] == {"t": "ok", "t1": "ok"}
    # the TFAS failure: G&A missed (tail of a wrapped label), only selling expenses read
    tail = _ln("administrasi", 304, 266)
    bad = _st("profit_loss", [gp, _ln("Beban umum dan"), tail, sell, _ln("Total Beban Usaha", 332, 299)])
    assert pr._sga_total(bad, [sell])[0] == {"t": "mismatch", "t1": "mismatch"}
    # another item printed on its own line inside the total is not a misread
    imp = _ln("Beban penyisihan penurunan nilai", 10, 0)
    other = _st("profit_loss", [gp, ga, sell, imp, _ln("Total Beban Usaha", 342, 299)])
    st, others = pr._sga_total(other, [ga, sell])
    assert st == {"t": "other", "t1": "ok"} and others == [imp]


def test_net_income_check():
    pbt, tax, ni = _ln("LABA SEBELUM PAJAK", 2822, 984), _ln("BEBAN PAJAK PENGHASILAN", 158, 338), _ln("LABA TAHUN BERJALAN", 2664, 646)
    pl = _st("profit_loss", [pbt, tax, ni])
    assert pr._net_income_check(pl, {"t": 2664, "t1": 646}) == {"t": True, "t1": True}   # tax printed without brackets
    assert pr._net_income_check(pl, {"t": 2665, "t1": 646}) == {}                          # no line with these figures
    pl2 = _st("profit_loss", [pbt, _ln("Beban pajak", -158, -338), _ln("Laba tahun berjalan", 2664, 600)])
    assert pr._net_income_check(pl2, {"t": 2664, "t1": 600}) == {"t": True, "t1": False}


def test_operating_cash_flow_check():
    cf = _st("cash_flow", [_ln("Kas neto diperoleh dari aktivitas operasi", 643, 486),
                           _ln("Kas neto digunakan untuk aktivitas investasi", -161, -439),
                           _ln("Kas neto digunakan untuk aktivitas pendanaan", -733, -209),
                           _ln("Pengaruh perubahan kurs", -1, 0),
                           _ln("Penurunan neto kas dan setara kas", -252, -162)])
    assert pr._cfo_check(cf, {"t": 643, "t1": 486}) == {"t": True, "t1": True}
    assert pr._cfo_check(cf, {"t": 600, "t1": 486}) == {"t": False, "t1": True}


def test_figures_found_again_in_the_notes():
    text = ["", "Kas 21.566.665.738 13.361.199.112 Cash", "Jumlah 54,753,896,950 63,949,833,306 Total"]
    assert pr.pair_in_text(text, 2, 21566665738, 13361199112) == 2
    assert pr.pair_in_text(text, 2, 54753896950, 63949833306) == 3          # English thousands style
    assert pr.pair_in_text(text, 2, 1566665738, 13361199112) is None        # part of a longer figure is no match
    assert pr.pair_in_text(text, 3, 21566665738, 13361199112) is None       # only from the first note page on
    assert pr.pair_in_text(text, 2, 107, 31) is None                        # small figures are not distinctive


def test_found_figure_without_any_cross_check_becomes_review():
    from wars_scanner.pdf_reader import Value
    values = [Value("cash_flow_from_operations", c, v, "FOUND") for c, v in (("t", 5), ("t1", 4))]
    out = pr._rule7(values, [], {}, [""], None, {}, [])
    assert {v.status for v in out} == {"REVIEW"}


def test_right_of_use_words_any_mention_keeps_the_review():
    """Gail 28 Oct 2026: right of use assets are taken as nil only when the report never mentions them."""
    for txt in ("Aset hak-guna", "aset hak guna - neto", "Right-of-use assets", "right of use", "Hak untuk menggunakan aset"):
        assert nr.ROU_WORDS.search(txt), txt
    for txt in ("Hak atas tanah", "Aset tetap", "Utang usaha"):
        assert not nr.ROU_WORDS.search(txt), txt


# ----------------------------------------------------------------------------- Trial 2 follow-up fixes (29 Oct 2026)

def _w(text, x0, top=100.0):
    return {"text": text, "x0": x0, "x1": x0 + 6 * len(text), "top": top}


def test_opening_bracket_printed_apart_is_joined_to_its_figure():
    """PYFA 2021: '( 385.949.260.966)'."""
    out = pr._open_brackets([_w("(", 200), dict(_w("385.949.260.966)", 213))])
    assert [w["text"] for w in out] == ["(385.949.260.966)"]
    far = pr._open_brackets([_w("(", 200), _w("385.949)", 240)])          # too far apart: left alone
    assert [w["text"] for w in far] == ["(", "385.949)"]
    word = pr._open_brackets([_w("(", 200), _w("Catatan", 207)])           # a bracket before text: left alone
    assert [w["text"] for w in word] == ["(", "Catatan"]


def test_glued_and_letter_spaced_text_layers_are_detected():
    glued = [_w(t, i * 50) for i, t in enumerate(["LAPORANPOSISIKEUANGAN", "STATEMENTOFFINANCIALPOSITION",
                                                  "Tanggal31Desember2021", "(DisajikandalamRupiah,", "Kas", "dan", "bank",
                                                  "Bebanpenyusutanasettetapyangdialokasikanpada", "kecualidinyatakanlain)",
                                                  "unlessotherwisestated)"])]
    assert pr._glued(glued)
    normal = [_w(t, i * 50) for i, t in enumerate(["Laporan", "posisi", "keuangan", "Kas", "dan", "setara", "kas",
                                                   "pertanggungjawabannya", "Pihak", "ketiga"])]
    assert not pr._glued(normal)
    spaced = [_w(c, i * 7) for i, c in enumerate("Beban Pokok".replace(" ", ""))]
    assert pr._spaced_lines(spaced) == {100}
    assert pr._spaced_lines(normal) == set()


def test_note_references_with_letters_and_dots():
    for ref in ("3m.", "3l.", "3b.3f.4", "2u,28,33&34"):
        assert pr.NOTE_REF.match(ref), ref
    for amount in ("1.234", "54.902.595.928"):
        assert not pr.NOTE_REF.match(amount), amount


def test_selling_general_and_administrative_on_one_wrapped_line():
    """ABMM 2021: 'Beban penjualan, umum dan' / 'administrasi (60.085.720)'."""
    lines = [_ln("Beban penjualan, umum dan"), _ln("administrasi", -60085720, -54081458)]
    assert any(pr._first(lines, pat) is lines[1] for pat in pr.SGA_PARTS)


def test_upper_case_wrapped_revenue_label():
    """ABMM 2021: 'PENDAPATAN DARI KONTRAK' / 'DENGAN PELANGGAN 1.021.865.474'."""
    lines = [_ln("PENDAPATAN DARI KONTRAK"), _ln("DENGAN PELANGGAN", 1021865474, 606407376, full_label="2021 PENDAPATAN DARI KONTRAK DENGAN PELANGGAN")]
    assert pr._first(lines, pr.FACE_RULES[0][2]) is lines[1]
    other = [_ln("BEBAN POKOK"), _ln("DENGAN PELANGGAN", 5, 4, full_label="x")]      # another head: no match
    assert pr._first(other, pr.FACE_RULES[0][2]) is None


def test_operating_cash_flow_label_printed_around_the_figures():
    """MTPS 2021: 'Jumlah Kas Bersih yang Diperoleh dari' / '(246.072.015.025) 89.153.940.475' / '(Digunakan untuk) Aktivitas Operasi'."""
    lines = [_ln("Jumlah Kas Bersih yang Diperoleh dari"), _ln("", -246072015025, 89153940475),
             _ln("(Digunakan untuk) Aktivitas Operasi"), _ln("Arus Kas dari Aktivitas Investasi")]
    assert pr._cfo_line(lines) is lines[1]
    sub = [_ln("Kas yang diperoleh dari"), _ln("", -240803307012, 89694261636), _ln("(digunakan untuk) operasi")]
    assert pr._cfo_line(sub) is None                       # cash generated from operations is not the total


def test_hyphen_ending_a_wrapped_english_label_is_not_nil():
    """TFAS 2021: 'bagian yang jatuh tempo 2,19b, Lease liabilities -'."""
    ln = _assign_amounts(_line_words("bagian", "yang", "jatuh", "tempo", "2,19b,", "Lease", "liabilities", "-"))
    assert ln.amounts == {}
    nil = _assign_amounts(_line_words("Uang", "muka", "pelanggan", "-", "2", "3.700.000", "Advances"))
    assert nil.amounts == {"t": 0, "t1": 3700000}


def test_split_first_letter_is_joined_in_labels():
    assert pr._norm("N ilai tercatat neto") == "nilai tercatat neto"
    assert pr._norm("U tang Pajak") == "utang pajak"
    assert pr._norm("A Bank") == "a bank"


def test_depreciation_sentence_with_amounts_before_the_verb():
    ok = ("Beban penyusutan untuk tahun-tahun yang berakhir pada tanggal 31 Desember 2021 dan 2020 masing-masing "
          "sebesar Rp 717.040.615 dan Rp 486.918.049 dialokasikan ke beban umum dan administrasi")
    assert nr.PPE_DEP_SENTENCE_B.search(ok)
    rou = ok.replace("Beban penyusutan", "Beban penyusutan aset hak guna")
    assert not nr.PPE_DEP_SENTENCE_B.search(rou)
