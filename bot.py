#!/usr/bin/env python3
"""
Instagram Post 1080x1350 Auto-Fitter Telegram Bot
Bot Name: igfoto (@denemekick_bot)
Repository: https://github.com/ahmedkaratas/post-bot
Updated by: doguner1 - GitHub senkronizasyon ve baglanti testi basarili!
"""

import os
import io
import re
import time
import signal
import sys
import json
import zipfile
import tempfile
import threading
import subprocess
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageOps
from html import escape
from radar_store import radar_store
from twitter_radar import find_top_new_viral_tweet, find_ai_curated_viral_tweet, find_high_repost_viral_tweet
from tweet_curator_agent import curate_smart_replies_and_caption
from reels_store import reels_store
from reels_radar import find_top_new_viral_reel, download_video_bytes
from twitter_video_radar import find_top_new_viral_twitter_video, download_twitter_video_bytes
from history_store import history_store
from session_manager import session_manager
from dedup_engine import dedup_engine
import photoroom_engine
import history_curator

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1350
TARGET_ASPECT = CANVAS_WIDTH / CANVAS_HEIGHT  # 0.8

import uuid
from datetime import datetime, timezone
import backup_manager

INSTANCE_ID = f"inst_{uuid.uuid4().hex[:8]}"
BOT_START_TIME = time.time()
CURRENT_BOOT_INFO = {"boot_id": "boot_init", "boot_count": 1, "is_wiped_or_first": False}
CONFLICT_TRACKER = {
    "detected": False,
    "last_time": 0,
    "count": 0,
    "last_desc": ""
}

def is_definitive_telegram_error(err_str: str, status_code: int = None) -> bool:
    """Telegram'dan dönen hatanın kesin bir istemci/format hatası olup olmadığını denetler."""
    if status_code in (400, 403, 404):
        return True
    s = str(err_str).lower()
    if any(k in s for k in [
        "bad request",
        "chat not found",
        "wrong file identifier",
        "file too large",
        "entity_mention_invalid",
        "can't parse entities",
        "bot was blocked",
        "user is deactivated"
    ]):
        return True
    return False

running = True

def signal_handler(sig, frame):
    global running
    sig_name = "SIGTERM" if sig == signal.SIGTERM else "SIGINT"
    print(f"\n{sig_name} alındı, bot kapatılıyor...")
    running = False
    try:
        print("📦 Son kapanış yedeği alınıyor...")
        backup_manager.create_and_upload_backup(
            API_URL,
            INSTANCE_ID,
            boot_id=CURRENT_BOOT_INFO.get("boot_id", ""),
            is_sigterm=True,
            force=False
        )
    except Exception as e:
        print(f"Kapanış yedeği hatası: {e}")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Koyeb / Cloud platformları için hafif healthcheck web sunucusu."""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"instagram-post-bot"}')

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_health_server():
    base_port = int(os.getenv("PORT", "8080"))
    for port in [base_port, 8088, 8089]:
        try:
            server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
            print(f"🌐 Cloud Healthcheck sunucusu aktif (Port: {port})")
            server.serve_forever()
            break
        except OSError:
            if "PORT" in os.environ:
                print(f"Uyarı: Cloud PORT {base_port} bağlanamadı.")
                break
            continue
        except Exception as e:
            print(f"Health server hatası: {e}")
            break

def parse_stat_number(val_str):
    """'120k', '1.5m', '120.000', '120,000' veya '5000' gibi metinleri int sayıya çevirir."""
    if not val_str:
        return None
    val = str(val_str).strip().lower()
    multiplier = 1
    if val.endswith("k"):
        multiplier = 1_000
        val = val[:-1]
    elif val.endswith("m"):
        multiplier = 1_000_000
        val = val[:-1]
    elif val.endswith("b"):  # Bin için 'b' yazılabilir
        multiplier = 1_000
        val = val[:-1]
    else:
        # Suffix yoksa; binlik ayırıcıları (. veya ,) temizle (örn: 120.000 -> 120000)
        val = val.replace(".", "").replace(",", "")

    # Suffix varsa ondalık için virgülü noktaya çevir (örn: 1,5k -> 1.5k)
    if multiplier > 1:
        val = val.replace(",", ".")

    try:
        return int(float(val) * multiplier)
    except Exception:
        return None

def parse_post_id(val_str):
    """'#12' veya '12' gibi metinlerden int post ID çıkarır."""
    if not val_str:
        return None
    cleaned = str(val_str).strip().lstrip("#")
    if cleaned.isdigit():
        return int(cleaned)
    return None

def send_chat_action(chat_id, action="upload_photo", message_thread_id=None):
    try:
        payload = {"chat_id": chat_id, "action": action}
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id
        requests.post(f"{API_URL}/sendChatAction", json=payload, timeout=10)
    except Exception:
        pass

def send_message(chat_id, text, reply_to_message_id=None, message_thread_id=None):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id
        resp = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram sendMessage hatası ({resp.status_code}): {resp.text}")
            # Eğer HTML parse hatası varsa, parse_mode olmadan düz metin olarak tekrar gönder
            if "can't parse entities" in resp.text:
                payload.pop("parse_mode", None)
                resp = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
        return resp
    except Exception as e:
        print(f"Mesaj gönderme hatası: {e}")
        return None

def edit_message(chat_id, message_id, text):
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
        resp = requests.post(f"{API_URL}/editMessageText", json=payload, timeout=10)
        if resp.status_code != 200 and "can't parse entities" in resp.text:
            payload.pop("parse_mode", None)
            resp = requests.post(f"{API_URL}/editMessageText", json=payload, timeout=10)
        return resp
    except Exception as e:
        print(f"Mesaj güncelleme hatası: {e}")
        return None

def delete_message(chat_id, message_id):
    try:
        requests.post(f"{API_URL}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=10)
    except Exception:
        pass

def is_video_or_gif(reply):
    """
    Yorumda video veya GIF olup olmadığını denetler.
    Yalnızca düz metin veya resim (fotoğraf) olanlar kabul edilir.
    """
    media = reply.get("media")
    if not media:
        return False
    if media.get("videos") or media.get("external"):
        return True
    for item in media.get("all", []):
        if item.get("type") in ("video", "gif", "animated_gif"):
            return True
    for p in media.get("photos", []):
        if p.get("type") in ("gif", "animated_gif"):
            return True
    return False

def fetch_qualifying_replies(tweet_id, min_likes=100, max_replies=6, main_author="", main_likes=0, min_ratio=0.0):
    """
    Tweetin yorumlarını fxtwitter conversation endpoint'inden çeker.
    Filtreler:
    - Min 100 beğeni (veya ana tweet beğenisine oranlı)
    - Video ve GIF içermeyen
    - Metinden mention, link ve emojiler temizlenince en az 8 karakter kalan
    - Tweet sahibinin kendi yorumu olmayan
    - Reklam veya spam içermeyen
    - Beğeni sayısına göre büyükten küçüğe sıralı en fazla max_replies (varsayılan 6) adet
    """
    from video_curator_agent import detect_ad_or_spam

    effective_min = max(min_likes, int(main_likes * min_ratio)) if min_ratio > 0 and main_likes > 0 else min_likes
    url = f"https://api.fxtwitter.com/2/conversation/{tweet_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ fxtwitter conversation ({tweet_id}) yanıt vermedi: HTTP {resp.status_code}")
            return []
        data = resp.json()
        replies = data.get("replies", [])
        print(f"💬 fxtwitter conversation ({tweet_id}): Toplam {len(replies)} adet yanıt döndü.")

        qualifying = []
        for r in replies:
            # 1. Beğeni kontrolü
            r_likes = r.get("likes") or 0
            if r_likes < effective_min:
                continue

            # 2. Medya format kontrolü (Video/GIF elenir)
            if is_video_or_gif(r):
                continue

            # 3. Tweet sahibinin kendi yanıtı elenir
            r_author = r.get("author", {}).get("screen_name", "")
            if main_author and r_author.lower() == str(main_author).lower():
                continue

            # 4. Metin uzunluğu kontrolü (Mention, URL ve emojiler temizlendikten sonra en az 8 karakter)
            raw_text = r.get("text", "")
            cleaned_text = re.sub(r"@\w+", "", raw_text)
            cleaned_text = re.sub(r"https?://\S+", "", cleaned_text)
            cleaned_text = re.sub(r"[^\w\sğüşıöçĞÜŞİÖÇ]", "", cleaned_text).strip()
            if len(cleaned_text) < 8:
                continue

            # 5. Reklam ve spam kontrolü
            is_ad, _ = detect_ad_or_spam(raw_text)
            if is_ad:
                continue

            # 6. Dil kontrolü (Varsa ve Türkçe değilse ele)
            r_lang = (r.get("lang") or "").strip().lower()
            if r_lang and r_lang != "tr":
                continue

            qualifying.append(r)

        qualifying.sort(key=lambda x: x.get("likes", 0), reverse=True)
        print(f"✅ fxtwitter conversation ({tweet_id}): {len(qualifying)} adet nitelikli yorum filtreden geçti (max: {max_replies}).")
        return qualifying[:max_replies]
    except Exception as e:
        print(f"Yorumları çekme hatası: {e}")
        return []

def process_image(image_bytes):
    """
    Görseli orijinal çözünürlük detaylarını koruyarak 
    1080x1350 saf siyah tuval üzerine tam ortalar ve sığdırır.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        # EXIF yönünü düzelt (Telefondan çekilen dikey/yatay fotoğrafların dönmesini engeller)
        img = ImageOps.exif_transpose(img)
        
        orig_w, orig_h = img.size
        img_aspect = orig_w / orig_h

        # En-boy oranına göre tam sığdır
        if img_aspect > TARGET_ASPECT:
            # Görsel daha yatay -> genişlik tam 1080px yapılır
            new_w = CANVAS_WIDTH
            new_h = int(round(CANVAS_WIDTH / img_aspect))
        else:
            # Görsel daha dikey -> yükseklik tam 1350px yapılır
            new_h = CANVAS_HEIGHT
            new_w = int(round(CANVAS_HEIGHT * img_aspect))

        # En yüksek kalite yeniden örnekleme (Lanczos antialiasing)
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 1080x1350 Saf Siyah Tuval (#000000)
        canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0))

        # Tam merkeze yerleştir
        paste_x = (CANVAS_WIDTH - new_w) // 2
        paste_y = (CANVAS_HEIGHT - new_h) // 2

        # Şeffaflık (PNG) desteği
        if resized.mode in ("RGBA", "LA") or (resized.mode == "P" and "transparency" in resized.info):
            canvas.paste(resized, (paste_x, paste_y), resized.convert("RGBA"))
        else:
            canvas.paste(resized.convert("RGB"), (paste_x, paste_y))

        # Çıktıyı PNG olarak belleğe kaydet (Kayıpsız / Lossless)
        out_buf = io.BytesIO()
        canvas.save(out_buf, format="PNG", optimize=True)
        out_buf.seek(0)
        
        return out_buf, (orig_w, orig_h), (new_w, new_h)

def render_tweet_to_canvas(tweet_input, cli_path):
    """
    tweet-shot CLI ile tweet'in OLED dark ekran görüntüsünü alır ve
    1080x1350 saf siyah tuval üzerine yerleştirir.
    Dönüş: (output_buffer, tweet_info, error_msg)
    """
    temp_dir = tempfile.gettempdir()
    temp_out = os.path.join(temp_dir, f"tweet_{int(time.time() * 1000)}_{os.getpid()}.png")

    try:
        res = subprocess.run(
            ["node", cli_path, str(tweet_input), temp_out],
            capture_output=True,
            text=True,
            timeout=75
        )

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip() or "Bilinmeyen hata"
            try:
                err_json = json.loads(err_msg)
                err_msg = err_json.get("error", err_msg)
            except Exception:
                pass
            return None, None, err_msg

        tweet_info = {}
        try:
            for line in res.stdout.strip().split("\n"):
                if line.strip().startswith("{"):
                    tweet_info = json.loads(line.strip())
                    break
        except Exception:
            pass

        if not os.path.exists(temp_out):
            return None, None, "Tweet ekran görüntüsü dosyası oluşturulamadı."

        with open(temp_out, "rb") as f:
            tweet_png_data = f.read()

        out_buffer, orig_size, new_size = process_image(tweet_png_data)
        return out_buffer, tweet_info, None

    except subprocess.TimeoutExpired:
        return None, None, "Zaman aşımı (75s)"
    except Exception as e:
        return None, None, str(e)
    finally:
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

def handle_tweet_url(chat_id, msg_id, raw_input):
    """
    /url2 komutu ile gelen linki işler:
    1. Ana tweet'i 1080x1350 OLED dark tuvale yerleştirir.
    2. Tweet'in yorumlarını tarar (Min 100 beğeni, videosuz/gifsiz, en çok beğenilen max 4 yorum).
    3. Her yorumu da otomatik olarak /url2 gibi işler ve görsele dönüştürür.
    4. Tüm slaytları kayıpsız dosya formatında alt alta profesyonelce kullanıcıya teslim eder.
    """
    send_chat_action(chat_id, "upload_document")

    # URL ve Tweet ID tespiti (Tekrarlanan komut veya ek parametrelere karşı korumalı)
    url_match = re.search(r"https?://(?:twitter\.com|x\.com|fixupx\.com|vxtwitter\.com|fxtwitter\.com)/([a-zA-Z0-9_]+)/status/(\d+)", raw_input)
    if url_match:
        author_handle = url_match.group(1)
        tweet_id = url_match.group(2)
        tweet_url = f"https://x.com/{author_handle}/status/{tweet_id}"
    else:
        id_match = re.search(r"\b(\d{15,25})\b", raw_input)
        if id_match:
            tweet_id = id_match.group(1)
            tweet_url = f"https://x.com/i/status/{tweet_id}"
        else:
            send_message(
                chat_id,
                "⚠️ Lütfen geçerli bir Twitter / X linki belirtin.\nÖrnek:\n<code>/url2 https://x.com/kullanici/status/1234567890</code>",
                reply_to_message_id=msg_id
            )
            return

    # Durum mesajı başlat
    status_resp = send_message(
        chat_id,
        "⏳ <b>Tweet ve popüler yorumlar taranıyor...</b>\n<i>Lütfen bekleyin, slaytlar hazırlanıyor.</i>",
        reply_to_message_id=msg_id
    )
    status_msg_id = status_resp.json().get("result", {}).get("message_id") if (status_resp and status_resp.status_code == 200) else None

    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots", "tweet-shot", "cli.js")

    try:
        # 1. Ana Tweet'i oluştur
        if status_msg_id:
            edit_message(chat_id, status_msg_id, "🎨 <b>[1/?] Ana Tweet hazırlanıyor...</b>")

        main_buf, main_info, main_err = render_tweet_to_canvas(tweet_url, cli_path)
        if main_err or not main_buf:
            err_text = f"❌ Ana tweet dönüştürülemedi: {main_err}"
            if status_msg_id:
                edit_message(chat_id, status_msg_id, err_text)
            else:
                send_message(chat_id, err_text, reply_to_message_id=msg_id)
            return

        # 2. Yorumları tara ve uygun olanları seç
        if status_msg_id:
            edit_message(chat_id, status_msg_id, "🔍 <b>Yorumlar taranıyor (Min 100 beğeni, videosuz/gifsiz)...</b>")

        qualifying_replies = fetch_qualifying_replies(
            tweet_id,
            min_likes=100,
            max_replies=6,
            main_author=main_info.get("author", "")
        )
        total_slides = 1 + len(qualifying_replies)

        slides_to_send = []
        # Ana Tweet Slaytı
        slides_to_send.append({
            "type": "main",
            "buffer": main_buf,
            "info": main_info,
            "likes": None,
            "author": main_info.get("author", "X"),
            "name": main_info.get("name", "Tweet")
        })

        # 3. Uygun yorumları slaytlara dönüştür
        for idx, rep in enumerate(qualifying_replies, start=2):
            rep_id = rep.get("id")
            rep_author = rep.get("author", {}).get("screen_name", "user")
            rep_likes = rep.get("likes", 0)

            if status_msg_id:
                edit_message(chat_id, status_msg_id, f"🎨 <b>[{idx}/{total_slides}] Popüler Yorum hazırlanıyor...</b> (@{rep_author} - ❤️ {rep_likes:,} beğeni)")

            rep_buf, rep_info, rep_err = render_tweet_to_canvas(rep_id, cli_path)
            if rep_buf and not rep_err:
                slides_to_send.append({
                    "type": "reply",
                    "buffer": rep_buf,
                    "info": rep_info or {},
                    "likes": rep_likes,
                    "author": (rep_info or {}).get("author", rep_author),
                    "name": (rep_info or {}).get("name", rep_author)
                })
            else:
                print(f"Yorum {rep_id} render edilemedi: {rep_err}")

        # Gerçek başarılı toplam slayt sayısı
        actual_total = len(slides_to_send)

        # 4. Tüm slaytları kayıpsız dosya (PNG) olarak alt alta gönder
        if status_msg_id:
            edit_message(chat_id, status_msg_id, f"🚀 <b>Tüm slaytlar ({actual_total} adet) iletiliyor...</b>")

        for i, slide in enumerate(slides_to_send, start=1):
            slide_buf = slide["buffer"]
            author_str = slide["author"]
            name_str = slide["name"]

            if slide["type"] == "main":
                caption = (
                    f"📌 <b>[Slayt {i}/{actual_total}] Ana Tweet</b>\n"
                    f"👤 <b>Yazar:</b> {name_str} (@{author_str})\n"
                    f"📐 <b>Ölçü:</b> 1080 × 1350 px (OLED Siyah Arka Plan)\n"
                    "📁 <i>Kayıpsız HD Orijinal PNG (Instagram'a Hazır)</i>"
                )
                filename = f"01_AnaTweet_{author_str}.png"
            else:
                likes_str = f"{slide['likes']:,}" if slide['likes'] is not None else "100+"
                caption = (
                    f"💬 <b>[Slayt {i}/{actual_total}] Popüler Yorum</b>\n"
                    f"👤 <b>Yazar:</b> {name_str} (@{author_str})\n"
                    f"🔥 <b>Etkileşim:</b> ❤️ {likes_str} Beğeni\n"
                    f"📐 <b>Ölçü:</b> 1080 × 1350 px (OLED Siyah Arka Plan)\n"
                    "📁 <i>Kayıpsız HD Orijinal PNG (Instagram'a Hazır)</i>"
                )
                filename = f"{i:02d}_Yorum_{author_str}_{slide.get('likes', 0)}likes.png"

            slide_buf.seek(0)
            requests.post(
                f"{API_URL}/sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "reply_to_message_id": msg_id
                },
                files={"document": (filename, slide_buf.getvalue(), "image/png")},
                timeout=30
            )

        # 5. Bitiş durum güncellemesi
        if len(qualifying_replies) > 0:
            final_text = (
                f"🎉 <b>Instagram Kaydırmalı Gönderi Paketi Hazır!</b>\n\n"
                f"📊 <b>İçerik:</b> 1 Ana Tweet + {len(slides_to_send) - 1} Popüler Yorum (Toplam {actual_total} slayt)\n"
                f"🎯 <b>Filtre:</b> Min 100 beğeni, videosuz ve gifsiz orijinal yorumlar seçildi.\n"
                f"📲 <i>Instagram'a yüklerken sırasıyla (1, 2, 3...) seçerek tam uyumlu kaydırmalı post paylaşabilirsiniz.</i>"
            )
        else:
            final_text = (
                f"✨ <b>Ana Tweet Başarıyla Gönderildi!</b>\n\n"
                f"ℹ️ <i>Bu tweet altında 100+ beğeni alan (ve videosuz/gifsiz) yorum bulunmadığı için sadece ana tweet iletildi.</i>"
            )

        if status_msg_id:
            edit_message(chat_id, status_msg_id, final_text)

    except Exception as e:
        print(f"Genel işlem hatası: {e}")
        err_msg = f"❌ İşlem sırasında beklenmeyen bir hata oluştu: {str(e)}"
        if status_msg_id:
            edit_message(chat_id, status_msg_id, err_msg)
        else:
            send_message(chat_id, err_msg, reply_to_message_id=msg_id)

def extract_tweet_id(text):
    """Tweet linkinden veya metinden tweet ID'sini ayıklar."""
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith("/img"):
        parts = raw.split(maxsplit=1)
        if len(parts) > 1:
            raw = parts[1].strip()
        else:
            return None
    match = re.search(r'(?:status|statuses|i/status)/(\d{1,25})', raw, re.IGNORECASE)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    loose = re.search(r'status(?:es)?/(\d{1,25})', raw, re.IGNORECASE)
    if loose:
        return loose.group(1)
    return None

def maximize_twitter_image_url(url):
    """Twitter görsel URL'sini en yüksek orijinal çözünürlüğe (?name=orig) ayarlar."""
    if not url:
        return url
    if "pbs.twimg.com" in url:
        if "name=" in url:
            return re.sub(r'name=[a-zA-Z0-9_]+', 'name=orig', url)
        else:
            sep = "&" if "?" in url else "?"
            return f"{url}{sep}name=orig"
    return url

def fetch_tweet_media_info(tweet_id):
    """
    Tweet ID'sine göre tweet içerisindeki fotoğrafları ve yazar bilgilerini çeker.
    Çok katmanlı yedekleme: fxtwitter -> vxtwitter -> node lib/tweet.js (syndication)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    # 1. Kaynak: api.fxtwitter.com
    try:
        resp = requests.get(f"https://api.fxtwitter.com/i/status/{tweet_id}", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tweet = data.get("tweet", {})
            media = tweet.get("media", {})
            raw_photos = media.get("photos", []) or [m for m in media.get("all", []) if m.get("type") == "photo"]
            urls = [maximize_twitter_image_url(p.get("url")) for p in raw_photos if p.get("url")]
            if urls:
                return {
                    "id": tweet_id,
                    "urls": urls,
                    "author": tweet.get("author", {}).get("screen_name", ""),
                    "name": tweet.get("author", {}).get("name", "")
                }
    except Exception as e:
        print(f"fxtwitter fetch hatası: {e}")

    # 2. Kaynak: api.vxtwitter.com
    try:
        resp = requests.get(f"https://api.vxtwitter.com/i/status/{tweet_id}", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            media = data.get("media_extended", []) or []
            urls = [maximize_twitter_image_url(m.get("url")) for m in media if m.get("type") == "image"]
            if urls:
                return {
                    "id": tweet_id,
                    "urls": urls,
                    "author": data.get("user_screen_name", ""),
                    "name": data.get("user_name", "")
                }
    except Exception as e:
        print(f"vxtwitter fetch hatası: {e}")

    # 3. Kaynak: shots/tweet-shot/lib/tweet.js (Node.js & syndication twimg)
    try:
        shots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots", "tweet-shot")
        node_script = f"""
        const {{ fetchTweet }} = require('./lib/tweet');
        fetchTweet('{tweet_id}').then(t => {{
            const photos = (t.media || []).filter(m => m.type === 'photo').map(m => m.url);
            console.log(JSON.stringify({{
                id: t.id,
                urls: photos,
                author: (t.author && t.author.handle) || '',
                name: (t.author && t.author.name) || ''
            }}));
        }}).catch(e => {{
            console.error(JSON.stringify({{ error: e.message }}));
            process.exit(1);
        }});
        """
        res = subprocess.run(
            ["node", "-e", node_script],
            cwd=shots_dir,
            capture_output=True,
            text=True,
            timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            node_data = json.loads(res.stdout.strip())
            urls = [maximize_twitter_image_url(u) for u in node_data.get("urls", []) if u]
            if urls:
                return {
                    "id": tweet_id,
                    "urls": urls,
                    "author": node_data.get("author", ""),
                    "name": node_data.get("name", "")
                }
    except Exception as e:
        print(f"Node fallback fetch hatası: {e}")

    return None

def send_documents_batch(chat_id, files_data, caption=None, reply_to_message_id=None, message_thread_id=None):
    """
    Görselleri Telegram'a toplu dosya (sendMediaGroup veya sendDocument) olarak gönderir.
    files_data: [(file_name, bytes_data), ...]
    """
    total = len(files_data)
    if total == 0:
        return

    # Tek dosya varsa sendDocument ile gönderilir (Telegram kuralları gereği sendMediaGroup en az 2 öğe ister)
    if total == 1:
        fname, fbytes = files_data[0]
        data = {
            "chat_id": chat_id,
            "caption": caption or "",
            "parse_mode": "HTML",
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if message_thread_id:
            data["message_thread_id"] = message_thread_id
        requests.post(
            f"{API_URL}/sendDocument",
            data=data,
            files={"document": (fname, fbytes, "image/png")},
            timeout=40
        )
        return

    # 2 veya daha fazla dosya: 10'arlı gruplara bölerek sendMediaGroup (InputMediaDocument) ile gönder
    chunk_size = 10
    for chunk_idx in range(0, total, chunk_size):
        chunk = files_data[chunk_idx:chunk_idx + chunk_size]

        if len(chunk) == 1:
            fname, fbytes = chunk[0]
            single_p = {"chat_id": chat_id, "parse_mode": "HTML"}
            if message_thread_id:
                single_p["message_thread_id"] = message_thread_id
            requests.post(
                f"{API_URL}/sendDocument",
                data=single_p,
                files={"document": (fname, fbytes, "image/png")},
                timeout=40
            )
            continue

        media_list = []
        files = {}
        for i, (fname, fbytes) in enumerate(chunk):
            attach_name = f"doc_{i}"
            item = {
                "type": "document",
                "media": f"attach://{attach_name}"
            }
            if chunk_idx == 0 and i == 0 and caption:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media_list.append(item)
            files[attach_name] = (fname, fbytes, "image/png")

        payload = {
            "chat_id": chat_id,
            "media": json.dumps(media_list)
        }
        if reply_to_message_id and chunk_idx == 0:
            payload["reply_to_message_id"] = reply_to_message_id
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id

        success = False
        try:
            resp = requests.post(f"{API_URL}/sendMediaGroup", data=payload, files=files, timeout=60)
            res_json = resp.json()
            if res_json.get("ok"):
                success = True
            else:
                print(f"sendMediaGroup yanıtı olumsuz ({res_json.get('description')}), tek tek sendDocument fallback devrede...")
        except Exception as e:
            print(f"sendMediaGroup bağlantı hatası: {e}, tek tek sendDocument fallback devrede...")

        # Eğer sendMediaGroup herhangi bir sebeple başarısız olursa tek tek sendDocument ile gönder
        if not success:
            for i, (fname, fbytes) in enumerate(chunk):
                doc_cap = caption if (chunk_idx == 0 and i == 0) else None
                p = {"chat_id": chat_id, "parse_mode": "HTML"}
                if doc_cap:
                    p["caption"] = doc_cap
                if reply_to_message_id and chunk_idx == 0 and i == 0:
                    p["reply_to_message_id"] = reply_to_message_id
                if message_thread_id:
                    p["message_thread_id"] = message_thread_id
                requests.post(
                    f"{API_URL}/sendDocument",
                    data=p,
                    files={"document": (fname, fbytes, "image/png")},
                    timeout=30
                )

def handle_tweet_images(chat_id, msg_id, text):
    """Eski /img çağrılarını yeni akıllı /ig motoruna yönlendirir."""
    handle_ig_command(chat_id, msg_id, text)

def handle_ig_command(chat_id, msg_id, raw_input, include_comments=True, message_thread_id=None, is_radar=False, post_id=None):
    """
    Akıllı Instagram Şablon Motoru:
    - /ig (veya doğrudan link): Ana tweet + 100+ popüler yorumlar + fotoğraflar (Full paket)
    - /url (veya /url2): Sadece ana tweet + fotoğraflar (Popüler yorumlara bakmaz)
    """
    send_chat_action(chat_id, "upload_document", message_thread_id=message_thread_id)

    # URL ve Tweet ID tespiti
    url_match = re.search(r"https?://(?:twitter\.com|x\.com|fixupx\.com|vxtwitter\.com|fxtwitter\.com)/([a-zA-Z0-9_]+)/status/(\d+)", raw_input)
    if url_match:
        author_handle = url_match.group(1)
        tweet_id = url_match.group(2)
        tweet_url = f"https://x.com/{author_handle}/status/{tweet_id}"
    else:
        id_match = re.search(r"\b(\d{15,25})\b", raw_input)
        if id_match:
            tweet_id = id_match.group(1)
            tweet_url = f"https://x.com/i/status/{tweet_id}"
            author_handle = "x"
        else:
            cmd_name = "/url" if not include_comments else "/ig"
            send_message(
                chat_id,
                f"⚠️ Lütfen geçerli bir Twitter / X linki belirtin.\nÖrnek:\n<code>{cmd_name} https://x.com/kullanici/status/1234567890</code>",
                reply_to_message_id=msg_id,
                message_thread_id=message_thread_id
            )
            return

    # Canlı dinamik durum mesajı (Radar modunda gereksiz kirlilik yaratmaması için kapalı)
    status_msg_id = None
    if not is_radar and msg_id:
        step_total = "4" if include_comments else "3"
        status_resp = send_message(
            chat_id,
            f"⏳ <b>[1/{step_total}] Ana tweet şablonu hazırlanıyor...</b>\n<i>Lütfen bekleyin, slaytlar işleniyor.</i>",
            reply_to_message_id=msg_id,
            message_thread_id=message_thread_id
        )
        status_msg_id = status_resp.json().get("result", {}).get("message_id") if (status_resp and status_resp.status_code == 200) else None

    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots", "tweet-shot", "cli.js")
    slides = []  # list of dicts: {"filename": str, "bytes": bytes, "desc": str}

    try:
        # 1. Aşama: Ana Tweet
        main_buf, main_info, main_err = render_tweet_to_canvas(tweet_url, cli_path)
        if main_err or not main_buf:
            err_text = f"❌ Ana tweet oluşturulamadı: {main_err}"
            if status_msg_id:
                edit_message(chat_id, status_msg_id, err_text)
            else:
                send_message(chat_id, err_text, reply_to_message_id=msg_id, message_thread_id=message_thread_id)
            return

        resolved_handle = (main_info or {}).get("author") or author_handle
        resolved_name = (main_info or {}).get("name") or resolved_handle

        slides.append({
            "filename": f"01_AnaTweet_{resolved_handle}.png",
            "bytes": main_buf.getvalue(),
            "desc": f"Ana Tweet (@{resolved_handle})"
        })

        # 2. Aşama: Popüler Yorumlar (Sadece include_comments=True olduğunda çalışır, /url ile atlanır)
        qualifying_replies = []
        if include_comments:
            if status_msg_id:
                edit_message(chat_id, status_msg_id, "🔍 <b>[2/4] Popüler yorumlar taranıyor (100+ beğeni, videosuz/gifsiz)...</b>")

            qualifying_replies = fetch_qualifying_replies(
            tweet_id,
            min_likes=100,
            max_replies=6,
            main_author=main_info.get("author", "")
        )
            for idx, rep in enumerate(qualifying_replies, start=1):
                rep_id = rep.get("id")
                rep_author = rep.get("author", {}).get("screen_name", "user")
                rep_likes = rep.get("likes", 0)

                if status_msg_id:
                    edit_message(chat_id, status_msg_id, f"🎨 <b>Yorum şablonu hazırlanıyor ({idx}/{len(qualifying_replies)})... (@{rep_author} - ❤️ {rep_likes:,})</b>")

                rep_buf, rep_info, rep_err = render_tweet_to_canvas(rep_id, cli_path)
                if rep_buf and not rep_err:
                    slide_num = len(slides) + 1
                    slides.append({
                        "filename": f"{slide_num:02d}_Yorum_{rep_author}_{rep_likes}likes.png",
                        "bytes": rep_buf.getvalue(),
                        "desc": f"Yorum (@{rep_author} - ❤️ {rep_likes:,})"
                    })
                else:
                    print(f"Yorum {rep_id} render hatası: {rep_err}")

        # 3. Aşama: Tweet içi fotoğraflar (Kaydırmalı Medya)
        step_media = "3/4" if include_comments else "2/3"
        if status_msg_id:
            edit_message(chat_id, status_msg_id, f"🖼️ <b>[{step_media}] Tweet içi fotoğraflar kontrol ediliyor...</b>")

        tweet_media = fetch_tweet_media_info(tweet_id)
        photo_urls = (tweet_media or {}).get("urls", [])
        added_photos = 0

        if len(photo_urls) == 1:
            try:
                single_url = photo_urls[0]
                img_resp = requests.get(single_url, timeout=30)
                if img_resp.status_code == 200:
                    with Image.open(io.BytesIO(img_resp.content)) as p_img:
                        pw, ph = p_img.size
                        p_aspect = pw / ph if ph > 0 else 1.0

                    if p_aspect < 0.95:
                        if status_msg_id:
                            edit_message(chat_id, status_msg_id, "📥 <b>Dikey uzun görsel tam boy slayt olarak hazırlanıyor...</b>")
                        p_buf, _, _ = process_image(img_resp.content)
                        slide_num = len(slides) + 1
                        slides.append({
                            "filename": f"{slide_num:02d}_Foto_1_TamBoy.png",
                            "bytes": p_buf.getvalue(),
                            "desc": "Tam Boy Dikey Görsel"
                        })
                        added_photos += 1
            except Exception as e:
                print(f"Tekil görsel dikey kontrol hatası: {e}")

        elif len(photo_urls) > 1:
            if status_msg_id:
                edit_message(chat_id, status_msg_id, f"📥 <b>{len(photo_urls)} adet kaydırmalı fotoğraf 1080×1350 tuvale yerleştiriliyor...</b>")

            for p_idx, p_url in enumerate(photo_urls, start=1):
                try:
                    img_resp = requests.get(p_url, timeout=30)
                    if img_resp.status_code == 200:
                        p_buf, _, _ = process_image(img_resp.content)
                        slide_num = len(slides) + 1
                        slides.append({
                            "filename": f"{slide_num:02d}_Foto_{p_idx}.png",
                            "bytes": p_buf.getvalue(),
                            "desc": f"Kaydırmalı Fotoğraf {p_idx}"
                        })
                        added_photos += 1
                except Exception as p_err:
                    print(f"Fotoğraf {p_idx} işleme hatası: {p_err}")

        total_slides = len(slides)

        # Post geçmişine kaydet
        if not post_id and not is_radar:
            try:
                post_id = history_store.add_post(
                    source_type="tweet",
                    delivery_mode="manual_ig" if include_comments else "manual_url",
                    link=tweet_url,
                    author=resolved_handle,
                    text=(main_info or {}).get("text", ""),
                    metrics={"likes": (main_info or {}).get("likes", 0)}
                )
            except Exception as hist_err:
                print(f"Manuel post geçmiş kaydetme hatası: {hist_err}")

        post_tag = f" #{post_id}" if post_id else ""

        # 4. Aşama: Tek tıkla indirme ve albüm teslimatı
        step_pkg = "4/4" if include_comments else "3/3"
        if status_msg_id:
            edit_message(chat_id, status_msg_id, f"📦 <b>[{step_pkg}] Tüm şablonlar tek pakette birleştiriliyor ({total_slides} slayt)...</b>")

        # Tek dosya ise (sadece ana tweet)
        if total_slides == 1:
            caption = (
                f"✨ <b>Instagram Post Şablonu Hazır!{post_tag}</b>\n"
                f"👤 <b>Yazar:</b> {resolved_name} (@{resolved_handle})\n"
                f"📐 <b>Ölçü:</b> 1080 × 1350 px (OLED Siyah Arka Plan)\n"
                "📁 <i>Kayıpsız HD Orijinal PNG (Instagram'a Hazır)</i>"
            )
            doc_data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
            }
            if msg_id:
                doc_data["reply_to_message_id"] = msg_id
            if message_thread_id:
                doc_data["message_thread_id"] = message_thread_id

            requests.post(
                f"{API_URL}/sendDocument",
                data=doc_data,
                files={"document": (slides[0]["filename"], slides[0]["bytes"], "image/png")},
                timeout=35
            )
        else:
            # B) Slaytları Telegram içinde tek bir albüm baloncuğunda gönder
            files_data = [(s["filename"], s["bytes"]) for s in slides]
            album_caption = (
                f"✨ <b>Instagram Post Şablonu Hazır!{post_tag}</b>\n"
                f"👤 <b>Yazar:</b> {resolved_name} (@{resolved_handle})\n"
                f"📐 <b>Ölçü:</b> 1080 × 1350 px (OLED Siyah Arka Plan)\n"
                "📁 <i>Kayıpsız HD Orijinal PNG (Instagram'a Hazır)</i>"
            )
            send_documents_batch(chat_id, files_data, caption=album_caption, reply_to_message_id=msg_id, message_thread_id=message_thread_id)

        # Geçici durum mesajını silerek sohbet kirliliğini önle
        if status_msg_id:
            delete_message(chat_id, status_msg_id)

    except Exception as e:
        print(f"İşlem hatası: {e}")
        err_msg = f"❌ İşlem sırasında beklenmeyen bir hata oluştu: {str(e)}"
        if status_msg_id:
            edit_message(chat_id, status_msg_id, err_msg)
        else:
            send_message(chat_id, err_msg, reply_to_message_id=msg_id, message_thread_id=message_thread_id)

def _old_handle_tweet_images(chat_id, msg_id, text):
    """
    /img komutu:
    1. Önce /url2 akışını çalıştırır: Ana tweet şablonu + varsa 100+ beğenili popüler yorumları üretir ve gönderir.
    2. Ardından tweetteki tüm fotoğrafları (kaydırmalı tweet içi resimler) çeker,
       her birini 1080x1350 saf siyah tuval üzerine ortalayarak sığdırır ve
       kayıpsız HD dosya şeklinde toplu mesaj olarak gönderir.
    """
    tweet_id = extract_tweet_id(text)
    if not tweet_id:
        send_message(
            chat_id,
            "⚠️ Lütfen geçerli bir Twitter / X linki belirtin.\nÖrnek:\n<code>/img https://x.com/kullanici/status/1234567890</code>",
            reply_to_message_id=msg_id
        )
        return

    # 1. ADIM: Önce /url2 çalışır (Ana tweet şablonu + varsa 100+ beğenili yorumlar)
    handle_tweet_url(chat_id, msg_id, text)

    # 2. ADIM: Tweet içerisindeki orijinal fotoğrafları işle ve toplu dosya olarak gönder
    status_resp = send_message(
        chat_id,
        "⏳ <b>Tweet içindeki fotoğraflar taranıyor ve hazırlanıyor...</b>",
        reply_to_message_id=msg_id
    )
    status_msg_id = status_resp.json().get("result", {}).get("message_id") if status_resp and status_resp.status_code == 200 else None

    send_chat_action(chat_id, "upload_document")

    try:
        tweet_data = fetch_tweet_media_info(tweet_id)
        if not tweet_data or not tweet_data.get("urls"):
            info_text = "ℹ️ <i>Bu tweette ayrıca gömülü fotoğraf bulunmuyor. Ana tweet şablonu ve yorumlar iletildi.</i>"
            if status_msg_id:
                edit_message(chat_id, status_msg_id, info_text)
            else:
                send_message(chat_id, info_text, reply_to_message_id=msg_id)
            return

        urls = tweet_data["urls"]
        author_str = f"@{tweet_data['author']}" if tweet_data.get("author") else "X / Twitter"
        name_str = tweet_data.get("name", "Tweet")
        total_photos = len(urls)

        if status_msg_id:
            edit_message(chat_id, status_msg_id, f"📥 <b>Tweetteki {total_photos} adet fotoğraf indiriliyor ve 1080×1350 tuvale yerleştiriliyor...</b>")

        processed_files = []
        last_orig_size = (0, 0)
        last_new_size = (0, 0)

        for idx, img_url in enumerate(urls, 1):
            try:
                # Orijinal görseli indir
                img_resp = requests.get(img_url, timeout=30)
                if img_resp.status_code != 200:
                    print(f"Görsel {idx} indirilemedi: HTTP {img_resp.status_code}")
                    continue

                # Normal foto atılmış gibi 1080x1350 Saf Siyah Tuvale Otomatik Sığdır
                output_buffer, orig_size, new_size = process_image(img_resp.content)
                last_orig_size = orig_size
                last_new_size = new_size

                file_name = f"tweet_{tweet_id}_{idx}.png"
                processed_files.append((file_name, output_buffer.getvalue(), orig_size, new_size))
            except Exception as err:
                print(f"Görsel {idx} işleme hatası: {err}")

        if not processed_files:
            err_text = "❌ Tweet fotoğrafları işlenirken bir sorun oluştu."
            if status_msg_id:
                edit_message(chat_id, status_msg_id, err_text)
            else:
                send_message(chat_id, err_text, reply_to_message_id=msg_id)
            return

        if status_msg_id:
            edit_message(chat_id, status_msg_id, f"🚀 <b>{len(processed_files)} adet işlenmiş HD tweet fotoğrafı gönderiliyor...</b>")

        # Caption (Açıklama metni)
        if len(processed_files) > 1:
            caption = (
                f"✨ <b>Tweet İçi Fotoğraflar Hazır! ({len(processed_files)} Görsel)</b>\n"
                f"👤 <b>Yazar:</b> {name_str} ({author_str})\n"
                f"📐 <b>Ölçü:</b> 1080 × 1350 px (Saf Siyah Tuval - 4:5 Dikey)\n"
                "📁 <i>Kayıpsız HD Orijinal PNG Dosyaları (Instagram'a Yüklemeye Hazır)</i>"
            )
        else:
            caption = (
                "✨ <b>Tweet İçi Fotoğraf Hazır!</b>\n"
                f"👤 <b>Yazar:</b> {name_str} ({author_str})\n"
                f"📐 <b>Ölçü:</b> 1080 × 1350 px (Saf Siyah Tuval)\n"
                f"🔍 <b>Orijinal:</b> {last_orig_size[0]}×{last_orig_size[1]} ➔ 🎯 <b>Görsel:</b> {last_new_size[0]}×{last_new_size[1]} (Tam Ortalandı)\n"
                "📁 <i>Kayıpsız HD Orijinal PNG (Instagram'a Yüklemeye Hazır)</i>"
            )

        # files_for_batch: [(file_name, file_bytes), ...]
        files_for_batch = [(f[0], f[1]) for f in processed_files]
        send_documents_batch(chat_id, files_for_batch, caption=caption, reply_to_message_id=msg_id)

        # Durum mesajını başarıyla sonlandır veya güncelle
        if status_msg_id:
            success_summary = (
                f"✅ <b>Tüm Paket Tamamlandı!</b>\n"
                f"1️⃣ Ana tweet şablonu ve popüler yorumlar iletildi.\n"
                f"2️⃣ Tweetteki {len(processed_files)} adet fotoğraf 1080×1350 saf siyah arka planla dosya formatında teslim edildi."
            )
            edit_message(chat_id, status_msg_id, success_summary)

    except Exception as e:
        print(f"/img işlem hatası: {e}")
        err_msg = f"❌ Tweet fotoğrafları işlenirken bir hata oluştu: {str(e)}"
        if status_msg_id:
            edit_message(chat_id, status_msg_id, err_msg)
        else:
            send_message(chat_id, err_msg, reply_to_message_id=msg_id)

def deliver_ai_curated_tweet(chat_id, tweet_dict, ai_eval, thread_id=None, reply_to_id=None):
    """
    AI Küratörü tarafından seçilen viral tweet'i, akıllıca seçilmiş yorumlar ve
    yapay zeka tarafından üretilmiş Instagram caption'ı ile birlikte gönderir.
    """
    try:
        tweet_id = tweet_dict["id"]
        tweet_url = tweet_dict["url"]
        author = tweet_dict.get("author", "X")
        name = tweet_dict.get("name", author)
        likes = tweet_dict.get("likes", 0)
        score = ai_eval.get("score", 8)
        reason = ai_eval.get("reason", "Yapay zeka viral içerik analizi")
        model_used = ai_eval.get("model", "Gemini")

        cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots", "tweet-shot", "cli.js")
        slides = []

        # 1. Ana tweet render
        main_buf, main_info, main_err = render_tweet_to_canvas(tweet_url, cli_path)
        if main_err or not main_buf:
            print(f"AI Tweet ana tweet render hatası: {main_err}")
            return False, main_err

        resolved_handle = (main_info or {}).get("author") or author
        resolved_name = (main_info or {}).get("name") or name

        slides.append({
            "filename": f"01_AI_AnaTweet_{resolved_handle}.png",
            "bytes": main_buf.getvalue(),
            "desc": f"Ana Tweet (@{resolved_handle})"
        })

        # 2. Akıllı Yorum Seçimi (Gemini Curator)
        raw_replies = fetch_qualifying_replies(
            tweet_id,
            min_likes=100,
            max_replies=8,
            main_author=resolved_handle,
            main_likes=likes
        )
        curate_res = curate_smart_replies_and_caption(tweet_dict, raw_replies)
        selected_replies = curate_res.get("selected_replies", [])
        caption_text = curate_res.get("instagram_caption", "Düşünceleriniz neler? Yorumlarda buluşalım! 👇\n\n#kesfet #mizah")

        for s_idx, rep in enumerate(selected_replies, start=1):
            rep_id = rep.get("id")
            rep_author = rep.get("author", {}).get("screen_name", "user")
            rep_likes = rep.get("likes", 0)
            rep_buf, _, rep_err = render_tweet_to_canvas(rep_id, cli_path)
            if rep_buf and not rep_err:
                slide_num = len(slides) + 1
                slides.append({
                    "filename": f"{slide_num:02d}_AI_Yorum_{rep_author}_{rep_likes}likes.png",
                    "bytes": rep_buf.getvalue(),
                    "desc": f"Seçilmiş Yorum (@{rep_author})"
                })

        # 3. Tweet İçi Fotoğraflar (Varsa)
        tweet_media = fetch_tweet_media_info(tweet_id)
        photo_urls = (tweet_media or {}).get("urls", [])
        if len(photo_urls) == 1:
            try:
                img_resp = requests.get(photo_urls[0], timeout=30)
                if img_resp.status_code == 200:
                    with Image.open(io.BytesIO(img_resp.content)) as p_img:
                        pw, ph = p_img.size
                        p_aspect = pw / ph if ph > 0 else 1.0
                    if p_aspect < 0.95:
                        p_buf, _, _ = process_image(img_resp.content)
                        slides.append({
                            "filename": f"{len(slides)+1:02d}_AI_Foto_TamBoy.png",
                            "bytes": p_buf.getvalue(),
                            "desc": "Tam Boy Görsel"
                        })
            except Exception as e:
                print(f"AI Görsel işleme hatası: {e}")
        elif len(photo_urls) > 1:
            for p_idx, p_url in enumerate(photo_urls, start=1):
                try:
                    img_resp = requests.get(p_url, timeout=30)
                    if img_resp.status_code == 200:
                        p_buf, _, _ = process_image(img_resp.content)
                        slides.append({
                            "filename": f"{len(slides)+1:02d}_AI_Foto_{p_idx}.png",
                            "bytes": p_buf.getvalue(),
                            "desc": f"Fotoğraf {p_idx}"
                        })
                except Exception as p_err:
                    print(f"AI Fotoğraf {p_idx} hatası: {p_err}")

        # 4. Post Geçmişine Kaydet (#ID)
        post_id = None
        try:
            post_id = history_store.add_post(
                source_type="tweet",
                delivery_mode="ai_curator",
                link=tweet_url,
                author=resolved_handle,
                text=tweet_dict.get("text", ""),
                metrics={
                    "likes": likes,
                    "retweets": tweet_dict.get("retweets", 0),
                    "replies": tweet_dict.get("replies", 0),
                    "quotes": tweet_dict.get("quotes", 0),
                    "bookmarks": tweet_dict.get("bookmarks", 0),
                    "views": tweet_dict.get("views", 0),
                },
                ai_score=score,
                ai_reason=reason,
                ai_model=model_used,
                selected_replies=selected_replies,
                caption=caption_text
            )
        except Exception as hist_err:
            print(f"AI Tweet geçmiş kaydetme hatası: {hist_err}")

        post_tag = f" #{post_id}" if post_id else ""

        # 5. Telegram Sade Başlık Mesajı
        ai_header = (
            f"🤖 <b>Ai Seçimi{post_tag}</b>\n"
            f"🔗 <b>Orijinal link:</b> {tweet_url}"
        )
        send_message(chat_id, ai_header, reply_to_message_id=reply_to_id, message_thread_id=thread_id)

        # Anons yapıldığı anda kesin gönderildi (CONFIRMED) olarak kütükle
        dedup_engine.confirm(tweet_id, url=tweet_url, author=resolved_handle, text=tweet_dict.get("text", ""))
        radar_store.mark_sent(f"ai_{tweet_id}", author=resolved_handle, likes=likes)
        radar_store.mark_sent(tweet_id, author=resolved_handle, likes=likes)
        backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))

        # 6. Slaytları İlet
        album_caption = f"🤖 <b>AI Seçimli Albüm{post_tag} ({len(slides)} Slayt):</b>\n@{resolved_handle} • Skor: {score}/10"
        if len(slides) == 1:
            doc_data = {
                "chat_id": chat_id,
                "caption": album_caption,
                "parse_mode": "HTML",
            }
            if reply_to_id:
                doc_data["reply_to_message_id"] = reply_to_id
            if thread_id:
                doc_data["message_thread_id"] = thread_id

            requests.post(
                f"{API_URL}/sendDocument",
                data=doc_data,
                files={"document": (slides[0]["filename"], slides[0]["bytes"], "image/png")},
                timeout=45
            )
        else:
            files_data = [(s["filename"], s["bytes"]) for s in slides]
            send_documents_batch(
                chat_id,
                files_data,
                caption=album_caption,
                reply_to_message_id=reply_to_id,
                message_thread_id=thread_id
            )

        # İnce ayraç
        send_message(chat_id, "----------------------------------------", message_thread_id=thread_id)
        return True, None
    except Exception as e:
        is_def = is_definitive_telegram_error(str(e))
        dedup_engine.abort(
            tweet_dict.get("id"),
            url=tweet_dict.get("url"),
            author=resolved_handle if 'resolved_handle' in locals() else "",
            text=tweet_dict.get("text", ""),
            is_definitive_error=is_def
        )
        if is_def and 'post_id' in locals() and post_id is not None:
            try:
                history_store.delete_post(post_id)
            except Exception:
                pass
        print(f"AI Tweet teslimat hatası: {e}")
        return False, str(e)

def deliver_high_repost_radar_single(chat_id, thread_id=None, reply_to_id=None):
    """Sadece yüksek repost almış viral tweeti bulup gönderir (/repost_now)."""
    cfg = radar_store.get_config()
    min_faves = cfg.get("min_faves", 3000)
    repost_tweet, rp_total, rp_stats, rp_err = find_high_repost_viral_tweet(min_faves=min_faves)
    if not repost_tweet:
        if reply_to_id:
            send_message(
                chat_id,
                f"⚠️ <b>Yüksek Repost Radarı:</b> {rp_err or 'Yeni yüksek repost tweet bulunamadı.'}",
                reply_to_message_id=reply_to_id,
                message_thread_id=thread_id
            )
        return False, rp_err

    rp_id = repost_tweet["id"]
    rp_url = repost_tweet["url"]
    rp_author = repost_tweet.get("author", "X")
    rp_likes = repost_tweet.get("likes", 0)
    rp_retweets = int(repost_tweet.get("retweets") or 0)
    rp_quotes = int(repost_tweet.get("quotes") or 0)
    rp_total_shares = rp_retweets + rp_quotes
    rp_rate_pct = rp_stats.get("repost_rate_pct", 0) if rp_stats else 0
    rp_mult = rp_stats.get("multiplier_vs_avg", 1) if rp_stats else 1

    post_id = None
    try:
        post_id = history_store.add_post(
            source_type="tweet",
            delivery_mode="high_repost",
            link=rp_url,
            author=rp_author,
            text=repost_tweet.get("text", ""),
            metrics={
                "likes": rp_likes,
                "retweets": rp_retweets,
                "quotes": rp_quotes,
                "total_reposts": rp_total_shares,
                "repost_rate_pct": rp_rate_pct,
                "views": repost_tweet.get("views", 0)
            }
        )
    except Exception as hist_err:
        print(f"Yüksek repost tweet geçmiş kaydetme hatası: {hist_err}")

    post_tag = f" #{post_id}" if post_id else ""
    mult_txt = f"\n📊 <i>Diğer tweetlere göre {rp_mult} kat daha fazla repost yapıldı!</i>" if rp_mult > 1.2 else ""
    rp_header = (
        f"🔁 <b>Yüksek Repost Seçimi{post_tag}</b>\n"
        f"❤️ <b>Beğeni:</b> {rp_likes:,} • 🔁 <b>Repost:</b> {rp_total_shares:,} (Yayılım: %{rp_rate_pct})"
        f"{mult_txt}\n"
        f"🔗 <b>Orijinal link:</b> {rp_url}"
    )
    send_message(chat_id, rp_header, reply_to_message_id=reply_to_id, message_thread_id=thread_id)
    dedup_engine.confirm(rp_id, url=rp_url, author=rp_author, text=repost_tweet.get("text", ""))
    radar_store.mark_sent(f"rp_{rp_id}", author=rp_author, likes=rp_likes)
    radar_store.mark_sent(rp_id, author=rp_author, likes=rp_likes)
    backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))

    handle_ig_command(
        chat_id=chat_id,
        msg_id=None,
        raw_input=rp_url,
        include_comments=True,
        message_thread_id=thread_id,
        is_radar=True,
        post_id=post_id
    )
    send_message(chat_id, "----------------------------------------", message_thread_id=thread_id)
    return True, None

def trigger_radar_delivery(chat_id, thread_id=None, reply_to_id=None):
    """
    Hedef odaya yeni viral tweetleri 3'lü A/B test formatında teslim eder:
    1. Paket: Standart Radar (En yüksek beğenili tweet + 100+ beğenili yorumlar)
    2. Paket: AI Küratör Radarı (Gemini analizli en esprili/viral tweet + akıllı yorumlar + hazır caption)
    3. Paket: Yüksek Repost / Viral Yayılım Radarı (Yüksek beğeni + diğer tweetlere göre yüksek repost)
    """
    try:
        cfg = radar_store.get_config()
        min_faves = cfg.get("min_faves", 5000)

        std_sent = False
        ai_sent = False
        repost_sent = False
        top_std_id = None
        top_ai_id = None

        # 1. STANDART SEÇİM (En yüksek beğeni alan)
        top_tweet, total_found, err = find_top_new_viral_tweet(min_faves=min_faves)
        if top_tweet:
            top_std_id = top_tweet["id"]
            tweet_url = top_tweet["url"]
            author = top_tweet.get("author", "X")
            name = top_tweet.get("name", author)
            likes = top_tweet.get("likes", 0)

            post_id = None
            try:
                post_id = history_store.add_post(
                    source_type="tweet",
                    delivery_mode="standard",
                    link=tweet_url,
                    author=author,
                    text=top_tweet.get("text", ""),
                    metrics={
                        "likes": likes,
                        "retweets": top_tweet.get("retweets", 0),
                        "replies": top_tweet.get("replies", 0),
                        "quotes": top_tweet.get("quotes", 0),
                        "bookmarks": top_tweet.get("bookmarks", 0),
                        "views": top_tweet.get("views", 0),
                    }
                )
            except Exception as hist_err:
                print(f"Standart tweet geçmiş kaydetme hatası: {hist_err}")

            post_tag = f" #{post_id}" if post_id else ""
            header_text = (
                f"📌 <b>Viral Tweet{post_tag}</b>\n"
                f"🔗 <b>Orijinal link:</b> {tweet_url}"
            )
            send_message(chat_id, header_text, reply_to_message_id=reply_to_id, message_thread_id=thread_id)
            dedup_engine.confirm(top_std_id, url=tweet_url, author=author, text=top_tweet.get("text", ""))
            radar_store.mark_sent(top_std_id, author=author, likes=likes)
            backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))

            handle_ig_command(
                chat_id=chat_id,
                msg_id=None,
                raw_input=tweet_url,
                include_comments=True,
                message_thread_id=thread_id,
                is_radar=True,
                post_id=post_id
            )
            # İnce ayraç
            send_message(chat_id, "----------------------------------------", message_thread_id=thread_id)
            std_sent = True
        else:
            print(f"Standart radar sonucu: {err or 'Yeni standart viral tweet bulunamadı.'}")

        # 2. AI KÜRATÖR SEÇİMİ (Gemini Destekli A/B Paketi)
        ai_tweet, ai_total, ai_eval, ai_err = find_ai_curated_viral_tweet(
            min_faves=min_faves,
            exclude_id=top_std_id
        )
        if ai_tweet:
            top_ai_id = ai_tweet.get("id")
            ok, a_err = deliver_ai_curated_tweet(chat_id, ai_tweet, ai_eval or {}, thread_id=thread_id, reply_to_id=reply_to_id)
            if ok:
                ai_sent = True
            else:
                print(f"AI Tweet gönderim hatası: {a_err}")
        else:
            print(f"AI radar sonucu: {ai_err or 'Yeni AI viral tweet bulunamadı.'}")

        # 3. YÜKSEK REPOST & VİRAL YAYILIM SEÇİMİ (Kullanıcı Talebi 3. Sinyal)
        repost_tweet, rp_total, rp_stats, rp_err = find_high_repost_viral_tweet(
            min_faves=min_faves,
            exclude_ids=[top_std_id, top_ai_id]
        )
        if repost_tweet:
            rp_id = repost_tweet["id"]
            rp_url = repost_tweet["url"]
            rp_author = repost_tweet.get("author", "X")
            rp_likes = repost_tweet.get("likes", 0)
            rp_retweets = int(repost_tweet.get("retweets") or 0)
            rp_quotes = int(repost_tweet.get("quotes") or 0)
            rp_total_shares = rp_retweets + rp_quotes
            rp_rate_pct = rp_stats.get("repost_rate_pct", 0) if rp_stats else 0
            rp_mult = rp_stats.get("multiplier_vs_avg", 1) if rp_stats else 1

            post_id = None
            try:
                post_id = history_store.add_post(
                    source_type="tweet",
                    delivery_mode="high_repost",
                    link=rp_url,
                    author=rp_author,
                    text=repost_tweet.get("text", ""),
                    metrics={
                        "likes": rp_likes,
                        "retweets": rp_retweets,
                        "quotes": rp_quotes,
                        "total_reposts": rp_total_shares,
                        "repost_rate_pct": rp_rate_pct,
                        "views": repost_tweet.get("views", 0)
                    }
                )
            except Exception as hist_err:
                print(f"Yüksek repost tweet geçmiş kaydetme hatası: {hist_err}")

            post_tag = f" #{post_id}" if post_id else ""
            mult_txt = f"\n📊 <i>Diğer tweetlere göre {rp_mult} kat daha fazla repost yapıldı!</i>" if rp_mult > 1.2 else ""
            rp_header = (
                f"🔁 <b>Yüksek Repost Seçimi{post_tag}</b>\n"
                f"❤️ <b>Beğeni:</b> {rp_likes:,} • 🔁 <b>Repost:</b> {rp_total_shares:,} (Yayılım: %{rp_rate_pct})"
                f"{mult_txt}\n"
                f"🔗 <b>Orijinal link:</b> {rp_url}"
            )
            send_message(chat_id, rp_header, reply_to_message_id=reply_to_id, message_thread_id=thread_id)
            dedup_engine.confirm(rp_id, url=rp_url, author=rp_author, text=repost_tweet.get("text", ""))
            radar_store.mark_sent(f"rp_{rp_id}", author=rp_author, likes=rp_likes)
            radar_store.mark_sent(rp_id, author=rp_author, likes=rp_likes)
            backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))

            handle_ig_command(
                chat_id=chat_id,
                msg_id=None,
                raw_input=rp_url,
                include_comments=True,
                message_thread_id=thread_id,
                is_radar=True,
                post_id=post_id
            )
            send_message(chat_id, "----------------------------------------", message_thread_id=thread_id)
            repost_sent = True
        else:
            print(f"Yüksek repost radar sonucu: {rp_err or 'Yeni yüksek repost tweet bulunamadı.'}")

        # Eğer üçü de bulunamadıysa ve kullanıcı manuel tetiklediyse bildirim gönder
        if not std_sent and not ai_sent and not repost_sent and reply_to_id is not None:
            err_msg = f"⚠️ <b>Radar Bildirimi:</b> Kriterlere uyan yeni bir viral tweet bulunamadı.\n(Standart: {err or 'Yok'}, AI: {ai_err or 'Yok'}, Repost: {rp_err or 'Yok'})"
            send_message(chat_id, err_msg, reply_to_message_id=reply_to_id, message_thread_id=thread_id)

        return (std_sent or ai_sent or repost_sent)

    except Exception as e:
        print(f"Radar genel teslimat hatası: {e}")
        if reply_to_id is not None:
            send_message(
                chat_id,
                f"❌ <b>Radar Teslimat Hatası:</b> {str(e)}",
                reply_to_message_id=reply_to_id,
                message_thread_id=thread_id
            )
        return False

def run_radar_scheduler():
    """
    Arka planda çalışan periyodik viral tweet radar zamanlayıcısı.
    """
    print("🛰️ Viral Tweet Radarı zamanlayıcısı aktif.")
    while running:
        try:
            cfg = radar_store.get_config()
            if cfg.get("is_active") and cfg.get("target_chat_id"):
                interval_secs = cfg.get("interval_minutes", 120) * 60
                last_run = cfg.get("last_run_timestamp", 0)
                now = int(time.time())

                if now - last_run >= interval_secs:
                    print(f"🛰️ Otomatik Radar tetiklendi (Chat: {cfg['target_chat_id']}, Thread: {cfg['target_thread_id']})...")
                    delivered = trigger_radar_delivery(cfg["target_chat_id"], cfg["target_thread_id"])
                    if delivered:
                        radar_store.touch_last_run()
                    else:
                        print("🛰️ Bu turda yeni viral tweet bulunamadı veya gönderilemedi. 5 dakika sonra tekrar denenecek.")
                        radar_store.touch_last_run(backoff_seconds=300)
        except Exception as e:
            print(f"Radar zamanlayıcı hatası: {e}")

        # Her 30 saniyede bir kontrol et
        time.sleep(30)

def deliver_instagram_reel(chat_id, thread_id=None, reply_to_id=None):
    """Instagram Reels akışından popüler videoyu bulup MP4 olarak Telegram'a gönderir."""
    try:
        cfg = reels_store.get_config()
        min_plays = cfg.get("min_plays", 50000)
        min_likes = cfg.get("min_likes", 2000)
        max_age_hours = cfg.get("max_age_hours", 72)

        top_reel, total_found, err = find_top_new_viral_reel(
            min_plays=min_plays,
            min_likes=min_likes,
            max_age_hours=max_age_hours
        )
        if err or not top_reel:
            return False, err or "Yeni viral Instagram Reels bulunamadı."

        code = top_reel["code"]
        username = top_reel["username"]
        full_name = top_reel.get("full_name", username)
        plays = top_reel.get("plays", 0)
        likes = top_reel.get("likes", 0)
        reel_url = top_reel["url"]
        caption_raw = top_reel.get("caption", "").strip()

        send_chat_action(chat_id, "upload_video", message_thread_id=thread_id)

        video_bytes, v_err = download_video_bytes(top_reel["video_url"])
        if v_err or not video_bytes:
            return False, f"Instagram video indirme hatası: {v_err}"

        clean_caption = (caption_raw[:300] + "...") if len(caption_raw) > 300 else caption_raw
        clean_cap_escaped = escape(clean_caption) if clean_caption else "<i>(Açıklama yok)</i>"

        post_id = None
        try:
            post_id = history_store.add_post(
                source_type="instagram_reel",
                delivery_mode="reels",
                link=reel_url,
                author=username,
                text=caption_raw,
                metrics={
                    "plays": plays,
                    "likes": likes
                }
            )
        except Exception as hist_err:
            print(f"Reels geçmiş kaydetme hatası: {hist_err}")

        post_tag = f" #{post_id}" if post_id else ""
        caption = (
            f"🎬 <b>[Instagram] Yeni Viral Reels!{post_tag}</b>\n\n"
            f"👤 <b>Yazar:</b> @{username} ({escape(full_name)})\n"
            f"🔥 <b>İzlenme:</b> {plays:,}\n"
            f"❤️ <b>Beğeni:</b> {likes:,}\n"
            f"🔗 <b>Reels Linki:</b> {reel_url}\n\n"
            f"📝 <b>Açıklama:</b>\n<i>{clean_cap_escaped}</i>"
        )

        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "supports_streaming": True
        }
        if top_reel.get("width") and top_reel.get("height"):
            payload["width"] = int(top_reel["width"])
            payload["height"] = int(top_reel["height"])
        if reply_to_id:
            payload["reply_to_message_id"] = reply_to_id
        if thread_id:
            payload["message_thread_id"] = thread_id

        video_filename = f"ig_reel_{code}_{username}.mp4"
        resp = None
        try:
            resp = requests.post(
                f"{API_URL}/sendVideo",
                data=payload,
                files={"video": (video_filename, video_bytes, "video/mp4")},
                timeout=90
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
            print(f"⚠️ Reels gönderme zaman aşımı/bağlantı hatası: {net_err}")
            # Telegram videoyu yayınlamış olabilir; kilidi KORU, post_history'den silme!
            dedup_engine.abort(code, url=reel_url, author=username, text=caption_raw, is_definitive_error=False)
            return False, f"Telegram video gönderme zaman aşımı (90s): {net_err}"

        if resp and resp.status_code == 200:
            dedup_engine.confirm(code, url=reel_url, author=username, text=caption_raw)
            reels_store.mark_sent(code, username=username, plays=plays, likes=likes)
            reels_store.mark_sent(f"ig_{code}", username=username, plays=plays, likes=likes)
            backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))
            return True, None
        else:
            if resp and "can't parse entities" in resp.text:
                payload.pop("parse_mode", None)
                payload["caption"] = f"🎬 [Instagram] Viral Reels: @{username}\nİzlenme: {plays:,}\nBeğeni: {likes:,}\n{reel_url}"
                try:
                    resp2 = requests.post(f"{API_URL}/sendVideo", data=payload, files={"video": (video_filename, video_bytes, "video/mp4")}, timeout=90)
                    if resp2.status_code == 200:
                        dedup_engine.confirm(code, url=reel_url, author=username, text=caption_raw)
                        reels_store.mark_sent(code, username=username, plays=plays, likes=likes)
                        backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))
                        return True, None
                except Exception:
                    pass

            is_def = is_definitive_telegram_error(resp.text if resp else "", resp.status_code if resp else None)
            dedup_engine.abort(code, url=reel_url, author=username, text=caption_raw, is_definitive_error=is_def)
            if is_def and post_id:
                try:
                    history_store.delete_post(post_id)
                except Exception:
                    pass
            err_msg = resp.text[:100] if resp else "Bilinmeyen hata"
            return False, f"Telegram video gönderme hatası: {err_msg}"
    except Exception as e:
        is_def = is_definitive_telegram_error(str(e))
        c_code = top_reel.get("code") if 'top_reel' in locals() and top_reel else None
        c_url = top_reel.get("url") if 'top_reel' in locals() and top_reel else None
        c_auth = top_reel.get("username", "") if 'top_reel' in locals() and top_reel else ""
        c_text = top_reel.get("caption", "") if 'top_reel' in locals() and top_reel else ""
        dedup_engine.abort(c_code, url=c_url, author=c_auth, text=c_text, is_definitive_error=is_def)
        if is_def and 'post_id' in locals() and post_id:
            try:
                history_store.delete_post(post_id)
            except Exception:
                pass
        return False, str(e)

def deliver_twitter_video(chat_id, thread_id=None, reply_to_id=None):
    """Twitter/X üzerinden popüler videoyu bulup MP4 olarak Telegram'a gönderir."""
    try:
        cfg = reels_store.get_config()
        min_likes = max(1000, cfg.get("min_likes", 3000))

        top_video, total_found, err = find_top_new_viral_twitter_video(min_faves=min_likes)
        if err or not top_video:
            return False, err or "Yeni viral Twitter videosu bulunamadı."

        tweet_id = top_video["id"]
        author = top_video["author"]
        name = top_video.get("name", author)
        likes = top_video.get("likes", 0)
        retweets = top_video.get("retweets", 0)
        views = top_video.get("views", 0)
        tweet_url = top_video["url"]
        text_raw = top_video.get("text", "").strip()

        send_chat_action(chat_id, "upload_video", message_thread_id=thread_id)

        video_bytes, v_err = download_twitter_video_bytes(top_video["video_url"])
        if v_err or not video_bytes:
            return False, f"Twitter video indirme hatası: {v_err}"

        clean_text = (text_raw[:300] + "...") if len(text_raw) > 300 else text_raw
        clean_text_escaped = escape(clean_text) if clean_text else "<i>(Metin yok)</i>"

        views_str = f"👁️ <b>Görüntülenme:</b> {views:,}\n" if views else ""

        post_id = None
        try:
            post_id = history_store.add_post(
                source_type="twitter_video",
                delivery_mode="twitter_video",
                link=tweet_url,
                author=author,
                text=text_raw,
                metrics={
                    "likes": likes,
                    "retweets": retweets,
                    "views": views
                }
            )
        except Exception as hist_err:
            print(f"Twitter video geçmiş kaydetme hatası: {hist_err}")

        post_tag = f" #{post_id}" if post_id else ""
        caption = (
            f"🐦 <b>[Twitter / X] Yeni Viral Video!{post_tag}</b>\n\n"
            f"👤 <b>Yazar:</b> @{author} ({escape(name)})\n"
            f"❤️ <b>Beğeni:</b> {likes:,}\n"
            f"🔁 <b>Retweet:</b> {retweets:,}\n"
            + views_str
            + f"🔗 <b>X Linki:</b> {tweet_url}\n\n"
            f"📝 <b>Tweet:</b>\n<i>{clean_text_escaped}</i>"
        )

        payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "supports_streaming": True
        }
        if top_video.get("width") and top_video.get("height"):
            payload["width"] = int(top_video["width"])
            payload["height"] = int(top_video["height"])
        if reply_to_id:
            payload["reply_to_message_id"] = reply_to_id
        if thread_id:
            payload["message_thread_id"] = thread_id

        video_filename = f"x_video_{tweet_id}_{author}.mp4"
        resp = None
        try:
            resp = requests.post(
                f"{API_URL}/sendVideo",
                data=payload,
                files={"video": (video_filename, video_bytes, "video/mp4")},
                timeout=90
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
            print(f"⚠️ Twitter video gönderme zaman aşımı/bağlantı hatası: {net_err}")
            # Telegram videoyu yayınlamış olabilir; kilidi KORU, post_history'den silme!
            dedup_engine.abort(tweet_id, url=tweet_url, author=author, text=text_raw, is_definitive_error=False)
            return False, f"Telegram video gönderme zaman aşımı (90s): {net_err}"

        if resp and resp.status_code == 200:
            dedup_engine.confirm(tweet_id, url=tweet_url, author=author, text=text_raw)
            reels_store.mark_sent(f"x_{tweet_id}", username=author, plays=views, likes=likes)
            reels_store.mark_sent(tweet_id, username=author, plays=views, likes=likes)
            backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))
            return True, None
        else:
            if resp and "can't parse entities" in resp.text:
                payload.pop("parse_mode", None)
                payload["caption"] = f"🐦 [Twitter/X] Viral Video: @{author}\nBeğeni: {likes:,}\n{tweet_url}"
                try:
                    resp2 = requests.post(f"{API_URL}/sendVideo", data=payload, files={"video": (video_filename, video_bytes, "video/mp4")}, timeout=90)
                    if resp2.status_code == 200:
                        dedup_engine.confirm(tweet_id, url=tweet_url, author=author, text=text_raw)
                        reels_store.mark_sent(f"x_{tweet_id}", username=author, plays=views, likes=likes)
                        backup_manager.notify_data_changed(API_URL, INSTANCE_ID, boot_id=CURRENT_BOOT_INFO.get("boot_id", ""))
                        return True, None
                except Exception:
                    pass

            is_def = is_definitive_telegram_error(resp.text if resp else "", resp.status_code if resp else None)
            dedup_engine.abort(tweet_id, url=tweet_url, author=author, text=text_raw, is_definitive_error=is_def)
            if is_def and post_id:
                try:
                    history_store.delete_post(post_id)
                except Exception:
                    pass
            err_msg = resp.text[:100] if resp else "Bilinmeyen hata"
            return False, f"Telegram video gönderme hatası: {err_msg}"
    except Exception as e:
        is_def = is_definitive_telegram_error(str(e))
        v_id = top_video.get("id") if 'top_video' in locals() and top_video else None
        v_url = top_video.get("url") if 'top_video' in locals() and top_video else None
        v_auth = top_video.get("author", "") if 'top_video' in locals() and top_video else ""
        v_text = top_video.get("text", "") if 'top_video' in locals() and top_video else ""
        dedup_engine.abort(v_id, url=v_url, author=v_auth, text=v_text, is_definitive_error=is_def)
        if is_def and 'post_id' in locals() and post_id:
            try:
                history_store.delete_post(post_id)
            except Exception:
                pass
        return False, str(e)

def trigger_reels_delivery(chat_id, thread_id=None, reply_to_id=None):
    """
    Hedef odaya hem Instagram'dan hem de Twitter'dan en popüler yeni viral videoları MP4 olarak teslim eder.
    """
    ig_ok, ig_err = deliver_instagram_reel(chat_id, thread_id, reply_to_id=reply_to_id)
    x_ok, x_err = deliver_twitter_video(chat_id, thread_id, reply_to_id=reply_to_id)

    if not ig_ok and not x_ok:
        print(f"🎬 Otomatik Reels Radarı Sonucu: Instagram={ig_err}, Twitter={x_err}")
        if reply_to_id is not None:
            err_msg = (
                "⚠️ <b>Viral Video Radarı:</b>\n"
                f"• 📸 Instagram: {ig_err}\n"
                f"• 🐦 Twitter / X: {x_err}"
            )
            send_message(chat_id, err_msg, reply_to_message_id=reply_to_id, message_thread_id=thread_id)
    elif not ig_ok:
        print(f"Instagram video gönderilemedi: {ig_err}")
        if reply_to_id is not None:
            send_message(chat_id, f"ℹ️ <b>Instagram Reels:</b> {ig_err}", reply_to_message_id=reply_to_id, message_thread_id=thread_id)
    elif not x_ok:
        print(f"Twitter video gönderilemedi: {x_err}")
        if reply_to_id is not None:
            send_message(chat_id, f"ℹ️ <b>Twitter / X Video:</b> {x_err}", reply_to_message_id=reply_to_id, message_thread_id=thread_id)

    return (ig_ok or x_ok)

def run_reels_scheduler():
    """
    Arka planda çalışan periyodik viral Instagram Reels radar zamanlayıcısı.
    """
    print("🎬 Viral Reels Radarı zamanlayıcısı aktif.")
    while running:
        try:
            cfg = reels_store.get_config()
            if cfg.get("is_active") and cfg.get("target_chat_id"):
                interval_secs = cfg.get("interval_minutes", 120) * 60
                last_run = cfg.get("last_run_timestamp", 0)
                now = int(time.time())

                if now - last_run >= interval_secs:
                    print(f"🎬 Otomatik Reels Radarı tetiklendi (Chat: {cfg['target_chat_id']}, Thread: {cfg['target_thread_id']})...")
                    delivered = trigger_reels_delivery(cfg["target_chat_id"], cfg["target_thread_id"])
                    if delivered:
                        reels_store.touch_last_run()
                    else:
                        print("🎬 Bu turda yeni viral video bulunamadı veya gönderilemedi. 5 dakika sonra tekrar denenecek.")
                        reels_store.touch_last_run(backoff_seconds=300)
        except Exception as e:
            print(f"Reels zamanlayıcı hatası: {e}")

        time.sleep(30)

def handle_dekupe_command(chat_id, msg_id, target_msg, opt_text="", message_thread_id=None):
    """
    PhotoRoom AI motoru ile arka planı temizler,
    1500x2000 saf beyaz tuval üzerine orantılı yerleştirip
    kayıpsız e-ticaret / Trendyol görseli olarak teslim eder.
    """
    file_id = None
    orig_file_name = "urun.jpg"

    if "photo" in target_msg:
        file_id = target_msg["photo"][-1]["file_id"]
        orig_file_name = "urun_1500x2000.jpg"
    elif "document" in target_msg:
        doc = target_msg["document"]
        mime = doc.get("mime_type", "")
        if mime.startswith("image/") or doc.get("file_name", "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            file_id = doc["file_id"]
            orig_file_name = doc.get("file_name", "urun_1500x2000.jpg")
        else:
            send_message(
                chat_id,
                "⚠️ Lütfen bir görsel dosyası (PNG, JPG, WEBP) seçin.",
                reply_to_message_id=msg_id,
                message_thread_id=message_thread_id
            )
            return

    if not file_id:
        send_message(
            chat_id,
            "⚠️ <b>Görsel bulunamadı!</b>\n\n"
            "• Fotoğraf gönderirken açıklama kısmına <code>/d</code> yazın,\n"
            "• Veya gruptaki bir fotoğrafa <code>/d</code> yazarak yanıt verin!",
            reply_to_message_id=msg_id,
            message_thread_id=message_thread_id
        )
        return

    send_chat_action(chat_id, "upload_document", message_thread_id=message_thread_id)

    try:
        # Telegram'dan dosya yolunu al
        get_file_resp = requests.get(f"{API_URL}/getFile?file_id={file_id}", timeout=15).json()
        if not get_file_resp.get("ok"):
            send_message(
                chat_id,
                "❌ Dosya Telegram sunucularından indirilemedi.",
                reply_to_message_id=msg_id,
                message_thread_id=message_thread_id
            )
            return

        file_path = get_file_resp["result"]["file_path"]
        download_url = f"{FILE_URL}/{file_path}"

        # Görseli indir
        img_data = requests.get(download_url, timeout=30).content

        opt_lower = opt_text.lower()

        # Tuval boyutu belirleme:
        # /d kare -> 1500x1500 (Kare e-ticaret)
        # /d yatay -> 2000x1500
        # Varsayılan: 1500x2000 (Trendyol dikey)
        canvas_w, canvas_h = 1500, 2000
        canvas_desc = "1500 × 2000 px (Trendyol / E-Ticaret Dikey)"
        if "kare" in opt_lower or "1:1" in opt_lower:
            canvas_w, canvas_h = 1500, 1500
            canvas_desc = "1500 × 1500 px (Kare Format)"
        elif "yatay" in opt_lower:
            canvas_w, canvas_h = 2000, 1500
            canvas_desc = "2000 × 1500 px (Yatay Format)"

        # Doluluk oranı: Varsayılan %96 (boşluksuz, devasa ve ortalanmış)
        # /d full veya /d tasir -> %100 (kenarlara tam dayalı taşma modu)
        margin = 0.96
        if "full" in opt_lower or "tasir" in opt_lower or "taşır" in opt_lower:
            margin = 1.00
        elif "kucuk" in opt_lower or "küçük" in opt_lower:
            margin = 0.85

        # PhotoRoom ile işle: Yüksek doluluklu Beyaz Zemin + Şeffaf Cutout
        white_jpg_io, cutout_png_io, orig_size, final_size = photoroom_engine.process_ecommerce_photo(
            img_data, canvas_w=canvas_w, canvas_h=canvas_h, margin=margin
        )

        send_png_only = "png" in opt_lower or "seffaf" in opt_lower or "şeffaf" in opt_lower
        send_both = "hepsi" in opt_lower or "all" in opt_lower

        base_name = os.path.splitext(orig_file_name)[0]
        if not base_name.startswith("urun_"):
            base_name = f"urun_{base_name}"

        doc_payload = {
            "chat_id": chat_id,
            "parse_mode": "HTML",
            "reply_to_message_id": msg_id
        }
        if message_thread_id:
            doc_payload["message_thread_id"] = message_thread_id

        # 1. Şeffaf PNG istenmişse veya her ikisi istenmişse
        if send_png_only or send_both:
            cutout_caption = (
                "🔲 <b>Şeffaf Dekupe PNG Hazır!</b>\n"
                f"🔍 <b>Orijinal:</b> {orig_size[0]}×{orig_size[1]} px\n"
                "⚡ <b>Motor:</b> PhotoRoom AI Cutout\n"
                "📁 <i>Arka planı tamamen temizlenmiş kayıpsız PNG</i>"
            )
            cutout_payload = dict(doc_payload)
            cutout_payload["caption"] = cutout_caption
            requests.post(
                f"{API_URL}/sendDocument",
                data=cutout_payload,
                files={"document": (f"{base_name}_cutout.png", cutout_png_io.getvalue(), "image/png")},
                timeout=30
            )

        # 2. Beyaz Zeminli E-Ticaret JPEG (Varsayılan veya hepsi)
        if not send_png_only:
            white_caption = (
                "🛍️ <b>Ürün Fotoğrafın Hazır!</b>\n"
                f"📐 <b>Ölçü:</b> {canvas_desc}\n"
                "🎨 <b>Zemin:</b> Saf Beyaz (#FFFFFF) & Genişletilmiş Merkezleme\n"
                f"🔍 <b>Orijinal:</b> {orig_size[0]}×{orig_size[1]} ➔ 🎯 <b>Tuval:</b> {final_size[0]}×{final_size[1]}\n"
                "⚡ <b>Motor:</b> PhotoRoom AI Motoru\n"
                "📁 <i>Kayıpsız HD Belge (Doğrudan Mağazaya Yüklemeye Hazır)</i>\n"
                "💡 <i>İpuçları: <code>/d kare</code> (1:1), <code>/d full</code> (tam taşma), <code>/d png</code> (şeffaf)</i>"
            )
            white_payload = dict(doc_payload)
            white_payload["caption"] = white_caption
            requests.post(
                f"{API_URL}/sendDocument",
                data=white_payload,
                files={"document": (f"{base_name}_{canvas_w}x{canvas_h}.jpg", white_jpg_io.getvalue(), "image/jpeg")},
                timeout=30
            )

    except Exception as e:
        print(f"PhotoRoom Dekupe hatası: {e}")
        send_message(
            chat_id,
            f"❌ Görsel işlenirken hata oluştu: {str(e)}",
            reply_to_message_id=msg_id,
            message_thread_id=message_thread_id
        )

def handle_update(update):
    message = update.get("message") or update.get("channel_post")
    if not message:
        return

    chat_id = message["chat"]["id"]
    msg_id = message["message_id"]
    thread_id = message.get("message_thread_id")
    chat_type = message.get("chat", {}).get("type", "private")
    is_group = chat_type in ("group", "supergroup", "channel")

    # Bota DM atan kullanıcıyı otomatik admin hedefi olarak tanı
    if not is_group:
        backup_manager.set_admin_chat_id(chat_id)

    # Otomatik hedef koruma: Konteyner yeniden başladığında radar hedefleri varsayılana dönmüşse,
    # gruptan atılan ilk komutla aktif odayı ve konuyu otomatik olarak radara bağla
    if is_group:
        try:
            cfg = radar_store.get_config()
            if cfg.get("target_chat_id") in (-1004409412493, None):
                radar_store.set_target(chat_id, thread_id, title=message.get("chat", {}).get("title"))
            r_cfg = reels_store.get_config()
            if r_cfg.get("target_chat_id") in (-1004409412493, None):
                reels_store.set_target(chat_id, thread_id, title=message.get("chat", {}).get("title"))
        except Exception:
            pass

    # Metin komutları
    if "text" in message:
        text = message["text"].strip()
        if text.startswith("/start") or text.startswith("/help"):
            welcome = (
                "👋 <b>Merhaba! Instagram 1080×1350 Post Botuna Hoş Geldin.</b>\n\n"
                "📸 <b>Fotoğraf Gönder:</b>\n"
                "Herhangi bir fotoğraf veya ekran görüntüsü at; kalitesini bozmadan 1080×1350 saf siyah tuval üzerine tam ortalayarak kayıpsız PNG olarak teslim edeyim.\n\n"
                "💎 <b>Full Instagram Paketi (/ig):</b>\n"
                "<code>/ig https://x.com/kullanici/status/1234567890</code> (veya doğrudan link at);\n"
                " • 📌 OLED dark ana tweet şablonunu hazırlar,\n"
                " • 💬 Varsa 100+ beğeni almış en popüler yorumları (max 6) şablona dönüştürür,\n"
                " • 🖼️ Tweet içindeki kaydırmalı fotoğrafları 1080×1350 tuvale basar,\n"
                " • 📸 Telegram içi <b>Önizleme Albümü</b> olarak kayıpsız teslim eder!\n\n"
                "⚡ <b>Yorumsuz Hızlı Şablon (/url):</b>\n"
                "<code>/url https://x.com/kullanici/status/1234567890</code>\n"
                " • Popüler yorumlara <b>bakmaz</b>; sadece ana tweet'i ve varsa tweet içi fotoğrafları hızlıca hazırlar.\n\n"
                "🛰️ <b>Viral Tweet Radarı:</b>\n"
                " • <code>/radar_start</code> - Bulunulan odayı otomatik hedefe bağlar ve periyodik taramayı başlatır.\n"
                " • <code>/radar_now</code> - Beklemeden hemen 3'lü viral paketi (Standart, AI Seçimi, Yüksek Repost) gönderir.\n"
                " • <code>/repost_now</code> - Sadece yüksek repost ve yayılım almış tweeti getirir.\n"
                " • <code>/radar_stop</code> - Otomatik taramayı duraklatır.\n"
                " • <code>/radar_status</code> - Radar durumunu ve istatistiklerini gösterir.\n"
                " • <code>/radar_set 5000</code> - Beğeni eşiğini ayarlar.\n"
                " • <code>/radar_interval 120</code> - Tarama süresini ayarlar (dakika).\n\n"
                "🎬 <b>Viral Reels & Video Radarı:</b>\n"
                " • <code>/reels_start</code> - Bulunulan odayı hedefe bağlar ve periyodik taramayı başlatır.\n"
                " • <code>/reels_now</code> - Beklemeden yeni dikey viral Reels/Video bulup indirir.\n"
                " • <code>/ig_now</code> - Sadece Instagram Reels getirir.\n"
                " • <code>/x_now</code> - Sadece Twitter/X videosu getirir.\n"
                " • <code>/reels_stop</code> - Video radarını duraklatır.\n"
                " • <code>/reels_status</code> - Video radarı durumunu ve istatistiklerini gösterir.\n"
                " • <code>/reels_set 100000</code> - Minimum izlenme eşiğini ayarlar.\n"
                " • <code>/reels_interval 120</code> - Tarama süresini ayarlar (dakika).\n\n"
                "📈 <b>Post Geçmişi & Geri Bildirim:</b>\n"
                " • <code>/gecmis</code> - Son 10 postu ve performans durumunu listeler.\n"
                " • <code>/tuttu #12</code> - Postu Instagram'da 'TUTTU' (başarılı) olarak etiketler.\n"
                " • <code>/tutmadi #12</code> - Postu Instagram'da 'TUTMADI' (başarısız) olarak etiketler.\n"
                " • <code>/sonuc #12 &lt;izlenme&gt; [paylaşım] [kaydetme]</code> - Gerçek Instagram sonuçlarını kaydeder (10 veri sonrası en üst %25 otomatik 'TUTTU' sayılır).\n"
                " • <code>/ekle &lt;link&gt; &lt;tuttu|tutmadi&gt; [izlenme]</code> - Botun atmadığı eski/harici postları kütüphaneye ekler.\n"
                " • <code>/ornekler</code> - Altın kütüphanedeki örnekleri ve yapay zeka analiz notlarını listeler.\n"
                " • <code>/not #12 &lt;not&gt;</code> - Postun neden tuttu/tutmadığına dair analiz notunu manuel düzenler.\n"
                " • <code>/sil #12</code> - Hatalı kaydı geçmişten siler.\n\n"
                "🛍️ <b>PhotoRoom Dekupe & 1500×2000 Beyaz Zemin (/d):</b>\n"
                " • Fotoğraf atarken açıklama kısmına <code>/d</code> yazın veya fotoğrafa <code>/d</code> ile yanıt verin;\n"
                " • Arka planı stüdyo kalitesinde silip 1500×2000 saf beyaz tuvale yerleştirir.\n"
                " • <code>/d png</code>: Şeffaf PNG | <code>/d hepsi</code>: Hem beyaz zemin hem şeffaf.\n\n"
                "🔐 <b>Canlı Oturum & Çerez Yönetimi (DM):</b>\n"
                " • <code>/session_status</code> - Instagram ve Twitter oturum durumunu gösterir.\n"
                " • <code>/set_ig &lt;sessionid&gt;</code> - Instagram çerezini canlı günceller (mesaj otomatik silinir).\n"
                " • <code>/set_x &lt;auth_token&gt; &lt;ct0&gt;</code> - Twitter çerezlerini canlı günceller.\n\n"
                "Hemen dene! 🚀"
            )
            send_message(chat_id, welcome, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /set_ig: Instagram sessionid çerezini canlı günceller (Coolify deploy gerektirmez)
        if text.startswith("/set_ig"):
            if is_group:
                delete_message(chat_id, msg_id)
                send_message(
                    chat_id,
                    "⚠️ <b>Güvenlik Uyarısı:</b> Oturum çerezlerini lütfen gruplarda paylaşmayın! Bu komutu bota <b>özel mesaj (DM)</b> olarak gönderin.",
                    message_thread_id=thread_id
                )
                return

            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                new_session = parts[1].strip()
                ok = session_manager.set_instagram_session_id(new_session)
                delete_message(chat_id, msg_id)
                if ok:
                    valid, test_res = session_manager.verify_instagram_session(new_session)
                    durum_txt = "🟢 Aktif & Doğrulandı (HTTP 200)" if valid else f"⚠️ Kaydedildi Fakat: {test_res}"
                    send_message(
                        chat_id,
                        "✅ <b>Instagram Oturumu Başarıyla Güncellendi!</b>\n\n"
                        f"• <b>Canlı API Testi:</b> {durum_txt}\n"
                        f"• <b>Kayıt:</b> Kalıcı Depolama (<code>data/cookies.json</code>)\n"
                        "• <b>Etki:</b> Anında devrede (Coolify yeniden dağıtımına gerek yoktur).\n\n"
                        "🛡️ <i>Güvenliğiniz için çerezi içeren mesajınız sohbetten silinmiştir.</i>",
                        message_thread_id=thread_id
                    )
                else:
                    send_message(chat_id, "❌ Çerez kaydedilemedi.", message_thread_id=thread_id)
            else:
                send_message(
                    chat_id,
                    "⚠️ <b>Kullanım:</b>\n<code>/set_ig &lt;instagram_sessionid&gt;</code>\n\n"
                    "Örnek:\n<code>/set_ig 123456789%3Aabcdef...</code>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /set_x: Twitter/X auth_token ve ct0 çerezlerini canlı günceller
        if text.startswith("/set_x"):
            if is_group:
                delete_message(chat_id, msg_id)
                send_message(
                    chat_id,
                    "⚠️ <b>Güvenlik Uyarısı:</b> Oturum çerezlerini lütfen gruplarda paylaşmayın! Bu komutu bota <b>özel mesaj (DM)</b> olarak gönderin.",
                    message_thread_id=thread_id
                )
                return

            parts = text.split()
            if len(parts) >= 3:
                auth_token = parts[1].strip()
                ct0 = parts[2].strip()
                ok = session_manager.set_twitter_credentials(auth_token, ct0)
                delete_message(chat_id, msg_id)
                if ok:
                    send_message(
                        chat_id,
                        "✅ <b>Twitter/X Oturumu Başarıyla Güncellendi!</b>\n\n"
                        f"• <b>auth_token:</b> 🟢 Kaydedildi\n"
                        f"• <b>ct0:</b> 🟢 Kaydedildi\n"
                        f"• <b>Kayıt:</b> Kalıcı Depolama (<code>data/cookies.json</code>)\n"
                        "• <b>Etki:</b> Anında devrede (Coolify yeniden dağıtımına gerek yoktur).\n\n"
                        "🛡️ <i>Güvenliğiniz için çerezleri içeren mesajınız sohbetten silinmiştir.</i>",
                        message_thread_id=thread_id
                    )
                else:
                    send_message(chat_id, "❌ Çerezler kaydedilemedi.", message_thread_id=thread_id)
            else:
                send_message(
                    chat_id,
                    "⚠️ <b>Kullanım:</b>\n<code>/set_x &lt;auth_token&gt; &lt;ct0&gt;</code>\n\n"
                    "Örnek:\n<code>/set_x 28a1c9... 8ef120...</code>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /session_status veya /oturum: Aktif çerez durumunu ve canlı API testini gösterir
        if text.startswith("/session_status") or text.startswith("/oturum"):
            status = session_manager.get_status(verify_live=True)
            ig = status["instagram"]
            tw = status["twitter"]
            is_mounted = status.get("storage_persistent", False)

            if ig.get("live_status"):
                ig_status = f"{ig['live_status']} (Maskeli: <code>{ig['masked']}</code>)"
            else:
                ig_status = f"🟢 Aktif (Maskeli: <code>{ig['masked']}</code>)" if ig["active"] else "🔴 Tanımsız / Süresi Dolmuş"
            tw_status = f"🟢 Aktif (auth: <code>{tw['auth_token_masked']}</code>, ct0: <code>{tw['ct0_masked']}</code>)" if tw["active"] else "🔴 Tanımsız / Eksik"

            storage_note = (
                "💾 <b>Kalıcı Depolama (/app/data):</b> 🟢 Aktif Bağlı (Deploylarda veriler korunur)"
                if is_mounted else
                "💾 <b>Kalıcı Depolama (/app/data):</b> ⚠️ Bağlı Değil (Geçici Hafıza)\n"
                "<i>⚠️ Coolify panelinde uygulamanızın 'Storages' sekmesine gidip /app/data için bir kalıcı depolama ekleyin; aksi takdirde her git push / deploy işleminde çerezler ve post geçmişi sıfırlanabilir.</i>"
            )

            msg_txt = (
                "🔐 <b>Canlı Oturum & Çerez Durumu</b>\n\n"
                f"📸 <b>Instagram Reels:</b>\n"
                f"• Durum: {ig_status}\n"
                f"• Kaynak: {ig['source']}\n\n"
                f"🐦 <b>Twitter/X Scraper:</b>\n"
                f"• Durum: {tw_status}\n"
                f"• Kaynak: {tw['source']}\n\n"
                f"{storage_note}\n\n"
                "💡 <b>Canlı Güncellemek İçin (Bota Özelden / DM):</b>\n"
                "• <code>/set_ig &lt;sessionid&gt;</code>\n"
                "• <code>/set_x &lt;auth_token&gt; &lt;ct0&gt;</code>\n\n"
                "<i>Not: Güncellemeler Coolify veya GitHub gerektirmeden anında aktif olur.</i>"
            )
            send_message(chat_id, msg_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /durum veya /status: Detaylı bot, kalıcı hafıza, instance, ledger ve yedek durum raporu
        if text.startswith("/durum") or text.startswith("/status"):
            if not is_group:
                backup_manager.set_admin_chat_id(chat_id)

            uptime_sec = int(time.time() - BOT_START_TIME)
            hours, rem = divmod(uptime_sec, 3600)
            minutes, seconds = divmod(rem, 60)
            uptime_str = f"{hours} saat {minutes} dk" if hours > 0 else f"{minutes} dk {seconds} sn"

            boot_count = CURRENT_BOOT_INFO.get("boot_count", 1)
            boot_id = CURRENT_BOOT_INFO.get("boot_id", "bilinmiyor")

            ledger_lines = backup_manager._count_ledger_lines()
            post_count = backup_manager._count_history_posts()

            mount_info = backup_manager.get_storage_mount_info()
            if mount_info["is_separate"]:
                storage_str = f"🟢 Ayrı Volume Bağlı (st_dev: {mount_info['data_dev']} != {mount_info['parent_dev']})"
            else:
                storage_str = f"⚠️ Kök Dizinle Aynı Aygıtta (st_dev: {mount_info['data_dev']}) - Kalıcı volume bağlı olmayabilir"

            boot_log_survived = not CURRENT_BOOT_INFO.get("is_wiped_or_first", False)
            boot_status_str = "🟢 Korundu (Önceki kayıtlar mevcut)" if boot_log_survived else "⚠️ Yeni Boot / Sıfır Kayıt"

            backup_chat = backup_manager.get_backup_chat_id() or "Tanımsız (Kanalda /yedek_ata yazın)"
            meta = backup_manager.get_backup_meta()
            last_bk_time = meta.get("last_backup_time")
            last_manifest = meta.get("last_manifest") or {}
            if last_bk_time:
                bk_diff = int(time.time() - last_bk_time) // 60
                bk_time_str = f"{bk_diff} dakika önce" if bk_diff > 0 else "Az önce"
                bk_info_str = f"🟢 Aktif (Msg #{meta.get('last_msg_id')}, {bk_time_str}, Ledger: {last_manifest.get('ledger_lines', 0)})"
            else:
                bk_info_str = "⚪ Henüz yedek alınmadı"

            # Son 5 gönderilen post
            recent_posts = history_store.get_recent_posts(limit=5)
            recent_lines = []
            for rp in recent_posts:
                pid = rp.get("id")
                stype = rp.get("source_type", "tweet")
                auth = rp.get("author", "user")
                c_time = rp.get("created_at", 0)
                time_str = datetime.fromtimestamp(c_time, timezone.utc).strftime("%H:%M") if c_time else ""
                recent_lines.append(f"• <b>#{pid}</b> [{stype}] @{auth} ({time_str} UTC)")
            recent_block = "\n".join(recent_lines) if recent_lines else "• Henüz gönderi yok"

            conflict_line = (
                f"⚠️ <b>DİKKAT: Başka bir bot kopyası çalışıyor olabilir!</b>\n"
                f"• 409 Conflict: {CONFLICT_TRACKER['count']} kez tespit edildi (Son: {CONFLICT_TRACKER['last_desc'][:50]})\n"
                if CONFLICT_TRACKER["detected"] else
                "🟢 <b>Bot Çakışması:</b> Yok (Tek instance devrede)"
            )

            durum_msg = (
                "📊 <b>Bot Durumu & Sağlık Raporu</b>\n\n"
                f"🆔 <b>Instance ID:</b> <code>{INSTANCE_ID}</code>\n"
                f"🔢 <b>Boot Sayısı:</b> #{boot_count} (<code>{boot_id}</code>)\n"
                f"⏱️ <b>Çalışma Süresi:</b> {uptime_str}\n\n"
                f"💾 <b>Kalıcı Depolama (/app/data):</b>\n"
                f"• Volume Durumu: {storage_str}\n"
                f"• .boot_log Durumu: {boot_status_str}\n\n"
                f"📁 <b>Veri Boyutları:</b>\n"
                f"• sent_ledger.txt: <b>{ledger_lines}</b> kayıt\n"
                f"• post_history.json: <b>{post_count}</b> post\n\n"
                f"☁️ <b>Telegram Veri Yedeği (Sorun 4):</b>\n"
                f"• Hedef Kanal: <code>{backup_chat}</code>\n"
                f"• Son Yedek: {bk_info_str}\n\n"
                f"{conflict_line}\n\n"
                f"📜 <b>Son 5 Gönderilen İçerik:</b>\n"
                f"{recent_block}"
            )
            send_message(chat_id, durum_msg, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /yedek_ata: Bulunulan özel Telegram kanalını veri yedeği hedefi olarak kaydeder
        if text.startswith("/yedek_ata"):
            ok = backup_manager.set_backup_chat_id(chat_id)
            if ok:
                send_message(
                    chat_id,
                    f"✅ <b>Yedek hedefi ayarlandı.</b>\n"
                    f"Chat ID: <code>{chat_id}</code>\n\n"
                    f"⚠️ <i>Bu ID'yi kodda <code>BACKUP_CHAT_ID_DEFAULT</code> olarak sabitleyin, yoksa veri silinirse yedeği bulamam.</i>\n\n"
                    f"📦 <i>İlk yedek arşivlenip sabitleniyor (pin)...</i>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
                threading.Thread(
                    target=backup_manager.create_and_upload_backup,
                    args=(API_URL, INSTANCE_ID, CURRENT_BOOT_INFO.get("boot_id", "")),
                    kwargs={"force": True},
                    daemon=True
                ).start()
            else:
                send_message(chat_id, "❌ Yedek hedefi kaydedilemedi.", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /yedek_al: Manuel anlık veri yedeği oluşturup Telegram'a yükler
        if text.startswith("/yedek_al"):
            send_message(chat_id, "📦 <b>Anlık veri yedeği oluşturuluyor ve yükleniyor...</b>", reply_to_message_id=msg_id, message_thread_id=thread_id)
            threading.Thread(
                target=backup_manager.create_and_upload_backup,
                args=(API_URL, INSTANCE_ID, CURRENT_BOOT_INFO.get("boot_id", "")),
                kwargs={"force": True},
                daemon=True
            ).start()
            return

        # /d veya /dekupe komutu: PhotoRoom arka plan silme + 1500x2000 beyaz tuval
        if text.startswith("/d") or text.startswith("/dekupe"):
            reply_msg = message.get("reply_to_message")
            if reply_msg and ("photo" in reply_msg or "document" in reply_msg):
                handle_dekupe_command(chat_id, msg_id, reply_msg, opt_text=text, message_thread_id=thread_id)
                return
            elif "photo" in message or "document" in message:
                handle_dekupe_command(chat_id, msg_id, message, opt_text=text, message_thread_id=thread_id)
                return
            else:
                send_message(
                    chat_id,
                    "🛍️ <b>PhotoRoom Dekupe & 1500×2000 Beyaz Zemin</b>\n\n"
                    "• Fotoğraf gönderirken açıklama (caption) kısmına <code>/d</code> yazın,\n"
                    "• Veya gruptaki bir fotoğrafa <code>/d</code> yazarak yanıt verin!\n\n"
                    "💡 <b>Seçenekler:</b>\n"
                    "• <code>/d</code> ➔ 1500×2000 Beyaz Zeminli HD JPEG (Trendyol / E-Ticaret)\n"
                    "• <code>/d png</code> ➔ Şeffaf Arka Planlı Dekupe PNG\n"
                    "• <code>/d hepsi</code> ➔ Hem Beyaz Zemin hem Şeffaf PNG",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
                return

        # /radar_start: Bulunulan odayı viral hedefine bağlar ve radarı aktif eder
        if text.startswith("/radar_start"):
            chat_title = message.get("chat", {}).get("title") or "Özel Sohbet"
            radar_store.set_target(chat_id, thread_id, title=chat_title)
            cfg = radar_store.get_config()
            room_str = f"Konu ID: <code>{thread_id}</code>" if thread_id else "Ana Sohbet"
            resp_txt = (
                "🎯 <b>Viral Tweet Radarı Aktif Edildi!</b>\n\n"
                f"📍 <b>Grup/Kanal:</b> {chat_title}\n"
                f"📌 <b>Oda:</b> {room_str}\n"
                f"⏱️ <b>Tarama Aralığı:</b> Her {cfg['interval_minutes']} dakikada bir\n"
                f"🔥 <b>Beğeni Eşiği:</b> Min {cfg['min_faves']:,} Beğeni (Türkçe Popüler)\n\n"
                "🚀 <i>Bot arka planda sürekli tarayacak ve her yarım saatte bir keşfettiği yeni viral tweetin 1080×1350 OLED Instagram slayt albümünü doğrudan bu odaya teslim edecektir.</i>\n\n"
                "ℹ️ <i>Hemen test etmek için:</i> <code>/radar_now</code>\n"
                "ℹ️ <i>Durdurmak için:</i> <code>/radar_stop</code>"
            )
            send_message(chat_id, resp_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /radar_stop: Radarı duraklatır
        if text.startswith("/radar_stop"):
            radar_store.set_active(False)
            send_message(
                chat_id,
                "⏸️ <b>Viral Tweet Radarı duraklatıldı.</b>\nTekrar başlatmak için <code>/radar_start</code> yazabilirsiniz.",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            return

        # /radar_status: Radar durumunu görüntüler
        if text.startswith("/radar_status"):
            cfg = radar_store.get_config()
            status_emoji = "🟢 Aktif" if cfg["is_active"] else "🔴 Duraklatıldı"
            room_str = f"Konu {cfg['target_thread_id']}" if cfg["target_thread_id"] else "Ana Sohbet"
            mins = cfg['interval_minutes']
            freq_str = f"{mins // 60} saat" if mins >= 60 and mins % 60 == 0 else f"{mins} dakika"
            status_txt = (
                "📊 <b>Viral Tweet Radarı Durumu:</b>\n\n"
                f"• <b>Durum:</b> {status_emoji}\n"
                f"• <b>Kayıtlı Hedef:</b> {cfg.get('target_title') or 'Bilinmiyor'} ({room_str})\n"
                f"• <b>Tarama Sıklığı:</b> Her {freq_str} bir\n"
                f"• <b>Beğeni Filtresi:</b> Min {cfg['min_faves']:,} Beğeni\n"
                "• <b>Teslimat Paketleri (3'lü Viral Sinyal):</b>\n"
                "  1️⃣ <b>Standart:</b> En çok beğenilen tweet\n"
                "  2️⃣ <b>AI Seçimi:</b> Gemini analizli mizahi/kaliteli tweet\n"
                "  3️⃣ <b>Yüksek Repost:</b> Yüksek beğeni + yüksek repost/yayılım oranı\n"
                f"• <b>Gönderilen Toplam Tweet:</b> {cfg['sent_count']} adet\n\n"
                "ℹ️ <i>Hemen test etmek için:</i> <code>/radar_now</code> veya <code>/repost_now</code>"
            )
            send_message(chat_id, status_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /radar_set: Beğeni eşiğini ayarlar
        if text.startswith("/radar_set"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                val = int(parts[1])
                radar_store.set_min_faves(val)
                send_message(
                    chat_id,
                    f"✅ <b>Beğeni eşiği güncellendi:</b> Min {val:,} beğeni.",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            else:
                send_message(
                    chat_id,
                    "⚠️ Kullanım: <code>/radar_set 3000</code>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /radar_interval: Tarama sıklığını dakika cinsinden ayarlar (örn: /radar_interval 120)
        if text.startswith("/radar_interval"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                mins = int(parts[1])
                radar_store.set_interval(mins)
                hrs = f" ({mins // 60} saat)" if mins >= 60 and mins % 60 == 0 else ""
                send_message(
                    chat_id,
                    f"⏱️ <b>Radar Tarama Sıklığı Güncellendi:</b> Her {mins} dakikada bir{hrs}.",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            else:
                send_message(
                    chat_id,
                    "⚠️ Kullanım: <code>/radar_interval 120</code> (2 saat için 120 yazın)",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /radar_now: Beklemeden hemen şimdi yeni bir viral tweet bul ve gönder
        if text.startswith("/radar_now"):
            send_message(
                chat_id,
                "🔍 <b>En son viral Türkçe tweetler taranıyor (3'lü Paket: Standart, AI, Yüksek Repost)...</b>\n<i>Lütfen bekleyin, taranıyor.</i>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            threading.Thread(
                target=trigger_radar_delivery,
                args=(chat_id, thread_id, msg_id),
                daemon=True
            ).start()
            return

        # /repost_now: Beklemeden hemen şimdi yüksek repost/yayılım oranına sahip viral tweeti bul ve gönder
        if text.startswith("/repost_now"):
            send_message(
                chat_id,
                "🔁 <b>Yüksek Repost Radarı devrede!</b>\n<i>Hem yüksek beğeni hem de diğer tweetlere kıyasla yüksek repost almış viral tweet taranıyor... Lütfen bekleyin...</i>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            threading.Thread(
                target=deliver_high_repost_radar_single,
                args=(chat_id, thread_id, msg_id),
                daemon=True
            ).start()
            return

        # /reels_start: Bulunulan odayı (örn: ViralReels konusu) hedefe bağlar ve radarı aktif eder
        if text.startswith("/reels_start"):
            chat_title = message.get("chat", {}).get("title") or "Özel Sohbet"
            reels_store.set_target(chat_id, thread_id, title=chat_title)
            cfg = reels_store.get_config()
            room_str = f"Konu ID: <code>{thread_id}</code>" if thread_id else "Ana Sohbet"
            resp_txt = (
                "🎯 <b>Viral Instagram Reels Radarı Aktif Edildi!</b>\n\n"
                f"📍 <b>Grup/Kanal:</b> {chat_title}\n"
                f"📌 <b>Oda:</b> {room_str}\n"
                f"⏱️ <b>Tarama Aralığı:</b> Her {cfg['interval_minutes']} dakikada bir\n"
                f"🔥 <b>İzlenme Eşiği:</b> Min {cfg['min_plays']:,} İzlenme\n"
                f"❤️ <b>Beğeni Eşiği:</b> Min {cfg['min_likes']:,} Beğeni\n\n"
                "🚀 <i>Bot arka planda Instagram Reels akışını tarayacak ve patlayan videoları doğrudan MP4 video olarak bu odaya indirecektir.</i>\n\n"
                "ℹ️ <i>Hemen test etmek için:</i> <code>/reels_now</code>\n"
                "ℹ️ <i>Durdurmak için:</i> <code>/reels_stop</code>\n"
                "ℹ️ <i>Durum ve İstatistikler:</i> <code>/reels_status</code>"
            )
            send_message(chat_id, resp_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /reels_stop: Reels radarını duraklatır
        if text.startswith("/reels_stop"):
            reels_store.set_active(False)
            send_message(
                chat_id,
                "⏸️ <b>Viral Reels Radarı duraklatıldı.</b>\nTekrar başlatmak için <code>/reels_start</code> yazabilirsiniz.",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            return

        # /reels_status: Reels radarı durumunu görüntüler
        if text.startswith("/reels_status"):
            cfg = reels_store.get_config()
            status_emoji = "🟢 Aktif" if cfg["is_active"] else "🔴 Duraklatıldı"
            room_str = f"Konu {cfg['target_thread_id']}" if cfg["target_thread_id"] else "Ana Sohbet"
            mins = cfg['interval_minutes']
            freq_str = f"{mins // 60} saat" if mins >= 60 and mins % 60 == 0 else f"{mins} dakika"
            status_txt = (
                "📊 <b>Viral Reels Radarı Durumu:</b>\n\n"
                f"• <b>Durum:</b> {status_emoji}\n"
                f"• <b>Kayıtlı Hedef:</b> {cfg.get('target_title') or 'Bilinmiyor'} ({room_str})\n"
                f"• <b>Tarama Sıklığı:</b> Her {freq_str} bir\n"
                f"• <b>İzlenme Filtresi:</b> Min {cfg['min_plays']:,} İzlenme\n"
                f"• <b>Beğeni Filtresi:</b> Min {cfg['min_likes']:,} Beğeni\n"
                f"• <b>Gönderilen Toplam Reels:</b> {cfg['sent_count']} adet\n"
                f"• <b>Küratör & AI Filtresi:</b> 🛡️ Aktif (9:16 Dikey, Anti-Reklam, Anti-Spam)\n\n"
                "ℹ️ <i>Sıklığı değiştirmek için:</i> <code>/reels_interval 120</code>"
            )
            send_message(chat_id, status_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /reels_set: İzlenme eşiğini ayarlar
        if text.startswith("/reels_set"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                val = int(parts[1])
                reels_store.set_min_plays(val)
                send_message(
                    chat_id,
                    f"✅ <b>Reels izlenme eşiği güncellendi:</b> Min {val:,} izlenme.",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            else:
                send_message(
                    chat_id,
                    "⚠️ Kullanım: <code>/reels_set 100000</code>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /reels_interval: Reels tarama sıklığını dakika cinsinden ayarlar (örn: /reels_interval 120)
        if text.startswith("/reels_interval"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                mins = int(parts[1])
                reels_store.set_interval(mins)
                hrs = f" ({mins // 60} saat)" if mins >= 60 and mins % 60 == 0 else ""
                send_message(
                    chat_id,
                    f"⏱️ <b>Reels Radar Tarama Sıklığı Güncellendi:</b> Her {mins} dakikada bir{hrs}.",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            else:
                send_message(
                    chat_id,
                    "⚠️ Kullanım: <code>/reels_interval 120</code> (2 saat için 120 yazın)",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
            return

        # /reels_now: Beklemeden hemen şimdi hem Instagram hem de Twitter'dan viral videolar bul ve gönder
        if text.startswith("/reels_now"):
            send_message(
                chat_id,
                "🔍 <b>Viral Video Radarı devrede!</b>\nHem <b>Instagram Reels</b> hem de <b>Twitter/X</b> taranıyor ve popüler videolar MP4 olarak indiriliyor...\n<i>Lütfen bekleyin...</i>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            threading.Thread(
                target=trigger_reels_delivery,
                args=(chat_id, thread_id, msg_id),
                daemon=True
            ).start()
            return

        # /ig_now: Sadece Instagram'dan viral Reels getir
        if text.startswith("/ig_now"):
            send_message(
                chat_id,
                "📸 <b>En güncel Instagram Reels taranıyor ve indiriliyor...</b>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            threading.Thread(
                target=deliver_instagram_reel,
                args=(chat_id, thread_id, msg_id),
                daemon=True
            ).start()
            return

        # /x_now: Sadece Twitter/X'ten viral video getir
        if text.startswith("/x_now"):
            send_message(
                chat_id,
                "🐦 <b>En güncel Twitter/X viral videosu taranıyor ve indiriliyor...</b>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            threading.Thread(
                target=deliver_twitter_video,
                args=(chat_id, thread_id, msg_id),
                daemon=True
            ).start()
            return

        # /ig komutu kontrolü: Popüler yorumlar + fotoğraflar + ana tweet (Full paket)
        if text.startswith("/ig"):
            handle_ig_command(chat_id, msg_id, text, include_comments=True, message_thread_id=thread_id)
            return

        # /url veya /url2 komutu kontrolü: Popüler yorumlara bakmaz, sadece ana tweet ve fotoğrafları işler
        if text.startswith("/url2") or text.startswith("/url"):
            handle_ig_command(chat_id, msg_id, text, include_comments=False, message_thread_id=thread_id)
            return

        # /img komutu kontrolü (Geriye dönük uyumluluk)
        if text.startswith("/img"):
            handle_ig_command(chat_id, msg_id, text, include_comments=True, message_thread_id=thread_id)
            return

        # /gecmis: Son 10 postu ve geri bildirim durumunu listeler
        if text.startswith("/gecmis"):
            recent = history_store.get_recent_posts(limit=10)
            if not recent:
                send_message(
                    chat_id,
                    "📭 <b>Henüz kayıtlı bir post geçmişi bulunmuyor.</b>\nRadar veya /ig ile gönderilen postlar burada otomatik listelenecektir.",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
                return

            lines = ["📜 <b>Son 10 Post ve Performans Durumu:</b>\n"]
            for p in recent:
                pid = p.get("id")
                stype = p.get("source_type", "tweet")
                author = p.get("author", "bilinmiyor")
                res = p.get("results", {})
                tag = res.get("tag")
                views = res.get("views")

                if stype == "tweet":
                    type_str = "AI Tweet" if p.get("delivery_mode") == "ai_curator" else "Tweet"
                elif stype == "instagram_reel":
                    type_str = "Reels"
                elif stype == "twitter_video":
                    type_str = "X Video"
                elif stype == "retroactive":
                    type_str = "Eski Post"
                else:
                    type_str = stype

                if tag == "tuttu":
                    tag_str = f"🟢 TUTTU" + (f" ({views:,} izlenme)" if views else "")
                elif tag == "tutmadi":
                    tag_str = f"🔴 TUTMADI" + (f" ({views:,} izlenme)" if views else "")
                elif tag == "orta":
                    tag_str = f"🟡 ORTA" + (f" ({views:,} izlenme)" if views else "")
                else:
                    tag_str = f"⚪ ({views:,} izlenme)" if views else "⚪ Sonuçsuz"

                lines.append(f"• <b>#{pid}</b> [{type_str}] @{author} — {tag_str}")

            lines.append("\nℹ️ <i>Geri bildirim için:</i> <code>/tuttu #12</code> veya <code>/sonuc #12 120k</code>")
            send_message(chat_id, "\n".join(lines), reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /tuttu: Postu Instagram'da başarılı olarak etiketler
        if text.startswith("/tuttu"):
            parts = text.split()
            if len(parts) > 1:
                pid = parse_post_id(parts[1])
                if pid:
                    ok = history_store.set_tag(pid, "tuttu", tagged_by="manual")
                    if ok:
                        # Aşama 3: Gemini ile 'Neden Tuttu' analizi üret
                        history_curator.generate_why_note_async(pid)
                        send_message(
                            chat_id,
                            f"✅ <b>Post #{pid} 'TUTTU' olarak etiketlendi!</b>\n\n"
                            "💡 <i>Yapay zeka başarı analizi kütüphaneye işleniyor...</i>\n"
                            "İçerik altın kütüphaneye dahil edildi ve gelecekteki seçimlerde başarılı referans (Few-Shot) olarak sunulacak.\n\n"
                            "ℹ️ <i>Kütüphaneyi ve analizleri görmek için:</i> <code>/ornekler</code>",
                            reply_to_message_id=msg_id,
                            message_thread_id=thread_id
                        )
                        return
                    else:
                        send_message(chat_id, f"❌ Post #{pid} geçmişte bulunamadı.", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
            send_message(chat_id, "⚠️ Kullanım: <code>/tuttu #12</code> veya <code>/tuttu 12</code>", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /tutmadi: Postu Instagram'da başarısız olarak etiketler
        if text.startswith("/tutmadi"):
            parts = text.split()
            if len(parts) > 1:
                pid = parse_post_id(parts[1])
                if pid:
                    ok = history_store.set_tag(pid, "tutmadi", tagged_by="manual")
                    if ok:
                        # Aşama 3: Gemini ile 'Neden Tutmadı' analizi üret
                        history_curator.generate_why_note_async(pid)
                        send_message(
                            chat_id,
                            f"❌ <b>Post #{pid} 'TUTMADI' olarak etiketlendi.</b>\n\n"
                            "💡 <i>Yapay zeka neden tutmadığını analiz edip kütüphaneye işliyor...</i>\n"
                            "Bu içerik gelecekteki yapay zeka seçimlerinde kaçınılması gereken negatif referans olarak kullanılacaktır.\n\n"
                            "ℹ️ <i>Kütüphaneyi ve analizleri görmek için:</i> <code>/ornekler</code>",
                            reply_to_message_id=msg_id,
                            message_thread_id=thread_id
                        )
                        return
                    else:
                        send_message(chat_id, f"❌ Post #{pid} geçmişte bulunamadı.", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
            send_message(chat_id, "⚠️ Kullanım: <code>/tutmadi #12</code> veya <code>/tutmadi 12</code>", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /sonuc: Gerçek Instagram izlenme ve etkileşim sonuçlarını kaydeder
        if text.startswith("/sonuc"):
            parts = text.split()
            if len(parts) >= 3:
                pid = parse_post_id(parts[1])
                views = parse_stat_number(parts[2])
                shares = parse_stat_number(parts[3]) if len(parts) > 3 else None
                saves = parse_stat_number(parts[4]) if len(parts) > 4 else None
                likes = parse_stat_number(parts[5]) if len(parts) > 5 else None
                comments = parse_stat_number(parts[6]) if len(parts) > 6 else None

                if pid and views is not None:
                    post = history_store.update_results(
                        post_id=pid,
                        views=views,
                        shares=shares,
                        saves=saves,
                        likes=likes,
                        comments=comments
                    )
                    if post:
                        res = post.get("results", {})
                        tag = res.get("tag")
                        tagged_by = res.get("tagged_by")

                        # Aşama 3: Etiket oluştuktan sonra analiz notunu tetikle
                        if tag in ["tuttu", "tutmadi"]:
                            history_curator.generate_why_note_async(pid)

                        status_line = ""
                        if tag == "tuttu":
                            status_line = "🟢 <b>TUTTU</b>" + (" (Dinamik En Üst %25)" if tagged_by == "auto" else " (Manuel)")
                        elif tag == "tutmadi":
                            status_line = "🔴 <b>TUTMADI</b>" + (" (Dinamik Alt %25)" if tagged_by == "auto" else " (Manuel)")
                        elif tag == "orta":
                            status_line = "🟡 <b>ORTA</b> (Dinamik %50 Dilim)"
                        else:
                            status_line = "⚪ Henüz otomatik eşik oluşmadı (10 posttan az veri var; <code>/tuttu</code> ile manuel etiketleyebilirsiniz)"

                        summary_txt = (
                            f"📊 <b>Post #{pid} Instagram Performansı Kaydedildi!</b>\n\n"
                            f"• 👁️ <b>İzlenme:</b> {views:,}\n"
                            + (f"• 📤 <b>Paylaşım:</b> {shares:,}\n" if shares is not None else "")
                            + (f"• 🔖 <b>Kaydetme:</b> {saves:,}\n" if saves is not None else "")
                            + (f"• ❤️ <b>Beğeni:</b> {likes:,}\n" if likes is not None else "")
                            + (f"• 💬 <b>Yorum:</b> {comments:,}\n" if comments is not None else "")
                            + f"\n🏷️ <b>Durum:</b> {status_line}\n"
                            "💡 <i>Yapay zeka analiz notu kütüphaneye işleniyor (/ornekler).</i>"
                        )
                        send_message(chat_id, summary_txt, reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
                    else:
                        send_message(chat_id, f"❌ Post #{pid} geçmişte bulunamadı.", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return

            send_message(
                chat_id,
                "⚠️ <b>Kullanım:</b> <code>/sonuc #12 &lt;izlenme&gt; [paylaşım] [kaydetme] [beğeni] [yorum]</code>\n"
                "Örnek: <code>/sonuc #12 120k 850 1400</code>\n"
                "<i>(10 post izlenmesi kaydedildiğinde en iyi %25 otomatik 'TUTTU' sayılır).</i>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            return

        # /ekle: Botun atmadığı harici/eski postları geriye dönük ekler
        if text.startswith("/ekle"):
            parts = text.split()
            if len(parts) >= 3:
                link = parts[1].strip()
                tag = parts[2].strip().lower()
                if tag in ["tuttu", "tutmadi"]:
                    views = parse_stat_number(parts[3]) if len(parts) > 3 else None
                    shares = parse_stat_number(parts[4]) if len(parts) > 4 else None
                    saves = parse_stat_number(parts[5]) if len(parts) > 5 else None

                    author = "harici"
                    match = re.search(r"(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)", link)
                    if match:
                        author = match.group(1)

                    pid = history_store.add_retroactive_post(
                        link=link,
                        tag=tag,
                        views=views,
                        shares=shares,
                        saves=saves,
                        author=author
                    )

                    # Aşama 3: Gemini ile 'Neden Tuttu/Tutmadı' analizi üret
                    history_curator.generate_why_note_async(pid)

                    tag_emoji = "🟢 TUTTU" if tag == "tuttu" else "🔴 TUTMADI"
                    stat_info = f"\n• 👁️ İzlenme: {views:,}" if views else ""

                    send_message(
                        chat_id,
                        f"✅ <b>Eski Post Başarıyla Eklendi (#{pid})!</b>\n"
                        f"• <b>Durum:</b> {tag_emoji}\n"
                        f"• <b>Yazar:</b> @{author}\n"
                        f"• <b>Link:</b> {link}"
                        f"{stat_info}\n\n"
                        "💡 <i>Kütüphaneye işlendi; yapay zeka başarı analizi üretilip öğrenme veritabanına eklendi.</i>",
                        reply_to_message_id=msg_id,
                        message_thread_id=thread_id
                    )
                    return
            send_message(
                chat_id,
                "⚠️ <b>Kullanım:</b> <code>/ekle &lt;link&gt; &lt;tuttu|tutmadi&gt; [izlenme] [paylaşım] [kaydetme]</code>\n"
                "Örnek: <code>/ekle https://x.com/user/status/123 tuttu 250k 1500 3200</code>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            return

        # /ornekler: Altın kütüphanedeki 'TUTTU' ve 'TUTMADI' postlarını ve Gemini analizlerini listeler
        if text.startswith("/ornekler"):
            stats = history_store.get_stats_summary()
            tagged_tuttu = history_store.get_tagged_posts("tuttu")
            tagged_tutmadi = history_store.get_tagged_posts("tutmadi")

            if not tagged_tuttu and not tagged_tutmadi:
                send_message(
                    chat_id,
                    "🏆 <b>Altın Kütüphane Boş</b>\n\n"
                    "Henüz etiketlenmiş bir post bulunmuyor.\n"
                    "• Gönderilen postları etiketlemek için: <code>/tuttu #12</code> veya <code>/tutmadi #12</code>\n"
                    "• Sonuç girmek için: <code>/sonuc #12 150k 1200 450</code>\n"
                    "• Eski başarılı postları eklemek için: <code>/ekle &lt;link&gt; tuttu [izlenme]</code>",
                    reply_to_message_id=msg_id,
                    message_thread_id=thread_id
                )
                return

            lines = [
                "🏆 <b>Altın Kütüphane & Yapay Zeka Öğrenme Veritabanı</b>\n",
                f"• <b>Tutan Postlar (TUTTU):</b> {stats['tuttu_count']} adet",
                f"• <b>Tutmayan Postlar (TUTMADI):</b> {stats['tutmadi_count']} adet"
            ]
            if stats['avg_views'] > 0:
                lines.append(f"• <b>Ortalama İzlenme:</b> {stats['avg_views']:,}")
            if stats["is_dynamic_active"] and stats["threshold_75"]:
                lines.append(f"• <b>Dinamik Üst %25 Eşiği:</b> {stats['threshold_75']:,} izlenme")
            lines.append("")

            if tagged_tuttu:
                lines.append("✅ <b>Öne Çıkan TUTTU Örnekleri:</b>")
                for p in tagged_tuttu[:6]:
                    pid = p.get("id")
                    author = p.get("author", "bilinmiyor")
                    res = p.get("results", {})
                    v = res.get("views")
                    v_str = f" ({v:,} izlenme)" if v else ""
                    text_raw = (p.get("text", "") or p.get("caption", "")).replace("\n", " ")
                    text_short = (text_raw[:70] + "...") if len(text_raw) > 70 else text_raw
                    why = p.get("why_note") or p.get("ai_reason") or "Yüksek etkileşim ve DM paylaşımı."

                    lines.append(f"• <b>#{pid}</b> @{author}{v_str}\n  💬 <i>\"{escape(text_short)}\"</i>\n  💡 <b>Neden:</b> {escape(why)}")
                lines.append("")

            if tagged_tutmadi:
                lines.append("❌ <b>Öne Çıkan TUTMADI Örnekleri:</b>")
                for p in tagged_tutmadi[:4]:
                    pid = p.get("id")
                    author = p.get("author", "bilinmiyor")
                    res = p.get("results", {})
                    v = res.get("views")
                    v_str = f" ({v:,} izlenme)" if v else ""
                    text_raw = (p.get("text", "") or p.get("caption", "")).replace("\n", " ")
                    text_short = (text_raw[:70] + "...") if len(text_raw) > 70 else text_raw
                    why = p.get("why_note") or "Düşük kitle rezonansı, yayılma sağlayamadı."

                    lines.append(f"• <b>#{pid}</b> @{author}{v_str}\n  💬 <i>\"{escape(text_short)}\"</i>\n  ⚠️ <b>Neden:</b> {escape(why)}")
                lines.append("")

            lines.append("✏️ <i>Bir postun analiz notunu düzenlemek için:</i>\n<code>/not #<no> <kendi açıklamanız></code>")

            send_message(chat_id, "\n".join(lines), reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # /not veya /not_duzelt: Postun neden tuttu/tutmadı analiz notunu günceller
        if text.startswith("/not") or text.startswith("/not_duzelt"):
            parts = text.split(maxsplit=2)
            if len(parts) >= 3:
                pid = parse_post_id(parts[1])
                new_note = parts[2].strip()
                if pid and new_note:
                    ok = history_store.set_why_note(pid, new_note)
                    if ok:
                        send_message(
                            chat_id,
                            f"✅ <b>Post #{pid} Analiz Notu Güncellendi!</b>\n\n"
                            f"💡 <b>Yeni Not:</b> <i>{escape(new_note)}</i>\n\n"
                            "Bu not altın kütüphaneye kaydedildi ve yapay zeka puanlamalarında referans olarak kullanılacaktır.",
                            reply_to_message_id=msg_id,
                            message_thread_id=thread_id
                        )
                        return
                    else:
                        send_message(chat_id, f"❌ Post #{pid} geçmişte bulunamadı.", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
            send_message(
                chat_id,
                "⚠️ <b>Kullanım:</b> <code>/not #&lt;no&gt; &lt;analiz notunuz&gt;</code>\n"
                "Örnek: <code>/not #4 Gündelik ilişki mizahı ve yüksek DM paylaşımı sayesinde tuttu.</code>",
                reply_to_message_id=msg_id,
                message_thread_id=thread_id
            )
            return

        # /sil: Hatalı postu geçmişten ve kütüphaneden siler
        if text.startswith("/sil"):
            parts = text.split()
            if len(parts) > 1:
                pid = parse_post_id(parts[1])
                if pid:
                    ok = history_store.delete_post(pid)
                    if ok:
                        send_message(chat_id, f"🗑️ <b>Post #{pid} başarıyla silindi.</b>", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
                    else:
                        send_message(chat_id, f"❌ Post #{pid} geçmişte bulunamadı.", reply_to_message_id=msg_id, message_thread_id=thread_id)
                        return
            send_message(chat_id, "⚠️ Kullanım: <code>/sil #12</code> veya <code>/sil 12</code>", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        # Doğrudan atılan Twitter/X linklerini de otomatik algıla (/ig gibi full çalışır)
        if re.search(r"https?://(?:twitter\.com|x\.com|fixupx\.com|vxtwitter\.com|fxtwitter\.com)/[a-zA-Z0-9_]+/status/\d+", text):
            handle_ig_command(chat_id, msg_id, text, include_comments=True, message_thread_id=thread_id)
            return

    # Caption (açıklama) içinde /d veya /dekupe kontrolü
    caption = (message.get("caption") or "").strip()
    if caption.startswith("/d") or caption.startswith("/dekupe") or re.search(r'(^|\s)/d(\s|$)', caption):
        handle_dekupe_command(chat_id, msg_id, message, opt_text=caption, message_thread_id=thread_id)
        return

    # Eğer grup veya kanaldaysa ve /d verilmediyse, gruptaki diğer botlarla çakışmamak için fotoğrafı işleme
    if is_group:
        return

    file_id = None
    file_name = "instagram_post.png"

    # Fotoğraf olarak gönderildiyse (En yüksek çözünürlüklü olanı seç)
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        file_name = "instagram_post_1080x1350.png"
    # Belge / Dosya olarak gönderildiyse (Sıkıştırmasız orijinal dosya)
    elif "document" in message:
        doc = message["document"]
        mime = doc.get("mime_type", "")
        if mime.startswith("image/") or doc.get("file_name", "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            file_id = doc["file_id"]
            file_name = f"insta_{doc.get('file_name', 'image')}.png"
        else:
            send_message(chat_id, "⚠️ Lütfen bir görsel dosyası (PNG, JPG, WEBP) gönderin.", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

    if not file_id:
        return

    send_chat_action(chat_id, "upload_document", message_thread_id=thread_id)

    try:
        # Telegram'dan dosya yolunu al
        get_file_resp = requests.get(f"{API_URL}/getFile?file_id={file_id}", timeout=15).json()
        if not get_file_resp.get("ok"):
            send_message(chat_id, "❌ Dosya Telegram sunucularından indirilemedi.", reply_to_message_id=msg_id, message_thread_id=thread_id)
            return

        file_path = get_file_resp["result"]["file_path"]
        download_url = f"{FILE_URL}/{file_path}"

        # Görseli indir
        img_data = requests.get(download_url, timeout=30).content

        # 1080x1350 Siyah Arka Plana Otomatik Sığdır
        output_buffer, orig_size, new_size = process_image(img_data)

        caption = (
            "✨ <b>Instagram Gönderin Hazır!</b>\n"
            f"📐 <b>Ölçü:</b> 1080 × 1350 px (4:5 Dikey)\n"
            f"🔍 <b>Orijinal:</b> {orig_size[0]}×{orig_size[1]} ➔ 🎯 <b>Görsel:</b> {new_size[0]}×{new_size[1]} (Tam Ortalandı)\n"
            "📁 <i>Kayıpsız HD Orijinal PNG (Doğrudan Instagram'a Yüklemeye Hazır)</i>"
        )

        # Sadece kayıpsız HD PNG dosyası olarak gönder (Telegram sıkıştırmasını atlar)
        output_buffer.seek(0)
        doc_payload = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_to_message_id": msg_id
        }
        if thread_id:
            doc_payload["message_thread_id"] = thread_id

        requests.post(
            f"{API_URL}/sendDocument",
            data=doc_payload,
            files={"document": (file_name, output_buffer.getvalue(), "image/png")},
            timeout=30
        )

    except Exception as e:
        print(f"İşlem hatası: {e}")
        send_message(chat_id, f"❌ Görsel işlenirken bir hata oluştu: {str(e)}", reply_to_message_id=msg_id, message_thread_id=thread_id)

def main():
    global CURRENT_BOOT_INFO
    print("=" * 55)
    print("🤖 Instagram Post Telegram Botu Başlatıldı!")
    print(f"🔗 Bot Kullanıcı Adı: @denemekick_bot")
    print(f"🆔 Instance Kimliği: {INSTANCE_ID}")
    print("=" * 55)

    # 1. Boot kaydı oluştur
    CURRENT_BOOT_INFO = backup_manager.record_boot(INSTANCE_ID)
    boot_count = CURRENT_BOOT_INFO.get("boot_count", 1)
    is_wiped = CURRENT_BOOT_INFO.get("is_wiped_or_first", False)

    # 2. Telegram Yedeğinden Geri Yükleme (Zamanlayıcılardan ÖNCE)
    print("🔄 Telegram veri yedeği denetleniyor...")
    restore_res = backup_manager.restore_from_telegram_if_needed(
        API_URL,
        INSTANCE_ID,
        boot_id=CURRENT_BOOT_INFO.get("boot_id", "")
    )
    dedup_engine.reload()

    # 3. Veri durumu tespiti ve Admin Bildirimi
    if restore_res.get("restored"):
        veri_durumu = f"Geri yüklendi ({restore_res.get('status')})"
    elif not is_wiped:
        veri_durumu = "Mevcut (Kalıcı disk korundu)"
    else:
        veri_durumu = "Sıfır / İlk Kurulum"
        # Önceki kayıt yok ve yedek de çekilemediyse: VERİ SIFIRLANDI UYARISI
        print("🚨 [UYARI] VERİ SIFIRLANDI: Önceki .boot_log kaydı bulunamadı ve Telegram yedeği alınamadı!")
        backup_manager.notify_admin(
            API_URL,
            f"🚨 <b>DİKKAT: BOT VERİLERİ SIFIRLANDI!</b>\n\n"
            f"• <b>Instance:</b> <code>{INSTANCE_ID}</code>\n"
            f"• Önceki boot kaydı bulunamadı ve Telegram yedeği yüklenemedi.\n"
            f"• Kalıcı depolama (/app/data volume) ayarlarını veya yedek kanalını kontrol edin."
        )

    ledger_cnt = backup_manager._count_ledger_lines()
    startup_dm = (
        f"🤖 <b>Bot başladı</b> (Instance: <code>{INSTANCE_ID}</code>)\n"
        f"• <b>Veri:</b> {veri_durumu}\n"
        f"• <b>Ledger:</b> {ledger_cnt} kayıt\n"
        f"• <b>Boot Sayısı:</b> #{boot_count}"
    )
    backup_manager.notify_admin(API_URL, startup_dm)

    # 4. 30 dakikalık periyodik veri yedekleme döngüsünü başlat
    threading.Thread(
        target=backup_manager.run_periodic_backup_loop,
        args=(API_URL, INSTANCE_ID, CURRENT_BOOT_INFO.get("boot_id", "")),
        daemon=True
    ).start()

    # 5. Koyeb / Cloud platformları için hafif healthcheck sunucusunu başlat
    threading.Thread(target=run_health_server, daemon=True).start()

    # 6. 30 dakikalık periyodik Viral Tweet Radarı zamanlayıcısını başlat
    threading.Thread(target=run_radar_scheduler, daemon=True).start()

    # 7. 30 dakikalık periyodik Viral Reels Radarı zamanlayıcısını başlat
    threading.Thread(target=run_reels_scheduler, daemon=True).start()

    print("Mesajlar dinleniyor (Çıkış için Ctrl+C)...")

    offset = 0
    # Eski birikmiş mesajları atla
    try:
        updates = requests.get(f"{API_URL}/getUpdates?offset=-1", timeout=10).json()
        if updates.get("ok") and updates.get("result"):
            offset = updates["result"][-1]["update_id"] + 1
    except Exception:
        pass

    while running:
        try:
            resp = requests.get(f"{API_URL}/getUpdates?offset={offset}&timeout=20", timeout=25).json()
            if resp.get("ok"):
                for update in resp["result"]:
                    offset = update["update_id"] + 1
                    handle_update(update)
            else:
                err_code = resp.get("error_code")
                desc = resp.get("description", "")
                if err_code == 409 or "conflict" in desc.lower():
                    CONFLICT_TRACKER["detected"] = True
                    CONFLICT_TRACKER["last_time"] = int(time.time())
                    CONFLICT_TRACKER["count"] += 1
                    CONFLICT_TRACKER["last_desc"] = desc
                    print(f"⚠️ [ÇAKIŞMA] Telegram 409 Conflict: Başka bir bot kopyası devrede! ({desc})")
                    time.sleep(5)
                else:
                    time.sleep(1)
        except requests.exceptions.RequestException:
            time.sleep(2)
        except Exception as e:
            print(f"Döngü hatası: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
