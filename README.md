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
- Fase 1: fondasi, login aman, multibahasa, grup/izin, laporan contoh.
- Fase 2: penjualan tiket di loket (foto dokumen, tunai/transfer + bukti, cetak 80mm + QR HMAC).
- Fase 3: **jadwal** — kelola pelayaran + kuota (admin & per operator), tunda/batal, pemindahan tiket otomatis
  (semua-atau-tidak-sama-sekali, cek kuota), pengumuman publik 4 bahasa, notifikasi sistem + email,
  batal/refund tiket (refund hanya alasan kesehatan, izin khusus), audit log.
- Fase 4: **scan QR Inspector (PWA)** — `/ticketing/scan/`. Online: tiap scan divalidasi server (sah / sudah naik / salah
  viajen / dibatalkan / QR palsu). Offline: daftar tiket viajen diunduh ke telemovel, scan diverifikasi dari daftar
  (cocok persis dengan payload QR bertanda tangan), antre di IndexedDB, dikirim otomatis saat online; server tetap
  penentu akhir (scan paling awal menang). Semua scan tercatat di `ScanEvent`. Kamera & service worker butuh
  **HTTPS** di produksi (localhost dikecualikan). Naikkan `APP_VERSION` di `.env` setelah deploy untuk menyegarkan cache PWA.
- Fase 5: **laporan** — dashboard (KPI hari/bulan/tahun + 4 grafik), laporan penjualan berfilter (rentang, rute, kapal,
  operator) dengan ekspor Excel & PDF, laporan kaixa per shift (kasir hanya melihat shift sendiri), laporan embarke
  (terjual vs naik, no-show, scan bermasalah), email otomatis harian/bulanan/tahunan ke `REPORT_RECIPIENTS` (Portugis,
  lampiran PDF + Excel). Operator hanya melihat angka kapalnya sendiri di semua halaman, grafik, dan ekspor.
- Fase 6: **layar kelola** (menu Jestaun) — matriks tarif (kategori × rute dalam satu layar; kosong = tidak dijual;
  harga baru hanya untuk penjualan berikutnya, tiket lama tidak berubah), kategori/rute/porta/operator/kapal,
  pengguna (satu peran + izin tambahan per orang, operator, undangan lewat email atau kata sandi awal, reset oleh
  admin yang menutup sesi lama), halaman akun sendiri, lupa password lewat email (link 24 jam, dibatasi 5/jam/IP),
  log audit. Pengaman: admin tidak bisa mengunci dirinya atau menghapus admin terakhir; tidak ada penghapusan pengguna
  (nonaktifkan saja); hapus data yang sudah dipakai ditolak dengan penjelasan. `/admin/` Django hanya untuk staf teknis.
- Fase 6b: **kategori & jenis penjualan** — penumpang hanya tiga kelas: *Labarik* (anak-anak), *Adultu* (dewasa),
  *Idozu* (lansia); batas umur diatur admin dan layar Kategoria memperingatkan jika ada umur tanpa kelas atau kelas
  yang tumpang-tindih. Orang asing (paspor) memakai kelas yang sama, kecuali admin membuat tarif khusus asing.
  **Aluga ró (charter)**: satu pemesanan per pelayaran (kuota charter 1), harga tarif atau hasil negosiasi (tercatat
  di audit), mengunci pelayaran dari penjualan kursi (dan sebaliknya); butuh izin `issue_charter`.
  **Bonus (gratis)** untuk pejabat pemerintah: pembayaran "Bonus", wajib referensi surat/ministerium, hanya
  penumpang, tetap memakai kursi, harga normal tersimpan untuk laporan (jumlah & nilai bonus), tidak bisa
  di-refund; butuh izin `issue_complimentary`. Kedua izin hanya dimiliki admin sampai diberikan per orang.
- Berikut: deploy (gunicorn, nginx, PostgreSQL, HTTPS, backup) menunggu server baru dari APORTIL; WhatsApp.

### Aturan hitung laporan (USD, hari = hari kalender Asia/Dili)
- **Bruto** = tiket yang dibuat pada periode, kecuali yang dibatalkan karena salah emisi (*void*, tidak dihitung).
- **Refund** = tiket refund (alasan kesehatan) yang refund-nya terjadi pada periode (tanggal refund, bukan tanggal jual).
- **Bersih** = bruto − refund. Uang di laci kaixa = penjualan tunai − refund tunai (transfer tidak masuk laci).

### Email laporan otomatis (cron, zona waktu server = Asia/Dili)
```
CRON_TZ=Asia/Dili
59 23 * * *  cd /srv/ticaportil && .venv/bin/python manage.py send_reports --period daily     # hari ini
10 6  1 * *  cd /srv/ticaportil && .venv/bin/python manage.py send_reports --period monthly   # bulan lalu
20 6  1 1 *  cd /srv/ticaportil && .venv/bin/python manage.py send_reports --period yearly    # tahun lalu
0  2  * * *  cd /srv/ticaportil && .venv/bin/python manage.py purge_documents
```
Aman dijalankan ulang: laporan yang sudah terkirim dilewati (`--force` untuk kirim lagi); kegagalan SMTP dicatat
di `ReportLog` dan perintah keluar dengan error agar cron/monitoring mengetahuinya.

Email dikirim lewat SMTP APORTIL (`EMAIL_*` di `.env`); jika SMTP gagal, perubahan jadwal tetap tersimpan
dan kegagalan dicatat di audit log (`email_failed`).
