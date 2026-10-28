"""Identify the issuer from the statement headers, using the master list (report design R-16, T-1).

Rule (T-1): the match must be unique; otherwise the issuer is "not identified". Nothing is guessed.

How it matches: the words of each master name (without "PT", "Tbk" and punctuation) must all appear
in the first lines of the primary statements (where the entity name is printed). Bilingual reports
print the name in two columns, so words are compared as a set, not as a phrase. When several master
names match and one of them contains all the words of the others (e.g. "Mayora Indah" and "Indah"),
the longer name is the more specific one and is taken; any other overlap is reported as not identified.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from functools import lru_cache

MASTER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "company_master.csv")
DROP = {"pt", "tbk", "persero", "the", "and", "dan", "of"}
HEADER_LINES = 8


@dataclass(frozen=True)
class Issuer:
    ticker: str
    name: str
    status: str


def _words(s: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in DROP)


@lru_cache(maxsize=1)
def master():
    with open(MASTER, encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return tuple(Issuer(r["ticker"], r["company_name"], r["listing_status"]) for r in rows)


def header_text(statements: dict) -> str:
    return " ".join(ln.text for s in statements.values() for ln in s.lines[:HEADER_LINES])


def identify(text: str):
    """(Issuer or None, candidates). Unique match only."""
    have = _words(text)
    cands = [i for i in master() if _words(i.name) and _words(i.name) <= have]
    if not cands:
        return None, []
    top = max(cands, key=lambda i: len(_words(i.name)))
    if all(_words(c.name) <= _words(top.name) for c in cands) and \
            sum(1 for c in cands if _words(c.name) == _words(top.name)) == 1:
        return top, cands
    return None, cands
