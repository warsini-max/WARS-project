"""M-08 package (approved by Gail, 23 Oct 2026): standard transition and restated comparatives.

Ports three existing workbook v0.6 checks (Pair_Validation) into the app, with the inputs read from
the report itself:

  (a) psak73_applied_t / _t1      -> r_standard_transition        (t = Y and t1 = N -> REVIEW)
  (b) standards_first_applied_t   -> r_standard_transition_other  (non-blank -> REVIEW; PSAK 71 / 72)
  (c) comparative_label_t1        -> r_comparative_label          (RESTATED / RECLASSIFIED / both -> REVIEW)

Rules (Gail's condition): evidence comes from the disclosures in the notes or from the column label
on the face of the statements, never from the reporting year alone. A standard counts as first
applied in year t only when a notes passage names the standard, uses first-application wording
(penerapan awal / adoption of / initial application / dampak penerapan ...), and 1 January t is stated close to the
mention (or on the previous page of the same accounting-policy-changes section). Amendments ("Amendemen PSAK 71, 55, 73 ...") are not
first application. The t-1 column counts as not restated (t1 = N) only when the notes say so or
name the modified retrospective method; otherwise t1 is left blank and the gap is reported.
Only REVIEW flags result; the M-score is not changed.
"""
from __future__ import annotations

import re

from .text import Msg, Psak

STANDARDS = {"71": "PSAK 71", "72": "PSAK 72", "73": "PSAK 73"}
MENTION = re.compile(r"PSAK\s*(?:No\.?\s*)?(71|72|73)\b|SFAS\s*(?:No\.?\s*)?(71|72|73)\b", re.I)
FIRST_APPLICATION = re.compile(
    r"penerapan awal|tanggal penerapan awal|penerapan atas psak|menerapkan psak|telah menerapkan|"
    r"dampak (kumulatif )?(dari )?penerapan|initial(ly)? appl|date of initial application|adoption of|adopted psak|"
    r"has applied psak|has implemented|first appl|pertama kali", re.I)
AMENDMENT_BEFORE = re.compile(r"(amendemen|amandemen|amendments?|penyesuaian tahunan|annual improvements?)[^.]{0,120}$", re.I)
NOT_RESTATED = re.compile(
    r"tidak menyajikan kembali|tidak disajikan kembali|did not restate|has not restated|not restated|"
    r"retrospektif yang dimodifikasi|modified retrospective|dampak kumulatif|cumulative effect", re.I)
FULLY_RESTATED = re.compile(r"penerapan retrospektif penuh|full(y)? retrospective", re.I)
RESTATED_LABEL = re.compile(r"disajikan kembali|as restated|\brestated\b", re.I)
RECLASS_LABEL = re.compile(r"direklasifikasi|reklasifikasi|as reclassified|\breclassified\b", re.I)


def _flat(s):
    return re.sub(r"\s+", " ", s or "")


def _date_t(text, t):
    return re.search(rf"\b1 Januari {t}\b|\bJanuary 1,? {t}\b|\b1 January {t}\b", text, re.I)


POLICY_SECTION = re.compile(r"perubahan kebijakan akuntansi|changes in accounting (principles|policies)|"
                            r"penerapan standar|adoption of (new|revised) (accounting )?standards", re.I)


def first_applied(text_pages, notes_start, fiscal_year):
    """{standard: evidence} for PSAK 71/72/73 first applied in year t, read from the notes.

    A passage qualifies when it names the standard (not as an amendment), uses first-application
    wording, and states 1 January t either within 600 characters of the mention, or on the previous
    page of the same accounting-policy-changes section (a section that runs over a page break).
    t1_restated: "N" when any qualifying passage (or a page holding one) says the comparatives were
    not restated or names the modified retrospective method; "Y" when it says fully retrospective.
    """
    hits = {}
    if not (notes_start and fiscal_year):
        return {}
    for i in range(notes_start - 1, len(text_pages)):
        page = _flat(text_pages[i])
        prev = _flat(text_pages[i - 1]) if i > 0 else ""
        section_carry = bool(POLICY_SECTION.search(page) and POLICY_SECTION.search(prev) and _date_t(prev, fiscal_year))
        for m in MENTION.finditer(page):
            std = m.group(1) or m.group(2)
            if AMENDMENT_BEFORE.search(page[max(0, m.start() - 160):m.start()]):
                continue
            lo, hi = max(0, m.start() - 600), m.end() + 600
            window = page[lo:hi]
            if not FIRST_APPLICATION.search(window):
                continue
            if not (_date_t(window, fiscal_year) or section_carry):
                continue
            h = hits.setdefault(std, {"page": i + 1, "quote": page[max(0, m.start() - 120):m.end() + 180].strip(),
                                      "restated": set()})
            if FULLY_RESTATED.search(window):
                h["restated"].add("Y")
            if NOT_RESTATED.search(window) or NOT_RESTATED.search(page):
                h["restated"].add("N")
    out = {}
    for std, h in hits.items():
        r = h["restated"]
        out[std] = {"page": h["page"], "quote": h["quote"],
                    "t1_restated": "Y" if r == {"Y"} else ("N" if r == {"N"} else "")}
    return out


def comparative_label(statements):
    """RESTATED / RECLASSIFIED / RESTATED_AND_RECLASSIFIED / NONE from the column header of the face
    statements (lines before the first line with figures), with the page; None when no header was read."""
    found, pages = set(), []
    seen = False
    for st in (statements or {}).values():
        for ln in st.lines:
            if ln.amounts:
                break
            seen = True
            txt = ln.text
            if RESTATED_LABEL.search(txt):
                found.add("RESTATED"); pages.append(ln.page)
            if RECLASS_LABEL.search(txt):
                found.add("RECLASSIFIED"); pages.append(ln.page)
    if not seen:
        return None, []
    label = "RESTATED_AND_RECLASSIFIED" if found == {"RESTATED", "RECLASSIFIED"} else (found.pop() if found else "NONE")
    return label, sorted(set(pages))


def detect(text_pages, notes_start, fiscal_year, statements):
    """Engine inputs for the three workbook checks, plus the evidence and any gap to report."""
    fa = first_applied(text_pages, notes_start, fiscal_year)
    inputs, evidence, gaps = {}, [], []
    if "73" in fa:
        inputs["psak73_applied_t"] = "Y"
        if fa["73"]["t1_restated"]:
            inputs["psak73_applied_t1"] = fa["73"]["t1_restated"]
        else:
            # psak73_applied_t1 is left blank (never guessed); the user is told to check the transition note
            gaps.append(Msg("issue.transition_gap", std=Psak("116", "73", fiscal_year), t=fiscal_year,
                            p=fa["73"]["page"]))
    other = [STANDARDS[s] for s in ("71", "72") if s in fa and fa[s]["t1_restated"] != "Y"]
    if other:
        inputs["standards_first_applied_t"] = "; ".join(other)
    for s, ev in sorted(fa.items()):
        evidence.append({"standard": STANDARDS[s], "page": ev["page"], "quote": ev["quote"], "t1_restated": ev["t1_restated"]})
    label, pages = comparative_label(statements)
    if label is not None:
        inputs["comparative_label_t1"] = label
        if label != "NONE":
            evidence.append({"standard": "comparative label", "page": pages[0] if pages else None,
                             "quote": label, "t1_restated": ""})
    return {"inputs": inputs, "evidence": evidence, "gaps": gaps}
