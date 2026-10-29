# Phase D acceptance evidence: real KLBF 2021 annual report

**Date:** 23 Oct 2026. **Run by:** Claude. **Status:** PASSED (Gail, 23 Oct 2026) for this one annual report. Produced by `tools/accept_real_annual_report.py` (unchanged reader, commit
`3ab69dc` reader code = Phase D `f376e04`). The PDF is not in git (CLAUDE.md rule 5); it is identified by SHA-256.

## Source of the annual report

- **Official source URL (supplied by Gail, 23 Oct 2026):** <https://www.kalbe.co.id/api-content/File/GetFile/AR%20Kalbe%20Tbk%202021.pdf> (PT Kalbe Farma Tbk website).
- The file tested is the one Gail downloaded and attached; SHA-256
  `4b0ff160e5515e17d813b3fa387f094a1c382612c537de64ae7dea8d10d7e02b`, 470 pages, 10,707,144 bytes.
- **URL checked (23 Oct 2026, web reader):** the link opens the Kalbe Farma annual report; cover "LAPORAN
  TAHUNAN 2021 ANNUAL REPORT"; table of contents lists "Laporan Keuangan Konsolidasi" at printed page 290.
  Listed on Kalbe's investor page <https://www.kalbe.co.id/id/investor/annual-report/annual-report> (Gail);
  that page loads its list by script, so the listing itself could not be read.
- **Hash not re-verified by Claude:** the build environment cannot reach kalbe.co.id (proxy refused), so the URL
  was not downloaded again to compare the hash. Anyone re-downloading can compare against the hash above.
- **Decision (Gail, 23 Oct 2026):** Phase D PASSED for this one annual report; scope limit as stated below.

## Additional evidence (beyond the tool output below)

- **Pages carrying a statement title that were NOT accepted** (criterion 1, 4):
  - p8, p160, p166: "Ikhtisar Kinerja / Performance Highlights": rejected by the heading exclusion.
  - p153: MD&A table headed "laporan posisi keuangan": heading not excluded, rejected because the page has
    no Notes column and no "integral part" footer (the second safeguard).
  - p4, p295: tables of contents: rejected by the heading exclusion.
  - p333–p432 (13 pages): notes pages that mention a statement title: rejected ("Catatan atas").
- **Embedded LK:** 162 of the 163 LK pages have identical text at a constant offset of 292 pages. The one
  difference (LK p132 / AR p424, notes) is word order in the text layer only, same words; not a source page.
- **M-score** after the same simulated non-PPE decision (NONE_PRESENT both years): identical for the annual report and the stand-alone financial statements.
- **Resources:** 470 pages, 10.2 MB; full pipeline 6.9 s; peak memory 368 MB (this test process).
- **Regression:** 215 passed, 1 skipped (SIDO 2021 amortisation is 0: digit-slip test not applicable).

## Tool output

# Phase D acceptance: AR_KLBF_2021.pdf

- Annual report: `AR_KLBF_2021.pdf`, 470 pages, SHA-256 `4b0ff160e5515e17d813b3fa387f094a1c382612c537de64ae7dea8d10d7e02b`
- Reference LK: `LK_KLBF_2021.pdf`, SHA-256 `1a4e53e378962add8198beaa10f3d7449ab50122d4ac3728f978a8635198be71`
- Issuer expected: PT Kalbe Farma Tbk; fiscal year expected: 2021
- Pages without a text layer: 4 (e.g. [290, 294, 296, 297])

## Candidates and blocks (criterion 4)

- Candidate pages: {'position': [298, 299, 300], 'profit_loss': [301, 302], 'cash_flow': [304, 305]}
- Blocks: [{'position': [298, 299, 300], 'profit_loss': [301, 302], 'cash_flow': [304, 305], 'notes_start': 306}]
- Chosen: {'position': [298, 299, 300], 'profit_loss': [301, 302], 'cash_flow': [304, 305], 'notes_start': 306}

  - block at p298: notes_start=306, parent-only wording=False, head: THE ORIGINAL CONSOLIDATED FINANCIAL STATEMENTS INCLUDED HEREIN ARE IN THE INDONESIAN LANGU

## Checks

| Check | Result | Detail |
|---|---|---|
| PDF unchanged by the reader | PASS |  |
| statements located | PASS | {'position': [298, 299, 300], 'profit_loss': [301, 302], 'cash_flow': [304, 305], 'notes_start': 306} |
| notes (CALK) located | PASS | p306 |
| exactly one complete block (else the choice must be explained) | PASS | 1 block(s) |
| chosen pages are not highlights / MD&A | PASS |  |
| issuer name on the statement of financial position | PASS | KALBE FARMA |
| fiscal year read = expected | PASS | read 2021 |
| basis = consolidated (reader) | PASS | read Consolidated |
| chosen statements are not parent-only | PASS |  |
| same issuer/year/basis as the reference LK | PASS | AR (2021, 'Consolidated', 'Units') vs LK (2021, 'Consolidated', 'Units') |
| values, statuses and quotes equal the reference LK | PASS | 48 values (40 numeric); all equal |
| each quote's figures are on the reported annual-report page | PASS |  |
| one constant page offset (statements embedded whole) | PASS | {292: 58} |
| printed page number of every source page = the LK's | PASS | 8 source pages |

## Printed page vs file page (every page a value was read from)

| File page (AR) | File page (LK) | Printed page (AR) | Printed page (LK) |
|---|---|---|---|
| 298 | 6 | 1 | 1 |
| 299 | 7 | 2 | 2 |
| 301 | 9 | 4 | 4 |
| 304 | 12 | 7 | 7 |
| 388 | 96 | 91 | 91 |
| 394 | 102 | 97 | 97 |
| 396 | 104 | 99 | 99 |
| 411 | 119 | 114 | 114 |

## Reader issues (AR)

- short-term bank loans excluded from current maturities (D-02): Utang bank jangka pendek - 18 220.500.000.000 Short-term ban (REVIEW: confirm none is a current portion of long-term debt)
- expense notes show 'Amortisasi' of 36.910.520.336 / 40.000.280.714 (p428,429), more than the intangible amortisation 21.663.837.089 / 39.814.259.965: other assets may be amortised (non-PPE D&A, Q2-c). REVIEW

**Result: ALL CHECKS PASS**