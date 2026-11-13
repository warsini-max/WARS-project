"""Fixes from the two reviews Gail sent on 12 Nov 2026 (15.43 app texts; 15.48 RUNS FY2025 report output) and the
final-tax rule (Gail 15.43: "setuju soal pajak final asal sesuai PSAK"). Each rule has a positive and a negative test
(CLAUDE.md rule 7). Lines are synthetic, modelled on non-case development reports (RDTX 2022, RUNS 2025)."""
from types import SimpleNamespace as NS

from wars_scanner import report, validation
from wars_scanner import xbrl_pipeline as XP


def L(text, page=13):
    return [(page, ln, set(XP.X._amounts(ln)) - {None}) for ln in text.strip("\n").split("\n")]


# RDTX 2022 face (p13) and note 22 (p61): XBRL G&A holds the final tax the face presents on its own
FACE = """
BEBAN OPERASIONAL 2 & 21 (182.031.885.610) (166.303.391.108) OPERATIONAL COSTS
LABA BRUTO 327.486.254.387 247.280.617.337 GROSS PROFIT
Beban Usaha 2 & 22 (43.201.750.272) (41.259.718.686) Operating Expenses
Pajak Final 2 & 14 (50.951.814.000) (41.358.400.845) Final Tax
"""
SGA_XBRL = (94_153_564_272, 82_618_119_531)       # SellingExpenses + GeneralAndAdministrativeExpenses


def test_final_tax_on_the_face_is_taken_out_of_sga_when_the_rest_is_printed():
    ft = XP.final_tax_on_face(L(FACE), [13], *SGA_XBRL)
    assert ft["amounts"] == (50_951_814_000, 41_358_400_845) and ft["page"] == 13 and ft["match"] == 13
    assert SGA_XBRL[0] - ft["amounts"][0] == 43_201_750_272


def test_final_tax_without_a_printed_remainder_is_not_deducted():
    face = FACE.replace("(43.201.750.272) (41.259.718.686)", "(43.201.750.000) (41.259.718.000)")
    ft = XP.final_tax_on_face(L(face), [13], *SGA_XBRL)
    assert ft is not None and ft["match"] is None          # flagged on the card, value unchanged


def test_final_tax_rule_negatives():
    # must NOT: a final-tax line in the notes (tax note, G&A breakdown), not on the face
    assert XP.final_tax_on_face(L(FACE, page=61), [13], *SGA_XBRL) is None
    # must NOT: income tax, final tax payable, a G&A line that merely names final tax
    for ln in ("Pajak penghasilan 2 & 14 (1.003.034.263) (14.336.288) Income tax",
               "Utang pajak final 7.666.963.618 5.726.829.308 Final tax payable",
               "Beban umum - pajak final 50.951.814.000 41.358.400.845"):
        assert not XP.FINAL_TAX_LINE.search(ln), ln
    # must NOT: two final-tax lines (which one?) or no SGA from XBRL
    assert XP.final_tax_on_face(L(FACE + "Pajak final lainnya 1.000.000 2.000.000\n"), [13], *SGA_XBRL) is None
    assert XP.final_tax_on_face(L(FACE), [13], None, SGA_XBRL[1]) is None
    assert XP.FINAL_TAX_LINE.search("Beban pajak final 2 (50.951.814.000) (41.358.400.845)")


def test_closing_cash_is_kept_when_the_statement_lines_are_dropped():
    # the app drops the statement lines after reading; the checks run again on 'Calculate' (RUNS FY2025, item 2.2)
    ln = NS(full_label="Kas dan setara kas akhir tahun", label="Kas dan setara kas akhir tahun",
            amounts={"t": 2_030, "t1": 3_166}, words=[NS(text="2.030"), NS(text="3.166")])
    ex = NS(statements={"cash_flow": NS(lines=[ln])})
    assert validation._cash_flow_closing_cash(ex)[0] == {"t": 2_030, "t1": 3_166}
    ex.statements = {}
    assert validation._cash_flow_closing_cash(ex)[0] == {"t": 2_030, "t1": 3_166}
    # must NOT: invent a closing balance where none was read
    ex2 = NS(statements={"cash_flow": NS(lines=[])})
    assert validation._cash_flow_closing_cash(ex2)[0] is None
    ex2.statements = {}
    assert validation._cash_flow_closing_cash(ex2)[0] is None


def _line(label, full, t, t1, page=9):
    return NS(label=label, full_label=full, amounts={"t": t, "t1": t1}, page=page)


def _r(values, lines):
    ex = NS(values=values, statements={"position": NS(lines=lines)}, printed_labels={})
    return NS(extraction=ex)


def test_wrapped_label_is_shown_in_full_and_a_date_never_as_a_line_item():
    from wars_scanner.pdf_reader import Value
    q = "31 Desember 2024 9 21.599.112.530 22.550.830.016 December 31, 2024"
    v = Value("property_plant_equipment_net", "t", 21_599_112_530, "FOUND", [9], [q])
    full = ("Aset tetap - setelah dikurangi akumulasi penyusutan sebesar Rp2.479.573.534 pada 31 Desember 2025 dan "
            "Rp2.170.760.626 pada 31 Desember 2024")
    r = _r([v], [_line("31 Desember 2024", full, 21_599_112_530, 22_550_830_016)])
    report.keep_printed_labels(r)
    assert report.printed_label(r, "property_plant_equipment_net", q) == \
        "Aset tetap - setelah dikurangi akumulasi penyusutan"
    # no statement line found: a date or a line of figures is never shown as the line item
    r2 = _r([v], [])
    assert report.printed_label(r2, "property_plant_equipment_net", q) == "—"
    assert report.printed_label(r2, "accounts_receivable", "10.072.224.294 12.982.401.242") == "—"
    # a lower-case tail that cannot be completed is marked as a tail
    assert report.printed_label(r2, "ppe_depreciation_disclosed",
                                "administrasi (Catatan 24) 684.682.636 787.916.217 expenses (See notes 24)") \
        == "…administrasi (Catatan 24)"


def test_full_label_is_not_used_for_a_complete_label_or_an_ambiguous_amount():
    from wars_scanner.pdf_reader import Value
    # must NOT: replace a complete label
    v = Value("cash_and_cash_equivalents", "t", 2_030, "FOUND", [9], ["Kas dan setara kas 4 2.030 3.166 Cash"])
    r = _r([v], [_line("Kas dan setara kas", "Notes ASET ASET LANCAR Kas dan setara kas", 2_030, 3_166)])
    report.keep_printed_labels(r)
    assert report.printed_label(r, "cash_and_cash_equivalents", v.quotes[0]) == "Kas dan setara kas"
    # must NOT: pick one of two different labels printed with the same amount
    v = Value("selling_general_administrative_expenses", "t", 500_000, "FOUND", [12], ["administrasi 500.000 400.000"])
    r = _r([v], [_line("administrasi", "Beban umum dan administrasi", 500_000, 400_000, 12),
                 _line("administrasi", "Beban penjualan dan administrasi", 500_000, 300_000, 12)])
    report.keep_printed_labels(r)
    assert report.printed_label(r, "selling_general_administrative_expenses", v.quotes[0]) == "…administrasi"


def test_shown_status_separates_nil_entered_assumed():
    from wars_scanner.pdf_reader import Value
    from wars_scanner.text import Msg
    nil = Value("x", "t", 0, "USER CONFIRMED", note=Msg("chk.prov.nil", note="Catatan 10"))
    ent = Value("x", "t", 5, "USER AMENDED", note=Msg("chk.prov.entered", p="45"))
    ok = Value("x", "t", 5, "USER CONFIRMED", note="")
    assert [report._shown_status(v) for v in (nil, ent, ok)] == ["USER NIL", "USER ENTERED", "USER CONFIRMED"]
    assert report._shown_status(Value("x", "t", 0, "ASSUMED")) == "ASSUMED ZERO"
    assert report._shown_status(Value("x", "t", 83, "ASSUMED")) == "ASSUMED"


def test_rou_card_label_from_the_statement_line_one_label_only():
    from wars_scanner import check
    ln = NS(page=9, label="akumulasi penyusutan", full_label="Aset hak guna - setelah dikurangi akumulasi penyusutan",
            amounts={"t": 115_299_853_434, "t1": 142_306_115_108})
    r = NS(extraction=NS(statements={"position": NS(lines=[ln])}))
    assert check._statement_label(r, 9, [115_299_853_434, 142_306_115_108]) == \
        "Aset hak guna - setelah dikurangi akumulasi penyusutan"
    # must NOT: another page, or two different labels with the same amounts
    assert check._statement_label(r, 10, [115_299_853_434, 142_306_115_108]) == ""
    ln2 = NS(page=9, label="akumulasi penyusutan", full_label="Aset tetap - setelah dikurangi akumulasi penyusutan",
             amounts=dict(ln.amounts))
    r.extraction.statements["position"].lines.append(ln2)
    assert check._statement_label(r, 9, [115_299_853_434, 142_306_115_108]) == ""
