#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts.py: Yorum metinlerini Microsoft Edge-TTS ile seslendiren modül.
Geliştirme aşamasında sıfır maliyetli ve ultra hızlı Türkçe doğal ses üretir.
İleride ElevenLabs'a tek satırla geçiş desteği hazırdır.
"""

import os
import re
import asyncio
import subprocess
import requests
import edge_tts

DEFAULT_VOICE = "tr-TR-AhmetNeural"  # Alternatif Edge: tr-TR-EmelNeural
ELEVENLABS_DEFAULT_VOICE = "TX3LPaxmHKxFdv7VOQHJ"  # Liam (Energetic Social Media Creator)
# Alternatif ElevenLabs: "pNInz6obpgDQGcFmaJgB" (Adam - Tok & Karizmatik Erkek Sesi)

def clean_text_for_speech(text: str) -> str:
    """
    Seslendirme için metni temizler:
    1. @kullanici veya @etiketleri kaldırır (Örn: @efe.ersan.58 seslendirilmez).
    2. Emojileri temizler (Örn: 😂, 😢 vb. Edge-TTS tarafından 'güzel yüz', 'ağlayan yüz' diye okunmaz).
    3. URL linklerini temizler.
    4. Gereksiz noktalama ve boşlukları düzenler.
    """
    if not text:
        return "..."
    t = text
    # 1. @mention temizliği: @kullanici_adi, @efe.ersan.58 gibi tüm etiketleri kaldır
    t = re.sub(r'@[A-Za-z0-9_.\-]+', '', t)
    # 2. URL linklerini temizle
    t = re.sub(r'https?://\S+', '', t)
    # 3. Tüm emojileri kaldır (Unicode emoji aralıkları ve ZWJ karakterleri)
    t = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\ufe00-\ufe0f\u200d\u200c]', '', t)
    # 4. Fazla boşlukları temizle
    t = re.sub(r'\s+', ' ', t).strip()
    return t if t else "..."

async def _synthesize_edge(text: str, voice: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def _synthesize_elevenlabs(text: str, voice_id: str, output_path: str, api_key: str = None) -> bool:
    """ElevenLabs Multilingual v2 modeli ile Türkçe doğal ses üretir."""
    key = api_key or os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return False

    vid = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or ELEVENLABS_DEFAULT_VOICE
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.20,
            "use_speaker_boost": True
        }
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return True
        else:
            print(f"[TTS] ElevenLabs hatası: HTTP {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        print(f"[TTS] ElevenLabs bağlantı hatası: {e}")
    return False

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
    """Dosya sonundaki boş sessizliği sıyırır."""
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

def generate_speech(
    text: str,
    output_path: str,
    voice: str = None,
    engine: str = None,
    eleven_api_key: str = None
) -> float:
    """
    Verilen metni temizler (@mention ve emojileri çıkarır), seslendirir,
    sonundaki boş sessizliği atar, output_path dosyasına kaydeder
    ve üretilen sesin tam süresini (float saniye) döner.
    engine: 'elevenlabs' veya 'edge' (varsayılan: ELEVENLABS_API_KEY varsa 'elevenlabs' yoksa 'edge')
    """
    clean_text = clean_text_for_speech(text)
    if not clean_text or clean_text == "...":
        clean_text = "..."

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Engine tespiti
    active_engine = engine or os.getenv("TTS_ENGINE")
    if not active_engine:
        active_engine = "elevenlabs" if (eleven_api_key or os.getenv("ELEVENLABS_API_KEY")) else "edge"

    success = False
    if active_engine == "elevenlabs":
        v_id = voice or os.getenv("ELEVENLABS_VOICE_ID") or ELEVENLABS_DEFAULT_VOICE
        success = _synthesize_elevenlabs(clean_text, v_id, output_path, api_key=eleven_api_key)
        if not success:
            print("[TTS] ElevenLabs başarısız oldu veya anahtar yok, Edge-TTS fallback devreye giriyor...")

    if not success:
        active_engine = "edge"
        edge_v = voice if (voice and voice.startswith("tr-TR-")) else DEFAULT_VOICE
        asyncio.run(_synthesize_edge(clean_text, edge_v, output_path))

    trim_trailing_silence(output_path)
    duration = get_audio_duration(output_path)
    print(f"[TTS] Ses üretildi ({duration:.2f}s, motor: {active_engine}) ['{clean_text[:40]}...']: {output_path}")
    return duration

if __name__ == "__main__":
    test_out = "/tmp/test_tts.mp3"
    d = generate_speech("Abi bu video ne böyle, gülmekten yarıldım!", test_out)
    print(f"Test başarılı. Süre: {d} sn")
