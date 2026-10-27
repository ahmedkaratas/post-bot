# TweetShot — tweet → screenshot

Public bir X / Twitter gönderisini linkinden alıp, referans görselle birebir
oturan temiz bir PNG'ye çeviren yerel araç.

`Time Display`, `Date`, `Show Metrics`, `Show Views`, `Show Media` ayarlarının
**hepsi varsayılan olarak kapalı** gelir; istenirse tek tek açılır.

Referans çıktı: `~/Resimler/Ekran görüntüsü_2026-10-27_03-23-12.png` (540×291).

---

## 1. Tersine mühendislik notları (REA)

Analiz `twittershots.com` üzerinde yapıldı; aşağıdakiler **doğrulanmış
bulgular**, tahmin değil.

| Bulgu | Kanıt |
|---|---|
| Site Next.js (App Router) + Vercel + Cloudflare | HTML içinde `/_next/static/chunks/app/page-*.js`, `x-vercel-cache`, `cf-ray` başlıkları |
| Görsel üretimi sunucu tarafında bir API ile yapılıyor | `api.twittershots.com/api/v1/screenshot/:id` (sayfa bundle'ındaki cURL örneği) |
| API anahtar zorunlu | `GET /api/v1/screenshot/1617979122625712128?format=png` → **401** `{"error":"API key is required..."}` |
| Çıktı formatları | `openapi.yaml`: `format=svg\|png\|html`, `theme=light\|dark`, `returnType=buffer\|url` |
| Ayar isimleri ve davranışı | `/docs/features/customize-tweet-screenshot`: *Timestamp (Date / Datetime / Hidden), Metrics, View count, Footer, 2× ve 4K çıktı, 6 en-boy oranı* |
| Kartın kendi ölçüleri | Referans PNG piksel ölçümü (aşağıdaki tablo) |

Referans görselden ölçülen geometri (540 px tuval, 2× çıktının 1× hâli):

| Öğe | Değer |
|---|---|
| Tuval | 540 geniş, `#FCFCFB`, padding `12px 20px 14px` |
| Kart | 500×266, `#FFFFFF`, 32 px padding, keskin/köşesiz, çok hafif gölge |
| Avatar | 40 px, sağ boşluk 8 px |
| İsim | 15 px bold, satır yüksekliği 20 px |
| Handle | 15 px regular, `#536471`, isimle arası 2–4 px |
| Gövde | 16 px / 24 px, paragraflar arası 16 px |
| Tarih satırı | 14.5 px, `#536471`, üst boşluk 20 px |
| Footer | 13.8 px, `#536471` |
| X logosu | 30 px kutu, sağ üst, dikeyde isimle hizalı |
| Doğrulanmış rozeti | 16 px, `#1d9bf0` |

Yazı tipi X'in kendi **Chirp** fontu (`abs.twimg.com/fonts/v2/chirp-*-web.woff2`),
projede `public/fonts/` altında yerel olarak duruyor.

---

## 2. Mimari

```
tarayıcı (public/)
   │  URL yapıştır → /api/tweet?url=…
   ▼
Express (server.js)
   ├─ lib/tweet.js   → gönderiyi normalize eder
   │    1) api.fxtwitter.com    (metin, yazar, medya, metrik, görüntülenme, alıntı, anket)
   │    2) api.vxtwitter.com    (yedek)
   │    3) cdn.syndication.twimg.com  (anahtarsız, birinci taraf; metrik/medya daha sınırlı)
   │
   ├─ /render/:id    → lib/card.js HTML'i (Chirp fontları, tüm CSS)
   └─ /api/v1/screenshot/:id
         → lib/shot.js: headless Chrome, `#shot` elementini `scale`× DPR ile çeker
         → .cache/<hash>.png (10 dakikalık kova + bellek LRU)
```

Önizleme ile indirilen PNG **aynı URL'den** gelir; yani ekranda gördüğün şey
kaydedilen dosyanın ta kendisidir. HTML'i tarayıcı render ettiği için emoji,
medya, gölge, font ve uzun metin kırılmaları birebir çalışır.

Neden Chrome? Satori/resvg gibi çözücüler CSS'in sadece bir alt kümesini
destekliyor. Chrome ile referans tasarıma piksel hassasiyetinde yaklaşmak ve
medya/emoji desteğini bedava almak mümkün.

### Neden API anahtarı yok?

twittershots.com kendi backend'ini `X-API-KEY` ile koruyor. Bu proje kendi
verisini anahtarsız kaynaklardan çekiyor. `fxtwitter` düşerse otomatik olarak
X'in `syndication` endpoint'ine geçer (`lib/tweet.js`).

---

## 3. Kurulum

Gereksinimler: Node.js 18+ ve Chrome/Chromium.

```bash
cd tweet-shot
npm install
npm start
# → http://localhost:3000
```

Chrome standart yollarda değilse:

```bash
CHROME_PATH=/yol/chrome npm start
```

Ortam değişkenleri:

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PORT` | `3000` | HTTP portu |
| `CHROME_PATH` | otomatik | Chrome/Chromium yolu |
| `SCREENSHOT_TZ` | `Europe/Istanbul` | Tarih/saat dilimi |
| `SCREENSHOT_FOOTER` | `Made with TwitterShots.com` | Kart alt yazısı |
| `TWEET_CACHE_TTL` | `180000` | Gönderi verisi önbelleği (ms) |
| `RENDER_CONCURRENCY` | `3` | Eşzamanlı Chrome sekmesi |

---

## 4. Kullanım

1. Linki yapıştır → **Generate** (yapıştırınca otomatik de çalışır).
2. Sağdaki ayarlarla oyna; önizleme ~200 ms içinde güncellenir.
3. **Download PNG** veya **Copy image**.

Ayarlar `localStorage`'da saklanır; **Reset** hepsini varsayılana döndürür
(hepsi kapalı, footer açık).

### Ayarlar

| Ayar | Query | Varsayılan |
|---|---|---|
| Time Display | `time=1` | kapalı |
| Date | `date=1` | kapalı |
| Show Metrics | `metrics=1` | kapalı |
| Show Views | `views=1` | kapalı |
| Show Media | `media=1` | kapalı |
| Footer | `footer=0` | açık |
| Tema | `theme=dark` | `light` |
| Çözünürlük | `scale=1\|2\|3` | `2` (1080 px genişlik) |

---

## 5. HTTP API

```bash
# PNG
curl -o tweet.png \
  "http://localhost:3000/api/v1/screenshot/1617979122625712128?theme=light&date=1"

# URL ile
curl -o tweet.png \
  "http://localhost:3000/api/v1/screenshot?url=https://x.com/karpathy/status/1617979122625712128&metrics=1"

# İndirme başlığı ile
curl -OJ "http://localhost:3000/api/v1/screenshot/1617979122625712128?download=1"
```

| Route | Açıklama |
|---|---|
| `GET /api/tweet?url=…` | Normalize edilmiş gönderi JSON'u |
| `GET /render/:id?…` | HTML kart (debug) |
| `GET /api/v1/screenshot/:id?…` | PNG (alias: `/api/screenshot/:id`) |
| `GET /health` | Sağlık kontrolü |

Not: Orijinal servis gibi `format=svg` desteklenmiyor; sadece PNG üretilir
(`format` verilirse `png` dışındakiler 400 döner).

---

## 6. Bilinen sınırlamalar

- Sadece **public** gönderiler. Korumalı/silinmiş gönderiler 404 döner.
- Görüntülenme sayısı yalnızca fxtwitter/vxtwitter kaynaklarında var;
  `syndication` yedeğine düşülürse `Show Views` boş kalır.
- Medya videoları statik kapak görseli olarak basılır (video oynatılmaz).
- Önbellek 10 dakikalık kovalarla tutulur; metrikler bu süre içinde eski olabilir.
- Embed edilen medya `pbs.twimg.com` / `video.twimg.com` üzerinden doğrudan yüklenir.

## 7. Dosya yapısı

```
tweet-shot/
├── server.js              # Express rotaları, önbellek, ayar ayrıştırma
├── lib/
│   ├── tweet.js           # URL ayrıştırma + 3 kaynaklı veri çekme/normalize
│   ├── card.js            # HTML/CSS kart (Chirp fontu, ölçülen geometri)
│   └── shot.js            # Chrome pool, element screenshot, disk/bellek cache
├── public/
│   ├── index.html         # editör arayüzü
│   ├── styles.css
│   ├── app.js
│   └── fonts/chirp-*.woff2
└── tools/
    └── render-mock.js     # geliştirici: sabit mock gönderiyi ölçer/render eder
```
