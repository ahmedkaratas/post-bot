#!/usr/bin/env python3
"""
Tweet Küratörü ve Yapay Zeka Editör Ajanı (TweetCuratorAgent)
Agency Agents prensipleriyle (agency-trend-researcher, agency-narrative-designer, agency-content-creator):
1. Tweet Havuzu Analizi: Tweetleri virallik, mizah ve Instagram kaydırmalı post uyumuna göre puanlar.
2. Akıllı Yorum Seçimi: Beğeni sayısı yerine en komik, en zeki veya ters köşe yorumları seçer.
3. Instagram Başlık Üretimi: Paylaşılmaya hazır caption ve algoritma dostu hashtag üretir.
"""

import re
import json
import requests
from video_curator_agent import get_ai_config, GEMINI_MODELS_CASCADE, detect_ad_or_spam

def evaluate_tweet_for_instagram(tweet_dict: dict) -> dict:
    """
    Tweetin Instagram kitlesine uygunluğunu, mizah/hikaye potansiyelini puanlar.
    Dönüş: {"approved": bool, "score": 1-10, "reason": str}
    """
    text = tweet_dict.get("text", "").strip()
    author = tweet_dict.get("author", "")
    likes = tweet_dict.get("likes", 0)

    # 1. Aşama: Hızlı Anti-Spam / Reklam Kontrolü
    is_spam, spam_reason = detect_ad_or_spam(text)
    if is_spam:
        return {"approved": False, "score": 0, "reason": f"Reklam/Spam: {spam_reason}"}

    cfg = get_ai_config()

    prompt = (
        f"Sen bir Instagram içerik stratejistisin (Agency Agents - Trend Researcher).\n"
        f"Aşağıdaki tweeti Instagram'da 1080x1350 kaydırmalı post olarak paylaşmak üzere değerlendir:\n"
        f"Yazar: @{author} (Beğeni: {likes:,})\n"
        f"Tweet Metni: \"{text[:400]}\"\n\n"
        f"Kriterler:\n"
        f"- Mizahi, zekice bir tespit, ilginç bir hikaye veya tartışma yaratan içerikler YÜKSEK PUAN (8-10) almalıdır.\n"
        f"- Kuru haber başlığı, siyasi polemik, anlamsız linç, reklam veya tek kelimelik içerikler DÜŞÜK PUAN almalı veya REDDEDİLMELİDİR.\n\n"
        f"Yalnızca şu JSON formatında cevap ver:\n"
        f'{{"approved": true/false, "score": 1-10, "reason": "kısa açıklama"}}'
    )

    if cfg["gemini_key"]:
        for model_name in GEMINI_MODELS_CASCADE:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=10
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        return {
                            "approved": bool(parsed.get("approved", True)),
                            "score": int(parsed.get("score", 7)),
                            "reason": parsed.get("reason", "Gemini AI tarafından onaylandı"),
                            "model": model_name
                        }
                elif resp.status_code in (429, 503, 404):
                    continue
            except Exception:
                continue

    # Fallback: Kural Tabanlı Puanlama
    score = 7
    if len(text) > 40:
        score += 1
    if likes > 10000:
        score += 1
    return {
        "approved": True,
        "score": score,
        "reason": "Kural Tabanlı Güvenlik Onayı.",
        "model": "heuristic"
    }

def curate_smart_replies_and_caption(main_tweet: dict, replies: list) -> dict:
    """
    Ana tweet ve gelen yorumları inceleyerek:
    1. En komik, en zeki veya ters köşe en iyi 2-3 yorumu seçer.
    2. Instagram için hazır gönderi metni (caption) ve hashtag üretir.
    Dönüş: {"selected_replies": list, "instagram_caption": str}
    """
    if not replies:
        return {
            "selected_replies": [],
            "instagram_caption": "Sizce kim haklı? Düşüncelerinizi yorumlarda belirtin! 👇\n\n#kesfet #instagram #mizah"
        }

    cfg = get_ai_config()
    main_text = main_tweet.get("text", "")
    author = main_tweet.get("author", "")

    # Yorum özetini hazırla
    replies_summary = []
    for idx, r in enumerate(replies[:8], start=1):
        r_author = r.get("author", {}).get("screen_name", "user")
        r_text = r.get("text", "").replace("\n", " ")
        r_likes = r.get("likes", 0)
        replies_summary.append(f"[{idx}] @{r_author} (❤️ {r_likes}): \"{r_text}\"")

    summary_str = "\n".join(replies_summary)

    prompt = (
        f"Sen bir viral Instagram gönderi editörüsün (Agency Agents - Narrative Designer & Content Creator).\n"
        f"Ana Tweet (@{author}): \"{main_text}\"\n\n"
        f"Yorumlar:\n{summary_str}\n\n"
        f"Görevin:\n"
        f"1. Bu yorumlar arasından ana tweeti en iyi tamamlayan, en komik veya en zeki EN FAZLA 3 yorumun indeks numaralarını seç (örn: [1, 3]).\n"
        f"2. Instagram için etkileşim alacak hazır, esprili bir gönderi açıklaması (caption) ve 5 niş hashtag yaz.\n\n"
        f"Yalnızca şu JSON formatında cevap ver:\n"
        f'{{"selected_indices": [1, 2], "caption": "Instagram hazır açıklama metni ve hashtagler"}}'
    )

    if cfg["gemini_key"]:
        for model_name in GEMINI_MODELS_CASCADE:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=12
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        indices = parsed.get("selected_indices", [1, 2])
                        selected = []
                        for i in indices:
                            if isinstance(i, int) and 1 <= i <= len(replies):
                                selected.append(replies[i - 1])
                        if not selected:
                            selected = replies[:3]

                        return {
                            "selected_replies": selected,
                            "instagram_caption": parsed.get("caption", "Düşünceleriniz neler? Yorumlarda buluşalım! 👇"),
                            "model": model_name
                        }
                elif resp.status_code in (429, 503, 404):
                    continue
            except Exception:
                continue

    # Fallback: En çok beğenilen ilk 3 yorum
    return {
        "selected_replies": replies[:3],
        "instagram_caption": "Siz bu konuda ne düşünüyorsunuz? Yorumlarda buluşalım! 👇\n\n#kesfet #mizah #gündem",
        "model": "heuristic"
    }
