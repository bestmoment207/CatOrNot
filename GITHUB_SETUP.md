# GitHub Actions Setup Guide — CatCentral

Panduan ini menjelaskan cara menjalankan CatCentral sepenuhnya di GitHub Actions,  
sehingga video ter-upload otomatis 3× sehari **tanpa server**.

---

## Prasyarat

- Akun GitHub (repo bisa private)
- Python 3.11+ di komputer lokal (hanya untuk setup awal)
- Project sudah bisa jalan secara lokal (`python main.py auth` berhasil)

---

## Langkah 1 — Push ke GitHub

```bash
cd CatOrNot
git init
git add .
git commit -m "initial commit"

# Ganti URL berikut dengan repo kamu
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

> **Private repo direkomendasikan** agar kode dan token tidak publik.

---

## Langkah 2 — Encode YouTube Token

Selesaikan OAuth dulu di lokal (kalau belum):

```bash
python main.py auth
```

Lalu encode tokennya:

```bash
python scripts/encode_token.py
```

Salin string panjang yang muncul — ini akan jadi secret `YOUTUBE_TOKEN`.

---

## Langkah 3 — Tambahkan GitHub Secrets

Buka: **GitHub repo → Settings → Secrets and variables → Actions → Secrets**

| Secret name          | Value                              |
|---------------------|------------------------------------|
| `GOOGLE_CLIENT_ID`   | Client ID dari Google Cloud        |
| `GOOGLE_CLIENT_SECRET` | Client Secret dari Google Cloud  |
| `YOUTUBE_TOKEN`      | Output dari `encode_token.py`      |
| `GH_PAT`             | Personal Access Token (lihat bawah)|

### Membuat `GH_PAT` (Personal Access Token)

Token ini digunakan workflow untuk memperbarui `YOUTUBE_TOKEN` secret setelah setiap run  
(agar token OAuth tetap fresh tanpa perlu auth ulang).

1. Buka: **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Klik **Generate new token**
3. Isi:
   - **Token name**: `CatCentral Bot`
   - **Expiration**: 1 year (atau No expiration)
   - **Repository access**: Only select repositories → pilih repo CatCentral
   - **Permissions → Secrets**: Read and write
4. Klik **Generate token** → salin tokennya
5. Tambahkan sebagai secret `GH_PAT` di repo

> Tanpa `GH_PAT`, workflow tetap jalan tapi token tidak di-refresh ke secret.  
> Ini aman selama refresh_token YouTube tidak dicabut (biasanya bertahan sangat lama).

---

## Langkah 4 — Atur GitHub Variables (Opsional)

Buka: **GitHub repo → Settings → Secrets and variables → Actions → Variables**

Variabel ini tidak wajib — workflow punya default values.  
Ubah sesuai kebutuhan:

| Variable name       | Default           | Keterangan                         |
|--------------------|-------------------|------------------------------------|
| `CLIPS_PER_VIDEO`  | `5`               | Jumlah clip per video              |
| `CLIP_DURATION`    | `25`              | Durasi tiap clip (detik)           |
| `WATERMARK_TEXT`   | `@CatCentral`     | Teks watermark                     |
| `TTS_ENABLED`      | `true`            | Aktifkan TTS narasi                |
| `TTS_VOICE`        | `en-US-GuyNeural` | Suara TTS                          |
| `BGM_ENABLED`      | `false`           | Aktifkan background music          |
| `BGM_VOLUME`       | `0.25`            | Volume BGM (0.0–1.0)               |
| `BGM_DUCK_ENABLED` | `true`            | Auto ducking BGM saat ada suara    |
| `DATA_CLEANUP_DAYS`| `3`               | Hapus file lama setelah N hari     |
| `LOG_LEVEL`        | `INFO`            | Level logging                      |

---

## Langkah 5 — Atur Jadwal Upload

Edit file `.github/workflows/upload.yml`, bagian `schedule`:

```yaml
on:
  schedule:
    - cron: '0 2 * * *'    # 09:00 WIB (UTC+7)
    - cron: '0 7 * * *'    # 14:00 WIB
    - cron: '0 12 * * *'   # 19:00 WIB
```

**Format cron:** `menit jam hari bulan hari-minggu`  
Konversi waktu: WIB (UTC+7) → kurangi 7 jam untuk dapat UTC.

| WIB   | UTC   | Cron expression |
|-------|-------|-----------------|
| 07:00 | 00:00 | `0 0 * * *`     |
| 09:00 | 02:00 | `0 2 * * *`     |
| 12:00 | 05:00 | `0 5 * * *`     |
| 14:00 | 07:00 | `0 7 * * *`     |
| 17:00 | 10:00 | `0 10 * * *`    |
| 19:00 | 12:00 | `0 12 * * *`    |
| 21:00 | 14:00 | `0 14 * * *`    |

Setelah edit, commit dan push:

```bash
git add .github/workflows/upload.yml
git commit -m "chore: update cron schedule"
git push
```

---

## Langkah 6 — Background Music (BGM)

Kalau mau aktifkan BGM:

1. Taruh file MP3/WAV/M4A di folder `assets/bgmusic/`
2. Commit file-file tersebut ke repo
3. Set variable `BGM_ENABLED` = `true`

```bash
cp ~/music/lofi_track.mp3 assets/bgmusic/
git add assets/bgmusic/
git commit -m "feat: add bgm tracks"
git push
```

> Sumber musik bebas royalti: [Pixabay Music](https://pixabay.com/music/), [Incompetech](https://incompetech.com/), [Bensound](https://www.bensound.com/)

---

## Cara Trigger Manual

1. Buka: **GitHub repo → Actions → 🐱 CatCentral — Auto Upload**
2. Klik **Run workflow**
3. Pilih opsi:
   - **Dry run = false** → upload sungguhan ke YouTube
   - **Dry run = true** → hanya scrape + edit video, tidak upload

---

## Troubleshooting

### Workflow tidak jalan sesuai jadwal
GitHub Actions schedule terkadang delay 5–15 menit. Kalau lebih dari 1 jam, cek:
- Tab Actions di repo apakah ada error
- Pastikan repo tidak dalam kondisi "inactive" (GitHub menonaktifkan scheduled workflows di repo yang tidak ada aktivitas >60 hari; push commit manual untuk mengaktifkan kembali)

### Error "YOUTUBE_TOKEN secret appears empty or invalid"
Token belum ditambahkan atau salah format. Ulangi langkah 2–3.

### Error "Token file missing — skipping secret update"
Pipeline gagal sebelum upload selesai. Cek log artifact untuk detail error.

### OAuth expired / invalid_grant
Refresh token dicabut (biasanya karena >6 bulan tidak dipakai, atau terlalu banyak token dibuat).  
Ulangi `python main.py auth` di lokal dan encode ulang tokennya.

### Video history hilang (clip berulang)
`data/used_videos.json` tidak ter-commit. Pastikan step "Commit video history" di workflow tidak error,  
dan file tersebut tidak masuk `.gitignore`.

---

## Struktur Secret & Variable

```
GitHub Secrets (Settings → Secrets → Actions)
├── GOOGLE_CLIENT_ID        ← dari Google Cloud Console
├── GOOGLE_CLIENT_SECRET    ← dari Google Cloud Console
├── YOUTUBE_TOKEN           ← output scripts/encode_token.py (base64)
└── GH_PAT                  ← Fine-grained PAT untuk update secret

GitHub Variables (Settings → Variables → Actions)
├── CLIPS_PER_VIDEO, CLIP_DURATION, WATERMARK_TEXT
├── TTS_ENABLED, TTS_VOICE
├── BGM_ENABLED, BGM_VOLUME, BGM_DUCK_ENABLED, BGM_DUCK_RATIO, BGM_DUCK_THRESHOLD
└── DATA_CLEANUP_DAYS, LOG_LEVEL
```

---

## Biaya

GitHub Actions **gratis** untuk:
- Public repo: unlimited menit
- Private repo: 2.000 menit/bulan (tier free)

Estimasi per run: ~5–10 menit (download + render + upload).  
3 run/hari × 30 hari = 90 run × 10 menit = **~900 menit/bulan** → masih dalam batas free tier.

---

*Untuk pertanyaan atau masalah, cek tab Issues di repo.*
