"""Load a golden-dataset CSV (data/golden/<TICKER>_<YEAR>.csv) as engine input."""
import csv
from pathlib import Path

NUMERIC_STATUSES = {"FOUND", "REVIEW", "UNDISCLOSED", "BUILT FROM DISCLOSED COMPONENTS"}
TEXT_FIELDS = {"statement_type", "reporting_currency", "unit_scale", "psak73_applied", "amort_status",
               "non_ppe_status", "doc_version"}


def load(path):
    """Return (engine_inputs, rows). Fields without a usable value stay out (= blank)."""
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
    p = {"ticker": rows[0]["ticker"], "fiscal_year_t": int(rows[0]["fiscal_year"])}
    for r in rows:
        f, col, val = r["field"], r["column"], r["value"]
        if val == "":
            continue
        if f in TEXT_FIELDS:
            v = int(val) if f == "doc_version" else val
        elif r["status"] in NUMERIC_STATUSES:
            v = int(val)
        else:
            continue
        if col == "both":
            p[f] = v
        elif f == "doc_version":
            p["doc_version"] = v
        else:
            p[f"{f}_{col}"] = v
    return p, rows
