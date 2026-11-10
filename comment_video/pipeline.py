#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py: Komik Yorum Videosu Oluşturucu Ana Orkestratörü.
Bağlantıdan medyayı alır, seçilen yorumları görselleştirir,
Edge-TTS ile seslendirir ve FFmpeg ile kurgulanmış final videosunu üretir.
"""

import os
import sys
import tempfile
import shutil
try:
    from .fetcher import fetch_post_and_comments
    from .renderer import render_comment_card
    from .tts import generate_speech
    from .composer import build_composite_video
    from .video_config import get_min_likes
except ImportError:
    from fetcher import fetch_post_and_comments
    from renderer import render_comment_card
    from tts import generate_speech
    from composer import build_composite_video
    from video_config import get_min_likes

def create_funny_comments_video(
    url: str,
    selected_indices: list = None,  # Örneğin [0, 1, 2, 3, 4] seçilen ilk 5 yorum
    output_path: str = None,
    min_likes: int = None,
    pre_fetched_data: dict = None,
    progress_callback = None
) -> dict:
    """
    Tüm süreci uçtan uca çalıştırır:
    1. Medyayı indirir ve yorumları toplar.
    2. Kullanıcının seçtiği yorumları işler (belirtilmemişse en çok beğeni alan ilk 3 yorumu alır).
    3. Her yorum için kristal netliğinde PNG kartı üretir.
    4. Her yorum için Türkçe doğal TTS sesi üretir.
    5. FFmpeg ile videoyu kurgular (dondurma + seslendirme + 2.5s normal oynatım döngüsü).
    """
    work_dir = tempfile.mkdtemp(prefix="pipeline_run_")
    
    def report(step: str):
        print(f"[Pipeline] {step}")
        if progress_callback:
            try:
                progress_callback(step)
            except Exception:
                pass

    try:
        if pre_fetched_data:
            fetch_res = pre_fetched_data
        else:
            effective_min_likes = min_likes if min_likes is not None else get_min_likes()
            report(f"📥 Gönderi ve yorumlar analiz ediliyor (Min Beğeni: {effective_min_likes:,})...")
            fetch_res = fetch_post_and_comments(url, min_likes=effective_min_likes, working_dir=work_dir)

        if "error" in fetch_res:
            return {"success": False, "error": fetch_res["error"]}

        comments = fetch_res.get("comments") or []
        if not comments:
            return {"success": False, "error": "Gönderide uygun yorum bulunamadı."}

        report(f"✅ Toplam {len(comments)} popüler yorum tespit edildi.")

        # Hangi yorumlar kullanılacak?
        if selected_indices is not None and len(selected_indices) > 0:
            target_comments = [comments[i] for i in selected_indices if i < len(comments)]
        else:
            # Varsayılan: En çok beğeni alan ilk 5 yorum
            target_comments = comments[:5]

        if not target_comments:
            target_comments = comments[:1]

        # Her yorum için PNG kart ve TTS sesi üret
        prepared_data = []
        for idx, c in enumerate(target_comments, start=1):
            report(f"🎨 [{idx}/{len(target_comments)}] Yorum görseli ve sesi üretiliyor (@{c['author_handle']})...")
            
            # 1. PNG Kart
            card_png = os.path.join(work_dir, f"card_{idx:02d}.png")
            render_comment_card(
                author_name=c.get("author_name", "Kullanıcı"),
                author_handle=c.get("author_handle", "user"),
                comment_text=c["text"],
                like_count=c["likes"],
                avatar_url=c.get("avatar_url", ""),
                platform=fetch_res["platform"],
                output_path=card_png
            )

            # 2. TTS Sesi
            audio_mp3 = os.path.join(work_dir, f"audio_{idx:02d}.mp3")
            dur = generate_speech(c["text"], audio_mp3)

            prepared_data.append({
                "card_png": card_png,
                "audio_mp3": audio_mp3,
                "audio_duration": dur,
                "comment": c
            })

        # 3. Final Video Kurgusu
        if not output_path:
            output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", f"final_output_{fetch_res['post_id']}.mp4")

        report("🎬 FFmpeg ile video kurgulanıyor (Kronolojik Akış + Eşit Aralıklar)...")
        success = build_composite_video(
            background_media=fetch_res["media_path"],
            is_video=fetch_res["is_video"],
            comments_data=prepared_data,
            output_video_path=output_path
        )

        if success and os.path.exists(output_path):
            report(f"🎉 Final video hazır: {output_path}")
            return {
                "success": True,
                "video_path": output_path,
                "comments_used": len(prepared_data),
                "total_found": len(comments)
            }
        else:
            return {"success": False, "error": "Video montajı sırasında bir hata oluştu."}

    finally:
        # Geçici çalışma dizinini temizle (Final çıktıyı koru)
        shutil.rmtree(work_dir, ignore_errors=True)
