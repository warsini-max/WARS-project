"""D3/D4 preparation tools on synthetic data (WARS_D3_D4_Persiapan_r0.md)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import d3_freeze as d3  # noqa: E402


def test_cp_known_values():
    # zero failures: 1 - 0.05 ** (1/n) (exact for k = 0)
    for n in (10, 29, 59, 60, 149, 299):
        assert d3.cp_upper(0, n) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-6)
    assert d3.cp_upper(0, 29) < 0.10 and d3.cp_upper(0, 28) > 0.10
    assert d3.cp_upper(0, 59) < 0.05 and d3.cp_upper(0, 58) > 0.05
    assert d3.cp_upper(5, 5) == 1.0
    assert d3.cp_upper(0, 60) < d3.cp_upper(1, 60) < d3.cp_upper(2, 60)


def test_cp_rejects_bad_input():
    with pytest.raises(ValueError):
        d3.cp_upper(3, 2)


FRAME = [{"ticker": f"T{s}{i:02d}", "sector": f"S{s}", "stratum": ""} for s in range(5) for i in range(4 + 3 * s)]


def test_draw_is_reproducible_and_proportional():
    a, b = d3.draw(FRAME, 7, 20), d3.draw(FRAME, 7, 20)
    assert a == b
    drawn = [r for r in a if r["role"] == "drawn"]
    assert len(drawn) == 20 and len({r["ticker"] for r in drawn}) == 20
    per = {s: sum(1 for r in drawn if r["sector"] == s) for s in {r["sector"] for r in FRAME}}
    assert min(per.values()) >= 1 and per["S4"] > per["S0"]
    assert len(a) == len(FRAME)                       # everything else is an ordered reserve
    assert d3.draw(FRAME, 8, 20) != a


def test_draw_refuses_case_issuers():
    # must NOT: an evaluation-case issuer in the frame (CLAUDE.md rule 4)
    with pytest.raises(ValueError):
        d3.draw(FRAME + [{"ticker": "AISA", "sector": "S0", "stratum": ""}], 1, 5)


def test_manifest_and_verify(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"one")
    (tmp_path / "b.zip").write_bytes(b"two")
    m = d3.manifest(tmp_path)
    assert [r["file"] for r in m] == ["a.pdf", "b.zip"] and all(len(r["sha256"]) == 64 for r in m)
    assert d3.verify(tmp_path, m) == []
    (tmp_path / "a.pdf").write_bytes(b"changed")
    os.remove(tmp_path / "b.zip")
    assert d3.verify(tmp_path, m) == [("a.pdf", "hash changed"), ("b.zip", "missing")]


def test_pick_d4():
    rows = [{"ticker": f"X{i}", "fy": "2025", "role": "drawn"} for i in range(30)] + [{"ticker": "R", "fy": "2025", "role": "reserve"}]
    p = d3.pick_d4(rows, 3, 10)
    assert len(p) == 10 and all(r["role"] == "drawn" for r in p) and p == d3.pick_d4(rows, 3, 10)
