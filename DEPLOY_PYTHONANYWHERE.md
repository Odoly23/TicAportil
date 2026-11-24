# Mencoba TicAportil di PythonAnywhere

Panduan untuk **uji coba**. Untuk produksi sungguhan di server APORTIL, lihat bagian "Sebelum produksi" di bawah.
Ganti `USERNAME` dengan nama akun PythonAnywhere Anda.

> Aplikasi sudah diuji di mode produksi (DEBUG mati, di belakang proxy HTTPS, gunicorn + WhiteNoise): halaman publik,
> login, dasbor, laporan, matriks tarif, dan file statis semuanya berjalan. Yang **belum** bisa saya uji dari sini
> adalah lingkungan PythonAnywhere itu sendiri, jadi bagian "Jika ada masalah" mungkin Anda perlukan.

## 1. Ambil kode (Bash console)

```bash
git clone https://github.com/Odoly23/TicAportil.git
cd TicAportil
git checkout main            # setelah pull request digabung (atau: claude/great-cori-vadrof untuk mencoba sebelum digabung)
```

Jika repo bersifat private, pakai *personal access token* GitHub sebagai kata sandi saat `git clone`.

## 2. Virtualenv dan paket

Pilih Python 3.10 atau lebih baru (Django 5.2 butuh ≥ 3.10; sesuaikan angka di bawah dengan yang tersedia di tab *Web*):

```bash
mkvirtualenv --python=/usr/bin/python3.12 ticaportil
pip install -r requirements.txt
```

## 3. File `.env` (rahasia, jangan di-commit)

Buat `~/TicAportil/.env`:

```ini
DJANGO_SECRET_KEY=<isi dengan string acak panjang>
TICKET_SIGNING_KEY=<string acak lain; JANGAN diubah setelah ada tiket tercetak>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=USERNAME.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://USERNAME.pythonanywhere.com
DJANGO_SSL_REDIRECT=False          # pengalihan HTTPS dilakukan PythonAnywhere (lihat langkah 6)
DEFAULT_FROM_EMAIL=bilheteira@aportil.gov.tl
REPORT_RECIPIENTS=pengelola@contoh.com
# SMTP (lihat catatan email di bawah):
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
```

Membuat string acak: `python -c "import secrets;print(secrets.token_urlsafe(60))"`.

## 4. Database dan data awal

```bash
cd ~/TicAportil
python manage.py migrate
python manage.py createcachetable          # dipakai untuk pembatasan percobaan login
python manage.py setup_roles               # grup: admin, resepsionista, inspector, operator
python manage.py createsuperuser           # akun admin pertama (otomatis berperan admin)
python manage.py collectstatic --noinput   # WAJIB: tanpa ini semua halaman error 500
```

Data contoh (hanya untuk uji coba, **harga di dalamnya placeholder**): `python manage.py seed_demo --force`.

## 5. Web app (tab *Web*)

1. **Add a new web app** → *Manual configuration* (bukan wizard Django) → pilih versi Python yang sama dengan virtualenv.
2. **Virtualenv**: `/home/USERNAME/.virtualenvs/ticaportil`
3. **Source code** dan **Working directory**: `/home/USERNAME/TicAportil`
4. Buka file **WSGI configuration** dan ganti seluruh isinya dengan:

```python
import os
import sys

path = '/home/USERNAME/TicAportil'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'ticaportil.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

5. **Static files**: tambahkan `URL: /static/` → `Directory: /home/USERNAME/TicAportil/staticfiles`.
   **Jangan** memetakan `/media/` (foto dokumen bersifat privat dan hanya dilayani lewat halaman terproteksi).
6. Aktifkan **Force HTTPS**. HTTPS wajib: kamera pemindai QR dan service worker hanya jalan lewat HTTPS.
7. Tekan **Reload**, lalu buka `https://USERNAME.pythonanywhere.com`.

## 6. Tugas terjadwal (tab *Tasks*)

PythonAnywhere menjalankan tugas dalam **UTC**. Dili = UTC+9, jadi **00:10 Dili = 15:10 UTC hari sebelumnya**.
Tambahkan dua tugas harian:

| Jam (UTC) | Perintah |
|---|---|
| 15:10 | `/home/USERNAME/.virtualenvs/ticaportil/bin/python /home/USERNAME/TicAportil/manage.py send_due_reports` |
| 18:00 | `/home/USERNAME/.virtualenvs/ticaportil/bin/python /home/USERNAME/TicAportil/manage.py purge_documents` |

`send_due_reports` mengirim laporan harian kemarin; tanggal 1 juga laporan bulan lalu; 1 Januari juga laporan tahun lalu.
Aman dijalankan dua kali (laporan yang sudah terkirim dilewati). Akun gratis mungkin hanya boleh satu tugas: dahulukan
`send_due_reports`.

## Catatan penting untuk uji coba

- **SQLite** (bawaan) cukup untuk mencoba. SQLite **tidak mengunci baris**, sehingga perlindungan agar dua loket tidak
  menjual kursi terakhir bersamaan hanya berlaku penuh di PostgreSQL. Jangan dipakai untuk penjualan sungguhan.
  Database ada di `~/TicAportil/db.sqlite3`; unduh berkala sebagai cadangan.
- **Email**: akun gratis PythonAnywhere membatasi koneksi keluar ke daftar situs tertentu, jadi SMTP APORTIL kemungkinan
  tidak terjangkau; Gmail SMTP biasanya diizinkan (periksa dokumentasi PythonAnywhere). Jika email gagal, perubahan jadwal
  dan penjualan tetap tersimpan, kegagalan dicatat di Audit Log (`email_failed`) dan tabel laporan.
- **Link di email** (undangan pengguna / lupa password) memakai `http` atau `https` sesuai permintaan yang diterima. Setelah
  mencoba sekali, pastikan link-nya berawalan `https://`.
- Foto dokumen disimpan di `~/TicAportil/private_media/` dan dihapus otomatis setelah 30 hari oleh `purge_documents`.
- Akun gratis PythonAnywhere perlu **diperpanjang berkala** lewat tombol di tab *Web*, atau aplikasi dinonaktifkan.

## Memperbarui setelah ada versi baru

```bash
cd ~/TicAportil
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py setup_roles
```

Lalu **Reload** di tab *Web*. Jika scanner QR tampak memakai tampilan lama, naikkan `APP_VERSION` di `.env`
(angka bebas, misalnya `2`) sebelum Reload agar cache PWA di HP diperbarui.

## Jika ada masalah

| Gejala | Penyebab / solusi |
|---|---|
| Semua halaman error 500 | `collectstatic` belum dijalankan, atau `.env` tidak terbaca. Lihat *Error log* di tab *Web*. |
| `DisallowedHost` | `DJANGO_ALLOWED_HOSTS` tidak memuat `USERNAME.pythonanywhere.com`. |
| Login: "CSRF verification failed" | `DJANGO_CSRF_TRUSTED_ORIGINS` salah (harus `https://...`). |
| Terlalu banyak pengalihan (redirect loop) | Pastikan `DJANGO_SSL_REDIRECT=False` dan **Force HTTPS** aktif di tab *Web*. |
| CSS/logo tidak tampil | Pemetaan `/static/` salah, atau `collectstatic` belum dijalankan setelah `git pull`. |
| Scanner: kamera tidak mau menyala | Akses lewat `https://`, dan izinkan kamera di browser. |

## Sebelum produksi di server APORTIL

Uji coba ini bukan konfigurasi produksi. Untuk produksi saya sarankan: PostgreSQL (kunci baris), gunicorn + nginx di
belakang HTTPS, cadangan database dan `private_media/` terjadwal, `DJANGO_DEBUG=False`, dan cron seperti di `README.md`.
Panduan lengkapnya saya siapkan setelah server baru dari APORTIL tersedia.
