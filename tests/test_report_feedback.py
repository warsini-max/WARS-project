"""PDF report: Feedback and Suggestions section (Gail, 13 Nov 2026 17.23, approved wording).

* The approved wording appears exactly, once, in the report language (EN / ID); never the other language's text.
* The section sits near the end (methodology page, after the disclaimer), within the page, without a blank page.
* The Contact Us envelope icon links to the configured address (report_pdf.CONTACT_EMAIL), on every page.
"""
import io
import re
from pathlib import Path

import pdfplumber
import pytest

from wars_scanner import pipeline, report_pdf
from wars_scanner.text import t

EN = ("WARS welcomes feedback, suggestions, and recommendations to support the further development and improvement of "
      "the system. Feedback may be submitted via email by selecting the email icon in the Contact Us section.")
ID = ("WARS terbuka terhadap masukan, saran, dan rekomendasi untuk pengembangan dan penyempurnaan sistem. Masukan dapat "
      "disampaikan melalui email dengan memilih ikon email pada bagian Hubungi Kami.")
HEAD = {"en": "Feedback and Suggestions", "id": "Masukan dan Saran"}
BODY = {"en": EN, "id": ID}
DOC = Path(__file__).resolve().parents[1].parent / "s3core" / "docs" / "LK_SIDO_2021.pdf"


def test_catalogue_holds_the_approved_wording_exactly():
    assert t("rep.feedback.title", "en") == HEAD["en"] and t("rep.feedback.title", "id") == HEAD["id"]
    assert t("rep.feedback.body", "en") == EN and t("rep.feedback.body", "id") == ID


@pytest.fixture(scope="module")
def pdfs():
    if not DOC.exists():
        pytest.skip("test document not available")
    r = pipeline.apply_provisional(pipeline.run(str(DOC), "X"))
    return {lang: report_pdf.build(r, lang, DOC.name, "0" * 64) for lang in ("en", "id")}


def _flat(s):
    return re.sub(r"\s+", " ", s).strip()


def _pages(pdf):
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [(p.extract_text() or "", [h.get("uri") for h in p.hyperlinks]) for p in doc.pages]


@pytest.mark.parametrize("lang", ["en", "id"])
def test_section_once_in_the_report_language(pdfs, lang):
    pages = _pages(pdfs[lang])
    text = _flat(" ".join(p for p, _ in pages))
    assert text.count(BODY[lang]) == 1                       # exact wording, once
    assert text.count(HEAD[lang]) == 1
    other = "id" if lang == "en" else "en"
    assert BODY[other] not in text and HEAD[other] not in text   # must NOT: the other language's text


@pytest.mark.parametrize("lang", ["en", "id"])
def test_section_is_near_the_end_after_the_disclaimer(pdfs, lang):
    pages = _pages(pdfs[lang])
    where = [i for i, (p, _) in enumerate(pages) if BODY[lang] in _flat(p)]
    assert where == [len(pages) - 1]                         # last page, whole paragraph on one page (no split)
    last = _flat(pages[-1][0])
    disc = _flat(t("app.disclaimer", lang))
    assert disc in last and last.index(disc) < last.index(HEAD[lang])
    for p, _ in pages:                                       # no blank page: every page has body text beyond the frame
        assert len(_flat(p)) > 300


@pytest.mark.parametrize("lang", ["en", "id"])
def test_contact_email_link_on_every_page(pdfs, lang):
    mail = "mailto:" + report_pdf.CONTACT_EMAIL
    assert re.fullmatch(r"mailto:[^@\s]+@[^@\s]+\.[a-z]{2,}", mail)
    for _p, links in _pages(pdfs[lang]):
        assert mail in links and report_pdf.LINKEDIN_URL in links


def test_configured_address_is_the_one_the_app_uses():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert f'CONTACT_EMAIL = "{report_pdf.CONTACT_EMAIL}"' in src


@pytest.mark.parametrize("lang", ["en", "id"])
def test_footer_label_is_the_section_the_text_refers_to(lang):
    # Gail 14 Nov 06.40: 'Hubungi Kami' (ID) and 'Contact Us' (EN); the feedback text refers to that label
    assert t("rep.contact", lang) == {"id": "Hubungi Kami", "en": "Contact Us"}[lang]
    assert f"bagian {t('rep.contact', lang)}." in BODY[lang] if lang == "id" else f"the {t('rep.contact', lang)} section" in BODY[lang]
