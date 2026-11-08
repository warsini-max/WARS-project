"""Synthetic tests for the note readers of xbrl_pipeline (no issuer documents).

Every rule has a negative test: what it must NOT pick (CLAUDE.md rule 7)."""
from wars_scanner import xbrl_pipeline as XP
from wars_scanner import xbrl_reader as X

PAGES = {"bs": [1], "pl": [2]}


def L(*page_texts):
    """page_texts: texts for pages 3, 4, ... (pages 1-2 are the face statements)."""
    return X.pdf_lines(["NERACA", "LABA RUGI", *page_texts])


# ---------------------------------------------------------------- _amounts
def test_amounts_strip_rates_article_lists_and_note_refs():
    assert X._amounts("Final 1% - 68.135 Final 1%") == [0, 68135]
    assert X._amounts("Pasal 21, 22, 23, 26 dan 4(2) 358 265 Article 21, 22, 23, 26 and 4(2)") == [358, 265]
    assert X._amounts("Pasal 25/29 4,052 3,166 Article 25/29") == [4052, 3166]
    assert X._amounts("Utang lain-lain 6,384,025 5,000,000") == [6384025, 5000000]   # comma thousands kept


# ---------------------------------------------------------------- PPE depreciation allocation table
ALLOC = """15. ASET TETAP (lanjutan)
Penyusutan dialokasikan sebagai berikut: Depreciation was allocated as follows:
2022 2021
Beban pokok pendapatan 8,573 8,767 Cost of revenue
Beban penjualan 349 346 Selling expenses
Beban umum dan administrasi 1,398 1,394 General and administrative expenses
Selisih kurs karena penjabaran laporan 571 44 Exchange difference on translation
10,891 10,551"""


def test_allocation_total_takes_out_translation_difference():
    a = XP.allocation_total(L(ALLOC), PAGES, 10_891, 10_551)
    assert (a["t"], a["t1"], a["fx_t"], a["fx_t1"]) == (10_320, 10_507, 571, 44)


def test_allocation_total_with_note_reference_in_label():
    txt = """a. Pembebanan penyusutan adalah sebagai berikut:
2022 2021
Beban pokok penjualan 69.953 70.654 Cost of goods sold
Beban umum dan administrasi
 (Catatan 27) 16.740 47.812 (Note 27)
Total 86.693 118.466 Total"""
    a = XP.allocation_total(L(txt), PAGES, 88_883, 118_466)
    assert (a["t"], a["t1"]) == (86_693, 118_466)


def test_allocation_total_rejects_table_of_other_asset_class():
    # negative: a table that adds up but is far from the XBRL owned movement (e.g. ROU or another class)
    assert XP.allocation_total(L(ALLOC), PAGES, 50_000, 48_000) is None
    rou = ALLOC.replace("Penyusutan dialokasikan", "Penyusutan aset hak guna dialokasikan")
    assert XP.allocation_total(L(rou), PAGES, 10_891, 10_551) is None


def test_allocation_total_needs_lines_that_add_up():
    bad = ALLOC.replace("10,891 10,551", "10,900 10,551")
    assert XP.allocation_total(L(bad), PAGES, 10_891, 10_551) is None


# ---------------------------------------------------------------- non-PPE movement tables
MOVE = """13. TANAMAN PERKEBUNAN
Saldo awal Penambahan Pengurangan Saldo akhir
Harga perolehan
Tanaman menghasilkan 500 20 - 520
Akumulasi penyusutan
Tanaman menghasilkan 100 30 5 125
Jumlah 100 30 5 125
Nilai buku 395"""


def test_movement_charge_total_row_with_balance_check():
    assert XP.movement_charge(L(MOVE), 395, PAGES) == (30.0, 3)


def test_movement_charge_not_anchored_returns_none():
    # negative: the book value printed in the note is not the XBRL carrying amount
    assert XP.movement_charge(L(MOVE), 396, PAGES) is None


def test_movement_charge_unbalanced_total_returns_none():
    bad = MOVE.replace("Jumlah 100 30 5 125", "Jumlah 100 30 5 140")
    assert XP.movement_charge(L(bad), 395, PAGES) is None


TRANSPOSED = """12. Properti Pertambangan 12. Mining Properties
Akuisisi Pengupasan Berproduksi Jumlah/Total
Nilai tercatat Cost
Saldo awal 11.870 24.129 70.884 106.883 Beginning balance
Penambahan - 19.901 - 19.901 Addition
Jumlah 11.870 44.030 70.884 126.784 Total
Akumulasi amortisasi Accumulated amortization
Saldo awal (197) (4.238) (5.418) (9.853) Beginning balance
Amortisasi tahun berjalan (23) (3.395) (1.453) (4.871) Amortization during the year
Jumlah (220) (7.633) (6.871) (14.724) Total
Nilai Tercatat 11.650 36.397 64.013 112.060 Net book value"""


def test_movement_charge_transposed_takes_year_line_not_coincident_total():
    # negative inside: the 'Jumlah' row of the accumulated block also balances by coincidence
    # (220 + 7,633 + 6,871 = 14,724); the charge is the 'for the year' line total, 4,871
    assert XP.movement_charge(L(TRANSPOSED), 112_060, PAGES) == (4871.0, 3)


def test_movement_charge_transposed_needs_balance():
    bad = TRANSPOSED.replace("(4.871) Amortization", "(4.881) Amortization")
    assert XP.movement_charge(L(bad), 112_060, PAGES) is None


# ---------------------------------------------------------------- intangible amortisation line
class _Inst:
    def __init__(self, t, t1):
        self.v = {"t": t, "t1": t1}

    def plain(self, concept, col, kind):
        return self.v[col] if concept == "IntangibleAssetsOtherThanGoodwill" else None


def _xr(t, t1):
    return {"fields": {"t": {}, "t1": {}}, "_inst": _Inst(t, t1)}


def test_amortisation_line_note_number_not_read_as_amount():
    lines = X.pdf_lines(["Aset takberwujud 12 1.500.000 1.300.000", "LABA RUGI",
                         "Beban usaha\nAmortisasi (Catatan 12) 289.412.177 121.821.716 Amortization (Note 12)"])
    a = XP.amortisation_from_notes(_xr(1_500_000, 1_300_000), lines, PAGES)
    assert (a["t"], a["t1"]) == (289_412_177, 121_821_716)


def test_amortisation_line_with_other_note_number_is_not_used():
    # negative: 'Amortisasi (Catatan 14)' belongs to another asset (note 14), not the intangible note 12
    lines = X.pdf_lines(["Aset takberwujud 12 1.500.000 1.300.000", "LABA RUGI",
                         "Amortisasi (Catatan 14) 5.000 4.000 Amortization (Note 14)"])
    assert XP.amortisation_from_notes(_xr(1_500_000, 1_300_000), lines, PAGES) is None


def test_year_line_without_roll_check_is_not_used():
    # negative: a lone 'amortisasi tahun berjalan' line next to the book value, with no beginning/closing rows
    txt = """Properti pertambangan
Amortisasi tahun berjalan 23 3.395 1.453 4.871
Nilai tercatat 112.060"""
    assert XP.movement_charge(L(txt), 112_060, PAGES) is None


def test_allocation_total_takes_out_intangible_amortisation_row():
    # EDGE pattern: 'Beban penyusutan dan amortisasi' table with an intangible amortisation row (wrapped label)
    txt = """Beban penyusutan dan amortisasi dialokasikan sebagai berikut:
2022 2021
Penyusutan aset tetap 58,631 45,391 Depreciation of fixed assets
Amortisasi aset Amortisation of intangible
takberwujud 23 33 assets
Total 58,654 45,424 Total"""
    a = XP.allocation_total(L(txt), PAGES, 56_222, 43_139, 58_631, 45_391)
    assert (a["t"], a["t1"]) == (58_631, 45_391)


def test_allocation_total_keeps_combined_depreciation_and_amortisation_row():
    # negative: a row labelled 'Penyusutan dan amortisasi' is depreciation for this rule and is not taken out
    txt = """Penyusutan dialokasikan sebagai berikut:
2022 2021
Beban pokok penjualan 5,000 4,000
Penyusutan dan amortisasi 1,000 900
Total 6,000 4,900"""
    a = XP.allocation_total(L(txt), PAGES, 6_000, 4_900)
    assert (a["t"], a["t1"]) == (6_000, 4_900)


# ---------------------------------------------------------------- stage 6 finding D: amortisation in a sentence
from wars_scanner import xbrl_pipeline as _XP

_SENT = ("12. ASET TAKBERWUJUD\nPerangkat lunak ... Beban amortisasi untuk tahun yang berakhir pada tanggal\n"
         "31 Desember 2022 dan 2021 masing-masing sebesar Rp101.100.000 dan Rp103.756.250 dibebankan ke beban umum.")


def test_amortisation_read_from_a_sentence_in_the_intangible_note():
    r = _XP.amortisation_from_sentence(["face", _SENT], [176_925_004, 278_025_004], 1)
    assert (r["t"], r["t1"], r["page"]) == (101_100_000, 103_756_250, 2)
    # statements in millions: full-Rupiah amounts in the sentence are converted to the statement unit
    r = _XP.amortisation_from_sentence(["face", _SENT], [177, 278], 1_000_000)
    assert (r["t"], r["t1"]) == (101, 104)


def test_amortisation_sentence_with_unit_word():
    txt = "Aset takberwujud. Beban amortisasi tahun 2022 dan 2021 masing-masing sebesar Rp8.207 juta dan Rp7.529 juta."
    r = _XP.amortisation_from_sentence([txt], [26_542, 25_566], 1_000_000)
    assert (r["t"], r["t1"]) == (8_207, 7_529)


def test_amortisation_sentence_negatives():
    # not intangible amortisation: transaction costs of a loan
    loan = "Aset takberwujud ... Amortisasi biaya transaksi pinjaman sebesar Rp5.000.000 dan Rp4.000.000."
    assert _XP.amortisation_from_sentence([loan], [176_925_004, 278_025_004], 1) is None
    # a page that is not about intangible assets
    assert _XP.amortisation_from_sentence([_SENT.replace("ASET TAKBERWUJUD", "ASET TETAP").replace("Perangkat lunak", "Bangunan")],
                                          [176_925_004, 278_025_004], 1) is None
    # implausible against the carrying amounts (amortisation larger than twice the intangibles)
    assert _XP.amortisation_from_sentence([_SENT], [1_000, 2_000], 1) is None
    # no intangibles on the face: nothing to anchor to
    assert _XP.amortisation_from_sentence([_SENT], [None, None], 1) is None
