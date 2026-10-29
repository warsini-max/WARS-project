# PDF reader (Phase 2 face, Phase 2b notes)

`wars_scanner/pdf_reader.py` reads the **face** of the three primary statements of a digital
IDX annual report; `wars_scanner/notes_reader.py` reads the **notes** items the M-score needs.
`wars_scanner/pipeline.py` turns the result into engine input and computes the score. Every
value carries the PDF page and the printed line.

## Face of the statements

1. **Locating the statements (Phase D, 23 Oct 2026): the whole document is searched**, so the
   audited statements are found inside a 300+ page Laporan Tahunan as well as in a standalone
   LK (`locate_financial_statements`, fast text of every page with pypdfium2). A page counts as a
   primary statement only when
   - its heading (top 30% of the page) carries a statement title and none of the excluded titles
     (notes, changes in equity, contents, auditor's report, **financial highlights / ikhtisar**,
     **management discussion / tinjauan keuangan**), and
   - the page shows that it belongs to a statement set: a "Catatan/Notes" column or the "notes form
     an integral part" footer.

   The statement of financial position, profit or loss and cash flows must lie within 15 pages of
   each other, and the notes (CALK) must start within 10 pages after them. **Explicit failure, no
   guessing:** no such set → "audited statements not found" (highlights are never used instead);
   statements without notes → "CALK not found", the score is not calculated. Pages without a text
   layer are counted; scanned statements are still refused (OCR not supported).
2. Text and word positions with `pdfplumber`, **only for the located statement pages**; the notes
   reader starts at the located first notes page.
3. Figures are read **in reading order**, not by column position: on the face of these PDFs
   the figures are not aligned in true columns. The year labels in the header decide which
   figure is t. Note references ("4,32,33", "15a") are skipped; a small bare number is a note
   when it sits under the Notes header and label text when it lies left of the amount area; a
   figure after "Rp" is label text; "-" is nil only in an amount position.
4. Fields are matched on the Indonesian label (multi-line labels are joined).
5. Cross-checks: assets = liabilities + equity; current ≤ total (assets and liabilities);
   revenue − cost of goods sold = gross profit.

## Notes (Phase 2b)

Candidate pages are found with a fast text index of every page (`pypdfium2`); only those
pages are parsed word by word.

**Reading a note table.** In the note tables the figures sit under the year header, so a
figure belongs to a year by **column position** (right edge within 0.6 × the column spacing of
that year's header). Numbers elsewhere on the line ("Pasal 21", "4 (2)", the English label)
are label text, and a line with figures in other columns (a movement table) is not read as a
two-year line. Where the PDF's text positions do not match the print (parts of SIDO 2020), the
line falls back to **reading order**, with two guards: extra leading numbers must look like
label text, and "Pasal 25 17.833" (a label number before a single figure) is not accepted as a
pair. Each line records which method was used.

| Item | Rule | How it is found | Cross-checks (all must pass for FOUND) |
|---|---|---|---|
| `taxes_payable` | D-03: Art. 25 + 29 of the group | The tax-note table that holds Art. 25/29 lines and whose total equals the face "Utang pajak"; may run over two pages and hold Company / subsidiary sub-totals | Lines (without sub-totals) = note total; note total = face. Withholding (4(2), 15, 21, 22, 23, 26), VAT, final tax and "lain-lain" excluded; foreign tax excluded and raised as an issue (PSAK cross-check open point); an unclassified line makes it REVIEW |
| `ppe_depreciation_owned` | D-07 | "Beban penyusutan … dialokasikan/dibebankan" table under the fixed-asset note | Components = total; total = the charge for the year in the movement table of accumulated depreciation |
| `rou_depreciation` | G-23, Q5 | Same kind of table under the right-of-use note | As above; a single line that cannot be reconciled is REVIEW. Not disclosed → blank, never 0 |
| `rou_assets_net` (in the notes) | D-08 | Right-of-use line inside other assets, when the face has none; added to PPE | REVIEW (classification) |
| `amortization_intangibles` | G-22, DP-01/02 (no intangibles found: left blank, M-15 pending) | "Amortisasi tahun berjalan" block under the intangible-asset note | Lines = sub-total (signed). Foreign-currency translation lines inside the block are left out of the amount → REVIEW. Intangibles present but no amount → 0 UNDISCLOSED. Expense notes with a larger "Amortisasi" line → issue (other amortisation, Q2-c) |
| `non_ppe_status`, `depreciation_amortization_non_ppe` | Q6, Q2-c, **M-06 (approved 22 Oct 2026)** | The machine only collects evidence for three groups (investment property, unused/abandoned assets, labelled long-term-cost amortisation): hits with pages, amounts read, and the list of note headings | **Never set by the machine.** NOT ASSESSED → score held. The user sets the status per year (`pipeline.apply_non_ppe_decisions`): NONE_PRESENT needs the notes examined; ALL_DISCLOSED only with an amount read (no manual entry, M-14); PARTIAL_UNDISCLOSED = amount read or 0, REVIEW |
| `ppe_depreciation_disclosed` | G-23 / DP-04 | Built: owned + ROU depreciation when ROU depreciation is disclosed, owned only when it is not | — |
| `depreciation_amortization_total` | DP-01/02 | Built: PPE depreciation + disclosed amortisation + non-PPE D&A, only after the non-PPE status is set; never derived from balances | Engine PPE-depreciation check |

A table whose title says "penyusutan dan amortisasi" (MYOR 2020) is accepted as PPE
depreciation only when its total equals the depreciation charge in the fixed-asset movement
table; otherwise REVIEW.

## Results on the non-case test documents (22 Oct 2026)

| Document | Face checks | Tax note reconciles (note and face) | PPE depreciation = movement table | M-score (PROVISIONAL; values kept in the private project notes) |
|---|---|---|---|---|
| SIDO 2021 | 8/8 | yes | yes | computed; equals the golden-dataset result |
| SIDO 2020 | 8/8 | yes | yes (figures read in order) | computed |
| KLBF 2020 | 8/8 | yes | yes | computed (ROU depreciation 2019 not presented: first PSAK 73 year) |
| KLBF 2021 | 8/8 | yes | yes | computed |
| KLBF 2023 | 8/8 | yes | yes | computed |
| MYOR 2020 | 8/8 | yes | yes | computed (ROU depreciation single line, not reconciled: REVIEW) |
| MYOR 2021 | — | — | — | NOT CALCULATED: statements are scanned images (correct refusal) |

All scores are below the −1.78 threshold. They are PROVISIONAL: inputs marked REVIEW (debt
classification, right-of-use, non-PPE status, amortisation) still need a person's check. Only
SIDO 2021 has a golden dataset (core figures VERIFIED by Gail, 29 Oct 2026).

**Against the SIDO 2021 golden dataset: 40 of 40 numeric fields match, 0 silent errors.**
Independent check: the t−1 figures of the 2021 reports equal the t figures of the 2020
reports for taxes payable, PPE depreciation, ROU depreciation and amortisation (SIDO, KLBF).

## Status of each output

`FOUND` read and reconciled; `REVIEW` needs judgement or could not be reconciled;
`UNDISCLOSED` (amortisation not disclosed, 0 = nothing disclosed); `BUILT FROM DISCLOSED
COMPONENTS`; `NOT DISCLOSED` (blank on purpose); `NOT FOUND`; `STATEMENT NOT FOUND`.

## Known limits

- Tuned on three issuers in two subsectors. New issuers will bring new table layouts; each
  new test document must be run before claims are made.
- Long-term debt and current maturities are label-based candidates on the face, always
  REVIEW (D-01, D-02).
- No OCR: scanned statements are refused, never guessed.
- English-only reports, non-IDR reports and banks are not supported.
- Reading time 5–15 s per report; a 354-page test annual report ±5 s (only the statement block and
  the note pages needed are read word by word).
- **No real annual report has been tested yet.** Phase D was tested on assembled 300+ page
  documents (generated front matter with highlight traps + the real SIDO/KLBF statements); a real
  Laporan Tahunan from a non-case issuer must still be run.
- The segment-note D&A aggregate is not used (open rule question).
- **ROU presented within fixed assets** (PSAK 116 ¶47(a)(i); approved for closing by Gail, 23 Oct 2026): when
  the fixed-asset note itself shows an ROU class row in its movement table, or says that fixed assets include
  right-of-use assets, the ROU carrying amount and the ROU depreciation table are **not added again** (status
  `INCLUDED IN PPE`; PPE and PPE depreciation REVIEW). 'Hak Guna Bangunan/Usaha' (land titles) and
  reclassification rows are not ROU. No test document presents ROU this way: tested on constructed pages, and
  no detection on the seven real test documents.
