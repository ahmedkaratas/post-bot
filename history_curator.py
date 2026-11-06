#!/usr/bin/env python3
"""
Geçmiş ve Altın Kütüphane Yapay Zeka Küratörü (HistoryCurator)
Aşama 3: Her tutan veya tutmayan post için Gemini ile 'Neden tuttu/tutmadı' analizi üretir.
Paylaşılabilirlik, tartışma/yorum ve merak/kaydırma dinamiklerini değerlendirip kütüphaneye işler.
"""

import os
import json
import threading
import requests
from history_store import history_store
from video_curator_agent import get_ai_config, GEMINI_MODELS_CASCADE

def generate_why_note(post_id: int) -> tuple[bool, str]:
    """
    Belirtilen post için Gemini ile 1-2 cümlelik (max 180 karakter)
    'Neden tuttu / tutmadı' analiz notu üretir ve kaydeder.
    """
    post = history_store.get_post(post_id)
    if not post:
        return False, "Post bulunamadı."

    res = post.get("results", {})
    tag = (res.get("tag") or "").lower()
    if not tag or tag not in ["tuttu", "tutmadi", "orta"]:
        return False, "Post henüz tuttu/tutmadı olarak etiketlenmemiş."

    text = (post.get("text", "") or post.get("caption", "")).strip()
    author = post.get("author", "bilinmiyor")
    source_type = post.get("source_type", "icerik")

    # Metrikleri derle
    views = res.get("views") or 0
    shares = res.get("shares") or 0
    saves = res.get("saves") or 0
    likes = res.get("likes") or post.get("metrics", {}).get("likes") or 0
    comments = res.get("comments") or 0

    metrics_str = f"Beğeni: {likes:,}"
    if views > 0:
        metrics_str += f" | IG İzlenme: {views:,}"
    if shares > 0:
        metrics_str += f" | Paylaşım: {shares:,}"
    if saves > 0:
        metrics_str += f" | Kaydetme: {saves:,}"
    if comments > 0:
        metrics_str += f" | Yorum: {comments:,}"

    tag_str = "TUTTU (BAŞARILI / VİRAL)" if tag == "tuttu" else ("TUTMADI (DÜŞÜK PERFORMANS)" if tag == "tutmadi" else "ORTA PERFORMANS")

    prompt = (
        f"Sen Instagram virallik ve kitle psikolojisi uzmanısın (Agency Agents - Trend Researcher & Behavioral Nudge Engine).\n"
        f"Aşağıdaki Instagram postunun kitle rezonansını ve sonucunu incele:\n\n"
        f"İçerik Türü: {source_type}\n"
        f"Yazar: @{author}\n"
        f"İçerik Metni: \"{text[:300] if text else '(Görsel/Video ağırlıklı içerik)'}\"\n"
        f"Sonuç Etiketi: {tag_str}\n"
        f"Performans Metrikleri: {metrics_str}\n\n"
        f"GÖREVİN:\n"
        f"Bu içeriğin Instagram'da NEDEN {tag.upper()} olduğunu tam olarak 1 veya en fazla 2 cümleyle (maksimum 150-180 karakter) açıkla.\n"
        f"Şu üç kritere odaklan:\n"
        f"1. Paylaşılabilirlik (Arkadaşa DM ile gönderme isteği uyandırdı mı?)\n"
        f"2. Tartışma / Yorum yaratma etkisi\n"
        f"3. Merak / Slayt kaydırma (retention) gücü\n\n"
        f"KURAL: Giriş/hitap cümlesi yazma. Doğrudan özeti söyle.\n"
        f"Örnek (Tuttu için): \"Gündelik empati kurulabilir ilişki mizahı doğrudan DM paylaşımını ve kaydetmeyi tetiklemiş; yüksek izlenme almış.\"\n"
        f"Örnek (Tutmadı için): \"Metin çok içe dönük ve niş kalmış; geniş kitlede tartışma veya arkadaşa atma refleksi yaratamamış.\"\n\n"
        f"Cevabını doğrudan bu kısa analiz metni olarak ver (tırnak veya JSON kullanma)."
    )

    cfg = get_ai_config()
    if cfg["gemini_key"]:
        for model_name in GEMINI_MODELS_CASCADE:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 200
                    }
                }
                resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=12)
                if resp.status_code == 200:
                    cand = resp.json().get("candidates", [])
                    if cand:
                        raw_note = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        # Tırnakları ve gereksiz satır başlarını temizle
                        clean_note = raw_note.strip('"\' \n')
                        if clean_note:
                            history_store.set_why_note(post_id, clean_note)
                            return True, clean_note
                else:
                    print(f"Why Note üretimi Gemini [{model_name}] hatası: HTTP {resp.status_code}")
                    continue
            except Exception as e:
                print(f"Why Note üretimi Gemini [{model_name}] istisnası: {e}")
                continue

    # Yedek heuristik not
    fallback_note = "Yüksek etkileşim ve DM paylaşım potansiyeliyle tuttu." if tag == "tuttu" else "Düşük kitle rezonansı nedeniyle yayılma sağlayamadı."
    history_store.set_why_note(post_id, fallback_note)
    return True, fallback_note

def generate_why_note_async(post_id: int, on_complete=None):
    """Arka planda çalışarak kullanıcı komutunu bekletmez."""
    def worker():
        try:
            ok, note = generate_why_note(post_id)
            if ok and on_complete:
                on_complete(post_id, note)
        except Exception as e:
            print(f"Async why note hatası (Post #{post_id}): {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
