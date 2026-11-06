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
from video_curator_agent import get_ai_config, GEMINI_MODELS_CASCADE, detect_ad_or_spam, calculate_ad_penalty

def evaluate_tweet_for_instagram(tweet_dict: dict) -> dict:
    """
    Tweetin Instagram kitlesine uygunluğunu, mizah/hikaye potansiyelini,
    Türkçe olup olmadığını ve reklam durumunu Gemini ile puanlar.
    Dönüş: {"approved": bool, "score": 1-10, "reason": str, "model": str}
    """
    text = tweet_dict.get("text", "").strip()
    author = tweet_dict.get("author", "")
    likes = tweet_dict.get("likes", 0)
    views = tweet_dict.get("views", 0)
    replies = tweet_dict.get("replies", 0)
    retweets = tweet_dict.get("retweets", 0)
    quotes = tweet_dict.get("quotes", 0)
    bookmarks = tweet_dict.get("bookmarks", 0)
    lang = (tweet_dict.get("lang") or "").strip().lower()

    # 1. Aşama: Sponsorlu / Promoted Reklam Kontrolü
    if tweet_dict.get("is_promoted"):
        return {"approved": False, "score": 0, "reason": "Sponsorlu reklam (Twitter Promoted) içeriği elendi.", "model": "rule_filter"}

    # 2. Aşama: Dil Kontrolü (legacy.lang == "tr" şartı)
    if lang and lang != "tr":
        return {"approved": False, "score": 0, "reason": f"Yabancı dil içeriği ({lang}) elendi.", "model": "rule_filter"}

    # 3. Aşama: Hızlı Anti-Spam / Kesin Ret Kontrolü
    is_spam, spam_reason = detect_ad_or_spam(text, tweet_dict)
    if is_spam:
        return {"approved": False, "score": 0, "reason": f"Reklam/Spam: {spam_reason}", "model": "rule_filter"}

    penalty = calculate_ad_penalty(text)
    cfg = get_ai_config()

    # Oranları hesapla
    likes_per_view = f"{(likes / views * 100):.2f}%" if views > 0 else "Bilinmiyor"
    bookmarks_per_like = f"{(bookmarks / likes * 100):.2f}%" if likes > 0 else "Bilinmiyor"
    replies_per_like = f"{(replies / likes * 100):.2f}%" if likes > 0 else "Bilinmiyor"

    metrics_str = (
        f"- Beğeni: {likes:,}\n"
        f"- Görüntülenme: {views:,}\n"
        f"- Yorum Sayısı: {replies:,}\n"
        f"- Retweet: {retweets:,}\n"
        f"- Alıntı: {quotes:,}\n"
        f"- Kaydetme (Bookmark): {bookmarks:,}\n"
        f"- Beğeni/İzlenme Oranı: {likes_per_view}\n"
        f"- Kaydetme/Beğeni Oranı: {bookmarks_per_like}\n"
        f"- Yorum/Beğeni Oranı: {replies_per_like}"
    )

    prompt = (
        f"Sen bir Instagram içerik stratejistisin (Agency Agents - Trend Researcher).\n"
        f"Aşağıdaki tweeti Instagram'da 1080x1350 kaydırmalı post olarak paylaşmak üzere değerlendir:\n"
        f"Yazar: @{author}\n"
        f"Tweet Metni: \"{text[:400]}\"\n\n"
        f"Performans ve Etkileşim Metrikleri:\n{metrics_str}\n\n"
        f"Kriterler:\n"
        f"1. TÜRKÇE KONTROLÜ (is_turkish): Tweet Türkçe veya Türkiye odaklı kültürel mizah/durum tespiti mi? Yabancı ise kesinlikle false yap.\n"
        f"2. REKLAM KONTROLÜ (is_ad): Gizli reklam, link satışı, ürün veya sinyal pazarlaması var mı? Varsa is_ad: true yap.\n"
        f"3. VİRALLİK & MİZAH (score 1-10): Arkadaşa DM atılacak, güldüren veya tartışma yaratan zekice tweetlere 8-10 ver.\n"
        f"4. Yalnızca is_turkish: true, is_ad: false ve score >= 7 olanları approved: true olarak onayla.\n\n"
        f"Yalnızca şu JSON formatında cevap ver:\n"
        f'{{"approved": true, "score": 8, "is_turkish": true, "is_ad": false, "reason": "kısa açıklama"}}'
    )

    if cfg["gemini_key"]:
        for model_name in GEMINI_MODELS_CASCADE:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "temperature": 0.2
                        }
                    },
                    timeout=10
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(raw_text)
                    is_tr = bool(parsed.get("is_turkish", True))
                    is_ad_found = bool(parsed.get("is_ad", False))
                    raw_score = int(parsed.get("score", 7)) - penalty
                    final_score = max(1, min(10, raw_score))
                    approved = bool(parsed.get("approved", True)) and is_tr and not is_ad_found and final_score >= 7

                    return {
                        "approved": approved,
                        "score": final_score,
                        "reason": parsed.get("reason", f"Gemini AI ({model_name}) onayı"),
                        "model": model_name
                    }
                else:
                    print(f"⚠️ Gemini API [{model_name}] hata: HTTP {resp.status_code} - {resp.text[:120]}")
                    continue
            except Exception as ex:
                print(f"⚠️ Gemini API [{model_name}] bağlantı hatası: {ex}")
                continue

    # Sert filtre kuralı: Tüm AI modelleri çökerse otomatik onay verme
    return {
        "approved": False,
        "score": 0,
        "reason": "AI çalışmadı (Modeller yanıt vermedi). Kural tabanlı otomatik onay devre dışı bırakıldı.",
        "model": "none"
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
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "temperature": 0.3
                        }
                    },
                    timeout=12
                )
                if resp.status_code == 200:
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(raw_text)
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
                else:
                    print(f"⚠️ Gemini API [{model_name}] caption hata: HTTP {resp.status_code}")
                    continue
            except Exception as ex:
                print(f"⚠️ Gemini API [{model_name}] caption bağlantı hatası: {ex}")
                continue

    # Fallback: En çok beğenilen ilk 3 yorum
    return {
        "selected_replies": replies[:3],
        "instagram_caption": "Siz bu konuda ne düşünüyorsunuz? Yorumlarda buluşalım! 👇\n\n#kesfet #mizah #gündem",
        "model": "heuristic"
    }
