"""Check that every golden-dataset quotation appears on the cited PDF page.

Usage: python tools/check_golden_quotes.py data/golden/SIDO_2021.csv <path/to/LK_SIDO_2021.pdf>
Text is extracted with `pdftotext -layout`; runs of whitespace are collapsed before matching.
A failure means the quote or the page is wrong (or the page has no text layer).
"""
import csv
import re
import subprocess
import sys


def pages(pdf):
    out = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout
    return [re.sub(r"\s+", " ", p) for p in out.split("\f")]


def main(csv_path, pdf):
    P = pages(pdf)
    bad = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for page, quote in zip(r["pdf_page"].split(";"), r["quote"].split(" || ")):
                if not page.strip() or not quote.strip():
                    continue
                q = re.sub(r"\s+", " ", quote.strip())
                if q not in P[int(page) - 1]:
                    bad += 1
                    print(f"NOT FOUND  {r['field']}/{r['column']}  p{page}: {q}")
    print("all quotes found" if not bad else f"{bad} quote(s) not found")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
