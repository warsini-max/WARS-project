"""D3/D4 preparation tools (WARS_D3_D4_Persiapan_r0.md §8; Gail 13 Nov 2026 16.46, K3 = B, K4 = B).

No data is in the repository (CLAUDE.md rule 5). These commands never print the content of a report:
  draw FRAME.csv --seed N --n 60 --out DRAW.csv     stratified draw without replacement + ordered reserves
  manifest DIR --out MANIFEST.csv                     file name, size, SHA-256 (content read only to hash)
  verify DIR MANIFEST.csv                             hashes unchanged before the run
  pick-d4 DRAW.csv --seed N --n 10                    reports for Gail's full verification (D4)
  cp K N [--conf 0.95]                                one-sided Clopper-Pearson upper bound

FRAME.csv columns: ticker, sector, stratum (stratum may be empty). Case issuers are refused (rule 4).
"""
import argparse
import csv
import hashlib
import math
import os
import random
import sys

CASES = {"AISA", "INAF", "KAEF", "GIAA"}


def _binom_cdf(k, n, p):
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))


def cp_upper(k, n, conf=0.95):
    """Smallest p with P(X <= k | n, p) <= 1 - conf (one-sided upper bound). k = n gives 1."""
    if not 0 <= k <= n or n <= 0:
        raise ValueError("need 0 <= k <= n, n > 0")
    if k == n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _binom_cdf(k, n, mid) > 1 - conf:
            lo = mid
        else:
            hi = mid
    return hi


def draw(frame, seed, n, per_stratum_min=1, reserves=1.0):
    """Allocation proportional to sector size (min per_stratum_min per sector, largest remainders), then a random
    order inside each sector: the first k are drawn, the rest are reserves in order."""
    bad = sorted({r["ticker"].upper() for r in frame} & CASES)
    if bad:
        raise ValueError(f"case issuers in the frame: {bad}")
    rng = random.Random(seed)
    by = {}
    for r in sorted(frame, key=lambda r: r["ticker"]):
        by.setdefault(r["sector"], []).append(r)
    total = sum(len(v) for v in by.values())
    if n > total:
        raise ValueError("n larger than the frame")
    quota = {s: max(per_stratum_min, len(v) * n / total) for s, v in by.items()}
    base = {s: min(len(by[s]), int(q)) for s, q in quota.items()}
    rest = n - sum(base.values())
    for s in sorted(quota, key=lambda s: (-(quota[s] - int(quota[s])), s)):
        if rest <= 0:
            break
        if base[s] < len(by[s]):
            base[s] += 1
            rest -= 1
    while sum(base.values()) > n:                     # minimums can overshoot: trim the largest sectors
        s = max(base, key=lambda s: (base[s], s))
        base[s] -= 1
    out = []
    for s in sorted(by):
        order = by[s][:]
        rng.shuffle(order)
        for i, r in enumerate(order):
            out.append({**r, "role": "drawn" if i < base[s] else "reserve", "order_in_sector": i + 1})
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(d):
    rows = []
    for root, _dirs, files in os.walk(d):
        for f in sorted(files):
            p = os.path.join(root, f)
            rows.append({"file": os.path.relpath(p, d), "bytes": os.path.getsize(p), "sha256": sha256(p)})
    return sorted(rows, key=lambda r: r["file"])


def verify(d, rows):
    """Files whose hash changed or that are missing."""
    bad = []
    for r in rows:
        p = os.path.join(d, r["file"])
        if not os.path.exists(p):
            bad.append((r["file"], "missing"))
        elif sha256(p) != r["sha256"]:
            bad.append((r["file"], "hash changed"))
    return bad


def pick_d4(rows, seed, n=10):
    drawn = sorted((r for r in rows if r.get("role", "drawn") == "drawn"), key=lambda r: (r["ticker"], r.get("fy", "")))
    if n > len(drawn):
        raise ValueError("n larger than the drawn set")
    return random.Random(seed).sample(drawn, n)


def _read(p):
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write(p, rows):
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("draw"); a.add_argument("frame"); a.add_argument("--seed", type=int, required=True)
    a.add_argument("--n", type=int, required=True); a.add_argument("--min", type=int, default=1); a.add_argument("--out", required=True)
    b = sub.add_parser("manifest"); b.add_argument("dir"); b.add_argument("--out", required=True)
    c = sub.add_parser("verify"); c.add_argument("dir"); c.add_argument("manifest")
    d = sub.add_parser("pick-d4"); d.add_argument("draw"); d.add_argument("--seed", type=int, required=True)
    d.add_argument("--n", type=int, default=10)
    e = sub.add_parser("cp"); e.add_argument("k", type=int); e.add_argument("n", type=int); e.add_argument("--conf", type=float, default=0.95)
    x = ap.parse_args(argv)
    if x.cmd == "draw":
        _write(x.out, draw(_read(x.frame), x.seed, x.n, x.min))
    elif x.cmd == "manifest":
        _write(x.out, manifest(x.dir))
    elif x.cmd == "verify":
        bad = verify(x.dir, _read(x.manifest))
        for f, why in bad:
            print(f, why)
        return 1 if bad else 0
    elif x.cmd == "pick-d4":
        for r in pick_d4(_read(x.draw), x.seed, x.n):
            print(r["ticker"], r.get("fy", ""))
    elif x.cmd == "cp":
        print(f"{cp_upper(x.k, x.n, x.conf):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
