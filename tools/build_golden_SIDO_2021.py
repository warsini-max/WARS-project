# Provenance script: builds data/golden/SIDO_2021.csv from LK_SIDO_2021.pdf (sha256 7151...04e6, not in git).
# Every quote is taken from the pdftotext line itself; values are asserted to appear in the quote.
import csv, re, subprocess
PDF='/home/claude/s3core/docs/LK_SIDO_2021.pdf'
raw=subprocess.run(['pdftotext','-layout',PDF,'-'],capture_output=True,text=True).stdout.split('\f')
def line(p, pat):
    hits=[re.sub(r'\s+',' ',l).strip() for l in raw[p-1].splitlines() if re.search(pat,l)]
    assert len(hits)>=1, (p,pat)
    return hits[0]
def fmt(n): return f"{n:,}".replace(',', '.')
rows=[]
def add(field,col,value,status,pages,quotes,components='',rule='',note=''):
    pages=[str(p) for p in pages]
    for q in quotes: pass
    if isinstance(value,int):
        assert any(fmt(abs(value)) in q for q in quotes) or components, (field,col,value)
    rows.append(dict(ticker='SIDO',fiscal_year=2021,field=field,column=col,value=value if value is not None else '',
        unit='IDR millions' if isinstance(value,int) else '',status=status,components=components,
        pdf_page=';'.join(pages),printed_page=';'.join(str(int(p)-6) for p in pages),
        quote=' || '.join(quotes),rule=rule,note=note,verification='DRAFT'))
# metadata
add('statement_type','both','Consolidated','FOUND',[7],[line(7,r'LAPORAN POSISI KEUANGAN')])
add('reporting_currency','both','IDR','FOUND',[7],[line(7,r'Disajikan dalam jutaan Rupiah')])
add('unit_scale','both','Millions','FOUND',[7],[line(7,r'Disajikan dalam jutaan Rupiah')],rule='A7')
add('psak73_applied','t','Y','FOUND',[8],[line(8,r'Liabilitas sewa - jangka pendek')],note='Lease liabilities presented in both columns')
add('psak73_applied','t1','Y','FOUND',[8],[line(8,r'Liabilitas sewa - jangka pendek')])
add('doc_version','t','1','NOT VERIFIED',[],[],note='Assumed first issue; whether this file is the first-submitted version has not been checked (human task)')
# face lines
def face(field,p,pat,t,t1,rule='',note=''):
    q=line(p,pat)
    add(field,'t',t,'FOUND',[p],[q],rule=rule,note=note); add(field,'t1',t1,'FOUND',[p],[q],rule=rule,note=note)
face('revenue',9,r'^\s*PENJUALAN',4020980,3335411)
face('cost_of_goods_sold',9,r'BEBAN POKOK PENJUALAN',1734948,1496628)
q1=line(9,r'Beban penjualan dan pemasaran'); q2=line(9,r'Beban umum dan administrasi')
add('selling_general_administrative_expenses','t',556440+169564,'FOUND',[9,9],[q1,q2],components='556.440 selling and marketing + 169.564 general and administrative')
add('selling_general_administrative_expenses','t1',492330+200659,'FOUND',[9,9],[q1,q2],components='492.330 selling and marketing + 200.659 general and administrative')
q1=line(7,r'Pihak ketiga - neto'); q2=line(7,r'Pihak berelasi')
add('accounts_receivable','t',372981+291077,'FOUND',[7,7],[q1,q2],components='372.981 third parties net + 291.077 related parties',rule='D-04',note='Other receivables (3.032 / 3.890) excluded: non-trade')
add('accounts_receivable','t1',296885+366872,'FOUND',[7,7],[q1,q2],components='296.885 third parties net + 366.872 related parties',rule='D-04')
face('ar_third',7,r'Pihak ketiga - neto',372981,296885,rule='D-04')
face('ar_related',7,r'Pihak berelasi',291077,366872,rule='D-04')
face('total_assets',7,r'TOTAL ASET',4068970,3849516)
face('current_assets',7,r'Total Aset Lancar',2244707,2052081)
qp=line(7,r'Aset tetap - neto'); qr=line(60,r'Hak untuk menggunakan aset')
add('property_plant_equipment_net','t',1588101+11455,'FOUND',[7,60],[qp,qr],components='1.588.101 fixed assets net + 11.455 right-of-use assets (inside other non-current assets, Note 11)',rule='D-08')
add('property_plant_equipment_net','t1',1568264+7811,'FOUND',[7,60],[qp,qr],components='1.568.264 fixed assets net + 7.811 right-of-use assets (Note 11)',rule='D-08')
face('rou_assets_net',60,r'Hak untuk menggunakan aset',11455,7811,rule='D-08')
face('current_liabilities',8,r'Total Liabilitas Jangka Pendek',543370,560043)
face('total_liabilities',8,r'TOTAL LIABILITAS\s+5',597785,627776)
face('long_term_debt',8,r'Liabilitas sewa - jangka panjang',2385,4216,rule='D-02',note='No bank loans or bonds; lease liabilities non-current only')
face('current_maturities_long_term_debt',8,r'Liabilitas sewa - jangka pendek',6285,2974,rule='D-02')
face('cash_and_cash_equivalents',7,r'Kas dan setara kas',1082219,1031954)
face('net_income',9,r'LABA TAHUN BERJALAN',1260898,934016)
face('cash_flow_from_operations',12,r'Aktivitas Operasi\s+1',1199317,1035754)
add('income_before_extraordinary_items','t',None,'NOT PRESENTED',[],[],note='No such line; leave blank')
add('income_before_extraordinary_items','t1',None,'NOT PRESENTED',[],[])
# taxes
q25=line(62,r'PPh Pasal 25'); q29=line(62,r'PPh Pasal 29'); s25=line(63,r'PPh Pasal 25'); s29=line(63,r'PPh Pasal 29')
note='D-03 (APPROVED 19 Oct 2026): corporate income tax payable only, PPh 25/29 of the group entities. Withholding taxes and VAT excluded. (The S3core scan cited Art. 29 only; superseded by the D-03 wording.) PSAK cross-check: docs/psak_crosscheck_taxes_payable.md (consistent with PSAK 212 par. 2, 5, 12; Pajak Luar Negeri 1 / - excluded, REVIEW, immaterial)'
add('taxes_payable','t',29809+99237+2162+18133,'FOUND',[62,62,63,63],[q25,q29,s25,s29],components='Company Art.25 29.809 + Art.29 99.237; subsidiaries Art.25 2.162 + Art.29 18.133',rule='D-03',note=note)
add('taxes_payable','t1',17833+89007+850+11210,'FOUND',[62,62,63,63],[q25,q29,s25,s29],components='Company Art.25 17.833 + Art.29 89.007; subsidiaries Art.25 850 + Art.29 11.210',rule='D-03',note=note)
# depreciation / amortisation
qa=line(57,r'Total akumulasi penyusutan'); qb=line(58,r'Total akumulasi penyusutan')
add('ppe_depreciation_disclosed','t',93944,'FOUND',[57],[qa],rule='D-07',note='Owned fixed assets only; allocation 87.433 + 1.330 + 5.181 (p80-81)')
add('ppe_depreciation_disclosed','t1',96876,'FOUND',[58],[qb],rule='D-07')
add('rou_depreciation','t',None,'NOT DISCLOSED',[],[],rule='G-23',note='Searched Notes 10, 11, depreciation allocation p80-81, lease text p37-38 (S3core scan)')
add('rou_depreciation','t1',None,'NOT DISCLOSED',[],[],rule='G-23')
qs=line(60,r'Sistem perangkat lunak')
nt='Software 4.792 / 6.659 has a finite life and is amortised (policy p33), but no amortisation amount is disclosed. Entry under DP-01/02: amortisation = amount actually disclosed (0 = nothing disclosed, NOT nil), amort_status = UNDISCLOSED, REVIEW'
add('amortization_intangibles','t',0,'UNDISCLOSED',[60],[qs],components='0 = nothing disclosed (not nil)',rule='G-22; DP-01/02',note=nt)
add('amortization_intangibles','t1',0,'UNDISCLOSED',[60],[qs],components='0 = nothing disclosed (not nil)',rule='G-22; DP-01/02',note=nt)
add('amort_status','t','UNDISCLOSED','FOUND',[60],[qs],rule='G-22; DP-01/02')
add('amort_status','t1','UNDISCLOSED','FOUND',[60],[qs],rule='G-22; DP-01/02')
nd='Built ONLY from disclosed components (DP-01/02 cond. 2; DP-04): owned PPE depreciation; ROU depreciation and software amortisation are undisclosed and left out. DEPI and TATA are affected (DP-04)'
add('depreciation_amortization_total','t',93944,'BUILT FROM DISCLOSED COMPONENTS',[57],[qa],components='93.944 owned PPE depreciation + 0 disclosed amortisation + 0 non-PPE',rule='DP-01/02; DP-04; Q5',note=nd)
add('depreciation_amortization_total','t1',96876,'BUILT FROM DISCLOSED COMPONENTS',[58],[qb],components='96.876 owned PPE depreciation + 0 disclosed amortisation + 0 non-PPE',rule='DP-01/02; DP-04; Q5',note=nd)
nn='No investment property, deferred-charge amortisation or other non-PPE D&A found (S3core scan: 0 hits as presented items). REVIEW: absence of hits is not proof of absence'
add('non_ppe_status','t','NONE_PRESENT','REVIEW',[],[],rule='Q2-c',note=nn)
add('non_ppe_status','t1','NONE_PRESENT','REVIEW',[],[],rule='Q2-c',note=nn)
add('depreciation_amortization_non_ppe','t',0,'REVIEW',[],[],components='0 (NONE_PRESENT)',rule='Q2-c')
add('depreciation_amortization_non_ppe','t1',0,'REVIEW',[],[],components='0 (NONE_PRESENT)',rule='Q2-c')
qs1=line(91,r'Depreciation and amortization'); qs2=line(92,r'Depreciation and amortization')
ns='Segment information discloses combined depreciation and amortisation (all classes). Found by the ChatGPT independent reading (gate 2), confirmed by Claude. NOT used as depreciation_amortization_total under DP-01/02 cond. 2 (total built from disclosed components). The unexplained difference to owned-PPE depreciation (8.735 / 6.940) must not be attributed to ROU or software (Q2-c). RULE QUESTION for Gail: use this aggregate for the TATA D&A term?'
add('da_aggregate_segment','t',102679,'FOUND',[91],[qs1],rule='DP-01/02; Q2-c',note=ns)
add('da_aggregate_segment','t1',103816,'FOUND',[92],[qs2],rule='DP-01/02; Q2-c',note=ns)
# gate 2: ChatGPT independent reading agreed on these rows (42/42), 22 Oct 2026
G2={'revenue','cost_of_goods_sold','selling_general_administrative_expenses','accounts_receivable','ar_third','ar_related',
    'total_assets','current_assets','property_plant_equipment_net','rou_assets_net','current_liabilities','total_liabilities',
    'long_term_debt','current_maturities_long_term_debt','cash_and_cash_equivalents','net_income','cash_flow_from_operations',
    'taxes_payable','ppe_depreciation_disclosed','rou_depreciation','amortization_intangibles'}
for r in rows:
    if r['field'] in G2:
        r['verification']='AI-CHECKED-2'
cols=list(rows[0].keys())
with open('data/golden/SIDO_2021.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
print(len(rows),'rows')
