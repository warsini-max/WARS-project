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


# XBRL stage 7, finding 1 (TNCA): a bilingual face line interleaves the two languages
_FACE_MIX = ("Aset takberwujud - setelah dikurangi akumulasi amortisasi sebesar Intangible asset - net of "
             "Rp1.193.046.259 pada tahun accumulated amortization of 2022 dan Rp635.142.745 Rp1,193,046,259 in 2022")
_NOTE_OK = ("10. ASET TAKBERWUJUD Amortisasi aset takberwujud dibebankan ke dalam beban umum dan administrasi "
            "masing-masing sebesar Rp557.903.514 dan Rp318.886.840 pada 31 Desember 2022 dan 2021 (Catatan 24).")


def test_amortisation_sentence_skips_face_pages_and_reads_the_note():
    r = _XP.amortisation_from_sentence([_FACE_MIX, _NOTE_OK], [627_045_917, 245_946_522], 1, {1})
    assert (r["t"], r["t1"], r["page"]) == (557_903_514, 318_886_840, 2)


def test_amortisation_sentence_never_reads_a_year_or_accumulated_wording():
    # negative: even off the face, the interleaved wording is refused (year-like figure; 'accumulated' before it)
    assert _XP.amortisation_from_sentence([_FACE_MIX], [627_045_917, 245_946_522], 1) is None
    year = "Aset takberwujud. Amortisasi tahun berjalan sebesar 2022 dan 2021 tidak material."
    assert _XP.amortisation_from_sentence([year], [627_045_917, 245_946_522], 1) is None
    acc = "Aset takberwujud. Akumulasi amortisasi sebesar Rp1.193.046.259 dan Rp635.142.745."
    assert _XP.amortisation_from_sentence([acc], [627_045_917, 245_946_522], 1) is None
    # negative: the face page itself is skipped even when its sentence looks fine
    assert _XP.amortisation_from_sentence([_NOTE_OK], [627_045_917, 245_946_522], 1, {1}) is None
    # positive control: a year written as an amount with a unit word is still an amount (Rp2.022 juta is not a year)
    unit = "Aset takberwujud. Beban amortisasi masing-masing sebesar Rp2.022 juta dan Rp1.500 juta."
    r = _XP.amortisation_from_sentence([unit], [26_542, 25_566], 1_000_000)
    assert (r["t"], r["t1"]) == (2_022, 1_500)


# ---------------------------------------------------------------- XBRL stage 7, finding 2: movement tables
# BIPI shape: the accumulated-amortisation heading is itself the row (begin | charge | deduction | end)
INTANG_ROW = """13. ASET TAKBERWUJUD 13. INTANGIBLE ASSETS
2022
Saldo awal/ Beginning balance Penambahan/ Additon Pengurangan/ Deduction Saldo akhir/ Ending balance
Harga perolehan 94.492.421 - - 94.492.421 Acquisition cost
Akumulasi amortisasi 69.327.065 3.366.190 - 72.693.255 Accumulated amortization
Jumlah tercatat neto 25.165.356 21.799.166 Net carrying amount"""
# SIPD shape: the total row of accumulated amortisation wraps its label over two lines
INTANG_WRAP = """10. ASET TAKBERWUJUD 10. INTANGIBLE ASSETS
2022
Saldo awal/ Saldo akhir/
Beginning Penambahan/ Reklasifikasi/ Ending
balance Addition Reclassification balance
Biaya perolehan Acquisition cost
Merek 23,737 - - 23,737 Brand
Jumlah biaya perolehan 41,604 2,509 - 44,113 Total acquisition cost
Akumulasi amortisasi Accumulated amortisation
Merek (16,089) (1,582) - (17,671) Brand
Perangkat lunak - (638) - (638) Software
Jumlah akumulasi Total accumulated
amortisasi (27,711) (2,220) - (29,931) amortisation
Nilai buku 13,893 14,182 Book value"""


def test_stage7_intangible_movement_row_and_wrapped_total():
    assert XP.movement_charge(L(INTANG_ROW), 21_799_166, PAGES) == (3_366_190.0, 3)
    assert XP.movement_charge(L(INTANG_WRAP), 14_182, PAGES) == (2_220.0, 3)


def test_stage7_intangible_movement_negatives():
    # the row does not roll (begin + charge != end) -> nothing
    assert XP.movement_charge(L(INTANG_ROW.replace("72.693.255", "72.693.355")), 21_799_166, PAGES) is None
    assert XP.movement_charge(L(INTANG_WRAP.replace("(29,931)", "(29,941)")), 14_182, PAGES) is None
    # the carrying amount is not the XBRL one -> nothing
    assert XP.movement_charge(L(INTANG_ROW), 21_799_167, PAGES) is None
    # both years are needed for the intangible reading (one year only -> no guess)
    assert XP.amortisation_from_movement(L(INTANG_ROW), [21_799_166, 25_165_356], PAGES) is None


# FAST shape: years in columns, movements in rows; two notes add up to the XBRL deferred charges
DEFER = ["""11. BIAYA RENOVASI BANGUNAN SEWA DITANGGUHKAN, NETO
31 Desember 2022/ 31 Desember 2021/
Biaya renovasi Renovation cost
Saldo awal 481.295.162 468.858.107 Opening balance
Penambahan tahun berjalan 170.060.316 122.689.377 Current year addition
Pengurangan tahun berjalan (4.745.528) (3.536.632) Current year deduction
646.609.950 588.010.852
Amortisasi tahun berjalan (107.381.342) (106.715.690) Current year amortization
Saldo akhir 539.228.608 481.295.162 Ending balance
Biaya restorasi Restoration cost
Saldo awal 56.449.040 61.481.614 Opening balance
Penambahan tahun berjalan 16.296.295 25.180.040 Current year addition
Pengurangan tahun berjalan (325.404) (193.696) Current year deduction
Amortisasi tahun berjalan (27.063.320) (30.018.918) Current year amortization
Saldo akhir 45.356.611 56.449.040 Ending balance
Total 584.585.219 537.744.202 Total
12. BEBAN DITANGGUHKAN, NETO 12. DEFERRED CHARGES, NET
Initial fee (Catatan 35) Initial fee (Note 35)
Saldo awal 126.934.755 143.933.075 Opening balance
Penambahan tahun berjalan 41.047.274 10.444.653 Current year addition
Pengurangan tahun berjalan (1.424.094) (1.346.265) Current year deduction
Amortisasi tahun berjalan (27.251.821) (26.096.708) Current year amortization
Saldo akhir 139.306.114 126.934.755 Ending balance""",
         """12. BEBAN DITANGGUHKAN, NETO (lanjutan) 12. DEFERRED CHARGES, NET (continued)
Aplikasi KFCKu dan lain-lain KFCKu application and others
Saldo awal 51.110.282 3.576.996 Opening balance
Penambahan tahun berjalan 11.124.225 49.494.830 Current year addition
Amortisasi tahun berjalan (8.780.922) (1.961.544) Current year amortization
Saldo akhir 53.453.585 51.110.282 Ending balance
Total 192.759.699 178.045.037 Total
13. ASET TIDAK LANCAR LAINNYA 13. OTHER NON-CURRENT ASSETS
Uang jaminan 45.046.004 44.486.750 Security deposits
Total 45.046.004 44.486.750 Total"""]
DEFER_PAIR = [584_585_219 + 192_759_699, 537_744_202 + 178_045_037]


def test_stage7_year_column_charge_two_notes_add_up_to_xbrl():
    r = XP.year_column_charge(L(*DEFER), DEFER_PAIR, PAGES)
    assert r[:2] == (107_381_342 + 27_063_320 + 27_251_821 + 8_780_922, 106_715_690 + 30_018_918 + 26_096_708 + 1_961_544)
    assert r[2] == [3, 4]                                  # the note continues on the next page


def test_stage7_year_column_charge_negatives():
    # a run that does not roll -> that table is out -> the XBRL pair cannot be made -> nothing
    bad = [DEFER[0].replace("539.228.608 481.295.162", "539.228.618 481.295.162"), DEFER[1]]
    assert XP.year_column_charge(L(*bad), DEFER_PAIR, PAGES) is None
    # the tables do not add up to the XBRL pair -> nothing
    assert XP.year_column_charge(L(*DEFER), [DEFER_PAIR[0] + 1_000, DEFER_PAIR[1]], PAGES) is None
    # a single table (one year missing from XBRL) -> nothing
    assert XP.year_column_charge(L(*DEFER), [DEFER_PAIR[0], None], PAGES) is None
    # accumulated amortisation is a balance, never the charge: a table whose only 'amortisation' row is the
    # accumulated balance gives no charge
    acc = """14. BIAYA DITANGGUHKAN
Saldo awal 100 90 Opening balance
Akumulasi amortisasi (10) (5) Accumulated amortization
Saldo akhir 90 85 Ending balance
Total 90 85 Total"""
    assert XP.year_column_charge(L(acc), [90, 85], PAGES) is None
    # two different combinations reach the XBRL pair -> ambiguous -> nothing
    dup = DEFER[1].replace("13. ASET TIDAK LANCAR LAINNYA", "14. BEBAN DITANGGUHKAN LAIN\nSaldo awal 10 10 Opening\n"
                           "Amortisasi tahun berjalan (1) (1) Amortization\nSaldo akhir 9 9 Ending\nTotal 9 9 Total\n"
                           "15. BEBAN DITANGGUHKAN LAIN\nSaldo awal 10 10 Opening\n"
                           "Amortisasi tahun berjalan (1) (1) Amortization\nSaldo akhir 9 9 Ending\nTotal 9 9 Total\n"
                           "13. ASET TIDAK LANCAR LAINNYA")
    assert XP.year_column_charge(L(DEFER[0], dup), [DEFER_PAIR[0] + 9, DEFER_PAIR[1] + 9], PAGES) is None


# regression on the development files (10 Nov): two wrong lines that the strict intangible reading must refuse
INTANG_CLASS_COLS = """11. ASET TAK BERWUJUD
Assets with indefinite useful life Total
Tahun yang berakhir pada tanggal 31 Desember 2022/
Nilai Tercatat/Carrying Amount
Saldo Awal/Beginning Balance 2.664.767 1.411.540 4.076.307
Penambahan/Additions - - -
Saldo Akhir/Ending Balance 2.664.767 1.411.540 4.076.307
Akumulasi Amortisasi/Rugi Penurunan Nilai/
Accumulated Amortization/Impairment Loss
Saldo Awal/Beginning Balance 1.798.714 551.833 2.350.547
Penambahan/Additions 133.238 - 133.238
Pengurangan/Deductions - - -
Saldo Akhir/Ending Balance 1.931.952 551.833 2.483.785
Nilai Tercatat Neto/Net Carrying Amount 732.815 859.707 1.592.522"""
INTANG_NO_TOTAL = """12. ASET TAKBERWUJUD
01/01/2022 Penambahan/Additions Acquisition of a subsidiary 31/12/2022
Akumulasi amortisasi Accumulated amortisation
3G upfront fee (1,216,849) - - (1,216,849) 3G upfront fee
Merk (164,310) - (3,274) (167,584) Brand
Komisi penjualan* (16,850) (19,174) - (36,024) Sales commission*
(1,938,455) (19,174) (7,567) (1,965,196)
Nilai buku bersih 5,712,558 5,988,468 Net book value"""
INTANG_FIRST_YEAR = """8. ASET TAKBERWUJUD
1 Jan 2021 Penambahan Pengurangan Reklasifikasi 31 Des 2021
Akumulasi Amortisasi
Sub Jumlah - 408.728.362 - - 408.728.362
Nilai Buku - 3.694.266.049"""


def test_regression_strict_intangible_reading_refuses_wrong_lines():
    # class columns (indefinite-life column + total) are not movement columns: 551.833 is not a charge
    assert XP.movement_charge(L(INTANG_CLASS_COLS), 1_592_522, PAGES, True) is None
    # no labelled total row: the category rows are not added up ('3G' in a label is not an amount)
    assert XP.movement_charge(L(INTANG_NO_TOTAL), 5_988_468, PAGES, True) is None
    # the whole accumulated balance in the first year (asset first recognised) is not the year's charge
    assert XP.movement_charge(L(INTANG_FIRST_YEAR), 3_694_266_049, PAGES, True) is None
    # positive controls: the shapes that are read stay read in strict mode
    assert XP.movement_charge(L(INTANG_ROW), 21_799_166, PAGES, True) == (3_366_190.0, 3)
    assert XP.movement_charge(L(INTANG_WRAP), 14_182, PAGES, True) == (2_220.0, 3)


# ---------------------------------------------------------------- XBRL stage 8, mining long-term costs (ITMG shape)
STRIP = """12. DEFERRED STRIPPING COSTS
 31 Desember/December 2025
 Saldo awal/ Saldo akhir/
 Opening Penambahan/ Pengurangan/ Ending
balance Additions Disposals balance

 Harga perolehan 881,340 155,507 - 1,036,847 Acquisition cost
 Accumulated
 Akumulasi amortisasi (704,894) (41,788) - (746,682) amortisation

 Nilai buku bersih 176,446 290,165 Net book value"""
EXPLO = """13. DEFERRED EXPLORATION AND DEVELOPMENT
 Saldo awal/ reklasifikasi/ financial Saldo akhir/
 Opening Penambahan/ Pengurangan/ Transfer/ statements Ending
Nilai perolehan Acquisition cost
 eksplorasi 1,100 611 - - - 1,711 exploration
 berproduksi 350,138 36,334 - 25,231 (928) 410,775 production
 403,091 40,731 (347) - (2,034) 441,441

Akumulasi Accumulated
 amortisasi amortisation

 Tambang yang Mines in
 berproduksi 233,425 8,540 - - (56) 241,909 production

 233,425 8,540 - - (56) 241,909
Nilai buku bersih 169,666 199,532 Net book value"""


def test_stage8_mining_cost_tables_strict():
    assert XP.movement_charge(L(STRIP), 290_165, PAGES, True) == (41_788.0, 3)
    assert XP.movement_charge(L(EXPLO), 199_532, PAGES, True) == (8_540.0, 3)


def test_stage8_mining_cost_tables_negatives():
    # an unlabelled last row that is not the sum of the labelled rows above it is no total
    bad = EXPLO.replace(" 233,425 8,540 - - (56) 241,909\nNilai", " 233,425 8,540 - - (56) 241,909\n 1 1 - - - 2\nNilai")
    assert XP.movement_charge(L(bad), 199_532, PAGES, True) is None
    # the accumulated row does not roll -> nothing
    assert XP.movement_charge(L(STRIP.replace("(746,682)", "(746,692)")), 290_165, PAGES, True) is None
