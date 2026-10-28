"""Golden-dataset files load and run through the engine.

Golden files are DRAFT until Gail verifies them, so no M-score value is asserted here;
the checks are structural.
"""
from pathlib import Path

import pytest

from wars_scanner.engine import REQUIRED_14, calculate
from wars_scanner.golden import load

GOLDEN = sorted((Path(__file__).parents[1] / "data" / "golden").glob("*_*.csv"))


@pytest.mark.parametrize("path", GOLDEN, ids=[p.stem for p in GOLDEN])
def test_golden_file_is_complete_and_computes(path):
    p, rows = load(path)
    assert all(r["verification"] in ("DRAFT", "AI-CHECKED-2", "VERIFIED") for r in rows)
    for s in ("t", "t1"):
        missing = [f for f in REQUIRED_14 if f"{f}_{s}" not in p]
        assert not missing, (s, missing)
    out = calculate(p)
    assert out["calc_status"] == "OK", out["calc_status"]
