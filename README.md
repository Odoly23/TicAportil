# TicAportil — APORTIL e-Ticketing (Bilheteira)

Sistem tiket kapal APORTIL Timor-Leste: Dili–Ataúro, Dili–Oecusse. Django 5.2, Bootstrap 4, crispy-forms,
DataTables, DRF + Highcharts. Mobile-first, 4 bahasa (Tetun default, PT, EN, ID). Gaya kode mengikuti proyek `sjdf`.

## Struktur
| App | Isi |
|---|---|
| `main` | layout/navbar per grup, halaman publik (jadwal & tarif), static (Bootstrap, DataTables, Highcharts) |
| `config` | `decorators.py` (`allowed_users`, `unauthenticated_user`), `utils.py` (id/hash SHA-256, nama bulan, path upload) |
| `users` | User, login (kunci setelah 5x gagal, sesi 30 menit), AuditLog, `setup_roles` |
| `custom` | data master: Port, Route, Operator, Vessel, FareItem, Fare |
| `ticketing` | Sailing (jadwal), SailingQuota, Ticket (QR HMAC), Announcement, `purge_documents` |
| `report` | dashboard + API grafik (`/api/report/...`) |

Grup: `admin`, `resepsionista`, `inspector`, `operator` (izin per pengguna bisa diatur admin).

## Jalankan lokal
```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py createcachetable
python manage.py setup_roles && python manage.py createsuperuser
python manage.py runserver
python manage.py test
```

## Terjemahan
Teks sumber = Tetun. Tambah di `scripts/translations.py`, lalu `python scripts/build_locale.py` (tanpa gettext).

## Cron
`python manage.py purge_documents` — harian; hapus foto dokumen > 30 hari.

## Status
Fase 1 (fondasi) selesai. Berikut: penjualan loket + cetak 80mm, scan QR PWA offline, jadwal/kuota/pengumuman,
refund medis, email laporan, deploy.
