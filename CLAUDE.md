# Working rules for this repository

Read `docs/WARS_App_Plan_r0.md` first. Owner: Gail (product owner, accountant, verifies
numbers). Claude builds and tests.

## Non-negotiable
1. **No silent wrong number.** Every extracted value is either (a) found and cross-checked,
   (b) flagged for the user to check, or (c) declared not found so the dependent ratio is
   not computed. Never guess, never fill a blank with 0 (0 is a real value).
2. **No fraud verdicts.** Output language is "red flag / needs closer examination". Never
   "fraud detected", never statements about intent. Every result carries the disclaimer.
3. **The workbook is the specification.** `WARS_TrackB_v0_6.xlsx` (project workspace) defines
   formulas and entry rules. Do not change engine behaviour unless the workbook rule changes;
   `tests/test_engine_vs_workbook.py` must stay green.
4. **Evaluation cases are off-limits until Phase 7.** Do not run, test or tune anything on an
   issuer in the case register (kept in the project, outside this repository) before the evaluation
   rules (S1) are locked. Rule
   WR-2 M2 of the project register. Use the non-case test documents in `data/test_documents.csv`.
5. **No source PDFs or case data in git.** PDFs are identified by SHA-256 only.
6. Report test results as they are, including failures and limits.
7. **Wrong line picked = worst failure** (Gail, 28 Oct 2026, after BIRD 2021: the tail of a wrapped label
   "Uang muka pembelian / aset tetap" was read as fixed assets and no check caught it). Every matching rule
   needs a negative test (what it must NOT match), and every field the score uses needs an independent
   cross-check (a second place in the report where the same figure must appear) before it can be FOUND.
   A figure that cannot be cross-checked stays REVIEW. Prefer withholding the score over a plausible wrong number.

## Layout
- `wars_scanner/` – package (`engine.py` = Track B calculation, `parameters.py` = coefficients/thresholds)
- `tests/` – pytest; `tests/fixtures/` holds synthetic workbook fixtures
- `tools/` – one-off scripts (fixture export from recalculated workbook builds)
- `data/golden/` – answer key for the PDF reader (DRAFT until Gail marks VERIFIED)
- `docs/` – plan and specifications
