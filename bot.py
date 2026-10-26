#!/usr/bin/env python3
"""
Instagram Post 1080x1350 Auto-Fitter Telegram Bot
Bot Name: igfoto (@denemekick_bot)
"""

import os
import io
import time
import signal
import sys
import requests
from PIL import Image, ImageOps

BOT_TOKEN = os.getenv("BOT_TOKEN", "8534996297:AAE9K8WOf1tgx_tKsy9jGUV3mlg2hn2plqU")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1350
TARGET_ASPECT = CANVAS_WIDTH / CANVAS_HEIGHT  # 0.8

running = True

def signal_handler(sig, frame):
    global running
    print("\nBot durduruluyor...")
    running = False
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def send_chat_action(chat_id, action="upload_photo"):
    try:
        requests.post(f"{API_URL}/sendChatAction", json={"chat_id": chat_id, "action": action}, timeout=10)
    except Exception:
        pass

def send_message(chat_id, text, reply_to_message_id=None):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        return requests.post(f"{API_URL}/sendMessage", json=payload, timeout=15)
    except Exception as e:
        print(f"Mesaj gönderme hatası: {e}")
        return None

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

def handle_update(update):
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    msg_id = message["message_id"]

    # Metin komutları
    if "text" in message:
        text = message["text"].strip()
        if text.startswith("/start") or text.startswith("/help"):
            welcome = (
                "👋 <b>Merhaba! Instagram 1080×1350 Post Botuna Hoş Geldin.</b>\n\n"
                "📸 Bana herhangi bir <b>ekran görüntüsü</b> veya <b>fotoğraf</b> gönder.\n\n"
                "⚡ <b>Ne Yaparım?</b>\n"
                "• Çözünürlüğü ve en-boy oranını bozmadan otomatik sığdırırım.\n"
                "• <b>1080 × 1350 px</b> saf siyah arka planın tam ortasına yerleştiririm.\n"
                "• Hem <b>önizleme fotoğrafı</b> hem de <b>orijinal kayıpsız dosya (PNG)</b> olarak anında teslim ederim!\n\n"
                "Hemen bir fotoğraf at ve dene! 🚀"
            )
            send_message(chat_id, welcome, reply_to_message_id=msg_id)
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
            send_message(chat_id, "⚠️ Lütfen bir görsel dosyası (PNG, JPG, WEBP) gönderin.", reply_to_message_id=msg_id)
            return

    if not file_id:
        return

    send_chat_action(chat_id, "upload_document")

    try:
        # Telegram'dan dosya yolunu al
        get_file_resp = requests.get(f"{API_URL}/getFile?file_id={file_id}", timeout=15).json()
        if not get_file_resp.get("ok"):
            send_message(chat_id, "❌ Dosya Telegram sunucularından indirilemedi.", reply_to_message_id=msg_id)
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
        requests.post(
            f"{API_URL}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_to_message_id": msg_id
            },
            files={"document": (file_name, output_buffer.getvalue(), "image/png")},
            timeout=30
        )

    except Exception as e:
        print(f"İşlem hatası: {e}")
        send_message(chat_id, f"❌ Görsel işlenirken bir hata oluştu: {str(e)}", reply_to_message_id=msg_id)

def main():
    print("=" * 55)
    print("🤖 Instagram Post Telegram Botu Başlatıldı!")
    print(f"🔗 Bot Kullanıcı Adı: @denemekick_bot")
    print("=" * 55)
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
                time.sleep(1)
        except requests.exceptions.RequestException:
            time.sleep(2)
        except Exception as e:
            print(f"Döngü hatası: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
