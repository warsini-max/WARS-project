"""Build synthetic "Laporan Tahunan" test documents around a real, non-case financial-statement PDF.

Used by tests/test_annual_report.py (Phase D). No real annual report is available in the build
environment, so the test document is assembled:

  front matter (generated, clearly labelled as a synthetic test document):
    cover, table of contents, narrative pages, image-only pages (like photo spreads),
    an "Ikhtisar Keuangan" page and a highlights page headed only "Laporan Posisi Keuangan
    Konsolidasian" (both with summary figures that differ from the statements: traps),
    "Analisis dan Pembahasan Manajemen" pages
  + the real audited financial statements and notes (e.g. LK_SIDO_2021.pdf), unchanged
  + back matter (generated)

Variants:
  full          front (n_front pages) + statements + notes + back      -> must be read
  front_only    front + back, no financial statements                  -> must fail explicitly
  no_notes      front + statements pages only (notes removed) + back   -> must fail explicitly

Nothing produced here is committed (CLAUDE.md rule 5); files go to a temporary folder.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

LABEL = "DOKUMEN UJI SINTETIS WARS - bukan laporan tahunan asli"


def _front_matter(n_pages: int, fiscal_year: int, image_pages=(5, 6, 40, 41, 120)) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    hl = {  # highlights deliberately different from the statements (rounded, in billions)
        "Total Aset": ("4.069", "3.850"), "Total Liabilitas": ("598", "628"), "Penjualan": ("4.021", "3.335"),
        "Laba Tahun Berjalan": ("1.261", "934"), "Kas dan Setara Kas": ("1.082", "1.032"),
    }
    for i in range(1, n_pages + 1):
        c.setFont("Helvetica", 8)
        c.drawString(40, 20, f"{LABEL} - halaman depan {i}")
        if i in image_pages:                      # image-only spread: no text layer except nothing
            c.setFillGray(0.85)
            c.rect(30, 40, w - 60, h - 80, stroke=0, fill=1)
            c.setFillGray(0)
            c.showPage()
            continue
        if i == 1:
            c.setFont("Helvetica-Bold", 28)
            c.drawString(60, h - 200, f"LAPORAN TAHUNAN {fiscal_year}")
            c.setFont("Helvetica", 14)
            c.drawString(60, h - 230, f"ANNUAL REPORT {fiscal_year}")
        elif i == 2:
            c.setFont("Helvetica-Bold", 16)
            c.drawString(60, h - 80, "DAFTAR ISI / TABLE OF CONTENTS")
            c.setFont("Helvetica", 11)
            for k, (t, p) in enumerate([("Ikhtisar Keuangan", 10), ("Laporan Posisi Keuangan Konsolidasian", 11),
                                        ("Analisis dan Pembahasan Manajemen", 60),
                                        ("Laporan Keuangan Konsolidasian", n_pages + 1)]):
                c.drawString(60, h - 120 - 18 * k, f"{t} .......... {p}")
        elif i == 10:                             # trap 1: financial highlights
            c.setFont("Helvetica-Bold", 16)
            c.drawString(60, h - 80, "IKHTISAR KEUANGAN / FINANCIAL HIGHLIGHTS")
            c.setFont("Helvetica-Bold", 12)
            c.drawString(60, h - 110, "Laporan Posisi Keuangan Konsolidasian (dalam miliar Rupiah)")
            c.drawString(320, h - 130, f"{fiscal_year}")
            c.drawString(400, h - 130, f"{fiscal_year - 1}")
            c.setFont("Helvetica", 11)
            for k, (lab, (a, b)) in enumerate(hl.items()):
                c.drawString(60, h - 150 - 16 * k, lab)
                c.drawRightString(350, h - 150 - 16 * k, a)
                c.drawRightString(430, h - 150 - 16 * k, b)
        elif i == 11:                             # trap 2: heading only "Laporan Posisi Keuangan", no Notes column
            c.setFont("Helvetica-Bold", 14)
            c.drawString(60, h - 80, "LAPORAN POSISI KEUANGAN KONSOLIDASIAN")
            c.drawString(60, h - 98, f"31 Desember {fiscal_year} dan {fiscal_year - 1}")
            c.setFont("Helvetica", 11)
            c.drawString(320, h - 125, f"{fiscal_year}")
            c.drawString(400, h - 125, f"{fiscal_year - 1}")
            for k, (lab, (a, b)) in enumerate(hl.items()):
                c.drawString(60, h - 145 - 16 * k, lab)
                c.drawRightString(350, h - 145 - 16 * k, a)
                c.drawRightString(430, h - 145 - 16 * k, b)
        elif 60 <= i <= 62:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(60, h - 80, "ANALISIS DAN PEMBAHASAN MANAJEMEN")
            c.setFont("Helvetica", 10)
            for k, line in enumerate(["Tinjauan keuangan berikut merujuk pada laporan arus kas, laporan laba rugi",
                                      "dan laporan posisi keuangan konsolidasian yang diaudit.",
                                      "Penjualan meningkat dibandingkan tahun sebelumnya."]):
                c.drawString(60, h - 110 - 14 * k, line)
        else:
            c.setFont("Helvetica", 10)
            for k in range(30):
                c.drawString(60, h - 80 - 14 * k, f"Narasi laporan tahunan, bagian {i}, paragraf {k + 1}.")
        c.showPage()
    c.save()
    return buf.getvalue()


def _back_matter(n_pages: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(1, n_pages + 1):
        c.setFont("Helvetica", 10)
        c.drawString(60, 760, f"{LABEL} - halaman belakang {i}")
        c.drawString(60, 740, "Lembar persetujuan dan tanggung jawab dewan direksi.")
        c.showPage()
    c.save()
    return buf.getvalue()


def build(fs_pdf: Path, out: Path, variant: str = "full", n_front: int = 255, n_back: int = 4,
          fiscal_year: int = 2021, statement_pages: int = 12) -> dict:
    """Write the composite PDF; return {'offset': pages before the statements PDF, 'pages': total}."""
    doc = pdfium.PdfDocument.new()
    front = pdfium.PdfDocument(_front_matter(n_front, fiscal_year))
    doc.import_pages(front)
    offset = len(front)
    if variant in ("full", "no_notes"):
        fs = pdfium.PdfDocument(str(fs_pdf))
        if variant == "full":
            doc.import_pages(fs)
        else:
            doc.import_pages(fs, list(range(min(statement_pages, len(fs)))))
    back = pdfium.PdfDocument(_back_matter(n_back))
    doc.import_pages(back)
    total = len(doc)
    doc.save(str(out))
    return {"offset": offset, "pages": total}


if __name__ == "__main__":
    src, dst, var = Path(sys.argv[1]), Path(sys.argv[2]), (sys.argv[3] if len(sys.argv) > 3 else "full")
    print(build(src, dst, var))
