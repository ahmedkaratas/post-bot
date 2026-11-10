#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli_test.py: Mac mini üzerinde sistemi doğrudan test etmek için interaktif CLI aracı.
Kullanım:
   ./venv/bin/python3 comment_video/cli_test.py "<link>"
veya parametresiz çalıştırarak sentetik test videosu üretir:
   ./venv/bin/python3 comment_video/cli_test.py
"""

import os
import sys
import subprocess
from pipeline import create_funny_comments_video
from composer import build_composite_video
from renderer import render_comment_card
from tts import generate_speech

def run_synthetic_test():
    """Gerçek internet linkine gerek olmadan tüm motoru (Kart + Edge-TTS + FFmpeg) test eder."""
    print("🚀 [Sentetik Test] Örnek bir video ve 2 adet komik yorumla Mac mini testi başlatılıyor...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base_dir, "temp")
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. 10 saniyelik şık bir dikey arka plan test videosu üret (FFmpeg ile)
    test_bg_video = os.path.join(out_dir, "test_background.mp4")
    print("🎥 1. Test arka plan videosu oluşturuluyor (1080x1920 dikey)...")
    cmd_bg = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:beep_factor=4",
        "-t", "10",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        test_bg_video
    ]
    subprocess.check_call(cmd_bg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 2. Örnek Yorumlar
    sample_comments = [
        {
            "name": "Burak Özkan",
            "handle": "burakozk",
            "text": "Arabanın gidişine bak resmen ışınlandı, arkadaki arkadaş hala durumu idrak etmeye çalışıyor 😂",
            "likes": 42500
        },
        {
            "name": "Selin Kaya",
            "handle": "selinkayaa",
            "text": "Bu videoyu izlerken kahvemi püskürttüm, yemin ederim haftanın en iyi içeriği net bu!",
            "likes": 18200
        }
    ]
    
    prepared = []
    for idx, c in enumerate(sample_comments, start=1):
        print(f"🎙️ 2.{idx} Yorum görseli ve Edge-TTS sesi üretiliyor: @{c['handle']} (❤️ {c['likes']:,})...")
        card_png = os.path.join(out_dir, f"test_card_{idx}.png")
        render_comment_card(
            author_name=c["name"],
            author_handle=c["handle"],
            comment_text=c["text"],
            like_count=c["likes"],
            platform="instagram",
            output_path=card_png
        )
        
        audio_mp3 = os.path.join(out_dir, f"test_audio_{idx}.mp3")
        dur = generate_speech(c["text"], audio_mp3)
        
        prepared.append({
            "card_png": card_png,
            "audio_mp3": audio_mp3,
            "audio_duration": dur
        })
        
    # 3. Kurguyu FFmpeg ile birleştir
    final_output = os.path.join(out_dir, "test_final_funny_video.mp4")
    print("🎬 3. FFmpeg ile kurgu tamamlanıyor (Dondurma + Ses + Normal Oynatım)...")
    ok = build_composite_video(
        background_media=test_bg_video,
        is_video=True,
        comments_data=prepared,
        output_video_path=final_output,
        inter_comment_play_sec=2.5
    )
    
    if ok and os.path.exists(final_output):
        fsize_mb = os.path.getsize(final_output) / (1024 * 1024)
        print("\n" + "="*50)
        print("✅ SENTETİK TEST BAŞARIYLA TAMAMLANDI!")
        print(f"📁 Oluşturulan Video: {final_output}")
        print(f"📊 Dosya Boyutu: {fsize_mb:.2f} MB")
        print("="*50)
        
        # macOS üzerinde videoyu otomatik açmak için
        if sys.platform == "darwin":
            print("👁️ Video açılıyor...")
            os.system(f"open '{final_output}'")
    else:
        print("❌ Test videosu oluşturulamadı.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = sys.argv[1].strip()
        print(f"🔗 URL Testi Başlatılıyor: {url}")
        res = create_funny_comments_video(url)
        if res.get("success"):
            print(f"🎉 Başarılı! Çıktı: {res['video_path']}")
            if sys.platform == "darwin":
                os.system(f"open '{res['video_path']}'")
        else:
            print(f"❌ Hata: {res.get('error')}")
    else:
        run_synthetic_test()
