"""Export the issuer master list (ticker, company name, listing status) from the Track B workbook.

Source: sheet `Company_Master` of WARS_TrackB_v0_6.xlsx (Gail, 27 Oct 2026; report design R-16, T-1).
Only the three columns the app uses are exported. Sector is not exported (R-16: no sector in the
report). Tickers and names are public information; no financial data leaves the workbook.

Usage:
    python tools/export_company_master.py <WARS_TrackB_v0_6.xlsx> --out data/company_master.csv
"""
import argparse
import csv
import hashlib
from pathlib import Path

import openpyxl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--out", default="data/company_master.csv")
    a = ap.parse_args()
    sha = hashlib.sha256(Path(a.workbook).read_bytes()).hexdigest()
    ws = openpyxl.load_workbook(a.workbook, read_only=True, data_only=True)["Company_Master"]
    rows = list(ws.iter_rows(values_only=True))
    head = next(i for i, r in enumerate(rows) if r and r[0] == "ticker")
    cols = {name: j for j, name in enumerate(rows[head]) if name}
    out, seen = [], set()
    for r in rows[head + 1:]:
        tk = str(r[cols["ticker"]] or "").strip().upper()
        if not tk:
            continue
        if tk in seen:
            raise SystemExit(f"duplicate ticker in Company_Master: {tk}")
        seen.add(tk)
        out.append({"ticker": tk, "company_name": str(r[cols["company_name"]] or "").strip(),
                    "listing_status": str(r[cols["listing_status"]] or "").strip()})
    out.sort(key=lambda x: x["ticker"])
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        fh.write(f"# source: WARS_TrackB_v0_6.xlsx sheet Company_Master, sha256 {sha}\n")
        w = csv.DictWriter(fh, fieldnames=["ticker", "company_name", "listing_status"])
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} issuers -> {a.out}")


if __name__ == "__main__":
    main()
