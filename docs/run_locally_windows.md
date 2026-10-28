# Menjalankan WARS Scanner di laptop Windows (uji Fase 4)

Waktu: sekitar 15 menit untuk pertama kali. Tidak perlu Git, tidak perlu mengetik perintah.

## A. Pasang Python (sekali saja)

1. Buka https://www.python.org/downloads/windows/ dan unduh **Python 3.13** ("Windows installer 64-bit").
2. Jalankan installer. **Penting:** di layar pertama, centang **"Add python.exe to PATH"**, lalu klik **Install Now**.
3. Tunggu sampai muncul "Setup was successful", lalu tutup.

## B. Ambil kode aplikasi

1. Buka https://github.com/warsini-max/window-dressing-accounting-red-flag-scanner
2. Klik tombol hijau **Code** → **Download ZIP**.
3. Klik kanan file ZIP → **Extract All…** → pilih folder, misalnya `Documents\WARS`.

## C. Jalankan

1. Buka folder hasil ekstrak (yang berisi `app.py`).
2. Klik dua kali **`run_windows.bat`**.
   - Kalau Windows menampilkan "Windows protected your PC": klik **More info** → **Run anyway**.
   - Pertama kali, jendela hitam akan memasang paket selama beberapa menit. Biarkan saja.
3. Browser terbuka di `http://localhost:8501`. Kalau halamannya kosong atau error, tunggu
   beberapa detik lalu tekan **F5**.
4. Untuk berhenti: tutup jendela hitam.

Berikutnya cukup klik dua kali `run_windows.bat` lagi; tidak ada instalasi ulang.

## D. Uji Fase 4: lakukan sendiri, tanpa bantuan

Gunakan file `LK_SIDO_2021.pdf` (laporan keuangan tahunan SIDO 2021 yang sama dengan data uji).

| Langkah | Yang diharapkan |
|---|---|
| 1. Unggah `LK_SIDO_2021.pdf` | Dalam 5–15 detik muncul hasil dengan status **"Ditahan: status non-aset tetap belum ditetapkan"** dan **belum ada M-score**. Ini benar (M-06): skor ditahan sampai Anda menetapkan statusnya |
| 1a. Di bagian "Penyusutan dan amortisasi selain aset tetap: wajib ditetapkan", untuk **tahun 2021 dan 2020**: pilih status **"Tidak ada"** dan pilih catatan yang Anda periksa (minimal satu, misalnya catatan aset tetap dan aset tidak lancar lainnya). Periksa catatan itu di PDF sebelum memilih | Setelah kedua tahun ditetapkan, muncul M-score **−2,316** dan status Sementara. Kalau "Tidak ada" dipilih tanpa catatan yang diperiksa, skor tetap ditahan |
| 2. Baca tabel "Angka yang dibaca dari laporan" | Ada warna hijau dan kuning, nomor halaman PDF, baris sumber |
| 3. Di bagian Konfirmasi, tandai beberapa item (buka PDF di halaman yang disebut) | Hitungan "sesuai / tidak sesuai / belum dicek" di atas ikut berubah |
| 4. Tandai satu item "Tidak sesuai" | M-score berubah menjadi "—" dan muncul "tidak boleh dipakai" |
| 5. Kembalikan ke "Sesuai", isi nama pemeriksa | Skor muncul lagi |
| 6. Klik "Unduh semua angka + sumber (CSV)" | File CSV tersimpan dan berisi baris CONFIRM dengan nama Anda |

Catat untuk setiap langkah: **berhasil / gagal / bingung**, dan bagian mana yang membingungkan.
Kalau ada pesan error di jendela hitam, salin teksnya (atau foto layar) dan kirim ke Claude.
Fase 4 selesai hanya kalau semua langkah (1, 1a, 2–6) berhasil tanpa dibantu.

## Catatan

- File PDF yang diunggah diproses di laptop Anda sendiri, tidak dikirim ke mana pun.
- Versi paket dikunci di `requirements-lock.txt` (versi yang sama dengan yang diuji).
- Yang belum diuji: instalasi di Windows itu sendiri (pengujian dilakukan di Linux). Kalau
  langkah A–C gagal, itu temuan yang harus dilaporkan, bukan kesalahan Anda.
