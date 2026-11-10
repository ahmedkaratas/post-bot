#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_user_video.py: Kullanıcının verdiği Instagram Reel'i (https://www.instagram.com/p/DdzbjMhsLcX/)
ve 5 adet komik yorumla tam kurgu videosunu derleyen ve Mac mini'de açan test scripti.
"""

import os
import sys
import subprocess
from renderer import render_comment_card
from tts import generate_speech
from composer import build_composite_video

def main():
    print("🎬 Instagram Gönderisi için 5 Yorumlu Tam Video Testi Başlatılıyor...")
    
    bg_video = "/tmp/test_ig_video.mp4"
    if not os.path.exists(bg_video):
        print("📥 Orijinal Instagram videosu indiriliyor...")
        yt_cmd = ["/Users/qwerty/.local/bin/yt-dlp", "-o", bg_video, "https://www.instagram.com/p/DdzbjMhsLcX/"]
        subprocess.check_call(yt_cmd)
        
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
    os.makedirs(out_dir, exist_ok=True)
    
    # Gerçek gönderideki en komik 5 yorum
    comments = [
        {
            "name": "Taha Atasy",
            "handle": "taha_.atsy",
            "text": "Kapı gruptan ayrıldı...",
            "likes": 52400
        },
        {
            "name": "Hasret Su",
            "handle": "hasrwt_su_911",
            "text": "Abla kavgaya beni de çağır, sonuna kadar haklısın çünkü!",
            "likes": 38100
        },
        {
            "name": "Murathan",
            "handle": "mr.murathan77",
            "text": "O en son dediğin küfürü de duydum bu arada...",
            "likes": 26500
        },
        {
            "name": "Henry",
            "handle": "henryninkaslikollari",
            "text": "Böyle olamadığımız için hayatta kaybettik be abi...",
            "likes": 19800
        },
        {
            "name": "Hasan Hıdıroğlu",
            "handle": "hasan_hidirogluu",
            "text": "Bu kız evlendi mi acaba, çok merak ettim.",
            "likes": 14200
        }
    ]
    
    prepared = []
    for idx, c in enumerate(comments, start=1):
        print(f"🎙️ [{idx}/5] Yorum kartı ve Edge-TTS sesi hazırlanıyor: @{c['handle']} (❤️ {c['likes']:,})...")
        
        # 1. Kart PNG
        card_png = os.path.join(out_dir, f"ig_card_{idx}.png")
        render_comment_card(
            author_name=c["name"],
            author_handle=c["handle"],
            comment_text=c["text"],
            like_count=c["likes"],
            platform="instagram",
            output_path=card_png
        )
        
        # 2. TTS Sesi
        audio_mp3 = os.path.join(out_dir, f"ig_audio_{idx}.mp3")
        dur = generate_speech(c["text"], audio_mp3)
        
        prepared.append({
            "card_png": card_png,
            "audio_mp3": audio_mp3,
            "audio_duration": dur
        })
        
    final_output = os.path.join(out_dir, "krstina_5_comments_funny_video.mp4")
    print(f"\n🎬 [FFmpeg] 5 yorumlu video kurgulanıyor (Kronolojik Akış + Eşit Aralıklar)...")
    ok = build_composite_video(
        background_media=bg_video,
        is_video=True,
        comments_data=prepared,
        output_video_path=final_output
    )
    
    if ok and os.path.exists(final_output):
        fsize_mb = os.path.getsize(final_output) / (1024 * 1024)
        print("\n" + "="*55)
        print("🎉 5 YORUMLU VİDEO KURGUSU BAŞARIYLA TAMAMLANDI!")
        print(f"📁 Çıktı Dosyası: {final_output}")
        print(f"📊 Dosya Boyutu: {fsize_mb:.2f} MB")
        print("="*55)
        
        # macOS üzerinde videoyu otomatik aç
        if sys.platform == "darwin":
            print("👁️ Video QuickTime ile açılıyor...")
            os.system(f"open '{final_output}'")
    else:
        print("❌ Video oluşturulamadı.")

if __name__ == "__main__":
    main()
