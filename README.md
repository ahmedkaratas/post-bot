# Instagram Post 1080x1350 Auto-Fitter (Bot & Web)

Fotoğrafları ve ekran görüntülerini kalitesini bozmadan **1080 × 1350 px (Instagram 4:5 Dikey)** saf siyah arka planın ortasına otomatik olarak yerleştiren Telegram Botu ve Web Arayüzü.

## 🚀 Özellikler
- **Telegram Botu (@denemekick_bot):** Fotoğraf veya belge olarak atılan görselleri anında 1080x1350 siyah tuvalde ortalayıp hem önizleme hem de kayıpsız PNG olarak geri yollar.
- **Web Arayüzü (index.html):** Canva gerektirmeden tarayıcıda sıfır gecikmeyle sürükle-bırak, zoom ve hizalama imkanı.
- **En Yüksek Kalite:** Pillow `LANCZOS` anti-aliasing enterpolasyonu ile sıfır kalite kaybı.

---

## 🛠️ 7/24 Sunucuda Çalıştırma Yöntemleri

### Yöntem 1: Docker ile (En Pratik)
```bash
# İmajı oluştur
docker build -t igbot .

# 7/24 arka planda çalıştır (sunucu yeniden başlasa bile otomatik açılır)
docker run -d --name igfoto-bot --restart always igbot
```

### Yöntem 2: Python / Virtualenv ile (Linux VPS)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Arka planda 7/24 çalıştırmak için:
nohup python3 bot.py > bot.log 2>&1 &
```

### Yöntem 3: PM2 ile
```bash
pm2 start bot.py --name "igfoto-bot" --interpreter ./venv/bin/python3
pm2 save
pm2 startup
```
