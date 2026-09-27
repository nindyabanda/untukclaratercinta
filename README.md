# 🌦️ Generator Laporan Cuaca BMKG & Data Historis (PDF)

Aplikasi web modern berbasis **Flask + WeasyPrint** untuk memantau prakiraan cuaca resmi BMKG (±3 hari ke depan) serta menganalisis data cuaca historis (1–12 bulan ke belakang via Open-Meteo ERA5), lengkap dengan pembagian waktu **Pagi, Siang, dan Malam** serta ekspor laporan ke format **PDF resmi siap cetak**.

---

## 🚀 Fitur Utama

1. **Prakiraan Cuaca BMKG (±3 Hari)**:
   - Data langsung dari API resmi BMKG per desa/kelurahan di seluruh Indonesia.
   - Ringkasan waktu: **Pagi (06:00–12:00)**, **Siang (12:00–18:00)**, dan **Malam (18:00–06:00)**.
   - Export PDF A4 portrait dengan WeasyPrint & fallback browser headless.

2. **Data Historis Cuaca (1–12 Bulan)**:
   - Data reanalisis Open-Meteo ERA5 Reanalysis berdasarkan koordinat presisi BMKG.
   - Agregasi harian & bulanan untuk suhu, kelembapan, curah hujan, angin, dan sinar matahari.
   - Rincian segmen pagi, siang, dan malam untuk setiap tanggal.
   - Export PDF A4 landscape dengan ringkasan statistik komprehensif.

3. **Database Wilayah Lengkap**:
   - SQLite `data/wilayah.db` memuat ~83.700 desa/kelurahan di Indonesia (Kepmendagri 2025).

---

## 🐳 Deployment Docker & GitHub Actions

Repository ini sudah terintegrasi penuh dengan **GitHub Actions** dan **GitHub Container Registry (GHCR)**.

### 1. Build & Push Otomatis via GitHub Actions
Setiap kali ada perubahan yang di-push ke branch `main`, GitHub Actions akan otomatis:
- Menjalankan build Docker container menggunakan `Dockerfile`.
- Mempublikasikan image ke **GitHub Container Registry**:
  ```text
  ghcr.io/nindyabanda/untukclaratercinta:latest
  ```

### 2. Menjalankan Container Docker di Server / VPS
Cukup jalankan satu perintah:
```bash
docker run -d -p 5000:5000 --name cuaca-app ghcr.io/nindyabanda/untukclaratercinta:latest
```

Atau menggunakan **Docker Compose**:
```bash
docker compose up -d
```
Aplikasi akan langsung aktif dan bisa diakses di `http://localhost:5000` (atau IP publik server Anda).

---

## 💻 Cara Menjalankan Secara Lokal (Python)

1. Pastikan Python 3.9+ terpasang.
2. Buat dan aktifkan virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```
3. Install dependensi:
   ```bash
   pip install -r requirements.txt
   ```
4. Jalankan aplikasi:
   ```bash
   python app.py
   ```
5. Buka browser di **http://127.0.0.1:5000**

---

## 📂 Struktur Proyek

```
cuaca-app/
├── .github/
│   └── workflows/
│       └── docker-publish.yml  # GitHub Actions CI/CD to GHCR
├── Dockerfile                  # Konfigurasi container Linux + WeasyPrint + Gunicorn
├── docker-compose.yml          # Konfigurasi 1-klik Docker Compose
├── requirements.txt            # Dependensi Python
├── app.py                      # Flask backend, router, logic API BMKG & Open-Meteo
├── build_wilayah_db.py         # Script generator database wilayah
├── data/
│   └── wilayah.db              # Database SQLite wilayah Indonesia
├── templates/
│   ├── index.html              # UI Web interaktif (Dual-Mode: BMKG & Historis)
│   ├── report.html             # Template PDF Prakiraan Cuaca BMKG
│   └── report_historis.html    # Template PDF Cuaca Historis
└── static/                     # Aset statis (jika ada)
```
