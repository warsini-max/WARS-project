"""The engine must reproduce WARS_TrackB_v0_6.xlsx exactly.

Expected values were calculated by LibreOffice in test builds of the workbook that
hold SYNTHETIC pairs only (see tools/export_workbook_fixtures.py).
"""
import json
import math
from collections import Counter
from pathlib import Path

import pytest

from wars_scanner.engine import Err, calculate

FIXTURE = Path(__file__).parent / "fixtures" / "workbook_v06_synthetic.json"
CASES = json.loads(FIXTURE.read_text())["cases"]

# Columns that depend on other rows or on sheets not ported yet.
NOT_PORTED = {"pair_row", "duplicate_count", "prior_row_same_pair", "prior_duplicate_count",
              "basis_match_prior", "m_score_usable"}

DUP = Counter((c["source_build"], c["expected_pair_inputs"]["obs_key"]) for c in CASES)


def norm(v):
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    return v


def same(a, b):
    a, b = norm(a), norm(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, str) and isinstance(b, str) and a.startswith("#") and b.startswith("#"):
        return True  # both errors; the exact error code may differ between Excel and LibreOffice
    return a == b


@pytest.mark.parametrize("case", CASES, ids=[f'{c["source_build"]}:{c["pair_id"]}' for c in CASES])
def test_matches_workbook(case):
    dup = DUP[(case["source_build"], case["expected_pair_inputs"]["obs_key"])] if case["expected_pair_inputs"]["obs_key"] else 1
    got = calculate(case["inputs"], duplicate_count=dup)
    expected = dict(case["expected_pair_inputs"])
    expected.update({k: v for k, v in case["expected_calculation"].items() if k not in NOT_PORTED})
    diffs = {k: (norm(got.get(k)), norm(v)) for k, v in expected.items() if not same(got.get(k), v)}
    assert not diffs, diffs
