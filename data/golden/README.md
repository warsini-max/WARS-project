# Golden dataset

The "answer key" for the PDF reader: for each test document, the correct value of
every input the engine needs, with the PDF page and a quotation from the document.

- Files: `<TICKER>_<YEAR>.csv`, one row per field and year column (t, t-1).
- Field definitions follow `WARS_TrackB_v0_6.xlsx` (Data_Entry_Guide, Data_Dictionary)
  and the S2 rulebook rules cited in each row.
- `verification`: `DRAFT` (prepared by Claude from the PDF text); `AI-CHECKED-2` (an independent
  blind reading by a second model, ChatGPT, gave the same value; still not human-verified); or
  `VERIFIED` (checked by Gail against the PDF page). Only VERIFIED rows count as an answer key
  for accuracy claims.
- Source PDFs are not in this repository; `data/test_documents.csv` identifies each
  file by SHA-256.
- Evaluation cases (issuers in the case register) are never added here before the evaluation rules are
  locked (plan Phase 7).

## Status

| File | Rows | Status | Open points for Gail |
|---|---|---|---|
| `SIDO_2021.csv` | 60 | 42 rows AI-CHECKED-2 (ChatGPT blind reading 22 Oct 2026: 42/42 identical), 18 DRAFT (all quotes found on the cited pages by `tools/check_golden_quotes.py`; balance sheet and gross profit cross-check) | (1) Corporate tax payable follows D-03 (approved 19 Oct 2026): PPh 25 + 29 of the group (149.341 / 118.900); cross-checked against PSAK 212 (`docs/psak_crosscheck_taxes_payable.md`), one open point: foreign tax 1 / -. (2) Software amortisation and ROU depreciation are not disclosed: entered under DP-01/02 and DP-04 (REVIEW). (3) Whether the file is the first-issued version is not verified. (4) NEW from gate 2: segment note p91/p92 discloses combined D&A 102.679 / 103.816; rule question whether TATA should use it (M changes by about -0,01)(5) Third AI check (29 Oct 2026, AI crosscheck sheet supplied by Gail; **not** human verification): 60/60 values identical, no core figure disputed. Points raised: field name `property_plant_equipment_net` holds PPE + ROU (D-08; app label already says so); amortisation 0 vs UNDISCLOSED (kept: approved M-15 option 4); `depreciation_amortization_total` is not complete D&A (known, DP-04); non-PPE 0 rests on absence of hits (REVIEW until a human checks). Human check sheet for the 28 core figures sent to Gail 29 Oct |
