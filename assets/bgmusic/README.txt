Background Music Folder
=======================

Taruh file audio (MP3, WAV, M4A, OGG, FLAC) di sini.
Setiap kali pipeline berjalan, satu file dipilih secara acak.

Aktifkan di .env:
  BGM_ENABLED=true
  BGM_VOLUME=0.25          (0.0 - 1.0)
  BGM_DUCK_ENABLED=true    (otomatis ducking saat ada suara)
  BGM_DUCK_RATIO=6         (seberapa kuat duck; 2-10)
  BGM_DUCK_THRESHOLD=0.025 (threshold suara yang trigger ducking)

Rekomendasi sumber musik bebas royalti:
  - https://pixabay.com/music/     (filter: lofi / ambient / calm)
  - https://incompetech.com/
  - https://www.bensound.com/
