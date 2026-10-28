"""The downloadable PDF report, in Indonesian or English (report design r0/r1, R-01 to R-17).

Built with reportlab (pure Python, so it runs on Streamlit Community Cloud). Every sentence comes
from the text catalogue; numbers follow the language (R-04). The footer disclaimer is English in
both versions (R-06, R-07, R-11). Sections:

  1 Overview · 2 Score breakdown · 3 Findings (B r1 §4: A, C, D) · 4 Checklist (the user's
  confirmation, moved here from the app on 28 Oct 2026) · Appendix A figures read ·
  Appendix B cross-checks (failed and review first, each with its explanation) · Appendix C reading notes
  (numbered, own page) · Methodology and limitations. Rule codes are never shown (Gail, 28 Oct 2026).
"""
from __future__ import annotations

import datetime as dt
import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.pdfgen import canvas as rl_canvas

from . import report
from .report import NEUTRAL_M, THRESHOLD, dec
from .text import Num, render, t, unit_msg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "assets", "fonts")
LOGO = os.path.join(ROOT, "assets", "wars_wordmark.png")

INK, MUTED, SOFT = colors.HexColor("#1B1E23"), colors.HexColor("#5A6069"), colors.HexColor("#3A3F46")
LINE, LINE2 = colors.HexColor("#C9CDD3"), colors.HexColor("#E3E6E2")
GREEN, ACCENT, RED = colors.HexColor("#006B53"), colors.HexColor("#00B088"), colors.HexColor("#C03A3A")
RED_BG, AMBER_BG, AMBER_INK, GREEN_BG = (colors.HexColor("#FBF1F1"), colors.HexColor("#FBF1DC"),
                                         colors.HexColor("#6E4700"), colors.HexColor("#E8F3EF"))
CELL = {report.GREEN: colors.white, report.YELLOW: colors.HexColor("#FDF4DC"), report.RED: colors.HexColor("#F9E1E0")}

MONTHS = {"id": "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des".split(),
          "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()}


def _fonts():
    if "Plex" in pdfmetrics.getRegisteredFontNames():
        return
    for name, f in (("Plex", "IBMPlexSans-Regular"), ("Plex-It", "IBMPlexSans-Italic"),
                    ("Plex-Semi", "IBMPlexSans-SemiBold"), ("Plex-Bold", "IBMPlexSans-Bold"),
                    ("PlexMono", "IBMPlexMono-Regular"), ("PlexMono-Semi", "IBMPlexMono-SemiBold")):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONTS, f + ".ttf")))
    pdfmetrics.registerFontFamily("Plex", normal="Plex", bold="Plex-Semi", italic="Plex-It", boldItalic="Plex-Semi")


def _styles():
    s = {}
    s["body"] = ParagraphStyle("body", fontName="Plex", fontSize=9.5, leading=13.5, textColor=INK)
    s["small"] = ParagraphStyle("small", parent=s["body"], fontSize=8, leading=11, textColor=SOFT)
    s["muted"] = ParagraphStyle("muted", parent=s["small"], textColor=MUTED)
    s["cell"] = ParagraphStyle("cell", parent=s["body"], fontSize=8, leading=10.5)
    s["cellm"] = ParagraphStyle("cellm", parent=s["cell"], fontName="PlexMono", fontSize=7.6, alignment=TA_RIGHT)
    s["tiny"] = ParagraphStyle("tiny", parent=s["cell"], fontSize=7, leading=9, textColor=SOFT)
    s["head"] = ParagraphStyle("head", parent=s["cell"], fontName="Plex-Semi", fontSize=7.2, textColor=SOFT)
    s["h1"] = ParagraphStyle("h1", fontName="Plex-Semi", fontSize=17, leading=21, textColor=INK)
    s["h2"] = ParagraphStyle("h2", fontName="Plex-Semi", fontSize=11.5, leading=15, textColor=INK, spaceBefore=4)
    s["label"] = ParagraphStyle("label", fontName="Plex-Semi", fontSize=7.2, leading=9.5, textColor=GREEN)
    s["field"] = ParagraphStyle("field", fontName="Plex", fontSize=7, leading=9, textColor=MUTED)
    s["fieldv"] = ParagraphStyle("fieldv", parent=s["body"], fontSize=9, leading=12)
    s["score"] = ParagraphStyle("score", fontName="PlexMono-Semi", fontSize=34, leading=38, textColor=INK)
    return s


def _x(s):
    return escape(str(s or ""))


def _date(d, lang):
    return f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"


class _Numbered(rl_canvas.Canvas):
    """Two-pass canvas so the footer can say 'page n of m'."""

    def __init__(self, *a, **kw):
        self._info = kw.pop("info")
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            _decorate(self, self._pageNumber, n, self._info)
            super().showPage()
        super().save()


def _decorate(c, page, pages, info):
    lang = info["lang"]
    w, h = A4
    c.saveState()
    # header: wordmark left, report identity right (R-10, R-16)
    try:
        c.drawImage(LOGO, 18 * mm, h - 21 * mm, width=30 * mm, height=30 * mm * 358 / 1392, mask="auto")
    except Exception:                                    # noqa: BLE001  logo missing: header text still shown
        pass
    c.setFont("Plex", 6.8)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, h - 24 * mm, "Window-dressing Accounting Red-Flag Scanner")
    c.setFont("Plex-Semi", 9)
    c.setFillColor(INK)
    c.drawRightString(w - 18 * mm, h - 13 * mm, t("rep.title", lang))
    c.setFont("Plex", 7.5)
    c.setFillColor(MUTED)
    c.drawRightString(w - 18 * mm, h - 17.5 * mm, info["who"])
    c.setFont("PlexMono", 7)
    c.drawRightString(w - 18 * mm, h - 21.5 * mm, info["rid"] + " · " + t("rep.version", lang))
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(18 * mm, h - 27 * mm, w - 18 * mm, h - 27 * mm)
    # footer: identity left, English disclaimer right (R-06, R-07, R-08, R-11)
    c.line(18 * mm, 22 * mm, w - 18 * mm, 22 * mm)
    c.setFont("Plex-Bold", 7.5)
    c.setFillColor(GREEN)
    c.drawString(18 * mm, 18 * mm, "WARS")
    c.setFont("Plex", 6.8)
    c.setFillColor(SOFT)
    c.drawString(18 * mm, 14.8 * mm, "Window-dressing Accounting Red-Flag Scanner · Beta")
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 11.6 * mm, t("rep.page", lang, n=page, m=pages) + " · " + info["date"])
    c._annotationCount = info.setdefault("annots", 0)      # the two-pass canvas restores the page state; keep
    _contact(c, 18 * mm, 6.6 * mm, lang)                  # link names unique across pages
    info["annots"] = c._annotationCount
    p = Paragraph(_x(t("rep.footer_disclaimer", lang)),
                  ParagraphStyle("f", fontName="Plex-It", fontSize=6.6, leading=8.6, textColor=colors.HexColor("#6B6B6B"),
                                 alignment=TA_RIGHT))
    pw, ph = p.wrap(98 * mm, 20 * mm)
    p.drawOn(c, w - 18 * mm - pw, 19.2 * mm - ph)
    c.restoreState()


LINKEDIN_URL = "https://www.linkedin.com/in/warsiniak"
CONTACT_EMAIL = "warsiniak@gmail.com"


def _contact(c, x, y, lang):
    """'Contact us' followed by two icons of the same size on one line (Gail, 28 Oct 2026): a profile icon that
    opens LinkedIn and an envelope icon that opens an email. Generic icons are drawn, not LinkedIn's logo."""
    c.setFont("Plex-Semi", 6.8)
    c.setFillColor(SOFT)
    label = t("rep.contact", lang)
    c.drawString(x, y, label)
    s, gap = 3.4 * mm, 1.6 * mm
    x += c.stringWidth(label, "Plex-Semi", 6.8) + 2.4 * mm
    bottom = y + 0.85 * mm - s / 2                      # icons centred on the text's x-height
    for kind, url in (("profile", LINKEDIN_URL), ("mail", "mailto:" + CONTACT_EMAIL)):
        c.setFillColor(GREEN)
        c.roundRect(x, bottom, s, s, 0.6 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.white)
        if kind == "profile":
            c.circle(x + s / 2, bottom + s * 0.64, s * 0.15, stroke=0, fill=1)
            c.wedge(x + s * 0.22, bottom - s * 0.12, x + s * 0.78, bottom + s * 0.52, 0, 180, stroke=0, fill=1)
        else:
            c.setLineWidth(0.5)
            l, r_, b, t_ = x + s * 0.2, x + s * 0.8, bottom + s * 0.28, bottom + s * 0.72
            c.rect(l, b, r_ - l, t_ - b, stroke=1, fill=0)
            pth = c.beginPath()
            pth.moveTo(l, t_)
            pth.lineTo((l + r_) / 2, (b + t_) / 2)
            pth.lineTo(r_, t_)
            c.drawPath(pth, stroke=1, fill=0)
        c.linkURL(url, (x, bottom, x + s, bottom + s), relative=0)
        x += s + gap


class _Scale(Flowable):
    """M-score scale: neutral company, the −1.78 threshold and this report's score (as in the app)."""

    def __init__(self, m, ticker, lang, width):
        super().__init__()
        self.m, self.ticker, self.lang, self.width, self.height = m, ticker, lang, width, 17 * mm

    def draw(self):
        c, w = self.canv, self.width
        lo, hi = min(-3.5, (self.m or 0) - 0.3 if self.m is not None else -3.5), max(-0.5, (self.m or -9) + 0.3)
        x = lambda v: (v - lo) / (hi - lo) * w                    # noqa: E731
        y = 7 * mm
        c.setFillColor(colors.HexColor("#ECEEF1"))
        c.roundRect(0, y, w, 2.6 * mm, 1.3 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#F7DCDC"))
        c.rect(x(THRESHOLD), y, w - x(THRESHOLD), 2.6 * mm, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.rect(x(NEUTRAL_M) - 0.3, y - 1 * mm, 0.6, 4.6 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.rect(x(THRESHOLD) - 0.4, y - 1.6 * mm, 0.8, 5.8 * mm, stroke=0, fill=1)
        c.setFont("PlexMono", 7)
        c.setFillColor(MUTED)
        c.drawString(0, 2 * mm, dec(lo, 2, self.lang))
        c.drawRightString(w, 2 * mm, dec(hi, 2, self.lang))
        c.setFont("Plex", 7)
        c.drawCentredString(x(NEUTRAL_M), 2 * mm, t("ui.res.scale_neutral", self.lang, n=Num(NEUTRAL_M, 2)))
        c.setFont("Plex-Semi", 7)
        c.setFillColor(INK)
        c.drawCentredString(x(THRESHOLD), 2 * mm, t("ui.res.scale_thr", self.lang, thr=Num(THRESHOLD, 2)))
        if self.m is not None:
            col = RED if self.m > THRESHOLD else GREEN
            c.setFillColor(col)
            c.setStrokeColor(colors.white)
            c.setLineWidth(1.5)
            c.circle(x(self.m), y + 1.3 * mm, 2.4 * mm, stroke=1, fill=1)
            c.setFont("Plex-Semi", 7.5)
            c.drawCentredString(x(self.m), y + 5 * mm, f"{self.ticker} {dec(self.m, 2, self.lang)}".strip())


def _section(story, title, S, number=None):
    story.append(Paragraph(_x(title), S["h1"]))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Table([[""]], colWidths=["100%"], rowHeights=[0.9 * mm],
                       style=[("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story.append(Spacer(1, 4 * mm))


def _table(rows, widths, S, head=True, zebra=False, extra=None):
    tb = Table(rows, colWidths=widths, repeatRows=1 if head else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
             ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE2)]
    if head:
        style += [("LINEBELOW", (0, 0), (-1, 0), 1, INK)]
    style += extra or []
    tb.setStyle(TableStyle(style))
    return tb


def build(r, lang="id", file_name="", sha="", now=None) -> bytes:
    """The PDF report for a provisional result `r` (pipeline.apply_provisional)."""
    _fonts()
    S = _styles()
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=7)))      # WIB
    ex = r.extraction
    fy = ex.fiscal_year
    yt, yt1 = (str(fy), str(fy - 1)) if fy else ("t", "t−1")
    ticker, name = report.issuer_line(r, lang)
    rid = f"WARS-{ticker or 'NA'}-FY{fy or 'NA'}-{(sha or '')[:8]}-{lang.upper()}"
    who = f"{name} ({ticker})" if ticker else name
    info = {"lang": lang, "who": f"{who} · {yt} vs {yt1}", "rid": rid, "date": _date(now, lang)}
    unit = unit_msg(ex.unit_scale, getattr(ex, "currency", None))
    W = A4[0] - 36 * mm

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=32 * mm,
                          bottomMargin=27 * mm, title=f"WARS {ticker} {yt}", author="WARS (Warsini)",
                          subject=t("rep.title", lang))
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(18 * mm, 27 * mm, W, A4[1] - 59 * mm, id="f",
                                                             leftPadding=0, rightPadding=0, topPadding=0,
                                                             bottomPadding=0)])])
    story = []
    P = lambda s, st="body": Paragraph(_x(s), S[st])               # noqa: E731

    # ------------------------------------------------------------------------------ 1 Overview
    _section(story, t("rep.s1", lang), S)
    stype = t(f"ui.res.stype.{ex.statement_type}" if ex.statement_type == "Consolidated" else "ui.res.stype.unknown", lang)
    grid = [[P(t("rep.f.entity", lang), "field"), P(t("rep.f.ticker", lang), "field"), P(t("rep.f.period", lang), "field")],
            [P(name, "fieldv"), P(ticker or "—", "fieldv"), P(t("rep.period", lang, t=yt, t1=yt1), "fieldv")],
            [P(t("rep.f.basis", lang), "field"), P(t("rep.f.unit", lang), "field"), P(t("rep.f.source", lang), "field")],
            [P(stype, "fieldv"), P(render(unit, lang), "fieldv"),
             P(t("rep.source", lang, name=file_name, pages=ex.n_pages, sha=(sha or "")[:16] + "…"), "fieldv")]]
    story.append(Table(grid, colWidths=[W * 0.36, W * 0.22, W * 0.42],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 1), (-1, 1), 6), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    story.append(Spacer(1, 5 * mm))

    head, detail, level = report.verdict(r, None, lang, provisional_note=False)
    m = r.m_score
    items = report.checklist_rows(r, lang)
    if m is not None:
        above = m > THRESHOLD
        chip = t("ui.res.chip_above", lang, thr=Num(THRESHOLD, 2)) if above else \
            t("ui.res.chip_below", lang, thr=Num(THRESHOLD, 2))
        chip_p = Paragraph(f'<font color="{"#FFFFFF" if above else "#1F4E43"}">{_x(chip)}</font>',
                           ParagraphStyle("chip", fontName="Plex-Semi", fontSize=8.5, leading=11, alignment=TA_RIGHT))
        right = [chip_p]
        if not above:
            right.append(Paragraph(_x(t("ui.res.chip_note", lang)), ParagraphStyle(
                "cn", fontName="Plex", fontSize=6.8, leading=9, textColor=colors.HexColor("#6B6B6B"), alignment=TA_RIGHT)))
        top = Table([[[P(t("rep.score_label", lang), "field"),
                       Paragraph(dec(m, 2, lang), S["score"])], right]], colWidths=[W * 0.5 - 8 * mm, W * 0.5 - 8 * mm],
                    style=[("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)])
        box = [top, Spacer(1, 3 * mm), _Scale(m, ticker, lang, W - 16 * mm), Spacer(1, 1 * mm),
               P(t("app.threshold", lang, thr=Num(THRESHOLD, 2)), "muted")]
    else:
        box = [P(t("rep.score_label", lang), "field"), Paragraph(_x(head), S["h2"]), P(detail)]
    if items and m is not None:
        box += [Spacer(1, 3 * mm), Table([[Paragraph(
            f"<b>{_x(t('ui.res.provisional', lang))}</b> {_x(t('rep.provisional_detail', lang, n=len(items)))}",
            ParagraphStyle("pv", parent=S["small"], textColor=colors.HexColor("#5C3D00")))]], colWidths=[W - 16 * mm],
            style=[("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBF6EA")),
                   ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#EAD9B0")), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)])]
    story.append(Table([[box]], colWidths=[W], style=[("BOX", (0, 0), (-1, -1), 0.6, LINE),
                                                     ("LEFTPADDING", (0, 0), (-1, -1), 8 * mm),
                                                     ("RIGHTPADDING", (0, 0), (-1, -1), 8 * mm),
                                                     ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                                                     ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm)]))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(_x(t("rep.summary", lang)), S["h2"]))
    if m is not None:
        story.append(P(head + ". " + detail))
    story.append(Spacer(1, 4 * mm))

    used = [v for v in ex.values if v.field in report.FIELD_ORDER]
    n_found = sum(1 for v in used if v.status in ("FOUND", "USER SET"))
    boxes = [[[P(t("rep.box.figures", lang), "field"), P(t("rep.box.figures_v", lang, a=n_found, b=len(used)), "fieldv"),
               P(t("rep.box.figures_d", lang, n=len(items)), "small")],
              [P(t("rep.box.user", lang), "field"),
               Table([[P(t("rep.box.user_v", lang), "small")]],
                     style=[("BACKGROUND", (0, 0), (-1, -1), AMBER_BG), ("BOX", (0, 0), (-1, -1), 0.5, AMBER_INK),
                            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)], hAlign="LEFT"),
               P(t("rep.box.user_d", lang), "small")]]]
    story.append(Table(boxes, colWidths=[W / 2 - 2 * mm] * 2, hAlign="LEFT",
                       style=[("BOX", (0, 0), (0, 0), 0.6, LINE), ("BOX", (1, 0), (1, 0), 0.6, LINE),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))

    # ------------------------------------------------------------------------------ 2 Score breakdown
    if m is not None:
        story.append(PageBreak())
        _section(story, t("rep.s2", lang), S)
        story.append(P(t("rep.breakdown_intro", lang, t=yt, t1=yt1, n=Num(NEUTRAL_M, 2))))
        story.append(Spacer(1, 3 * mm))
        rows = [[P(t("ui.idx.col.index", lang), "head"), P(t("ui.idx.col.name", lang), "head"),
                 P(t("ui.idx.col.value", lang), "head"), P(t("rep.col.coef", lang), "head"),
                 P(t("ui.idx.col.push", lang), "head"), "", P(t("rep.col.trace", lang), "head")]]
        extra, total = [], 0.0
        idx = report.index_rows(r, lang)
        top_push = max([abs(x["push_vs_neutral"]) for x in idx if x["push_vs_neutral"] is not None] or [1])
        drv = {d["index"] for d in report.drivers(r, lang=lang)}
        for i, x in enumerate(idx, 1):
            pu = x["push_vs_neutral"]
            total += pu or 0
            bar = _Bar(pu, top_push, 22 * mm)
            rows.append([Paragraph(f"<b>{x['index']}</b>", S["cell"]), P(x["name"], "cell"),
                         Paragraph(dec(x["value"], 3, lang), S["cellm"]),
                         Paragraph(dec(x["coefficient"], 3, lang), S["cellm"]),
                         Paragraph(dec(pu, 3, lang) if pu is None else report.fmt_push(pu, lang), S["cellm"]), bar,
                         P(report.index_sources(r, x["index"], lang), "tiny")])
            if x["index"] in drv:
                extra.append(("BACKGROUND", (0, i), (-1, i), RED_BG))
        story.append(_table(rows, [12 * mm, 36 * mm, 14 * mm, 14 * mm, 16 * mm, 25 * mm, W - 117 * mm], S,
                            extra=extra + [("VALIGN", (5, 1), (5, -1), "MIDDLE")]))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_x(t("rep.sum_line", lang, n=Num(NEUTRAL_M, 3), p=Num(m - NEUTRAL_M, 3, True), m=Num(m, 3),
                                    thr=Num(THRESHOLD, 2))),
                               ParagraphStyle("sum", parent=S["body"], fontName="Plex-Semi", alignment=TA_RIGHT)))

    # ------------------------------------------------------------------------------ 3 Findings
    story.append(PageBreak())
    _section(story, t("rep.s3", lang), S)
    if m is None:
        story.append(P(t("rep.no_score", lang)))
    else:
        drv = report.drivers(r, lang=lang)
        if not drv:
            story.append(P(t("rep.no_findings", lang)))
        for n, d in enumerate(drv, 1):
            f = report.finding(r, d["index"], None, lang)
            block = [Table([[Paragraph(_x(t("rep.finding", lang, n=n, idx=d["index"]) + " · " + d["name"]), S["h2"]),
                             Paragraph(f'<font color="#FFFFFF">{_x(t("rep.push_tag", lang, p=Num(d["push_vs_neutral"], 3, True)))}</font>',
                                       ParagraphStyle("tag", fontName="Plex-Semi", fontSize=7.5, leading=10,
                                                      alignment=TA_RIGHT))]],
                           colWidths=[W - 40 * mm, 40 * mm],
                           style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (1, 0), (1, 0), RED),
                                  ("LEFTPADDING", (0, 0), (0, 0), 0), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ACCENT)]),
                     Spacer(1, 2 * mm),
                     P(t("rep.a", lang), "label"), Spacer(1, 1 * mm), P(f["a"]), Spacer(1, 2.5 * mm)]
            for cv in f["caveats"]:
                block += [P(cv, "small"), Spacer(1, 1.5 * mm)]
            block += [Table([[[P(t("rep.c", lang), "head"), Spacer(1, 1 * mm), P(f["c"], "small")],
                              [P(t("rep.d", lang), "label"), Spacer(1, 1 * mm), P(f["d"], "small")]]],
                            colWidths=[W * 0.42, W * 0.58],
                            style=[("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F4F5F7")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]),
                      Spacer(1, 2 * mm), P(t("rep.why", lang) + ": " + f["why"], "muted"), Spacer(1, 7 * mm)]
            story.append(KeepTogether(block))

    # ------------------------------------------------------------------------------ 4 Checklist
    story.append(PageBreak())
    _section(story, t("rep.s4", lang), S)
    story.append(P(t("rep.check_intro", lang)))
    story.append(Spacer(1, 3 * mm))
    if not items:
        story.append(P(t("rep.check.none", lang)))
    else:
        rows = [[P(t(f"rep.check.col.{k}", lang), "head") for k in ("no", "item", "year", "value", "page", "why", "ok", "bad")]]
        extra = []
        for i, x in enumerate(items, 1):
            why = _x(x["why"]) + (f'<br/><font color="#5A6069">{_x(t("rep.check.line", lang, s=x["source"]))}</font>'
                                   if x["source"] else "")
            rows.append([P(x["no"], "cell"), P(x["item"], "cell"), P(x["year"], "cell"), Paragraph(_x(x["value"]), S["cellm"]),
                         P(x["pages"], "cell"), Paragraph(why, S["cell"]),
                         _Box(), _Box()])
            if x["assumed"]:
                extra.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDF4DC")))
        story.append(_table(rows, [8 * mm, 32 * mm, 11 * mm, 31 * mm, 10 * mm, W - 8 * mm - 32 * mm - 11 * mm - 31 * mm - 10 * mm - 26 * mm,
                                   13 * mm, 13 * mm], S, extra=extra))
        assumed = [x for x in items if x["assumed"]]
        if assumed:
            story.append(Spacer(1, 3 * mm))
            story.append(P(t("rep.check.assumed", lang) + ": " + ", ".join(str(x["no"]) for x in assumed) + ".", "small"))
    for a_ in r.assumptions:
        story.append(Spacer(1, 1.5 * mm))
        story.append(P(t("app.assumption", lang, text=a_), "small"))
    story.append(Spacer(1, 8 * mm))
    story.append(P(t("rep.check.sign", lang)))

    # ------------------------------------------------------------------------------ Appendix A figures read
    story.append(PageBreak())
    _section(story, t("rep.s5", lang), S)
    story.append(P(t("rep.inputs_intro", lang, unit=unit), "small"))
    story.append(Spacer(1, 3 * mm))
    rows = [[P(t("inputs.col.item", lang), "head"), P(yt, "head"), P(yt1, "head"),
             P(t("xl.k.status", lang), "head"), P(t("rep.check.col.page", lang), "head"),
             P(t("xl.col.source_label", lang), "head")]]
    extra = []
    for i, x in enumerate(report.input_rows(r, lang), 1):
        status = x["status_t"] if x["status_t"] == x["status_t1"] else f'{yt}: {x["status_t"]}; {yt1}: {x["status_t1"]}'
        rows.append([P(x["label"].strip(), "cell"), Paragraph(_x(x["value_t"]), S["cellm"]),
                     Paragraph(_x(x["value_t1"]), S["cellm"]), P(status, "cell"),
                     P(x["pages"], "cell"), P(report.source_label(x["source"], lang), "cell")])
        extra += [("BACKGROUND", (1, i), (1, i), CELL[x["colour_t"]]), ("BACKGROUND", (2, i), (2, i), CELL[x["colour_t1"]])]
    story.append(_table(rows, [40 * mm, 31 * mm, 31 * mm, 30 * mm, 11 * mm, W - 143 * mm], S, extra=extra))

    # ------------------------------------------------------------------------------ Appendix B cross-checks
    story.append(PageBreak())
    _section(story, t("rep.s6", lang), S)
    story.append(P(t("rep.b_intro", lang), "small"))
    story.append(Spacer(1, 3 * mm))
    col_name = lambda c: {"t": yt, "t1": yt1}.get(c) or t("col.both", lang, a=yt, b=yt1)   # noqa: E731
    failed, review, passed = [], [], []
    for name_, col, ok, det in ex.checks:
        row = (f"{render(name_, lang)} ({col_name(col)})", render(det, lang))
        (passed if ok else failed).append(row if ok else (row[0], t("rep.b.failed_why", lang) +
                                                          (" " + row[1] + "." if row[1] else "")))
    for p_ in r.passed:
        passed.append((render(p_, lang), ""))
    for fl in r.flags:
        fields = ", ".join(report.title(x, lang) for x in fl.fields) or "—"
        (failed if fl.severity == "ERROR" else review).append((f"{fields} ({col_name(fl.column)})", render(fl.message, lang)))
    rows = [[P(t("rep.b.col.no", lang), "head"), P(t("rep.b.col.check", lang), "head"),
             P(t("rep.b.col.result", lang), "head"), P(t("rep.b.col.expl", lang), "head")]]
    extra = []
    for res_key, colour, group in (("rep.checks.failed", RED, failed), ("rep.checks.review", AMBER_INK, review),
                                   ("rep.checks.passed", GREEN, passed)):
        for chk, expl in group:
            rows.append([P(str(len(rows)), "cell"), P(chk, "cell"), P(t(res_key, lang), "cell"), P(expl, "cell")])
            extra.append(("TEXTCOLOR", (2, len(rows) - 1), (2, len(rows) - 1), colour))
    story.append(_table(rows, [9 * mm, 72 * mm, 22 * mm, W - 103 * mm], S, extra=extra))

    # ------------------------------------------------------------------------------ Appendix C reading notes
    if ex.issues:
        story.append(PageBreak())
        _section(story, t("rep.s8", lang), S)
        story.append(P(t("rep.c_intro", lang), "small"))
        story.append(Spacer(1, 3 * mm))
        rows = [[P(t("rep.b.col.no", lang), "head"), P(t("rep.c.col.note", lang), "head")]]
        for n_, i_ in enumerate(ex.issues, 1):
            rows.append([P(str(n_), "cell"), P(render(i_, lang), "cell")])
        story.append(_table(rows, [9 * mm, W - 9 * mm], S))

    # ------------------------------------------------------------------------------ Methodology
    story.append(PageBreak())
    _section(story, t("rep.s7", lang), S)
    for k in ("rep.method.p1", "rep.method.p2", "rep.method.p3", "rep.method.p4"):
        story += [P(t(k, lang)), Spacer(1, 3 * mm)]
    story += [P(t("rep.formula", lang, const=Num(report.M_CONSTANT, 2)), "small"), Spacer(1, 3 * mm),
              P(t("app.disclaimer", lang))]

    doc.build(story, canvasmaker=lambda *a, **kw: _Numbered(*a, info=info, **kw))
    return buf.getvalue()


class _Bar(Flowable):
    """Push bar: red to the right (raises the score), grey to the left."""

    def __init__(self, push, top, width):
        super().__init__()
        self.push, self.top, self.width, self.height = push, top or 1, width, 3 * mm

    def draw(self):
        c, mid = self.canv, self.width / 2
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(mid, -0.5 * mm, mid, 3.5 * mm)
        if self.push is None:
            return
        w = abs(self.push) / self.top * (mid - 1)
        c.setFillColor(RED if self.push > 0 else colors.HexColor("#9AA0A8"))
        if self.push > 0:
            c.rect(mid, 0.4 * mm, w, 2.2 * mm, stroke=0, fill=1)
        else:
            c.rect(mid - w, 0.4 * mm, w, 2.2 * mm, stroke=0, fill=1)


class _Box(Flowable):
    """An empty tick box for the checklist."""

    def __init__(self):
        super().__init__()
        self.width, self.height = 3.6 * mm, 3.6 * mm

    def draw(self):
        self.canv.setStrokeColor(INK)
        self.canv.setLineWidth(0.7)
        self.canv.rect(0, 0, 3.4 * mm, 3.4 * mm, stroke=1, fill=0)
