"""One bilingual text catalogue for everything the user reads (app now, PDF report later).

Decisions behind it (Gail, 22-23 Oct 2026; see the project docs WARS_UI_Text_Review_r1,
WARS_Analysis_Text_Rules_r1, WARS_Report_Design_Decisions_r0/r1):

* Two languages from one source; the user chooses ID or EN (R-01, R-02).
* Sentences are built in the chosen language from structured data, never translated (R-03, K5).
* Number formats follow the language: ID 1.304.100 and -1,25; EN 1,304,100 and -1.25 (R-04).
* British English (A1). The EN version contains no Indonesian words, and the ID version no English
  words except fixed terms (red flag, M-score, index names) (language rule, Gail 23 Oct 15.22).
* Rule codes ([D-08], [G-22]) never in a heading or main sentence; only in detail views, the CSV
  and the technical appendix (A2, K8): `render(lang, codes=True)` adds them.
* PSAK numbers follow the financial year, old/new number in brackets (R-05): `psak()`.

Every catalogue entry records where its wording comes from (`src`):
  "r0 x.y" / "r1 x.y" / "B r1 §n"  - wording approved by Gail (UI review r0/r1, analysis rules B r1);
  "C6 x.y"                         - short app wording drafted for C6, awaiting Gail's review;
  "new"                            - wording written while implementing, awaiting Gail's review;
  "M-05"                           - depends on a methodology item that is still PROPOSED.
`review_list()` lists everything not yet approved, for the review document.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

LANGS = ("id", "en")
DEFAULT_LANG = "id"


# ----------------------------------------------------------------------------------- formatting

def _group(intpart: str, sep: str) -> str:
    out = []
    while len(intpart) > 3:
        out.insert(0, intpart[-3:])
        intpart = intpart[:-3]
    out.insert(0, intpart)
    return sep.join(out)


def fmt_number(v, lang, decimals=0, sign=False):
    """R-04: ID 1.234,5 / EN 1,234.5; minus sign U+2212; optional explicit plus."""
    if v is None:
        return "—"
    neg = v < 0
    s = f"{abs(v):.{decimals}f}"
    intpart, _, frac = s.partition(".")
    thou, dec = (".", ",") if lang == "id" else (",", ".")
    body = _group(intpart, thou) + (dec + frac if frac else "")
    if neg and float(s) != 0:
        return "−" + body
    return ("+" if sign and v > 0 else "") + body


@dataclass(frozen=True)
class Num:
    """A decimal number (index, score)."""
    value: float
    decimals: int = 3
    sign: bool = False

    def render(self, lang, codes=False):
        return fmt_number(self.value, lang, self.decimals, self.sign)


@dataclass(frozen=True)
class Amt:
    """An amount as printed in the report (integer, thousands separators)."""
    value: float

    def render(self, lang, codes=False):
        return fmt_number(self.value, lang, 0)


@dataclass(frozen=True)
class Pct:
    """A ratio shown as a percentage: Pct(0.206) -> 20,6% / 20.6%."""
    value: float
    decimals: int = 1
    sign: bool = False

    def render(self, lang, codes=False):
        return fmt_number(self.value * 100, lang, self.decimals, self.sign) + "%"


@dataclass(frozen=True)
class Money:
    """Amount with the report's unit: Rp3.335.411 juta / IDR 3,335,411 million; a change may carry its sign.
    Reports presented in US dollars (P4, Gail 28 Oct 2026) show USD in both languages."""
    value: float
    unit: str | None
    sign: bool = False
    currency: str | None = "IDR"

    def render(self, lang, codes=False):
        n = fmt_number(abs(self.value), lang, 0)
        word = {"id": {"Thousands": " ribu", "Millions": " juta", "Billions": " miliar"},
                "en": {"Thousands": " thousand", "Millions": " million", "Billions": " billion"}}[lang].get(self.unit, "")
        pre = "−" if self.value < 0 else ("+" if self.sign and self.value > 0 else "")
        if self.currency == "USD":
            return pre + f"USD {n}{word}"
        return pre + (f"Rp{n}{word}" if lang == "id" else f"IDR {n}{word}")


def unit_msg(unit, currency=None):
    """The presentation unit as a catalogue message, per currency."""
    if not unit:
        return Msg("unit.unknown")
    return Msg(f"unit.USD.{unit}" if currency == "USD" else f"unit.{unit}")


@dataclass(frozen=True)
class Raw:
    """Text quoted from the PDF (or typed by the user): shown as is in both languages."""
    text: str

    def render(self, lang, codes=False):
        return self.text


@dataclass(frozen=True)
class Pages:
    pages: tuple

    def render(self, lang, codes=False):
        return ", ".join(str(p) for p in self.pages)


def psak(new: str, old: str | None, fiscal_year, lang, para: str = "") -> str:
    """R-05: the number in force for the financial year, the other one in brackets.

    psak("116", "73", 2021, "id", "¶47(a)(i)") -> "PSAK 73 ¶47(a)(i) (kini PSAK 116)".
    The renumbering took effect on 1 January 2024 (IAI); paragraph numbers did not change.
    """
    p = f" {para}" if para else ""
    if not old:
        return f"PSAK {new}{p}"
    if isinstance(fiscal_year, int) and fiscal_year < 2024:
        return f"PSAK {old}{p} (" + ("kini" if lang == "id" else "now") + f" PSAK {new})"
    return f"PSAK {new}{p} (" + ("sebelumnya" if lang == "id" else "formerly") + f" PSAK {old})"


@dataclass(frozen=True)
class Psak:
    new: str
    old: str | None
    fiscal_year: object = None
    para: str = ""

    def render(self, lang, codes=False):
        return psak(self.new, self.old, self.fiscal_year, lang, self.para)


# ----------------------------------------------------------------------------------- messages

class Msg(str):
    """A catalogue message with its parameters. As a plain string it reads in Indonesian (the
    version that prevails, R-07), so existing joins and CSV writers keep working; `render(lang)`
    gives either language. Picklable (Streamlit cache) and deep-copyable."""

    def __new__(cls, key: str, **params):
        if key not in CATALOG:
            raise KeyError(f"text key not in catalogue: {key}")
        obj = str.__new__(cls, _render(key, params, DEFAULT_LANG, False))
        obj.key, obj.params = key, params
        return obj

    def __reduce__(self):
        return (_rebuild, (self.key, self.params))

    def __deepcopy__(self, memo):
        return self

    def render(self, lang=DEFAULT_LANG, codes=False):
        return _render(self.key, self.params, lang, codes)

    @property
    def codes(self):
        return CATALOG[self.key].get("codes", ())


def _rebuild(key, params):
    return Msg(key, **params)


def join(parts, sep="; "):
    """Several messages shown as one (e.g. a value's notes)."""
    parts = [p for p in parts if p]
    return Msg("_join", parts=tuple(parts), sep=sep)


def keys_in(x) -> set:
    """Catalogue keys inside a message (joins and nested parameters included); for tests and audits."""
    out = set()
    if isinstance(x, Msg):
        if x.key != "_join":
            out.add(x.key)
        for v in x.params.values():
            out |= keys_in(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            out |= keys_in(v)
    return out


def render(x, lang=DEFAULT_LANG, codes=False):
    """Render anything a message parameter or field may hold."""
    if x is None:
        return ""
    if isinstance(x, Msg):
        return x.render(lang, codes)
    if hasattr(x, "render") and not isinstance(x, str):
        return x.render(lang, codes)
    if isinstance(x, (list, tuple)):
        return ", ".join(render(i, lang, codes) for i in x)
    return str(x)


class _Fmt(string.Formatter):
    def __init__(self, lang, codes):
        self.lang, self.codes = lang, codes

    def format_field(self, value, spec):
        return render(value, self.lang, self.codes)


def _render(key, params, lang, codes):
    if key == "_join":
        return params["sep"].join(render(p, lang, codes) for p in params["parts"])
    e = CATALOG[key]
    text = _Fmt(lang, codes).format(e[lang], **params)
    if codes and e.get("codes"):
        text += " [" + ", ".join(e["codes"]) + "]"
    return text


def t(key, lang=DEFAULT_LANG, codes=False, **params):
    return _render(key, params, lang, codes)


def placeholders(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def review_list():
    """Catalogue entries whose wording Gail has not approved yet, grouped by source."""
    return [(k, e["src"], e["id"], e["en"]) for k, e in CATALOG.items()
            if not k.startswith("_") and not re.match(APPROVED_SRC, e["src"])]


# Wording approved by Gail: UI review r0/r1, analysis rules B r1, or approved directly in chat ("Gail <date>").
APPROVED_SRC = r"^(r0|r1|B r1|Gail \d+)\b"


# ----------------------------------------------------------------------------------- catalogue

def _e(id_, en, src, *codes):
    return {"id": id_, "en": en, "src": src, "codes": tuple(codes)}


CATALOG: dict = {
    "_join": _e("", "", "internal"),

    # ---------------------------------------------------------------- app: fixed texts (C6 short drafts)
    "app.title": _e("Window-dressing Red-flag Scanner", "Window-dressing Red-flag Scanner", "Gail 28 Okt 10.41"),
    "app.subtitle": _e("Beneish M-score (1999) untuk laporan keuangan tahunan emiten BEI",
                       "Beneish M-score (1999) for annual financial statements of IDX-listed companies", "Gail 28 Okt C6 7.1"),
    "app.lang": _e("Bahasa / Language", "Bahasa / Language", "Gail 28 Okt impl"),
    "app.disclaimer": _e(
        "Hasil ini adalah penyaringan red flag dengan Beneish M-score, bukan bukti kecurangan. Akun yang ditandai "
        "perlu diperiksa lebih lanjut.",
        "This is a red-flag screen using the Beneish M-score, not evidence of fraud. The flagged accounts need "
        "closer examination.", "Gail 28 Okt C6 7.2 (versi halus Claude disetujui)"),
    "app.beta": _e("Versi beta untuk uji coba. Hasil dapat berubah seiring perbaikan pembaca.",
                   "Beta version for testing. Results may change as the reader is improved.", "Gail 28 Okt A1"),
    "app.get_lk.title": _e("Cara mendapatkan PDF laporan keuangan", "How to get the financial statements PDF",
                           "Gail 28 Okt A2"),
    "app.get_lk": _e("LK teraudit dapat diunduh dari situs perusahaan atau situs BEI (idx.co.id).",
                     "Audited financial statements can be downloaded from the company's website or the IDX website "
                     "(idx.co.id).", "Gail 28 Okt A2"),
    "app.privacy_online": _e("Versi online berjalan di server Streamlit Community Cloud di Amerika Serikat.",
                             "The online version runs on Streamlit Community Cloud servers in the United States.",
                             "Gail 28 Okt B2"),
    "app.method.title": _e("Metodologi dan batasan", "Methodology and limitations", "Gail 28 Okt A3"),
    "app.model_limit": _e("Model dikembangkan dari data perusahaan AS (Beneish 1999) dan belum divalidasi untuk emiten "
                          "BEI; skor rendah tidak berarti bebas salah saji.",
                          "The model was built on US company data (Beneish 1999) and has not been validated for IDX "
                          "companies; a low score does not mean the statements are free of misstatement.",
                          "Gail 28 Okt A3"),
    "app.author": _e("Dibuat oleh Warsini", "Made by Warsini", "Gail 28 Okt B3"),
    "app.howto.title": _e("Cara pakai", "How to use", "Gail 28 Okt impl"),
    "app.howto": _e(
        "1. Unggah PDF digital LK teraudit (dianjurkan) atau Laporan Tahunan berisi LK lengkap. Bukan hasil pindai.\n"
        "2. Tetapkan status yang diminta.\n3. Periksa angka bertanda kuning.",
        "1. Upload the digital PDF of the audited financial statements (recommended) or an annual report that "
        "contains them in full. Not a scan.\n2. Set the statuses requested.\n3. Check the figures marked yellow.",
        "Gail 28 Okt C6 7.3"),
    "app.legend": _e("Warna: hijau = terbaca dan tercocokkan · kuning = perlu diperiksa · merah = tidak ditemukan.",
                     "Colours: green = read and reconciled · yellow = needs review · red = not found.", "Gail 28 Okt impl"),
    "app.limits": _e("Belum didukung: PDF hasil pindai, laporan hanya berbahasa Inggris, mata uang selain Rupiah, "
                     "bank dan asuransi.",
                     "Not yet supported: scanned PDFs, English-only reports, non-Rupiah currencies, banks and insurers.",
                     "Gail 28 Okt C6 7.4"),
    "app.privacy": _e(
        "PDF disimpan sementara di disk server selama dibaca, lalu dihapus. Hasil bacaan (angka, kutipan, halaman) "
        "disimpan di memori server, maksimal 20 dokumen, sampai server dimulai ulang, agar tidak perlu dibaca ulang. "
        "Bila aplikasi dijalankan di komputer Anda sendiri, semuanya terjadi di komputer Anda.",
        "The PDF is written temporarily to the server's disk while it is read, then deleted. The results (figures, "
        "quotes, pages) are kept in server memory, up to 20 documents, until the server restarts, so the file need "
        "not be read again. When you run the app on your own computer, all of this happens on your computer.",
        "r1 7.5"),
    "app.upload": _e("Unggah laporan keuangan tahunan (PDF)", "Upload the annual financial statements (PDF)", "Gail 28 Okt impl"),
    "app.upload_help": _e("Satu file PDF, maksimal 50 MB.", "One PDF file, up to 50 MB.", "Gail 28 Okt impl"),
    "app.ticker": _e("Kode saham (opsional, contoh: SIDO)", "Ticker (optional, e.g. SIDO)", "Gail 28 Okt impl"),
    "app.reading": _e("Membaca laporan utama dan catatan atas laporan keuangan…",
                      "Reading the primary statements and the notes…", "Gail 28 Okt impl"),
    "app.pdf_error": _e("PDF tidak dapat dibuka. Pastikan berkas adalah PDF digital yang tidak rusak atau terkunci.",
                        "The PDF could not be opened. Check that the file is a digital PDF that is not damaged or locked.",
                        "Gail 28 Okt impl"),
    "app.pdf_error_detail": _e("Detail teknis", "Technical detail", "Gail 28 Okt impl"),
    "app.fileline": _e("Berkas: {name} · SHA-256 {sha}… · {pages} halaman · tahun buku {year} · {stype} · satuan {unit}",
                       "File: {name} · SHA-256 {sha}… · {pages} pages · financial year {year} · {stype} · unit: {unit}",
                       "Gail 28 Okt impl"),
    "app.status": _e("Status: {status}", "Status: {status}", "Gail 28 Okt impl"),
    "app.confirm_counts": _e("Konfirmasi: {ok} sesuai · {bad} tidak sesuai · {pending} belum diperiksa",
                             "Confirmation: {ok} matching · {bad} not matching · {pending} not checked", "Gail 28 Okt impl"),
    "app.threshold": _e("Makin ke kanan, skor makin tinggi. Di kanan {thr}: perlu pemeriksaan lanjutan, bukan "
                        "probabilitas kecurangan.",
                        "Further right means a higher score. Right of {thr}: further review is warranted; it is not a "
                        "probability of fraud.", "Gail 28 Okt C6 7.8"),
    "app.check_failed": _e("Pemeriksaan silang gagal: {msg}", "Cross-check failed: {msg}", "Gail 28 Okt impl"),
    "app.read_detail": _e("Detail pembacaan", "Reading details", "Gail 28 Okt impl"),
    "app.footer_model": _e("Model: Beneish (1999), 8 variabel; tahun berjalan dan pembanding diambil dari laporan "
                           "yang sama.",
                           "Model: Beneish (1999), 8 variables; the current year and the comparatives come from the "
                           "same report.", "Gail 28 Okt impl"),
    "app.assumption": _e("Asumsi: {text}", "Assumption: {text}", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- drivers (B r1 §3-§5; C6 7.13-7.15)
    "drivers.title": _e("Rasio di atas normal", "Ratios above normal", "r1 7.13"),
    "drivers.note": _e("Pembanding: perusahaan netral (semua indeks 1, TATA 0). Rasio ini menaikkan skor menurut "
                       "rumus model; bukan bukti salah saji.",
                       "Benchmark: a neutral company (all indices 1, TATA 0). These ratios raise the score under the "
                       "model formula; not evidence of misstatement.", "Gail 28 Okt C6 7.13"),
    "drivers.none": _e("Tidak ada rasio yang memenuhi kriteria.", "No ratio meets the display criteria.", "Gail 28 Okt C6 7.15"),
    "drivers.about": _e("Tentang indeks ini", "About this index", "r1 7.14"),
    "drivers.c": _e("Hal ini dapat terjadi karena, antara lain: {items}.",
                    "This can happen because of, among other things: {items}.", "B r1 §4"),
    "drivers.d": _e("Area pemeriksaan: {items}.", "Areas for examination: {items}.", "B r1 §4"),
    "drivers.unconfirmed": _e("(angka belum dikonfirmasi)", "(figures not yet confirmed)", "B r1 §1 K2"),
    "drivers.caveat_transition": _e(
        "Tahun {t} adalah tahun pertama penerapan {std}; tidak dapat disimpulkan dari data ini seberapa besar "
        "perubahan berasal dari perubahan standar.",
        "{t} is the first year of {std}; how much of the change comes from the change of standard cannot be "
        "concluded from this data.", "B r1 §6"),
    "drivers.caveat_restated": _e(
        "Kolom tahun lalu disajikan kembali; tidak dapat disimpulkan dari data ini tanpa membaca pengungkapannya.",
        "The prior-year column was restated; nothing can be concluded from this data without reading the "
        "disclosure.", "B r1 §6"),
    "drivers.ca_note": _e("Aset kontrak tidak dihitung sebagai piutang (hal. {p}).",
                          "Contract assets are not counted as receivables (p. {p}).", "B r1 §5", "G-06"),
    "chg.up": _e("naik {pct}", "rose {pct}", "B r1 §5"),
    "chg.down": _e("turun {pct}", "fell {pct}", "B r1 §5"),
    "f.DSRI": _e("Piutang usaha {chg_ar} sementara penjualan {chg_rev} (piutang {ar_t1} → {ar_t}, hal. {p_ar}; "
                 "penjualan hal. {p_rev}). DSRI {idx} menaikkan skor {push} menurut rumus model.",
                 "Trade receivables {chg_ar} while sales {chg_rev} (receivables {ar_t1} → {ar_t}, p. {p_ar}; sales "
                 "p. {p_rev}). DSRI {idx} raises the score by {push} under the model formula.", "B r1 §5"),
    "f.GMI": _e("Margin laba kotor turun dari {gm_t1} menjadi {gm_t} (hal. {p_rev}). GMI {idx} menaikkan skor {push} "
                "menurut rumus model.",
                "The gross margin fell from {gm_t1} to {gm_t} (p. {p_rev}). GMI {idx} raises the score by {push} "
                "under the model formula.", "B r1 §5"),
    "f.AQI": _e("Porsi aset tidak lancar selain aset tetap naik dari {aq_t1} menjadi {aq_t} dari total aset "
                "(hal. {p_ta}). AQI {idx} menaikkan skor {push} menurut rumus model.",
                "The share of non-current assets other than PPE rose from {aq_t1} to {aq_t} of total assets "
                "(p. {p_ta}). AQI {idx} raises the score by {push} under the model formula.", "B r1 §5"),
    "f.SGI": _e("Penjualan {chg_rev} ({rev_t1} → {rev_t}, hal. {p_rev}). Kenaikan ini tidak dengan sendirinya "
                "menunjukkan salah saji; SGI {idx} menaikkan skor {push} menurut rumus model.",
                "Sales {chg_rev} ({rev_t1} → {rev_t}, p. {p_rev}). This does not by itself indicate misstatement; "
                "SGI {idx} raises the score by {push} under the model formula.", "B r1 §5"),
    "f.TATA": _e("Akrual modal kerja setelah penyusutan setara {tata} dari total aset: aset lancar non-kas berubah "
                 "{d_ca}, liabilitas jangka pendek operasional berubah {d_cl}, penyusutan dan amortisasi {da} "
                 "(hal. {p_ca}). Sebagai pembanding, laba tahun berjalan {ni} dan arus kas operasi {cfo} "
                 "(hal. {p_ni}, {p_cfo}).",
                 "Working-capital accruals after depreciation equal {tata} of total assets: non-cash current assets "
                 "changed by {d_ca}, operating current liabilities changed by {d_cl}, depreciation and amortisation "
                 "{da} (p. {p_ca}). For comparison, profit for the year was {ni} and operating cash flow {cfo} "
                 "(p. {p_ni}, {p_cfo}).", "B r1 §5"),
    "f.TATA_nocmp": _e("Akrual modal kerja setelah penyusutan setara {tata} dari total aset: aset lancar non-kas "
                       "berubah {d_ca}, liabilitas jangka pendek operasional berubah {d_cl}, penyusutan dan "
                       "amortisasi {da} (hal. {p_ca}).",
                       "Working-capital accruals after depreciation equal {tata} of total assets: non-cash current "
                       "assets changed by {d_ca}, operating current liabilities changed by {d_cl}, depreciation and "
                       "amortisation {da} (p. {p_ca}).", "B r1 §5"),
    "c.DSRI": _e("perubahan termin kredit; pelanggan besar baru; penjualan musiman di akhir tahun",
                 "a change in credit terms; a large new customer; seasonal sales at the year end", "B r1 §5"),
    "d.DSRI": _e("umur piutang; piutang pihak berelasi; cadangan kerugian kredit; kebijakan pengakuan pendapatan "
                 "({psak115})",
                 "receivables ageing; related-party receivables; the credit-loss allowance; the revenue recognition "
                 "policy ({psak115})", "B r1 §5"),
    "c.GMI": _e("harga bahan baku atau kurs; bauran produk; strategi harga",
                "raw-material prices or exchange rates; product mix; pricing strategy", "B r1 §5"),
    "d.GMI": _e("rincian beban pokok penjualan; persediaan dan penurunan nilainya; margin per segmen",
                "the cost of sales breakdown; inventories and their write-downs; margins by segment", "B r1 §5"),
    "c.AQI": _e("akuisisi (goodwill, aset takberwujud); investasi strategis; uang muka proyek ekspansi",
                "acquisitions (goodwill, intangible assets); strategic investments; advances for expansion projects",
                "B r1 §5"),
    "d.AQI": _e("aset tidak lancar lainnya; aset takberwujud dan kapitalisasi biaya ({psak238}); goodwill dan uji "
                "penurunan nilai; uang muka",
                "other non-current assets; intangible assets and capitalised costs ({psak238}); goodwill and "
                "impairment testing; advances", "B r1 §5"),
    "c.SGI": _e("akuisisi; produk baru; kenaikan harga", "acquisitions; new products; price increases", "B r1 §5"),
    "d.SGI": _e("pendapatan per segmen atau produk ({psak115}); kombinasi bisnis; penjualan pihak berelasi",
                "revenue by segment or product ({psak115}); business combinations; related-party sales", "B r1 §5"),
    "c.TATA": _e("penumpukan persediaan; pertumbuhan yang memerlukan modal kerja; pembayaran pemasok dipercepat",
                 "inventory build-up; growth that needs working capital; faster payments to suppliers", "B r1 §5"),
    "d.TATA": _e("persediaan; piutang; beban akrual dan utang usaha; laporan arus kas",
                 "inventories; receivables; accrued expenses and trade payables; the statement of cash flows",
                 "B r1 §5"),
    "why.DSRI": _e("Beneish (1999) memakai DSRI karena kenaikan piutang yang tidak sebanding dengan penjualan dapat "
                   "berasal dari perubahan kebijakan kredit atau dari pendapatan yang dicatat terlalu besar; ini "
                   "alasan model, bukan penilaian atas emiten.",
                   "Beneish (1999) uses DSRI because receivables rising faster than sales can come from a change in "
                   "credit policy or from overstated revenue; this is the model's rationale, not an assessment of the "
                   "company.", "B r1 §5"),
    "why.GMI": _e("Dalam model Beneish, margin yang memburuk dipakai sebagai sinyal prospek yang melemah, bukan "
                  "sebagai tanda angka margin itu salah saji.",
                  "In the Beneish model a deteriorating margin is used as a signal of weaker prospects, not as a sign "
                  "that the margin figure is misstated.", "B r1 §5"),
    "why.AQI": _e("Beneish (1999) memakai AQI sebagai ukuran porsi aset yang manfaat masa depannya kurang pasti; "
                  "kenaikannya dapat berarti lebih banyak biaya yang dikapitalisasi.",
                  "Beneish (1999) uses AQI to measure the share of assets whose future benefits are less certain; a "
                  "rise can mean that more costs were capitalised.", "B r1 §5"),
    "why.SGI": _e("Beneish (1999) memasukkan pertumbuhan penjualan karena perusahaan yang tumbuh menghadapi tekanan "
                  "mempertahankan pertumbuhan, dan pengendalian sering tertinggal dari pertumbuhan; ini alasan model, "
                  "bukan penilaian atas emiten. Pertumbuhan bukan manipulasi.",
                  "Beneish (1999) includes sales growth because growing companies face pressure to sustain growth, "
                  "and controls often lag behind growth; this is the model's rationale, not an assessment of the "
                  "company. Growth is not manipulation.", "B r1 §5"),
    "why.TATA": _e("Beneish (1999) memakai TATA sebagai ukuran seberapa jauh laba didukung kas.",
                   "Beneish (1999) uses TATA to measure how far earnings are backed by cash.", "B r1 §5"),
    "why.minor": _e("Tidak signifikan dalam model Beneish (1999); tidak dibahas sebagai temuan.",
                    "Not significant in the Beneish (1999) model; not discussed as a finding.", "B r1 §5 K7"),
    "why.DEPI_g23": _e("Penyusutan aset hak-guna tidak diungkapkan; DEPI memakai penyusutan aset tetap milik "
                       "(lingkup tidak sepadan).",
                       "Right of use depreciation is not disclosed; DEPI uses owned-PPE depreciation (scope not "
                       "comparable).", "B r1 §5", "G-23"),
    "idx.name.DSRI": _e("Piutang dibanding penjualan", "Receivables relative to sales", "Gail 28 Okt impl"),
    "idx.name.GMI": _e("Margin laba kotor", "Gross margin", "Gail 28 Okt impl"),
    "idx.name.AQI": _e("Kualitas aset", "Asset quality", "Gail 28 Okt impl"),
    "idx.name.SGI": _e("Pertumbuhan penjualan", "Sales growth", "Gail 28 Okt impl"),
    "idx.name.DEPI": _e("Tarif penyusutan", "Depreciation rate", "Gail 28 Okt impl"),
    "idx.name.SGAI": _e("Beban penjualan dan umum dibanding penjualan", "Selling and general expenses relative to sales",
                        "Gail 28 Okt impl"),
    "idx.name.LVGI": _e("Tingkat utang", "Leverage", "Gail 28 Okt impl"),
    "idx.name.TATA": _e("Akrual total dibanding total aset", "Total accruals relative to total assets", "Gail 28 Okt impl"),
    "idx.expander": _e("Kedelapan indeks Beneish", "The eight Beneish indices", "Gail 28 Okt impl"),
    "idx.col.index": _e("Indeks", "Index", "Gail 28 Okt impl"),
    "idx.col.name": _e("Arti", "Meaning", "Gail 28 Okt impl"),
    "idx.col.value": _e("Nilai", "Value", "Gail 28 Okt impl"),
    "idx.col.coef": _e("Koefisien", "Coefficient", "Gail 28 Okt impl"),
    "idx.col.contribution": _e("Kontribusi ke M", "Contribution to M", "Gail 28 Okt impl"),
    "idx.col.push": _e("Dorongan vs netral", "Push vs neutral", "Gail 28 Okt impl"),
    "idx.col.note": _e("Penjelasan", "Explanation", "Gail 28 Okt impl"),
    "idx.caption": _e("Perusahaan netral: semua indeks 1 dan TATA 0. M = {const} + Σ koefisien × indeks.",
                      "Neutral company: all indices 1 and TATA 0. M = {const} + Σ coefficient × index.", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- verdicts (B r1 §6, r1/C6 7.x)
    "v.withheld": _e("M-score ditahan", "M-score withheld", "r1 9.8"),
    "v.held_nonppe": _e("Status penyusutan dan amortisasi selain aset tetap untuk {years} belum ditetapkan. Tetapkan "
                        "di bagian '{section}'. Mesin tidak mengisi 'tidak ada' sendiri.",
                        "The status of depreciation and amortisation other than PPE for {years} has not been set. Set "
                        "it in the '{section}' section. The machine does not enter 'none' by itself.", "r1 9.8", "Q6"),
    "v.held_amort": _e("Aset takberwujud tidak ditemukan oleh pembaca untuk {years}. Tetapkan statusnya di bagian "
                       "'{section}'. Mesin tidak mengisi 0 sendiri; 'tidak ditemukan' tidak sama dengan 'tidak ada'.",
                       "The reader found no intangible assets for {years}. Set the status in the '{section}' section. "
                       "The machine does not enter 0 by itself; 'not found' is not the same as 'none'.", "r1 9.16",
                       "M-15"),
    "v.not_calc": _e("M-score tidak dihitung", "M-score not calculated", "r0 7.12"),
    "v.not_calc_detail": _e("Alasan: {reason}. Tidak ada angka yang ditebak atau diisi 0.",
                            "Reason: {reason}. No figure was guessed or entered as 0.", "B r1 §6"),
    "v.missing_inputs": _e("Input yang belum ada: {items}", "Inputs not available: {items}", "Gail 28 Okt impl"),
    "v.unreadable_detail": _e("{why} Tidak ada angka yang ditebak.", "{why} No figure was guessed.", "Gail 28 Okt impl"),
    "v.unusable": _e("M-score tidak dapat dipakai", "The M-score cannot be used", "B r1 §6"),
    "v.unusable_detail": _e("Angka yang dibaca kemungkinan salah ({checks}). Periksa di PDF.",
                            "The figures as read may be wrong ({checks}). Check them in the PDF.", "B r1 §6"),
    "v.rejected_detail": _e("{name} menandai {n} hal tidak sesuai laporan ({items}). Angka terkait perlu diperiksa.",
                            "{name} marked {n} items as not matching the report ({items}). The figures concerned need "
                            "checking.", "Gail 28 Okt C6 7.11"),
    "v.someone": _e("Pengguna", "The user", "Gail 28 Okt impl"),
    "v.below": _e("M-score {m}: tidak melewati batas {thr}", "M-score {m}: does not cross the {thr} threshold",
                  "Gail 28 Okt C6 7.6"),
    "v.below_detail": _e("Bukan jaminan laporan bebas salah saji.",
                         "This does not guarantee the statements are free of misstatement.", "Gail 28 Okt C6 7.6"),
    "v.above": _e("M-score {m}: melewati batas {thr}", "M-score {m}: crosses the {thr} threshold", "Gail 28 Okt C6 7.7"),
    "v.above_detail": _e("Angka terkait perlu diperiksa lebih lanjut; bukan bukti kecurangan atau salah saji.",
                         "The related figures warrant closer examination; this is not evidence of fraud or "
                         "misstatement.", "Gail 28 Okt C6 7.7"),
    "v.above_detail_idx": _e("Angka terkait perlu diperiksa lebih lanjut, terutama {indices}; bukan bukti kecurangan "
                             "atau salah saji.",
                             "The related figures warrant closer examination, especially {indices}; this is not "
                             "evidence of fraud or misstatement.", "B r1 §6"),
    "v.provisional": _e("Sementara: {n} dari {m} hal kuning belum diperiksa.",
                        "Provisional: {n} of {m} yellow items not yet checked.", "Gail 28 Okt C6 7.9"),
    "v.confirmed": _e("Semua {m} hal kuning dinyatakan Sesuai oleh {name}. Ini konfirmasi pengguna, bukan verifikasi "
                      "independen.",
                      "{name} marked all {m} yellow items as matching the report. This is user confirmation, not "
                      "independent verification.", "Gail 28 Okt C6 7.10"),
    "v.transition": _e("Tahun {t} adalah tahun pertama penerapan {std}; kolom tahun lalu disusun dengan standar lama. "
                       "Perbandingan {indices} dibaca dengan hati-hati.",
                       "{t} is the first year of {std}; the prior-year column follows the previous standard. Read "
                       "the {indices} comparison with care.", "B r1 §6", "M-08"),
    "v.restated": _e("Kolom tahun lalu disajikan kembali; lihat pengungkapannya di CALK ({psak208}).",
                     "The prior-year column was restated; see the disclosure in the notes ({psak208}).", "B r1 §6",
                     "M-08"),
    "years.t": _e("tahun berjalan", "the current year", "r0 9.8"),
    "years.t1": _e("tahun pembanding", "the comparative year", "r0 9.8"),
    "years.and": _e("{a} dan {b}", "{a} and {b}", "Gail 28 Okt impl"),

    "st.NOT CALCULATED": _e("Tidak dihitung", "Not calculated", "Gail 28 Okt impl"),
    "st.CALCULATED": _e("Dihitung", "Calculated", "Gail 28 Okt impl"),
    "st.NOT USABLE (cross-check error)": _e("Tidak dapat dipakai: pemeriksaan silang gagal",
                                            "Cannot be used: a cross-check failed", "Gail 28 Okt impl"),
    "st.AWAITING NON-PPE STATUS": _e("Ditahan: status non-aset tetap belum ditetapkan", "Withheld: non-PPE status not set",
                                     "r1 9.9"),
    "st.AWAITING AMORTISATION STATUS": _e("Ditahan: status amortisasi aset takberwujud belum ditetapkan",
                                          "Withheld: amortisation status not set", "r1 9.17"),
    "st.PROVISIONAL (inputs to check)": _e("Sementara: ada input yang perlu diperiksa",
                                           "Provisional: some inputs need review", "Gail 28 Okt impl"),
    "st.bad": _e("Tidak dapat dipakai: ada input yang ditandai tidak sesuai",
                 "Cannot be used: an input was marked as not matching", "Gail 28 Okt impl"),
    "st.confirmed": _e("Dikonfirmasi pengguna (bukan verifikasi independen)",
                       "Confirmed by the user (not independent verification)", "Gail 28 Okt impl"),

    # engine not-ready reasons (engine.not_ready_reason; the engine strings stay as in the workbook)
    "reason.basis": _e("jenis laporan, mata uang atau satuan tidak disebutkan",
                       "statement type, currency or unit not specified", "Gail 28 Okt impl"),
    "reason.inputs_t": _e("ada input wajib yang kosong atau bukan angka (tahun berjalan)",
                          "a required input is missing or not a number (current year)", "Gail 28 Okt impl"),
    "reason.inputs_t1": _e("ada input wajib yang kosong atau bukan angka (tahun pembanding)",
                           "a required input is missing or not a number (comparative year)", "Gail 28 Okt impl"),
    "reason.nonppe_t": _e("status penyusutan dan amortisasi selain aset tetap belum ditetapkan (tahun berjalan)",
                          "status of non-PPE depreciation and amortisation not set (current year)", "Gail 28 Okt impl"),
    "reason.nonppe_t1": _e("status penyusutan dan amortisasi selain aset tetap belum ditetapkan (tahun pembanding)",
                           "status of non-PPE depreciation and amortisation not set (comparative year)", "Gail 28 Okt impl"),
    "reason.ppedep_t": _e("pemeriksaan penyusutan aset tetap gagal (tahun berjalan)",
                          "the PPE depreciation check failed (current year)", "Gail 28 Okt impl"),
    "reason.ppedep_t1": _e("pemeriksaan penyusutan aset tetap gagal (tahun pembanding)",
                           "the PPE depreciation check failed (comparative year)", "Gail 28 Okt impl"),
    "reason.ticker": _e("kode saham atau tahun buku tidak valid", "ticker or financial year not valid", "Gail 28 Okt impl"),
    "reason.denominator": _e("ada penyebut yang tidak valid atau nol", "a denominator is invalid or zero", "Gail 28 Okt impl"),
    "reason.incomplete": _e("input belum lengkap", "inputs incomplete", "Gail 28 Okt impl"),
    "reason.other": _e("alasan teknis: {raw}", "technical reason: {raw}", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- confirmation
    "confirm.title": _e("Konfirmasi: {n} hal perlu diperiksa", "Confirmation: {n} items to check", "Gail 28 Okt C6 7.17"),
    "confirm.caption": _e("Buka halaman PDF yang disebut, lalu tandai tiap hal. Dicatat di hasil unduhan; bukan "
                          "verifikasi independen.",
                          "Open the PDF page shown and mark each item. Recorded in the download; not independent "
                          "verification.", "Gail 28 Okt C6 7.17"),
    "confirm.PENDING": _e("Belum diperiksa", "Not checked", "Gail 28 Okt C6 7.18"),
    "confirm.OK": _e("Sesuai", "Matches", "Gail 28 Okt C6 7.18"),
    "confirm.BAD": _e("Tidak sesuai", "Does not match", "Gail 28 Okt C6 7.18"),
    "confirm.reviewer": _e("Diperiksa oleh", "Checked by", "r0 7.19"),
    "confirm.none": _e("Tidak ada hal yang perlu dikonfirmasi.", "Nothing to confirm.", "Gail 28 Okt impl"),
    "confirm.why": _e("{status}. {note}", "{status}. {note}", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- input table, cross-checks, CSV
    "inputs.title": _e("Angka yang dibaca dari laporan keuangan", "Figures read from the financial statements", "r0 7.16"),
    "inputs.col.item": _e("Pos", "Line item", "Gail 28 Okt impl"),
    "inputs.col.status": _e("Status {y}", "Status {y}", "Gail 28 Okt impl"),
    "inputs.col.pages": _e("Halaman PDF", "PDF page", "Gail 28 Okt impl"),
    "inputs.col.source": _e("Baris sumber", "Source line", "Gail 28 Okt impl"),
    "inputs.col.note": _e("Keterangan", "Remarks", "Gail 28 Okt impl"),
    "inputs.caption": _e("Angka dalam satuan laporan ({unit}). Kuning = dipakai dalam perhitungan tetapi perlu "
                         "diperiksa; merah = tidak ditemukan, sehingga rasio terkait tidak dihitung.",
                         "Figures in the report's unit ({unit}). Yellow = used in the calculation but needs review; "
                         "red = not found, so the related ratios are not calculated.", "Gail 28 Okt impl"),
    "checks.expander": _e("Pemeriksaan silang ({ok} lolos · {err} gagal · {rev} perlu diperiksa)",
                          "Cross-checks ({ok} passed · {err} failed · {rev} need review)", "Gail 28 Okt impl"),
    "checks.line": _e("{msg} ({cols}; {src}: {code})", "{msg} ({cols}; {src}: {code})", "Gail 28 Okt impl"),
    "checks.src.workbook": _e("aturan buku kerja WARS", "WARS workbook rule", "Gail 28 Okt impl"),
    "checks.src.app": _e("aturan aplikasi", "app rule", "Gail 28 Okt impl"),
    "checks.passed_line": _e("{name} ({col}) {detail}", "{name} ({col}) {detail}", "Gail 28 Okt impl"),
    "issues.expander": _e("Catatan pembacaan ({n})", "Reading notes ({n})", "Gail 28 Okt impl"),
    "csv.button": _e("Unduh angka dan sumbernya (CSV)", "Download figures and sources (CSV)", "Gail 28 Okt C6 7.20"),
    "col.t": _e("{y}", "{y}", "Gail 28 Okt impl"),
    "col.both": _e("{a} dan {b}", "{a} and {b}", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- user-set statuses (M-06, M-15)
    "np.title": _e("Penyusutan dan amortisasi selain aset tetap: wajib ditetapkan",
                   "Depreciation and amortisation other than PPE: status required", "r1 9.4"),
    "np.caption": _e("Status harus ditetapkan untuk tiap tahun. Mesin hanya mencari dan menunjukkan bukti; 'tidak "
                     "ditemukan' tidak sama dengan 'tidak ada'. M-score ditahan sampai kedua tahun ditetapkan.",
                     "The status must be set for each year. The machine only searches and shows evidence; 'not "
                     "found' is not the same as 'none'. The M-score is withheld until both years are set.", "r1 9.5",
                     "Q6"),
    "np.opt.": _e("Belum ditetapkan", "Not set", "r1 9.6"),
    "np.opt.NONE_PRESENT": _e("Tidak ada", "None", "r1 9.6"),
    "np.opt.ALL_DISCLOSED": _e("Ada, seluruhnya diungkapkan", "Present, fully disclosed", "r1 9.6"),
    "np.opt.PARTIAL_UNDISCLOSED": _e("Ada, sebagian/seluruhnya tidak diungkapkan", "Present, partly or wholly not disclosed",
                                     "r1 9.6"),
    "np.notes": _e("Catatan yang Anda periksa ({y})", "Notes you examined ({y})", "r1 9.7"),
    "np.extra": _e("Catatan lain yang diperiksa ({y}), pisahkan dengan ;", "Other notes examined ({y}), separated by ;",
                   "r1 9.7"),
    "np.year": _e("Tahun {y}", "Year {y}", "Gail 28 Okt impl"),
    "np.status": _e("Status {y}", "Status {y}", "Gail 28 Okt impl"),
    "np.hit": _e("hal. {p}: {text}", "p. {p}: {text}", "Gail 28 Okt impl"),
    "np.hit_amount": _e("(ada angka)", "(with an amount)", "Gail 28 Okt impl"),
    "np.found": _e("{label}: ditemukan {n} kali", "{label}: found {n} time(s)", "Gail 28 Okt impl"),
    "np.not_found": _e("{label}: tidak ditemukan oleh pencarian mesin.", "{label}: not found by the machine search.", "Gail 28 Okt impl"),
    "np.amounts": _e("Jumlah yang terbaca: {list} ({source})", "Amounts read: {list} ({source})", "Gail 28 Okt impl"),
    "np.source": _e("hal. {p}: {text}", "p. {p}: {text}", "Gail 28 Okt impl"),
    "np.err_notes": _e("Belum diterapkan: pilih catatan yang Anda periksa untuk 'Tidak ada'.",
                       "Not applied: select the notes you examined for 'None'.", "Gail 28 Okt impl"),
    "np.err_amount": _e("Belum diterapkan: 'Ada, seluruhnya diungkapkan' hanya bisa dipilih bila jumlahnya terbaca "
                        "dari CALK.",
                        "Not applied: 'Present, fully disclosed' can be chosen only when the amount was read from the "
                        "notes.", "Gail 28 Okt impl", "M-14"),
    "np.applied": _e("Diterapkan: {choice}", "Applied: {choice}", "r1 9.15"),
    "np.group.investment_property": _e("Properti investasi", "Investment property", "Gail 28 Okt impl"),
    "np.group.unused_assets": _e("Aset yang tidak digunakan / dihentikan penggunaannya",
                                 "Assets not in use or retired from active use", "Gail 28 Okt impl"),
    "np.group.long_term_costs": _e("Amortisasi biaya jangka panjang (biaya ditangguhkan, hak atas tanah, dll.)",
                                   "Amortisation of long-term costs (deferred charges, land rights, etc.)", "Gail 28 Okt impl"),
    "am.title": _e("Amortisasi aset takberwujud: wajib ditetapkan", "Amortisation of intangible assets: status required",
                   "r1 9.10"),
    "am.caption": _e(
        "Pembaca tidak menemukan aset takberwujud. 'Tidak ditemukan' tidak sama dengan 'tidak ada', jadi mesin tidak "
        "mengisi 0 sendiri. Periksa CALK, lalu tetapkan status untuk tiap tahun dan catat catatan atau halaman yang "
        "Anda periksa. Bila Anda tidak dapat memastikan, biarkan 'Belum ditetapkan': M-score tetap ditahan. Bila "
        "Anda melihat angka amortisasi di CALK yang tidak terbaca, biarkan juga 'Belum ditetapkan': skor ditahan "
        "karena pembaca gagal membaca angka tersebut; Anda tidak perlu dan tidak dapat mengisi angka.",
        "The reader found no intangible assets. 'Not found' is not the same as 'none', so the machine does not enter "
        "0 by itself. Check the notes, then set the status for each year and record the notes or pages you "
        "examined. If you cannot be sure, leave 'Not set': the M-score stays withheld. If you see an amortisation "
        "amount in the notes that was not read, also leave 'Not set': the score is withheld because the reader "
        "failed to read it; you do not need to, and cannot, enter any figure.", "r1 9.11", "M-15"),
    "am.opt.": _e("Belum ditetapkan", "Not set", "r1 9.12"),
    "am.opt.NONE_PRESENT": _e("Tidak ada aset takberwujud", "No intangible assets", "r1 9.12"),
    "am.opt.GOODWILL_ONLY": _e("Hanya goodwill; tidak ada aset takberwujud lain yang diamortisasi",
                               "Goodwill only; no other intangible asset to amortise", "r1 9.12"),
    "am.opt.INDEFINITE_ONLY": _e("Ada aset takberwujud, seluruhnya berumur manfaat tidak terbatas (tidak diamortisasi)",
                                 "Intangible assets present, all with indefinite useful lives (not amortised)",
                                 "r1 9.12"),
    "am.opt.UNDISCLOSED": _e("Ada aset takberwujud, tetapi amortisasinya tidak diungkapkan",
                             "Intangible assets present, but amortisation not disclosed", "r1 9.12"),
    "am.status": _e("Status amortisasi {y}", "Amortisation status {y}", "Gail 28 Okt impl"),
    "am.notes": _e("Catatan yang Anda periksa ({y})", "Notes you examined ({y})", "r1 9.13"),
    "am.extra": _e("Catatan/halaman lain yang diperiksa ({y}), pisahkan dengan ;",
                   "Other notes/pages examined ({y}), separated by ;", "r1 9.13"),
    "am.err": _e("Belum diterapkan: pilih atau tulis catatan/halaman yang Anda periksa.",
                 "Not applied: select or type the notes/pages you examined.", "r1 9.14"),

    # ---------------------------------------------------------------- field labels (r0 §8, r1 C7)
    "label.revenue": _e("Pendapatan (penjualan neto)", "Revenue (net sales)", "r0 8"),
    "label.cost_of_goods_sold": _e("Beban pokok penjualan", "Cost of goods sold", "r0 8"),
    "label.selling_general_administrative_expenses": _e("Beban penjualan dan beban umum & administrasi",
                                                         "Selling, general and administrative expenses", "r1 C7"),
    "label.accounts_receivable": _e("Piutang usaha pihak ketiga dan berelasi (tidak termasuk aset kontrak)",
                                    "Trade receivables from third parties and related parties (excluding contract "
                                    "assets)", "r1 C7"),
    "label.contract_assets": _e("Aset kontrak (tidak dihitung sebagai piutang)",
                                "Contract assets (not counted as receivables)", "r1 C7"),
    "label.total_assets": _e("Total aset", "Total assets", "r0 8"),
    "label.current_assets": _e("Aset lancar", "Current assets", "r0 8"),
    "label.cash_and_cash_equivalents": _e("Kas dan setara kas", "Cash and cash equivalents", "r0 8"),
    "label.property_plant_equipment_net": _e("Aset tetap neto + aset hak-guna (sesuai definisi WARS)",
                                             "Net PPE + right of use assets (under the WARS definition)", "r1 C7"),
    "label.rou_assets_net": _e("di antaranya: aset hak-guna", "of which: right of use assets", "r0 8"),
    "label.current_liabilities": _e("Liabilitas jangka pendek", "Current liabilities", "r0 8"),
    "label.total_liabilities": _e("Total liabilitas", "Total liabilities", "r0 8"),
    "label.noncurrent_liabilities": _e("liabilitas jangka panjang", "non-current liabilities", "Gail 28 Okt impl"),
    "label.long_term_debt": _e("Utang berbunga jangka panjang", "Interest-bearing long-term debt", "r0 8"),
    "label.current_maturities_long_term_debt": _e("Bagian lancar utang jangka panjang", "Current portion of long-term debt",
                                                  "r0 8"),
    "label.taxes_payable": _e("Utang pajak penghasilan badan (Pasal 25 dan 29)",
                              "Corporate income tax payable (Articles 25 and 29)", "r0 8"),
    "label.ppe_depreciation_disclosed": _e("Beban penyusutan aset tetap milik + aset hak-guna bila diungkapkan",
                                           "Owned-PPE depreciation plus right of use depreciation where disclosed",
                                           "r1 C7"),
    "label.ppe_depreciation_owned": _e("Beban penyusutan aset tetap milik", "Owned-PPE depreciation", "Gail 28 Okt impl"),
    "label.rou_depreciation": _e("di antaranya: penyusutan aset hak-guna", "of which: right of use depreciation", "r0 8"),
    "label.amortization_intangibles": _e("Amortisasi aset takberwujud", "Amortisation of intangible assets", "r0 8"),
    "label.depreciation_amortization_non_ppe": _e(
        "Penyusutan dan amortisasi aset selain aset tetap/hak-guna dan aset takberwujud",
        "Depreciation and amortisation of assets other than PPE/right of use assets and intangible assets", "r1 C7"),
    "label.depreciation_amortization_total": _e("Total penyusutan dan amortisasi", "Total depreciation and amortisation",
                                                "r0 8"),
    "label.net_income": _e("Laba tahun berjalan (sebagai pembanding)", "Profit for the year (comparison only)", "r0 8"),
    "label.cash_flow_from_operations": _e("Arus kas dari aktivitas operasi (sebagai pembanding)",
                                          "Cash flows from operating activities (comparison only)", "r0 8"),
    "label.amort_status": _e("Status amortisasi", "Amortisation status", "Gail 28 Okt impl"),
    "label.non_ppe_status": _e("Status penyusutan dan amortisasi selain aset tetap",
                               "Status of non-PPE depreciation and amortisation", "Gail 28 Okt impl"),
    "label.statement_type": _e("Jenis laporan", "Statement type", "Gail 28 Okt impl"),
    "label.reporting_currency": _e("Mata uang pelaporan", "Reporting currency", "Gail 28 Okt impl"),
    "label.unit_scale": _e("Satuan penyajian", "Presentation unit", "Gail 28 Okt impl"),

    "unit.Units": _e("Rupiah penuh", "Rupiah", "Gail 28 Okt impl"),
    "unit.Thousands": _e("ribuan Rupiah", "thousands of Rupiah", "Gail 28 Okt impl"),
    "unit.Millions": _e("jutaan Rupiah", "millions of Rupiah", "Gail 28 Okt impl"),
    "unit.Billions": _e("miliar Rupiah", "billions of Rupiah", "Gail 28 Okt impl"),
    "unit.unknown": _e("tidak diketahui", "unknown", "Gail 28 Okt impl"),
    "stype.Consolidated": _e("konsolidasian", "consolidated", "Gail 28 Okt impl"),
    "stype.unknown": _e("jenis laporan tidak diketahui", "statement type unknown", "Gail 28 Okt impl"),
    "stmt.position": _e("Laporan posisi keuangan", "Statement of financial position", "r0 1.1"),
    "stmt.profit_loss": _e("Laporan laba rugi", "Statement of profit or loss", "r0 1.2"),
    "stmt.cash_flow": _e("Laporan arus kas", "Statement of cash flows", "r0 1.3"),
    "where.face": _e("laporan posisi keuangan", "statement of financial position", "r0 1.1"),
    "where.notes": _e("CALK", "notes", "r0 1.4"),

    # ---------------------------------------------------------------- value statuses (r0 §2, r1 C1)
    "status.FOUND": _e("Terbaca dan tercocokkan", "Read and reconciled", "r0 2.1"),
    "status.REVIEW": _e("Perlu diperiksa", "Needs review", "r1 2.2"),
    "status.UNDISCLOSED": _e("Tidak diungkapkan (diperlakukan sebagai 0 sesuai aturan; bukan berarti jumlah "
                             "sebenarnya nol)",
                             "Not disclosed (treated as 0 under the rule; this does not mean the actual amount is "
                             "zero)", "r1 2.3"),
    "status.BUILT FROM DISCLOSED COMPONENTS": _e("Dijumlahkan dari komponen yang diungkapkan",
                                                 "Sum of disclosed components", "r0 2.4"),
    "status.NOT DISCLOSED": _e("Nilai tidak tersedia (dibiarkan kosong)", "Value unavailable (left blank)", "r1 2.5"),
    "status.NOT FOUND": _e("Tidak ditemukan dalam pencarian", "Not found in the search", "r1 2.6"),
    "status.STATEMENT NOT FOUND": _e("Laporan utama tidak ditemukan dalam dokumen yang diperiksa",
                                     "Primary statements not found in the document examined", "r1 2.7"),
    "status.NOT SEARCHED": _e("Belum dicari karena laporan utama tidak dapat dibaca",
                              "Not searched because the primary statements could not be read", "r1 2.8"),
    "status.NOT ASSESSED": _e("Belum ditetapkan pengguna; skor ditahan", "Not yet set by the user; score withheld",
                              "r1 2.9"),
    "status.USER SET": _e("Ditetapkan pengguna", "Set by the user", "r1 2.10"),
    "status.INCLUDED IN PPE": _e("Sudah termasuk dalam aset tetap (tidak ditambahkan lagi)",
                                 "Already included in PPE (not added again)", "r1 2.11"),

    # ---------------------------------------------------------------- notes per value (r0 §3, r1 C2)
    "note.ar": _e("Piutang usaha pihak ketiga dan berelasi; aset kontrak tidak termasuk",
                  "Trade receivables from third parties and related parties; excludes contract assets", "r1 3.1",
                  "D-04", "G-06"),
    "note.ar_combined": _e("Piutang usaha disajikan bersama aset kontrak; tidak dapat dipisahkan dari laporan utama dan "
                           "tidak diperkirakan; periksa catatan piutang atau pendapatan",
                           "Trade receivables presented together with contract assets; they cannot be separated from "
                           "the primary statements and nothing is estimated; check the receivables or revenue note",
                           "r1 9.19", "G-06"),
    "note.contract_assets": _e("Aset kontrak disajikan terpisah (hal. {p}): tidak dihitung sebagai piutang usaha untuk "
                               "DSRI",
                               "Contract assets presented separately (p. {p}): not counted as trade receivables for "
                               "DSRI", "r1 9.18", "G-06"),
    "note.sga": _e("Jumlah beban penjualan dan beban umum & administrasi sesuai laporan laba rugi",
                   "Selling expenses plus general and administrative expenses as presented", "r0 3.2"),
    "note.ppe_face_only": _e("Hanya baris laporan posisi keuangan; aset hak-guna yang disajikan di tempat lain perlu "
                             "ditambahkan",
                             "Statement of financial position line only; right of use assets presented elsewhere must "
                             "be added", "Gail 28 Okt impl", "D-08"),
    "note.ppe_plus_rou_face": _e("Aset tetap ditambah aset hak-guna yang disajikan di laporan posisi keuangan",
                                 "PPE plus right of use assets presented in the statement of financial position",
                                 "r0 3.3", "D-08"),
    "note.ppe_plus_rou_notes": _e("Aset tetap ditambah aset hak-guna yang disajikan dalam aset lain-lain (CALK)",
                                  "PPE plus right of use assets presented within other assets (notes)", "r0 3.4", "D-08"),
    "note.ppe_rou_inside": _e("Aset tetap sesuai laporan; aset hak-guna sudah termasuk di baris ini ({psak116}), tidak "
                              "ditambahkan lagi",
                              "PPE as presented; right of use assets are included in this line ({psak116}), not added "
                              "again", "Gail 28 Okt impl", "D-08"),
    "note.ppe_only": _e("Nilai aset hak-guna untuk tahun ini tidak ditemukan; sementara hanya aset tetap yang dipakai, "
                        "perlu diperiksa",
                        "Right of use amount for this year not found; PPE only is used for now and needs review",
                        "r1 3.5", "D-08"),
    "note.rou_face": _e("Aset hak-guna, disajikan di laporan posisi keuangan",
                        "Right of use assets, presented in the statement of financial position", "r0 3.6", "D-08"),
    "note.rou_notes": _e("Aset hak-guna di dalam aset lain-lain (CALK); dijumlahkan ke aset tetap",
                         "Right of use assets within other assets (notes); added to PPE", "r0 3.7", "D-08"),
    "note.rou_inside": _e("Aset hak-guna disajikan di dalam aset tetap ({psak116}); sudah termasuk di angka aset "
                          "tetap, tidak ditambahkan lagi",
                          "Right of use assets presented within PPE ({psak116}); already in the PPE figure, not added "
                          "again", "Gail 28 Okt impl", "D-08"),
    "note.rou_none": _e("Baris aset hak-guna tidak ditemukan di laporan utama maupun di CALK",
                        "No right of use line found in the primary statements or in the notes", "Gail 28 Okt impl", "D-08"),
    "note.debt": _e("Dipilih berdasarkan nama akun; periksa klasifikasinya",
                    "Selected by line-item label; check the classification", "r0 3.8", "D-01", "D-02"),
    "note.ltd_none": _e("Tidak ditemukan baris utang berbunga jangka panjang menurut nama akun; nilai nihil perlu "
                        "dipastikan",
                        "No interest-bearing non-current line found by label; a nil balance needs confirming", "Gail 28 Okt impl",
                        "G-24"),
    "note.cm_none": _e("Tidak ditemukan baris bagian lancar utang jangka panjang menurut nama akun; nilai nihil perlu "
                       "dipastikan",
                       "No current-portion line found by label; a nil balance needs confirming", "Gail 28 Okt impl", "G-24"),
    "note.tax": _e("PPh badan Pasal 25 dan 29 seluruh grup; PPh potong/pungut, PPN, pajak final dan pajak lain tidak "
                   "dimasukkan",
                   "Corporate income tax (Articles 25 and 29) of the group; withholding taxes, VAT, final and other "
                   "taxes excluded", "r0 3.9", "D-03"),
    "note.tax_foreign": _e("baris pajak luar negeri tidak dimasukkan (lihat catatan pembacaan)",
                           "foreign tax line(s) excluded (see reading notes)", "M-05 (r0 3.10)", "D-03"),
    "note.tax_none": _e("Tabel utang pajak dengan baris Pasal 25/29 tidak ditemukan di CALK",
                        "No taxes-payable table with Article 25/29 lines found in the notes", "Gail 28 Okt impl", "D-03"),
    "note.alloc_ppe_ok": _e("Aset tetap milik: total tabel alokasi beban penyusutan; dicocokkan dengan beban penyusutan "
                            "tahun berjalan di tabel mutasi",
                            "Owned PPE: total of the depreciation allocation table, agreed to the charge for the year "
                            "in the movement schedule", "r1 3.11"),
    "note.alloc_ppe": _e("Aset tetap milik: total tabel alokasi beban penyusutan; belum dicocokkan dengan tabel mutasi",
                         "Owned PPE: total of the depreciation allocation table; not agreed to the movement schedule",
                         "Gail 28 Okt impl"),
    "note.alloc_rou_ok": _e("Aset hak-guna: total tabel alokasi beban penyusutan; dicocokkan dengan beban tahun berjalan "
                            "di tabel mutasi",
                            "Right of use assets: total of the depreciation allocation table, agreed to the charge for "
                            "the year in the movement schedule", "r1 3.14"),
    "note.alloc_rou": _e("Aset hak-guna: total tabel alokasi beban penyusutan; belum dicocokkan dengan tabel mutasi",
                         "Right of use assets: total of the depreciation allocation table; not agreed to the movement "
                         "schedule", "Gail 28 Okt impl"),
    "note.alloc_intang_ok": _e("Aset takberwujud: total tabel alokasi beban amortisasi; dicocokkan dengan beban tahun "
                               "berjalan di tabel mutasi",
                               "Intangible assets: total of the amortisation allocation table, agreed to the charge "
                               "for the year in the movement schedule", "Gail 28 Okt impl"),
    "note.alloc_intang": _e("Aset takberwujud: total tabel alokasi beban amortisasi; belum dicocokkan dengan tabel "
                            "mutasi",
                            "Intangible assets: total of the amortisation allocation table; not agreed to the "
                            "movement schedule", "Gail 28 Okt impl"),
    "note.alloc_components": _e("komponen tabel tidak berjumlah sama dengan totalnya",
                                "the table's components do not add up to its total", "Gail 28 Okt impl"),
    "note.alloc_single": _e("Tabel hanya berisi satu baris dan tidak dapat dicocokkan dengan tabel mutasi",
                            "Single-line table; could not be agreed to the movement schedule", "r1 3.15"),
    "note.alloc_combined_ok": _e("Judul tabel menyebut \"penyusutan dan amortisasi\", tetapi totalnya sama dengan beban "
                                 "penyusutan tahun berjalan di tabel mutasi aset tetap",
                                 "The table is titled \"depreciation and amortisation\", but its total equals the "
                                 "depreciation charge for the year in the PPE movement schedule", "r1 3.13"),
    "note.alloc_combined": _e("Judul tabel menyebut \"penyusutan dan amortisasi\"; periksa apa yang diamortisasi",
                              "The table is titled \"depreciation and amortisation\"; check what is amortised", "Gail 28 Okt impl"),
    "note.order": _e("Angka dibaca menurut urutan teks karena posisi teks PDF di halaman ini tidak dapat diandalkan; "
                     "periksa kutipan dan halaman sumber",
                     "Figures read in text order because the text positions on this PDF page are unreliable; check the "
                     "quoted line and source page", "r1 3.12"),
    "note.alloc_none": _e("Tabel alokasi beban penyusutan tidak ditemukan di catatan aset tetap",
                          "No depreciation allocation table found in the PPE note", "Gail 28 Okt impl"),
    "note.rou_dep_none": _e("Penyusutan aset hak-guna tidak diungkapkan; dibiarkan kosong, tidak diisi 0",
                            "Right of use depreciation not disclosed; left blank, not entered as 0", "r0 3.16",
                            "G-23", "Q5"),
    "note.dep_owned_rou": _e("Penyusutan aset tetap milik + penyusutan aset hak-guna; kedua angka tercetak, masing-masing "
                             "sumber dicatat; periode, entitas dan basis sama",
                             "Owned PPE depreciation plus right of use depreciation; both printed, each source "
                             "recorded; same period, entity and basis", "r1 3.17", "G-23", "M-01"),
    "note.dep_owned_only": _e("Hanya penyusutan aset tetap milik, karena penyusutan aset hak-guna tidak diungkapkan",
                              "Owned PPE depreciation only, because right of use depreciation is not disclosed",
                              "r0 3.18", "G-23", "DP-04"),
    "note.dep_rou_inside": _e("Aset hak-guna disajikan di dalam aset tetap: penyusutan aset tetap sudah memuat penyusutan "
                              "aset hak-guna; tabel aset hak-guna tidak ditambahkan ({psak116})",
                              "Right of use assets are presented within PPE: the PPE depreciation already includes "
                              "right of use depreciation; the right of use table is not added ({psak116})", "Gail 28 Okt impl",
                              "D-08"),
    "note.amort": _e("Amortisasi tahun berjalan dari CALK aset takberwujud",
                     "Amortisation for the year, from the intangible-asset note", "r0 3.19"),
    "note.amort_sum": _e("baris-baris tidak berjumlah sama dengan subtotal", "the lines do not add up to the sub-total",
                         "Gail 28 Okt impl"),
    "note.amort_fx": _e("Baris selisih kurs penjabaran di dalam blok tidak dihitung sebagai amortisasi; baris itu dicatat "
                        "sebagai bukti ({evidence}); {psak238}",
                        "Foreign-currency translation line(s) within the block excluded from amortisation; kept as "
                        "evidence ({evidence}); {psak238}", "r1 3.20", "M-03"),
    "note.amort_disclosed": _e("amortisasi diungkapkan", "amortisation disclosed", "Gail 28 Okt impl"),
    "note.amort_undisclosed": _e("Ada aset takberwujud, tetapi amortisasinya tidak diungkapkan; komponen diperlakukan "
                                 "sebagai 0 sesuai aturan dan perlu diperiksa. Ini bukan pernyataan bahwa beban "
                                 "sebenarnya nol",
                                 "Intangible assets exist, but their amortisation is not disclosed; the component is "
                                 "treated as 0 under the rule and needs review. This does not state that the actual "
                                 "charge is nil", "r1 3.21", "G-22"),
    "note.amort_not_assessed": _e("Pembaca tidak menemukan aset takberwujud; tidak ditemukan bukan berarti nihil. Status "
                                  "ditetapkan pengguna per tahun",
                                  "The reader found no intangible assets; not found does not mean nil. The status is "
                                  "set by the user for each year", "Gail 28 Okt impl", "M-15"),
    "note.nonppe_not_assessed": _e("Status penyusutan dan amortisasi selain aset tetap belum ditetapkan pengguna; tidak "
                                   "diisi 0",
                                   "Status of non-PPE depreciation and amortisation not yet set by the user; not "
                                   "entered as 0", "Gail 28 Okt impl", "Q6", "M-06"),
    "note.ppe_dep_none": _e("Penyusutan aset tetap milik tidak ditemukan", "Owned-PPE depreciation not found", "Gail 28 Okt impl"),
    "note.dat_cannot": _e("Tidak dapat disusun karena penyusutan aset tetap tidak ditemukan; skor tidak dihitung",
                          "Cannot be built because PPE depreciation was not found; the score is not calculated", "Gail 28 Okt impl"),
    "note.dat_wait": _e("Menunggu status penyusutan dan amortisasi selain aset tetap dari pengguna",
                        "Waiting for the user to set the non-PPE depreciation and amortisation status", "Gail 28 Okt impl", "M-06"),
    "note.component_missing": _e("Ada komponen yang tidak tersedia", "A component is not available", "Gail 28 Okt impl"),
    "note.dat_built": _e("Dijumlahkan dari komponen yang diungkapkan; tidak pernah diturunkan dari selisih saldo",
                         "Sum of disclosed components; never derived from balance movements", "r0 3.24", "DP-01/02",
                         "Q2-c"),
    "note.notes_not_read_fs": _e("CALK tidak dibaca karena laporan utama tidak dapat dibaca; skor tidak dihitung",
                                 "Notes not read because the primary statements could not be read; score not "
                                 "calculated", "r1 3.25"),
    "note.notes_not_read_calk": _e("CALK tidak dibaca karena CALK tidak ditemukan setelah laporan utama; skor tidak "
                                   "dihitung",
                                   "Notes not read because no notes were found after the primary statements; score "
                                   "not calculated", "Gail 28 Okt impl"),
    "note.basis": _e("basis tidak disebutkan", "basis not specified", "Gail 28 Okt impl"),
    "note.np_pending": _e("Ditetapkan oleh pengguna", "To be set by the user", "Gail 28 Okt impl", "M-06"),
    "note.np_none": _e("Ditetapkan pengguna: tidak ada; catatan yang diperiksa: {notes}",
                       "Set by the user: none; notes examined: {notes}", "Gail 28 Okt impl", "M-06"),
    "note.np_all": _e("Ditetapkan pengguna: ada, seluruhnya diungkapkan; jumlah yang terbaca: {source}",
                      "Set by the user: present, fully disclosed; amount read: {source}", "Gail 28 Okt impl", "M-06"),
    "note.np_partial": _e("Ditetapkan pengguna: ada, sebagian/seluruhnya tidak diungkapkan; jumlah yang diungkapkan: "
                          "{source}",
                          "Set by the user: present, partly or wholly not disclosed; disclosed amount read: {source}",
                          "Gail 28 Okt impl", "M-06"),
    "note.np_partial_zero": _e("Ditetapkan pengguna: ada, sebagian/seluruhnya tidak diungkapkan; tidak ada jumlah yang "
                               "diungkapkan (0)",
                               "Set by the user: present, partly or wholly not disclosed; no amount disclosed (0)",
                               "Gail 28 Okt impl", "M-06"),
    "note.examined": _e("catatan yang diperiksa: {notes}", "notes examined: {notes}", "Gail 28 Okt impl"),
    "note.am_set": _e("Ditetapkan pengguna: {choice}; catatan yang diperiksa: {notes}",
                      "Set by the user: {choice}; notes examined: {notes}", "Gail 28 Okt impl", "M-15"),
    "note.am_g22": _e("0 adalah perlakuan aturan untuk komponen yang tidak diungkapkan, bukan pernyataan bahwa bebannya "
                      "nihil",
                      "0 is the rule's treatment of an undisclosed component, not a statement that the charge is nil",
                      "Gail 28 Okt impl", "G-22"),

    # components (how a value was added up)
    "comp.sum": _e("{parts}", "{parts}", "Gail 28 Okt impl"),
    "comp.ppe_rou": _e("{a} aset tetap + {b} aset hak-guna ({where})", "{a} PPE + {b} right of use ({where})", "Gail 28 Okt impl"),
    "comp.ppe_incl_rou": _e("{a} aset tetap termasuk hak-guna", "{a} PPE including right of use", "Gail 28 Okt impl"),
    "comp.owned_rou": _e("{a} aset tetap milik + {b} aset hak-guna", "{a} owned PPE + {b} right of use", "Gail 28 Okt impl"),
    "comp.owned": _e("{a} aset tetap milik", "{a} owned PPE", "Gail 28 Okt impl"),
    "comp.dat": _e("{a} aset tetap + {b} amortisasi yang diungkapkan + {c} selain aset tetap",
                   "{a} PPE + {b} disclosed amortisation + {c} non-PPE", "Gail 28 Okt impl"),
    "comp.zero_undisclosed": _e("0 = tidak ada yang diungkapkan (bukan nihil)", "0 = nothing disclosed (not nil)", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- reading notes (r0 §4, r1 C3, D1)
    "issue.fs_not_found": _e(
        "Laporan keuangan teraudit tidak ditemukan dalam dokumen ini (dicari di seluruh {n} halaman: laporan posisi "
        "keuangan, laba rugi dan arus kas yang memuat kolom Catatan, diikuti Catatan atas Laporan Keuangan). Ikhtisar "
        "keuangan tidak dipakai sebagai pengganti.",
        "Audited financial statements not found in this document (all {n} pages searched for a statement of "
        "financial position, profit or loss and cash flows with a Notes column, followed by the notes). Financial "
        "highlights are not used as a substitute.", "r1 9.1"),
    "issue.fs_candidates": _e("Kandidat sebagian: {list}.", "Partial candidates: {list}.", "Gail 28 Okt impl"),
    "issue.cand_item": _e("{stmt} (hal. {p})", "{stmt} (p. {p})", "Gail 28 Okt impl"),
    "issue.scanned": _e("{k} halaman berupa gambar hasil pindai tanpa teks (mis. hal. {pages}); bila laporan keuangan ada "
                        "di halaman itu, pembacaan gambar (OCR) belum didukung.",
                        "{k} pages are scanned images without text (e.g. p. {pages}); if the statements are on those "
                        "pages, image reading (OCR) is not yet supported.", "r1 9.2"),
    "issue.notes_not_found": _e("Catatan atas Laporan Keuangan (CALK) tidak ditemukan setelah laporan keuangan utama, "
                                "sehingga utang pajak, penyusutan dan amortisasi tidak dapat dibaca. Skor tidak dihitung.",
                                "Notes to the financial statements not found after the primary statements, so taxes "
                                "payable, depreciation and amortisation cannot be read. The score is not calculated.",
                                "r1 9.3"),
    "issue.year_labels": _e("{stmt}: label tahun tidak ditemukan di judul kolom; angka pertama dianggap tahun berjalan "
                            "(perlu diperiksa)",
                            "{stmt}: year labels not found in the column headings; the first figure is taken as the "
                            "current year (needs review)", "Gail 28 Okt impl"),
    "issue.stmt_missing": _e("{stmt}: tidak ditemukan di blok halaman {a}–{b}",
                             "{stmt}: not found in the page block {a}–{b}", "Gail 28 Okt impl"),
    "issue.unit": _e("Satuan penyajian (Rupiah penuh, ribuan, jutaan) tidak ditemukan. M-score tidak dihitung karena "
                     "basis satuan belum dapat dipastikan",
                     "Presentation unit (Rupiah, thousands, millions) not found. The M-score is not calculated because "
                     "the unit basis cannot be confirmed", "r1 4.2"),
    "issue.short_term_loans": _e("Utang bank jangka pendek tidak dimasukkan ke bagian lancar utang jangka panjang: "
                                 "{lines}. Pastikan tidak ada bagian lancar pinjaman jangka panjang di dalamnya",
                                 "Short-term bank loans excluded from the current portion of long-term debt: {lines}. "
                                 "Confirm that none is a current portion of a long-term loan", "r0 4.3", "D-02"),
    "issue.tax_foreign": _e("Pajak luar negeri tidak dimasukkan ke utang PPh badan: CALK tidak menyebutkan apakah pajak "
                            "ini dihitung dari laba ({line})",
                            "Foreign tax excluded from corporate income tax payable: the notes do not state whether it "
                            "is a tax on profit ({line})", "M-05 (r0 4.4)", "D-03"),
    "issue.tax_unclassified": _e("Baris catatan pajak yang tidak terklasifikasi, tidak dimasukkan (perlu diperiksa): "
                                 "{lines}",
                                 "Tax-note lines not classified and left out (needs review): {lines}", "Gail 28 Okt impl", "D-03"),
    "issue.table_unlinked": _e("Tabel penyusutan/amortisasi di hal. {p} tidak terkait dengan kelompok aset ('{title}'); "
                               "tidak dipakai (perlu diperiksa)",
                               "Depreciation/amortisation table on p. {p} not linked to an asset class ('{title}'); not "
                               "used (needs review)", "Gail 28 Okt impl"),
    "issue.rou_inside": _e("Aset hak-guna disajikan di dalam aset tetap (hal. {p}: '{quote}'): nilai tercatat aset tetap "
                           "dan penyusutan aset tetap milik sudah memuatnya; angka aset hak-guna tidak ditambahkan lagi "
                           "({psak116}). Perlu diperiksa",
                           "Right of use assets presented within PPE (p. {p}: '{quote}'): the PPE carrying amount and "
                           "the owned-PPE depreciation already include them; right of use figures are not added again "
                           "({psak116}). Needs review", "Gail 28 Okt impl", "D-08"),
    "issue.expense_amort": _e("Rincian beban mencantumkan amortisasi {x} (hal. {p}), lebih besar dari amortisasi aset "
                              "takberwujud {y}. Kemungkinan ada aset lain yang diamortisasi",
                              "Expense notes show amortisation of {x} (p. {p}), higher than intangible-asset "
                              "amortisation of {y}. Other assets may be amortised", "r0 4.5", "Q2-c"),
    "issue.transition_gap": _e("{std} pertama kali diterapkan di {t} (hal. {p}), tetapi CALK tidak menyebut apakah angka "
                               "pembanding disajikan kembali; periksa catatan transisi",
                               "{std} first applied in {t} (p. {p}), but the notes do not say whether the comparatives "
                               "were restated; check the transition note", "r1 6.18", "M-08"),
    "assume.first_issue": _e("Diasumsikan laporan ini adalah versi pertama yang diterbitkan (belum diverifikasi)",
                             "Assumed to be the first-issued version of the report (not verified)", "r0 4.7"),

    # ---------------------------------------------------------------- cross-checks (r0 §5, r1 C4)
    "check.balance": _e("Total aset = total liabilitas + ekuitas", "Total assets = total liabilities + equity", "r0 5.1"),
    "check.ca_ta": _e("Aset lancar ≤ total aset", "Current assets ≤ total assets", "r0 5.2"),
    "check.cl_tl": _e("Liabilitas jangka pendek ≤ total liabilitas", "Current liabilities ≤ total liabilities", "r0 5.3"),
    "check.gross_profit": _e("Pendapatan − beban pokok penjualan = laba bruto",
                             "Revenue − cost of goods sold = gross profit", "r0 5.4"),
    "check.tax_components": _e("Rincian utang pajak di CALK dijumlahkan dan dibandingkan dengan total di CALK",
                               "Tax-payable breakdown in the notes added up and compared with the notes total", "r1 5.5"),
    "check.tax_face": _e("Total utang pajak di CALK dibandingkan dengan utang pajak di laporan posisi keuangan",
                         "Notes total compared with taxes payable in the statement of financial position", "r1 5.6"),
    "check.alloc_ppe": _e("Beban penyusutan aset tetap (tabel alokasi) dibandingkan dengan beban tahun berjalan di tabel "
                          "mutasi",
                          "PPE depreciation (allocation table) compared with the charge for the year in the movement "
                          "schedule", "r1 5.7"),
    "check.alloc_rou": _e("Beban penyusutan aset hak-guna (tabel alokasi) dibandingkan dengan beban tahun berjalan di "
                          "tabel mutasi",
                          "Right of use depreciation (allocation table) compared with the charge for the year in the "
                          "movement schedule", "r1 5.8"),
    "check.alloc_intang": _e("Beban amortisasi aset takberwujud (tabel alokasi) dibandingkan dengan beban tahun berjalan "
                             "di tabel mutasi",
                             "Intangible-asset amortisation (allocation table) compared with the charge for the year in "
                             "the movement schedule", "Gail 28 Okt impl"),
    "check.cash": _e("Kas akhir tahun di laporan arus kas dibandingkan dengan kas dan setara kas di laporan posisi "
                     "keuangan (kedua tahun)",
                     "Closing cash in the statement of cash flows compared with cash and cash equivalents in the "
                     "statement of financial position (both years)", "r1 5.9"),
    "check.detail_eq": _e("{a} vs {b} + {c}", "{a} vs {b} + {c}", "Gail 28 Okt impl"),
    "check.detail_gp": _e("{a} − {b} vs {c}", "{a} − {b} vs {c}", "Gail 28 Okt impl"),
    "check.detail_vs": _e("{a} vs {b}", "{a} vs {b}", "Gail 28 Okt impl"),
    "check.detail_page": _e("hal. {p}", "p. {p}", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- flags (r0 §6, r1 C5)
    "flag.cl_gt_tl": _e("Liabilitas jangka pendek melebihi total liabilitas", "Current liabilities exceed total liabilities",
                        "r0 6.1"),
    "flag.amort_gt_da": _e("Amortisasi melebihi total penyusutan dan amortisasi",
                           "Amortisation exceeds total depreciation and amortisation", "r0 6.2"),
    "flag.nonppe_neg": _e("Penyusutan non-aset tetap bernilai negatif", "Non-PPE depreciation is negative", "r0 6.3"),
    "flag.nonppe_gt": _e("Penyusutan non-aset tetap melebihi total penyusutan dan amortisasi dikurangi amortisasi",
                         "Non-PPE depreciation exceeds total depreciation and amortisation less amortisation", "r0 6.3"),
    "flag.ca_ppe_gt_ta": _e("Aset lancar ditambah aset tetap melebihi total aset", "Current assets plus PPE exceed total assets",
                            "r0 6.4"),
    "flag.negative": _e("Nilai negatif terdeteksi pada {items}; periksa tanda dan penyajiannya di laporan",
                        "Negative value found for {items}; check the sign and presentation in the report", "r1 6.5"),
    "flag.negative_gp": _e("Laba bruto negatif; periksa tanda dan penyajiannya di laporan",
                           "Negative gross profit; check the sign and presentation in the report", "Gail 28 Okt impl"),
    "flag.yoy": _e("Perubahan tahun-ke-tahun {x} melewati batas pemeriksaan ±{thr}; periksa angka, satuan dan kolom tahun",
                   "Year-on-year change of {x} exceeds the ±{thr} review threshold; check the figures, units and year "
                   "columns", "r1 6.6"),
    "flag.nonppe_partial": _e("Penyusutan dan amortisasi selain aset tetap sebagian tidak diungkapkan",
                              "Non-PPE depreciation and amortisation partly not disclosed", "Gail 28 Okt impl", "Q6"),
    "flag.amort_undisclosed": _e("Ada aset takberwujud, tetapi amortisasinya tidak diungkapkan",
                                 "Intangible assets exist, but their amortisation is not disclosed", "r0 6.7", "G-22"),
    "flag.rou_dep_missing": _e("Ada aset hak-guna, tetapi penyusutannya tidak diungkapkan; DEPI hanya memakai penyusutan "
                               "aset tetap milik",
                               "Right of use assets exist, but their depreciation is not disclosed; DEPI uses owned PPE "
                               "depreciation only", "r0 6.8", "G-23"),
    "flag.transition73": _e("Tahun pertama penerapan {std} (sewa){pg}; kolom tahun lalu tidak disajikan kembali, sehingga "
                            "dasar kedua kolom berbeda. Skor tidak berubah; perbandingan antar-tahun dibaca dengan "
                            "hati-hati",
                            "First year of {std} (leases){pg}; the prior-year column was not restated, so the two "
                            "columns are on different bases. The score is unchanged; read year-on-year comparisons with "
                            "care", "r1 6.15", "D-08", "M-08"),
    "flag.transition_other": _e("Standar yang pertama kali diterapkan di tahun berjalan: {listed}. Piutang (DSRI) dan "
                                "pendapatan (SGI, GMI) tahun lalu bisa disusun dengan standar lama. Skor tidak berubah",
                                "Standards first applied this year: {listed}. Prior-year receivables (DSRI) and revenue "
                                "(SGI, GMI) may follow the previous standards. The score is unchanged", "r1 6.16",
                                "M-08"),
    "flag.std_page": _e("{std} (hal. {p})", "{std} (p. {p})", "r1 6.16"),
    "flag.page": _e(" (hal. {p})", " (p. {p})", "r1 6.15"),
    "flag.comparative": _e("Kolom tahun lalu berlabel \"{word}\"{pg}: lihat pengungkapannya di CALK ({psak208}). Skor tidak "
                           "berubah",
                           "The prior-year column is labelled \"{word}\"{pg}: see the disclosure in the notes ({psak208}). "
                           "The score is unchanged", "r1 6.17", "M-08"),
    "label.RESTATED": _e("disajikan kembali", "restated", "r1 6.17"),
    "label.RECLASSIFIED": _e("direklasifikasi", "reclassified", "Gail 28 Okt impl"),
    "label.RESTATED_AND_RECLASSIFIED": _e("disajikan kembali dan direklasifikasi", "restated and reclassified", "Gail 28 Okt impl"),
    "flag.unit": _e("Angka yang dibaca: dengan satuan \"{unit}\", total aset menjadi {x}, di luar rentang pemeriksaan "
                    "kewajaran; periksa satuan dan skala di PDF",
                    "Figures as read: with the unit \"{unit}\", total assets would be {x}, outside the plausibility "
                    "range; check the unit and scale in the PDF", "r1 6.9", "M-12"),
    "flag.part_gt_total": _e("Angka yang dibaca: {part} melebihi {total}; kemungkinan salah baca, periksa di PDF",
                             "Figures as read: {part} exceeds {total}; possibly misread, check in the PDF", "r1 6.10",
                             "M-12"),
    "flag.sga_gt_rev": _e("Angka yang dibaca: beban penjualan dan umum melebihi pendapatan; bisa sah, periksa di PDF",
                          "Figures as read: selling and general expenses exceed revenue; may be legitimate, check in "
                          "the PDF", "r1 6.10b", "M-12"),
    "flag.jump": _e("Angka yang dibaca: nilai satu tahun ≥{r}× tahun lainnya. Bisa sah (mis. akuisisi), bisa salah digit "
                    "atau satuan; periksa di PDF",
                    "Figures as read: one year's value is {r}× the other or more. May be legitimate (e.g. an acquisition) "
                    "or a misread digit or unit; check in the PDF", "r1 6.11", "M-12"),
    "flag.cash_diff": _e("Angka yang dibaca: kas akhir tahun di laporan arus kas berbeda dengan kas di laporan posisi "
                         "keuangan. Ini bisa wajar (misalnya ada cerukan bank); mohon dicek",
                         "Figures as read: closing cash in the statement of cash flows differs from cash in the "
                         "statement of financial position. This can be legitimate (e.g. bank overdrafts); please check",
                         "Gail 28 Okt impl (r0 6.12 + awalan M-12)", "M-12"),
    "flag.cash_swapped": _e("Angka yang dibaca: kolom tahun kemungkinan tertukar (kas di laporan posisi keuangan sama "
                            "dengan kas akhir tahun di arus kas untuk tahun yang lain). Periksa di PDF",
                            "Figures as read: the year columns may be swapped (balance-sheet cash equals the other "
                            "year's closing cash in the statement of cash flows). Check in the PDF", "r1 6.13", "M-12"),
    "flag.year_missing": _e("Angka yang dibaca: label tahun di judul kolom tidak terbaca pada {stmts}, sehingga kolom "
                            "tahun berjalan dan pembanding tidak dapat dipastikan. Skor ditahan; periksa di PDF",
                            "Figures as read: the year labels in the column headings could not be read in {stmts}, so "
                            "the current and comparative columns cannot be confirmed. The score is withheld; check in "
                            "the PDF", "new", "P0-2"),
    "flag.year_mismatch": _e("Angka yang dibaca: tahun di judul kolom berbeda antar laporan ({list}). Skor ditahan; "
                             "periksa di PDF",
                             "Figures as read: the year in the column headings differs between statements ({list}). The "
                             "score is withheld; check in the PDF", "new", "P0-2"),
    "flag.year_item": _e("{stmt} {y}, hal. {p}", "{stmt} {y}, p. {p}", "new"),
    "check.year_labels": _e("Label tahun di judul kolom sama di ketiga laporan utama: {list}",
                            "The year labels in the column headings agree across the primary statements: {list}",
                            "new", "P0-2"),
    "issue.financial_institution": _e(
        "Laporan ini memuat pos khas bank, asuransi atau lembaga pembiayaan ({items}). Model Beneish tidak berlaku "
        "untuk lembaga keuangan, sehingga M-score tidak dihitung.",
        "This report contains line items typical of a bank, insurer or finance company ({items}). The Beneish model "
        "does not apply to financial institutions, so the M-score is not calculated.", "new"),
    "flag.cash_unavailable": _e("Saldo kas akhir tahun di laporan arus kas tidak ditemukan, sehingga pemeriksaan kolom "
                                "tertukar tidak dapat dilakukan",
                                "Closing cash in the statement of cash flows not found; the swapped-column check could "
                                "not be run", "r0 6.14"),

    # decision errors (pipeline.DecisionError)
    "err.np_notes": _e("pilih catatan yang Anda periksa untuk 'Tidak ada'", "select the notes you examined for 'None'",
                       "Gail 28 Okt impl", "M-06"),
    "err.np_amount": _e("'Ada, seluruhnya diungkapkan' hanya bisa dipilih bila jumlahnya terbaca dari CALK",
                        "'Present, fully disclosed' can be chosen only when the amount was read from the notes", "Gail 28 Okt impl",
                        "M-14"),
    "err.am_read": _e("amortisasi sudah terbaca dari laporan; pilihan status tidak berlaku",
                      "amortisation was read from the report; the status choice does not apply", "Gail 28 Okt impl", "M-15"),
    "err.am_notes": _e("pilih atau tulis catatan/halaman yang Anda periksa",
                       "select or type the notes/pages you examined", "r1 9.14", "M-15"),

    # ---------------------------------------------------------------- app design (Gail 28 Okt 11.01: design approved)
    # ID wording as on the approved canvas "WARS App Design"; EN versions written by Claude to the same rules.
    "ui.tagline": _e("Beneish M-score untuk laporan keuangan tahunan emiten BEI",
                     "Beneish M-score for annual financial statements of IDX-listed companies", "Gail 28 Okt desain"),
    "ui.guest": _e("Masuk sebagai Tamu", "Continue as Guest", "Gail 28 Okt desain"),
    "ui.guest_label": _e("Tamu", "Guest", "Gail 28 Okt desain"),
    "ui.logout": _e("Keluar", "Sign out", "Gail 28 Okt desain"),
    "ui.step.upload": _e("Unggah", "Upload", "Gail 28 Okt desain"),
    "ui.step.read": _e("Dibaca", "Reading", "Gail 28 Okt desain"),
    "ui.step.result": _e("Hasil", "Result", "Gail 28 Okt desain"),
    "ui.up.title": _e("Unggah laporan keuangan", "Upload the financial statements", "Gail 28 Okt desain"),
    "ui.up.sub": _e("PDF digital laporan keuangan tahunan. Satu file, maksimal 50 MB.",
                    "Digital PDF of the annual financial statements. One file, up to 50 MB.", "Gail 28 Okt desain"),
    "ui.up.drop": _e("Tarik PDF ke sini atau pilih berkas", "Drag the PDF here or choose a file", "Gail 28 Okt desain"),
    "ui.up.scan": _e("PDF hasil pindai belum didukung", "Scanned PDFs are not supported yet", "Gail 28 Okt desain"),
    "ui.up.ready": _e("{size} · siap dibaca", "{size} · ready to read", "Gail 28 Okt desain"),
    "ui.up.replace": _e("Ganti", "Replace", "Gail 28 Okt desain"),
    "ui.up.start": _e("Mulai analisis", "Start analysis", "Gail 28 Okt desain"),
    "ui.up.bank": _e("Laporan keuangan bank, asuransi, dan lembaga pembiayaan belum dapat digunakan pada sistem ini.",
                     "Financial statements of banks, insurers and finance companies cannot be used in this system yet.",
                     "Gail 28 Okt desain"),
    "ui.proc.title": _e("Membaca laporan", "Reading the report", "Gail 28 Okt desain"),
    "ui.proc.sub": _e("{name} · {pages} halaman. Biasanya selesai dalam 10–30 detik.",
                      "{name} · {pages} pages. This usually takes 10–30 seconds.", "Gail 28 Okt desain"),
    "ui.proc.fs": _e("Laporan utama ditemukan", "Primary statements found", "Gail 28 Okt desain"),
    "ui.proc.fs_detail": _e("Posisi keuangan hal. {a} · Laba rugi hal. {b} · Arus kas hal. {c} · tahun {t} dan {t1}",
                            "Financial position p. {a} · Profit or loss p. {b} · Cash flows p. {c} · years {t} and {t1}",
                            "Gail 28 Okt desain"),
    "ui.proc.notes": _e("Catatan atas laporan keuangan dibaca", "Notes to the financial statements read",
                        "Gail 28 Okt desain"),
    "ui.proc.notes_detail": _e("Utang pajak, penyusutan, aset hak-guna, amortisasi",
                               "Taxes payable, depreciation, right of use assets, amortisation", "Gail 28 Okt desain"),
    "ui.proc.checks": _e("Pemeriksaan silang", "Cross-checks", "Gail 28 Okt desain"),
    "ui.proc.checks_detail": _e("{ok} lolos · {err} gagal", "{ok} passed · {err} failed", "Gail 28 Okt desain"),
    "ui.proc.calc": _e("Menghitung 8 indeks Beneish…", "Calculating the 8 Beneish indices…", "Gail 28 Okt desain"),
    "ui.proc.summary": _e("Ringkasan pembacaan", "Reading summary", "new"),
    "ui.res.another": _e("Analisis laporan lain", "Analyse another report", "Gail 28 Okt desain"),
    "ui.res.meta": _e("Tahun buku {t} vs {t1} · {stype} · {unit} · {pages} halaman",
                      "Financial year {t} vs {t1} · {stype} · {unit} · {pages} pages", "Gail 28 Okt desain"),
    "unit.USD.Units": _e("Dolar AS", "US dollars", "Gail 28 Okt P4"),
    "unit.USD.Thousands": _e("ribuan Dolar AS", "thousands of US dollars", "Gail 28 Okt P4"),
    "unit.USD.Millions": _e("jutaan Dolar AS", "millions of US dollars", "Gail 28 Okt P4"),
    "unit.USD.Billions": _e("miliaran Dolar AS", "billions of US dollars", "Gail 28 Okt P4"),
    "check.section_ca": _e("Baris aset lancar dijumlahkan sama dengan jumlah aset lancar",
                           "Current asset lines add up to total current assets", "new"),
    "check.section_cl": _e("Baris liabilitas jangka pendek dijumlahkan sama dengan jumlah liabilitas jangka pendek",
                           "Current liability lines add up to total current liabilities", "new"),
    "check.ta_tle": _e("Total aset sama dengan total liabilitas dan ekuitas",
                       "Total assets agree with total liabilities and equity", "new"),
    "check.tl_parts": _e("Liabilitas jangka pendek ditambah liabilitas jangka panjang sama dengan total liabilitas",
                         "Current plus non-current liabilities agree with total liabilities", "new"),
    "check.net_income": _e("Laba sebelum pajak dan baris di bawahnya sama dengan laba tahun berjalan",
                           "Profit before tax and the lines below it agree with profit for the year", "new"),
    "check.cfo": _e("Arus kas operasi, investasi dan pendanaan dijumlahkan sama dengan kenaikan (penurunan) kas",
                    "Operating, investing and financing cash flows add up to the net change in cash", "new"),
    "check.cash_cf": _e("Kas dan setara kas sama dengan saldo di laporan arus kas",
                        "Cash and cash equivalents agree with the balance in the statement of cash flows", "new"),
    "check.sga_total": _e("Beban penjualan dan beban umum dijumlahkan sama dengan total beban usaha yang tercetak",
                          "Selling and general expenses add up to the printed total operating expenses", "new"),
    "check.in_notes": _e("{item}: angka yang sama ditemukan lagi di catatan (hal. {p})",
                         "{item}: the same figures were found again in the notes (p. {p})", "new"),
    "note.no_crosscheck": _e("Angka ini belum bisa dicocokkan dengan tempat kedua di laporan; periksa di PDF",
                             "This figure could not be matched to a second place in the report; check in the PDF", "new"),
    "issue.sga_other": _e("Total beban usaha juga memuat pos lain yang tidak dihitung sebagai beban penjualan dan umum: "
                          "{lines}. Periksa di PDF",
                          "Total operating expenses also holds other items not counted as selling and general expenses: "
                          "{lines}. Check in the PDF", "new"),
    "flag.sga_total": _e("Angka yang dibaca: beban penjualan dan beban umum ({a}) tidak sama dengan total beban usaha yang "
                         "tercetak, dan selisihnya bukan pos lain yang berdiri sendiri. Kemungkinan ada baris yang terlewat; "
                         "periksa di PDF",
                         "Figures as read: selling and general expenses ({a}) do not agree with the printed total operating "
                         "expenses, and the difference is not another item on its own line. A line may have been missed; "
                         "check in the PDF", "new"),
    "check.section_nca": _e("Baris aset tidak lancar dijumlahkan sama dengan jumlah aset tidak lancar",
                            "Non-current asset lines add up to total non-current assets", "new"),
    "issue.section_sum": _e("{sec}: tidak cocok untuk kolom {col} ({a} terbaca, {b} tercetak, hal. {p}). Ada baris yang "
                            "terlewat, terbaca ganda atau berupa subjumlah; periksa di PDF",
                            "{sec}: does not agree for column {col} ({a} read, {b} printed, p. {p}). A line was missed, "
                            "read twice or is a subtotal; check in the PDF", "new"),
    "issue.ambiguous": _e("Lebih dari satu baris dengan angka berbeda cocok untuk {item}: {lines}. Baris pertama dipakai "
                          "dan ditandai untuk diperiksa",
                          "More than one line with different figures matches {item}: {lines}. The first line is used "
                          "and marked for review", "new"),
    "note.tax_no_face_match": _e("Tabel pajak dengan PPh Pasal 25/29 ditemukan, tetapi jumlahnya tidak cocok dengan utang "
                                 "pajak di laporan posisi keuangan; angkanya tidak dipakai",
                                 "A tax table with Articles 25/29 was found, but its total does not agree with taxes "
                                 "payable on the statement of financial position; its figures are not used", "new", "D-03"),
    "note.tax_zero_evidence": _e("Tabel utang pajak di catatan (hal. {p}) cocok dengan laporan posisi keuangan dan tidak "
                                 "memuat PPh badan Pasal 25/29 (misalnya pajak final atau lebih bayar); utang PPh badan "
                                 "= 0. Periksa di PDF",
                                 "The taxes-payable table in the notes (p. {p}) agrees with the statement of financial "
                                 "position and holds no corporate income tax (Articles 25/29), e.g. final tax or an "
                                 "overpayment; corporate income tax payable = 0. Check in the PDF", "new", "D-03"),
    "flag.ppe_note": _e("Angka yang dibaca: aset tetap di laporan posisi keuangan tidak ditemukan sebagai nilai tercatat "
                        "di catatan aset tetap (yang terbaca di catatan: {seen}). Kemungkinan baris yang salah terambil; "
                        "periksa di PDF",
                        "Figures as read: the fixed assets on the statement of financial position were not found as a "
                        "carrying amount in the fixed-asset note (read in the note: {seen}). The wrong line may have been "
                        "taken; check in the PDF", "new"),
    "check.ppe_note": _e("Aset tetap di laporan posisi keuangan sama dengan nilai tercatat di catatan aset tetap (hal. {p})",
                         "Fixed assets on the statement of financial position agree with the carrying amount in the "
                         "fixed-asset note (p. {p})", "new"),
    "note.cogs_direct": _e("Beban langsung dipakai sebagai beban pokok penjualan: laporan laba rugi menyajikan laba bruto "
                           "sesudahnya dan pendapatan dikurangi beban langsung sama dengan laba bruto di kedua tahun",
                           "Direct costs used as cost of sales: the statement of profit or loss shows gross profit "
                           "after them, and revenue less direct costs equals gross profit in both years", "Gail 28 Okt P5"),
    "note.sga_opex": _e("Beban usaha disajikan satu baris (tanpa pemisahan beban penjualan dan beban umum); dipakai sebagai "
                        "beban penjualan dan umum. Periksa rinciannya di catatan, karena bisa mencakup pos lain",
                        "Operating expenses are shown on one line (no split into selling and general expenses); used as "
                        "selling, general and administrative expenses. Check the breakdown in the notes, as it may "
                        "include other items", "Gail 28 Okt P5"),
    "note.ar_construction": _e("Piutang retensi tidak dihitung sebagai piutang usaha",
                               "Retention receivables are not counted as trade receivables", "Gail 28 Okt P7"),
    "issue.retention": _e("Piutang retensi disajikan terpisah (hal. {p}); tidak dihitung sebagai piutang usaha karena "
                          "haknya belum tanpa syarat. Periksa catatannya",
                          "Retention receivables are presented separately (p. {p}); not counted as trade receivables "
                          "because the right is not yet unconditional. Check the note", "Gail 28 Okt P7"),
    "note.debt_nil_g24": _e("Nihil karena tidak ada baris utang berbunga di bagian ini, neraca seimbang di kedua tahun, "
                            "dan tidak ada catatan pinjaman jangka panjang, obligasi atau sewa; periksa di PDF",
                            "Nil because the section has no interest-bearing line, the balance sheet balances in both "
                            "years, and no note covers long-term borrowings, bonds or leases; check in the PDF",
                            "new", "G-24"),
    "note.amort_sentence": _e("Amortisasi aset takberwujud diambil dari kalimat di catatan (tidak ada tabel); periksa angkanya "
                              "di halaman tersebut",
                              "Intangible amortisation taken from a sentence in the notes (no table); check the figures on "
                              "that page", "new"),
    "note.ppe_dep_sentence": _e("Penyusutan aset tetap milik diambil dari kalimat di catatan aset tetap (tidak ada tabel "
                                "alokasi); periksa angkanya di halaman tersebut",
                                "Owned-PPE depreciation taken from a sentence in the fixed-asset note (no allocation "
                                "table); check the figures on that page", "new"),
    "np.source_fv": _e("hal. {p}: properti investasi diukur dengan model nilai wajar, sehingga tidak disusutkan: \"{text}\"",
                       "p. {p}: investment property is measured under the fair value model, so it is not depreciated: "
                       "\"{text}\"", "new"),
    "v.held_invprop": _e(
        "Properti investasi ada di laporan posisi keuangan (hal. {p}), tetapi penyusutannya tidak terbaca dari catatan "
        "atas laporan keuangan untuk {years}. M-score ditahan, karena menganggapnya 0 dapat membuat skor salah.",
        "Investment property is on the statement of financial position (p. {p}), but its depreciation could not be "
        "read from the notes for {years}. The M-score is withheld, because taking it as 0 could make the score "
        "wrong.", "new"),
    "issue.number_format": _e(
        "Format angka tidak dapat dipastikan: laporan utama memakai titik dan koma sebagai pemisah ribuan secara "
        "bercampur. Angka tidak dibaca, karena salah pemisah mengubah nilai seribu kali lipat.",
        "The number format could not be determined: the primary statements mix dots and commas as thousands "
        "separators. No figure was read, because a wrong separator changes amounts a thousandfold.", "new"),
    "ui.res.meta_file": _e("{name} · {pages} halaman", "{name} · {pages} pages", "new"),
    "ui.res.stype.Consolidated": _e("Laporan keuangan konsolidasian", "Consolidated financial statements",
                                    "Gail 28 Okt 11.01"),
    "ui.res.stype.unknown": _e("Laporan keuangan (jenis tidak terbaca)", "Financial statements (type not read)", "new"),
    "ui.res.issuer_unknown": _e("Emiten tidak teridentifikasi", "Issuer not identified", "new"),
    "ui.res.issuer_note": _e("Nama dari data master emiten (buku kerja v0.6)", "Name from the issuer master list (workbook v0.6)",
                             "new"),
    "ui.res.chip_below": _e("Tidak melewati batas {thr}*", "Does not cross the {thr} threshold*", "Gail 28 Okt 11.01"),
    "ui.res.chip_note": _e("*Bukan jaminan laporan bebas salah saji.",
                           "*This does not guarantee the statements are free of misstatement.", "Gail 28 Okt 11.01"),
    "ui.res.chip_above": _e("Melewati batas {thr}", "Crosses the {thr} threshold", "Gail 28 Okt desain"),
    "ui.res.scale_neutral": _e("Netral {n}", "Neutral {n}", "Gail 28 Okt desain"),
    "ui.res.scale_thr": _e("Batas {thr}", "Threshold {thr}", "Gail 28 Okt desain"),
    "ui.res.provisional": _e("Hasil sementara.", "Provisional result.", "Gail 28 Okt desain"),
    "ui.res.provisional_detail": _e("{n} angka perlu dicocokkan dengan PDF sumber. Daftar periksanya ada di laporan PDF.",
                                    "{n} figures need to be checked against the source PDF. The checklist is in the PDF "
                                    "report.", "Gail 28 Okt desain"),
    "ui.res.assumed": _e("Termasuk {n} asumsi untuk angka yang tidak ditemukan; rinciannya di daftar periksa.",
                         "This includes {n} assumptions for figures that were not found; details in the checklist.",
                         "new"),
    "ui.idx.title": _e("Kedelapan indeks", "The eight indices", "Gail 28 Okt desain"),
    "ui.idx.col.index": _e("INDEKS", "INDEX", "Gail 28 Okt desain"),
    "ui.idx.col.name": _e("ARTI", "MEANING", "Gail 28 Okt desain"),
    "ui.idx.col.value": _e("NILAI", "VALUE", "Gail 28 Okt desain"),
    "ui.idx.col.push": _e("DORONGAN", "PUSH", "Gail 28 Okt desain"),
    "ui.idx.minor": _e("DEPI, SGAI dan LVGI tidak signifikan dalam model Beneish (1999); tidak dibahas sebagai temuan.",
                       "DEPI, SGAI and LVGI are not significant in the Beneish (1999) model; they are not discussed as "
                       "findings.", "Gail 28 Okt desain"),
    "ui.dl.title": _e("Unduh hasil", "Download the results", "Gail 28 Okt desain"),
    "ui.dl.pdf": _e("Laporan PDF", "PDF report", "Gail 28 Okt desain"),
    "ui.dl.pdf_sub": _e("Rincian temuan, sumber halaman, daftar periksa angka, metodologi",
                        "Findings in detail, source pages, checklist of figures, methodology", "Gail 28 Okt desain"),
    "ui.dl.xlsx": _e("Tabel angka (Excel)", "Table of figures (Excel)", "Gail 28 Okt desain"),
    "ui.dl.xlsx_sub": _e("Semua angka {t} dan {t1} dengan halaman dan baris sumbernya",
                         "All {t} and {t1} figures with their source pages and lines", "Gail 28 Okt desain"),
    "ui.dl.lang": _e("Pilih bahasa laporan dengan tombol ID / EN di atas sebelum mengunduh.",
                     "Choose the report language with the ID / EN switch above before downloading.", "Gail 28 Okt desain"),
    "ui.method": _e("Model dikembangkan berdasarkan Beneish (1999). Skor rendah tidak berarti bebas salah saji. Model: "
                    "Beneish (1999), 8 variabel; tahun berjalan dan pembanding diambil dari laporan yang sama.",
                    "The model is based on Beneish (1999). A low score does not mean the statements are free of "
                    "misstatement. Model: Beneish (1999), 8 variables; the current year and the comparatives come from "
                    "the same report.", "Gail 28 Okt 10.32"),
    "ui.not_traced": _e("Sistem tidak dapat menelusuri nilai {items}; M-score tidak dapat ditampilkan.",
                        "The system could not trace the value of {items}; the M-score cannot be shown.",
                        "Gail 28 Okt 10.32 (dirapikan Claude)"),
    "ui.unreadable_title": _e("Laporan tidak dapat dibaca", "The report could not be read", "new"),
    "ui.read_details": _e("Detail pembacaan", "Reading details", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- provisional assumptions (Gail 28 Okt 10.41)
    "status.ASSUMED": _e("Asumsi hasil sementara", "Provisional assumption", "new"),
    "note.assumed_am": _e("Aset takberwujud tidak ditemukan; amortisasi dianggap 0 untuk hasil sementara. Periksa "
                          "di catatan atas laporan keuangan apakah memang tidak ada.",
                          "No intangible assets were found; amortisation is taken as 0 for the provisional result. "
                          "Check in the notes to the financial statements whether there are none.", "new"),
    "note.assumed_np": _e("Penyusutan dan amortisasi aset selain aset tetap: dipakai jumlah yang terbaca ({source}); "
                          "belum dapat dipastikan lengkap.",
                          "Depreciation and amortisation of assets other than PPE: the amount read is used ({source}); "
                          "it cannot yet be confirmed as complete.", "new"),
    "note.assumed_np_zero": _e("Penyusutan dan amortisasi aset selain aset tetap tidak ditemukan; dianggap 0 untuk hasil "
                               "sementara. Periksa di catatan atas laporan keuangan apakah memang tidak ada.",
                               "Depreciation and amortisation of assets other than PPE were not found; taken as 0 for "
                               "the provisional result. Check in the notes to the financial statements whether there "
                               "are none.", "new"),

    # ---------------------------------------------------------------- PDF report and Excel (new; awaiting review)
    "rep.title": _e("Laporan Penyaringan Red Flag", "Red Flag Screening Report", "new"),
    "rep.page": _e("Halaman {n} dari {m}", "Page {n} of {m}", "new"),
    "rep.generated": _e("Dibuat {d}", "Generated {d}", "new"),
    "rep.version": _e("Bahasa Indonesia", "English", "new"),
    "rep.footer_disclaimer": _e(
        "This is a red-flag screen using the Beneish M-score, not evidence of fraud. The flagged accounts need closer "
        "examination. In case of any discrepancy, the Indonesian version prevails.",
        "This is a red-flag screen using the Beneish M-score, not evidence of fraud. The flagged accounts need closer "
        "examination. In case of any discrepancy, the Indonesian version prevails.", "Gail 23 Okt R-06 R-07 R-11"),
    "rep.s1": _e("Ikhtisar", "Overview", "r0 report"),
    "rep.s2": _e("Rincian skor", "Score breakdown", "r0 report"),
    "rep.s3": _e("Temuan", "Findings", "r0 report"),
    "rep.s4": _e("Daftar periksa", "Checklist", "new"),
    "rep.s5": _e("Lampiran A · Angka yang dibaca", "Appendix A · Figures read", "new"),
    "rep.s6": _e("Lampiran B · Pemeriksaan silang dan catatan pembacaan", "Appendix B · Cross-checks and reading notes",
                 "new"),
    "rep.s7": _e("Metodologi dan batasan", "Methodology and limitations", "Gail 28 Okt A3"),
    "rep.f.entity": _e("ENTITAS", "ENTITY", "r0 report"),
    "rep.f.ticker": _e("KODE SAHAM", "TICKER", "r0 report"),
    "rep.f.period": _e("PERIODE DIBANDINGKAN", "PERIODS COMPARED", "r0 report"),
    "rep.f.basis": _e("DASAR", "BASIS", "r0 report"),
    "rep.f.unit": _e("SATUAN", "UNIT", "new"),
    "rep.f.source": _e("SUMBER", "SOURCE", "r0 report"),
    "rep.period": _e("{t} (t) vs {t1} (t−1)", "{t} (t) vs {t1} (t−1)", "new"),
    "rep.source": _e("{name} · {pages} halaman · SHA-256 {sha}", "{name} · {pages} pages · SHA-256 {sha}", "new"),
    "rep.score_label": _e("BENEISH M-SCORE · MODEL 8 VARIABEL", "BENEISH M-SCORE · 8-VARIABLE MODEL", "r0 report"),
    "rep.box.figures": _e("ANGKA", "FIGURES", "new"),
    "rep.box.figures_v": _e("{a} dari {b} angka terbaca dan tercocokkan", "{a} of {b} figures read and reconciled",
                            "new"),
    "rep.box.figures_d": _e("{n} perlu dicocokkan; lihat daftar periksa.", "{n} to be checked; see the checklist.", "new"),
    "rep.box.rules": _e("ATURAN", "RULES", "new"),
    "rep.box.rules_v": _e("Workbook v0.6", "Workbook v0.6", "Gail 23 Okt R-15"),
    "rep.box.rules_d": _e("Rumus dan aturan pengisian sesuai buku kerja WARS Track B v0.6.",
                          "Formulas and entry rules as in the WARS Track B v0.6 workbook.", "new"),
    "rep.box.user": _e("KONFIRMASI PENGGUNA", "USER CONFIRMATION", "Gail 23 Okt R-15"),
    "rep.box.user_v": _e("Belum dilakukan", "Not done yet", "new"),
    "rep.box.user_d": _e("Isi daftar periksa. Konfirmasi pengguna bukan verifikasi independen.",
                         "Complete the checklist. User confirmation is not independent verification.", "Gail 23 Okt R-15"),
    "rep.summary": _e("Ringkasan", "Summary", "r0 report"),
    "rep.breakdown_intro": _e(
        "Setiap indeks membandingkan {t} dengan {t1}. Dorongan menunjukkan seberapa jauh suatu indeks menggeser skor "
        "dari perusahaan netral ({n}). Jumlah delapan dorongan sama dengan selisih antara nilai netral dan skor akhir.",
        "Each index compares {t} with {t1}. The push shows how far an index moves the score away from a neutral "
        "company ({n}). The eight pushes add up to the difference between the neutral value and the final score.",
        "new"),
    "rep.col.coef": _e("KOEF.", "COEF.", "r0 report"),
    "rep.sum_line": _e("Netral {n} + dorongan bersih {p} = M-score {m} · batas {thr}",
                       "Neutral {n} + net push {p} = M-score {m} · threshold {thr}", "new"),
    "rep.formula": _e(
        "Indeks = rasio tahun berjalan ÷ rasio tahun pembanding; TATA = akrual total ÷ total aset tahun berjalan. "
        "Dorongan = koefisien × (indeks − nilai netral); nilai netral 1 untuk indeks dan 0 untuk TATA. "
        "M = {const} + Σ koefisien × indeks.",
        "Index = current-year ratio ÷ comparative-year ratio; TATA = total accruals ÷ current-year total assets. "
        "Push = coefficient × (index − neutral value); the neutral value is 1 for the indices and 0 for TATA. "
        "M = {const} + Σ coefficient × index.", "new"),
    "rep.no_findings": _e("Tidak ada rasio yang memenuhi kriteria temuan (DSRI, GMI, AQI, SGI atau TATA dengan dorongan "
                          "di atas 0,005).",
                          "No ratio meets the criteria for a finding (DSRI, GMI, AQI, SGI or TATA with a push above "
                          "0.005).", "B r1 §3"),
    "rep.no_score": _e("M-score tidak dihitung, sehingga tidak ada temuan.",
                       "The M-score was not calculated, so there are no findings.", "new"),
    "rep.finding": _e("Temuan {n} · {idx}", "Finding {n} · {idx}", "r0 report"),
    "rep.push_tag": _e("DORONGAN {p}", "PUSH {p}", "Gail 23 Okt R-13"),
    "rep.a": _e("A · ANGKA", "A · FIGURES", "r0 report"),
    "rep.c": _e("C · KEMUNGKINAN PENJELASAN", "C · POSSIBLE EXPLANATIONS", "B r1 §4"),
    "rep.d": _e("D · AREA UNTUK PEMERIKSAAN LEBIH LANJUT", "D · AREAS FOR FURTHER EXAMINATION", "r0 report"),
    "rep.why": _e("Tentang indeks ini", "About this index", "r1 7.14"),
    "rep.check_intro": _e(
        "Buka halaman PDF yang disebut dan cocokkan tiap angka. Beri tanda pada kolom Sesuai atau Tidak sesuai. Satu "
        "jawaban Tidak sesuai berarti M-score ini tidak dapat dipakai sampai angka tersebut diperbaiki. Konfirmasi "
        "pengguna bukan verifikasi independen.",
        "Open the PDF page shown and check each figure. Tick Matches or Does not match. One Does not match means this "
        "M-score cannot be used until the figure is corrected. User confirmation is not independent verification.",
        "new"),
    "rep.check.none": _e("Tidak ada angka yang perlu dicocokkan.", "No figure needs checking.", "Gail 28 Okt impl"),
    "rep.check.col.no": _e("No", "No", "new"),
    "rep.check.col.item": _e("Pos", "Line item", "Gail 28 Okt impl"),
    "rep.check.col.year": _e("Tahun", "Year", "new"),
    "rep.check.col.value": _e("Nilai", "Value", "Gail 28 Okt impl"),
    "rep.check.col.page": _e("Hal.", "Page", "new"),
    "rep.check.col.why": _e("Yang perlu dicocokkan", "What to check", "new"),
    "rep.check.col.ok": _e("Sesuai", "Matches", "Gail 28 Okt C6 7.18"),
    "rep.check.col.bad": _e("Tidak sesuai", "Does not match", "Gail 28 Okt C6 7.18"),
    "rep.check.assumed": _e("Asumsi untuk hasil sementara", "Assumptions for the provisional result", "new"),
    "rep.check.sign": _e("Diperiksa oleh: ____________________    Tanggal: ____________    Paraf: ________",
                         "Checked by: ____________________    Date: ____________    Initials: ________", "new"),
    "rep.inputs_intro": _e("Angka dalam satuan laporan ({unit}). Baris sumber dikutip dari PDF.",
                           "Figures in the report's unit ({unit}). Source lines are quoted from the PDF.", "new"),
    "rep.checks.passed": _e("Lolos", "Passed", "new"),
    "rep.checks.failed": _e("Gagal", "Failed", "new"),
    "rep.checks.review": _e("Perlu diperiksa", "Needs review", "r1 2.2"),
    "rep.method.p1": _e(
        "Model dikembangkan berdasarkan Beneish (1999). Skor rendah tidak berarti bebas salah saji. Model: Beneish "
        "(1999), 8 variabel; tahun berjalan dan pembanding diambil dari laporan yang sama.",
        "The model is based on Beneish (1999). A low score does not mean the statements are free of misstatement. "
        "Model: Beneish (1999), 8 variables; the current year and the comparatives come from the same report.",
        "Gail 28 Okt 10.32"),
    "rep.method.p2": _e(
        "Batas yang ditampilkan hanya −1,78 (Beneish 1999). Skor di atas batas berarti angka terkait perlu diperiksa "
        "lebih lanjut; skor bukan probabilitas kecurangan.",
        "The only threshold shown is −1.78 (Beneish 1999). A score above it means the related figures warrant closer "
        "examination; the score is not a probability of fraud.", "new"),
    "rep.method.p3": _e(
        "Angka dibaca otomatis dari PDF digital. Setiap angka tercatat dengan halaman dan baris sumbernya. Angka yang "
        "tidak ditemukan tidak diisi; angka yang dianggap 0 untuk hasil sementara tercantum di daftar periksa.",
        "Figures are read automatically from the digital PDF. Each figure is recorded with its source page and line. "
        "Figures that were not found are not filled in; figures taken as 0 for the provisional result are listed in "
        "the checklist.", "new"),
    "rep.method.p4": _e(
        "Laporan ini hasil penyaringan otomatis. Laporan ini bukan opini audit, tidak menggantikan prosedur "
        "pemeriksaan, dan bukan bukti kecurangan atau salah saji.",
        "This report is an automated screen. It is not an audit opinion, does not replace examination procedures, and "
        "is not evidence of fraud or misstatement.", "new"),
    "rep.method.p5": _e("Dibuat oleh Warsini · linkedin.com/in/warsiniak · versi beta",
                        "Made by Warsini · linkedin.com/in/warsiniak · beta version", "Gail 28 Okt B3"),

    "xl.sheet.summary": _e("Ringkasan", "Summary", "new"),
    "xl.sheet.figures": _e("Angka", "Figures", "new"),
    "xl.sheet.indices": _e("Indeks", "Indices", "new"),
    "xl.sheet.checklist": _e("Daftar periksa", "Checklist", "new"),
    "xl.sheet.checks": _e("Pemeriksaan silang", "Cross-checks", "new"),
    "xl.col.answer": _e("Jawaban (Sesuai / Tidak sesuai)", "Answer (Matches / Does not match)", "new"),
    "xl.col.source_label": _e("Pos di laporan", "Line in the report", "new"),
    "xl.col.source_line": _e("Baris sumber (kutipan PDF)", "Source line (PDF quote)", "new"),
    "xl.col.check": _e("Pemeriksaan", "Check", "new"),
    "xl.col.result": _e("Hasil", "Result", "Gail 28 Okt desain"),
    "xl.col.detail": _e("Rincian", "Detail", "new"),
    "xl.k.file": _e("Berkas", "File", "new"),
    "xl.k.generated": _e("Dibuat", "Generated", "new"),
    "xl.k.mscore": _e("M-score", "M-score", "new"),
    "xl.k.status": _e("Status", "Status", "Gail 28 Okt impl"),
}


ENGINE_REASONS = {
    "statement_type / currency / unit_scale not specified (t or t-1)": "reason.basis",
    "missing or non-numeric required input (fiscal year t)": "reason.inputs_t",
    "missing or non-numeric required input (fiscal year t-1)": "reason.inputs_t1",
    "non-PPE D&A not assessed (fiscal year t)": "reason.nonppe_t",
    "non-PPE D&A not assessed (fiscal year t-1)": "reason.nonppe_t1",
    "PPE depreciation check failed (fiscal year t)": "reason.ppedep_t",
    "PPE depreciation check failed (fiscal year t-1)": "reason.ppedep_t1",
    "missing or invalid ticker / fiscal_year": "reason.ticker",
    "invalid or zero denominator": "reason.denominator",
}


def engine_reason(raw: str):
    """The engine keeps the workbook's reason strings; the user reads them from the catalogue."""
    if not raw:
        return Msg("reason.incomplete")
    key = ENGINE_REASONS.get(raw.strip())
    return Msg(key) if key else Msg("reason.other", raw=Raw(raw))
