"""
Laporan Cuaca BMKG + Data Historis (Open-Meteo)
------------------------------------------------
Aplikasi lokal (Flask) untuk:
  1) Prakiraan cuaca ±3 hari ke depan  — via API resmi BMKG
  2) Data cuaca historis 1–12 bulan ke belakang — via Open-Meteo Archive API

Jalankan:
    pip install -r requirements.txt
    python app.py
lalu buka http://127.0.0.1:5000
"""

import os
import shutil
import subprocess
import tempfile
import sqlite3
import io
from datetime import datetime, timedelta, date
from collections import OrderedDict, Counter

import requests
from flask import Flask, render_template, jsonify, send_file, abort, request

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    HTML = None
    WEASYPRINT_AVAILABLE = False

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "wilayah.db")
BMKG_API = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
OPENMETEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# WMO weather-code mapping → deskripsi cuaca bahasa Indonesia
WMO_DESCRIPTIONS = {
    0: "Cerah",
    1: "Cerah Berawan",
    2: "Berawan Sebagian",
    3: "Berawan",
    45: "Berkabut",
    48: "Berkabut Tebal",
    51: "Gerimis Ringan",
    53: "Gerimis",
    55: "Gerimis Lebat",
    56: "Gerimis Beku Ringan",
    57: "Gerimis Beku",
    61: "Hujan Ringan",
    63: "Hujan Sedang",
    65: "Hujan Lebat",
    66: "Hujan Beku Ringan",
    67: "Hujan Beku",
    71: "Salju Ringan",
    73: "Salju Sedang",
    75: "Salju Lebat",
    77: "Butiran Salju",
    80: "Hujan Singkat Ringan",
    81: "Hujan Singkat",
    82: "Hujan Singkat Lebat",
    85: "Hujan Salju Ringan",
    86: "Hujan Salju Lebat",
    95: "Badai Petir",
    96: "Badai Petir + Hujan Es Ringan",
    99: "Badai Petir + Hujan Es Lebat",
}

# WMO code → emoji
WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "🌨️", 77: "🌨️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

# ── Arah angin dari derajat ──
def deg_to_compass(deg):
    """Konversi derajat angin ke arah kompas singkat."""
    if deg is None:
        return "-"
    dirs = ["U", "TL", "T", "TG", "S", "BD", "B", "BL"]
    ix = round(deg / 45) % 8
    return dirs[ix]


# ── HTTP session dengan retry ──
_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(max_retries=3)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


# ── PDF generator ──────────────────────────────────────────────

def find_headless_browser():
    """Cari executable browser headless yang tersedia (Edge / Chrome)."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "msedge",
        "chrome",
        "chromium",
    ]
    for c in candidates:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def generate_pdf_bytes(html_str, base_url=""):
    """Generate PDF bytes menggunakan WeasyPrint atau fallback headless browser (Edge/Chrome)."""
    if WEASYPRINT_AVAILABLE and HTML is not None:
        try:
            return HTML(string=html_str, base_url=base_url).write_pdf()
        except Exception as e:
            app.logger.warning(f"WeasyPrint gagal: {e}. Mengalihkan ke browser headless...")

    browser = find_headless_browser()
    if browser:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(html_str)
            html_file = f.name
        pdf_file = html_file.replace(".html", ".pdf")
        try:
            subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    f"--print-to-pdf={pdf_file}",
                    "--no-pdf-header-footer",
                    html_file,
                ],
                check=True,
                timeout=30,
            )
            with open(pdf_file, "rb") as pf:
                return pf.read()
        finally:
            for fpath in (html_file, pdf_file):
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass

    raise RuntimeError("Tidak dapat membuat PDF: WeasyPrint maupun browser (Edge/Chrome) tidak tersedia.")


# ── Database helpers ───────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_wilayah(level, parent=None):
    conn = get_db()
    if parent is None:
        rows = conn.execute(
            "SELECT kode, nama FROM wilayah WHERE level=? ORDER BY nama",
            (level,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT kode, nama FROM wilayah WHERE level=? AND parent=? ORDER BY nama",
            (level, parent),
        ).fetchall()
    conn.close()
    return [{"kode": r["kode"], "nama": r["nama"]} for r in rows]


def get_nama_wilayah(kode):
    """Ambil nama lengkap (desa, kecamatan, kab/kota, provinsi) dari kode adm4."""
    conn = get_db()
    row = conn.execute("SELECT kode, nama FROM wilayah WHERE kode=?", (kode,)).fetchone()
    if not row:
        conn.close()
        return None

    parts = kode.split(".")
    hierarchy = {}
    labels = ["provinsi", "kabkota", "kecamatan", "desa"]
    for i, label in enumerate(labels[: len(parts)]):
        sub_kode = ".".join(parts[: i + 1])
        r = conn.execute("SELECT nama FROM wilayah WHERE kode=?", (sub_kode,)).fetchone()
        hierarchy[label] = r["nama"] if r else "-"
    conn.close()
    return hierarchy


# ── BMKG forecast ──────────────────────────────────────────────

def classify_bmkg_slot(slot):
    """Klasifikasi slot waktu BMKG menjadi Pagi, Siang, Malam, atau Dini Hari."""
    dt_str = slot.get("local_datetime", "")
    time_part = dt_str.split(" ")[1] if " " in dt_str else ""
    try:
        hour = int(time_part.split(":")[0])
    except Exception:
        hour = 12

    if 6 <= hour < 12:
        return {
            "kategori": "pagi",
            "label": "Pagi",
            "icon": "🌅",
            "badge_class": "badge-pagi",
        }
    elif 12 <= hour < 18:
        return {
            "kategori": "siang",
            "label": "Siang / Sore",
            "icon": "☀️",
            "badge_class": "badge-siang",
        }
    elif 18 <= hour <= 23:
        return {
            "kategori": "malam",
            "label": "Malam",
            "icon": "🌙",
            "badge_class": "badge-malam",
        }
    else:
        return {
            "kategori": "malam",
            "label": "Dini Hari",
            "icon": "🌌",
            "badge_class": "badge-dini",
        }


def summarize_day_periods(slots):
    """
    Rangkum prakiraan cuaca per periode (Pagi, Siang, Malam) untuk satu hari.
    """
    period_defs = [
        ("pagi", "Pagi", "06:00 – 12:00", "🌅"),
        ("siang", "Siang / Sore", "12:00 – 18:00", "☀️"),
        ("malam", "Malam", "18:00 – 06:00", "🌙"),
    ]
    grouped = {"pagi": [], "siang": [], "malam": []}
    for s in slots:
        kat = s.get("waktu_info", {}).get("kategori", "siang")
        if kat in grouped:
            grouped[kat].append(s)

    result = []
    for key, label, jam_range, icon in period_defs:
        s_list = grouped[key]
        if not s_list:
            result.append({
                "key": key,
                "label": label,
                "jam_range": jam_range,
                "icon": icon,
                "ada_data": False,
                "weather_desc": "Data terlewat / tidak ada",
                "image": None,
                "suhu_str": "-",
                "kelembapan_str": "-",
                "angin_str": "-",
            })
            continue

        rep = s_list[len(s_list) // 2]
        temps = [s["t"] for s in s_list if s.get("t") is not None]
        hums = [s["hu"] for s in s_list if s.get("hu") is not None]
        winds = [s["ws"] for s in s_list if s.get("ws") is not None]

        if temps:
            t_min, t_max = min(temps), max(temps)
            suhu_str = f"{t_min}–{t_max}°C" if t_min != t_max else f"{t_min}°C"
        else:
            suhu_str = "-"

        hum_str = f"{round(sum(hums)/len(hums))}%" if hums else "-"
        wind_str = f"{round(sum(winds)/len(winds))} km/j ({rep.get('wd', '-')})" if winds else "-"

        result.append({
            "key": key,
            "label": label,
            "jam_range": jam_range,
            "icon": icon,
            "ada_data": True,
            "weather_desc": rep.get("weather_desc") or "-",
            "image": rep.get("image"),
            "suhu_str": suhu_str,
            "kelembapan_str": hum_str,
            "angin_str": wind_str,
        })
    return result


def fetch_bmkg_forecast(adm4):
    """Ambil data prakiraan cuaca dari API BMKG dan kelompokkan per tanggal & periode."""
    resp = _session.get(BMKG_API, params={"adm4": adm4}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    by_date = OrderedDict()
    cuaca_list = data.get("data", [{}])[0].get("cuaca", [])
    for hari in cuaca_list:
        for slot in hari:
            dt_str = slot.get("local_datetime", "")
            tanggal = dt_str.split(" ")[0] if dt_str else "N/A"
            slot["waktu_info"] = classify_bmkg_slot(slot)
            by_date.setdefault(tanggal, []).append(slot)

    day_summaries = {}
    for tanggal, slots in by_date.items():
        day_summaries[tanggal] = summarize_day_periods(slots)

    lokasi = data.get("lokasi", {})
    return lokasi, by_date, day_summaries


def get_bmkg_coordinates(adm4):
    """Ambil lat/lon dari BMKG API untuk kode adm4."""
    resp = _session.get(BMKG_API, params={"adm4": adm4}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    lokasi = data.get("lokasi", {})
    lat = lokasi.get("lat")
    lon = lokasi.get("lon")
    tz = lokasi.get("timezone", "Asia/Jakarta")
    return lat, lon, tz, lokasi


# ── Open-Meteo historical ─────────────────────────────────────

def fetch_historical_weather(lat, lon, start_date, end_date, timezone="Asia/Jakarta"):
    """
    Fetch daily & hourly historical weather data from Open-Meteo Archive API.
    Menghasilkan ringkasan harian dan segmen waktu Pagi, Siang, dan Malam.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "weathercode",
            "windspeed_10m_max",
            "winddirection_10m_dominant",
            "relative_humidity_2m_mean",
            "sunshine_duration",
        ]),
        "timezone": timezone,
    }
    resp = _session.get(OPENMETEO_ARCHIVE, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])

    # Kelompokkan data hourly per tanggal
    hourly = data.get("hourly", {})
    h_times = hourly.get("time", [])
    h_temps = hourly.get("temperature_2m", [])
    h_codes = hourly.get("weather_code", [])
    h_rains = hourly.get("precipitation", [])

    by_day_hourly = {}
    for idx, ht in enumerate(h_times):
        d_part, h_part = ht.split("T") if "T" in ht else ht.split(" ")
        hour = int(h_part.split(":")[0])
        by_day_hourly.setdefault(d_part, []).append({
            "hour": hour,
            "temp": h_temps[idx] if idx < len(h_temps) else None,
            "code": h_codes[idx] if idx < len(h_codes) else 0,
            "rain": h_rains[idx] if idx < len(h_rains) else 0.0,
        })

    def calc_period_segment(h_items):
        if not h_items:
            return {"temp": None, "code": None, "desc": "Tidak ada data", "emoji": "—", "rain": 0.0}
        valid_temps = [it["temp"] for it in h_items if it["temp"] is not None]
        avg_temp = round(sum(valid_temps) / len(valid_temps), 1) if valid_temps else None

        codes = [it["code"] for it in h_items if it["code"] is not None]
        sig_codes = [c for c in codes if c >= 50]
        if sig_codes:
            dom_code = Counter(sig_codes).most_common(1)[0][0]
        elif codes:
            dom_code = Counter(codes).most_common(1)[0][0]
        else:
            dom_code = 0

        total_rain = round(sum(it["rain"] for it in h_items if it["rain"] is not None), 1)
        return {
            "temp": avg_temp,
            "code": dom_code,
            "desc": WMO_DESCRIPTIONS.get(dom_code, f"Kode {dom_code}"),
            "emoji": WMO_EMOJI.get(dom_code, "🌡️"),
            "rain": total_rain,
        }

    rows = []
    for i, t in enumerate(times):
        wcode = daily["weathercode"][i]
        sunshine_s = daily["sunshine_duration"][i]
        sunshine_h = round(sunshine_s / 3600, 1) if sunshine_s is not None else None

        day_h = by_day_hourly.get(t, [])
        pagi_list = [h for h in day_h if 6 <= h["hour"] < 12]
        siang_list = [h for h in day_h if 12 <= h["hour"] < 18]
        malam_list = [h for h in day_h if h["hour"] >= 18 or h["hour"] < 6]

        rows.append({
            "tanggal": t,
            "suhu_max": daily["temperature_2m_max"][i],
            "suhu_min": daily["temperature_2m_min"][i],
            "curah_hujan": daily["precipitation_sum"][i],
            "weathercode": wcode,
            "cuaca_desc": WMO_DESCRIPTIONS.get(wcode, f"Kode {wcode}"),
            "cuaca_emoji": WMO_EMOJI.get(wcode, "🌡️"),
            "angin_max": daily["windspeed_10m_max"][i],
            "angin_arah_deg": daily["winddirection_10m_dominant"][i],
            "angin_arah": deg_to_compass(daily["winddirection_10m_dominant"][i]),
            "kelembapan": daily["relative_humidity_2m_mean"][i],
            "sinar_matahari_jam": sunshine_h,
            "pagi": calc_period_segment(pagi_list),
            "siang": calc_period_segment(siang_list),
            "malam": calc_period_segment(malam_list),
        })

    # Group by month for easier display
    by_month = OrderedDict()
    for row in rows:
        month_key = row["tanggal"][:7]  # "YYYY-MM"
        by_month.setdefault(month_key, []).append(row)

    # Compute monthly statistics
    monthly_stats = OrderedDict()
    for month_key, month_rows in by_month.items():
        temps_max = [r["suhu_max"] for r in month_rows if r["suhu_max"] is not None]
        temps_min = [r["suhu_min"] for r in month_rows if r["suhu_min"] is not None]
        rain = [r["curah_hujan"] for r in month_rows if r["curah_hujan"] is not None]
        hum = [r["kelembapan"] for r in month_rows if r["kelembapan"] is not None]
        wind = [r["angin_max"] for r in month_rows if r["angin_max"] is not None]
        sun = [r["sinar_matahari_jam"] for r in month_rows if r["sinar_matahari_jam"] is not None]
        rainy_days = sum(1 for r in rain if r > 0.5)

        pagi_temps = [r["pagi"]["temp"] for r in month_rows if r["pagi"]["temp"] is not None]
        siang_temps = [r["siang"]["temp"] for r in month_rows if r["siang"]["temp"] is not None]
        malam_temps = [r["malam"]["temp"] for r in month_rows if r["malam"]["temp"] is not None]

        monthly_stats[month_key] = {
            "jumlah_hari": len(month_rows),
            "suhu_max_rata": round(sum(temps_max) / len(temps_max), 1) if temps_max else None,
            "suhu_min_rata": round(sum(temps_min) / len(temps_min), 1) if temps_min else None,
            "suhu_tertinggi": max(temps_max) if temps_max else None,
            "suhu_terendah": min(temps_min) if temps_min else None,
            "suhu_pagi_rata": round(sum(pagi_temps) / len(pagi_temps), 1) if pagi_temps else None,
            "suhu_siang_rata": round(sum(siang_temps) / len(siang_temps), 1) if siang_temps else None,
            "suhu_malam_rata": round(sum(malam_temps) / len(malam_temps), 1) if malam_temps else None,
            "total_hujan": round(sum(rain), 1) if rain else None,
            "hari_hujan": rainy_days,
            "kelembapan_rata": round(sum(hum) / len(hum), 1) if hum else None,
            "angin_max": round(max(wind), 1) if wind else None,
            "sinar_rata": round(sum(sun) / len(sun), 1) if sun else None,
        }

    # Overall stats
    all_temps_max = [r["suhu_max"] for r in rows if r["suhu_max"] is not None]
    all_temps_min = [r["suhu_min"] for r in rows if r["suhu_min"] is not None]
    all_pagi = [r["pagi"]["temp"] for r in rows if r["pagi"]["temp"] is not None]
    all_siang = [r["siang"]["temp"] for r in rows if r["siang"]["temp"] is not None]
    all_malam = [r["malam"]["temp"] for r in rows if r["malam"]["temp"] is not None]
    all_rain = [r["curah_hujan"] for r in rows if r["curah_hujan"] is not None]
    all_hum = [r["kelembapan"] for r in rows if r["kelembapan"] is not None]

    overall = {
        "total_hari": len(rows),
        "suhu_max_rata": round(sum(all_temps_max) / len(all_temps_max), 1) if all_temps_max else None,
        "suhu_min_rata": round(sum(all_temps_min) / len(all_temps_min), 1) if all_temps_min else None,
        "suhu_pagi_rata": round(sum(all_pagi) / len(all_pagi), 1) if all_pagi else None,
        "suhu_siang_rata": round(sum(all_siang) / len(all_siang), 1) if all_siang else None,
        "suhu_malam_rata": round(sum(all_malam) / len(all_malam), 1) if all_malam else None,
        "suhu_tertinggi": max(all_temps_max) if all_temps_max else None,
        "suhu_terendah": min(all_temps_min) if all_temps_min else None,
        "total_hujan": round(sum(all_rain), 1) if all_rain else None,
        "hari_hujan": sum(1 for r in all_rain if r > 0.5),
        "kelembapan_rata": round(sum(all_hum) / len(all_hum), 1) if all_hum else None,
    }

    return rows, by_month, monthly_stats, overall


# ── Routes ─────────────────────────────────────────────────────

@app.route("/")
def index():
    provinsi = fetch_wilayah(level=1)
    return render_template("index.html", provinsi=provinsi)


@app.route("/api/kabkota/<prov_kode>")
def api_kabkota(prov_kode):
    return jsonify(fetch_wilayah(level=2, parent=prov_kode))


@app.route("/api/kecamatan/<kab_kode>")
def api_kecamatan(kab_kode):
    return jsonify(fetch_wilayah(level=3, parent=kab_kode))


@app.route("/api/desa/<kec_kode>")
def api_desa(kec_kode):
    return jsonify(fetch_wilayah(level=4, parent=kec_kode))


@app.route("/api/tanggal/<adm4>")
def api_tanggal(adm4):
    """Kembalikan daftar tanggal yang tersedia dari prakiraan BMKG (biasanya 3 hari)."""
    try:
        _, by_date, _ = fetch_bmkg_forecast(adm4)
    except requests.RequestException:
        return jsonify({"error": "Gagal mengambil data dari BMKG"}), 502
    return jsonify(list(by_date.keys()))


@app.route("/api/coordinates/<adm4>")
def api_coordinates(adm4):
    """Return lat/lon for an adm4 code via BMKG."""
    try:
        lat, lon, tz, _ = get_bmkg_coordinates(adm4)
    except requests.RequestException:
        return jsonify({"error": "Gagal mengambil koordinat dari BMKG"}), 502
    if lat is None or lon is None:
        return jsonify({"error": "Koordinat tidak tersedia"}), 404
    return jsonify({"lat": lat, "lon": lon, "timezone": tz})


# ── Prakiraan cuaca (BMKG) ────

@app.route("/preview")
def preview():
    adm4 = request.args.get("adm4")
    tanggal = request.args.get("tanggal")
    if not adm4:
        abort(400, "Parameter adm4 wajib diisi")

    hierarchy = get_nama_wilayah(adm4)
    if not hierarchy:
        abort(404, "Kode wilayah tidak ditemukan")

    try:
        lokasi, by_date, day_summaries = fetch_bmkg_forecast(adm4)
    except requests.RequestException:
        abort(502, "Gagal mengambil data dari BMKG")

    if tanggal and tanggal in by_date:
        selected = {tanggal: by_date[tanggal]}
        selected_summaries = {tanggal: day_summaries.get(tanggal, [])}
    else:
        selected = by_date
        selected_summaries = day_summaries

    return render_template(
        "report.html",
        lokasi=lokasi,
        hierarchy=hierarchy,
        by_date=selected,
        day_summaries=selected_summaries,
        generated_at=datetime.now().strftime("%d %B %Y, %H:%M"),
        adm4=adm4,
    )


@app.route("/pdf")
def pdf():
    adm4 = request.args.get("adm4")
    tanggal = request.args.get("tanggal")
    if not adm4:
        abort(400, "Parameter adm4 wajib diisi")

    hierarchy = get_nama_wilayah(adm4)
    if not hierarchy:
        abort(404, "Kode wilayah tidak ditemukan")

    try:
        lokasi, by_date, day_summaries = fetch_bmkg_forecast(adm4)
    except requests.RequestException:
        abort(502, "Gagal mengambil data dari BMKG")

    if tanggal and tanggal in by_date:
        selected = {tanggal: by_date[tanggal]}
        selected_summaries = {tanggal: day_summaries.get(tanggal, [])}
    else:
        selected = by_date
        selected_summaries = day_summaries

    html_str = render_template(
        "report.html",
        lokasi=lokasi,
        hierarchy=hierarchy,
        by_date=selected,
        day_summaries=selected_summaries,
        generated_at=datetime.now().strftime("%d %B %Y, %H:%M"),
        adm4=adm4,
        pdf_mode=True,
    )

    pdf_bytes = generate_pdf_bytes(html_str, base_url=request.base_url)

    filename = f"cuaca_{hierarchy['desa'].replace(' ', '_')}_{tanggal or 'semua'}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


# ── Data historis (Open-Meteo) ────

@app.route("/preview-historis")
def preview_historis():
    adm4 = request.args.get("adm4")
    start = request.args.get("start")
    end = request.args.get("end")
    if not adm4 or not start or not end:
        abort(400, "Parameter adm4, start, dan end wajib diisi")

    hierarchy = get_nama_wilayah(adm4)
    if not hierarchy:
        abort(404, "Kode wilayah tidak ditemukan")

    try:
        lat, lon, tz, lokasi = get_bmkg_coordinates(adm4)
    except requests.RequestException:
        abort(502, "Gagal mengambil koordinat dari BMKG")

    if lat is None or lon is None:
        abort(404, "Koordinat tidak tersedia untuk kode wilayah ini")

    try:
        rows, by_month, monthly_stats, overall = fetch_historical_weather(lat, lon, start, end, tz)
    except requests.RequestException as e:
        abort(502, f"Gagal mengambil data historis dari Open-Meteo: {e}")

    return render_template(
        "report_historis.html",
        lokasi=lokasi,
        hierarchy=hierarchy,
        lat=lat,
        lon=lon,
        start_date=start,
        end_date=end,
        rows=rows,
        by_month=by_month,
        monthly_stats=monthly_stats,
        overall=overall,
        generated_at=datetime.now().strftime("%d %B %Y, %H:%M"),
        adm4=adm4,
    )


@app.route("/pdf-historis")
def pdf_historis():
    adm4 = request.args.get("adm4")
    start = request.args.get("start")
    end = request.args.get("end")
    if not adm4 or not start or not end:
        abort(400, "Parameter adm4, start, dan end wajib diisi")

    hierarchy = get_nama_wilayah(adm4)
    if not hierarchy:
        abort(404, "Kode wilayah tidak ditemukan")

    try:
        lat, lon, tz, lokasi = get_bmkg_coordinates(adm4)
    except requests.RequestException:
        abort(502, "Gagal mengambil koordinat dari BMKG")

    if lat is None or lon is None:
        abort(404, "Koordinat tidak tersedia")

    try:
        rows, by_month, monthly_stats, overall = fetch_historical_weather(lat, lon, start, end, tz)
    except requests.RequestException as e:
        abort(502, f"Gagal mengambil data historis: {e}")

    html_str = render_template(
        "report_historis.html",
        lokasi=lokasi,
        hierarchy=hierarchy,
        lat=lat,
        lon=lon,
        start_date=start,
        end_date=end,
        rows=rows,
        by_month=by_month,
        monthly_stats=monthly_stats,
        overall=overall,
        generated_at=datetime.now().strftime("%d %B %Y, %H:%M"),
        adm4=adm4,
        pdf_mode=True,
    )

    pdf_bytes = generate_pdf_bytes(html_str, base_url=request.base_url)

    filename = f"historis_{hierarchy['desa'].replace(' ', '_')}_{start}_{end}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
