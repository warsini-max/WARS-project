# Engine specification (Track B)

Source of truth: `WARS_TrackB_v0_6.xlsx` (project workspace), sheets `Pair_Inputs`
(derived columns) and `Beneish_Pair_Calculation`. `wars_scanner/engine.py` ports them
formula by formula.

## Inputs (one report, columns t and t−1)

Required, 14 per year (all must be numbers):

| Field | Meaning (short; full rules in the workbook Data_Entry_Guide) |
|---|---|
| revenue | Net sales / revenue from main operations |
| accounts_receivable | Trade receivables, net (third parties + related parties) |
| cost_of_goods_sold | Cost of goods sold / cost of revenue |
| selling_general_administrative_expenses | Selling + general & administrative expenses |
| total_assets | Total assets |
| current_assets | Total current assets |
| property_plant_equipment_net | PPE net, including right-of-use assets (D-08) |
| depreciation_amortization_total | D&A charge of the year (flow), all classes |
| amortization_intangibles | Amortisation of intangible assets only |
| current_liabilities | Total current liabilities |
| long_term_debt | Interest-bearing long-term debt, net of current portion |
| current_maturities_long_term_debt | Current portion of long-term debt |
| cash_and_cash_equivalents | Cash and cash equivalents |
| taxes_payable | Corporate income tax payable only |

Also used: `depreciation_amortization_non_ppe_*` and `non_ppe_status_*`
(NONE_PRESENT / ALL_DISCLOSED / PARTIAL_UNDISCLOSED), `ppe_depreciation_disclosed_*`,
`rou_assets_net_*`, `rou_depreciation_*`, `amort_status_*`, `doc_version`,
`statement_type`, `reporting_currency`, `unit_scale`, `mixed_source_fields`;
optional `net_income_t`, `cash_flow_from_operations_t`, `income_before_extraordinary_items_t`
(comparators only, not in the M-score).

## Derived values

- `gross_profit = revenue − cost_of_goods_sold` (both numbers, else "").
- `depreciation_expense = D&A total − amortisation of intangibles − non-PPE D&A`, only when
  the non-PPE status is assessed, the PPE check is not MISMATCH, and all three are numbers.
- `ppe_dep_check`: compares `depreciation_expense` with the disclosed PPE depreciation
  (tolerance 1 unit): OK / MISMATCH / NOT CHECKABLE / NOT PROVIDED.
- `required_inputs_complete`: 14 numbers AND (disclosed PPE depreciation is a number OR
  (amortisation status is not "UNDISCLOSED" AND not (ROU > 0 with no ROU depreciation))).

## Indices and score

DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI and TATA (working-capital accruals:
ΔCA − ΔCash − (ΔCL − ΔCurrent maturities − ΔTax payable) − D&A, divided by total assets).
M = −4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI
+ 4.679·TATA − 0.327·LVGI. No score unless all eight indices are numbers.

A pair is not calculated (with the reason stated) when: the document is not the first-issued
version; a MIXED_SOURCE value is present; ticker/year are invalid; the basis is not specified;
a required input is missing; non-PPE D&A is not assessed; or the PPE depreciation check fails.

## Spreadsheet semantics kept on purpose

Blank input = 0 in arithmetic but not a number for ISNUMBER/COUNT; a formula "" is text and
makes arithmetic an error; errors propagate and ISNUMBER(error) is FALSE.

## Not ported yet

| Workbook part | Plan |
|---|---|
| `Pair_Validation` and `m_score_usable` | Phase 3 (cross-checks) |
| Duplicate and prior-row checks across many rows | Not needed for a single upload; the caller can pass `duplicate_count` |
| `Pair_Sensitivity_MS`, `Pair_Sensitivity_ROU`, `TATA_Sensitivity` | Later, as optional detail views |
| Track A (`Beneish_Calculation`, two reports per score), `EarlyWarning_Features` | Not in the app scope |

## Test coverage and known gaps

- `tests/test_engine_vs_workbook.py`: 95 synthetic pairs, 53 columns each, against
  LibreOffice-recalculated values (75 OK pairs, 20 NOT CALCULATED pairs of 5 kinds).
- `tests/test_engine_reference.py`: OK pairs against an independent textbook implementation.
- Gaps: no fixture sits on the PPE-check tolerance boundary (a change from 1 to 0 units is not
  detected); no fixture produces a spreadsheet error value, so the error-propagation path is
  not exercised by workbook data.
