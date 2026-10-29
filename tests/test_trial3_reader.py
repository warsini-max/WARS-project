"""Reader rules added after Trial 3 wave A (development, 29 Oct 2026). Rule 7: every matching rule has a
negative test (what it must NOT match). Synthetic lines only; the shapes are taken from ERAA, SOSS, TALF, TEBE
and SAME 2021 (non-case issuers)."""
from wars_scanner import notes_reader as nr
from wars_scanner import pdf_reader as pr
from wars_scanner.notes_reader import PageCache
from wars_scanner.pdf_reader import Line, Word


def _ln(label, t=None, t1=None, page=1, full_label=None):
    ln = Line(page, 0.0, [Word(x, 0, 1, 0) for x in label.split()])
    ln.label, ln.full_label = label, full_label if full_label is not None else label
    ln.amounts = {k: v for k, v in (("t", t), ("t1", t1)) if v is not None}
    ln.n_cols = 2
    return ln


class FakeCache(PageCache):
    def __init__(self, pages, n=None, text=None):
        n = n or max(pages)
        self.fmt, self.fiscal_year, self.notes_start = "dot", 2021, 1
        self._lines = {p: pages.get(p, []) for p in range(1, n + 1)}
        self.text = [(text or {}).get(p) or "\n".join(ln.text for ln in self._lines[p]) for p in range(1, n + 1)]

    def lines(self, p):
        return self._lines.get(p, [])


def _hdr():
    ln = _ln("2021 2020")
    ln.is_header = True
    return ln


def _line_words(*texts):
    x, words = 10.0, []
    for t in texts:
        words.append(Word(t, x, x + 5, 100.0))
        x += 8
    return Line(1, 100.0, words)


# ----------------------------------------------------------------------------- labels: glued and split words

def test_glued_label_words_are_split():
    """ERAA 2021: 'LABATAHUN BERJALAN'."""
    assert pr._norm("LABATAHUN BERJALAN") == "laba tahun berjalan"
    assert pr._norm("Utangpembiayaan konsumen") == "utang pembiayaan konsumen"


def test_real_words_are_not_split():
    for label in ("PENDAPATAN", "Penghasilan", "Kasbon", "labaentitas", "Persediaan"):
        assert pr._norm(label) == label.lower()


def test_words_split_inside_are_joined():
    """TEBE 2021: 'P ajak', 'Jum lah', 'P ertam bahan N ilai - B ersih'."""
    assert pr._norm("Jum lah") == "jumlah"
    assert pr._norm("P ajak P ertam bahan N ilai - B ersih") == "pajak pertambahan nilai - bersih"
    assert pr._norm("E ntitas Anak") == "entitas anak"


def test_separate_real_words_are_not_joined():
    assert pr._norm("Utang pajak") == "utang pajak"
    assert pr._norm("A Bank") == "a bank"
    assert pr._norm("Obligasi Seri A dan B") == "obligasi seri a dan b"


# ----------------------------------------------------------------------------- revenue label

def test_service_revenue_net_is_revenue():
    rx = __import__("re").compile(pr.FACE_RULES[0][2])
    assert rx.search(pr._norm("PENDAPATAN JASA - NETO"))
    assert rx.search(pr._norm("Penjualan neto"))


def test_interest_on_current_accounts_is_not_revenue():
    rx = __import__("re").compile(pr.FACE_RULES[0][2])
    assert not rx.search(pr._norm("Pendapatan jasa giro"))
    assert not rx.search(pr._norm("Pendapatan lain-lain"))


# ----------------------------------------------------------------------------- figures in a sentence

def test_clause_comma_after_the_second_figure():
    """ERAA 2021: 'sebesar Rp126.917.735 dan Rp132.757.304, dan dicatat sebagai ...'."""
    got = nr.sentence_pair(" Rp126.917.735 dan Rp132.757.304, dan dicatat sebagai bagian", "2021 dan 2020")
    assert got == {"t": 126917735, "t1": 132757304}


def test_decimal_part_is_not_cut_off():
    assert nr.MONEY_TOKEN.findall("Rp1.234.567,50 dan") == []
    assert nr.MONEY_TOKEN.findall("1,234,567.50") == []


# ----------------------------------------------------------------------------- debt on the face

def test_current_maturities_sub_heading_takes_the_bank_loan_and_financing_lines():
    """ERAA 2021: under 'Utang jangka panjang yang akan jatuh tempo dalam waktu satu tahun:' the lines have no
    'current portion' wording of their own."""
    lines = [_ln("LIABILITAS JANGKA PENDEK"), _ln("Utang bank jangka pendek", 1287, 1878),
             _ln("Utang jangka panjang yang"), _ln("akan jatuh tempo dalam"), _ln("waktu satu tahun:"),
             _ln("Liabilitas sewa", 298, 227), _ln("Utang bank jangka panjang", 143, 0),
             _ln("Utang pembiayaan konsumen", 175, 98),
             _ln("TOTAL LIABILITAS JANGKA PENDEK", 4279, 5142)]
    lt, cm, excluded, _ = pr._debt(lines)
    assert [x.label for x in cm] == ["Liabilitas sewa", "Utang bank jangka panjang", "Utang pembiayaan konsumen"]
    assert [x.label for x in excluded] == ["Utang bank jangka pendek"]


def test_short_term_financing_without_the_sub_heading_stays_out():
    """SOSS 2021: 'Utang pembiayaan jangka pendek' is a short-term facility (D-02), the current portion of the
    long-term financing is in."""
    lines = [_ln("LIABILITAS JANGKA PENDEK"), _ln("Utang pembiayaan jangka pendek", 60000, 60000),
             _ln("Utang pembiayaan jangka panjang yang jatuh tempo dalam satu tahun", 174, 100),
             _ln("Jumlah liabilitas jangka pendek", 131533, 138966), _ln("LIABILITAS JANGKA PANJANG"),
             _ln("Utang pembiayaan jangka panjang setelah dikurangi bagian yang jatuh tempo dalam satu tahun", 116, 72),
             _ln("Liabilitas diestimasi atas imbalan kerja karyawan", 3980, 5860),
             _ln("JUMLAH LIABILITAS", 135630, 144899)]
    lt, cm, excluded, _ = pr._debt(lines)
    assert [x.amounts["t"] for x in cm] == [174]
    assert [x.amounts["t"] for x in lt] == [116]
    assert [x.amounts["t"] for x in excluded] == [60000]


def test_net_of_current_maturities_heading_in_current_section_does_not_open_current_maturities():
    lines = [_ln("LIABILITAS JANGKA PENDEK"), _ln("Utang jangka panjang setelah dikurangi"),
             _ln("bagian yang jatuh tempo dalam satu tahun"), _ln("Utang bank", 50, 40),
             _ln("Jumlah liabilitas jangka pendek", 500, 400)]
    lt, cm, excluded, _ = pr._debt(lines)
    assert cm == [] and [x.amounts["t"] for x in excluded] == [50]


# ----------------------------------------------------------------------------- receivables

def test_allowance_amount_wrapped_inside_the_receivable_label():
    """TEBE 2021: 'Piutang usaha - setelah dikurangi / cadangan ... / Rp 957.438 dan Rp 1.315.561 pada /
    tanggal ...' then 'Pihak berelasi' and 'Pihak ketiga'."""
    lines = [_ln("Kas dan setara kas", 251, 45), _ln("Piutang usaha - setelah dikurangi"),
             _ln("cadangan kerugian penurunan"), _ln("nilai masing-masing sebesar"),
             _ln("Rp 957.438 dan Rp 1.315.561 pada"), _ln("tanggal 31 Desember 2021 dan 2020"),
             _ln("Pihak berelasi", 19533, 17192), _ln("Pihak ketiga", 6193, 15457),
             _ln("Piutang lain-lain - setelah dikurangi"), _ln("Pihak berelasi", 105, 8)]
    block, _ = pr._receivables(lines)
    assert [x.amounts["t"] for x in block] == [19533, 6193]


def test_next_item_after_a_receivable_heading_without_items_is_not_taken():
    lines = [_ln("Piutang usaha - setelah dikurangi"), _ln("Rp 957.438 pada 2021"),
             _ln("Persediaan", 4962, 3593)]
    block, _ = pr._receivables(lines)
    assert block == []


# ----------------------------------------------------------------------------- selling and G&A under a heading

def test_items_under_operating_expenses_heading():
    """TEBE 2021: 'BEBAN USAHA' / 'Umum dan administrasi (32.772.589)'."""
    lines = [_ln("LABA KOTOR", 241123, 37512), _ln("BEBAN USAHA"), _ln("Umum dan administrasi", -32772, -26851),
             _ln("LABA USAHA", 208350, 10661)]
    assert [x.amounts["t"] for x in pr._sga_parts(lines)] == [-32772]


def test_other_lines_under_operating_expenses_heading_are_not_selling_or_ga():
    lines = [_ln("BEBAN USAHA"), _ln("Penyusutan", -500, -400), _ln("Umum dan administrasi", -32772, -26851)]
    assert pr._sga_parts(lines) == []


# ----------------------------------------------------------------------------- Notes column

def test_note_named_in_a_column_header_is_not_the_notes_column():
    """SAME 2021: 'Disajikan kembali - Catatan 4/' above the 2020 column; the real 'Catatan/' is further left."""
    head = Line(1, 10.0, [Word("Disajikan", 321, 350, 10), Word("kembali", 354, 380, 10), Word("-", 382, 384, 10),
                          Word("Catatan", 386, 410, 10), Word("4/", 414, 420, 10)])
    notes = Line(1, 20.0, [Word("Catatan/", 180, 205, 20)])
    assert abs(pr._notes_column_x([head, notes]) - 192.5) < 0.01
    assert pr._notes_column_x([head]) is None


# ----------------------------------------------------------------------------- note headings and tables

def test_numbered_heading_without_a_space():
    cache = FakeCache({1: [_ln("11.ASET TETAP (lanjutan)"), _ln("Penyusutan untuk tahun")]})
    assert cache.heading_before(1, 1) == "ASET TETAP (LANJUTAN)"


def test_list_item_without_a_space_is_not_a_heading():
    cache = FakeCache({1: [_ln("1.Penjualan bersih kepada pihak berelasi"), _ln("Penyusutan untuk tahun")]})
    assert cache.heading_before(1, 1) == ""


def _soss_rou_page():
    """SOSS 2021: a sentence in the ROU note (no table), then note 13 starts with the prepaid-tax table."""
    return [_ln("12.ASET HAK GUNA (lanjutan)"), _ln("Pada tanggal 31 Desember 2021 dan 2020, beban"),
            _ln("penyusutan yang dibebankan pada beban umum dan"), _ln("administrasi masing-masing"),
            _ln("13.PERPAJAKAN"), _ln("a.Pajak Dibayar di Muka"), _ln("Akun ini terdiri dari:"),
            _hdr(),
            _ln("Pajak Pertambahan Nilai", 1297, 355), _ln("Pasal 21", 73, 0), _ln("Jumlah", 1370, 355)]


def test_tax_table_after_a_new_note_is_not_a_depreciation_allocation():
    page = _soss_rou_page()
    cache = FakeCache({1: page})
    assert nr.allocation_tables(cache, 1) == []


def test_tax_lines_are_never_an_allocation_even_without_a_note_break():
    page = [_ln("16. ASET HAK GUNA"), _ln("Penyusutan dibebankan sebagai berikut:"),
            _hdr(),
            _ln("Pajak Pertambahan Nilai", 1297, 355), _ln("Pasal 21", 73, 0), _ln("Jumlah", 1370, 355)]
    cache = FakeCache({1: page})
    assert nr.allocation_tables(cache, 1) == []


def test_allocation_table_still_found():
    page = [_ln("11. ASET TETAP"), _ln("Penyusutan dibebankan sebagai berikut:"),
            _hdr(),
            _ln("Beban pokok pendapatan", 1722, 2026), _ln("Beban umum dan administrasi", 2184, 2390),
            _ln("Jumlah", 3906, 4416)]
    cache = FakeCache({1: page})
    tables = nr.allocation_tables(cache, 1)
    assert len(tables) == 1 and tables[0]["kind"] == "PPE" and tables[0]["total"].amounts["t"] == 3906


# ----------------------------------------------------------------------------- ROU depreciation

def _rollforward(close_t=815734, open_t=655964, dep=(-328038, -268759)):
    return [_ln("15. ASET HAK-GUNA DAN LIABILITAS SEWA"), _ln("Saldo Awal", open_t, 737193),
            _ln("Penambahan", 535906, 187646), _ln("Pengurangan", -45835, -2467),
            _ln("Beban penyusutan", dep[0], dep[1]), _ln("Efek translasi", -2263, 2351),
            _ln("Total", close_t, 655964)]


def test_rou_depreciation_from_a_movement_schedule_that_proves_itself():
    """ERAA 2021 (scaled): opening + movements = closing for both years, opening(t) = closing(t-1), closing = ROU
    assets; the same pair printed again in the lease P&L table (page 2)."""
    page2 = [_ln("15. ASET HAK-GUNA DAN LIABILITAS SEWA (lanjutan)"),
             _ln("Beban penjualan dan distribusi 328.038 268.759")]
    cache = FakeCache({1: _rollforward(), 2: page2},
                      text={1: "hak-guna", 2: "aset hak-guna\nBeban penjualan dan distribusi 328.038 268.759"})
    got = nr.rou_depreciation_rollforward(cache, 1, {"t": 815734, "t1": 655964})
    assert got is not None
    assert got[0] == {"t": 328038, "t1": 268759} and got[3] == 2


def test_rou_movement_schedule_that_does_not_add_up_is_not_used():
    cache = FakeCache({1: _rollforward(close_t=815000)}, text={1: "hak-guna"})
    assert nr.rou_depreciation_rollforward(cache, 1, {"t": 815000, "t1": 655964}) is None


def test_rou_movement_schedule_not_equal_to_the_rou_assets_is_not_used():
    cache = FakeCache({1: _rollforward()}, text={1: "hak-guna"})
    assert nr.rou_depreciation_rollforward(cache, 1, {"t": 999999, "t1": 655964}) is None


def test_movement_schedule_outside_a_rou_note_is_not_used():
    lines = _rollforward()
    lines[0] = _ln("11. ASET TETAP")
    cache = FakeCache({1: lines}, text={1: "hak-guna"})
    assert nr.rou_depreciation_rollforward(cache, 1, {"t": 815734, "t1": 655964}) is None


def test_rou_depreciation_sentence_only_inside_the_rou_note():
    sentence = ("Pada tanggal 31 Desember 2021 dan 2020, beban penyusutan yang dibebankan pada beban umum dan "
                "administrasi masing-masing sebesar Rp5.628.680.799 dan Rp5.422.812.656 (lihat Catatan 24).")
    rou = [_ln("12.ASET HAK GUNA (lanjutan)"), _ln("Pada tanggal 31 Desember 2021 dan 2020, beban")]
    cache = FakeCache({1: rou}, text={1: "aset hak guna " + sentence})
    got = nr.rou_depreciation_sentence(cache, 1)
    assert got is not None and got[0] == {"t": 5628680799, "t1": 5422812656} and got[3] is False
    ppe = [_ln("11.ASET TETAP (lanjutan)"), _ln("Pada tanggal 31 Desember 2021 dan 2020, beban")]
    cache = FakeCache({1: ppe}, text={1: "aset hak guna " + sentence})
    assert nr.rou_depreciation_sentence(cache, 1) is None


# ----------------------------------------------------------------------------- investment property depreciation

def _talf(expense_t=216309544, note_text="masing-masing adalah sebesar Rp 216.309.544 (Catatan 27)."):
    note = [_ln("11. PROPERTI INVESTASI (lanjutan)"), _ln("Penyusutan properti investasi dibebankan pada")]
    expense = [_ln("27. BEBAN UMUM DAN ADMINISTRASI"), _ln("Penyusutan properti investasi"),
               _ln("(Catatan 11)", expense_t, expense_t)]
    text = {1: "properti investasi\nPenyusutan properti investasi dibebankan pada " + note_text,
            2: "Penyusutan properti investasi\n(Catatan 11) 216.309.544 216.309.544"}
    return FakeCache({1: note, 2: expense}, text=text)


def test_investment_property_depreciation_from_the_expense_note_with_a_cross_check():
    """TALF 2021: one figure in the note sentence, both years in the expense note."""
    face = _ln("Properti investasi - neto", 144206362, 360515906)
    got, src = nr.invprop_depreciation(_talf(), 1, face)
    assert got == {"t": 216309544, "t1": 216309544}


def test_investment_property_expense_line_without_the_cross_check_is_not_used():
    face = _ln("Properti investasi - neto", 144206362, 360515906)
    got, _ = nr.invprop_depreciation(_talf(note_text="dicatat sebagai beban umum."), 1, face)
    assert got == {}


def test_investment_property_expense_line_larger_than_the_carrying_amount_is_not_used():
    """A figure in another unit (full Rupiah against statements in thousands) fails."""
    face = _ln("Properti investasi - neto", 144206, 360515)
    got, _ = nr.invprop_depreciation(_talf(), 1, face)
    assert got == {}


def test_sentence_in_a_combined_fixed_asset_and_rou_note_is_not_rou_depreciation():
    """LINK 2021: '8. ASET TETAP DAN ASET HAK GUNA (lanjutan)': the sentence there is the fixed-asset depreciation;
    taking it again as ROU depreciation would count it twice."""
    sentence = ("Beban penyusutan yang dibebankan pada laporan laba rugi dan penghasilan komprehensif lain konsolidasian "
                "masing-masing sebesar Rp991.859 dan Rp849.439 untuk tahun yang berakhir pada tanggal 31 Desember 2021.")
    lines = [_ln("8. ASET TETAP DAN ASET HAK GUNA (lanjutan)"), _ln("Beban penyusutan yang dibebankan pada")]
    cache = FakeCache({1: lines}, text={1: "aset hak guna " + sentence})
    assert nr.rou_depreciation_sentence(cache, 1) is None


def test_cash_generated_from_operations_is_not_net_operating_cash_flow():
    """ERAA 2021: 'Kas yang dihasilkan dari / aktivitasoperasi 1.135.679.864' (before interest and tax) comes before
    'Kas Neto yang Diperoleh dari / Aktivitas Operasi 21.739.143'. Splitting the glued word must not make the first
    one the operating cash flow."""
    gen = _ln("aktivitasoperasi", 1135679864, 3323271467, full_label="Kas yang dihasilkan dari aktivitasoperasi")
    net = _ln("Aktivitas Operasi", 21739143, 2852705359, full_label="Kas Neto yang Diperoleh dari Aktivitas Operasi")
    lines = [_ln("Kas yang dihasilkan dari"), gen, _ln("Pajak penghasilan", -942, -292),
             _ln("Kas Neto yang Diperoleh dari"), net]
    assert pr._cfo_line(lines) is net
