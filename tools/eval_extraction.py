"""Compare PDF-reader output with a golden-dataset file.

Usage: python tools/eval_extraction.py data/golden/SIDO_2021.csv /path/to/LK_SIDO_2021.pdf
Prints, per field and column: golden value, extracted value and the outcome:
  MATCH        the reader found the golden value
  WRONG        the reader returned a different number (a silent error unless the status is REVIEW)
  FLAGGED      the reader returned no value and said so (NOT FOUND / NOT SEARCHED / REVIEW)
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wars_scanner.pdf_reader import read  # noqa: E402


def evaluate(golden_csv, pdf):
    gold = {(r["field"], r["column"]): r for r in csv.DictReader(open(golden_csv, encoding="utf-8"))}
    ext = read(pdf)
    rows = []
    for v in ext.values:
        g = gold.get((v.field, v.column))
        if not g or not g["value"].lstrip("-").isdigit():
            continue
        gv = int(g["value"])
        if v.value is None:
            outcome = "FLAGGED"
        elif v.value == gv:
            outcome = "MATCH"
        else:
            outcome = "WRONG" + (" (flagged REVIEW)" if v.status == "REVIEW" else " (SILENT)")
        rows.append((v.field, v.column, gv, v.value, v.status, outcome))
    return ext, rows


if __name__ == "__main__":
    ext, rows = evaluate(sys.argv[1], sys.argv[2])
    for r in rows:
        print(*r, sep=" | ")
    from collections import Counter
    print(Counter(r[5].split(" ")[0] for r in rows), "| silent wrong:", sum("SILENT" in r[5] for r in rows))
    print("checks:", [(n, c, ok) for n, c, ok, _ in ext.checks])
