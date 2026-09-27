# Menggunakan image Python resmi berbasis Debian (slim)
FROM python:3.11-slim

# Mencegah Python menulis file .pyc ke disk
ENV PYTHONDONTWRITEBYTECODE=1
# Memastikan output stdout dan stderr tidak di-buffer
ENV PYTHONUNBUFFERED=1

# Mengatur direktori kerja di dalam container
WORKDIR /app

# Menginstal dependensi sistem yang dibutuhkan oleh WeasyPrint untuk render PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Menyalin file requirements terlebih dahulu untuk caching layer Docker
COPY requirements.txt .

# Menginstal dependensi Python
RUN pip install --no-cache-dir -r requirements.txt

# Menyalin seluruh kode aplikasi ke direktori kerja
COPY . .

# Mengekspos port 5000 untuk Flask/Gunicorn
EXPOSE 5000

# Perintah untuk menjalankan aplikasi menggunakan Gunicorn untuk production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
