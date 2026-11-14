"""P0-5, first group (Gail 14 Nov 2026 06.40): SGA without proven completeness (K5-A) is REVIEW with a card; nothing
else the ledger proposes is applied. The value is never changed."""
import os
from types import SimpleNamespace as NS

import pytest

from wars_scanner import check, decide, gate, xbrl_pipeline
from wars_scanner.pdf_reader import Extraction, Value
from wars_scanner.text import t

SGA = "selling_general_administrative_expenses"
PL = """LAPORAN LABA RUGI
PENDAPATAN 24 1.780.476 2.020.780 REVENUES
BEBAN POKOK PENDAPATAN 25 (840.233) (1.078.759) COST OF REVENUES
LABA BRUTO 940.243 942.021 GROSS PROFIT
Beban pemasaran 26 (106.100) (102.565) Marketing expenses
Beban administrasi 27 (283.317) (264.972) Administrative expenses
Beban keuangan 28 (5.965) (6.055) Finance cost
LABA SEBELUM PAJAK 502.621 535.424 PROFIT BEFORE TAX"""


def _r(sga, extra=()):
    vals = [Value(SGA, c, v, "FOUND", [1], [""]) for c, v in zip(("t", "t1"), sga)] + list(extra)
    ex = Extraction("t.pdf", 1, [], 2025, "Full", "Consolidated", {"profit_loss": NS(kind="profit_loss", pages=[1], lines=[])},
                    vals, [], checks=[])
    return NS(extraction=ex, inputs={f"{v.field}_{v.column}": v.value for v in vals}, calc={"m_score_B": -2.0},
              review=[], missing=[], unreadable="", flags=[])


def test_complete_sga_stays_found():
    r = _r((389_417, 367_537))
    assert decide.apply(r, [PL], "P") == []
    assert all(v.status == "FOUND" for v in r.extraction.values) and r.review == []


def test_partial_sga_becomes_review_with_its_card_and_the_value_is_kept():
    r = _r((106_100, 102_565))                       # marketing alone (MTLA 2025, PDF path)
    assert decide.apply(r, [PL], "P") == [(SGA, "t"), (SGA, "t1")]
    assert [(v.value, v.status) for v in r.extraction.values] == [(106_100, "REVIEW"), (102_565, "REVIEW")]
    assert r.calc == {"m_score_B": -2.0} and r.inputs[f"{SGA}_t"] == 106_100
    reason, _ = check._reason(SGA, " ".join(n for *_x, n in r.review), [], r)
    assert reason.key == "chk.r.k5_sga"


def test_other_proposals_are_not_applied():
    # must NOT: receivables / PPE completeness (K5-A), identity (K1-B) or inferred zeros (K2-B) change status here
    extra = [Value("accounts_receivable", c, 1, "FOUND", [1], [""]) for c in ("t", "t1")]
    extra += [Value("long_term_debt", c, 0, "FOUND") for c in ("t", "t1")]
    r = _r((389_417, 367_537), extra)
    rows = decide.ledger.build(r, [PL], "P")
    assert any(x["field"] == "accounts_receivable" and x["status_proposed"] == "REVIEW" for x in rows)
    decide.apply(r, [PL], "P")
    assert all(v.status == "FOUND" for v in r.extraction.values)


DATA = os.environ.get("WARS_DATA", "/mnt/user-data/uploads")


def _real(stage, tk, year, path):
    d = os.path.join(DATA, f"WARS_Trial_XBRL_{stage}")
    z, p = os.path.join(d, f"{tk}_instance_{year}.zip"), os.path.join(d, f"{tk}_LK_{year}.pdf")
    if not (os.path.exists(z) and os.path.exists(p)):
        pytest.skip(f"{tk} {year} not available")
    x = xbrl_pipeline.run(open(z, "rb").read(), p)
    r = check.merge_xbrl(x.pdf, x) if path == "X" else x.pdf
    before = {(v.field, v.column): v.value for v in r.extraction.values}
    decide.apply(r, xbrl_pipeline.pdf_pages(p), path)
    its = check.items(r)
    check.annotate(r, its)
    gate.enforce(r, its)
    assert {(v.field, v.column): v.value for v in r.extraction.values} == before      # values never change
    return r, {i.field: i for i in its}


@pytest.mark.parametrize("stage,tk,path", [("Tahap 9", "APEX", "X"), ("Tahap 9", "MTLA", "P"), ("Tahap 8", "MERK", "P")])
def test_known_wrong_sga_values_are_now_on_the_review_screen(stage, tk, path):
    r, cards = _real(stage, tk, 2025, path)
    assert {v.status for v in r.extraction.values if v.field == SGA} == {"REVIEW"}
    assert SGA in cards
    for lang in ("id", "en"):                         # the card text (possibly with its component lines appended)
        assert t("chk.r.k5_sga", lang) in cards[SGA].reason.render(lang)
    assert r.gate.ok
