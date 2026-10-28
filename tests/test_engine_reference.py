"""Cross-check against an independent, textbook implementation of the Beneish (1999) model.

The workbook comparison (test_engine_vs_workbook.py) proves that the engine matches the
workbook. This test guards against the engine and the workbook sharing the same mistake:
the indices are recomputed here directly from the published definitions.
"""
import json
import math
from pathlib import Path

from wars_scanner.engine import calculate

CASES = [c for c in json.loads((Path(__file__).parent / "fixtures" / "workbook_v06_synthetic.json")
                               .read_text())["cases"]
         if c["expected_calculation"]["calc_status"] == "OK"]


def textbook(p):
    t = lambda f: p[f + "_t"]            # noqa: E731
    q = lambda f: p[f + "_t1"]           # noqa: E731
    dep = lambda g: g("depreciation_amortization_total") - g("amortization_intangibles") - g("depreciation_amortization_non_ppe")  # noqa: E731
    gm = lambda g: (g("revenue") - g("cost_of_goods_sold")) / g("revenue")  # noqa: E731
    aq = lambda g: 1 - (g("current_assets") + g("property_plant_equipment_net")) / g("total_assets")  # noqa: E731
    rate = lambda g: dep(g) / (dep(g) + g("property_plant_equipment_net"))  # noqa: E731
    lev = lambda g: (g("current_liabilities") + g("long_term_debt")) / g("total_assets")  # noqa: E731
    d = lambda f: t(f) - q(f)  # noqa: E731
    idx = {
        "DSRI": (t("accounts_receivable") / t("revenue")) / (q("accounts_receivable") / q("revenue")),
        "GMI": gm(q) / gm(t),
        "AQI": aq(t) / aq(q),
        "SGI": t("revenue") / q("revenue"),
        "DEPI": rate(q) / rate(t),
        "SGAI": (t("selling_general_administrative_expenses") / t("revenue"))
        / (q("selling_general_administrative_expenses") / q("revenue")),
        "LVGI": lev(t) / lev(q),
        # Working-capital accruals definition (Beneish 1999), as used by the workbook.
        "TATA": ((d("current_assets") - d("cash_and_cash_equivalents"))
                 - (d("current_liabilities") - d("current_maturities_long_term_debt") - d("taxes_payable"))
                 - t("depreciation_amortization_total")) / t("total_assets"),
    }
    coef = dict(DSRI=0.920, GMI=0.528, AQI=0.404, SGI=0.892, DEPI=0.115, SGAI=-0.172, TATA=4.679, LVGI=-0.327)
    return -4.84 + sum(coef[k] * idx[k] for k in coef), idx


def test_reference_cases_exist():
    assert len(CASES) >= 50


def test_engine_equals_textbook_formula():
    for c in CASES:
        p = dict(c["inputs"])
        for s in ("t", "t1"):
            p.setdefault(f"depreciation_amortization_non_ppe_{s}", 0)
        m, idx = textbook(p)
        got = calculate(c["inputs"])
        assert math.isclose(got["m_score_B"], m, rel_tol=1e-12), c["pair_id"]
        for k, v in idx.items():
            assert math.isclose(got[k], v, rel_tol=1e-12), (c["pair_id"], k)
