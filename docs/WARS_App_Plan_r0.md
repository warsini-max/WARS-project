# WARS Scanner — Rencana Pembangunan Aplikasi (r0)

**Tanggal:** 21 Okt 2026
**Status:** rencana kerja, disusun atas permintaan Gail (21:36 WIB). Belum ada kode aplikasi yang ditulis.
**Perubahan arah:** barang jadi WARS adalah **aplikasi yang bisa dipakai user**. Evaluasi S1 tetap ada, tetapi fungsinya sebagai bukti uji aplikasi, bukan tujuan akhir.

---

## 1. Produk yang dibangun

**Satu kalimat:** user meng-upload PDF laporan keuangan tahunan teraudit (digital) milik emiten IDX. Aplikasi membaca angkanya, menghitung delapan rasio Beneish dan M-score, lalu menampilkan **red flag** beserta alasannya. Setiap angka bisa ditelusuri ke halaman sumbernya.

**Yang dikeluarkan aplikasi:**
- M-score dan posisinya terhadap ambang skrining:
  - −1,78 dan −1,49 (Beneish 1999, sudah dicek di workbook);
  - −2,22 hanya boleh ditampilkan dengan label "tidak berasal dari Beneish 1999, belum diverifikasi".
- Delapan rasio, dengan penanda rasio mana yang paling mendorong skor naik.
- Tabel angka yang dipakai: nama pos, nilai t dan t−1, satuan, serta halaman dan kutipan sumber.
- Catatan kualitas data: angka yang tidak ditemukan, perlu dicek, atau dihitung dengan asumsi.
- Batasan, ditulis jelas di setiap hasil.

**Yang TIDAK dilakukan aplikasi:**
- Tidak menyatakan "fraud" atau "manipulasi terjadi". Bahasanya: "pola angka mirip kasus manipulasi dalam model Beneish; perlu pemeriksaan lebih lanjut".
- Tidak menilai niat, tidak menilai kasus hukum, tidak memberi rekomendasi investasi.
- Tidak dipakai untuk bank, asuransi, dan lembaga keuangan lain. Model Beneish dibangun dari perusahaan manufaktur dan dagang, dan struktur akunnya tidak cocok (misalnya tidak ada HPP). Aplikasi menolak atau memberi peringatan untuk laporan seperti ini.

**Sikap forensik yang dipegang:** tidak boleh ada angka salah yang lolos diam-diam. Setiap angka harus memenuhi salah satu dari tiga syarat: (a) ditemukan dan lolos cek silang, (b) ditandai "perlu dicek" dan ditunjukkan ke user, atau (c) dinyatakan tidak ditemukan sehingga rasio terkait tidak dihitung. Tebakan diam-diam tidak diizinkan.

---

## 2. Aset yang sudah ada

| Aset | Lokasi | Dipakai untuk |
|---|---|---|
| Workbook `WARS_TrackB_v0_6.xlsx` (26 sheet, termasuk Parameters, Data_Dictionary 248 baris, Validation_Checks, Data_Entry_Guide, Mapping_Decisions) | workspace sesi ini, `trackb/out/` | **Spesifikasi mesin.** Rumus, koefisien, ambang, aturan entri (D-01 s.d. D-13, A3, A4, A7), dan cek validasi dipindah ke Python |
| Skrip `mscore.py`, `entries.py` (contoh entri), `build_trackb_v06.py` | workspace | Rumus M-score yang sudah jalan di Python; contoh format angka dengan sumber halaman |
| 8 PDF uji non-evaluasi: SIDO 2020/2021, KLBF 2020/2021/2023, MYOR 2020/2021 | `s3core/docs/` | **Data uji aplikasi.** MYOR 2021 sengaja dipakai sebagai contoh halaman hasil scan |
| Catatan scan S3core (SIDO, KLBF, MYOR) | Project docs | Daftar jebakan yang sudah diketahui: satuan, PSAK 73/sewa, amortisasi tidak diungkap (G-22), reklasifikasi aset dimiliki untuk dijual, metode arus kas langsung, halaman scan |
| Aturan evaluasi S1 (register Part 1–12, konsolidasi r5) | Project docs, workspace | **Diparkir.** Dipakai lagi di Fase 7 sebagai uji kelayakan aplikasi |
| PDF emiten dalam register kasus | workspace | **Tidak dipakai untuk membangun atau mengetes aplikasi** sampai S1 dikunci (WR-2 M2) |

---

## 3. Alur aplikasi

```
[1] Upload PDF
      |
[2] Cek dokumen: digital atau scan per halaman, jumlah halaman, bahasa, tahun buku,
    sektor (tolak/beri peringatan untuk lembaga keuangan)
      |
[3] Temukan halaman laporan utama: posisi keuangan, laba rugi, arus kas,
    plus catatan yang dibutuhkan (aset tetap/penyusutan, beban)
      |
[4] Ekstraksi: ambil 15-18 pos untuk kolom t dan t-1, kenali satuan
    (Rupiah penuh / ribuan / jutaan), catat halaman dan kutipan
      |
[5] Cek silang otomatis: total aset = liabilitas + ekuitas, subtotal cocok,
    kolom t-1 konsisten, tanda (+/-) wajar
      |
[6] Layar konfirmasi: tabel angka + sumber. Hijau = lolos cek; kuning = perlu
    dilihat; merah = tidak ditemukan. User cukup klik "Lanjut" atau memperbaiki
    angka yang kuning/merah
      |
[7] Hitung: 8 rasio + M-score, dengan aturan workbook v0.6
      |
[8] Laporan hasil: skor, red flag, pendorong utama, catatan kualitas data,
    batasan. Bisa diunduh (PDF/Excel)
```

---

## 4. Fase kerja

Setiap fase punya kriteria selesai. Fase berikutnya tidak dimulai sebelum kriteria fase sebelumnya terpenuhi.

### Fase 0 — Persiapan dan "kunci jawaban" data uji
- **Pekerjaan:**
  - Bekukan pekerjaan S1 di r5. Tidak ada aturan evaluasi baru sampai Fase 7.
  - Susun struktur proyek kode (`wars_scanner/`).
  - Bangun **golden dataset**: untuk setiap PDF uji, daftar 15–18 angka yang benar, dengan halaman sumbernya. Asisten menyiapkan draf dari catatan scan S3core; **Gail memverifikasi** angkanya di PDF.
- **Kriteria selesai:** golden dataset untuk minimal 4 laporan (SIDO 2020/2021, KLBF 2020/2021) terverifikasi Gail.
- **Alasan:** tanpa kunci jawaban ini, kita tidak bisa mengukur apakah pembaca PDF-nya benar.

### Fase 1 — Mesin hitung (engine)
- **Pekerjaan:**
  - Port rumus delapan rasio dan M-score, koefisien, ambang, dan aturan entri yang relevan dari workbook v0.6 ke modul Python.
  - Tulis tes otomatis.
- **Kriteria selesai:** untuk angka input yang sama, hasil Python **sama persis** dengan workbook v0.6 (selisih hanya pembulatan), untuk semua pasangan uji yang tersedia.

### Fase 2 — Pembaca PDF (ekstraksi)
- **Pekerjaan:**
  - Deteksi halaman scan vs digital.
  - Pencari halaman laporan utama.
  - Pembaca tabel dua kolom (t, t−1).
  - Kamus nama akun dua bahasa (Indonesia/Inggris) beserta variasinya.
  - Deteksi satuan.
  - Pencarian di catatan untuk penyusutan dan amortisasi.
- **Pendekatan:** dimulai dengan aturan (kamus akun dan pola tabel), tanpa AI berbayar.
- **Kriteria selesai, diukur terhadap golden dataset:**
  - **nol angka salah yang tidak ditandai** (aturan forensik di §1);
  - persentase angka yang ditemukan otomatis dilaporkan per pos. Targetnya ditetapkan setelah pengukuran pertama.

### Fase 3 — Cek silang dan layar konfirmasi
- **Pekerjaan:** cek identitas neraca, subtotal, konsistensi kolom, perubahan tahun-ke-tahun yang ekstrem (ambang 100% di workbook), serta penanda hijau, kuning, dan merah.
- **Kriteria selesai:** setiap kesalahan yang sengaja disuntikkan ke data uji (salah satuan, kolom tertukar, angka hilang) tertangkap sebagai kuning atau merah.

### Fase 4 — Aplikasi web (Streamlit)
- **Pekerjaan:** halaman upload, konfirmasi, dan hasil; unduh hasil; teks batasan dan disclaimer.
- **Kriteria selesai:** Gail bisa menjalankan alur penuh untuk SIDO 2021 dari upload sampai unduh hasil, tanpa bantuan.

### Fase 5 — Uji coba

| Uji | Isi | Lulus bila |
|---|---|---|
| U1 Hitung | Engine vs workbook v0.6 | Sama persis |
| U2 Ekstraksi | Semua PDF uji vs golden dataset | Nol angka salah tanpa tanda; tingkat temuan otomatis dicatat |
| U3 Ketahanan | MYOR 2021 (laporan utama hasil scan), laporan dengan kolom "disajikan kembali", satuan berbeda-beda, laporan tanpa penyusutan terpisah | Aplikasi memberi peringatan yang benar, tidak diam-diam salah |
| U4 Sektor | Satu laporan bank (dicari belakangan) | Aplikasi menolak atau memberi peringatan |
| U5 Pengguna | Gail dan 2–3 orang lain (misalnya teman akuntansi/auditor) mencoba tanpa dipandu | Mereka paham arti hasil dan tidak membacanya sebagai "terbukti fraud" |

### Fase 6 — Online dan portofolio
- **Pekerjaan:**
  - Kode di GitHub (repo publik).
  - Hosting gratis di Streamlit Community Cloud atau Hugging Face Spaces.
  - README yang menjelaskan metode, batasan, dan cara pakai.
- **Kriteria selesai:** ada link yang bisa dibuka orang lain, dan aplikasi berjalan untuk semua PDF uji.

### Fase 7 — Uji kelayakan terhadap kasus nyata (S1, versi cukup)
- **Pekerjaan:**
  - Selesaikan aturan S1 minimum yang dibutuhkan (F3, P4, cut-off), lalu kunci.
  - Baru setelah itu jalankan aplikasi ke emiten dalam register kasus.
  - Tulis halaman "Seberapa bisa dipercaya alat ini" berisi hasil apa adanya.
- **Batas klaim:** dengan jumlah kasus sesedikit ini, hasilnya adalah **studi kasus**, bukan bukti akurasi statistik.

### Fase 8 (opsional) — Peningkatan
- OCR untuk halaman scan.
- Bantuan model AI lewat API untuk mengenali pos yang sulit (butuh API key, ada biaya per laporan).
- Laporan multi-tahun.

---

## 5. Pembagian peran

| Pihak | Peran |
|---|---|
| **Claude** (di sesi Claude ini) | Pemimpin teknis: menulis kode, menjalankan tes, menyiapkan draf golden dataset, menjaga aturan forensik, dan melaporkan hasil uji apa adanya |
| **Gail** | Pemilik produk dan ahli akuntansi: memverifikasi golden dataset di PDF, memutuskan hal-hal di §6, mengurus akun GitHub/Streamlit, dan menguji sebagai pengguna |
| **ChatGPT** | Reviewer kedua atas rencana, hasil uji, dan teks penjelasan untuk user. Tidak menambah aturan evaluasi baru selama Fase 0–6 |

---

## 6. Keputusan yang perlu diambil Gail (bertahap, bukan sekarang semua)

| # | Keputusan | Kapan | Usulan Claude |
|---|---|---|---|
| K1 | Nama aplikasi | Sebelum Fase 6 | "WARS Scanner" |
| K2 | Bahasa tampilan | Sebelum Fase 4 | Indonesia, dengan istilah teknis Inggris |
| K3 | Repo publik atau privat | Sebelum Fase 6 | Publik (untuk portofolio) |
| K4 | Pakai AI berbayar untuk ekstraksi | Setelah U2 | Hanya bila tingkat temuan otomatis berbasis aturan terlalu rendah |
| K5 | Ambang mana yang ditampilkan | Sebelum Fase 4 | −1,78 sebagai utama; −1,49 sebagai tambahan; −2,22 dengan label "belum diverifikasi" atau tidak ditampilkan |

---

## 7. Risiko dan pengendalian

| Risiko | Pengendalian |
|---|---|
| Hasil dibaca sebagai tuduhan fraud terhadap perusahaan nyata | Bahasa "red flag / perlu pemeriksaan"; disclaimer di setiap hasil; tidak ada label "fraud" |
| Satu angka salah baca membuat skor melenceng | Aturan forensik §1, cek silang Fase 3, dan layar konfirmasi dengan sumber halaman |
| PDF hasil scan | Dideteksi dan diberi peringatan (Fase 2); OCR di Fase 8 |
| Laporan yang disajikan kembali | Aturan workbook: pakai laporan edisi pertama untuk skor utama; kolom "disajikan kembali" diberi tanda |
| Sektor yang tidak cocok | Ditolak atau diberi peringatan (U4) |
| Klaim akurasi berlebihan | Fase 7 hanya studi kasus; batasan ditulis jelas |
| Kebocoran evaluasi (lihat skor emiten register kasus sebelum aturan dikunci) | Emiten register kasus tidak dipakai sampai Fase 7 (WR-2 M2 tetap berlaku) |

---

## 8. Status pekerjaan S1

- Pekerjaan aturan S1 **dibekukan** di register Part 12 dan konsolidasi r5. Tidak ada keputusan yang dicabut.
- Paket F3 (D-F3-1 s.d. D-F3-7) tetap PROPOSED — NOT APPROVED dan dibuka lagi di Fase 7.
- Workbook v0.6 tidak diubah. Aplikasi membaca aturannya, bukan mengubahnya.
