#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts.py: Yorum metinlerini Microsoft Edge-TTS ile seslendiren modül.
Geliştirme aşamasında sıfır maliyetli ve ultra hızlı Türkçe doğal ses üretir.
İleride ElevenLabs'a tek satırla geçiş desteği hazırdır.
"""

import os
import asyncio
import subprocess
import edge_tts

DEFAULT_VOICE = "tr-TR-AhmetNeural"  # Alternatif: tr-TR-EmelNeural

async def _synthesize_edge(text: str, voice: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def get_audio_duration(audio_path: str) -> float:
    """ffprobe ile ses dosyasının tam süresini saniye cinsinden döner."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ]
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception as e:
        print(f"[TTS] ffprobe süre ölçüm hatası: {e}")
        return 3.0

def trim_trailing_silence(audio_path: str):
    """Edge-TTS'in dosya sonuna eklediği ~1.1 saniyelik boş sessizliği sıyırır."""
    ffmpeg_bin = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
    tmp_trimmed = audio_path + ".trimmed.mp3"
    cmd = [
        ffmpeg_bin, "-y",
        "-i", audio_path,
        "-af", "areverse,silenceremove=start_periods=1:start_silence=0.05:start_threshold=-35dB,areverse",
        tmp_trimmed
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(tmp_trimmed) and os.path.getsize(tmp_trimmed) > 1000:
            os.replace(tmp_trimmed, audio_path)
    except Exception as e:
        print(f"[TTS] Sessizlik kırpma hatası: {e}")

def generate_speech(text: str, output_path: str, voice: str = DEFAULT_VOICE) -> float:
    """
    Verilen metni seslendirir, sonundaki boş sessizliği atar,
    output_path dosyasına kaydeder ve üretilen sesin tam süresini (float saniye) döner.
    """
    clean_text = text.strip()
    if not clean_text:
        clean_text = "..."

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    asyncio.run(_synthesize_edge(clean_text, voice, output_path))
    trim_trailing_silence(output_path)
    duration = get_audio_duration(output_path)
    print(f"[TTS] Ses üretildi ({duration:.2f}s): {output_path}")
    return duration

if __name__ == "__main__":
    test_out = "/tmp/test_tts.mp3"
    d = generate_speech("Abi bu video ne böyle, gülmekten yarıldım!", test_out)
    print(f"Test başarılı. Süre: {d} sn")
