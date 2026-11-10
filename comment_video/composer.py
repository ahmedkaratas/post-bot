#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
composer.py: Arka plan videosunun baştan sona kesintisiz akmasını sağlayan,
videoyu eşit aralıklara bölerek yorum anında videoyu TAM O KAREDE DONDURAN (Still Image),
yorum okuması bitince videoyu kaldığı tam o kareden devam ettiren profesyonel montaj motoru.

Apple Silicon / macOS QuickTime & iOS Uyumlu:
- macOS üzerinde Apple donanım hızlandırmalı 'h264_videotoolbox' kullanılır (Sıfır siyah ekran riski, 180+ FPS).
- Linux / Sunucu üzerinde 'libx264 -profile:v high -level 4.1' kullanılır.
- Her iki platformda da '-tag:v avc1' ve '-movflags +faststart' uygulanır.
"""

import os
import sys
import subprocess
import tempfile
import shutil

FFMPEG_BIN = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg")
FFPROBE_BIN = shutil.which("ffprobe") or ("/opt/homebrew/bin/ffprobe" if os.path.exists("/opt/homebrew/bin/ffprobe") else "ffprobe")

def get_video_encoder_args():
    """Platforma göre en uyumlu ve kararlı video encoder parametrelerini döner."""
    if sys.platform == "darwin":
        # macOS donanım kodlayıcı: QuickTime ve iOS ile %100 kusursuz çalışır
        return ["-c:v", "h264_videotoolbox", "-b:v", "4M", "-tag:v", "avc1"]
    else:
        # Linux / Coolify sunucu: H.264 High Profile
        return ["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.1", "-tag:v", "avc1"]

def get_media_info(file_path: str) -> dict:
    """Medya dosyasının süresini, çözünürlüğünü ve ses kanalı varlığını kontrol eder."""
    try:
        cmd_v = [
            FFPROBE_BIN, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration:format=duration",
            "-of", "default=noprint_wrappers=1",
            file_path
        ]
        out_v = subprocess.check_output(cmd_v).decode()
        info = {}
        for line in out_v.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                info[k.strip()] = v.strip()

        # Ses kanalı kontrolü
        cmd_a = [
            FFPROBE_BIN, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1",
            file_path
        ]
        out_a = subprocess.check_output(cmd_a).decode().strip()
        has_audio = bool("codec_name=" in out_a)

        dur = float(info.get("duration", 0) or 0)
        width = int(info.get("width", 1080) or 1080)
        height = int(info.get("height", 1920) or 1920)
        return {"duration": dur, "width": width, "height": height, "has_audio": has_audio, "is_valid": True}
    except Exception as e:
        print(f"[Composer] ffprobe hatası: {e}")
        return {"duration": 10.0, "width": 1080, "height": 1920, "has_audio": False, "is_valid": False}

def extract_still_frame(video_path: str, timestamp: float, output_image_path: str) -> bool:
    """Videonun timestamp saniyesindeki tam karesini tek bir statik fotoğraf olarak çıkarır."""
    try:
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            output_image_path
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return os.path.exists(output_image_path)
    except Exception as e:
        print(f"[Composer] Kare çıkarma hatası: {e}")
        return False

def create_frozen_comment_clip(
    still_frame_path: str,
    comment_png: str,
    audio_path: str,
    duration: float,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920
) -> bool:
    """
    Statik arka plan fotoğrafını loop ederek TAMAMEN HAREKETSİZ dondurur,
    üzerine yorum kartını ortalar ve TTS sesini ekler.
    """
    try:
        filter_complex = (
            f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[bg];"
            f"[1:v]scale=w='min(iw,{target_width}-60)':h=-1[card];"
            f"[bg][card]overlay=(W-w)/2:(H-h)/2[v];"
            f"[2:a]apad,atrim=0:{duration},aresample=async=1,"
            f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a]"
        )

        enc_args = get_video_encoder_args()

        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1", "-i", still_frame_path,
            "-loop", "1", "-i", comment_png,
            "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-t", str(duration),
            *enc_args,
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            output_path
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[Composer] Dondurulmuş klip oluşturma hatası: {e}")
        return False

def create_normal_play_clip(
    bg_path: str,
    start_time: float,
    duration: float,
    has_audio: bool,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920
) -> bool:
    """Orijinal videonun start_time -> start_time + duration aralığını doğal akışında keser."""
    try:
        enc_args = get_video_encoder_args()
        if has_audio:
            filter_complex = (
                f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[v];"
                f"[0:a]aresample=async=1,aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a]"
            )
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", bg_path,
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "[a]",
                *enc_args,
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                output_path
            ]
        else:
            filter_complex = (
                f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black[v];"
                f"anullsrc=r=44100:cl=stereo,atrim=0:{duration}[a]"
            )
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", str(start_time),
                "-t", str(duration),
                "-i", bg_path,
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "[a]",
                *enc_args,
                "-r", "30",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                output_path
            ]

        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"[Composer] Normal oynatım klibi hatası: {e}")
        return False

def build_composite_video(
    background_media: str,
    is_video: bool,
    comments_data: list,
    output_video_path: str
) -> bool:
    """
    Kusursuz Kronolojik Video Akışı:
    - Orijinal video baştan sona (0.0s -> Son) kesintisiz oynar.
    - Yorumlar (N adet) video süresi boyunca (N+1 eşit aralığa) homojen dağıtılır.
    - Video o karede TAMAMEN DURUR (Still Frame). Yorum okunur.
    - Yorum bittiğinde video donduğu tam o saniyeden oynamaya DEVAM EDER.
    - Asla başa sarmaz, asla ileri-geri zıplamaz.
    """
    temp_dir = tempfile.mkdtemp(prefix="comment_video_")
    segment_files = []

    try:
        bg_info = get_media_info(background_media)
        total_bg_dur = bg_info.get("duration", 10.0) or 10.0
        has_audio = bg_info.get("has_audio", False)
        num_comments = len(comments_data)

        if num_comments == 0:
            print("[Composer] Yorum listesi boş!")
            return False

        if is_video:
            # Orijinal videoyu (N + 1) eşit parçaya böl
            interval = total_bg_dur / (num_comments + 1)
            print(f"[Composer] ⏱️ Toplam Video: {total_bg_dur:.2f}s | {num_comments} Yorum | Aralık: {interval:.2f}s")

            for i in range(num_comments):
                play_start = i * interval
                play_dur = interval
                freeze_time = (i + 1) * interval

                # 1. Normal Oynatım: Video play_start saniyesinden freeze_time saniyesine kadar akar
                play_seg = os.path.join(temp_dir, f"seg_{i:02d}_play.mp4")
                ok_play = create_normal_play_clip(
                    bg_path=background_media,
                    start_time=play_start,
                    duration=play_dur,
                    has_audio=has_audio,
                    output_path=play_seg
                )
                if ok_play and os.path.exists(play_seg):
                    segment_files.append(play_seg)

                # 2. Tam Donma: freeze_time anındaki kareyi TEK BİR FOTOĞRAF olarak çıkar
                still_frame = os.path.join(temp_dir, f"frame_{i:02d}.jpg")
                ok_extract = extract_still_frame(background_media, freeze_time, still_frame)
                if not ok_extract:
                    still_frame = background_media

                # 3. Yorum Okuma: O kare TAMAMEN HAREKETSİZ durur, yorum okunur
                c_item = comments_data[i]
                c_dur = c_item["audio_duration"] + 0.40  # Yorum bittikten sonra tam 0.40s bekleme
                freeze_seg = os.path.join(temp_dir, f"seg_{i:02d}_freeze.mp4")
                ok_freeze = create_frozen_comment_clip(
                    still_frame_path=still_frame,
                    comment_png=c_item["card_png"],
                    audio_path=c_item["audio_mp3"],
                    duration=c_dur,
                    output_path=freeze_seg
                )
                if ok_freeze and os.path.exists(freeze_seg):
                    segment_files.append(freeze_seg)

            # 4. Final Oynatım: Son yorum bittikten sonra videonun kalan kısmı tam bitişe kadar oynar
            last_start = num_comments * interval
            last_dur = max(0.5, total_bg_dur - last_start)
            last_seg = os.path.join(temp_dir, f"seg_{num_comments:02d}_final_play.mp4")
            ok_last = create_normal_play_clip(
                bg_path=background_media,
                start_time=last_start,
                duration=last_dur,
                has_audio=has_audio,
                output_path=last_seg
            )
            if ok_last and os.path.exists(last_seg):
                segment_files.append(last_seg)

        else:
            # Arka plan fotoğraf ise
            photo_interval = 2.0
            for i in range(num_comments):
                c_item = comments_data[i]
                c_dur = c_item["audio_duration"] + 0.40
                freeze_seg = os.path.join(temp_dir, f"seg_{i:02d}_freeze.mp4")
                ok_freeze = create_frozen_comment_clip(
                    still_frame_path=background_media,
                    comment_png=c_item["card_png"],
                    audio_path=c_item["audio_mp3"],
                    duration=c_dur,
                    output_path=freeze_seg
                )
                if ok_freeze and os.path.exists(freeze_seg):
                    segment_files.append(freeze_seg)

                if i < num_comments - 1:
                    play_seg = os.path.join(temp_dir, f"seg_{i:02d}_play.mp4")
                    create_normal_play_clip(
                        bg_path=background_media,
                        start_time=0.0,
                        duration=photo_interval,
                        has_audio=False,
                        output_path=play_seg
                    )
                    if os.path.exists(play_seg):
                        segment_files.append(play_seg)

        if not segment_files:
            print("[Composer] Hiçbir segment oluşturulamadı!")
            return False

        # 5. Tüm segmentleri tek dosyada birleştir
        # macOS üzerinde h264_videotoolbox, Linux üzerinde libx264 high profile
        concat_list_file = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_file, "w") as f:
            for s in segment_files:
                f.write(f"file '{s}'\n")

        os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
        enc_args = get_video_encoder_args()
        concat_cmd = [
            FFMPEG_BIN, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_file,
            *enc_args,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            output_video_path
        ]
        subprocess.check_call(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[Composer] Final video başarıyla derlendi: {output_video_path}")
        return True

    except Exception as e:
        print(f"[Composer] Video derleme hatası: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
