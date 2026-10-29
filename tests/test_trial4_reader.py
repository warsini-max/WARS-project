"""Reader rules added after the Trial 4 blind run (development, 29 Oct 2026). Rule 7: every matching rule has a
negative test (what it must NOT match). Synthetic lines only; the shapes are taken from LMSH, MARI (file holding the
ABBA report), FLMC, TOBA, CASH, PUDP and TAMA 2021 (non-case issuers)."""
import re

from wars_scanner import notes_reader as nr
from wars_scanner import pdf_reader as pr
from wars_scanner.notes_reader import PageCache
from wars_scanner.pdf_reader import Line, Word


def _ln(label, t=None, t1=None, page=1, full_label=None, figs=()):
    """A line whose words are the label words followed by the printed figures `figs` (strings)."""
    words = [Word(x, 0, 1, 0) for x in label.split()] + [Word(f, 0, 1, 0) for f in figs]
    ln = Line(page, 0.0, words)
    ln.label, ln.full_label = label, full_label if full_label is not None else label
    ln.amounts = {k: v for k, v in (("t", t), ("t1", t1)) if v is not None}
    ln.n_cols = 2
    return ln


def _hdr():
    ln = _ln("2021 2020")
    ln.is_header = True
    return ln


class FakeCache(PageCache):
    def __init__(self, pages, n=None, text=None):
        n = n or max(pages)
        self.fmt, self.fiscal_year, self.notes_start = "dot", 2021, 1
        self._lines = {p: pages.get(p, []) for p in range(1, n + 1)}
        self.text = [(text or {}).get(p) or "\n".join(ln.text for ln in self._lines[p]) for p in range(1, n + 1)]

    def lines(self, p):
        return self._lines.get(p, [])


# ----------------------------------------------------------------------------- locating the statements

def test_notes_header_on_the_year_line_and_footer_without_yang():
    """LMSH 2021: 'Catatan 2021 2020'; ABBA 2021: 'Catatan 31 Desember 2021 ...' and '... merupakan bagian tidak
    terpisahkan dari Laporan Keuangan'."""
    assert pr.NOTES_COLUMN.search("ASET\nCatatan 2021 2020\nKas")
    assert pr.NOTES_COLUMN.search("Ekshibit A/1\r\nCatatan 31 Desember 2021 31 Desember 2020*")
    assert pr.INTEGRAL_FOOTER.search("yang merupakan bagian tidak terpisahkan dari Laporan Keuangan")
    assert pr.INTEGRAL_FOOTER.search("Catatan terlampir merupakan bagian yang tidak terpisahkan dari laporan keuangan.")


def test_a_note_mentioned_in_a_sentence_is_not_the_notes_column():
    assert not pr.NOTES_COLUMN.search("lihat catatan 2021 atas laporan keuangan")
    assert not pr.NOTES_COLUMN.search("Penjelasan lebih lanjut diungkapkan dalam Catatan 10 dan 11.")
    assert not pr.INTEGRAL_FOOTER.search("Ikhtisar data keuangan penting")


# ----------------------------------------------------------------------------- labels on the face

def test_revenue_and_cost_labels_of_a_hotel_company():
    """PUDP 2021: 'Penjualan dan Pendapatan'; 'Beban Pokok Penjualan dan / Beban Langsung'."""
    rev, cogs = re.compile(pr.FACE_RULES[0][2]), re.compile(pr.FACE_RULES[1][2])
    assert rev.search(pr._norm("Penjualan dan Pendapatan"))
    assert cogs.search(pr._norm("Beban Pokok Penjualan dan Beban Langsung"))
    assert not rev.search(pr._norm("Penjualan dan pendapatan lain-lain"))
    assert not cogs.search(pr._norm("Beban pokok penjualan dan beban usaha"))


def test_fixed_assets_label_with_bracketed_net_of_wording():
    assert pr.PPE_WRAPPED.search(pr._norm("Aset Tetap (Setelah dikurangi akumulasi penyusutan pada tahun 2021"))
    assert not pr.PPE_WRAPPED.search(pr._norm("Uang muka pembelian aset tetap"))


# ----------------------------------------------------------------------------- debt on the face

def test_bare_bank_and_lease_lines_under_long_term_headings():
    """TAMA 2021: 'Utang jangka panjang yang jatuh / tempo dalam 1 (satu) tahun' then 'Bank' and 'Liabilitas sewa';
    TOBA 2021: 'Sewa' under the current-maturities heading."""
    lines = [_ln("Liabilitas Jangka Pendek"), _ln("Utang bank jangka pendek", 60658, 64114),
             _ln("Utang jangka panjang yang jatuh"), _ln("tempo dalam 1 (satu) tahun"),
             _ln("Bank", 8060, 4138), _ln("Sewa", 917, 640),
             _ln("Jumlah Liabilitas Jangka Pendek", 73186, 69689), _ln("Liabilitas Jangka Panjang"),
             _ln("Liabilitas jangka panjang - setelah"), _ln("dikurangi bagian yang jatuh tempo"),
             _ln("Bank", 50932, 48644), _ln("Liabilitas sewa", 8, 69),
             _ln("Jumlah Liabilitas", 124381, 118785)]
    lt, cm, excluded, _ = pr._debt(lines)
    assert [x.amounts["t"] for x in cm] == [8060, 917]
    assert [x.amounts["t"] for x in lt] == [50932, 8]
    assert [x.amounts["t"] for x in excluded] == [60658]


def test_bank_line_in_current_liabilities_without_the_sub_heading_stays_out():
    lines = [_ln("LIABILITAS JANGKA PENDEK"), _ln("Bank", 500, 400), _ln("Utang usaha", 70, 60),
             _ln("Jumlah liabilitas jangka pendek", 570, 460)]
    lt, cm, excluded, _ = pr._debt(lines)
    assert cm == [] and [x.amounts["t"] for x in excluded] == [500]


# ----------------------------------------------------------------------------- taxes payable

def _tax_cache():
    """LMSH 2021: the payable table (Articles 21/23) agrees with the face; the reconciliation on the next page has an
    'Pasal 25 - -' line and a different total."""
    p1 = [_ln("14. PERPAJAKAN"), _ln("b. Utang pajak terdiri dari:"), _hdr(), _ln("Pajak Penghasilan"),
          _ln("Pasal 21", 30442, 47292), _ln("Pasal 23", 2367, 2087), _ln("Total", 32809, 49379)]
    p2 = [_ln("14. PERPAJAKAN (lanjutan)"), _ln("Dikurang uang muka pajak"), _hdr(),
          _ln("Pasal 25", 0, 0), _ln("Taksiran tagihan pajak", 0, 0), _ln("Total", -557, 574)]
    return FakeCache({1: p1, 2: p2}, text={1: "utang pajak pasal 21 pasal 23", 2: "pasal 25 utang pajak"})


def test_payable_table_without_articles_25_29_that_agrees_with_the_face_gives_nil():
    face = _ln("Utang pajak", 32809, 49379)
    values, checks, issues = nr.tax_payable(_tax_cache(), 1, face)
    assert [(v.value, v.status) for v in values] == [(0, "REVIEW"), (0, "REVIEW")]


def test_without_a_face_line_the_old_rule_is_unchanged():
    """No face line to agree with: the Article 25/29 table is used as before (REVIEW), not the evidence-of-nil rule."""
    values, _, _ = nr.tax_payable(_tax_cache(), 1, None)
    assert all(v.status == "REVIEW" and v.note is not None and getattr(v.note, "key", "") == "note.tax" for v in values)


def test_rows_by_fiscal_year_under_article_29():
    """FLMC 2021: 'Pasal 29' / 'Tahun 2020 1.738.336.620 1.744.179.631' / 'Tahun 2016 678.451.108 -'."""
    p1 = [_ln("14. PERPAJAKAN"), _ln("a. Utang Pajak"), _hdr(), _ln("Pajak Pertambahan Nilai", 538, 920),
          _ln("Pajak Penghasilan:"), _ln("Pasal 21", 70, 37), _ln("Pasal 25", 0, 60), _ln("Pasal 29"),
          _ln("Tahun 2020", 1738, 1744), _ln("Tahun 2016", 678, 0), _ln("Jumlah", 3024, 2761)]
    cache = FakeCache({1: p1}, text={1: "utang pajak pasal 29"})
    values, _, _ = nr.tax_payable(cache, 1, _ln("Utang pajak", 3024, 2761))
    assert {v.column: v.value for v in values} == {"t": 2416, "t1": 1804}


def test_year_rows_under_article_21_are_not_corporate_tax():
    ln = _ln("Tahun 2020", 10, 20)
    ln.tax_head = "pasal 21"
    assert not nr._corporate(ln)
    ln.tax_head = "pasal 29"
    assert nr._corporate(ln)


def test_corporate_income_tax_printed_as_pasal_penghasilan_badan():
    """TOBA 2021: 'Pasal penghasilan badan 5.578.502 609.843'."""
    assert nr.CORPORATE.search(pr._norm("Pasal penghasilan badan"))
    assert not nr.CORPORATE.search(pr._norm("Pasal 23"))


# ----------------------------------------------------------------------------- fixed assets in the note

def test_wrapped_carrying_amount_label_confirms_the_face_figure():
    """FLMC 2021: 'Nilai Buku' / 'Bersih 85.135.723.754 173.819.310.108'."""
    page = [_ln("10. ASET TETAP (lanjutan)"), _ln("Nilai Buku"), _ln("Bersih", figs=("85.135.723.754", "173.819.310.108"))]
    cache = FakeCache({1: page}, text={1: "aset tetap nilai buku bersih"})
    out = nr.ppe_note_carrying(cache, 1, {"t": 173819310108, "t1": 85135723754})
    assert out["t"][0] == "ok" and out["t1"][0] == "ok"


def test_net_line_under_another_heading_is_not_a_carrying_amount():
    page = [_ln("10. ASET TETAP (lanjutan)"), _ln("Laba penjualan aset tetap"),
            _ln("Bersih", figs=("85.135.723.754", "173.819.310.108"))]
    cache = FakeCache({1: page}, text={1: "aset tetap laba penjualan bersih"})
    out = nr.ppe_note_carrying(cache, 1, {"t": 173819310108, "t1": 85135723754})
    assert out["t"][0] == "none"


def test_rou_class_heading_with_rows_inside_the_fixed_asset_note():
    """CASH 2021: 'Aset hak guna' heads its rows ('Tanah', 'Bangunan') in the fixed-asset table."""
    page = [_ln("14. ASET TETAP"), _ln("Aset hak guna"),
            _ln("Tanah", figs=("-", "565.701.640", "-", "169.710.492", "735.412.132")),
            _ln("Bangunan", figs=("-", "219.259.259", "465.914.785", "1.212.313.107", "1.897.457.581"))]
    cache = FakeCache({1: page})
    assert nr.rou_within_ppe(cache, {"page": 1}) is not None


def test_rou_class_heading_in_the_lease_note_is_not_inside_fixed_assets():
    page = [_ln("16. SEWA"), _ln("Aset hak guna"),
            _ln("Tanah", figs=("-", "565.701.640", "-", "169.710.492", "735.412.132"))]
    cache = FakeCache({1: page})
    assert nr.rou_within_ppe(cache, {"page": 1}) is None


def test_heading_with_the_english_part_on_the_same_line():
    """TAMA 2021: '10 . ASET TETAP - Lanjutan 10. PROPERTY, PLANT AND EQUIPMEMNT -'."""
    cache = FakeCache({1: [_ln("10 . ASET TETAP - Lanjutan 10. PROPERTY, PLANT AND EQUIPMEMNT -"), _ln("Beban")]})
    assert cache.heading_before(1, 1) == "ASET TETAP - LANJUTAN"


# ----------------------------------------------------------------------------- depreciation

def test_allocation_titles_that_start_otherwise():
    """TOBA 2021: 'Pengalokasian beban penyusutan adalah sebagai / berikut:'; CASH 2021: 'Untuk periode yang berakhir
    ..., penyajian beban penyusutan / pada laporan laba rugi sebagai berikut:'."""
    assert nr.ALLOC_TITLE.search(pr._norm("Pengalokasian beban penyusutan adalah sebagai berikut:"))
    assert nr.ALLOC_TITLE.search(pr._norm("Untuk periode yang berakhir 31 Desember 2021 dan 2020, penyajian beban penyusutan"))
    assert not nr.ALLOC_TITLE.search(pr._norm("Akumulasi penyusutan"))
    assert not nr.ALLOC_TITLE.search(pr._norm("Laba penjualan aset tetap adalah sebagai berikut:"))


def test_wrapped_allocation_title_is_found():
    page = [_ln("15. ASET TETAP"), _ln("Pengalokasian beban penyusutan adalah sebagai"), _ln("berikut:"), _hdr(),
            _ln("Beban pokok pendapatan", 5037, 5853), _ln("Beban umum dan administrasi", 831, 922),
            _ln("Total", 5868, 6775)]
    tables = nr.allocation_tables(FakeCache({1: page}), 1)
    assert len(tables) == 1 and tables[0]["kind"] == "PPE" and tables[0]["total"].amounts["t"] == 5868


def test_depreciation_sentence_naming_both_years():
    """PUDP 2021: 'Beban penyusutan tahun 2021 dan 2020 masing-masing sebesar Rp 8.028.275.933 dan Rp 8.565.013.429'."""
    assert nr.PPE_DEP_SENTENCE_C.search("Beban penyusutan tahun 2021 dan 2020 masing-masing sebesar Rp 8.028.275.933")
    assert not nr.PPE_DEP_SENTENCE_C.search("Beban penyusutan masing-masing sebesar Rp 8.028.275.933")


def test_depreciation_sentence_with_dialokasi():
    """TAMA 2021: '... masing-masing sebesar Rp2.004.813.428 dan Rp2.322.102.199 yang dialokasi pada beban pokok'."""
    txt = ("Beban Penyusutan untuk tahun yang berakhir pada tanggal 31 Desember 2021 dan 2020 adalah masing-masing "
           "sebesar Rp2.004.813.428 dan Rp2.322.102.199 yang dialokasi pada beban pokok pendapatan")
    assert nr.PPE_DEP_SENTENCE_B.search(txt)


# ----------------------------------------------------------------------------- investment property

def test_standards_list_is_not_a_fair_value_policy():
    """TOBA 2021: 'PSAK No. 13, "Properti Investasi", tentang pengungkapan penerapan model nilai wajar telah dihapus'."""
    face = _ln("Properti investasi, neto", 7996675, 8470924)
    face.full_label = face.label
    cache = FakeCache({1: [_ln("2. KEBIJAKAN AKUNTANSI")]},
                      text={1: 'PSAK No. 13, "Properti Investasi", tentang pengungkapan penerapan model nilai wajar telah dihapus.'})
    got, _ = nr.invprop_depreciation(cache, 1, face)
    assert got == {}


def test_fair_value_policy_still_gives_nil():
    face = _ln("Properti investasi", 7996675, 8470924)
    cache = FakeCache({1: [_ln("2. KEBIJAKAN AKUNTANSI")]},
                      text={1: "Properti investasi diukur dengan model nilai wajar setelah pengakuan awal."})
    got, _ = nr.invprop_depreciation(cache, 1, face)
    assert got == {"t": 0, "t1": 0}


def _toba_ip(close_2021="7.996.675"):
    p = [_ln("14. PROPERTI INVESTASI"),
         _ln("Akumulasi Depresiasi"), _ln("Bangunan", figs=("(1.014.057)", "(474.249)", "-", "-", "(1.488.306)")),
         _ln("", figs=("8.470.924", "(474.249)", "-", "-", close_2021)),
         _ln("Akumulasi Depresiasi"), _ln("Bangunan", figs=("(539.808)", "(474.249)", "-", "-", "(1.014.057)")),
         _ln("", figs=("8.945.173", "(474.249)", "-", "-", "8.470.924"))]
    return FakeCache({1: p}, text={1: "properti investasi"})


def test_investment_property_depreciation_from_a_self_checking_schedule():
    face = _ln("Properti investasi, neto", 7996675, 8470924)
    got, _ = nr.invprop_movement(_toba_ip(), 1, face)
    assert got == {"t": 474249, "t1": 474249}


def test_schedule_that_does_not_close_at_the_face_figure_is_not_used():
    face = _ln("Properti investasi, neto", 7996675, 8470924)
    got, _ = nr.invprop_movement(_toba_ip(close_2021="7.996.000"), 1, face)
    assert got == {}


def test_schedule_with_a_carrying_amount_row():
    """TAMA 2021: 'Jumlah 237.685.168 624.009.905 - - 861.695.073' and 'Nilai Tercatat 147.402.151.680
    155.404.947.377'."""
    p = [_ln("9. PROPERTI INVESTASI"), _ln("Akumulasi"), _ln("Penyusutan"),
         _ln("Bangunan", figs=("237.685.168", "624.009.905", "-", "-", "861.695.073")),
         _ln("Jumlah", figs=("237.685.168", "624.009.905", "-", "-", "861.695.073")),
         _ln("Nilai Tercatat", figs=("147.402.151.680", "155.404.947.377")),
         _ln("9. PROPERTI INVESTASI - Lanjutan"), _ln("Akumulasi penyusutan"),
         _ln("Bangunan", figs=("-", "237.685.168", "-", "237.685.168")),
         _ln("Jumlah", figs=("-", "237.685.168", "-", "237.685.168")),
         _ln("Nilai Tercatat", figs=("-", "147.402.151.680"))]
    face = _ln("Properti investasi", 155404947377, 147402151680)
    got, _ = nr.invprop_movement(FakeCache({1: p}, text={1: "properti investasi"}), 1, face)
    assert got == {"t": 624009905, "t1": 237685168}


def test_balance_row_of_a_rou_movement_table_is_not_an_allocation_total():
    """KOIN 2021: 'Beban amortisasi selama tahun / berjalan' sits in a ROU movement table; the next 'Posisi per 1
    Januari 2020' row (its date read as a figure) must not become the ROU depreciation."""
    page = [_ln("10. ASET HAK GUNA DAN LIABILITAS SEWA 10. RIGHT-OF-USE ASSETS AND LEASE"),
            _ln("Beban amortisasi selama tahun"), _ln("berjalan"), _hdr(), _ln("Aset hak-guna"),
            _ln("Posisi per", None, 1)]
    page[-1].n_cols = 1
    assert nr.allocation_tables(FakeCache({1: page}), 1) == []


def test_lease_liability_lines_are_not_an_allocation_table():
    """KOIN 2021: under 'Beban amortisasi selama tahun' the lease liabilities 'Jangka pendek' / 'Jangka panjang' and
    their unlabelled total were taken as the ROU depreciation."""
    page = [_ln("10. ASET HAK GUNA DAN LIABILITAS SEWA"), _ln("Beban amortisasi selama tahun"), _ln("berjalan"), _hdr(),
            _ln("Liabilitas sewa"), _ln("Jangka pendek", 4055, 3393), _ln("Jangka panjang", 5303, 9265), _ln("", 9358, 12658)]
    assert nr.allocation_tables(FakeCache({1: page}), 1) == []


def test_unnamed_depreciation_sentence_under_the_investment_property_heading():
    """ERAA 2021: '12. INVESTASI PROPERTI - NETO' / 'Beban penyusutan ... masing-masing sebesar Rp362.727 dan
    Rp2.899.460 ...'. The same sentence under the fixed-asset heading is not investment property."""
    sentence = ("Beban penyusutan untuk tahun yang berakhir pada tanggal-tanggal 31 Desember 2021 dan 2020 yang dibebankan "
                "pada operasi masing-masing sebesar Rp362.727 dan Rp2.899.460, dan dicatat sebagai beban umum.")
    face = _ln("Properti investasi", 14479323, 15166829)
    ip = FakeCache({1: [_ln("12. INVESTASI PROPERTI - NETO"), _ln("Beban penyusutan untuk tahun yang berakhir pada")]},
                   text={1: "investasi properti " + sentence})
    got, _ = nr.invprop_depreciation(ip, 1, face)
    assert got == {"t": 362727, "t1": 2899460}
    ppe = FakeCache({1: [_ln("13. ASET TETAP - NETO"), _ln("Beban penyusutan untuk tahun yang berakhir pada")]},
                    text={1: "properti investasi " + sentence})
    got, _ = nr.invprop_depreciation(ppe, 1, face)
    assert got == {}


def test_rou_depreciation_from_the_lines_under_its_heading():
    """PYFA 2021: 'Beban penyusutan aset hak-guna' / 'Beban pokok penjualan (Catatan 25) - 221.553.614' / 'Beban penjualan
    dan pemasaran ...' / 'Beban umum dan administrasi ...' / then a short-term lease line and a total that includes it."""
    page = [_ln("13. ASET HAK-GUNA DAN LIABILITAS SEWA (Lanjutan)"), _ln("Bunga atas liabilitas sewa", 743, 164),
            _ln("Beban penyusutan aset hak-guna"), _ln("Beban pokok penjualan (Catatan 25)", 0, 221),
            _ln("Beban penjualan dan pemasaran (Catatan 26)", 942, 636), _ln("Beban umum dan administrasi (Catatan 27)", 5461, 341),
            _ln("Beban terkait liabilitas sewa bernilai rendah", 1783, 2956), _ln("Jumlah", 8930, 4320)]
    got = nr.rou_depreciation_lines(FakeCache({1: page}, text={1: "aset hak-guna"}), 1)
    assert got is not None and got[0] == {"t": 6403, "t1": 1198}


def test_lease_liability_movement_is_not_rou_depreciation():
    """PYFA 2021: 'Saldo awal / Penambahan tahun berjalan / Arus kas / Jumlah' is the lease-liability movement."""
    page = [_ln("13. ASET HAK-GUNA DAN LIABILITAS SEWA (Lanjutan)"), _ln("Beban penyusutan aset hak-guna"),
            _ln("Saldo awal", 8935, 2694), _ln("Penambahan tahun berjalan", 10886, 0), _ln("Jumlah", 13945, 8935)]
    assert nr.rou_depreciation_lines(FakeCache({1: page}, text={1: "aset hak-guna"}), 1) is None
