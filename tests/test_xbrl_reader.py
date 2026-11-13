"""XBRL reader (rules approved 30 Oct 2026): synthetic instances only; no issuer data in git (rule 5).
Each rule has a positive and a negative case (rule 7)."""
import io
import zipfile

import pytest

from wars_scanner import xbrl_reader as X

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:idx-cor="http://www.idx.co.id/xbrl/taxonomy/2020-01-01/cor"
 xmlns:idx-dei="http://www.idx.co.id/xbrl/taxonomy/2020-01-01/dei" xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
"""
CTX = """<context id="{id}"><entity><identifier scheme="x">TEST</identifier></entity><period>{p}</period>{s}</context>"""


def ctx_xml():
    out = [CTX.format(id="CurrentYearInstant", p="<instant>2022-12-31</instant>", s=""),
           CTX.format(id="PriorEndYearInstant", p="<instant>2021-12-31</instant>", s=""),
           CTX.format(id="CurrentYearDuration", p="<startDate>2022-01-01</startDate><endDate>2022-12-31</endDate>", s=""),
           CTX.format(id="PriorYearDuration", p="<startDate>2021-01-01</startDate><endDate>2021-12-31</endDate>", s="")]
    for y in ("2022", "2021"):
        for m, cls in (("DirectlyOwnedMember", True), ("TOTAL", False)):
            dims = '<xbrldi:explicitMember dimension="idx-cor:CarryingAmountPropertyPlantEquipmentAxis">' \
                   'idx-cor:CarryingAmountAccumulatedDepreciationMember</xbrldi:explicitMember>'
            if cls:
                dims += f'<xbrldi:explicitMember dimension="idx-cor:ClassesPropertyPlantEquipmentAxis">idx-cor:{m}</xbrldi:explicitMember>'
            out.append(CTX.format(id=f"Dep{y}{m}", p=f"<instant>{y}-12-31</instant>", s=f"<scenario>{dims}</scenario>"))
    return "".join(out)


DEI = {"EntityCode": "TEST", "PeriodOfFinancialStatementsSubmissions": "Tahunan / Annual",
       "TypeOfReportOnFinancialStatements": "Diaudit / Audited", "CurrentPeriodEndDate": "2022-12-31",
       "PriorYearEndDate": "2021-12-31", "LevelOfRoundingUsedInFinancialStatements": "Jutaan / In Million"}

BASE = {  # concept: (t, t-1) in millions
    "Assets": (1000, 900), "CurrentAssets": (400, 350), "NonCurrentAssets": (600, 550), "LiabilitiesAndEquity": (1000, 900),
    "Liabilities": (500, 450), "CurrentLiabilities": (300, 250), "NonCurrentLiabilities": (200, 200),
    "LongTermBankLoans": (150, 160), "CurrentMaturitiesOfBankLoans": (30, 20),
    "PropertyPlantAndEquipment": (500, 480), "CashAndCashEquivalents": (120, 110),
    "TradeReceivablesThirdParties": (90, 80), "TaxesPayable": (15, 12),
}
DUR = {"SalesAndRevenue": (2000, 1800), "CostOfSalesAndRevenue": (1500, 1350), "SellingExpenses": (100, 90),
       "GeneralAndAdministrativeExpenses": (150, 140), "ProfitLoss": (120, 100),
       "NetCashFlowsReceivedFromUsedInOperatingActivities": (130, 110)}


def instance(base=None, dur=None, dei=None, dep=(55, 50, 60, 54)):
    base = dict(BASE, **(base or {}))
    dur = dict(DUR, **(dur or {}))
    d = dict(DEI, **(dei or {}))
    x = [HEAD, ctx_xml()]
    for k, v in d.items():
        x.append(f'<idx-dei:{k} contextRef="CurrentYearDuration">{v}</idx-dei:{k}>')
    for k, (a, b) in base.items():
        if a is not None:
            x.append(f'<idx-cor:{k} contextRef="CurrentYearInstant" unitRef="IDR" decimals="-6">{a * 10**6}</idx-cor:{k}>')
        if b is not None:
            x.append(f'<idx-cor:{k} contextRef="PriorEndYearInstant" unitRef="IDR" decimals="-6">{b * 10**6}</idx-cor:{k}>')
    for k, (a, b) in dur.items():
        x.append(f'<idx-cor:{k} contextRef="CurrentYearDuration" unitRef="IDR" decimals="-6">{a * 10**6}</idx-cor:{k}>')
        x.append(f'<idx-cor:{k} contextRef="PriorYearDuration" unitRef="IDR" decimals="-6">{b * 10**6}</idx-cor:{k}>')
    own_t, own_t1, tot_t, tot_t1 = dep
    for y, own, tot in (("2022", own_t, tot_t), ("2021", own_t1, tot_t1)):
        x.append(f'<idx-cor:AdditionInPropertyPlantAndEquipment contextRef="Dep{y}DirectlyOwnedMember" unitRef="IDR" decimals="-6">{own * 10**6}</idx-cor:AdditionInPropertyPlantAndEquipment>')
        x.append(f'<idx-cor:AdditionInPropertyPlantAndEquipment contextRef="Dep{y}TOTAL" unitRef="IDR" decimals="-6">{tot * 10**6}</idx-cor:AdditionInPropertyPlantAndEquipment>')
    x.append("</xbrl>")
    return "".join(x).encode()


BS = """LAPORAN POSISI KEUANGAN
Kas dan setara kas 120 110 Cash
Piutang usaha - pihak ketiga 90 80 Trade receivables
Jumlah aset lancar 400 350 Total current assets
Aset tetap 500 480 Fixed assets
JUMLAH ASET 1.000 900 TOTAL ASSETS
Utang pajak 15 12 Taxes payable
Pinjaman bank jangka panjang 30 20 Current portion of bank loans
Jumlah liabilitas jangka pendek 300 250 Total current liabilities
Pinjaman bank jangka panjang 150 160 Long-term bank loans
JUMLAH LIABILITAS 500 450 TOTAL LIABILITIES"""
PL = """LAPORAN LABA RUGI
Pendapatan 2.000 1.800 Revenue
Beban pokok pendapatan (1.500) (1.350) Cost of revenue
Beban penjualan (100) (90) Selling expenses
Beban umum dan administrasi (150) (140) General and administrative
Laba tahun berjalan 120 100 Profit for the year
Kas neto dari aktivitas operasi 130 110 Net cash from operating activities"""
NOTE = """Akumulasi penyusutan
Jumlah penyusutan pemilikan langsung 55 tahun 2022
Jumlah penyusutan pemilikan langsung 50 tahun 2021"""


def run(xml, pages=None):
    return X.read(xml, pages or [BS, PL, NOTE], "TEST")


def test_clean_instance_all_found():
    r = run(instance())
    assert r["gate"] == []
    for name in ("revenue", "total_assets", "long_term_debt", "current_maturities_long_term_debt",
                 "selling_general_administrative_expenses", "accounts_receivable", "ppe_depreciation_owned"):
        assert r["fields"]["t"][name].status == "FOUND", name
    assert r["fields"]["t"]["selling_general_administrative_expenses"].value == 250
    assert r["face_findings"] == [] and r["bank_rule"] == []


def test_zip_input_and_scale():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("instance.xbrl", instance())
        z.writestr("Taxonomy.xsd", "<schema/>")
    r = X.read(buf.getvalue(), [BS, PL, NOTE], "TEST")
    assert r["scale"] == 10**6 and r["fields"]["t1"]["revenue"].value == 1800


def test_gate_rejects_interim_unaudited_and_wrong_ticker():
    r = run(instance(dei={"PeriodOfFinancialStatementsSubmissions": "Kuartal III / Third Quarter",
                          "TypeOfReportOnFinancialStatements": "Tidak Diaudit / Unaudited"}))
    assert "not an annual report" in r["gate"] and "not audited" in r["gate"]
    assert X.read(instance(), [BS, PL], "OTHER")["gate"] == ["entity code TEST is not OTHER"]


def test_value_not_printed_in_pdf_is_review():
    # CPRO lesson: XBRL depreciation includes impairment; the PDF prints another figure
    r = run(instance(dep=(57, 50, 57, 50)))
    assert r["fields"]["t"]["ppe_depreciation_owned"].status == "REVIEW"
    # negative: the printed figures are FOUND
    assert run(instance())["fields"]["t"]["ppe_depreciation_owned"].status == "FOUND"


def test_rule2_face_line_tagged_elsewhere_is_review():
    # KBAG/TMAS lesson: consumer financing payables tagged as non-financial liabilities
    bs = BS.replace("JUMLAH LIABILITAS", "Utang pembiayaan konsumen 170 160 Consumer financing payables\nJUMLAH LIABILITAS")
    r = run(instance(base={"OtherNonCurrentNonFinancialLiabilities": (170, 160)}), [bs, PL, NOTE])
    assert any(f["family"] == "debt" for f in r["face_findings"])
    assert r["fields"]["t"]["long_term_debt"].status == "REVIEW"
    # negative: tagged as a borrowing -> no finding
    r = run(instance(base={"LongTermConsumerFinancingPayables": (170, 160)}), [bs, PL, NOTE])
    assert not r["face_findings"]


def test_rule2_rou_tagged_as_advance():
    # IPTV lesson
    bs = BS.replace("Aset tetap 500 480", "Aset tetap 500 480\nAset hak guna 290 865 Right of use assets")
    r = run(instance(base={"OtherNonCurrentAdvances": (290, 865)}), [bs, PL, NOTE])
    assert any(f["family"] == "rou" for f in r["face_findings"])
    # negative: a land-rights sentence (HGB) is not a right-of-use line
    bs2 = BS.replace("Aset tetap 500 480", "Aset tetap 500 480\nSertifikat Hak Guna Bangunan 290 865")
    assert not run(instance(), [bs2, PL, NOTE])["face_findings"]


def test_rule2_combined_debt_line_and_pl_lines_not_flagged():
    # ASII lesson: one face line = bank loans + other loans; CPRO lesson: FX loss on long-term loan on the P&L
    bs = BS.replace("Pinjaman bank jangka panjang 150 160 Long-term bank loans",
                    "Pinjaman bank dan pinjaman lain 155 162 Bank loans and other loans")
    pl = PL + "\nRugi selisih kurs atas pinjaman jangka panjang (8) (3) loss on long-term loan"
    r = run(instance(base={"LongTermOtherBorrowings": (5, 2)}), [bs, pl, NOTE])
    assert not r["face_findings"]


def test_rule1_bank_loan_current_portion_tagged_short_term():
    # MKPI/KBAG lesson
    r = run(instance(base={"CurrentMaturitiesOfBankLoans": (None, None), "ShortTermBankLoans": (30, 20)}))
    assert {b["column"] for b in r["bank_rule"]} == {"t", "t1"}
    assert r["fields"]["t"]["current_maturities_long_term_debt"].status == "REVIEW"
    # negative: short-term loans with tagged current maturities -> no flag
    r = run(instance(base={"ShortTermBankLoans": (30, 20)}))
    assert r["bank_rule"] == []
    # negative: short-term loans, no long-term loans at all -> no flag
    r = run(instance(base={"LongTermBankLoans": (None, None), "CurrentMaturitiesOfBankLoans": (None, None),
                           "ShortTermBankLoans": (30, 20)}))
    assert r["bank_rule"] == []


def test_rule3_untagged_debt_zero_only_when_proven():
    base = {"LongTermBankLoans": (None, None), "CurrentMaturitiesOfBankLoans": (None, None)}
    bs = "\n".join(l for l in BS.split("\n") if "Pinjaman" not in l)
    r = run(instance(base=base), [bs, PL, NOTE])
    assert r["fields"]["t"]["long_term_debt"].value == 0 and r["fields"]["t"]["long_term_debt"].status == "FOUND"
    # negative: a borrowing line is printed on the face but not tagged -> not zero
    bs2 = bs.replace("JUMLAH LIABILITAS", "Utang bank 150 160 Bank loans\nJUMLAH LIABILITAS")
    r = run(instance(base=base), [bs2, PL, NOTE])
    assert r["fields"]["t"]["long_term_debt"].value is None
    # negative: subtotals do not add up -> not zero
    r = run(instance(base=dict(base, NonCurrentAssets=(590, 550))), [bs, PL, NOTE])
    assert r["fields"]["t"]["long_term_debt"].value is None


def test_owned_depreciation_not_table_total():
    # IPTV/IRRA/UNTR lesson: the table total includes ROU depreciation
    r = run(instance(dep=(55, 50, 60, 54)))
    assert r["fields"]["t"]["ppe_depreciation_owned"].value == 55
    assert r["fields"]["t"]["ppe_table_depreciation_total"].value == 60


def test_no_entities_or_network():
    evil = instance().replace(b'<?xml version="1.0" encoding="UTF-8"?>',
                              b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>')
    inst = X.read_instance(evil)
    assert not any("root:" in f.value for f in inst.facts)


# ---------------------------------------------------------------- after XBRL stage 3 (development, 31 Oct 2026)
TAXNOTE = """CATATAN 20. PERPAJAKAN
b. Utang pajak b. Taxes payable
31 Desember 2022 31 Desember 2021
Pasal 21 3 2 Article 21
Pasal 25 4 3 Article 25
Pasal 29 6 5 Article 29
Pajak Pertambahan Nilai 2 2 Value-Added Tax
Jumlah 15 12 Total"""


def test_tax_pph25_29_from_table_that_adds_up_to_face():
    r = run(instance(), [BS, PL, NOTE, TAXNOTE])
    assert r["tax"]["status"] == "FOUND" and (r["tax"]["t"], r["tax"]["t1"]) == (10, 8)


def test_tax_table_not_adding_up_is_not_found():
    bad = TAXNOTE.replace("Pasal 21 3 2", "Pasal 21 4 2")
    t = run(instance(), [BS, PL, NOTE, bad])["tax"]
    assert t["proxy"] is True and t["status"] == "REVIEW"   # PPh 25/29 not taken from a table that does not add up


def test_tax_prepaid_table_with_same_total_is_not_used():
    prepaid = TAXNOTE.replace("b. Utang pajak b. Taxes payable", "a. Pajak dibayar di muka a. Prepaid taxes")
    prepaid = prepaid.replace("Pasal 25 4 3", "Pasal 28A 4 3")
    r = run(instance(), [BS, PL, NOTE, prepaid])
    assert r["tax"]["status"] != "FOUND"


def test_tax_columns_conflict_is_review():
    # PTPW lesson: detail columns add up to the other year's total
    sw = TAXNOTE.replace("Jumlah 15 12", "Jumlah 12 15")
    r = run(instance(base={"TaxesPayable": (12, 15)}), [BS.replace("Utang pajak 15 12", "Utang pajak 12 15"), PL, NOTE, sw])
    assert r["tax"]["status"] == "REVIEW"


def test_false_alarms_from_stage3_are_gone():
    bs = BS.replace("Aset tetap 500 480", "Aset tetap 500 480\nUang muka aset hak guna 1.244 - Advance for right of use assets"
                    "\nPinjaman kepada pihak berelasi 100.000 - Loan to a related party")
    r = run(instance(base={"OtherNonCurrentAdvances": (1244, None), "ReceivablesFromRelatedParties": (100000, None)}),
            [bs, PL, NOTE])
    assert not r["face_findings"]


def test_bank_rule_not_fired_when_issuer_uses_current_maturity_concept_in_other_year():
    # ZYRX lesson: long-term loan repaid; the short-term loan is genuine
    r = run(instance(base={"LongTermBankLoans": (None, 160), "CurrentMaturitiesOfBankLoans": (None, 20),
                           "ShortTermBankLoans": (150, None)}))
    assert r["bank_rule"] == []


def test_financial_institution_gate_needs_two_markers():
    bs1 = BS.replace("Kas dan setara kas 120 110 Cash", "Kas dan setara kas 120 110 Cash\nPiutang pembiayaan konsumen 300 250 Consumer financing receivables")
    assert not any("financial institution" in g for g in run(instance(), [bs1, PL, NOTE])["gate"])
    bs2 = bs1.replace("Jumlah aset lancar", "Piutang sewa pembiayaan 50 40 Finance lease receivables\nJumlah aset lancar")
    bs2 = bs2.replace("Utang pajak 15 12", "Simpanan nasabah 70 60 Deposits from customers\nUtang pajak 15 12")
    assert any("financial institution" in g for g in run(instance(), [bs2, PL, NOTE])["gate"])


def test_d03g_proxy_when_pph_not_found():
    # Gail, 31 Oct 2026: total taxes payable as PENDEKATAN + REVIEW when PPh 25/29 is not found
    r = run(instance(), [BS, PL, NOTE])
    assert r["tax"]["proxy"] is True and r["tax"]["status"] == "REVIEW" and (r["tax"]["t"], r["tax"]["t1"]) == (15, 12)
    # negative: PPh 25/29 found -> no proxy
    r = run(instance(), [BS, PL, NOTE, TAXNOTE])
    assert r["tax"]["proxy"] is False and r["tax"]["status"] == "FOUND"


# ---------------------------------------------------------------- structural debt check (Gail, 4 Nov 2026, after stage 5)
BS_CM = BS.replace("Utang pajak 15 12", "LIABILITAS JANGKA PENDEK\nUtang pajak 15 12").replace(
                   "Pinjaman bank jangka panjang 30 20 Current portion of bank loans",
                   "Utang jangka panjang yang jatuh tempo dalam satu tahun:\n"
                   "Pinjaman bank jangka panjang 30 20 Current portion of bank loans\n"
                   "Pembiayaan 127 125 Financing")


def test_catch_all_line_in_current_maturities_block_is_review():
    # DEAL 2022 lesson: 'Pembiayaan' (financing, current portion) tagged as other payables
    r = run(instance(base={"OtherPayablesThirdParties": (127, 125)}), [BS_CM, PL, NOTE])
    f = [x for x in r["face_findings"] if x.get("kind") == "catch-all"]
    assert f and f[0]["section"] == "c"
    assert r["fields"]["t"]["current_maturities_long_term_debt"].status == "REVIEW"
    assert r["fields"]["t"]["long_term_debt"].status == "FOUND"


def test_catch_all_other_payables_outside_maturities_block_is_not_flagged():
    # negative: ordinary 'Utang lain-lain' among current liabilities, before the current-maturities block
    bs = BS.replace("Utang pajak 15 12 Taxes payable", "Utang lain-lain 127 125 Other payables\nUtang pajak 15 12 Taxes payable")
    r = run(instance(base={"OtherPayablesThirdParties": (127, 125)}), [bs, PL, NOTE])
    assert not r["face_findings"]
    assert r["fields"]["t"]["current_maturities_long_term_debt"].status == "FOUND"


def test_non_current_section_from_total_current_liabilities_line():
    # ICBP 2022 lesson: the non-current heading is wrapped ('LIABILITAS JANGKA / PANJANG'); the lease line below the
    # total current liabilities is non-current, so long-term debt is REVIEW
    bs = BS.replace("JUMLAH LIABILITAS", "LIABILITAS JANGKA\nPANJANG\nLiabilitas sewa 109 111 Lease liabilities\nJUMLAH LIABILITAS")
    r = run(instance(base={"OtherNonCurrentFinancialLiabilities": (109, 111)}), [bs, PL, NOTE])
    f = [x for x in r["face_findings"] if x["family"] == "debt"]
    assert f and f[0]["section"] == "nc"
    assert r["fields"]["t"]["long_term_debt"].status == "REVIEW"


def test_non_debt_catch_all_line_in_non_current_is_not_flagged():
    # negative: employee benefits or provisions tagged with a catch-all concept are not debt
    bs = BS.replace("JUMLAH LIABILITAS", "Liabilitas imbalan kerja 109 111 Employee benefits liability\nJUMLAH LIABILITAS")
    r = run(instance(base={"OtherNonCurrentLiabilities": (109, 111)}), [bs, PL, NOTE])
    assert not r["face_findings"]


def test_rule3_needs_a_readable_liabilities_face():
    # TECH 2022 lesson: the liabilities page is an image; debt = 0 cannot be proven from the face
    base = {"LongTermBankLoans": (None, None), "CurrentMaturitiesOfBankLoans": (None, None)}
    assets_only = "\n".join(BS.split("\n")[:6])
    r = run(instance(base=base), [assets_only, PL, NOTE])
    assert r["fields"]["t"]["long_term_debt"].value is None
    # negative: liabilities printed and no debt line -> zero allowed (as before)
    bs = "\n".join(l for l in BS.split("\n") if "Pinjaman" not in l)
    assert run(instance(base=base), [bs, PL, NOTE])["fields"]["t"]["long_term_debt"].status == "FOUND"


def test_current_maturity_heading_on_asset_side_does_not_open_debt_block():
    # negative (CLPI 2022): 'Bagian lancar atas: investasi' among assets; other payables later are not debt
    bs = BS.replace("Kas dan setara kas 120 110 Cash", "Kas dan setara kas 120 110 Cash\nBagian lancar atas:")
    bs = bs.replace("Utang pajak 15 12 Taxes payable", "LIABILITAS JANGKA PENDEK\nUtang lain-lain 127 125 Other payables\n"
                                                         "Utang pajak 15 12 Taxes payable")
    r = run(instance(base={"OtherPayablesThirdParties": (127, 125)}), [bs, PL, NOTE])
    assert not r["face_findings"]


def test_current_maturity_heading_sharing_a_line_with_the_first_item():
    # DEAL 2022: 'yang jatuh tempo dalam satu tahun : ... Utang bank - 3.361' on one line, 'Pembiayaan' next
    bs = BS.replace("Pinjaman bank jangka panjang 30 20 Current portion of bank loans",
                    "LIABILITAS\nUtang jangka panjang yang jatuh tempo dalam satu tahun: Utang bank 30 20 Bank debt\n"
                    "Pembiayaan 127 125 Financing")
    r = run(instance(base={"OtherPayablesThirdParties": (127, 125)}), [bs, PL, NOTE])
    assert [x for x in r["face_findings"] if x.get("kind") == "catch-all"]


# ---------------------------------------------------------------- stage 6 finding A (SOHO 2022): wrapped heading
BS_WRAP = BS.replace("Utang pajak 15 12", "LIABILITAS JANGKA PENDEK\nUtang pajak 15 12").replace(
    "Pinjaman bank jangka panjang 30 20 Current portion of bank loans",
    "Bagian liabilitas jangka panjang\nyang jatuh tempo dalam satu tahun: Current portion\n"
    "Pinjaman bank jangka panjang 30 20 Current portion of bank loans\nLiabilitas sewa 127 125 Lease liabilities")


def test_wrapped_current_maturities_heading_is_not_the_non_current_heading():
    r = run(instance(base={"OtherCurrentNonFinancialLiabilities": (127, 125)}), [BS_WRAP, PL, NOTE])
    f = [x for x in r["face_findings"] if x["family"] == "debt"]
    assert f and all(x["section"] == "c" for x in f)
    assert r["fields"]["t"]["current_maturities_long_term_debt"].status == "REVIEW"
    assert r["fields"]["t"]["long_term_debt"].status == "FOUND"


def test_real_non_current_heading_still_opens_the_non_current_section():
    # negative: 'LIABILITAS JANGKA PANJANG' as a heading, and a total line, keep their meaning
    bs = BS.replace("Pinjaman bank jangka panjang 150 160", "LIABILITAS JANGKA PANJANG\nLiabilitas sewa 109 111 Lease liabilities\n"
                    "Pinjaman bank jangka panjang 150 160")
    r = run(instance(base={"OtherNonCurrentFinancialLiabilities": (109, 111)}), [bs, PL, NOTE])
    f = [x for x in r["face_findings"] if x["family"] == "debt"]
    assert f and f[0]["section"] == "nc"
    assert not X.CM_WRAP.match("Jumlah bagian liabilitas jangka panjang")
    assert X.CM_WRAP.match("Bagian liabilitas jangka panjang")


# ---------------------------------------------------------------- stage 6 finding F (IMPC, PTPW): year columns swapped
def test_year_columns_swapped_on_some_face_lines_are_detected():
    bs = BS.replace("JUMLAH ASET 1.000 900", "JUMLAH ASET 900 1.000").replace(
        "Jumlah liabilitas jangka pendek 300 250", "Jumlah liabilitas jangka pendek 250 300")
    o = run(instance(), [bs, PL, NOTE])["column_order"]
    assert o["inconsistent"] and {n for _, n in o["reversed"]} >= {"total_assets"}


def test_consistent_year_columns_are_not_flagged():
    # negative: every face line in the same order
    assert not run(instance(), [BS, PL, NOTE])["column_order"]["inconsistent"]


def test_movement_tables_on_note_pages_do_not_count():
    # negative: a note table printing the opening balance (t-1) before the closing one is not a swapped layout
    note = NOTE + "\nNilai buku 480 500 Net book value"
    o = run(instance(), [BS, PL, note])["column_order"]
    assert not o["inconsistent"]


# ---------------------------------------------------------------- XBRL stage 7, findings 3 and 7 (synthetic)
def test_stage7_debt_labels_lease_payables_and_loans_from_related_parties():
    rx, no = X.FAMILY_LABEL["debt"], X.NOT_FAMILY["debt"]
    for ln in ("Utang sewa 98.950.627 2m,15,24 627.171.962 Lease payables",
               "Utang kepada pihak berelasi 126.641.220.018 20,31 118.719.269.018 Loans from related parties"):
        assert rx.search(ln) and not no.search(ln), ln
    # negatives: a payable to a related party without the word 'loan' (no interest can be seen on the face),
    # a loan given (asset), and the cash-flow payment line
    assert not rx.search("Utang pihak berelasi - 2f,2h,8d 156.013.596 Due to related party")
    assert no.search("Pinjaman kepada karyawan 1.000 900 Loans to employees")
    assert no.search("Pembayaran utang sewa (577.792.960) 15 (1.106.974.950) Payment of lease payables")


def test_stage7_rule2_untagged_lease_payables_line_makes_debt_review():
    bs = BS.replace("Jumlah liabilitas jangka pendek", "Utang sewa 900 700 Lease payables\nJumlah liabilitas jangka pendek")
    r = run(instance(), [bs, PL, NOTE])
    assert any(f["family"] == "debt" and "Utang sewa" in f["line"] for f in r["face_findings"])
    assert r["fields"]["t"]["current_maturities_long_term_debt"].status == "REVIEW"


def test_stage7_nil_dash_is_not_a_bullet():
    assert X.nil_dashes("- Liabilitas Sewa 2 173.279.599 - - Lease Liabilities") == 1
    assert X.nil_dashes("- Pembiayaan Konsumen - 71.931.020 - Consumer Financing") == 1
    # negative: a real three-column line (1 January column) without bullets still has two nil amounts
    assert X.nil_dashes("Utang bank 1.500 - - Bank loans") == 2


def test_stage7_reversed_wrapped_current_maturities_heading():
    assert X.CM_WRAP.match(" Liabilitas Jangka Panjang - Bagian Long-term Liabilities - Current")
    # negatives: the non-current section heading and its total are not a current-maturities heading
    assert not X.CM_WRAP.match("LIABILITAS JANGKA PANJANG NON-CURRENT LIABILITIES")
    assert not X.CM_WRAP.match("Liabilitas jangka panjang - bagian tidak lancar jumlah 500 400")


def test_p5_cost_of_sales_face_words():
    # a face that prints cost of sales or gross profit keeps the XBRL figure; one without (by nature) does not
    for ln in ("Beban pokok penjualan (1.200) (1.100) Cost of goods sold", "LABA BRUTO 500 450 GROSS PROFIT",
               "Cost of revenues (10) (9)"):
        assert X.COST_OF_SALES_FACE.search(ln), ln
    for ln in ("Beban penyusutan (10,569,622) 7 (9,956,227) Depreciation expenses",
               "Beban infrastruktur (7,733,947) 24a (7,989,540) Infrastructure expenses"):
        assert not X.COST_OF_SALES_FACE.search(ln), ln


# ---------------------------------------------------------------- XBRL stage 8 findings (synthetic)
class _Inst:
    def __init__(self, v):
        self.v = v

    def plain(self, concept, col, kind):
        return self.v.get((concept, col))


def _lines(page, text):
    return [(page, ln, set(X._amounts(ln))) for ln in text.split("\n")]


_FACE_TAX = """Utang usaha - pihak ketiga 14 157,850 132,939 Trade payables - third parties
Utang pajak Taxes payable
 - Pajak penghasilan badan 7b 12,466 22,763 Corporate income tax -
 - Pajak lain-lain 7b 4,651 6,723 Other taxes -
Beban yang masih harus dibayar 15 114,346 110,661 Accrued expenses"""


def test_stage8_corporate_tax_from_the_face():
    inst = _Inst({("TaxesPayable", "t"): 17117, ("TaxesPayable", "t1"): 29486})
    r = X.corporate_tax_on_face(inst, _lines(11, _FACE_TAX), {"bs": [11], "pl": []})
    assert (r["t"], r["t1"], r["status"], r["page"]) == (12466.0, 22763.0, "REVIEW", 11)


def test_stage8_corporate_tax_from_the_face_negatives():
    pages = {"bs": [11], "pl": []}
    # the lines do not add up to the XBRL total -> nothing
    bad = _Inst({("TaxesPayable", "t"): 17118, ("TaxesPayable", "t1"): 29486})
    assert X.corporate_tax_on_face(bad, _lines(11, _FACE_TAX), pages) is None
    inst = _Inst({("TaxesPayable", "t"): 17117, ("TaxesPayable", "t1"): 29486})
    # an unnamed line in the block -> nothing (no guess what it is)
    odd = _FACE_TAX.replace(" - Pajak lain-lain 7b 4,651 6,723 Other taxes -", " - Bunga 7b 4,651 6,723 Interest -")
    assert X.corporate_tax_on_face(inst, _lines(11, odd), pages) is None
    # not on the balance sheet pages -> nothing
    assert X.corporate_tax_on_face(inst, _lines(75, _FACE_TAX), pages) is None
    # two corporate lines -> nothing
    two = _FACE_TAX.replace(" - Pajak lain-lain 7b 4,651 6,723 Other taxes -", " - PPh pasal 29 7b 4,651 6,723 Article 29 -")
    assert X.corporate_tax_on_face(inst, _lines(11, two), pages) is None


def test_stage8_rounding_difference_uses_the_printed_figure():
    ln = [(9, "TOTAL ASET 290.273.064.686 289.976.056.809 TOTAL ASSETS", {290273064686, 289976056809})]
    assert X._pair_lines_rounded(ln, 290273064683, 289976056809) == [(9, ln[0][1], 290273064686, 289976056809)]
    # negatives: more than 10 units apart, a small figure, two different nearby pairs, and an exact pair
    assert X._pair_lines_rounded(ln, 290273064670, 289976056809) == []
    small = [(9, "Kas 5.394.569 10.422.997", {5394569, 10422997})]
    assert X._pair_lines_rounded(small, 5394566, 10422997) == []
    two = ln + [(10, "JUMLAH 290.273.064.680 289.976.056.809", {290273064680, 289976056809})]
    assert X._pair_lines_rounded(two, 290273064683, 289976056809) == []
    assert X._pair_lines_rounded(ln, 290273064686, 289976056809) == []      # exact: the normal path handles it


def test_rule2_rou_label_wrapped_onto_the_amount_line():
    # SPTO 2021 lesson: 'Aset hak guna - setelah dikurangi' / 'akumulasi penyusutan 12 115.299 ...'; the amount line
    # alone names no family and right-of-use assets tagged as other financial assets went into PPE as FOUND
    wrap = "Aset hak guna - setelah dikurangi Right of use assets - net of\nakumulasi penyusutan 12 290 865 accumulated depreciation"
    bs = BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + wrap)
    r = run(instance(base={"OtherNonCurrentFinancialAssets": (290, 865)}), [bs, PL, NOTE])
    f = [x for x in r["face_findings"] if x["family"] == "rou"]
    assert f and f[0]["wrapped"] and f[0]["amounts"] == [290, 865]
    # must NOT: an advance for right-of-use assets above a continuation line
    adv = "Uang muka aset hak guna\nuntuk sewa kantor 12 290 865 advances"
    assert not [x for x in run(instance(base={"OtherNonCurrentFinancialAssets": (290, 865)}),
                               [BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + adv), PL, NOTE])["face_findings"]
                if x["family"] == "rou"]
    # must NOT: a line that starts its own label (capital) does not inherit the line above
    own = "Aset hak guna - neto Right of use assets - net\nInvestasi jangka panjang 12 290 865 Long-term investments"
    assert not [x for x in run(instance(base={"OtherNonCurrentFinancialAssets": (290, 865)}),
                               [BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + own), PL, NOTE])["face_findings"]
                if x["family"] == "rou"]
    # must NOT: a label above a blank line
    gap = "Aset hak guna - setelah dikurangi\n\nakumulasi penyusutan 12 290 865"
    assert not [x for x in run(instance(base={"OtherNonCurrentFinancialAssets": (290, 865)}),
                               [BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + gap), PL, NOTE])["face_findings"]
                if x["family"] == "rou"]
    # must NOT: a label-only line above the label that the amount line continues (JAST 2025)
    two = "Utang sewa guna Lease liabilities\nLiabilitas\nimbalan kerja 23 290 865"
    assert not [x for x in run(instance(base={"OtherNonCurrentFinancialAssets": (290, 865)}),
                               [BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + two), PL, NOTE])["face_findings"]
                if x["family"] == "debt" and x.get("wrapped")]
    # must NOT: a note sentence ending with a date (the year is not an amount; PURI 2022)
    sent = "Utang pihak berelasi merupakan pinjaman modal kerja,\njangka waktu sampai dengan 31 Agustus 2025."
    assert not [x for x in run(instance(), [BS.replace("Aset tetap 500 480", "Aset tetap 500 480\n" + sent), PL, NOTE])
                ["face_findings"] if x.get("wrapped")]

