# WARS Scanner: Window-dressing Accounting Red-Flag Scanner

By **Warsini** · [LinkedIn](https://www.linkedin.com/in/warsiniak)

**Status: beta.** Development stopped at beta on 4 November 2026: the last blind test did not meet the targets
set before it was run (see [Known limitations](#known-limitations)). The app runs end to end (continue as guest →
upload → reading → review step → result → PDF report and Excel table) in Bahasa Indonesia and English. See
[docs/STATUS.md](docs/STATUS.md).

WARS Scanner reads the audited annual financial statements of a company listed on the Indonesia
Stock Exchange (IDX), computes the eight Beneish (1999) indices and the M-score, and shows which
ratios raise the score. Every figure it uses is traced to the page and the line of the report it
was read from.

> **A red flag is not a finding of fraud.** The M-score is a screening model. A score above the
> threshold means the reported figures warrant closer examination. It is not evidence of fraud or
> misstatement, says nothing about intent, and does not replace examination procedures. Not for
> banks, insurers or other financial institutions.

*Ringkas (ID): aplikasi penyaring red flag berbasis Beneish M-score untuk laporan keuangan emiten
BEI, dalam Bahasa Indonesia dan Inggris. Hasilnya tanda untuk pemeriksaan lebih lanjut, bukan
kesimpulan tentang kecurangan.*

## How it works

1. **Upload** the digital PDF of the audited financial statements (an annual report that contains
   the full statements also works) and, optionally, the IDX XBRL instance (`instance.zip`, FY2022
   onwards). Scanned PDFs are refused with the reason.
2. **Reading.** With XBRL, the figures on the face of the statements come from the XBRL instance and
   each one is reconciled to the PDF; note figures (corporate income tax payable, depreciation, right
   of use assets, amortisation) are read from the PDF, anchored to XBRL. Without XBRL, the PDF reader
   finds the three primary statements in the whole document and reads both years from the one report.
   Statements of banks, insurers and finance companies are recognised and not scored.
3. **Checks.** A figure is FOUND only when it is cross-checked in a second place of the report.
   Reading-quality checks look for a wrong unit, swapped year columns or a digit slip; the score is
   withheld if the year labels are missing or disagree, or if the PDF statements cannot be read.
   A figure that is not found is never filled in, so the score is not calculated.
4. **Review step.** Score inputs that could not be cross-checked are shown one by one with an extract
   of the source page. The user agrees with the reading or types the amount from the report; amended
   amounts are cross-checked again and recorded as user confirmed or user amended. The user may skip
   the step and download the report without a score.
5. **Result and downloads.** The M-score against the −1.78 threshold, the ratios that raise it with the
   figures and pages behind them, and the eight indices. A PDF report (findings, score breakdown, a
   checklist of every figure to check against its source page, cross-checks, methodology and
   limitations) and an Excel table of all figures with their pages and source lines. Where the notes
   are silent (for example, amortisation not found), the app uses 0 under the workbook rule, marks it as
   an assumption and labels the result provisional. User confirmation is not independent verification.

## Design principles

- **No silent wrong number.** Every value is found and cross-checked, marked for review, or declared
  not found, in which case the score is not calculated. A blank is never filled with 0.
- **Screening language only.** No fraud verdicts, no statements about intent, the disclaimer on
  every screen.
- **The workbook is the specification.** The calculation engine is a line-by-line port of the
  project workbook (`WARS_TrackB_v0_6.xlsx`) and matches it on 95 synthetic test pairs.
- **One text catalogue, two languages.** Every sentence the user reads comes from
  `wars_scanner/text.py`, written directly in Bahasa Indonesia or British English, with the same
  figures in both.

## Model

- Beneish (1999), unweighted probit, 8 variables; coefficients as published.
- Threshold shown: −1.78 (Beneish 1999). At this threshold the model missed 26% of manipulators in
  the estimation sample and 50% in the holdout sample, and flagged 13.8% and 7.2% of
  non-manipulators. These rates come from the original US sample; the model has not been validated
  on IDX companies.
- One report per score: the current year and the comparative year both come from the same audited
  statements.

## Tested on

- PDF reader: digital audited statements of three IDX companies in two subsectors (pharmaceuticals, food)
  for 2020–2023, one 470-page annual report, and cross-sector trials of about 50 IDX companies.
- XBRL path: blind stages 3 to 6, 10 IDX companies each (one per sector, drawn at random, FY2022), with
  the code frozen before the files were opened and every score input checked by hand against the PDF.

Test documents are identified by SHA-256 in `data/test_documents.csv` and the project record; source
PDFs are not stored in this repository.

## Known limitations

**Blind test results on the XBRL path** (targets: no FOUND value wrong; every wrong input shown in the
review step or the score withheld):

| Stage | FOUND values wrong | Main cause | Score not withheld |
|---|---|---|---|
| 3 | 0 (face figures only; notes not yet read) | – | not comparable |
| 4 | 7, in 3 companies | right-of-use depreciation missing; amortisation counted as depreciation; lease liabilities tagged as "other" liabilities | 9 of 10 |
| 5 | 4, in 2 companies | untagged financing and lease lines in interest-bearing debt | 8 of 10 |
| 6 (last) | 2 of 261, in 1 company | heading of the current-maturities block wrapped over lines, so a lease line was read as non-current | 6 of 10 |

The effect of the wrong values on the scores shown in stage 6 was under 0.03, with no change of zone
against −1.78. The targets were nevertheless missed, and development stopped at beta under a rule
agreed before the last stage.

After stage 6, three gaps found by it were closed without a new test stage: the score is withheld when the
PDF statements cannot be read (one of the six scores above), amortisation and non-PPE depreciation marked for
review now appear in the review step, and the review text for PPE no longer states that right-of-use assets
are included.

**Known causes of wrong or unread figures**

- The reader works line by line: labels and headings wrapped over several lines can be matched to the
  wrong item.
- Statement pages that are images cannot be read (no OCR); the score is then withheld.
- In some PDFs the text layer prints the year columns in a different order from the page; the check of a
  figure pair on one line cannot tell the years apart in such files.
- Amortisation disclosed only in a sentence, and depreciation of assets other than PPE that the notes do
  not state, are counted as 0 and listed as assumptions.
- Corporate income tax payable (PPh 25/29) is found in 3 to 4 of 10 reports; otherwise total taxes
  payable is used as an approximation and marked for review.
- Interest-bearing debt is identified from labels and XBRL tags; whether a related-party loan bears
  interest is not read.
- Without XBRL, the PDF reader withholds the score for most reports.
- Not supported: scanned PDFs, English-only reports, banks, insurers and finance companies.

## Run the app

```bash
pip install -r requirements-lock.txt
streamlit run app.py
```

Windows, step by step: [docs/run_locally_windows.md](docs/run_locally_windows.md).
Uploads are limited to one PDF of up to 50 MB (`.streamlit/config.toml`). The fonts in `static/fonts` and
`assets/fonts` (Source Sans 3, Source Serif 4, Source Code Pro, by Adobe) are used under the SIL Open Font
License (the `LICENSE-*.md` files next to them).

## Run the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

Phase status and test evidence: [docs/STATUS.md](docs/STATUS.md).
Reader: [docs/pdf_reader.md](docs/pdf_reader.md) · Checks: [docs/validation.md](docs/validation.md) ·
Engine: [docs/engine_spec.md](docs/engine_spec.md).
