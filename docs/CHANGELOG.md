# Changelog

Entries from 13 Nov 2026 onward (change control of Gail's decision of 13 Nov 2026 16.46). Earlier history: the
register in the project (`WARS_Register_Persetujuan_Gail_r0.md`) and `docs/STATUS.md`.

Each entry says what was **approved**, what is **implemented**, what is **tested**, and what stays **open**.

## Branch `v1/p0` (from `7cc725e`; not in the guest app)

### P0-1 – score gate and invariants

- **Approved:** Gail 13 Nov 2026 16.46 (authorisation P0-1; INV-1..4, INV-10, INV-P; REG-HOPE25, REG-PURI22, REG-CTTH22).
- **Implemented:**
  - `wars_scanner/gate.py` (new): an input that needs the user (any non-FOUND status, and every risk field) and has
    no card on the review screen withholds the M-score ("WITHHELD (inputs not covered by the review step)").
  - INV-3 normalisation: a value-claiming status with no value (e.g. REVIEW with value None) becomes NOT FOUND.
  - `check.items`: a gate field with no value now gets a "missing" card (the branch marked "handled below" had no
    handler; HOPE 2025 PPE depreciation had no card at `7cc725e`).
  - `report.verdict`: the withheld reason names the items. New text key `v.held_gate` (awaiting Gail's review).
  - `app.analyse` and `check.apply` enforce the gate.
- **Tested (commit `3518fea`):** test_gate 12 passed (incl. INV-P, 10,000 combinations); REG-HOPE25, REG-PURI22,
  REG-CTTH22 passed; full suite 568 passed, 1 skipped (pre-existing SIDO amortisation 0); test_engine_vs_workbook green.
  Regression 96 non-case pairs x 2 paths vs `7cc725e`: 0 value, 0 M-score, 0 shown/withheld changes, 0 gate blocks;
  +1 card (HOPE 2025 XBRL, PPE depreciation); 45 status changes REVIEW -> NOT FOUND, all with value None (44 PDF-path
  long-term debt / current maturities in 22 pairs, 1 HOPE).
- **Visible change:** those 45 lines are labelled "not found" instead of "review" in the app and report (they had no
  value either way; the card was already there except HOPE).
- **Open:** text `v.held_gate` waits for Gail's review.

### P0-2 – evidence ledger (shadow mode)

- **Approved:** Gail 13 Nov 2026 16.46 (K1 = B, K2 = B, K5 = A, K6 shadow mode).
- **Implemented:** `wars_scanner/ledger.py` (new); `tools/ledger_compare.py` (new). CLAUDE.md rule 7 revised (K1 = B).
- **Shadow only:** the ledger never changes value, status, card, score or report (K6). Proposed statuses are recorded
  next to the old ones with the reason ("K1-B", "K2-B", "K5-A").
- **Tested:** test_ledger 12 passed (C-LAB, C-REC SGA block and families, each with negatives; K6 invariance);
  REG-LEDGER-APP (app.analyse on HOPE 2025: ledger attached, values/statuses/cards/score identical).
  `tools/ledger_compare.py` over 99 non-case pairs (Tahap 1-9, 1_v2, 7_2025), both paths: 0 K6 violations, 0 errors.
  - XBRL path: 179 of 3,756 rows would change status (K5-A 92, K2-B 49, K1-B 38); fields that would need a new card:
    77 (0.80 per readable pair).
  - PDF path: 82 of 3,726 rows (K5-A 62, K2-B 20); new card fields 41 (0.43 per readable pair).
  - The 6 known wrong non-risk FOUND values (APEX 2025 X SGA, MTLA 2025 P SGA, MERK 2025 P SGA; t and t1) are all
    proposed REVIEW. **Not independent:** the corroboration rules were tuned on Tahap 6-9.
- **Open:** operational use of the proposed statuses (next P0 stages); K2-R1..R3 (`WARS_K2_Conflict_Map_r0.md`) need
  explicit authorisation.

### Feedback and Suggestions (PDF report)

- **Approved:** Gail 13 Nov 2026 17.23 (wording EN and ID, to be used exactly).
- **Implemented (`1604f95`):** `rep.feedback.title` / `rep.feedback.body`; section after the disclaimer on the last page.
  No new link: the footer envelope icon already links to `mailto:` + `CONTACT_EMAIL` (same value as `app.py`).
- **Tested:** `tests/test_report_feedback.py` 8 passed; page counts unchanged for 5 reports x 2 languages.
- **Open:** the ID footer label is "Hubungi kami" while the approved text says "Contact Us" (Gail to decide).

### Right-of-use asset not from the deferred tax table (`e9dd578`)

- **Problem:** MTLA 2025 (PDF path) PPE included 'Aset hak guna (598)' from the deferred tax breakdown.
- **Implemented:** candidate lines under a deferred tax heading are skipped (`notes_reader`).
- **Tested:** REG-MTLA25-PDF; regression: only MTLA 2025 changes (PPE 839,194 -> 838,596 in the PDF path;
  M -0.22160 -> -0.22159).

### P0-3 / P0-4 – shadow acceptance sets (`e51ec9d`)

- **Approved:** K1 = B, K5 = A (Gail 13 Nov 2026 16.46).
- **Implemented:** POS-X1..X3, NEG-X1..X7, POS-A1..A2, NEG-A1..A5 as ledger unit tests; C-LAB uses line amounts only;
  labels wrapped below the amounts.
- **Tested:** test_ledger 20 passed; full suite 605 passed, 1 skipped; ledger_compare 0 K6 violations.
- **Open:** card-increase threshold (criterion of P0-3, not yet set); P0-5 (operational `decide`) needs Gail's review
  of the differences; NEG-A6/A7 belong to the depreciation reader (P1).

## Release to the guest app – 14 Nov 2026 (`c2dd81b`, main = dev = v1/p0)

Gail 14 Nov 2026 06.40 ("oke 1-4"), before pausing the project:
1. **P0-5 first group:** SGA without proven completeness (K5-A) is REVIEW with card `chk.r.k5_sga`.
2. P0-1 (score gate), P0-2 (ledger, shadow), MTLA right-of-use fix, D3/D4 tools.
3. Methodology item 5 (`beta.limits`) rewritten after Tahap 9.
4. Footer label 'Hubungi Kami' / 'Contact Us'; the ID feedback text refers to 'Hubungi Kami'.

- **Tested:** full suite 613 passed, 1 skipped (pre-existing SIDO amortisation 0); test_engine_vs_workbook green.
  Regression 96 non-case pairs x 2 paths against the previous guest (`7cc725e`): values unchanged except MTLA 2025
  PDF path PPE (839,194 -> 838,596); M unchanged except MTLA PDF (-0.22160 -> -0.22159), no zone change;
  SGA FOUND -> REVIEW in 8 pairs (XBRL path; +6 cards) and 12 pairs (PDF path; +12 cards); HOPE +1 card;
  45 empty debt/depreciation lines REVIEW -> NOT FOUND.
- **Checked by hand:** the SGA cards of APEX (X), MTLA (P), MERK (P): amount, components and page. The other 15 new
  SGA cards: amount unchanged, components and page extract not checked one by one.
- **Open:** EN translations of the two new texts (Gail's ID wording); K5-A receivables and PPE; K1-B; K2-R1..R3; K8;
  D3/D4; P1.
