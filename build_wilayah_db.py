"""
Download ulang dataset kode wilayah administrasi Indonesia (format
PP.RR.KK.DDDD, sama dengan parameter `adm4` BMKG) dari sumber publik
cahyadsn/wilayah, lalu build ulang data/wilayah.db (SQLite).

Jalankan ini kalau butuh update data wilayah terbaru (misal ada pemekaran
daerah baru). Butuh koneksi internet.
"""

import re
import sqlite3
import sys
import urllib.request

SRC_URL = "https://raw.githubusercontent.com/cahyadsn/wilayah/master/db/wilayah.sql"
OUT = "data/wilayah.db"

row_re = re.compile(r"\('([0-9.]+)'\s*,\s*'((?:[^'\\]|'')*)'\)")


def unescape(s):
    return s.replace("''", "'")


def main():
    print(f"Mengunduh {SRC_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(SRC_URL, timeout=30) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    rows = row_re.findall(content)
    print(f"Ditemukan {len(rows)} baris wilayah", file=sys.stderr)

    conn = sqlite3.connect(OUT)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS wilayah")
    cur.execute("""
        CREATE TABLE wilayah (
            kode TEXT PRIMARY KEY,
            nama TEXT NOT NULL,
            level INTEGER NOT NULL,
            parent TEXT
        )
    """)

    data = []
    for kode, nama in rows:
        nama = unescape(nama)
        parts = kode.split(".")
        level = len(parts)
        parent = ".".join(parts[:-1]) if level > 1 else None
        data.append((kode, nama, level, parent))

    cur.executemany(
        "INSERT OR REPLACE INTO wilayah (kode, nama, level, parent) VALUES (?,?,?,?)",
        data,
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_parent ON wilayah (parent)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_level ON wilayah (level)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nama ON wilayah (nama)")
    conn.commit()
    conn.close()
    print(f"Selesai -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
