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
