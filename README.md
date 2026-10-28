# WARS Scanner: Window-dressing Accounting Red-Flag Scanner

By **Warsini** · [LinkedIn](https://www.linkedin.com/in/warsiniak)

**Status: beta, under construction.** The app runs end to end (continue as guest → upload → reading →
result → PDF report and Excel table) in Bahasa Indonesia and English. See [docs/STATUS.md](docs/STATUS.md).

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
   the full statements also works). Scanned PDFs are refused with the reason.
2. **Reading.** The app finds the three primary statements in the whole document (financial
   highlights and management discussion are not used), reads both years from the one report, and
   reads the notes the model needs: corporate income tax payable, depreciation, right of use assets,
   amortisation. Statements of banks, insurers and finance companies are recognised and not scored.
3. **Checks.** Every note figure is reconciled to a total, to the primary statements or to the
   movement schedule. Reading-quality checks look for a wrong unit, swapped year columns or a
   digit slip; the year columns are taken from the year labels printed in each statement's heading,
   and the score is withheld if they are missing or disagree. A figure that needs judgement is marked yellow; a figure that is not found is never
   filled in, so the score is not calculated.
4. **Provisional result.** The M-score against the −1.78 threshold, the ratios that raise it with
   the figures and pages behind them, and the eight indices. Where the notes are silent (for
   example, no intangible assets found), the app uses the amount read or 0 under the workbook rule
   and marks it as an assumption; the result is labelled provisional.
5. **Downloads.** A PDF report (findings with possible non-manipulative explanations and areas for
   examination, score breakdown, a checklist of every figure to check against the source page,
   figures read, cross-checks, methodology) and an Excel table of all figures with their pages and
   source lines. The user ticks each checklist item as matching the report or not; one "does not
   match" means the score cannot be used. User confirmation is not independent verification.

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

Digital audited statements of three IDX companies in two subsectors (pharmaceuticals, food) for
2020–2023, plus one 470-page annual report. Test documents are identified by SHA-256 in
`data/test_documents.csv`; source PDFs are not stored in this repository.

## Run the app

```bash
pip install -r requirements-lock.txt
streamlit run app.py
```

Windows, step by step: [docs/run_locally_windows.md](docs/run_locally_windows.md).
Uploads are limited to one PDF of up to 50 MB (`.streamlit/config.toml`). The IBM Plex fonts in
`static/fonts` and `assets/fonts` are used under the SIL Open Font License (`OFL.txt`).

## Run the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

Phase status and test evidence: [docs/STATUS.md](docs/STATUS.md).
Reader: [docs/pdf_reader.md](docs/pdf_reader.md) · Checks: [docs/validation.md](docs/validation.md) ·
Engine: [docs/engine_spec.md](docs/engine_spec.md).
