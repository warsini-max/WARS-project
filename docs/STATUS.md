# Phase status and evidence

Updated 28 Oct 2026. Phase definitions and completion criteria: `docs/WARS_App_Plan_r0.md` §4.
A phase is DONE only when its completion criterion is met, not when the code exists.

This public repository starts from the state of 28 Oct 2026. Earlier development history (and the commit
references in the tables below) is kept in a private archive repository.

| Phase | Criterion (plan §4) | Status | Evidence |
|---|---|---|---|
| 0 Golden data | Golden dataset for the test reports | **SIDO 2021: 44 of 60 rows VERIFIED by Gail (29 Oct 2026)**, incl. all 28 core score figures; the rest are comparison-only, text or not-disclosed fields (6 AI-CHECKED-2, 10 DRAFT). Other reports have no golden yet | `data/golden/SIDO_2021.csv` |
| 1 Engine | Engine = workbook v0.6 | **Done** | 95 synthetic pairs × 53 columns, `tests/test_engine_vs_workbook.py` |
| 2 / 2b Reader | Zero unflagged wrong numbers vs golden; find rate reported | **Done for SIDO 2021** (40/40 fields match, 0 silent). Other reports have no golden yet | `tests/test_pdf_reader.py`, `tests/test_notes_reader.py`, `docs/pdf_reader.md` |
| 3 Cross-checks + confirmation | Every injected error (unit, swapped columns, missing value) caught as yellow or red | **Technical criterion met.** Formally open: four reading-quality controls are PROPOSED (below) and need Gail's decision | `tests/test_validation.py`, `docs/validation.md` |
| 4 Web app | **Gail runs SIDO 2021 from upload to download, without help** | **NOT DONE; DEFERRED by Gail (23 Oct 2026)** after the Windows SmartScreen warning on `run_windows.bat`. App runs locally in the build environment only. Blocks Phases 5–6, nothing else | `app.py`, `run_windows.bat`, `docs/run_locally_windows.md` |
| 5 Tests U1–U5 | See plan | Not started (U1, U2 partly covered by the automated tests) | — |
| 6 Online | Public link working for all test PDFs | Not started. **No deployment before Phase 6** | — |
| 7 Case evaluation | S1 rules | Frozen until Phase 7 (WR-2 M2) | — |
| D Annual report 300+ pages | Real Laporan Tahunan read correctly vs the audited LK (Gail, 23 Oct 2026: KLBF 2021) | **PASSED (Gail, 23 Oct 2026) for the one annual report tested** (KLBF 2021, 470 pages, LK embedded whole). Not a claim that other annual-report formats are covered. Source URL (from Gail): kalbe.co.id, see `docs/phaseD_acceptance_KLBF_2021.md`; hash not re-verified from the URL (site unreachable from the build environment) | `docs/phaseD_acceptance_KLBF_2021.md`, `tools/accept_real_annual_report.py`, `tests/test_annual_report.py` |

## Test evidence

| Commit | Result | Notes |
|---|---|---|
| `8281113` (Phase 2b) | 143 passed | Notes reader, pipeline |
| `ea215ae` (Phase 4 minimal app) | 149 passed | + presentation tests |
| `02e33f2` (M-06) | 203 passed, 1 skipped | non-PPE status set by the user |
| `f376e04` (Phase D) | **212 passed, 1 skipped** | statements located in the whole document; 9 annual-report tests |
| (this commit) acceptance tool | 213 passed, 2 skipped | skipped: real KLBF 2021 annual report not supplied (acceptance PENDING); SIDO amortisation 0 (as before) |
| (this commit) real annual report | **215 passed, 1 skipped** | real KLBF 2021 annual report acceptance runs and passes; skipped: SIDO amortisation 0 (as before) |
| ROU-within-PPE guard | **261 passed, 1 skipped** | no double count when ROU is presented within fixed assets; skipped: SIDO amortisation 0 (as before) |
| Trial 4 blind run (29 Oct 2026) | code frozen at `76c8ea2` (382 passed, 1 skipped) | 10 issuers drawn at random (seed 20261029, one per non-financial sector; replacements only where the 2021 report was missing or the issuer suspended). **1 of 10 scored** (BINO −2.376; every score figure checked by hand against the PDF: **0 wrong**). Not scored: statements not located in 3 digital PDFs (DGNS, LMSH, MARI); false-alarm ERROR on fixed assets in 2 (FLMC, TOBA: the carrying-amount label wraps over two lines); depreciation or other figures not found in 3 (CASH, PUDP, TAMA); MITI held by the year-label check (three-column restated statement). Target proposed by Claude (≥6 of 10 scored, 0 wrong without a flag): **not met** on coverage. Blind waves so far: 6 of 30 issuers scored, 1 figure wrong without a flag (Trial 2, APII, since fixed) |
| Trial 3 reader gaps and safeguard audit (29 Oct 2026, development) | **382 passed, 1 skipped** | Audit of all 37 non-case documents (Trial 1–3 and the test documents): no ERROR safeguard is left holding a score (the SAME ERRORs came from a note reference read as a figure). Fixes, each with a negative test (`tests/test_trial3_reader.py`, 31 tests): glued and split words in labels ('LABATAHUN', 'P ajak', 'Jum lah'); a clause comma after a sentence figure; current-maturity sub-heading in current liabilities (bank loan current portion was left out: ERAA, MTPS); 'utang pembiayaan' counted as interest-bearing debt (D-02; changes APII, GLVA, KLBF 2023, SOSS, TALF debt, KLBF 2023 M −2.2232 → −2.2234); ROU depreciation from a self-checking ROU movement schedule or a ROU-note sentence, never from a combined fixed-asset/ROU note; numbered headings without a space ('11.ASET TETAP'); a new note or a tax line ends an allocation table (SOSS prepaid tax would otherwise have been read as ROU depreciation); investment-property depreciation from the expense note when the note repeats it; receivable label with the allowance amount wrapped; selling/G&A items under a 'BEBAN USAHA' heading; a 'Catatan 4' column header is not the Notes column; 'Pendapatan jasa - neto'; 'cash generated from operations' is not the operating cash flow (this also corrects PTSN, which had the wrong line under REVIEW). Coverage on the 37 documents: 25 → 29 scored. Not scored: 4 scanned PDFs, LINK (expenses by nature, no COGS), PTSN (P5 decision), SAME (merging-entities restatement, unaudited comparatives), WSBP (bonds reclassified to current, 3-column notes). 8 test documents: only KLBF 2023 changes (financing payable in long-term debt) |
| Trial 2 follow-up and Trial 3 wave A (29 Oct 2026) | **351 passed, 1 skipped** | Trial 3 wave A blind run at `9928704` (10 issuers chosen by Gail): 2 of 10 scored, **0 figures wrong without a flag** (checked by hand), 3 withheld by a safeguard (2 were false alarms), 5 not calculated. Development fixes since then (not validation): Trial 2 now 8 of 10 scored, Trial 3 4 of 10; SGA completeness check; glued, letter-spaced and bracket-split text layers; 'Parent-only' basis; depreciation sentences only inside the fixed-asset note. 8 test documents: values and M-scores unchanged |
| Report review by Gail (28 Oct 2026) | **338 passed, 1 skipped** | report PDF and Excel revised per Gail's 13 points: title 'Red-flag Scanner Report' in both versions; no 'rules / Workbook v0.6' box or footer text; no rule codes anywhere for the user; score breakdown gets a source-figures column (line items and PDF pages per index), formula only in methodology; shorter checklist intro; 'Tidak diungkapkan (dihitung 0)'; Appendix B with an explanation per check (failed and review first, clear wording instead of 'vs'); reading notes on their own page (Appendix C); numbered lists; wider figure columns; footer 'Contact us' with LinkedIn link and an email icon (mailto). Right of use assets taken as 0 when the report never mentions them (Gail approved); M-scores of Trial 1 and Trial 2 unchanged |
| Rule 7 cross-checks after Trial 2 (28 Oct 2026) | **337 passed, 1 skipped** | Trial 2 blind run (commit `9f07402`, 10 issuers) found two figures marked FOUND without a cross-check and wrong: APII trade receivables (wrapped third-party label missed; score −1.649 wrong) and TFAS SGA (wrapped 'Beban umum dan / administrasi' missed; score withheld for another reason). Fixes: every score figure on the face now needs a passed cross-check to be FOUND, otherwise REVIEW (balance, total liabilities and equity, current + non-current liabilities, section sums incl. current liabilities, gross profit, profit before tax → profit for the year, operating + investing + financing = net change in cash, cash in the cash-flow statement, SGA = printed total operating expenses (ERROR `a_sga_total` when a line is missed), or the same pair of figures found again in the notes); trade-receivable items with wrapped labels; head + tail of a wrapped label matched together. 9 new tests. 8 test documents: values and M-scores identical; operating cash flow of KLBF 2021 and MYOR 2020 moves FOUND → REVIEW (no cross-check passed). Trial 1 M-scores unchanged; APII after fixes −2.576 (development run, not validation) |
| Rule 7 safeguards + Trial 1 fixes (28 Oct 2026) | **328 passed, 1 skipped** | rule 7 (wrong line picked = worst failure): fixed assets on the face must agree with the carrying amount in the PPE note (ERROR otherwise); sections of the statement of financial position must add up to their printed totals; several candidate lines with different amounts = REVIEW; tail of a wrapped label never matched alone; taxes payable only from the table that agrees with the face (prepaid tables skipped, company + subsidiary tables under a grand total); 18 tests in `tests/test_rule7_safeguards.py`, each rule with a negative case. Behaviour on the 8 test documents: values, statuses, flags and M-scores identical; only new passing section checks added. Trial 1 (10 issuers, one per sector): 7 scored provisionally, PTSN awaiting (operating expenses without an operating-profit line, investment property depreciation not read), POLY and ULTJ scanned (not read) |
| App design + downloads (28 Oct 2026) | **298 passed, 1 skipped** | approved design (guest → upload → reading → result); provisional score with assumptions marked ASSUMED (M-06/M-15 replaced "for now", Gail 28 Oct); confirmation moved to the PDF checklist; PDF report and Excel table in ID/EN; issuer from `data/company_master.csv` (unique match only). Reader, engine and the user-decision flows unchanged: behaviour snapshot on the 8 test documents identical to 27 Oct. Browser check on SIDO 2021 (ID and EN), PDF and Excel downloaded |
| Beta: P0-2, bank block, texts (28 Oct 2026) | **291 passed, 1 skipped** | year labels read per statement, score withheld when missing or inconsistent (P0-2); bank/insurer/finance-company statements not scored; Beta label, author credit, approved texts. Behaviour on the 8 test documents identical to the 27 Oct snapshot (values, statuses, flags, M-scores) |
| Bilingual app texts (27 Oct 2026) | **273 passed, 1 skipped** | one ID/EN text catalogue (`wars_scanner/text.py`); 12 new language tests (`tests/test_text.py`). Values, statuses, pages, flags, review items and M-scores on all 8 test documents identical before and after (behaviour snapshot compared field by field) |
| `ae794de` (Phase 3) | **195 passed, 1 skipped** | + injected-error tests. Skipped: `test_digit_slip_is_caught[LK_SIDO_2021.pdf-amortization_intangibles-1000-t]`, because SIDO 2021 amortisation is 0 (UNDISCLOSED) and a digit slip on 0 does not apply |

Document tests run only where the non-case test PDFs are available (`WARS_TEST_PDF_DIR`);
they are identified by SHA-256 in `data/test_documents.csv`.

## App texts: bilingual catalogue (27 Oct 2026)

Every text the user reads comes from `wars_scanner/text.py`: Bahasa Indonesia or English, chosen in
the app. Decisions applied: UI review r1 (Gail 23 Oct, A–E, 1.7, 7.5, language rule), analysis rules
B r1, report design R-01 to R-17 where they concern the app. Each catalogue entry records where its
wording comes from; `text.review_list()` lists the wording **not yet approved** (C6 short drafts and
texts written during implementation). The engine is unchanged (its reason strings are mapped to the
catalogue at display time). Displayed list of driver ratios now follows B r1 §3 (only DSRI, GMI, AQI,
SGI, TATA; push > 0.005); only the −1.78 threshold is shown (M-09 A).

**28 Oct 2026:** app redesigned to the approved canvas; PDF report (`wars_scanner/report_pdf.py`) and
Excel table (`wars_scanner/report_xlsx.py`) built. Texts of the report and Excel marked `new` in the
catalogue await Gail's review (`text.review_list()`).

## Reading-quality controls: APPROVED (M-12 A, Gail, 23 Oct 2026)

These are technical controls on automatic reading (misread unit, digit slip, swapped
columns). They are **not** WARS evaluation rules (S1) and **not** workbook rules. Approved with
the thresholds below. They never change a number and say nothing about the issuer: an ERROR means
the figures **as read** may be wrong, so the score is withheld until checked.

| Control | Rule | Severity | Effect on the M-score | Basis |
|---|---|---|---|---|
| `a_unit_implausible` | total assets × unit outside Rp1 miliar – Rp3.000 triliun | ERROR | Score withheld | Technical control; threshold chosen by Claude |
| `a_part_exceeds_total` | receivables or cash > current assets; tax payable or current maturities > current liabilities; long-term debt > non-current liabilities | ERROR | Score withheld | Extension of workbook `e_impossible_values` |
| `a_part_exceeds_total` (SG&A) | SG&A > revenue | REVIEW | Provisional | Technical control |
| `a_cash_tie` | cash-flow closing cash ≠ balance-sheet cash: equal to the other year's cash (swapped columns) / otherwise different | ERROR / REVIEW | Withheld / provisional | Technical control |
| `a_year_jump` | one year ≥ 5× the other | REVIEW | Provisional | Technical control; 5× chosen by Claude |

## Methodology decisions (`claude/WARS_Methodology_Decisions_r2.md` in the Project)

- **M-01 APPROVED (22 Oct 2026):** owned + ROU depreciation may be the sum of two printed figures (same
  period, entity, basis; both pages recorded; BUILT FROM DISCLOSED COMPONENTS; no subtraction). Already
  the reader's behaviour.
- **M-06 APPROVED (22 Oct 2026):** the non-PPE status is set by the user per year; the machine shows
  evidence only; NONE_PRESENT requires the notes examined; the score is held while NOT ASSESSED.
  **Implemented 23 Oct 2026.**
- **M-14 DECIDED:** no manual correction of values.
- **Approved 23 Oct 2026 (Gail: "Setuju 1–6 dengan catatan Claude"),** recorded in
  `claude/WARS_Methodology_Decisions_r3.md`: Phase D passed (scope: one report); **M-03 A** (FX line
  excluded from amortisation, REVIEW); **M-08 a, b, c** (port workbook `r_standard_transition`,
  `r_standard_transition_other`, `r_comparative_label`; detection from disclosures/labels, never from
  the year); **M-12 A**; **M-15 C with four choices** (Gail, 23 Oct 2026, 11:26: none / goodwill only /
  indefinite lives only / not disclosed; notes or pages examined required; per year; a user who cannot
  decide or who found an unread amount leaves it unset and the score stays held: no manual correction, M-14); **G-06 A** (contract assets out of
  receivables, REVIEW).
- Still PROPOSED: M-02, M-04, M-05, M-07, M-09, M-10, M-11, M-13.

## Other decisions pending (Gail)

- Clarification of `ppe_depreciation_disclosed` = owned + ROU as the sum of two printed figures
  (workbook text says owned + ROU and "always a PRINTED figure").
- KLBF amortisation difference (expense notes > intangible note): kept REVIEW.
- KLBF 2023 foreign-currency line inside the amortisation block: excluded, REVIEW.
- Segment D&A aggregate for TATA: not used.
- Foreign tax: excluded from `taxes_payable` (proposed clarification of D-03).
- Manual correction of values in the app: **not built** (agreed 22 Oct 2026: keep
  Belum dicek / Sesuai / Tidak sesuai; a rejected input withholds the score).

## Known limits

- A whole income statement with both year columns swapped consistently is not caught by the
  cross-checks (only by the header year labels). See `docs/validation.md`.
- Confirmation in the app is the user's own check, not independent verification.
