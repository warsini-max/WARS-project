# Cross-checks and confirmation (Phase 3)

`wars_scanner/validation.py` runs after the reader. It never changes a number; it raises
**ERROR** (red: the M-score is not shown, as the workbook's `m_score_usable` = N) or **REVIEW**
(yellow: may be legitimate, a person must look).

## Workbook checks (ported from `WARS_TrackB_v0_6.xlsx`, same rule and severity)

| Code | Rule | Severity |
|---|---|---|
| `e_impossible_values` | current liabilities > total liabilities; amortisation > D&A total; non-PPE D&A < 0 or > D&A − amortisation (Pair_Validation); current assets + PPE > total assets (Validation_Checks) | ERROR |
| `r_negative_values` | a negative input or a negative gross profit | REVIEW |
| `r_unusual_yoy_change` | \|t / t−1 − 1\| > `yoy_change_threshold` (1.0) for revenue, receivables, COGS, SG&A, total assets, PPE | REVIEW |
| `r_amort_undisclosed` | amort_status UNDISCLOSED (G-22) | REVIEW |
| `r_rou_dep_missing` | ROU assets > 0 without ROU depreciation (G-23) | REVIEW |
| `r_non_ppe_partial` | non-PPE status PARTIAL_UNDISCLOSED (Q6) | REVIEW |
| PPE depreciation check | engine (`ppe_dep_check`) | NOT CALCULATED on MISMATCH |

## App checks (added for automatic reading): PROPOSED, decision pending

Technical controls on automatic reading, not WARS evaluation rules and not workbook rules.
Active until decided (see `docs/STATUS.md`); the thresholds are Claude's choices.

| Code | Catches | Severity |
|---|---|---|
| `a_unit_implausible` | total assets × unit outside Rp1 miliar – Rp3.000 triliun: unit misread | ERROR |
| `a_part_exceeds_total` | receivables or cash > current assets; tax payable or current maturities > current liabilities; long-term debt > non-current liabilities (ERROR); SG&A > revenue (REVIEW) | ERROR / REVIEW |
| `a_year_jump` | one year ≥ 5× the other for any input: digit or unit slip | REVIEW |
| `a_cash_tie` | closing cash in the cash-flow statement ≠ balance-sheet cash. Equal to the *other* year's cash → columns swapped (ERROR); otherwise REVIEW (can be legitimate: overdrafts, disposal groups) | ERROR / REVIEW |

On the six digital test reports: no ERROR. REVIEW raised by the app checks: KLBF 2020 cash tie
for 2019 (the cash-flow statement deducts a separate line; legitimate, to be confirmed) and
KLBF 2020 current maturities 2020 vs 2019 (first PSAK 73 year).

## Injected-error test (Phase 3 completion criterion)

`tests/test_validation.py` takes the real reader output for SIDO 2021 and KLBF 2021 and
injects: wrong unit (3 cases), balance-sheet columns swapped (2), one line swapped (1), a missing
value (8), a digit slip ×10 or ×1000 on 12 fields (24, one not applicable because the value is 0),
a wrong sign (3), a year-on-year change just above and below the workbook threshold.
**All are caught as yellow or red.**

**Not caught (known limit):** the whole income statement with its two columns swapped together
(revenue, COGS and expenses all moved consistently). The cross-checks cannot see it; only the
year labels in the header protect against it. A check against the prior-year report (when the
user uploads both) would catch it: planned.

## Confirmation screen

Every yellow item (a REVIEW input or a REVIEW cross-check) is listed with its reason; the user
marks it *Belum dicek / Sesuai / Tidak sesuai* and enters a name. States:

- any item *Tidak sesuai* → the score is withheld ("tidak boleh dipakai");
- items still unchecked → SEMENTARA, with the count;
- all confirmed → "dikonfirmasi pengguna (bukan verifikasi independen)".

The confirmations and the reviewer's name are included in the CSV download. Correcting a
value in the app is not possible yet (decision pending).
