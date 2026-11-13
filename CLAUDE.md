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
   needs a negative test (what it must NOT match), and every field the score uses needs corroboration before it
   can be FOUND. **Revised 13 Nov 2026 (Gail, K1 = B):** corroboration must be able to catch the kind of error it
   is meant to control - identity of the line/account, period (year column), completeness of components, magnitude,
   sign and scale - kept apart. A second appearance of the same figure in the same report (found by its number) shows
   presence, period and magnitude only; it is never by itself proof of identity or completeness, and two appearances
   in one document are not automatically independent. XBRL is not a source of truth. Composite items need proven
   completeness (K5 = A). Evidence kinds and the policy per field: `WARS_Evidence_Policy_Matrix_r0.md`.
   (Previous wording, 28 Oct 2026: "an independent cross-check (a second place in the report where the same
   figure must appear)".) A figure that cannot be corroborated this way stays REVIEW. Prefer withholding the score
   over a plausible wrong number.
8. **Never skip anything that touches WARS accuracy** (Gail, 11 Nov 2026 13.34: "JANGAN PERNAH MELEWATKAN APAPUN
   YANG MELIBATKAN AKURASI WARS", after LRNA 2025 showed three faults that the stage 7 and 8 targets did not
   measure). Every test stage and every release goes through the full accuracy checklist, not only "no wrong
   FOUND value": (a) every score input against the PDF; (b) both paths, XBRL + PDF and PDF only; (c) every
   review-step card: amount, components, and that the page extract shows them; (d) the report's conclusion:
   findings and "no findings" consistent with the indices, ratios with a sign or denominator that makes them
   meaningless (e.g. a negative gross margin) flagged; (e) the per-issuer result texts. A passed target is
   reported as exactly what it measured, never as "WARS is accurate".

## Layout
- `wars_scanner/` – package (`engine.py` = Track B calculation, `parameters.py` = coefficients/thresholds)
- `tests/` – pytest; `tests/fixtures/` holds synthetic workbook fixtures
- `tools/` – one-off scripts (fixture export from recalculated workbook builds)
- `data/golden/` – answer key for the PDF reader (DRAFT until Gail marks VERIFIED)
- `docs/` – plan and specifications
