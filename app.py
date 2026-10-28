"""WARS Scanner web app: upload a digital IDX annual report, get the Beneish M-score red-flag screen
with every input traced to its page. Every text comes from the bilingual catalogue (wars_scanner.text);
the user chooses Bahasa Indonesia or English.

Run:  streamlit run app.py
"""
import hashlib
import os
import tempfile

import pandas as pd
import streamlit as st

from wars_scanner import pipeline, report
from wars_scanner.text import Amt, Msg, Num, Raw, render, t

st.set_page_config(page_title="WARS Scanner", page_icon="🔎", layout="wide")

COLOURS = {"green": "#d9f2e3", "yellow": "#fff3c4", "red": "#f9d6d5"}
LANG_NAMES = {"id": "Bahasa Indonesia", "en": "English"}


@st.cache_data(show_spinner=False, max_entries=20)
def analyse(data: bytes, ticker: str):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "report.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
        r = pipeline.run(path, ticker or "UPLOAD")
    r.extraction.statements = {}          # not needed by the page; keeps the cache small
    return r


lang = st.radio("Bahasa / Language", list(LANG_NAMES), format_func=LANG_NAMES.get, horizontal=True, key="lang")


def T(key, codes=False, **kw):
    return t(key, lang, codes, **kw)


def R(x, codes=False):
    return render(x, lang, codes)


LINKEDIN = "https://www.linkedin.com/in/warsiniak"

st.title(T("app.title"))
st.caption(T("app.subtitle") + " · **Beta**")
st.caption(T("app.beta"))
st.info(T("app.disclaimer"), icon="⚖️")

with st.sidebar:
    st.header(T("app.howto.title"))
    st.markdown(T("app.howto"))
    st.markdown(T("app.legend"))
    st.markdown(T("app.limits"))
    with st.expander(T("app.get_lk.title")):
        st.markdown(T("app.get_lk"))
    st.caption(T("app.privacy") + " " + T("app.privacy_online"))
    st.markdown(f"{T('app.author')} · [LinkedIn]({LINKEDIN})")

up = st.file_uploader(T("app.upload"), type=["pdf"], key="upload", help=T("app.upload_help"))      # fixed keys: the language switch keeps state
ticker = st.text_input(T("app.ticker"), max_chars=6, key="ticker").strip().upper()

if not up:
    st.divider()
    st.caption(T("app.disclaimer") + " " + T("app.footer_model") + f" {T('app.author')} · [LinkedIn]({LINKEDIN})")
    st.stop()

data = up.getvalue()
with st.spinner(T("app.reading")):
    try:
        r = analyse(data, ticker)
    except Exception as e:                                     # noqa: BLE001
        st.error(T("app.pdf_error"))
        with st.expander(T("app.pdf_error_detail")):
            st.code(f"{type(e).__name__}: {e}")
        st.caption(T("app.disclaimer"))
        st.stop()

ex = r.extraction
sha = hashlib.sha256(data).hexdigest()
fy = ex.fiscal_year
YR = {"t": str(fy) if fy else "t", "t1": str(fy - 1) if fy else "t−1"}
st.caption(T("app.fileline", name=Raw(up.name), sha=sha[:16], pages=ex.n_pages, year=fy or "?",
             stype=Msg(f"stype.{ex.statement_type}") if ex.statement_type == "Consolidated" else Msg("stype.unknown"),
             unit=Msg(f"unit.{ex.unit_scale}") if ex.unit_scale else Msg("unit.unknown")))


def col_name(c):
    return YR.get(c) or T("col.both", a=YR["t"], b=YR["t1"])


# ------------------------------------------------------------------------------------ non-PPE status (M-06)
NP_OPTIONS = ["", "NONE_PRESENT", "ALL_DISCLOSED", "PARTIAL_UNDISCLOSED"]
np_decisions, np_errors = {}, {}
if not r.unreadable:
    for c in ("t", "t1"):
        stt = st.session_state.get(f"{sha}:np:{c}:status", "")
        notes = list(st.session_state.get(f"{sha}:np:{c}:notes", []))
        extra = [x.strip() for x in st.session_state.get(f"{sha}:np:{c}:extra", "").split(";") if x.strip()]
        if stt:
            np_decisions[c] = {"status": stt, "notes": notes + extra}
    for c, d in list(np_decisions.items()):
        try:
            pipeline.apply_non_ppe_decisions(r, {c: d})
        except pipeline.DecisionError as e:
            np_errors[c] = e.message
            np_decisions.pop(c)

# ------------------------------------------------------------------------------------ amortisation status (M-15)
AM_OPTIONS = ["", "NONE_PRESENT", "GOODWILL_ONLY", "INDEFINITE_ONLY", "UNDISCLOSED"]
am_pending = r.amort_pending if not r.unreadable else []
am_decisions, am_errors = {}, {}
for c in am_pending:
    stt = st.session_state.get(f"{sha}:am:{c}:status", "")
    notes = list(st.session_state.get(f"{sha}:am:{c}:notes", []))
    extra = [x.strip() for x in st.session_state.get(f"{sha}:am:{c}:extra", "").split(";") if x.strip()]
    if stt:
        am_decisions[c] = {"status": stt, "notes": notes + extra}
for c, d in list(am_decisions.items()):
    try:
        pipeline.apply_amort_decisions(r, {c: d})
    except pipeline.DecisionError as e:
        am_errors[c] = e.message
        am_decisions.pop(c)
if not r.unreadable:
    r = pipeline.apply_user_decisions(r, np_decisions, am_decisions)

# ------------------------------------------------------------------------------------ verdict
items = report.review_items(r, lang) if not r.unreadable else []
answers = {i["key"]: st.session_state.get(f"{sha}:{i['key']}", report.PENDING_ANSWER) for i in items}
reviewer = st.session_state.get(f"{sha}:reviewer", "")
confirm = report.confirmation_summary(items, answers)
head, detail, level = report.verdict(r, confirm, lang, reviewer)
box = {"high": st.error, "low": st.success, "none": st.warning}[level]
c1, c2 = st.columns([1, 3])
with c1:
    shown = r.m_score if confirm["state"] != "bad" else None
    st.metric("M-score", report.dec(shown, 3, lang))
    st.caption(T("app.status", status=Raw(report.status_text(r, confirm, lang))))
    if items:
        st.caption(T("app.confirm_counts", ok=confirm["ok"], bad=confirm["bad"], pending=confirm["pending"]))
with c2:
    box(f"**{head}**\n\n{detail}")
    st.caption(T("app.threshold", thr=Num(report.THRESHOLD, 2)))
    with st.expander(T("app.method.title")):
        st.write(T("app.model_limit") + " " + T("app.footer_model"))

for f in r.errors:
    st.error(T("app.check_failed", msg=f.message))

if r.unreadable:
    with st.expander(T("app.read_detail")):
        for i in ex.issues:
            st.markdown(f"- {R(i, codes=True)}")
    st.divider()
    st.caption(T("app.disclaimer") + " " + T("app.footer_model") + f" {T('app.author')} · [LinkedIn]({LINKEDIN})")
    st.stop()

# ------------------------------------------------------------------------------------ drivers (B r1 §3-§5)
if r.m_score is not None and confirm["state"] != "bad":
    st.subheader(T("drivers.title"))
    st.caption(T("drivers.note"))
    drv = report.drivers(r, lang=lang)
    if not drv:
        st.write(T("drivers.none"))
    for d in drv:
        f = report.finding(r, d["index"], confirm, lang)
        st.markdown(f"**{d['index']} – {d['name']}**  \n{f['a']}  \n{f['c']}  \n{f['d']}"
                    + "".join(f"  \n_{x}_" for x in f["caveats"]))
        with st.expander(T("drivers.about") + f" ({d['index']})"):
            st.write(f["why"])
    cols = {k: T(f"idx.col.{k}") for k in ("index", "name", "value", "coef", "contribution", "push", "note")}
    idx = pd.DataFrame([{cols["index"]: x["index"], cols["name"]: x["name"],
                         cols["value"]: report.dec(x["value"], 3, lang), cols["coef"]: report.dec(x["coefficient"], 3, lang),
                         cols["contribution"]: report.dec(x["contribution"], 3, lang),
                         cols["push"]: report.dec(x["push_vs_neutral"], 3, lang), cols["note"]: x["note"]}
                        for x in report.index_rows(r, lang)])
    with st.expander(T("idx.expander")):
        st.dataframe(idx, hide_index=True, width="stretch")
        st.caption(T("idx.caption", const=Num(report.M_CONSTANT, 2)))

# ------------------------------------------------------------------------------------ non-PPE section (M-06)
ev = ex.non_ppe_evidence or {}
st.subheader(T("np.title"))
st.caption(T("np.caption"))
for g in ev.get("groups", []):
    glabel = T(f"np.group.{g['key']}")
    if g["found"]:
        lines = "  \n".join(T("np.hit", p=h["page"], text=Raw(h["text"])) + (" " + T("np.hit_amount") if h["with_amount"] else "")
                            for h in g["hits"][:5])
        st.markdown(f"**{T('np.found', label=Raw(glabel), n=g['n_hits'])}**  \n{lines}")
    else:
        st.markdown(T("np.not_found", label=Raw(glabel)))
if ev.get("amounts_read"):
    st.markdown(T("np.amounts", list=Raw(", ".join(f"{YR[c]}: {report.amount(v, lang)}" for c, v in ev["amounts_read"].items())),
                  source=ev.get("amount_source", "")))
note_options = [n["heading"] for n in ev.get("notes", [])]
cols2 = st.columns(2)
for col, c in zip(cols2, ("t", "t1")):
    with col:
        st.markdown(f"**{T('np.year', y=YR[c])}**")
        opts = [k for k in NP_OPTIONS if k != "ALL_DISCLOSED" or c in ev.get("amounts_read", {})]
        st.radio(T("np.status", y=YR[c]), opts, format_func=lambda k: T(f"np.opt.{k}"), key=f"{sha}:np:{c}:status")
        st.multiselect(T("np.notes", y=YR[c]), note_options, key=f"{sha}:np:{c}:notes")
        st.text_input(T("np.extra", y=YR[c]), key=f"{sha}:np:{c}:extra")
        if c in np_errors:
            st.error(T("np.err_amount") if np_errors[c].key == "err.np_amount" else T("np.err_notes"))
        elif c in r.decisions:
            st.success(T("np.applied", choice=Msg(f"np.opt.{r.decisions[c]['status']}")))

# ------------------------------------------------------------------------------------ amortisation section (M-15)
if am_pending:
    st.subheader(T("am.title"))
    st.caption(T("am.caption"))
    cols3 = st.columns(2)
    for col, c in zip(cols3, ("t", "t1")):
        if c not in am_pending:
            continue
        with col:
            st.markdown(f"**{T('np.year', y=YR[c])}**")
            st.radio(T("am.status", y=YR[c]), AM_OPTIONS, format_func=lambda k: T(f"am.opt.{k}"), key=f"{sha}:am:{c}:status")
            st.multiselect(T("am.notes", y=YR[c]) + " ", note_options, key=f"{sha}:am:{c}:notes")
            st.text_input(T("am.extra", y=YR[c]), key=f"{sha}:am:{c}:extra")
            if c in am_errors:
                st.error(T("am.err"))
            elif c in r.amort_decisions:
                st.success(T("np.applied", choice=Msg(f"am.opt.{r.amort_decisions[c]['status']}")))

# ------------------------------------------------------------------------------------ inputs
st.subheader(T("inputs.title"))
rows = report.input_rows(r, lang)
df = pd.DataFrame([{T("inputs.col.item"): x["label"], YR["t"]: x["value_t"], YR["t1"]: x["value_t1"],
                    T("inputs.col.status", y=YR["t"]): x["status_t"], T("inputs.col.status", y=YR["t1"]): x["status_t1"],
                    T("inputs.col.pages"): x["pages"], T("inputs.col.source"): x["source"],
                    T("inputs.col.note"): x["note"]} for x in rows])


def _style(frame):
    styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for i, x in enumerate(rows):
        styles.iloc[i, 1] = f"background-color: {COLOURS[x['colour_t']]}"
        styles.iloc[i, 2] = f"background-color: {COLOURS[x['colour_t1']]}"
    return styles


st.dataframe(df.style.apply(_style, axis=None), hide_index=True, width="stretch", height=760)
st.caption(T("inputs.caption", unit=Msg(f"unit.{ex.unit_scale}") if ex.unit_scale else Msg("unit.unknown")))

# ------------------------------------------------------------------------------------ confirmation
if items:
    st.subheader(T("confirm.title", n=len(items)))
    st.caption(T("confirm.caption"))
    for i in items:
        a, b = st.columns([3, 2])
        with a:
            st.markdown(f"**{i['title']}** ({col_name(i['column'])})  \n{i['why']}")
        with b:
            st.radio(i["title"], list(report.ANSWERS), format_func=lambda k: T(f"confirm.{k}"), horizontal=True,
                     key=f"{sha}:{i['key']}", label_visibility="collapsed")
    st.text_input(T("confirm.reviewer"), key=f"{sha}:reviewer")
else:
    st.write(T("confirm.none"))
for a_ in r.assumptions:
    st.caption(T("app.assumption", text=a_))

n_pass = sum(1 for x in ex.checks if x[2]) + len(r.passed)
with st.expander(T("checks.expander", ok=n_pass, err=len(r.errors), rev=sum(f.severity == "REVIEW" for f in r.flags))):
    for name, col, ok, det in ex.checks:
        st.markdown(f"- {'✅' if ok else '❌'} " + T("checks.passed_line", name=name, col=col_name(col), detail=det))
    for p_ in r.passed:
        st.markdown(f"- ✅ {R(p_)}")
    for f in r.flags:
        icon = {"ERROR": "❌", "REVIEW": "🟨", "WARNING": "⚠️"}[f.severity]
        fields = ", ".join(report.title(x, lang) for x in f.fields) or "—"
        st.markdown(f"- {icon} " + T("checks.line", msg=f.message, cols=Raw(f"{fields}; {col_name(f.column)}" if f.column else fields),
                                     src=Msg(f"checks.src.{f.source}"), code=Raw(f"`{f.code}`"), codes=False)
                    + (" [" + ", ".join(getattr(f.message, "codes", ())) + "]" if getattr(f.message, "codes", ()) else ""))

if ex.issues:
    with st.expander(T("issues.expander", n=len(ex.issues))):
        for i in ex.issues:
            st.markdown(f"- {R(i, codes=True)}")

csv = pd.DataFrame([{"field": v.field, "column": v.column, "value": v.value, "status": v.status,
                     "status_text": report.status_label(v.status, lang),
                     "pages": ";".join(map(str, v.pages)), "source": " || ".join(v.quotes),
                     "components": R(v.components), "note": R(v.note, codes=True)} for v in ex.values]
                   + [{"field": f"CONFIRM {i['title']}", "column": i["column"], "value": answers[i["key"]],
                       "status": "USER CONFIRMATION", "status_text": T(f"confirm.{answers[i['key']]}"),
                       "note": f"{i['why']} | {T('confirm.reviewer')}: {reviewer or '-'}"}
                      for i in items]).to_csv(index=False)
st.download_button(T("csv.button"), csv, file_name=f"wars_{ticker or 'upload'}_{YR['t']}_{lang}.csv", mime="text/csv")

st.divider()
st.caption(T("app.disclaimer") + " " + T("app.footer_model") + f" {T('app.author')} · [LinkedIn]({LINKEDIN})")
