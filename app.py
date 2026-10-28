"""WARS web app: Window-dressing Accounting Red-Flag Scanner (Beneish M-score) for annual financial statements.

Flow (design approved by Gail, 28 Oct 2026, canvas "WARS App Design"):
  continue as guest -> upload the PDF -> reading -> short result -> download the PDF report / Excel table.

Every text comes from the bilingual catalogue (wars_scanner.text); the ID / EN switch changes the
page and the downloads. The score is shown at once as a provisional result; figures to check and
the assumptions for figures not found go to the checklist in the PDF report (Gail, 28 Oct 2026).

Run:  streamlit run app.py
"""
import base64
import datetime as dt
import hashlib
import html
import os
import tempfile

import streamlit as st

from wars_scanner import pipeline, report, report_pdf, report_xlsx
from wars_scanner.report import NEUTRAL_M, THRESHOLD, dec
from wars_scanner.text import Msg, Num, Raw, fmt_number, render, t, unit_msg

ROOT = os.path.dirname(os.path.abspath(__file__))
LINKEDIN = "https://www.linkedin.com/in/warsiniak"

st.set_page_config(page_title="WARS · Window-dressing Accounting Red-Flag Scanner",
                   page_icon=os.path.join(ROOT, "assets", "wars_icon.png"), layout="wide",
                   initial_sidebar_state="collapsed")

ss = st.session_state
ss.setdefault("page", "gate")
ss.setdefault("lang", "id")
ss.setdefault("upn", 0)
ss.setdefault("_lang_prev", ss["lang"] or "id")


@st.cache_data(show_spinner=False)
def _b64(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


WORDMARK = "data:image/svg+xml;base64," + _b64(os.path.join(ROOT, "assets", "wars_wordmark.svg"))
E = html.escape


def lang():
    return ss.get("lang") or ss.get("_lang_prev") or "id"


def T(key, codes=False, **kw):
    return t(key, lang(), codes, **kw)


def R(x, codes=False):
    return render(x, lang(), codes)


# ------------------------------------------------------------------------------------------------ style
CSS = """
<style>
:root{--ink:#1B1E23;--muted:#5A6069;--soft:#3A3F46;--line:#D9DCD8;--bg:#F6F7F5;--green:#006B53;--accent:#00B088;--red:#C03A3A}
.stApp{background:var(--bg);color:var(--ink)}
header[data-testid="stHeader"],#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stSidebarCollapsedControl"]{display:none !important}
.block-container{max-width:1040px;padding-top:0.6rem !important;padding-bottom:1.5rem !important}
.w-top{display:flex;align-items:center;gap:12px;padding:6px 0}
.w-top img{height:26px;width:auto;display:block}
.w-chip{font-size:12px;font-weight:600;letter-spacing:.08em;color:#6E4700;background:#FBF1DC;border:1px solid #E8D3A6;padding:2px 8px;border-radius:999px}
.w-rule{border-bottom:1px solid var(--line);margin:2px 0 26px}
.w-guest{font-size:13px;color:var(--soft)}
.w-steps{list-style:none;margin:0 0 22px;padding:0;display:flex;gap:10px;flex-wrap:wrap;font-size:13px}
.w-steps li{display:flex;align-items:center;gap:8px;color:var(--muted)}
.w-steps .n{display:inline-flex;width:24px;height:24px;border-radius:50%;border:1px solid #A3A8AE;align-items:center;justify-content:center;font-size:12px}
.w-steps .on{font-weight:600;color:var(--green)} .w-steps .on .n{background:var(--green);color:#fff;border-color:var(--green)}
.w-steps .done{color:var(--green)} .w-steps .done .n{background:#E8F3EF;color:var(--green);border-color:#E8F3EF}
.w-steps .sep{color:#A3A8AE}
.w-h1{margin:0;font-size:28px;font-weight:600;letter-spacing:-.01em;line-height:1.25}
.w-sub{margin:6px 0 22px;color:var(--muted);font-size:15px}
.w-note{margin:14px 0 0;font-size:13px;color:var(--muted)}
.w-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:26px 30px 22px;margin-top:14px}
.w-file{display:flex;align-items:center;gap:12px;padding:14px 18px;border:1px solid var(--line);border-radius:12px;background:#fff;margin:14px 0}
.w-file .ic{display:inline-flex;width:36px;height:36px;border-radius:8px;background:#E8F3EF;color:var(--green);align-items:center;justify-content:center;font-size:11px;font-weight:700}
.w-file .nm{font-weight:600;overflow-wrap:anywhere} .w-file .sz{font-size:13px;color:var(--muted)}
.w-bar{height:8px;border-radius:999px;background:#E3E6E2;overflow:hidden;margin:4px 0 22px;position:relative}
.w-bar div{position:absolute;height:8px;width:40%;background:var(--accent);border-radius:999px;animation:wslide 1.4s ease-in-out infinite}
@keyframes wslide{0%{left:-40%}100%{left:100%}}
.w-list{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:12px;background:#fff}
.w-list li{display:flex;gap:14px;align-items:flex-start;padding:15px 20px;border-bottom:1px solid #ECEEEB}
.w-list li:last-child{border-bottom:0}
.w-list .ok{flex:0 0 auto;display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--green);color:#fff;align-items:center;justify-content:center;font-size:12px}
.w-list .run{flex:0 0 auto;width:22px;height:22px;border-radius:50%;border:2px solid #CFE9DF;border-top-color:var(--accent);box-sizing:border-box;animation:wspin 1s linear infinite}
.w-list .wait{flex:0 0 auto;width:22px;height:22px;border-radius:50%;border:2px solid #D9DCD8;box-sizing:border-box}
.w-list .bad{flex:0 0 auto;display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--red);color:#fff;align-items:center;justify-content:center;font-size:12px}
@keyframes wspin{to{transform:rotate(360deg)}}
.w-list .t{font-weight:600} .w-list .d{font-size:13px;color:var(--muted)}
.w-tk{font-size:13px;font-weight:600;letter-spacing:.08em;color:var(--green)}
.w-name{margin:2px 0 0;font-size:26px;font-weight:600;letter-spacing:-.01em;line-height:1.25}
.w-meta{margin:4px 0 0;font-size:14px;color:var(--muted)}
.w-lbl{font-size:12px;font-weight:600;letter-spacing:.08em;color:var(--muted)}
.w-score{font-family:'IBM Plex Mono',monospace;font-size:56px;font-weight:600;line-height:1.05}
.w-row{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap}
.w-chipok{display:inline-block;font-size:13px;font-weight:600;color:#1F4E43;background:#E8F3EF;border:1px solid #B9D9CD;padding:5px 12px;border-radius:999px}
.w-chiphi{display:inline-block;font-size:13px;font-weight:600;color:#fff;background:var(--red);border:1px solid var(--red);padding:5px 12px;border-radius:999px}
.w-chipnote{font-size:11px;color:#6B6B6B;margin-top:8px;text-align:right}
.w-scale{position:relative;height:64px;margin:24px 0 6px}
.w-scale .tr{position:absolute;left:0;right:0;top:22px;height:10px;border-radius:999px;background:#ECEEF1}
.w-scale .hi{position:absolute;right:0;top:22px;height:10px;border-radius:0 999px 999px 0;background:#F7DCDC}
.w-scale .tick{position:absolute;width:2px}
.w-scale .dot{position:absolute;top:17px;width:20px;height:20px;margin-left:-10px;border-radius:50%;border:3px solid #fff;box-sizing:border-box}
.w-scale .lab{position:absolute;top:44px;font-size:12px;color:var(--muted);white-space:nowrap;transform:translateX(-50%)}
.w-scale .me{position:absolute;top:-4px;transform:translateX(-50%);font-size:12px;font-weight:600;white-space:nowrap}
.w-mono{font-family:'IBM Plex Mono',monospace}
.w-small{margin:0;font-size:13px !important;color:var(--muted)}
.w-note{font-size:13px !important} .w-meta{font-size:14px !important} .w-sub{font-size:15px !important}
.w-drv p{font-size:14px !important} .w-warn p{font-size:14px !important}
.w-tbl th,.w-tbl td{border-left:0 !important;border-right:0 !important;border-top:0 !important}
.w-tbl table{border:0 !important}
.w-warn{display:flex;gap:12px;align-items:flex-start;padding:12px 16px;border-radius:10px;background:#FBF6EA;border:1px solid #EAD9B0;margin-top:18px}
.w-warn p{margin:0;font-size:14px;color:#5C3D00}
.w-err{padding:12px 16px;border-radius:10px;background:#FBF1F1;border:1px solid #EBC4C4;margin-top:14px;font-size:14px;color:#6B1F1F}
.w-h2{margin:30px 0 4px;font-size:18px;font-weight:600}
.w-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:12px}
@media (max-width:760px){.w-grid{grid-template-columns:1fr}.w-score{font-size:44px}}
.w-drv{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px 22px}
.w-drv h3{margin:0;font-size:16px;font-weight:600}
.w-drv .top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:10px}
.w-drv p{margin:0;font-size:14px;line-height:1.55}
.w-push{font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600;color:var(--red)}
.w-tbl{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-top:24px}
.w-tbl .h{margin:0 0 12px;font-size:16px;font-weight:600}
.w-tbl table{width:100%;border-collapse:collapse;font-size:14px;line-height:1.4}
.w-tbl th{padding:8px 10px;font-weight:600;font-size:12px;letter-spacing:.04em;color:var(--soft);text-align:left;border-bottom:1.5px solid var(--ink)}
.w-tbl td{padding:9px 10px;border-bottom:1px solid #ECEEEB;vertical-align:top}
.w-tbl tr:last-child td{border-bottom:0}
.w-tbl .r{text-align:right;font-family:'IBM Plex Mono',monospace;white-space:nowrap}
.w-tbl tr.drv{background:#FBF1F1} .w-tbl tr.drv .p{font-weight:600;color:var(--red)}
.w-foot{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap;padding:16px 0 4px;border-top:1px solid var(--line);margin-top:40px}
.w-foot .dis{margin:0;max-width:720px;font-size:12px;font-style:italic;color:#6B6B6B;line-height:1.5}
.w-foot .by{margin:0;font-size:12px;color:var(--soft)} .w-foot a{color:var(--green)}
/* streamlit widgets */
.stButton button[kind="primary"],.stDownloadButton button[kind="primary"]{background:var(--green);border-color:var(--green);border-radius:10px;min-height:50px;font-weight:600;font-size:16px}
.stButton button[kind="primary"]:hover,.stDownloadButton button[kind="primary"]:hover{background:#00563F;border-color:#00563F}
.stButton button[kind="primary"]:disabled{background:#A9C6BC;border-color:#A9C6BC;color:#fff}
.stButton button[kind="secondary"],.stDownloadButton button[kind="secondary"]{border-radius:10px;border-color:#C9CDD3;background:#fff}
.stDownloadButton button{min-height:50px;font-weight:600;font-size:16px}
[data-testid="stFileUploaderDropzone"]{background:#fff;border:1.5px dashed #9BB8AE;border-radius:14px;padding:40px 24px 34px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;cursor:pointer}
[data-testid="stFileUploaderDropzone"]::before{content:"";width:40px;height:40px;background:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23006B53' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'><path d='M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z'/><path d='M14 3v5h5'/><path d='M12 17v-6'/><path d='M9.5 13.5 12 11l2.5 2.5'/></svg>") no-repeat center/contain}
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"]{background:transparent;border:0;box-shadow:none;color:#1B1E23;font-weight:600;min-height:0;padding:4px 8px}
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] [data-testid="stIconMaterial"]{display:none}
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] p{font-size:0 !important}
[data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-secondary"] p::after{content:var(--w-drop);font-size:15px;font-weight:600}
[data-testid="stFileUploaderDropzoneInstructions"] span{display:none}
[data-testid="stFileUploaderDropzoneInstructions"]::after{content:var(--w-scan);font-size:13px;color:#5A6069}
.st-key-gatecard{background:#fff;border:1px solid var(--line) !important;border-radius:16px;padding:34px 32px 28px !important;box-shadow:0 1px 2px rgba(27,30,35,.04),0 8px 24px rgba(27,30,35,.06);margin-top:56px}
.st-key-dlcard{background:#fff;border:1px solid var(--line) !important;border-radius:16px;padding:22px 26px !important;margin-top:24px}
[data-testid="stExpander"] details{background:#fff;border:1px solid var(--line);border-radius:12px}
[data-testid="stExpander"] summary p{font-weight:600;font-size:14px}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(f"<style>:root{{--w-drop:'{T('ui.up.drop')}';--w-scan:'{T('ui.up.scan')}'}}</style>", unsafe_allow_html=True)


def _keep_lang():
    """The switch can be clicked off; keep the last language instead of none."""
    if ss.get("lang") is None:
        ss["lang"] = ss["_lang_prev"]
    else:
        ss["_lang_prev"] = ss["lang"]


def header(signed_in: bool):
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        st.markdown(f'<div class="w-top"><img src="{WORDMARK}" alt="WARS"><span class="w-chip">BETA</span></div>',
                    unsafe_allow_html=True)
    with right:
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            if signed_in:
                st.markdown(f'<span class="w-guest">{E(T("ui.guest_label"))}</span>', unsafe_allow_html=True)
            st.segmented_control(T("app.lang"), ["id", "en"], format_func=str.upper, key="lang",
                                 label_visibility="collapsed", on_change=_keep_lang)
            if signed_in and st.button(T("ui.logout"), key="logout", type="tertiary"):
                ss.page, ss.pdf = "gate", None
                st.rerun()
    st.markdown('<div class="w-rule"></div>', unsafe_allow_html=True)


def footer():
    st.markdown(f'<div class="w-foot"><p class="dis">{E(T("app.disclaimer"))}</p>'
                f'<p class="by">{E(T("app.author"))} · <a href="{LINKEDIN}" target="_blank">LinkedIn</a></p></div>',
                unsafe_allow_html=True)


def steps(active):
    names = [T("ui.step.upload"), T("ui.step.read"), T("ui.step.result")]
    out = []
    for i, n in enumerate(names, 1):
        cls, mark = ("done", "✓") if i < active else ("on", str(i)) if i == active else ("", str(i))
        out.append(f'<li class="{cls}"><span class="n">{mark}</span>{E(n)}</li>')
    st.markdown('<ol class="w-steps">' + '<li class="sep">—</li>'.join(out) + "</ol>", unsafe_allow_html=True)


def _size(n):
    return f"{dec(n / 1048576, 1, lang())} MB" if n >= 1048576 else f"{dec(n / 1024, 0, lang())} KB"


# ------------------------------------------------------------------------------------------------ analysis
@st.cache_data(show_spinner=False, max_entries=20)
def analyse(data: bytes):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "report.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
        r = pipeline.run(path, "UPLOAD")
    r = pipeline.apply_provisional(r)
    r.extraction.statements = {}          # not needed after reading; keeps the cache small
    return r


@st.cache_data(show_spinner=False)
def page_count(data: bytes):
    try:
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(data))
    except Exception:                       # noqa: BLE001  the reader reports damaged files itself
        return None


@st.cache_data(show_spinner=False, max_entries=40)
def make_pdf(sha, lg, name, _r):
    return report_pdf.build(_r, lg, name, sha)


@st.cache_data(show_spinner=False, max_entries=40)
def make_xlsx(sha, lg, name, generated, _r):
    return report_xlsx.build(_r, lg, name, sha, generated)


# ------------------------------------------------------------------------------------------------ pages
def page_gate():
    header(False)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.container(key="gatecard"):
            st.markdown(f'<div style="text-align:center"><img src="{WORDMARK}" alt="WARS" style="width:200px;height:auto">'
                        f'<h1 style="margin:22px 0 6px;font-size:22px;font-weight:600;letter-spacing:-.01em;padding:0">'
                        f'{E(T("app.title"))}</h1><p style="margin:0 0 20px;color:#5A6069;font-size:14px">'
                        f'{E(T("ui.tagline"))}</p></div>', unsafe_allow_html=True)
            if st.button("👤  " + T("ui.guest"), type="primary", use_container_width=True, key="guest"):
                ss.page = "upload"
                st.rerun()
    footer()


def page_upload():
    header(True)
    _, mid, _ = st.columns([0.55, 3, 0.55])
    with mid:
        steps(1)
        st.markdown(f'<h1 class="w-h1">{E(T("ui.up.title"))}</h1><p class="w-sub">{E(T("ui.up.sub"))}</p>',
                    unsafe_allow_html=True)
        up = st.file_uploader(T("ui.up.drop"), type=["pdf"], key=f"upload{ss.upn}", label_visibility="collapsed")
        if up is not None:
            st.markdown(f"<style>.st-key-upload{ss.upn}{{display:none}}</style>", unsafe_allow_html=True)
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            with c1:
                st.markdown(f'<div class="w-file"><span class="ic">PDF</span><div><div class="nm">{E(up.name)}</div>'
                            f'<div class="sz">{E(T("ui.up.ready", size=Raw(_size(up.size))))}</div></div></div>',
                            unsafe_allow_html=True)
            with c2:
                if st.button(T("ui.up.replace"), key="replace", use_container_width=True):
                    ss.upn += 1
                    st.rerun()
        if st.button(T("ui.up.start"), type="primary", use_container_width=True, disabled=up is None, key="start"):
            data = up.getvalue()
            ss.pdf = {"name": up.name, "data": data, "sha": hashlib.sha256(data).hexdigest()}
            ss.page = "proc"
            st.rerun()
        st.markdown(f'<p class="w-note">{E(T("ui.up.bank"))}</p>', unsafe_allow_html=True)
    footer()


def _proc_list(r=None):
    """The reading steps; filled in from the result once it is there."""
    if r is None:
        rows = [("run", T("ui.proc.fs"), ""), ("wait", T("ui.proc.notes"), ""), ("wait", T("ui.proc.checks"), ""),
                ("wait", T("ui.proc.calc"), "")]
    else:
        ex = r.extraction
        loc = (ex.fs_location or {}).get("chosen") or {}
        pg = lambda k: ", ".join(map(str, loc.get(k) or [])) or "—"          # noqa: E731
        fy = ex.fiscal_year
        fs_ok = bool(loc.get("position") and loc.get("profit_loss"))
        n_ok = sum(1 for x in ex.checks if x[2]) + len(r.passed)
        rows = [("ok" if fs_ok else "bad", T("ui.proc.fs"),
                 T("ui.proc.fs_detail", a=pg("position"), b=pg("profit_loss"), c=pg("cash_flow"),
                   t=fy or "?", t1=(fy - 1) if fy else "?") if fs_ok else ""),
                ("ok" if loc.get("notes_start") else "bad", T("ui.proc.notes"), T("ui.proc.notes_detail")),
                ("ok" if not r.errors else "bad", T("ui.proc.checks"),
                 T("ui.proc.checks_detail", ok=n_ok, err=len(r.errors) + sum(1 for x in ex.checks if not x[2]))),
                ("ok" if r.m_score is not None else "bad", T("ui.proc.calc").rstrip("…"), "")]
    li = []
    for state, title, detail in rows:
        icon = {"ok": '<span class="ok">✓</span>', "bad": '<span class="bad">!</span>', "run": '<span class="run"></span>',
                "wait": '<span class="wait"></span>'}[state]
        li.append(f'<li>{icon}<div><div class="t">{E(title)}</div>'
                  + (f'<div class="d">{E(detail)}</div>' if detail else "") + "</div></li>")
    return '<ul class="w-list">' + "".join(li) + "</ul>"


def page_proc():
    st.markdown('<style>[data-stale="true"]{display:none !important}</style>', unsafe_allow_html=True)
    header(True)
    pdf = ss.get("pdf")
    if not pdf:
        ss.page = "upload"
        st.rerun()
    _, mid, _ = st.columns([0.55, 3, 0.55])
    with mid:
        steps(2)
        n = page_count(pdf["data"])
        st.markdown(f'<h1 class="w-h1">{E(T("ui.proc.title"))}</h1>'
                    f'<p class="w-sub">{E(T("ui.proc.sub", name=Raw(pdf["name"]), pages=n if n else "?"))}</p>'
                    f'<div class="w-bar"><div></div></div>' + _proc_list(), unsafe_allow_html=True)
        try:
            analyse(pdf["data"])
        except Exception as e:                                     # noqa: BLE001
            st.error(T("app.pdf_error"))
            with st.expander(T("app.pdf_error_detail")):
                st.code(f"{type(e).__name__}: {e}")
            if st.button(T("ui.res.another"), key="back"):
                ss.page, ss.pdf = "upload", None
                ss.upn += 1
                st.rerun()
            footer()
            return
    ss.page = "result"
    st.rerun()


def _scale(m, ticker):
    lo = min(-3.5, round((m - 0.3) * 2) / 2)
    hi = max(-0.5, round((m + 0.3) * 2) / 2)
    x = lambda v: f"{(min(max(v, lo), hi) - lo) / (hi - lo) * 100:.2f}%"        # noqa: E731
    col = "#C03A3A" if m > THRESHOLD else "#006B53"
    L = lang()
    return (f'<div class="w-scale" role="img" aria-label="M-score {E(dec(m, 2, L))}">'
            f'<div class="tr"></div><div class="hi" style="left:{x(THRESHOLD)}"></div>'
            f'<div class="tick" style="left:{x(NEUTRAL_M)};top:16px;height:22px;background:#7A8089"></div>'
            f'<div class="tick" style="left:{x(THRESHOLD)};top:13px;height:28px;background:#1B1E23"></div>'
            f'<div class="dot" style="left:{x(m)};background:{col};box-shadow:0 0 0 1px {col}"></div>'
            f'<div class="me" style="left:{x(m)};color:{col}">{E((ticker + " ") if ticker else "")}{E(dec(m, 2, L))}</div>'
            f'<div class="lab w-mono" style="left:0;transform:none">{E(dec(lo, 2, L))}</div>'
            f'<div class="lab" style="left:{x(NEUTRAL_M)}">{E(T("ui.res.scale_neutral", n=Num(NEUTRAL_M, 2)))}</div>'
            f'<div class="lab" style="left:{x(THRESHOLD)};font-weight:600;color:#1B1E23">'
            f'{E(T("ui.res.scale_thr", thr=Num(THRESHOLD, 2)))}</div>'
            f'<div class="lab w-mono" style="right:0;left:auto;transform:none">{E(dec(hi, 2, L))}</div></div>')


def page_result():
    header(True)
    pdf = ss.get("pdf")
    if not pdf:
        ss.page = "upload"
        st.rerun()
    r = analyse(pdf["data"])
    L = lang()
    ex = r.extraction
    fy = ex.fiscal_year
    yt, yt1 = (str(fy), str(fy - 1)) if fy else ("t", "t−1")
    ticker, name = report.issuer_line(r, L)
    unit = unit_msg(ex.unit_scale, getattr(ex, "currency", None))
    stype = Msg("ui.res.stype.Consolidated") if ex.statement_type == "Consolidated" else Msg("ui.res.stype.unknown")

    steps(3)
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    with a:
        meta = T("ui.res.meta", t=yt, t1=yt1, stype=stype, unit=unit, pages=ex.n_pages) if not r.unreadable else \
            T("ui.res.meta_file", name=Raw(pdf["name"]), pages=ex.n_pages)
        st.markdown((f'<div class="w-tk">{E(ticker)}</div>' if ticker else "")
                    + f'<div class="w-name">{E(name)}</div><p class="w-meta">{E(meta)}</p>', unsafe_allow_html=True)
    with b:
        if st.button(T("ui.res.another"), key="another", use_container_width=True):
            ss.page, ss.pdf = "upload", None
            ss.upn += 1
            st.rerun()

    # ------------------------------------------------------------------ score card
    head, detail, level = report.verdict(r, None, L, provisional_note=False)
    items = report.checklist_rows(r, L) if not r.unreadable else []
    m = r.m_score
    if m is not None:
        above = m > THRESHOLD
        chip = (f'<span class="w-chiphi">{E(T("ui.res.chip_above", thr=Num(THRESHOLD, 2)))}</span>' if above else
                f'<span class="w-chipok">{E(T("ui.res.chip_below", thr=Num(THRESHOLD, 2)))}</span>'
                f'<div class="w-chipnote">{E(T("ui.res.chip_note"))}</div>')
        below_base = T("v.below_detail")
        extra = detail[len(below_base):].strip() if not above and detail.startswith(below_base) else detail
        body = (f'<div class="w-row"><div><div class="w-lbl">BENEISH M-SCORE</div>'
                f'<div class="w-score">{E(dec(m, 2, L))}</div></div><div style="text-align:right">{chip}</div></div>'
                + _scale(m, ticker)
                + f'<p class="w-small">{E(T("app.threshold", thr=Num(THRESHOLD, 2)))}</p>'
                + (f'<p class="w-small" style="margin-top:8px;color:#3A3F46">{E(extra)}</p>' if extra else ""))
        if items:
            n_ass = sum(1 for x in items if x["assumed"])
            body += (f'<div class="w-warn"><span style="color:#8A5A00;font-weight:700">ⓘ</span><p><strong>'
                     f'{E(T("ui.res.provisional"))}</strong> {E(T("ui.res.provisional_detail", n=len(items)))}'
                     + (f' {E(T("ui.res.assumed", n=n_ass))}' if n_ass else "") + "</p></div>")
    else:
        body = (f'<div class="w-lbl">BENEISH M-SCORE</div><div style="font-size:24px;font-weight:600;margin:6px 0 8px">'
                f'{E(head)}</div><p style="margin:0;font-size:15px;color:#3A3F46">{E(detail)}</p>')
        for f in r.errors:
            body += f'<div class="w-err">{E(T("app.check_failed", msg=f.message))}</div>'
    st.markdown(f'<section class="w-card">{body}</section>', unsafe_allow_html=True)

    # ------------------------------------------------------------------ drivers and the eight indices
    if m is not None:
        drv = report.drivers(r, lang=L)
        if drv:
            cards = []
            for d in drv:
                f = report.finding(r, d["index"], None, L)
                cards.append(f'<article class="w-drv"><div class="top"><h3>{E(d["index"])} · {E(d["name"])}</h3>'
                             f'<span class="w-push">{E(fmt_number(d["push_vs_neutral"], L, 2, True))}</span></div>'
                             f'<p>{E(f["a"])}</p>'
                             + "".join(f'<p class="w-small" style="margin-top:8px">{E(c)}</p>' for c in f["caveats"])
                             + "</article>")
            st.markdown(f'<div class="w-h2">{E(T("drivers.title"))}</div><p class="w-small">{E(T("drivers.note"))}</p>'
                        f'<div class="w-grid">{"".join(cards)}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="w-h2">{E(T("drivers.title"))}</div><p class="w-small">{E(T("drivers.none"))}</p>',
                        unsafe_allow_html=True)
        names = {d["index"] for d in drv}
        trs = "".join(
            f'<tr class="{"drv" if x["index"] in names else ""}"><td style="font-weight:600">{x["index"]}</td>'
            f'<td>{E(x["name"])}</td><td class="r">{E(dec(x["value"], 3, L))}</td>'
            f'<td class="r p">{E(report.fmt_push(x["push_vs_neutral"], L) if x["push_vs_neutral"] is not None else "—")}</td></tr>'
            for x in report.index_rows(r, L))
        st.markdown(f'<section class="w-tbl"><div class="h">{E(T("ui.idx.title"))}</div><div style="overflow-x:auto"><table><thead><tr>'
                    f'<th>{E(T("ui.idx.col.index"))}</th><th>{E(T("ui.idx.col.name"))}</th>'
                    f'<th style="text-align:right">{E(T("ui.idx.col.value"))}</th>'
                    f'<th style="text-align:right">{E(T("ui.idx.col.push"))}</th></tr></thead><tbody>{trs}</tbody></table></div>'
                    f'<p class="w-small" style="margin-top:12px;font-size:12px">{E(T("ui.idx.minor"))}</p></section>',
                    unsafe_allow_html=True)

    # ------------------------------------------------------------------ downloads
    if not r.unreadable:
        with st.container(key="dlcard"):
            st.markdown(f'<div style="margin:0 0 4px;font-size:18px;font-weight:600">{E(T("ui.dl.title"))}</div>',
                        unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M WIB")
            base_name = f"WARS_{ticker or 'NA'}_{yt}_{L.upper()}"
            with c1:
                st.download_button("⤓  " + T("ui.dl.pdf"), make_pdf(pdf["sha"], L, pdf["name"], r),
                                   file_name=base_name + ".pdf", mime="application/pdf", type="primary",
                                   use_container_width=True, on_click="ignore", key="dl_pdf")
                st.markdown(f'<p class="w-small">{E(T("ui.dl.pdf_sub"))}</p>', unsafe_allow_html=True)
            with c2:
                st.download_button("▦  " + T("ui.dl.xlsx"), make_xlsx(pdf["sha"], L, pdf["name"], stamp, r),
                                   file_name=base_name + ".xlsx", type="secondary", use_container_width=True,
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   on_click="ignore", key="dl_xlsx")
                st.markdown(f'<p class="w-small">{E(T("ui.dl.xlsx_sub", t=yt, t1=yt1))}</p>', unsafe_allow_html=True)
            st.markdown(f'<p class="w-small" style="font-size:12px;margin-top:10px">{E(T("ui.dl.lang"))}</p>',
                        unsafe_allow_html=True)

    # ------------------------------------------------------------------ methodology and reading details
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    with st.expander(T("app.method.title")):
        st.markdown(E(T("ui.method")))
    with st.expander(T("ui.proc.summary") if not r.unreadable else T("ui.read_details")):
        if not r.unreadable:
            st.markdown(_proc_list(r), unsafe_allow_html=True)
        for i in ex.issues:
            st.markdown("- " + E(R(i)))
    footer()


{"gate": page_gate, "upload": page_upload, "proc": page_proc, "result": page_result}.get(ss.page, page_gate)()
