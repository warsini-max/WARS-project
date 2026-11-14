"""P0-5, first group: the evidence ledger's completeness rule (K5 = A) applied to selling + general and administrative
expenses only (Gail, 14 Nov 2026 06.40, "oke 1-4": SGA first, before closing the portfolio).

A FOUND selling + G&A value whose completeness cannot be shown from the profit or loss statement (ledger.sga_complete,
K5-A) becomes REVIEW, with the card text chk.r.k5_sga. The value is never changed. Every other proposal of the ledger
(K1-B, K2-B, K5-A for receivables and PPE) stays shadow (K6) until Gail authorises it.

The ledger rows are attached to the result as before (r.ledger), recording the status before this decision.
"""
from . import ledger

FIELD = "selling_general_administrative_expenses"
NOTE = "K5-A SGA: completeness not shown"          # read by check._reason


def sga_rows(rows):
    """Ledger rows this decision acts on: SGA, FOUND, proposed REVIEW for completeness (K5-A)."""
    return [x for x in rows if x["field"] == FIELD and x["status_old"] == "FOUND"
            and x["status_proposed"] == "REVIEW" and x["reason"].startswith("K5-A")]


def apply(r, page_texts, path):
    """Attach the ledger, then demote SGA without proven completeness. Returns the (field, column) demoted."""
    rows = ledger.attach(r, page_texts, path)
    hit = sga_rows(rows)
    if not hit:
        return []
    cols = {x["column"]: x for x in hit}
    for v in r.extraction.values:
        if v.field == FIELD and v.column in cols and v.status == "FOUND":
            v.status = "REVIEW"
    why = {c: f"{NOTE} ({x['reason']})" for c, x in cols.items()}
    r.review = [e for e in r.review if not (e[0] == FIELD and e[1] in cols)]
    r.review += [(FIELD, c, "REVIEW", why[c]) for c in sorted(cols)]
    xb = getattr(r, "xbrl", None)
    if xb:
        notes = xb.setdefault("notes", {})
        for c in cols:
            notes[(FIELD, c)] = why[c]
        for it in xb.get("items") or []:
            if getattr(it, "field", None) == FIELD and getattr(it, "column", None) in cols and it.status == "FOUND":
                it.status = "REVIEW"
    r.decided = sorted((FIELD, c) for c in cols)
    return r.decided
