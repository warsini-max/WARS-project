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
    if lang == "en":
        text = _en_singular(text)
    if codes and e.get("codes"):
        text += " [" + ", ".join(e["codes"]) + "]"
    return text


# English plural after a count of one: "1 items require" -> "1 item requires" (Gail, 5 Nov 2026). Only a lone "1"
# counts ("11 items", "0.1 items" and "2 of 1 items" are left alone, the last as "of 1 item").
_ONE = re.compile(r"(?<![\d.,])\b1 (item|figure|assumption|page|line|year|issue|check)s\b")
_ONE_VERB = re.compile(r"(?<![\d.,])\b(1 (?:item|figure|assumption|issue|check)) (require|need|remain)\b")


def _en_singular(text):
    text = _ONE.sub(r"1 \1", text)
    return _ONE_VERB.sub(r"\1 \2s", text)


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
    "app.title": _e("Window-dressing Accounting Red-Flag Scanner", "Window-dressing Accounting Red-Flag Scanner", "Gail 28 Okt 20.07"),
    "app.subtitle": _e("Beneish M-score (1999) untuk laporan keuangan tahunan emiten BEI",
                       "Beneish M-score (1999) for annual financial statements of IDX-listed companies", "Gail 28 Okt C6 7.1"),
    "app.lang": _e("Bahasa / Language", "Bahasa / Language", "Gail 28 Okt impl"),
    # Disclaimer: professional English in every language version, app, website and PDF (Gail, 4 Nov 2026 09.07)
    "app.disclaimer": _e(
        "WARS is a red-flag detection system; its results do not constitute a conclusion of fraud and require further "
        "review.",
        "WARS is a red-flag detection system; its results do not constitute a conclusion of fraud and require further "
        "review.", "Gail 4 Nov 09.07 (EN di kedua versi)"),
    "app.beta": _e("WARS v0.1 Beta untuk uji coba. Hasil dapat berubah seiring perbaikan pembaca.",
                   "WARS v0.1 Beta for testing. Results may change as the reader is improved.",
                   "Gail 28 Okt A1; label v0.1 Beta Gail 11 Nov 12.37"),
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
    # Part C chosen from the company's figures (wording and limits approved by Gail, 8 Nov 2026 11.38)
    "c.DSRI_denom": _e("Kenaikan rasio ini berasal dari turunnya penjualan, bukan dari bertambahnya piutang "
                       "(piutang tidak bertambah).",
                       "The rise in this ratio comes from lower sales, not from higher receivables (receivables did "
                       "not increase).", "Gail 8 Nov 11.38 (bagian C)"),
    "c.DSRI_both": _e("Kenaikan rasio ini berasal dari dua arah: piutang bertambah sementara penjualan menurun.",
                      "The rise in this ratio comes from two directions: receivables increased while sales decreased.",
                      "Gail 8 Nov 11.38 (bagian C)"),
    "c.DSRI_numer": _e("Kenaikan rasio ini berasal dari piutang yang tumbuh lebih cepat daripada penjualan.",
                       "The rise in this ratio comes from receivables growing faster than sales.",
                       "Gail 8 Nov 11.38 (bagian C)"),
    "c.small_base_DSRI": _e("Piutang tahun lalu sangat kecil (kurang dari {lim} penjualan), sehingga perubahan "
                            "nominal yang kecil sudah menghasilkan indeks yang tinggi. Baca indeks ini bersama "
                            "nominalnya.",
                            "Prior-year receivables were very small (less than {lim} of sales), so a small change in "
                            "amount already produces a high index. Read this index together with the amounts.",
                            "Gail 8 Nov 11.38 (bagian C)"),
    "c.small_base_AQI": _e("Porsi aset tidak lancar selain aset tetap tahun lalu sangat kecil ({aq_t1} dari total "
                           "aset, kurang dari {lim}), sehingga perubahan nominal yang kecil sudah menghasilkan indeks "
                           "yang tinggi. Baca indeks ini bersama nominalnya.",
                           "The prior-year share of non-current assets other than PPE was very small ({aq_t1} of "
                           "total assets, less than {lim}), so a small change in amount already produces a high "
                           "index. Read this index together with the amounts.", "Gail 8 Nov 11.38 (bagian C)"),
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
    "idx.col.push": _e(
                        'Kontribusi vs netral',
                        'Contribution vs neutral',
                        'Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
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
    "np.source_cross": _e(
                           'Hal. {p}: {text}. Angka tahun berjalan juga tercantum dalam catatan properti investasi pada hal. {q}.',
                           'P. {p}: {text}. The current-year figure is also presented in the investment property note on p. {q}.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
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
    "label.property_plant_equipment_net": _e("Aset tetap neto + aset hak-guna", "Net PPE + right of use assets",
                                             "Gail 28 Okt report"),
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
    "stype.Parent-only": _e(
                             'bukan konsolidasian',
                             'not consolidated',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "stype.unknown": _e("jenis laporan tidak diketahui", "statement type unknown", "Gail 28 Okt impl"),
    "stmt.position": _e("Laporan posisi keuangan", "Statement of financial position", "r0 1.1"),
    "stmt.profit_loss": _e("Laporan laba rugi", "Statement of profit or loss", "r0 1.2"),
    "stmt.cash_flow": _e("Laporan arus kas", "Statement of cash flows", "r0 1.3"),
    "where.face": _e("laporan posisi keuangan", "statement of financial position", "r0 1.1"),
    "where.notes": _e("CALK", "notes", "r0 1.4"),

    # ---------------------------------------------------------------- value statuses (r0 §2, r1 C1)
    "status.FOUND": _e("Terbaca dan tercocokkan", "Read and reconciled", "r0 2.1"),
    "status.REVIEW": _e("Perlu diperiksa", "Needs review", "r1 2.2"),
    "status.UNDISCLOSED": _e("Tidak diungkapkan (dihitung 0)", "Not disclosed (counted as 0)", "Gail 28 Okt report"),
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
    "note.rou_absent": _e("Laporan tidak menyebut aset hak-guna sama sekali; dihitung 0",
                          "The report does not mention right of use assets at all; counted as 0", "Gail 28 Okt report"),
    "note.ppe_no_rou": _e("Aset tetap sesuai laporan; perusahaan tidak menyajikan aset hak-guna",
                          "PPE as presented; the company presents no right of use assets", "Gail 28 Okt report"),
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
    "note.tax_foreign": _e(
                            'Baris pajak luar negeri dikecualikan (lihat catatan pembacaan).',
                            'Foreign tax line item(s) excluded (see reading notes).',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "D-03"),
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
    "issue.tax_foreign": _e(
                             'Pajak luar negeri tidak dimasukkan dalam utang PPh badan karena catatan atas laporan keuangan tidak menjelaskan apakah pajak tersebut merupakan pajak atas laba ({line}).',
                             'Foreign taxes are excluded from corporate income tax payable because the notes to the financial statements do not specify whether they are taxes on profit ({line}).',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "D-03"),
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
    "check.detail_eq": _e("Total aset {a}; total liabilitas {b} + ekuitas {c}",
                          "Total assets {a}; total liabilities {b} + equity {c}", "Gail 28 Okt report"),
    "check.detail_gp": _e("Pendapatan {a} − beban pokok {b}; laba bruto tercetak {c}",
                          "Revenue {a} − cost of sales {b}; printed gross profit {c}", "Gail 28 Okt report"),
    "check.detail_vs": _e("Hasil penjumlahan {a}; total tercetak {b}", "Sum of the lines {a}; printed total {b}", "Gail 28 Okt report"),
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
    "flag.year_missing": _e(
                             'Angka hasil ekstraksi: label tahun pada judul kolom tidak dapat dibaca pada {stmts}. Dengan demikian, kolom tahun berjalan dan tahun pembanding belum dapat dipastikan. Skor ditahan; periksa di PDF.',
                             'Extracted figures: the year labels in the column headings could not be read in {stmts}. Therefore, the current-year and comparative-year columns cannot be confirmed. The score is withheld; check the PDF.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "P0-2"),
    "flag.year_mismatch": _e(
                              'Angka hasil ekstraksi: tahun pada judul kolom berbeda antar laporan ({list}). Skor ditahan; periksa di PDF.',
                              'Extracted figures: the year labels in the column headings differ across the statements ({list}). The score is withheld; check the PDF.',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "P0-2"),
    "flag.year_item": _e(
                          '{stmt} {y}, hal. {p}',
                          '{stmt} {y}, p. {p}',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.year_labels": _e(
                             'Label tahun pada judul kolom konsisten di ketiga laporan utama: {list}.',
                             'The year labels in the column headings are consistent across the three primary financial statements: {list}.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "P0-2"),
    "issue.financial_institution": _e(
                                       'Laporan ini memuat pos-pos yang lazim ditemukan pada bank, perusahaan asuransi, atau lembaga pembiayaan ({items}). Model Beneish tidak dirancang untuk menilai lembaga keuangan; karena itu, M-score tidak dihitung.',
                                       'This report contains line items commonly found in banks, insurance companies, or finance companies ({items}). The Beneish model was not designed to assess financial institutions; therefore, the M-score is not calculated.',
                                       'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
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
    "ui.proc.sub": _e("{name} · {pages} halaman", "{name} · {pages} pages", "Gail 4 Nov 16.53 (perkiraan waktu dihapus)"),
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
    "ui.proc.summary": _e(
                           'Ringkasan pembacaan',
                           'Reading summary',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.proc.xbrl": _e(
                        'Data XBRL dicocokkan dengan laporan PDF',
                        'XBRL data reconciled to the PDF financial statements',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.proc.xbrl_detail": _e(
                               '{ok} dari {n} angka pada laporan utama tercetak sebagai pasangan komparatif dua tahun; {rev} perlu diverifikasi',
                               '{ok} of {n} primary-statement figures were identified as two-year comparative pairs; {rev} require verification',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.proc.checks_x": _e(
                            '{err} gagal · {rev} perlu diperiksa',
                            '{err} failed · {rev} require review',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.xbrl_path": _e("Angka pada laporan posisi keuangan, laporan laba rugi dan laporan arus kas bersumber dari "
                          "berkas XBRL yang diunggah dan telah dicocokkan dengan PDF. Oleh karena itu, catatan pembacaan "
                          "PDF atas ketiga laporan tersebut tidak disajikan.",
                          "Amounts in the statements of financial position, profit or loss and cash flows are sourced "
                          "from the uploaded XBRL file and agreed to the PDF. Accordingly, the PDF reading notes on these "
                          "statements are not presented.", "Gail 4 Nov 17.07 (arah); teks disetujui Gail 4 Nov 18.40"),
    "ui.res.another": _e("Analisis laporan lain", "Analyse another report", "Gail 28 Okt desain"),
    "ui.res.meta": _e("Tahun buku {t} vs {t1} · {stype} · {unit} · {pages} halaman",
                      "Financial year {t} vs {t1} · {stype} · {unit} · {pages} pages", "Gail 28 Okt desain"),
    "unit.USD.Units": _e("Dolar AS", "US dollars", "Gail 28 Okt P4"),
    "unit.USD.Thousands": _e("ribuan Dolar AS", "thousands of US dollars", "Gail 28 Okt P4"),
    "unit.USD.Millions": _e("jutaan Dolar AS", "millions of US dollars", "Gail 28 Okt P4"),
    "unit.USD.Billions": _e("miliaran Dolar AS", "billions of US dollars", "Gail 28 Okt P4"),
    "check.section_ca": _e(
                            'Jumlah seluruh pos aset lancar sama dengan total aset lancar.',
                            'The current asset line items sum to total current assets.',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.section_cl": _e(
                            'Jumlah seluruh pos liabilitas jangka pendek sama dengan total liabilitas jangka pendek.',
                            'The current liability line items sum to total current liabilities.',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.ta_tle": _e(
                        'Total aset sama dengan jumlah total liabilitas dan ekuitas.',
                        'Total assets equal total liabilities and equity.',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.tl_parts": _e(
                          'Jumlah liabilitas jangka pendek dan liabilitas jangka panjang sama dengan total liabilitas.',
                          'Current and non-current liabilities sum to total liabilities.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.net_income": _e(
                            'Laba sebelum pajak dan pos-pos setelahnya menghasilkan laba tahun berjalan yang sama dengan yang dilaporkan.',
                            'Profit before tax and the subsequent line items reconcile to the reported profit for the year.',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.cfo": _e(
                     'Jumlah arus kas dari aktivitas operasi, investasi, dan pendanaan sama dengan kenaikan (penurunan) bersih kas.',
                     'Operating, investing, and financing cash flows sum to the net increase (decrease) in cash.',
                     'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.cash_cf": _e(
                         'Saldo kas dan setara kas cocok dengan saldo pada laporan arus kas.',
                         'Cash and cash equivalents agree with the balance reported in the statement of cash flows.',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.sga_total": _e(
                           'Jumlah beban penjualan dan beban umum sama dengan total beban usaha yang tercantum dalam laporan.',
                           'Selling and general expenses sum to the total operating expenses reported in the financial statements.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.in_notes": _e(
                          '{item}: angka yang sama ditemukan kembali dalam catatan (hal. {p}).',
                          '{item}: the same figure was also identified in the notes (p. {p}).',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.no_crosscheck": _e(
                              'Angka ini belum dapat dikonfirmasi melalui sumber kedua dalam laporan. Periksa di PDF.',
                              'This figure could not be corroborated against a second source within the report. Check the PDF.',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.sga_missed": _e(
                            'Baris yang tampak sebagai beban penjualan atau beban umum tidak teridentifikasi sebagai bagian dari kelompok beban tersebut: {lines}. Skor ditahan sampai baris-baris ini diperiksa.',
                            'Lines that appear to represent selling or general expenses were not identified as part of those expense categories: {lines}. Score calculation is withheld pending review of these lines.',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.sga_other": _e(
                           'Total beban usaha juga mencakup pos lain yang tidak diklasifikasikan sebagai beban penjualan dan beban umum: {lines}. Periksa di PDF.',
                           'Total operating expenses also include other items that are not classified as selling and general expenses: {lines}. Check the PDF.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "flag.sga_total": _e(
                          'Angka hasil ekstraksi: jumlah beban penjualan dan beban umum ({a}) tidak sama dengan total beban usaha yang tercantum. Selisihnya juga tidak dijelaskan oleh pos lain yang disajikan secara terpisah. Kemungkinan terdapat baris yang terlewat; periksa di PDF.',
                          'Extracted figures: selling and general expenses ({a}) do not agree with the reported total operating expenses. The difference is not explained by another separately presented line item. A line item may have been missed; check the PDF.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.section_nca": _e(
                             'Jumlah seluruh pos aset tidak lancar sama dengan total aset tidak lancar.',
                             'The non-current asset line items sum to total non-current assets.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.section_sum": _e(
                             '{sec}: angka pada kolom {col} tidak cocok ({a} terbaca; {b} tercetak; hal. {p}). Kemungkinan terdapat baris yang terlewat, terbaca lebih dari sekali, atau merupakan subtotal. Periksa di PDF.',
                             '{sec}: the figure in column {col} does not match ({a} extracted; {b} printed; p. {p}). A line may have been missed, read more than once, or treated as a subtotal. Check the PDF.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.ambiguous": _e(
                           'Lebih dari satu baris dengan angka berbeda cocok dengan {item}: {lines}. Sistem menggunakan baris pertama dan menandai pos tersebut untuk diperiksa.',
                           'More than one line containing different figures matches {item}: {lines}. The system uses the first matching line and flags the item for review.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.tax_no_face_match": _e(
                                  'Tabel pajak yang memuat PPh Pasal 25/29 ditemukan, tetapi jumlahnya tidak cocok dengan saldo utang pajak pada laporan posisi keuangan. Angka dari tabel tersebut tidak digunakan.',
                                  'A tax table containing Articles 25/29 income tax was identified, but its total does not agree with the taxes-payable balance in the statement of financial position. The table figures are not used.',
                                  'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "D-03"),
    "note.tax_zero_evidence": _e(
                                  'Tabel utang pajak dalam catatan (hal. {p}) cocok dengan laporan posisi keuangan, tetapi tidak memuat PPh badan Pasal 25/29 (misalnya hanya memuat pajak final, atau PPh badan sedang dalam posisi lebih bayar). Utang PPh badan dicatat 0. Periksa di PDF.',
                                  'The taxes-payable table in the notes (p. {p}) agrees with the statement of financial position but does not include Articles 25/29 corporate income tax (for example, it holds only final tax, or corporate income tax is in an overpayment position). Corporate income tax payable is recorded as zero. Check the PDF.',
                                  'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "D-03"),
    "flag.ppe_note": _e(
                         'Angka hasil ekstraksi: nilai aset tetap pada laporan posisi keuangan tidak ditemukan sebagai nilai tercatat dalam catatan aset tetap (angka yang terbaca dalam catatan: {seen}). Kemungkinan baris yang keliru terambil; periksa di PDF.',
                         'Extracted figures: the PPE amount in the statement of financial position was not identified as a carrying amount in the PPE note (figure identified in the note: {seen}). The wrong line item may have been extracted; check the PDF.',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "check.ppe_note": _e(
                          'Nilai tercatat aset tetap pada laporan posisi keuangan cocok dengan nilai tercatat dalam catatan aset tetap (hal. {p}).',
                          'The carrying amount of PPE in the statement of financial position agrees with the carrying amount disclosed in the PPE note (p. {p}).',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
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
    "note.debt_nil_g24": _e(
                             'Nihil sementara: tidak terdapat baris utang berbunga pada bagian ini; laporan posisi keuangan seimbang untuk kedua tahun; dan tidak ditemukan catatan pinjaman jangka panjang, obligasi, atau liabilitas sewa. Tetap periksa di PDF.',
                             'Provisionally assessed as nil: no interest-bearing line item appears in this section; the statement of financial position balances for both years; and no note on long-term borrowings, bonds, or lease liabilities was identified. Review the PDF before finalising.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)', "G-24"),
    "note.amort_sentence": _e(
                               'Amortisasi aset takberwujud diambil dari narasi dalam catatan (bukan dari tabel). Periksa angka pada halaman tersebut.',
                               'Intangible-asset amortisation was extracted from narrative disclosure in the notes rather than from a table. Review the figures on that page.',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_roll_ok": _e(
                                'Penyusutan aset hak-guna diambil dari tabel mutasi aset hak-guna. Rekonsiliasi saldo awal, mutasi, dan saldo akhir seimbang untuk kedua tahun; angka yang sama juga tercantum pada hal. {p}.',
                                'Depreciation of right-of-use assets was extracted from the right-of-use asset movement schedule. The opening balance, movements, and closing balance reconcile for both years; the same figure is also presented on p. {p}.',
                                'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_roll": _e(
                             'Penyusutan aset hak-guna diambil dari tabel mutasi aset hak-guna. Rekonsiliasi saldo awal, mutasi, dan saldo akhir seimbang untuk kedua tahun. Angka tersebut belum ditemukan pada sumber lain; periksa halaman terkait.',
                             'Depreciation of right-of-use assets was extracted from the right-of-use asset movement schedule. The opening balance, movements, and closing balance reconcile for both years. The figure has not been corroborated against another source; review the relevant page.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_sentence_ok": _e(
                                    'Penyusutan aset hak-guna diambil dari narasi dalam catatan aset hak-guna. Angka untuk kedua tahun juga tercantum dalam tabel mutasi akumulasi penyusutan.',
                                    'Depreciation of right-of-use assets was extracted from narrative disclosure in the right-of-use asset note. The figures for both years are also presented in the accumulated depreciation movement schedule.',
                                    'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_sentence": _e(
                                 'Penyusutan aset hak-guna diambil dari narasi dalam catatan aset hak-guna, tetapi tidak ditemukan dalam tabel mutasi. Periksa angka pada halaman tersebut.',
                                 'Depreciation of right-of-use assets was extracted from narrative disclosure in the right-of-use asset note but was not identified in the movement schedule. Review the figures on that page.',
                                 'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_lines_ok": _e(
                                 'Penyusutan aset hak-guna dijumlahkan dari baris beban di bawah judul “Beban penyusutan aset hak-guna”. Jumlah tersebut juga tercantum dalam tabel mutasi.',
                                 'Depreciation of right-of-use assets was aggregated from the expense lines under the heading “Depreciation of right-of-use assets”. The same total is also presented in the movement schedule.',
                                 'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.rou_dep_lines": _e(
                              'Penyusutan aset hak-guna dijumlahkan dari baris beban di bawah judul “Beban penyusutan aset hak-guna”. Total tabel tidak digunakan karena mencakup beban lain. Periksa angka tersebut.',
                              'Depreciation of right-of-use assets was aggregated from the expense lines under the heading “Depreciation of right-of-use assets”. The table total was not used because it includes other expenses. Review the figures.',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.ppe_dep_sentence": _e(
                                 'Penyusutan aset tetap milik sendiri diambil dari narasi dalam catatan aset tetap (tanpa tabel alokasi). Periksa angka pada halaman tersebut.',
                                 'Depreciation of owned PPE was extracted from narrative disclosure in the fixed-asset note; no allocation table was available. Review the figures on that page.',
                                 'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "np.source_fv": _e(
                        'Hal. {p}: properti investasi diukur dengan model nilai wajar sehingga tidak disusutkan: “{text}”.',
                        'P. {p}: investment property is measured using the fair value model and is therefore not depreciated: “{text}”.',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "v.held_invprop": _e(
                          'Properti investasi tercantum dalam laporan posisi keuangan (hal. {p}), tetapi beban penyusutannya tidak dapat diambil dari catatan atas laporan keuangan untuk {years}. M-score ditahan karena menganggapnya 0 dapat menghasilkan skor yang tidak akurat.',
                          'Investment property is presented in the statement of financial position (p. {p}), but its depreciation expense could not be extracted from the notes to the financial statements for {years}. M-score calculation is withheld because assuming a value of zero could produce an inaccurate score.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "issue.number_format": _e(
                               'Format angka tidak dapat ditentukan karena laporan utama menggunakan titik dan koma secara tidak konsisten sebagai pemisah ribuan. Angka tidak diekstrak karena kesalahan pemisah dapat mengubah nilainya hingga seribu kali lipat.',
                               'The number format could not be determined because the primary statements use dots and commas inconsistently as thousands separators. The figures were not extracted because an incorrect separator could change their values by a factor of 1,000.',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.res.meta_file": _e(
                            '{name} · {pages} halaman',
                            '{name} · {pages} pages',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.res.stype.Consolidated": _e("Laporan keuangan konsolidasian", "Consolidated financial statements",
                                    "Gail 28 Okt 11.01"),
    "ui.res.stype.Parent-only": _e(
                                    'Laporan keuangan (tidak dikonsolidasikan)',
                                    'Financial statements (unconsolidated)',
                                    'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.res.stype.unknown": _e(
                                'Jenis laporan keuangan tidak dapat dipastikan',
                                'Financial statement type could not be determined',
                                'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.res.issuer_unknown": _e(
                                 'Emiten tidak teridentifikasi',
                                 'Issuer could not be identified',
                                 'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.res.issuer_note": _e(
                              'Nama emiten dari sumber data yang tersedia',
                              'Issuer name from the available data sources',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
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
    "ui.res.assumed": _e(
                          'Termasuk {n} asumsi untuk angka yang tidak ditemukan. Rinciannya tercantum dalam daftar periksa.',
                          'This includes {n} assumptions for figures that were not found. See the checklist for details.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.idx.title": _e("Kedelapan indeks", "The eight indices", "Gail 28 Okt desain"),
    "ui.idx.col.index": _e("INDEKS", "INDEX", "Gail 28 Okt desain"),
    "ui.idx.col.name": _e("ARTI", "MEANING", "Gail 28 Okt desain"),
    "ui.idx.col.value": _e("NILAI", "VALUE", "Gail 28 Okt desain"),
    "ui.idx.col.push": _e(
                           'KONTRIBUSI',
                           'CONTRIBUTION',
                           'Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
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
    "ui.unreadable_title": _e(
                               'Laporan tidak dapat dibaca',
                               'The report could not be read',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.read_details": _e("Detail pembacaan", "Reading details", "Gail 28 Okt impl"),

    # ---------------------------------------------------------------- provisional assumptions (Gail 28 Okt 10.41)
    "status.ASSUMED": _e(
                          'Asumsi hasil sementara',
                          'Provisional assumption',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),

    # ---------------------------------------------------------------- verification step in the app (Gail 4 Nov 2026)
    "ui.step.check": _e("Pengecekan", "Review", "Gail 4 Nov 09.07"),
    "ui.up.xbrl": _e(
                      'File XBRL (opsional)',
                      'XBRL file (optional)',
                      'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "ui.up.xbrl_sub": _e(
                          'Untuk tahun buku 2022 dan seterusnya, unggah instance.zip dari situs BEI. Angka laporan utama diambil dari XBRL, lalu dicocokkan dengan laporan PDF.',
                          'For financial years 2022 onwards, provide the instance.zip file downloaded from the IDX website. Primary-statement figures are extracted from XBRL and then reconciled to the PDF financial statements.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chk.title": _e("Skor ditahan: {n} pos memerlukan verifikasi", "Score withheld: {n} items require verification", "Gail 4 Nov 09.07"),
    "chk.sub": _e("Pos lainnya telah selesai pembacaan automated dan rekonsiliasi silang. Pos berikut belum dapat "
                  "direkonsiliasi dengan sumber kedua dalam laporan. Tinjau setiap pos terhadap potongan halaman sumber, "
                  "lalu pilih Sesuai apabila pembacaan WARS telah tepat, atau Ganti nilai untuk memasukkan nilai yang benar. "
                  "Untuk pos yang tidak ditemukan, lengkapi nilai beserta rujukan halaman sumber atau nyatakan nihil. "
                  "Skor dihitung setelah seluruh pos diverifikasi.",
                  "All other items have completed automated reading and cross-reconciliation. The items below could not be "
                  "reconciled to a second source within the report. Review each item against the source page extract, then "
                  "select Agree if the WARS reading is correct, or Amend to enter the correct amount. For lines not "
                  "found, complete the amount with its source page reference or state nil. The score is "
                  "calculated once all items have been verified.", "Gail 4 Nov 09.07; tambahan Gail 8 Nov 16.32"),
    "chk.item_of": _e("POS {i} DARI {n}", "ITEM {i} OF {n}", "Gail 4 Nov 09.07"),
    "chk.reading": _e("Pembacaan WARS {y}", "WARS reading {y}", "Gail 4 Nov 09.07"),
    "chk.ok": _e("Sesuai", "Agree", "Gail 4 Nov 09.07"),
    "chk.edit": _e("Ganti nilai", "Amend", "Gail 4 Nov 09.07"),
    "chk.input": _e("Nilai yang benar {y}", "Correct amount {y}", "Gail 4 Nov 09.07"),
    "chk.input_help": _e("Tanpa desimal, dalam {unit}.", "No decimals, in {unit}.", "Gail 4 Nov 09.07"),
    "chk.badge.pending": _e("Belum diverifikasi", "Pending", "Gail 4 Nov 09.07"),
    "chk.badge.ok": _e("Sesuai", "Agreed", "Gail 4 Nov 09.07"),
    "chk.badge.edit": _e("Diganti", "Amended", "Gail 4 Nov 09.07"),
    "chk.extract": _e("Potongan halaman {p}", "Page extract, page {p}", "Gail 4 Nov 09.07"),
    "chk.no_extract": _e("Potongan halaman tidak tersedia. Periksa laporan pada halaman {p}.",
                         "Page extract unavailable. Refer to page {p} of the report.", "Gail 4 Nov 09.07"),
    "chk.summary": _e("Ringkasan", "Summary", "Gail 4 Nov 09.07"),
    "chk.progress": _e("{d} dari {n} pos telah diverifikasi", "{d} of {n} items verified", "Gail 4 Nov 09.07"),
    "chk.others": _e("{n} pos lainnya: Selesai pembacaan automated.", "{n} other items: automated reading completed.", "Gail 4 Nov 09.07"),
    "chk.calc": _e("Hitung skor", "Calculate score", "Gail 4 Nov 09.07"),
    "chk.calc_hint": _e("Tersedia setelah seluruh pos diverifikasi.", "Available once all items have been verified.", "Gail 4 Nov 09.07"),
    "chk.skip": _e("Lewati langkah pengecekan. Unduh laporan.", "Skip the review step. Download the report.", "Gail 4 Nov 09.07"),
    "chk.skipped": _e("Langkah pengecekan dilewati. Skor tidak dihitung; pos yang memerlukan verifikasi tercantum di "
                      "daftar periksa laporan.",
                      "The review step was skipped. No score is calculated; the items that require verification are listed "
                      "in the report checklist.", "Gail 4 Nov 09.07"),
    "chk.back": _e("Ubah verifikasi", "Change verification", "Gail 4 Nov 09.07"),
    "chk.gate": _e("File XBRL tidak dapat digunakan: {why}", "The XBRL file cannot be used: {why}", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.err.format": _e("Nilai tidak valid. Masukkan angka tanpa desimal, misalnya 91.300.000.000.",
                         "Invalid amount. Enter a whole number, for example 91,300,000,000.", "Gail 4 Nov 09.07"),
    "chk.err.pending": _e("{item} belum diverifikasi.", "{item} has not been verified.", "Gail 4 Nov 09.07"),
    "chk.err.missing": _e("Nilai {y} untuk {item} belum diisi.", "The {y} amount for {item} has not been entered.", "Gail 4 Nov 09.07"),
    "chk.err.negative": _e("{item} tidak boleh bernilai negatif.", "{item} cannot be negative.", "Gail 4 Nov 09.07"),
    "chk.err.checks": _e("Nilai yang dimasukkan tidak lolos pemeriksaan: {msg}", "The amounts entered failed a check: {msg}",
                         "Gail 4 Nov 09.07"),
    "chk.prov.note": _e("Pembacaan WARS: {old}", "WARS reading: {old}", "Gail 4 Nov 09.07"),
    "chk.note.assumed": _e("Tidak terbaca dalam laporan; dihitung 0 sesuai asumsi sementara.",
                           "Not read from the report; counted as 0 under the provisional assumption.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.note.assumed_part": _e("Sebagian dibaca dari laporan; bagian yang tidak terbaca dihitung 0 sesuai asumsi sementara.",
                                "Partly read from the report; the parts not read are counted as 0 under the provisional "
                                "assumption.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.note.not_found": _e("Tidak ditemukan dalam laporan.", "Not found in the report.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.note.single": _e("Dibaca dari satu sumber dalam laporan; belum direkonsiliasi dengan sumber kedua.",
                          "Read from a single source within the report; not reconciled to a second source.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.res.origin": _e("ASAL NILAI", "ORIGIN OF AMOUNTS", "Gail 4 Nov 09.07"),
    "chk.res.auto": _e("Selesai pembacaan automated", "Automated reading completed", "Gail 4 Nov 09.07"),
    "chk.res.agreed": _e("Diverifikasi sesuai oleh pengguna", "Agreed by the user", "Gail 4 Nov 09.07"),
    "chk.res.amended": _e("Diganti oleh pengguna", "Amended by the user", "Gail 4 Nov 09.07"),
    "chk.res.n": _e("{n} pos", "{n} items", "Gail 4 Nov 09.07"),
    "chk.res.caveat": _e("Skor ini menggunakan nilai yang diverifikasi atau diganti oleh pengguna. Seluruh nilai tersebut "
                         "tercantum dalam laporan yang diunduh.",
                         "This score uses amounts agreed or amended by the user. All such amounts are listed in the "
                         "downloadable reports.", "Gail 4 Nov 09.07"),
    "chk.res.table": _e("Pos yang diverifikasi pengguna", "Items verified by the user", "Gail 4 Nov 09.07"),
    "chk.res.col.item": _e("Pos", "Item", "Gail 4 Nov 09.07"),
    "chk.res.col.status": _e("Status", "Status", "Gail 4 Nov 09.07"),
    "chk.res.col.reading": _e("Pembacaan WARS {t} / {t1}", "WARS reading {t} / {t1}", "Gail 4 Nov 09.07"),
    "chk.res.col.used": _e("Digunakan {t} / {t1}", "Used {t} / {t1}", "Gail 4 Nov 09.07"),
    "status.USER CONFIRMED": _e("Diverifikasi sesuai oleh pengguna", "Agreed by the user", "Gail 4 Nov 09.07"),
    "status.USER AMENDED": _e("Diganti oleh pengguna", "Amended by the user", "Gail 4 Nov 09.07"),
    "chk.f.revenue": _e("Pendapatan", "Revenue", "Gail 4 Nov 09.07"),
    "chk.f.cost_of_goods_sold": _e("Beban pokok pendapatan", "Cost of revenue", "Gail 4 Nov 09.07"),
    "chk.f.selling_general_administrative_expenses": _e("Beban penjualan, umum dan administrasi",
                                                        "Selling, general and administrative expenses", "Gail 4 Nov 09.07"),
    "chk.f.accounts_receivable": _e("Piutang usaha", "Trade receivables", "Gail 4 Nov 09.07"),
    "chk.f.total_assets": _e("Total aset", "Total assets", "Gail 4 Nov 09.07"),
    "chk.f.current_assets": _e("Aset lancar", "Current assets", "Gail 4 Nov 09.07"),
    "chk.f.property_plant_equipment_net": _e("Aset tetap dan aset hak-guna", "Fixed assets and right-of-use assets", "Gail 4 Nov 09.07"),
    "chk.f.current_liabilities": _e("Liabilitas jangka pendek", "Current liabilities", "Gail 4 Nov 09.07"),
    "chk.f.total_liabilities": _e("Total liabilitas", "Total liabilities", "Gail 4 Nov 09.07"),
    "chk.f.long_term_debt": _e("Utang berbunga jangka panjang", "Interest-bearing long-term debt", "Gail 4 Nov 09.07"),
    "chk.f.current_maturities_long_term_debt": _e("Bagian lancar utang berbunga jangka panjang",
                                                  "Current maturities of interest-bearing long-term debt", "Gail 4 Nov 09.07"),
    "chk.f.cash_and_cash_equivalents": _e("Kas dan setara kas", "Cash and cash equivalents", "Gail 4 Nov 09.07"),
    "chk.f.taxes_payable": _e("Utang pajak penghasilan badan", "Corporate income tax payable", "Gail 4 Nov 09.07"),
    "chk.f.ppe_depreciation_disclosed": _e("Beban penyusutan aset tetap dan aset hak-guna",
                                           "Depreciation of fixed assets and right-of-use assets", "Gail 4 Nov 09.07"),
    "chk.f.amortization_intangibles": _e("Amortisasi aset takberwujud", "Amortisation of intangible assets",
                                         "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.f.depreciation_amortization_non_ppe": _e(
        "Penyusutan dan amortisasi lain (properti investasi, aset tidak digunakan, biaya jangka panjang)",
        "Other depreciation and amortisation (investment property, assets not in use, long-term costs)",
        "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.f.net_income": _e("Laba tahun berjalan", "Profit for the year", "Gail 4 Nov 09.07"),
    "chk.f.cash_flow_from_operations": _e("Arus kas dari aktivitas operasi", "Cash flows from operating activities", "Gail 4 Nov 09.07"),
    "chk.r.tax_proxy": _e("Utang PPh badan (Pasal 25 dan 29) tidak dapat direkonsiliasi dengan total utang pajak, sehingga "
                          "total utang pajak digunakan sebagai pendekatan. Pilih Sesuai untuk mempertahankan pendekatan "
                          "tersebut, atau Ganti nilai dengan jumlah utang PPh badan.",
                          "Corporate income tax payable (Articles 25 and 29) could not be reconciled to total taxes payable; "
                          "total taxes payable is therefore used as an approximation. Select Agree to retain the "
                          "approximation, or Amend to enter the corporate income tax payable.", "Gail 4 Nov 09.07"),
    "chk.r.ar_contract": _e("Nilai XBRL mencakup tagihan bruto kepada pemberi kerja (aset kontrak). Aset kontrak tidak "
                            "termasuk piutang usaha; apabila rinciannya disajikan, nilai yang digunakan hanya piutang "
                            "usaha pihak ketiga dan pihak berelasi.",
                            "The XBRL amount includes gross amounts due from customers (contract assets). Contract assets "
                            "are excluded from trade receivables; where a breakdown is presented, only third-party and "
                            "related-party trade receivables are used.", "Gail 4 Nov 09.07"),
    "chk.r.debt_untagged": _e("Pos \u201c{line}\u201d pada laporan posisi keuangan tidak diklasifikasikan sebagai utang "
                              "berbunga dalam XBRL. Liabilitas sewa dan pinjaman berbunga lainnya termasuk dalam pos ini.",
                              "The line \u201c{line}\u201d in the statement of financial position is not classified as "
                              "interest-bearing debt in XBRL. Lease liabilities and other interest-bearing borrowings are "
                              "included in this item.", "Gail 4 Nov 09.07"),
    "chk.r.ppe_rou": _e("Pos \u201c{line}\u201d pada laporan posisi keuangan tidak diklasifikasikan dalam XBRL. Nilai "
                        "aset tetap yang digunakan harus mencakup aset hak-guna; periksa apakah pos ini sudah termasuk "
                        "dalam angka di atas.",
                        "The line \u201c{line}\u201d in the statement of financial position is not classified in XBRL. "
                        "The fixed asset amount used must include right-of-use assets; check whether this line is "
                        "already included in the amount above.", "Gail 4 Nov 09.07; diubah Claude 4 Nov opsi 1, menunggu Gail"),
    "chk.r.dep_rou": _e("Aset hak-guna disajikan terpisah dan tidak diklasifikasikan dalam XBRL. Beban penyusutan yang "
                        "digunakan harus mencakup penyusutan aset hak-guna.",
                        "Right-of-use assets are presented separately and are not classified in XBRL. The depreciation "
                        "used must include depreciation of right-of-use assets.", "Gail 4 Nov 09.07"),
    "chk.r.dep_conflict": _e("Beban penyusutan menurut catatan atas laporan keuangan berbeda dengan tabel mutasi aset "
                             "tetap dalam XBRL ({x}). Beban penyusutan yang digunakan mencakup aset tetap milik sendiri "
                             "dan aset hak-guna, tanpa amortisasi aset takberwujud.",
                             "Depreciation per the notes to the financial statements differs from the XBRL fixed asset "
                             "movement schedule ({x}). The depreciation used covers owned fixed assets and right-of-use "
                             "assets, excluding amortisation of intangible assets.", "Gail 4 Nov 09.07"),
    "chk.r.not_printed": _e("Nilai XBRL tidak ditemukan sebagai pasangan angka dua tahun pada satu baris laporan PDF, "
                            "sehingga belum dapat direkonsiliasi.",
                            "The XBRL amount does not appear as a two-year pair on a single line of the PDF statements and "
                            "could not be reconciled.", "Gail 4 Nov 09.07"),
    # A line WARS did not find (Gail 8 Nov 16.21: test branch first; wording chosen by Gail 16.32: 1A, 2A, 3B, 4A)
    "chk.r.missing": _e("Nilai pos ini tidak teridentifikasi dalam laporan sehingga skor belum dapat dihitung. "
                        "Masukkan nilai beserta rujukan halaman sumber, atau nyatakan nihil apabila pos ini tidak "
                        "terdapat dalam laporan.",
                        "The amount for this line was not identified in the report, so the score cannot yet be "
                        "calculated. Enter the amount with its source page reference, or state nil where the line is "
                        "not present in the report.", "Gail 8 Nov 16.32"),
    "chk.miss.enter": _e("Masukkan nilai", "Enter amount", "Gail 8 Nov 16.32"),
    "chk.miss.nil": _e("Nihil", "Nil", "Gail 8 Nov 16.32"),
    "chk.miss.input": _e("Nilai tercatat {y}", "Recorded amount {y}", "Gail 8 Nov 16.32"),
    "chk.miss.page": _e("Halaman sumber", "Source page", "Gail 8 Nov 16.32"),
    "chk.miss.note": _e("Dasar pernyataan nihil (catatan yang diperiksa)", "Basis for nil (notes examined)", "Gail 8 Nov 16.32"),
    "chk.prov.entered": _e("Dilengkapi oleh pengguna; rujukan halaman {p}.",
                           "Completed by the user; page reference {p}.", "Gail 8 Nov 16.32"),
    "chk.prov.nil": _e("Dinyatakan nihil oleh pengguna berdasarkan telaah atas: {note}.",
                       "Stated as nil by the user based on a review of: {note}.", "Gail 8 Nov 16.32"),
    "chk.prov.amended": _e("Diganti oleh pengguna; rujukan halaman {p}. Pembacaan WARS: {old}.",
                           "Amended by the user; page reference {p}. WARS reading: {old}.",
                           "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.page_help": _e("Nomor halaman menurut urutan file PDF (halaman pertama file = 1), bukan nomor halaman yang "
                        "tercetak di laporan.",
                        "Page number in the order of the PDF file (first page of the file = 1), not the page number "
                        "printed on the report.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.h.depreciation_amortization_non_ppe": _e(
        "Pos ini hanya mencakup penyusutan properti investasi (model biaya), penyusutan aset yang tidak digunakan "
        "atau dihentikan penggunaannya, dan amortisasi biaya jangka panjang (biaya ditangguhkan, hak atas tanah). "
        "Penyusutan aset tetap dan aset hak-guna serta amortisasi aset takberwujud dicatat pada pos tersendiri. "
        "Jangan memakai total penyusutan dan amortisasi dari informasi segmen, karena total tersebut sudah mencakup "
        "pos-pos tersebut. Bila tidak ada, nilainya nihil.",
        "This item covers only depreciation of investment property (cost model), depreciation of assets not in use "
        "or retired from use, and amortisation of long-term costs (deferred charges, land rights). Depreciation of "
        "PPE and right of use assets and amortisation of intangible assets are recorded under their own items. Do not "
        "use the total depreciation and amortisation from the segment information, as that total already includes "
        "those items. If there is none, the amount is nil.",
        "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.err.page": _e("Isi halaman sumber untuk {item}.", "Enter the source page for {item}.",
                       "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.err.note": _e("Isi dasar pernyataan nihil untuk {item}.", "Enter the basis for nil for {item}.",
                       "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.layout_cols": _e("Urutan kolom tahun pada lapisan teks PDF tidak konsisten antarbaris (halaman {pages}), "
                          "sehingga angka XBRL tidak dapat dicocokkan dengan laporan secara andal. Skor tidak dihitung.",
                          "The order of the year columns in the PDF text layer is inconsistent between lines (page "
                          "{pages}), so the XBRL amounts cannot be reliably agreed to the report. The score is not "
                          "calculated.", "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.r.risk": _e("Pos ini selalu memerlukan verifikasi karena penyajiannya sering tersebar di beberapa baris atau "
                     "catatan. Pastikan seluruh komponen, termasuk liabilitas sewa dan aset hak-guna, telah tercakup "
                     "dalam Pembacaan WARS.",
                     "This line always requires verification because its presentation is often spread across several "
                     "lines or notes. Confirm that all components, including lease liabilities and right of use "
                     "assets, are captured in the WARS reading.", "Gail 8 Nov 12.50 (1C)"),
    "chk.r.risk_debt": _e("Pos ini selalu memerlukan verifikasi karena penyajiannya sering tersebar di beberapa baris "
                          "atau catatan. Pastikan seluruh komponen, termasuk liabilitas sewa dan pinjaman pihak berelasi "
                          "yang dikenakan bunga, telah tercakup dalam Pembacaan WARS.",
                          "This line always requires verification because its presentation is often spread across "
                          "several lines or notes. Confirm that all components, including lease liabilities and "
                          "interest-bearing loans from related parties, are captured in the WARS reading.",
                          "Gail 11 Nov 09.43 (14 teks layar cek disetujui, dua bahasa)"),
    "chk.r.risk_tax": _e("Pos ini selalu memerlukan verifikasi karena penyajiannya sering tersebar di beberapa baris "
                         "atau catatan. Pastikan seluruh komponen, termasuk Pasal 25 dan Pasal 29, telah tercakup "
                         "dalam Pembacaan WARS.",
                         "This line always requires verification because its presentation is often spread across "
                         "several lines or notes. Confirm that all components, including Article 25 and Article 29, "
                         "are captured in the WARS reading.", "Gail 8 Nov 16.06 (1C, versi utang pajak)"),
    "chk.r.risk_zero": _e("Nilai ini tidak ditemukan dalam laporan sehingga dihitung nol. Telaah catatan terkait; "
                          "apabila nilai diungkapkan, termasuk dalam uraian naratif, masukkan nilai tersebut.",
                          "This amount was not found in the report and is counted as nil. Review the related note; "
                          "where the amount is disclosed, including in narrative text, enter that amount.",
                          "Gail 8 Nov 12.50 (2A)"),
    "chk.r.single": _e("Nilai ini belum dapat direkonsiliasi dengan sumber kedua dalam laporan.",
                       "This amount could not be reconciled to a second source within the report.", "Gail 4 Nov 09.07"),
    "note.assumed_am": _e(
                           'Aset takberwujud tidak ditemukan pada bagian laporan yang dibaca. Untuk hasil sementara, amortisasinya dianggap 0. Periksa catatan atas laporan keuangan sebelum memakai hasil ini.',
                           'No intangible assets were identified in the sections read. For the provisional result, their amortisation is assumed to be zero. Check the notes to the financial statements before relying on this result.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.assumed_np": _e(
                           'Penyusutan dan amortisasi aset selain aset tetap: jumlah yang berhasil diekstrak ({source}) digunakan, tetapi kelengkapannya belum dapat dipastikan.',
                           'Depreciation and amortisation of assets other than PPE: the extracted amount ({source}) is used, but its completeness has not been established.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "note.assumed_np_zero": _e(
                                'Penyusutan dan amortisasi aset selain aset tetap tidak ditemukan pada bagian laporan yang dibaca. Untuk hasil sementara, nilainya dianggap 0. Periksa catatan atas laporan keuangan sebelum memakai hasil ini.',
                                'Depreciation and amortisation of assets other than PPE were not identified in the sections read. For the provisional result, they are assumed to be zero. Check the notes to the financial statements before relying on this result.',
                                'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),

    # ---------------------------------------------------------------- PDF report and Excel (new; awaiting review)
    "rep.title": _e("Red-flag Scanner Report", "Red-flag Scanner Report", "Gail 28 Okt report"),
    "rep.page": _e(
                    'Halaman {n} dari {m}',
                    'Page {n} of {m}',
                    'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.generated": _e(
                         'Dibuat {d}',
                         'Generated {d}',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.version": _e(
                       'Bahasa Indonesia',
                       'English',
                       'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.footer_disclaimer": _e(
        "WARS is a red-flag detection system; its results do not constitute a conclusion of fraud and require further "
        "review. In case of any discrepancy, the Indonesian version prevails.",
        "WARS is a red-flag detection system; its results do not constitute a conclusion of fraud and require further "
        "review. In case of any discrepancy, the Indonesian version prevails.", "Gail 23 Okt R-06 R-07 R-11; 4 Nov 09.07"),
    "rep.s1": _e("Ikhtisar", "Overview", "r0 report"),
    "rep.s2": _e("Rincian skor", "Score breakdown", "r0 report"),
    "rep.s3": _e("Temuan", "Findings", "r0 report"),
    "rep.s4": _e(
                  'Daftar periksa',
                  'Checklist',
                  'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.s5": _e(
                  'Lampiran A · Angka yang dibaca',
                  'Appendix A · Figures read',
                  'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.s6": _e("Lampiran B · Pemeriksaan silang", "Appendix B · Cross-checks", "Gail 28 Okt report"),
    "rep.s8": _e("Lampiran C · Catatan pembacaan", "Appendix C · Reading notes", "Gail 28 Okt report"),
    "rep.b_intro": _e("Setiap pemeriksaan mencocokkan angka yang dibaca dengan tempat kedua di laporan. Lolos: angka "
                      "cocok. Gagal: angka tidak cocok, sehingga angka terkait perlu dicocokkan dengan PDF. Perlu "
                      "diperiksa: pemeriksaan tidak dapat diselesaikan secara otomatis. Alasannya tercantum di kolom "
                      "Penjelasan.",
                      "Each check agrees a figure read to a second place in the report. Passed: the figures agree. "
                      "Failed: the figures do not agree, so the related figures need to be agreed to the PDF. Needs "
                      "review: the check could not be completed automatically. The reason is given in the Explanation "
                      "column.", "Gail 28 Okt report"),
    "rep.b.col.no": _e("No.", "No.", "Gail 28 Okt report"),
    "rep.b.col.check": _e("Pemeriksaan", "Check", "Gail 28 Okt report"),
    "rep.b.col.result": _e("Hasil", "Result", "Gail 28 Okt report"),
    "rep.b.col.expl": _e("Penjelasan", "Explanation", "Gail 28 Okt report"),
    "rep.b.failed_why": _e("Angka tidak cocok. Kemungkinan ada baris yang terlewat, terbaca dua kali atau salah baca; "
                           "cocokkan baris terkait dengan PDF.",
                           "The figures do not agree. A line may have been missed, read twice or misread; agree the "
                           "related lines to the PDF.", "Gail 28 Okt report"),
    "rep.c_intro": _e("Hal-hal berikut ditemukan saat membaca PDF dan perlu diperhatikan saat mencocokkan angka.",
                      "The following points were found while reading the PDF and need to be considered when agreeing "
                      "the figures.", "Gail 28 Okt report"),
    "rep.c.col.note": _e("Catatan", "Note", "Gail 28 Okt report"),
    "rep.col.trace": _e("ANGKA SUMBER (HAL.)", "SOURCE FIGURES (PAGE)", "Gail 28 Okt report"),
    "rep.trace_item": _e("{item} (hal. {p})", "{item} (p. {p})", "Gail 28 Okt report"),
    "note.ambiguous_line": _e("Ada lebih dari satu baris dengan label serupa; pastikan baris yang dipakai benar",
                              "More than one line has a similar label; confirm that the line used is the right one", "Gail 28 Okt report"),
    "short.accounts_receivable": _e("Piutang usaha", "Trade receivables", "Gail 28 Okt report"),
    "short.revenue": _e("Pendapatan", "Revenue", "Gail 28 Okt report"),
    "short.cost_of_goods_sold": _e("Beban pokok", "Cost of sales", "Gail 28 Okt report"),
    "short.current_assets": _e("Aset lancar", "Current assets", "Gail 28 Okt report"),
    "short.property_plant_equipment_net": _e("Aset tetap", "PPE", "Gail 28 Okt report"),
    "short.total_assets": _e("Total aset", "Total assets", "Gail 28 Okt report"),
    "short.ppe_depreciation_disclosed": _e("Penyusutan", "Depreciation", "Gail 28 Okt report"),
    "short.selling_general_administrative_expenses": _e("Beban penjualan dan umum", "SG&A expenses", "Gail 28 Okt report"),
    "short.current_liabilities": _e("Liabilitas jangka pendek", "Current liabilities", "Gail 28 Okt report"),
    "short.long_term_debt": _e("Utang jangka panjang", "Long-term debt", "Gail 28 Okt report"),
    "short.cash_and_cash_equivalents": _e("Kas", "Cash", "Gail 28 Okt report"),
    "short.current_maturities_long_term_debt": _e("Bagian lancar utang", "Current portion of debt", "Gail 28 Okt report"),
    "short.taxes_payable": _e("Utang pajak", "Taxes payable", "Gail 28 Okt report"),
    "short.depreciation_amortization_total": _e("Penyusutan dan amortisasi", "Depreciation and amortisation", "Gail 28 Okt report"),
    "rep.s7": _e("Metodologi dan batasan", "Methodology and limitations", "Gail 28 Okt A3"),
    "rep.f.entity": _e("ENTITAS", "ENTITY", "r0 report"),
    "rep.f.ticker": _e("KODE SAHAM", "TICKER", "r0 report"),
    "rep.f.period": _e("PERIODE DIBANDINGKAN", "PERIODS COMPARED", "r0 report"),
    "rep.f.basis": _e("DASAR", "BASIS", "r0 report"),
    "rep.f.unit": _e(
                      'SATUAN',
                      'UNIT',
                      'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.f.source": _e("SUMBER", "SOURCE", "r0 report"),
    "rep.period": _e(
                      '{t} (t) vs {t1} (t−1)',
                      '{t} (t) vs {t1} (t−1)',
                      'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.source": _e(
                      '{name} · {pages} halaman · SHA-256 {sha}',
                      '{name} · {pages} pages · SHA-256 {sha}',
                      'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.score_label": _e("BENEISH M-SCORE · MODEL 8 VARIABEL", "BENEISH M-SCORE · 8-VARIABLE MODEL", "r0 report"),
    "rep.box.figures": _e(
                           'ANGKA',
                           'FIGURES',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.figures_v": _e(
                             '{a} dari {b} angka berhasil dibaca dan dicocokkan',
                             '{a} of {b} figures were successfully extracted and reconciled',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.figures_d": _e(
                             '{n} angka perlu diperiksa; lihat daftar periksa.',
                             '{n} figures require review; see the checklist.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.user": _e("KONFIRMASI PENGGUNA", "USER CONFIRMATION", "Gail 23 Okt R-15"),
    "rep.box.user_v": _e(
                          'Belum diperiksa',
                          'Not yet reviewed',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.user_done": _e(
                             'Di layar cek: {a} pos dikonfirmasi Sesuai dan {b} pos diganti nilainya dengan rujukan halaman',
                             'On the review screen: {a} items confirmed as Agree and {b} items amended with a page reference',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.user_skipped": _e(
                                'Dilewati; M-score tidak dihitung',
                                'Skipped; M-score not calculated',
                                'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.user_done_d": _e(
                               'Ini merupakan konfirmasi pengguna, bukan verifikasi independen. Status setiap angka tercantum dalam Lampiran A.',
                               'This is a user confirmation, not an independent verification. The status of each figure is provided in Appendix A.',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.box.user_d": _e("Cocokkan angka melalui daftar periksa.", "Agree the figures using the checklist.", "Gail 28 Okt report"),
    "rep.provisional_detail": _e("{n} angka perlu dicocokkan dengan PDF sumber melalui daftar periksa.",
                                 "{n} figures need to be agreed to the source PDF using the checklist.", "Gail 28 Okt report"),
    "rep.summary": _e("Ringkasan", "Summary", "r0 report"),
    "rep.breakdown_intro": _e(
                               'Setiap indeks membandingkan {t} dengan {t1}. Kontribusi menunjukkan seberapa jauh suatu indeks menggeser skor dari perusahaan netral ({n}). Kolom angka sumber menunjukkan pos dan halaman PDF yang dipakai untuk menghitung indeks.',
                               'Each index compares {t} with {t1}. The contribution shows how far an index moves the score away from a neutral company ({n}). The source figures column shows the line items and PDF pages used to calculate the index.',
                               'Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
    "rep.col.coef": _e("KOEF.", "COEF.", "r0 report"),
    "rep.sum_line": _e(
                        'Komponen netral {n} + kontribusi bersih {p} = M-score {m} · batas {thr}',
                        'Neutral component {n} + net contribution {p} = M-score {m} · threshold {thr}',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa); Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
    "rep.formula": _e(
                       'Indeks = rasio tahun berjalan ÷ rasio tahun pembanding; TATA = total akrual ÷ total aset tahun berjalan. Kontribusi = koefisien × (indeks − nilai netral); nilai netral adalah 1 untuk indeks dan 0 untuk TATA. M = {const} + Σ (koefisien × indeks).',
                       'Index = current-year ratio ÷ comparative-year ratio; TATA = total accruals ÷ current-year total assets. Contribution = coefficient × (index − neutral value); the neutral value is 1 for the indices and 0 for TATA. M = {const} + Σ (coefficient × index).',
                       'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa); Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
    "rep.no_findings": _e(
                           'Tidak ada rasio yang memenuhi kriteria temuan (DSRI, GMI, AQI, SGI atau TATA dengan kontribusi di atas 0,005).',
                           'No ratio meets the criteria for a finding (DSRI, GMI, AQI, SGI or TATA with a contribution above 0.005).',
                           'Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
    "rep.no_score": _e(
                        'M-score tidak dihitung; oleh karena itu, penilaian berbasis M-score tidak tersedia.',
                        'The M-score was not calculated; therefore, no M-score-based assessment is available.',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.finding": _e("Temuan {n} · {idx}", "Finding {n} · {idx}", "r0 report"),
    "rep.push_tag": _e(
                        'KONTRIBUSI {p}',
                        'CONTRIBUTION {p}',
                        'Gail 11 Nov 12.12 (Dorongan diganti Kontribusi)'),
    "rep.a": _e("A · ANGKA", "A · FIGURES", "r0 report"),
    "rep.c": _e("C · KEMUNGKINAN PENJELASAN", "C · POSSIBLE EXPLANATIONS", "B r1 §4"),
    "rep.d": _e("D · AREA UNTUK PEMERIKSAAN LEBIH LANJUT", "D · AREAS FOR FURTHER EXAMINATION", "r0 report"),
    "rep.why": _e("Tentang indeks ini", "About this index", "r1 7.14"),
    "rep.check_intro": _e(
        "Cocokkan setiap angka dengan halaman PDF yang disebut, lalu centang Sesuai atau Tidak sesuai. Jika ada angka "
        "yang tidak sesuai, M-score belum dapat digunakan.",
        "Agree each figure to the PDF page shown, then tick Matches or Does not match. If any figure does not match, "
        "the M-score cannot be relied on yet.", "Gail 28 Okt report"),
    "rep.check.none": _e("Tidak ada angka yang perlu dicocokkan.", "No figure needs checking.", "Gail 28 Okt impl"),
    "rep.check.col.no": _e(
                            'No',
                            'No',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.check.col.item": _e("Pos", "Line item", "Gail 28 Okt impl"),
    "rep.check.col.year": _e(
                              'Tahun',
                              'Year',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.check.col.value": _e("Nilai", "Value", "Gail 28 Okt impl"),
    "rep.check.col.page": _e(
                              'Hal.',
                              'Page',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.check.col.why": _e(
                             'Yang perlu dicocokkan',
                             'What to check',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.check.col.ok": _e("Sesuai", "Matches", "Gail 28 Okt C6 7.18"),
    "rep.check.col.bad": _e("Tidak sesuai", "Does not match", "Gail 28 Okt C6 7.18"),
    "rep.check.assumed": _e(
                             'Asumsi yang digunakan untuk hasil sementara',
                             'Assumptions used for the provisional result',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.check.sign": _e(
                          'Diperiksa oleh: ____________________    Tanggal: ____________    Paraf: ________',
                          'Reviewed by: ____________________    Date: ____________    Initials: ________',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.inputs_intro": _e(
                            'Angka disajikan dalam satuan yang digunakan pada laporan ({unit}). Baris sumber dikutip dari PDF.',
                            'Figures are presented in the unit used in the financial statements ({unit}). Source lines are quoted from the PDF.',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.checks.passed": _e(
                             'Lolos',
                             'Passed',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.checks.failed": _e(
                             'Tidak lolos',
                             'Failed',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.checks.review": _e("Perlu diperiksa", "Needs review", "r1 2.2"),
    "rep.method.p1": _e(
        "Model dikembangkan berdasarkan Beneish (1999). Skor rendah tidak berarti bebas salah saji. Model: Beneish "
        "(1999), 8 variabel; tahun berjalan dan pembanding diambil dari laporan yang sama.",
        "The model is based on Beneish (1999). A low score does not mean the statements are free of misstatement. "
        "Model: Beneish (1999), 8 variables; the current year and the comparatives come from the same report.",
        "Gail 28 Okt 10.32"),
    "rep.method.p2": _e(
                         'Batas yang ditampilkan hanya −1,78 (Beneish, 1999). Skor di atas batas tersebut menunjukkan bahwa angka terkait perlu diperiksa lebih lanjut; skor ini bukan probabilitas terjadinya kecurangan.',
                         'The only threshold shown is −1.78 (Beneish, 1999). A score above this threshold indicates that the relevant figures warrant further examination; the score is not a probability of fraud.',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.method.p3": _e(
                         'Angka diambil otomatis dari file XBRL bila diunggah, atau dibaca dari PDF digital. Setiap angka dicatat beserta halaman dan baris sumbernya di PDF. Angka yang tidak ditemukan dibiarkan kosong; angka yang untuk sementara diasumsikan 0 dicantumkan dalam daftar periksa.',
                         'Figures are taken automatically from the XBRL file when it is uploaded, or extracted from the digital PDF. Each figure is recorded with its source page and line in the PDF. Figures that are not found are left blank; figures provisionally assumed to be zero are listed in the checklist.',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "beta.limits": _e(
        "WARS v0.1 Beta telah melalui dua pengujian blind terhadap 20 emiten FY2022 dan FY2025 pada November 2026. "
        "Pengujian belum menunjukkan kesalahan pembacaan pada angka berstatus “Terbaca dan tercocokkan” untuk pos "
        "non-berisiko dalam sampel tersebut. Namun, sistem masih memiliki keterbatasan ekstraksi, belum diuji oleh "
        "pengguna independen, dan belum menjamin akurasi seluruh hasil. Pengguna wajib memverifikasi setiap angka "
        "melalui halaman sumber laporan keuangan sebelum menggunakan hasil analisis.",
        "WARS v0.1 Beta has been through two blind tests covering 20 IDX companies (FY2022 and FY2025) in November "
        "2026. The tests found no reading errors in figures with the status “Read and reconciled” for non-risk items in "
        "that sample. However, the system still has extraction limitations, has not been tested by independent users, "
        "and does not guarantee the accuracy of all results. Users must verify every figure against the source page of "
        "the financial statements before using the results of the analysis.",
        "Gail 11 Nov 12.37 (teks ID dari Gail); EN terjemahan Claude, menunggu Gail"),
    "rep.method.p4": _e(
                         'Laporan ini merupakan hasil penyaringan otomatis. Laporan ini bukan opini audit, tidak menggantikan prosedur audit atau pemeriksaan lainnya, dan bukan bukti adanya kecurangan maupun salah saji.',
                         'This report presents the results of an automated screening process. It is not an audit opinion, does not replace audit or other examination procedures, and does not constitute evidence of fraud or misstatement.',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.title.DSRI": _e(
                            'Piutang usaha dibanding penjualan',
                            'Trade receivables relative to sales',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.title.GMI": _e(
                           'Margin laba kotor',
                           'Gross margin',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.title.AQI": _e(
                           'Porsi aset tidak lancar selain aset tetap',
                           'Share of non-current assets other than PPE',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.title.SGI": _e(
                           'Penjualan',
                           'Sales',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.title.TATA": _e(
                            'Laba tahun berjalan dan arus kas operasi',
                            'Profit for the year and operating cash flow',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.SGI": _e(
                     'Penjualan',
                     'Sales',
                     'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.TATA_ni": _e(
                         'Laba tahun berjalan',
                         'Profit for the year',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.TATA_cfo": _e(
                          'Arus kas operasi',
                          'Operating cash flow',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.leg.prev": _e(
                          '{y} (tahun pembanding)',
                          '{y} (comparative year)',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.leg.cur": _e(
                         '{y} (tahun berjalan)',
                         '{y} (current year)',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.measure": _e(
                         'Ukuran: {name}',
                         'Measure: {name}',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.DSRI_ar": _e(
                         'Piutang usaha',
                         'Trade receivables',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.DSRI_rev": _e(
                          'Penjualan',
                          'Sales',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.GMI_rev": _e(
                         'Penjualan',
                         'Sales',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.GMI_gp": _e(
                        'Laba kotor',
                        'Gross profit',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.AQI_other": _e(
                           'Aset tidak lancar selain aset tetap',
                           'Non-current assets other than PPE',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.AQI_ta": _e(
                        'Total aset',
                        'Total assets',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.read.DSRI": _e(
                           'Piutang usaha sebesar {r1} dari penjualan pada {y1} dan {r} pada {y}. Kenaikan rasio ini meningkatkan DSRI.',
                           'Trade receivables represented {r1} of sales in {y1} and {r} in {y}. An increase in this ratio raises the DSRI.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.read.GMI": _e(
                          'Laba kotor sebesar {r1} dari penjualan pada {y1} dan {r} pada {y}. Penurunan margin ini meningkatkan GMI.',
                          'Gross profit represented {r1} of sales in {y1} and {r} in {y}. A decrease in this margin raises the GMI.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.read.AQI": _e(
                          'Aset tidak lancar selain aset tetap sebesar {r1} dari total aset pada {y1} dan {r} pada {y}. Kenaikan proporsi ini meningkatkan AQI.',
                          'Non-current assets other than property, plant and equipment (PPE) represented {r1} of total assets in {y1} and {r} in {y}. An increase in this proportion raises the AQI.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.read.SGI": _e(
                          'Penjualan berubah sebesar {g} dari {y1} ke {y}. Pertumbuhan penjualan meningkatkan SGI.',
                          'Sales changed by {g} from {y1} to {y}. Sales growth increases the SGI.',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.read.TATA": _e(
                           'Grafik membandingkan laba tahun berjalan dengan arus kas operasi sebagai gambaran akrual. TATA dalam skor dihitung dari perubahan modal kerja dikurangi penyusutan dan amortisasi, dibagi total aset, sehingga nilainya dapat berbeda dari selisih pada grafik.',
                           'The chart compares profit for the year with operating cash flow as an indication of accruals. TATA in the score is computed from the change in working capital less depreciation and amortisation, divided by total assets, so its value can differ from the gap shown in the chart.',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "chart.unconfirmed": _e(
                             'Angka pada grafik belum dikonfirmasi di layar cek; lihat daftar periksa.',
                             'Chart figures have not yet been confirmed on the review screen; see the checklist.',
                             'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "rep.contact": _e("Hubungi kami", "Contact us", "Gail 28 Okt report"),
    "rep.check.line": _e("Baris di PDF: {s}", "Line in the PDF: {s}", "Gail 28 Okt report"),

    "xl.sheet.summary": _e(
                            'Ringkasan',
                            'Summary',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.sheet.figures": _e(
                            'Angka',
                            'Figures',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.sheet.indices": _e(
                            'Indeks',
                            'Indices',
                            'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.sheet.checklist": _e(
                              'Daftar periksa',
                              'Checklist',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.sheet.checks": _e(
                           'Pemeriksaan silang',
                           'Cross-checks',
                           'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.col.answer": _e(
                         'Jawaban (Sesuai / Tidak sesuai)',
                         'Answer (Matches / Does not match)',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.col.source_label": _e(
                               'Pos di laporan',
                               'Line in the report',
                               'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.col.source_line": _e(
                              'Baris sumber (kutipan PDF)',
                              'Source line (PDF quote)',
                              'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.col.check": _e(
                        'Pemeriksaan',
                        'Check',
                        'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.col.result": _e("Hasil", "Result", "Gail 28 Okt desain"),
    "xl.col.detail": _e(
                         'Rincian',
                         'Detail',
                         'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.k.file": _e(
                     'Berkas',
                     'File',
                     'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.k.generated": _e(
                          'Dibuat',
                          'Generated',
                          'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
    "xl.k.mscore": _e(
                       'M-score',
                       'M-score',
                       'Gail 11 Nov 12.12 (tinjauan teks, dua bahasa)'),
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
