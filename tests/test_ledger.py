"""P0-2 evidence ledger and shadow mode (Gail 13 Nov 2026 16.46: K1 = B, K2 = B, K5 = A, K6). Each corroboration test
has positive and negative cases (CLAUDE.md rule 7); the ledger must never change the result it describes (K6)."""
import copy
from types import SimpleNamespace as NS

from wars_scanner import ledger
from wars_scanner.pdf_reader import Extraction, Value

L = ledger.raw_lines


def _pages(*texts):
    return list(texts)


PL = """LAPORAN LABA RUGI
PENDAPATAN 24 1.780.476 2.020.780 REVENUES
BEBAN POKOK PENDAPATAN 25 (840.233) (1.078.759) COST OF REVENUES
LABA BRUTO 940.243 942.021 GROSS PROFIT
Beban pemasaran 26 (106.100) (102.565) Marketing expenses
Beban administrasi 27 (283.317) (264.972) Administrative expenses
Beban keuangan 28 (5.965) (6.055) Finance cost
Beban pajak final 29 (72.137) (77.547) Final tax expense
LABA SEBELUM PAJAK 502.621 535.424 PROFIT BEFORE TAX"""


# ------------------------------------------------------------------ C-LAB

def test_c_lab_identity_on_the_right_statement():
    lines = L(_pages(PL))
    assert ledger.c_lab(lines, {1}, "revenue", 1_780_476, 2_020_780)[0]
    assert ledger.c_lab(lines, {1}, "cost_of_goods_sold", 840_233, 1_078_759)[0]


def test_c_lab_negatives():
    apex = "LABA RUGI\nBEBAN LANGSUNG 24 (59.818.429) (66.016.956) DIRECT COST\nLABA BRUTO 24.420.758 18.565.480 GROSS PROFIT"
    lines = L(_pages(apex))
    # must NOT: a selling-expense pair printed on the direct-cost line (APEX 2025)
    assert not ledger.c_lab(lines, {1}, "sga_selling", 59_818_429, 66_016_956)[0]
    # must NOT: the pair printed only on a page that is not the primary statement (notes)
    lines2 = L(_pages("LABA RUGI", "26. BEBAN PEMASARAN\nJumlah 106.100 102.565"))
    assert not ledger.c_lab(lines2, {1}, "sga_selling", 106_100, 102_565)[0]
    # must NOT: the tail of a wrapped label ('Uang muka pembelian / aset tetap', BIRD 2021, FISH 2025)
    fish = "Uang muka pembelian\n   aset tetap 7.308.965 9 9.748.469 fixed assets"
    assert not ledger.c_lab(L(_pages(fish)), {1}, "ppe", 7_308_965, 9_748_469)[0]
    # must NOT: 'Aset hak guna' in the deferred tax table (MTLA 2025)
    dtx = "Liabilitas pajak tangguhan\nAset hak guna (598) - Right of use asset deferred tax"
    assert not ledger.c_lab(L(_pages(dtx)), {1}, "rou", 598, 0)[0]


def test_c_lab_wrapped_and_indented_labels():
    cl = "Jumlah liabilitas\njangka pendek 6,485,612 5,755,158 liabilities"
    assert ledger.c_lab(L(_pages(cl)), {1}, "current_liabilities", 6_485_612, 5_755_158)[0]


# ------------------------------------------------------------------ C-REC (selling + G&A)

def test_sga_block_complete_when_every_line_is_classified():
    lines = L(_pages(PL))
    assert ledger.sga_complete(lines, {1}, {"t": 389_417, "t1": 367_537})[0]


def test_sga_block_rejects_a_partial_value():
    # must NOT: marketing alone, although the same pair is printed again in its note (MTLA 2025, PDF path)
    lines = L(_pages(PL, "26. BEBAN PEMASARAN\nJumlah 106.100 102.565"))
    assert not ledger.sga_complete(lines, {1}, {"t": 106_100, "t1": 102_565})[0]


def test_sga_block_negatives():
    # must NOT: no operating profit / profit before tax line (completeness cannot be shown)
    no_end = PL.split("\nLABA SEBELUM")[0]
    assert not ledger.sga_complete(L(_pages(no_end)), {1}, {"t": 389_417, "t1": 367_537})[0]
    # must NOT: an unclassified line in the block
    odd = PL.replace("Beban keuangan 28 (5.965) (6.055) Finance cost", "Beban penelitian 28 (5.965) (6.055) Research")
    ok, why = ledger.sga_complete(L(_pages(odd)), {1}, {"t": 389_417, "t1": 367_537})
    assert not ok and "unclassified" in why


def test_sga_block_unlabelled_subtotal():
    pl = """LABA BRUTO 940.243 942.021 GROSS PROFIT
Beban usaha
Penjualan (106.100) (102.565) Selling
Umum dan administrasi (283.317) (264.972) General and administrative
(389.417) (367.537)
LABA USAHA 550.826 574.484 OPERATING PROFIT"""
    assert ledger.sga_complete(L(_pages(pl)), {1}, {"t": 389_417, "t1": 367_537})[0]


# ------------------------------------------------------------------ C-REC (families)

AR = """Piutang usaha - setelah dikurangi cadangan kerugian 5 Trade receivables - net
penurunan nilai sebesar Rp 2.429.785.811 dan for impairment of Rp 2,429,785,811 and
Pihak berelasi 4.193.320.763 7.312.673.435 Related parties
Pihak ketiga 6.398.965.494 6.979.937.104 Third parties
Piutang lain-lain 1.119.723.829 6 470.194.306 Other receivables"""


def test_family_receivables_under_a_wrapped_heading_with_quoted_amounts():
    ok, why, n = ledger.family_sum(L(_pages(AR)), {1}, ["accounts_receivable"],
                                   {"t": 10_592_286_257, "t1": 14_292_610_539})
    assert ok and n == 2, why


def test_family_receivables_negatives():
    # must NOT: the third-party line alone (related parties missing)
    assert not ledger.family_sum(L(_pages(AR)), {1}, ["accounts_receivable"],
                                 {"t": 6_398_965_494, "t1": 6_979_937_104})[0]
    # must NOT: other receivables counted
    assert not ledger.family_sum(L(_pages(AR)), {1}, ["accounts_receivable"],
                                 {"t": 11_712_010_086, "t1": 14_762_804_845})[0]


def test_family_ppe_excludes_loans_and_advances():
    bs = """Aset tetap - neto 99.142.946 9 103.085.969 Fixed assets - net
Aset hak-guna - neto 7.007.939 12 7.335.209 Right-of-use assets - net
Uang muka pembelian
   aset tetap 7.308.965 9 9.748.469 fixed assets
Pinjaman pembelian aset tetap 31.663.000 20.000.000 PPE purchase loans"""
    ok, why, n = ledger.family_sum(L(_pages(bs)), {1}, ["ppe", "rou", "bearer"], {"t": 106_150_885, "t1": 110_421_178})
    assert ok and n == 2, why


# ------------------------------------------------------------------ the ledger and shadow mode

def _result(values, statements=None, xbrl=None, checks=None):
    ex = Extraction("t.pdf", 3, [], 2025, "Full", "Consolidated", statements or {}, values, [], checks=checks or [])
    r = NS(extraction=ex, inputs={f"{v.field}_{v.column}": v.value for v in values if v.value is not None},
           calc={"m_score_B": -2.0}, review=[], missing=[], unreadable="", flags=[])
    if xbrl is not None:
        r.xbrl = xbrl
    return r


def _st(kind, pages):
    return NS(kind=kind, pages=pages, lines=[])


def test_ledger_rows_and_derivations():
    vals = [Value("selling_general_administrative_expenses", c, v, "FOUND", [1], ["Beban usaha 72.391.110"])
            for c, v in (("t", 72_391_110), ("t1", 79_683_181))]
    vals += [Value("long_term_debt", c, 0, "FOUND") for c in ("t", "t1")]
    vals += [Value("amortization_intangibles", c, 0, "ASSUMED") for c in ("t", "t1")]
    vals += [Value("revenue", c, 5, "USER CONFIRMED") for c in ("t", "t1")]
    items = [NS(field="selling_general_administrative_expenses", column=c, value=v, status="FOUND",
                source="XBRL SellingExpenses+GeneralAndAdministrativeExpenses", note="")
             for c, v in (("t", 72_391_110), ("t1", 79_683_181))]
    items += [NS(field="long_term_debt", column=c, value=0, status="FOUND", source="XBRL ",
                 note="not tagged; subtotals add up and no such line on the PDF face (rule 3)") for c in ("t", "t1")]
    apex = "LABA RUGI\nPENDAPATAN 84.239.187 84.582.436 REVENUE\nBEBAN LANGSUNG (59.818.429) (66.016.956) DIRECT\n" \
           "LABA BRUTO 24.420.758 18.565.480 GROSS\nBeban usaha (12.572.681) (13.666.225) Operating expenses\n" \
           "LABA SEBELUM PAJAK 4.428.797 827.789 PROFIT BEFORE TAX"
    notes = "Catatan\n15. LIABILITAS SEWA\nLiabilitas sewa 12.757.236"
    r = _result(vals, {"profit_loss": _st("profit_loss", [1]), "position": _st("position", [1])}, {"items": items})
    before = copy.deepcopy([(v.field, v.column, v.value, v.status) for v in r.extraction.values])
    rows = ledger.attach(r, [apex, notes], "X")
    by = {(x["field"], x["column"]): x for x in rows}
    sga = by[("selling_general_administrative_expenses", "t")]
    assert sga["derivation"] == "A-AGG" and sga["xbrl_concepts"] == ["SellingExpenses", "GeneralAndAdministrativeExpenses"]
    assert sga["status_old"] == "FOUND" and sga["status_proposed"] == "REVIEW" and sga["reason"].startswith("K5-A")
    ltd = by[("long_term_debt", "t")]
    assert ltd["derivation"] == "A-INF" and ltd["status_proposed"] == "REVIEW" and ltd["reason"].startswith("K2-B")
    assert by[("amortization_intangibles", "t")]["derivation"] == "A-INF"
    assert by[("revenue", "t")]["derivation"] == "A-USR" and by[("revenue", "t")]["status_proposed"] == "USER CONFIRMED"
    for x in rows:                                   # every row carries the fields the ledger must record
        for k in ("field", "year", "value", "derivation", "source_doc", "pages", "label", "xbrl_concepts", "components",
                  "corroboration", "error_kinds_tested", "status_old", "status_proposed", "reason"):
            assert k in x
    # K6: shadow only - nothing on the result changes except r.ledger
    assert [(v.field, v.column, v.value, v.status) for v in r.extraction.values] == before
    assert r.calc == {"m_score_B": -2.0}
    cmp = ledger.compare(rows)
    assert cmp["by_reason"]["K5-A"] == 2 and cmp["by_reason"]["K2-B"] == 2


def test_absence_zero_kept_when_the_report_is_readable_and_silent():
    vals = [Value("long_term_debt", c, 0, "FOUND") for c in ("t", "t1")]
    items = [NS(field="long_term_debt", column=c, value=0, status="FOUND", source="XBRL ",
                note="not tagged; subtotals add up and no such line on the PDF face (rule 3)") for c in ("t", "t1")]
    r = _result(vals, {"position": _st("position", [1])}, {"items": items})
    rows = ledger.build(r, ["NERACA\nJUMLAH LIABILITAS 100 90", "Catatan\nUtang usaha 50 40"], "X")
    assert all(x["status_proposed"] == "FOUND" for x in rows)


# ------------------------------------------------------------------ P0-3 / P0-4 acceptance sets (Test Plan r0 §3)

def test_pos_x2_sub_line_under_its_heading():
    ar = "Piutang usaha 5 Trade receivables\nPihak ketiga 6.398.965.494 6.979.937.104 Third parties"
    assert ledger.c_lab(L(_pages(ar)), {1}, "accounts_receivable", 6_398_965_494, 6_979_937_104)[0]


def test_neg_x3_pair_on_another_statement():
    # must NOT: a balance-sheet item corroborated by the same pair on the cash flow statement page
    pages = _pages("LAPORAN POSISI KEUANGAN\nJumlah aset 9.000.000 8.000.000 Total assets",
                   "LAPORAN ARUS KAS\nKas dan setara kas akhir tahun 120.000 110.000 Cash at end of year")
    assert not ledger.c_lab(L(pages), {1}, "cash_and_cash_equivalents", 120_000, 110_000)[0]


def test_neg_x4_one_year_component_on_another_label():
    # must NOT: a one-year value whose amount is printed on a line with another label
    lines = L(_pages("Beban lain-lain 1.780.476 - Other expenses\nPENDAPATAN 24 2.000.001 2.020.780 REVENUES"))
    assert not ledger.c_lab(lines, {1}, "revenue", 1_780_476, None)[0]


def test_neg_x7_quoted_amount_is_not_a_line_amount():
    # must NOT: the amount quoted inside a label ('... sebesar Rp 2.429.785.811 ...') read as the line's figure
    lines = L(_pages(AR))
    assert not ledger.family_sum(lines, {1}, ["accounts_receivable"], {"t": 2_429_785_811, "t1": 2_429_785_811})[0]
    q = "Jumlah aset termasuk penyisihan sebesar Rp 5.000.000 dan Rp 4.000.000 Total assets"
    assert not ledger.c_lab(L(_pages(q)), {1}, "total_assets", 5_000_000, 4_000_000)[0]


def test_pos_a1_recognised_other_lines_in_the_block():
    pl = PL.replace("Beban pajak final 29 (72.137) (77.547) Final tax expense",
                    "Penghasilan lain-lain 2.000 1.000 Other income\nBeban lain-lain (1.500) (900) Other expenses")
    assert ledger.sga_complete(L(_pages(pl)), {1}, {"t": 389_417, "t1": 367_537})[0]


def test_neg_a3_subtotal_of_another_block():
    # must NOT: a subtotal equal to the value printed outside the gross profit -> operating profit block
    pl = """LABA BRUTO 940.243 942.021 GROSS PROFIT
Beban penjualan (100.000) (100.000) Selling expenses
Beban umum dan administrasi (200.000) (200.000) General and administrative expenses
LABA USAHA 640.243 642.021 OPERATING PROFIT
Jumlah beban lain-lain (389.417) (367.537) Total other expenses"""
    assert not ledger.sga_complete(L(_pages(pl)), {1}, {"t": 389_417, "t1": 367_537})[0]


def test_neg_a5_ppe_without_the_separate_right_of_use_line():
    # must NOT: owned PPE alone when right-of-use assets are presented on a line of their own
    bs = """Aset tetap - neto 99.142.946 9 103.085.969 Fixed assets - net
Aset hak-guna - neto 7.007.939 12 7.335.209 Right-of-use assets - net"""
    assert not ledger.family_sum(L(_pages(bs)), {1}, ["ppe", "rou", "bearer"], {"t": 99_142_946, "t1": 103_085_969})[0]


def test_c_lab_label_wrapped_below_the_amounts():
    cf = """Arus kas bersih yang diperoleh dari 37,342 38,252 Net cash flows provided from
aktivitas operasi operating activities
Arus kas dari aktivitas investasi: Cash flows from investing activities:"""
    assert ledger.c_lab(L(_pages(cf)), {1}, "cash_flow_from_operations", 37_342, 38_252)[0]
    # must NOT: the next line carries amounts of its own (it is another line, not the rest of the label)
    cf2 = """Arus kas bersih yang diperoleh dari 37,342 38,252 Net cash flows
aktivitas operasi 1,000 2,000 operating activities"""
    assert not ledger.c_lab(L(_pages(cf2)), {1}, "cash_flow_from_operations", 37_342, 38_252)[0]
    # must NOT: the continuation is on the next page
    assert not ledger.c_lab(L(_pages("Arus kas bersih yang diperoleh dari 37,342 38,252", "aktivitas operasi")),
                            {1, 2}, "cash_flow_from_operations", 37_342, 38_252)[0]
