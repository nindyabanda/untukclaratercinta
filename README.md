# Generator Laporan Cuaca BMKG (PDF)

Aplikasi lokal berbasis **Flask + WeasyPrint** untuk memilih lokasi
(Provinsi → Kab/Kota → Kecamatan → Desa/Kelurahan) dan tanggal prakiraan,
lalu men-generate laporan cuaca BMKG dalam bentuk **PDF rapi yang bisa
langsung didownload**.

## Cara menjalankan (lokal)

1. Pastikan Python 3.9+ terpasang.
2. Buat virtual environment (opsional tapi disarankan):
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```
3. Install dependency:
   ```bash
   pip install -r requirements.txt
   ```
4. Jalankan servernya:
   ```bash
   python app.py
   ```
5. Buka browser ke **http://127.0.0.1:5000**

## Catatan penting soal WeasyPrint di Windows

WeasyPrint butuh library sistem **Pango/GDK-Pixbuf/Cairo**. Di Linux/Mac
biasanya lancar. Di Windows kadang perlu install GTK3 runtime terpisah
(cari "GTK3 Runtime Windows installer"), atau alternatifnya ganti
`weasyprint` di `app.py` dan `requirements.txt` dengan `xhtml2pdf`
(install-nya lebih ringan tapi hasil rendering CSS tidak sebagus WeasyPrint).

## Struktur proyek

```
cuaca-app/
├── app.py                  # Flask app: routing, panggil API BMKG, render PDF
├── requirements.txt
├── data/
│   └── wilayah.db          # SQLite: kode wilayah adm1-adm4 (≈83.700 desa/kelurahan)
├── templates/
│   ├── index.html          # Form pilih lokasi (cascading dropdown) + tanggal
│   └── report.html         # Template laporan (dipakai untuk preview & sumber PDF)
└── build_wilayah_db.py     # Script untuk build ulang wilayah.db dari sumber resmi
```

## Tentang `wilayah.db`

Berisi kode wilayah administrasi (format `PP.RR.KK.DDDD`, sama persis dengan
parameter `adm4` yang dipakai API BMKG) untuk seluruh Indonesia — bersumber
dari dataset publik [cahyadsn/wilayah](https://github.com/cahyadsn/wilayah)
(mengacu Kepmendagri No 300.2.2-2430 Tahun 2025). Sudah diubah ke SQLite
dengan kolom `level` (1=provinsi, 2=kab/kota, 3=kecamatan, 4=desa) dan
`parent` supaya query cascading dropdown-nya cepat.

Kalau di kemudian hari ada pemekaran wilayah baru, tinggal jalankan ulang:
```bash
python build_wilayah_db.py
```
(script ini akan download ulang data terbaru dan build ulang `data/wilayah.db`)

## Alur aplikasi

1. User pilih Provinsi → Kab/Kota → Kecamatan → Desa (masing-masing level
   di-fetch on-the-fly dari `wilayah.db` lewat endpoint `/api/...`, tidak
   perlu load semua data sekaligus).
2. Setelah Desa dipilih, aplikasi memanggil `/api/tanggal/<adm4>` yang
   nge-hit API BMKG (`api.bmkg.go.id/publik/prakiraan-cuaca?adm4=...`) dan
   mengembalikan daftar tanggal yang tersedia (biasanya 3 hari ke depan,
   update tiap 3 jam — **ini batasan dari API BMKG sendiri, bukan
   keterbatasan aplikasi**, jadi tidak bisa pilih tanggal jauh ke masa lalu
   atau masa depan).
3. User klik **Lihat Preview** (buka `report.html` di tab baru) atau
   **Download PDF** (`/pdf`, yang me-render template yang sama lalu
   convert ke PDF via WeasyPrint dan langsung trigger download).

## Kustomisasi

- Ganti logo/warna/layout PDF: edit `templates/report.html` (CSS di dalam
  `<style>`, WeasyPrint support CSS `@page` untuk header/footer/nomor
  halaman seperti yang sudah dipakai).
- Mau expose ke jaringan lokal (diakses dari HP di WiFi yang sama)? Ganti
  baris terakhir `app.py` jadi `app.run(host="0.0.0.0", port=5000)`.
