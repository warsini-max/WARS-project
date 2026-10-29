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
| `SIDO_2021.csv` | 60 | **44 rows VERIFIED by Gail (29 Oct 2026)**: the 28 core score figures (14 fields × 2 years, checked line by line against the PDF on a check sheet of 40 printed figures, all 'Sesuai'), the receivable and ROU components, and the D&A fields after her answers (no long-term debt besides leases; no other depreciated or amortised assets; software amortisation not disclosed anywhere). 6 rows AI-CHECKED-2, 10 DRAFT: statement type, currency, unit, PSAK 73 flag, document version, net income and operating cash flow (comparison only), income before extraordinary items (not presented), ROU depreciation (not disclosed), segment D&A | Open for Gail: (1) whether the file is the first-issued version; (2) rule question whether TATA should use the segment D&A 102.679 / 103.816 (M changes by about −0,01). History: ChatGPT blind reading 22 Oct (42/42 identical); third AI check 29 Oct (60/60 identical) |
