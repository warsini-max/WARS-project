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


FULL_NAMES = os.path.join(os.path.dirname(MASTER), "company_master_names.csv")


@lru_cache(maxsize=1)
def full_names():
    """Full names for master entries the workbook cut at 30 characters (Gail, 11 Nov 2026)."""
    if not os.path.exists(FULL_NAMES):
        return {}
    with open(FULL_NAMES, encoding="utf-8") as fh:
        return {r["ticker"]: r["company_name"].strip() for r in csv.DictReader(l for l in fh if not l.startswith("#"))}


@lru_cache(maxsize=1)
def master():
    full = full_names()
    with open(MASTER, encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return tuple(Issuer(r["ticker"], full.get(r["ticker"], r["company_name"]), r["listing_status"]) for r in rows)


def header_text(statements: dict) -> str:
    return " ".join(ln.text for s in statements.values() for ln in s.lines[:HEADER_LINES])


TRUNCATED = 30          # the workbook master cuts names at 30 characters ('Astrindo Nusantara Infrastrukt')


def _name_in(name: str, have: frozenset) -> bool:
    """All words of the master name appear in the header. When the master name was cut at 30 characters, its last
    word may be cut too, so it only has to begin a header word (BIPI: 'infrastrukt' / 'infrastruktur')."""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in DROP]
    if not words:
        return False
    if len(name) >= TRUNCATED and not re.search(r"(?i)\btbk\.?\s*$", name):
        if "tbk".startswith(words[-1]):            # '... Indonesia Tb': the cut fell inside 'Tbk'
            return bool(words[:-1]) and set(words[:-1]) <= have
        if len(words[-1]) >= 3:
            return set(words[:-1]) <= have and any(h.startswith(words[-1]) for h in have)
    return set(words) <= have


def by_ticker(code: str):
    """The master entry for a ticker (the XBRL EntityCode), else None."""
    code = (code or "").strip().upper()
    return next((i for i in master() if i.ticker == code), None)


def identify(text: str):
    """(Issuer or None, candidates). Unique match only."""
    have = _words(text)
    cands = [i for i in master() if _words(i.name) and _name_in(i.name, have)]
    if not cands:
        return None, []
    top = max(cands, key=lambda i: len(_words(i.name)))
    if all(_words(c.name) <= _words(top.name) for c in cands) and \
            sum(1 for c in cands if _words(c.name) == _words(top.name)) == 1:
        return top, cands
    return None, cands
