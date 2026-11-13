"""P0-2 shadow comparison: run the evidence ledger (wars_scanner/ledger.py) over the non-case development pairs,
both paths, and write old vs proposed status per field (Gail 13 Nov 2026 16.46: K1 = B, K2 = B, K5 = A, K6).

The ledger is shadow only. This script also checks K6 on every pair: values, statuses, cards and the M-score shown
must be identical before and after the ledger is attached.

Source reports are not in git (CLAUDE.md rule 5). Location: $WARS_DATA (default /mnt/user-data/uploads), folders
'WARS_Trial_XBRL_Tahap N' with <TICKER>_instance_<year>.zip and <TICKER>_LK_<year>.pdf. Evaluation-case issuers are
skipped (CLAUDE.md rule 4).

Usage: python tools/ledger_compare.py OUT.json [--workers 2]
"""
import argparse
import glob
import json
import logging
import os
import re
import sys
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("WARS_DATA", "/mnt/user-data/uploads")
CASES = {"AISA", "INAF", "KAEF", "GIAA"}          # case register (WR-2 M2): never run here


def pairs():
    out = []
    for d in sorted(glob.glob(os.path.join(DATA, "WARS_Trial_XBRL_Tahap *"))):
        st = os.path.basename(d).replace("WARS_Trial_XBRL_", "")
        for z in glob.glob(d + "/*.zip"):
            tk = re.split(r"[_-]", os.path.basename(z))[0].upper()
            tk = "TOTL" if tk == "TOTAL" else tk
            p = [x for x in glob.glob(d + "/*.pdf") if re.split(r"[_-]", os.path.basename(x))[0].upper() == tk]
            if p and tk not in CASES:
                out.append((st, tk, z, p[0]))
    return out


def _state(r, its):
    return ([(v.field, v.column, v.value, v.status) for v in r.extraction.values],
            [(i.field, i.mode) for i in its], r.m_score, list(getattr(r, "gate_block", []) or []))


def one(a):
    st, tk, z, pdf = a
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    from wars_scanner import check, gate, ledger, xbrl_pipeline
    try:
        pages = xbrl_pipeline.pdf_pages(pdf)
        x = xbrl_pipeline.run(open(z, "rb").read(), pdf)
        r = check.merge_xbrl(x.pdf, x)
        its = check.items(r)
        check.annotate(r, its)
        gate.enforce(r, its)
        pr = x.pdf
        pits = check.items(pr)
        gate.enforce(pr, pits)
        out = {}
        for path, rr, ii in (("X", r, its), ("P", pr, pits)):
            before = _state(rr, ii)
            rows = ledger.attach(rr, pages, path)
            out[path] = {"k6_unchanged": _state(rr, ii) == before, "unreadable": bool(rr.unreadable),
                         "cards": sorted({i.field for i in ii}), "rows": rows}
        return f"{st}:{tk}", out
    except Exception:                                 # noqa: BLE001  reported per pair, never hidden
        import traceback
        return f"{st}:{tk}", {"error": traceback.format_exc()[-600:]}


def summary(res):
    s = {}
    for path in ("X", "P"):
        c = Counter()
        k6 = [k for k, o in res.items() if path in o and not o[path]["k6_unchanged"]]
        new_cards = Counter()
        for k, o in res.items():
            if path not in o:
                continue
            for x in o[path]["rows"]:
                c["rows"] += 1
                c["old_" + x["status_old"]] += 1
                if x["status_old"] != x["status_proposed"]:
                    c["differ"] += 1
                    c["reason_" + x["reason"][:4]] += 1
            # a field whose proposed status differs and which has no card today would need one (one card per field)
            fields = {x["field"] for x in o[path]["rows"] if x["status_old"] != x["status_proposed"]}
            new_cards[k] = len(fields - set(o[path]["cards"]))
        n = sum(1 for o in res.values() if path in o)
        nr = sum(1 for o in res.values() if path in o and not o[path]["unreadable"])
        s[path] = {"pairs": n, "readable_pairs": nr, "k6_violations": k6, "counts": dict(c),
                   "extra_card_fields_total": sum(new_cards.values()),
                   "extra_card_fields_per_readable_pair": round(sum(new_cards.values()) / nr, 2) if nr else None}
    s["errors"] = sorted(k for k, o in res.items() if "error" in o)
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    ps = pairs()
    print(len(ps), "pairs", flush=True)
    res = {}
    with ProcessPoolExecutor(a.workers) as ex:
        for k, o in ex.map(one, ps):
            res[k] = o
            print(k, "error" if "error" in o else "ok", flush=True)
    s = summary(res)
    json.dump({"summary": s, "pairs": res}, open(a.out, "w"), default=str)
    print(json.dumps(s, indent=1, default=str))
