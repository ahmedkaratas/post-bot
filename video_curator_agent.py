#!/usr/bin/env python3
"""
Video Küratörü ve Kalite Denetçisi Ajanı (ShortVideoCuratorAgent)
Agency Agents prensipleriyle (agency-short-video-editing-coach, agency-reality-checker):
1. Format & Boyut Denetimi: Yalnızca dikey (9:16 / Reels) videoları kabul eder; yatay veya kare videoları eler.
2. Anti-Reklam & Anti-Spam: Reklam, sponsorluk, ürün satışı, bahis, borsa dolandırıcılığı ve çekilişleri ayıklar.
3. AI Destekli Analiz: APMix AI (veya OpenAI uyumlu) API ile video açıklamasını denetler.
"""

import os
import re
import json
import requests

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_ai_config():
    """AI sağlayıcı ayarlarını yalnızca Coolify/container environment değişkenlerinden okur."""
    return {
        "gemini_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "ai_api_key": os.getenv("AI_API_KEY", "").strip(),
        "base_url": os.getenv("AI_BASE_URL", "https://api.apmix.ai/v1").strip().rstrip("/"),
        "ai_model": os.getenv("AI_MODEL", "claude-sonnet-4-6").strip()
    }

# -------------------------------------------------------------
# 1. KURAL: FORMAT VE BOYUT DENETİMİ (DİKEY 9:16 REELS)
# -------------------------------------------------------------

def is_vertical_reels_format(width_or_dict, height: int = 0) -> tuple[bool, str]:
    """
    Videonun Instagram Reels / TikTok dikey boyutuna uygunluğunu denetler.
    Standart Reels: 9:16 (0.5625 en/boy oranı, yani height / width = 1.77).
    Tolerans: Dikey olmalı (height > width) ve height / width >= 1.25.
    width_or_dict: int genişlik veya {"width": ..., "height": ...} sözlüğü kabul eder.
    """
    if isinstance(width_or_dict, dict):
        width = int(width_or_dict.get("width") or 0)
        height = int(width_or_dict.get("height") or 0)
    else:
        width = int(width_or_dict or 0)
        height = int(height or 0)
    if not width or not height or width <= 0 or height <= 0:
        # Boyut bilgisi yoksa şimdilik geçir (fallback)
        return True, "Boyut bilgisi belirtilmemiş."

    # Yatay video kontrolü (Eni boyundan büyükse kesinlikle Reels değildir)
    if width >= height:
        ratio = round(width / height, 2)
        return False, f"Yatay veya kare video ({width}x{height}, oran: {ratio}:1). Reels boyutu (9:16 dikey) değil."

    ratio = height / width
    # Gerçek 9:16 Reels oranı: height / width = 1.77 (16:9 dikey)
    # 4:5 (1.25) veya 3:4 (1.33) oranlarındaki dikey videolar Instagram Post (Gönderi) formatıdır, Reels değildir!
    # Minimum 1.50 dikey oran şartı koyarak post boyutundaki videoları eliyoruz.
    if ratio < 1.50:
        return False, f"Post formatında dikey video ({width}x{height}, oran: {round(ratio, 2)}:1). Gerçek 9:16 Reels formatı (en az 1.50 oran) değil."

    return True, f"Geçerli dikey Reels formatı ({width}x{height}, oran: {round(ratio, 2)})."

# -------------------------------------------------------------
# 2. KURAL: ANTİ-REKLAM, ANTİ-SPAM VE KALİTE FİLTRESİ
# -------------------------------------------------------------

# Kesin ret (Hard Ban) gerektiren ifadeler: Bu kelimeler geçiyorsa içerik anında elenir.
HARD_BAN_KEYWORDS = [
    # Reklam ve İş birliği
    r"#reklam\b", r"#işbirliği\b", r"#isbirligi\b", r"#sponsorlu\b", r"\bsponsorlu\b",
    r"\biş birliği\b", r"\bisbirligi\b", r"\bindirim kodu\b", r"\bkupon kodu\b", r"\bhediye çeki\b",
    # Doğrudan Satış / Profil Linki
    r"\blinki profilde\b", r"\blink biyografide\b", r"\bbio'daki link\b", r"\bbiodaki link\b",
    r"\bprofildeki link\b", r"\bprofildeki linkten\b",
    # Dolandırıcılık, Kumar, Bahis, Kripto Sinyal
    r"\bbahis\b", r"\bkumar\b", r"\bslot\b", r"\bcasino\b",
    r"\bdeneme bonusu\b", r"\byatırımsız kazanç\b", r"\byatırım tavsiyesi\b",
    r"\bgünlük kazanç\b", r"\bevdən qazanc\b",
    # Çekiliş ve Takipçi Tuzağı
    r"\bçekiliş\b", r"\bcekilis\b", r"\bhediye ediyoruz\b", r"\bbu gönderiyi beğen ve kaydet\b",
    r"\btakip et kazan\b"
]

# Şüpheli ifadeler: Komik veya meşru içerikte de geçebileceği için kesin ret değil, puan cezası (-2) uygulanır.
SUSPICIOUS_KEYWORDS = [
    r"\bwhatsapp\b", r"\btelegram\b", r"\btrendyol\b", r"\bhepsiburada\b", r"\bamazon link\b",
    r"\bkripto\b", r"\bforex\b", r"\bsatın al\b", r"\bsipariş için\b", r"\bfiyat için dm\b",
    r"\bdm atın\b", r"\bdm'den yazın\b"
]

HARD_BAN_REGEX = re.compile("|".join(HARD_BAN_KEYWORDS), re.IGNORECASE)
SUSPICIOUS_REGEX = re.compile("|".join(SUSPICIOUS_KEYWORDS), re.IGNORECASE)

def detect_ad_or_spam(text: str, metadata: dict = None) -> tuple[bool, str]:
    """
    Video açıklamasında veya meta verisinde KESİN RET gerektiren reklam/spam tespiti yapar.
    """
    if metadata:
        if metadata.get("is_promoted"):
            return True, "Twitter/X Promoted (sponsorlu) reklam işareti tespit edildi."
        if metadata.get("is_paid_partnership"):
            return True, "Sponsorlu iş birliği etiketi (is_paid_partnership) tespit edildi."
        if metadata.get("sponsor_tags"):
            return True, "Sponsor etiketi (sponsor_tags) tespit edildi."

    if not text:
        return False, "Metin boş."

    match = HARD_BAN_REGEX.search(text)
    if match:
        return True, f"Kesin reklam/spam ifadesi tespit edildi: '{match.group(0)}'"

    return False, "Temiz içerik."

def calculate_ad_penalty(text: str) -> int:
    """Şüpheli ticari kelimeler geçiyorsa ceza puanı döner (örn: -2)."""
    if not text:
        return 0
    matches = SUSPICIOUS_REGEX.findall(text)
    return min(4, len(matches) * 2)

# -------------------------------------------------------------
# 3. KURAL: AI DESTEKLİ VİRAL VE KALİTE DEĞERLENDİRMESİ
# -------------------------------------------------------------

# Google Gemini API doğrulanmış aktif model basamakları:
GEMINI_MODELS_CASCADE = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest"
]

def evaluate_video_with_ai(title: str, text: str, author: str = "", platform: str = "reels", metrics: dict = None, thumbnail_url: str = None) -> dict:
    """
    Videonun kalitesini, virallik potansiyelini, Türkçe olup olmadığını ve reklam durumunu Gemini ile puanlar.
    Varsa video kapak görselini (thumbnail) multimodal olarak modele verir.
    """
    cfg = get_ai_config()
    combined_text = f"{title} {text}".strip()
    metrics = metrics or {}

    # 1. Aşama: Hızlı Kural Tabanlı Kesin Ret Kontrolü
    is_spam, spam_reason = detect_ad_or_spam(combined_text, metrics)
    if is_spam:
        return {
            "is_approved": False,
            "quality_score": 0,
            "reason": f"Kural Tabanlı Eleme: {spam_reason}",
            "source": "rule_filter"
        }

    penalty = calculate_ad_penalty(combined_text)

    # Metrikleri ve oranları hazırla
    views = metrics.get("plays") or metrics.get("views") or 0
    likes = metrics.get("likes") or 0
    retweets = metrics.get("retweets") or 0
    comments = metrics.get("replies") or 0
    likes_per_view = f"{(likes / views * 100):.2f}%" if views > 0 else "Bilinmiyor"
    comments_per_like = f"{(comments / likes * 100):.2f}%" if likes > 0 else "Bilinmiyor"

    metrics_str = (
        f"- İzlenme/Oynatma: {views:,}\n"
        f"- Beğeni: {likes:,}\n"
        f"- Yorum: {comments:,}\n"
        f"- Retweet/Paylaşım: {retweets:,}\n"
        f"- Beğeni/İzlenme Oranı: {likes_per_view}\n"
        f"- Yorum/Beğeni Oranı: {comments_per_like}"
    )

    # Aşama 3: Altın kütüphaneden Few-Shot video öğrenme örneklerini çek
    few_shot_section = ""
    try:
        from history_store import history_store
        few_shot_section = history_store.format_few_shot_prompt_section(source_type="video")
    except Exception:
        pass

    prompt = (
        f"Sen sosyal medya ve kısa video uzmanısın (Agency Agents - Short Video Curator).\n"
        f"Platform: {platform}\n"
        f"Yazar: @{author}\n"
        f"Video Açıklaması: \"{combined_text[:400] if combined_text else '(Açıklama metni yok / sadece video/emoji)'}\"\n\n"
        f"Sayısal Performans Metrikleri:\n{metrics_str}\n"
        f"{few_shot_section}\n\n"
        f"Değerlendirme Kuralları:\n"
        f"1. TÜRKÇE KONTROLÜ (is_turkish): Video metni, içeriği, esprisi veya hedef kitlesi Türkçe/Türkiye odaklı mı? "
        f"Yabancı veya dili belirsiz içerikleri KESİNLİKLE reddet (is_turkish: false).\n"
        f"2. REKLAM KONTROLÜ (is_ad): Gizli reklam, ürün pazarlama, bahis, spam veya yönlendirme var mı? Varsa is_ad: true yap.\n"
        f"3. KALİTE VE VİRALLİK (score 1-10): İnsanların birbirine DM ile göndereceği, merak uyandıran, komik veya düşündürücü videolara 8-10 ver.\n"
        f"4. REFERANS ÖĞRENİMİ: Yukarıda verilen gerçek tutan/tutmayan video örneklerini dikkate alarak benzer dinamikleri ödüllendir veya cezalandır.\n"
        f"5. Yalnızca is_turkish: true, is_ad: false ve score >= 7 olanları approved: true olarak onayla.\n\n"
        f"Yalnızca şu JSON formatında cevap ver:\n"
        f'{{"approved": true, "score": 8, "is_turkish": true, "is_ad": false, "reason": "kısa açıklama"}}'
    )

    # 2. Aşama: Google Gemini API (Multimodal Kapak Desteği ve Cascade)
    if cfg["gemini_key"]:
        # Varsa kapak görselini (thumbnail) indirip base64 yap
        thumbnail_part = None
        if thumbnail_url:
            try:
                import base64
                img_resp = requests.get(thumbnail_url, timeout=5)
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    b64_data = base64.b64encode(img_resp.content).decode("utf-8")
                    mime = img_resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
                    thumbnail_part = {"inlineData": {"mimeType": mime, "data": b64_data}}
            except Exception as e:
                print(f"Video thumbnail indirme atlandı ({thumbnail_url[:40]}...): {e}")

        parts = [{"text": prompt}]
        if thumbnail_part:
            parts.append(thumbnail_part)

        for model_name in GEMINI_MODELS_CASCADE:
            try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                g_payload = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2
                    }
                }
                g_resp = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json=g_payload, timeout=12)
                if g_resp.status_code == 200:
                    raw_text = g_resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(raw_text)
                    is_tr = bool(parsed.get("is_turkish", True))
                    is_ad_found = bool(parsed.get("is_ad", False))
                    raw_score = int(parsed.get("score", 7)) - penalty
                    final_score = max(1, min(10, raw_score))
                    approved = bool(parsed.get("approved", True)) and is_tr and not is_ad_found and final_score >= 7

                    return {
                        "is_approved": approved,
                        "quality_score": final_score,
                        "reason": parsed.get("reason", f"Gemini AI ({model_name}) analizi"),
                        "source": f"gemini_{model_name}"
                    }
                else:
                    print(f"⚠️ Gemini API [{model_name}] hata: HTTP {g_resp.status_code} - {g_resp.text[:120]}")
                    continue
            except Exception as ex:
                print(f"⚠️ Gemini API [{model_name}] bağlantı hatası: {ex}")
                continue

    # AI başarısız olursa sert filtre gereği kural tabanlı otomatik onay vermiyoruz
    return {
        "is_approved": False,
        "quality_score": 0,
        "reason": "AI modelleri yanıt vermedi veya içerik onaylanmadı. Kural tabanlı otomatik onay devre dışı.",
        "source": "none"
    }
    if cfg["ai_api_key"]:
        try:
            headers = {
                "Authorization": f"Bearer {cfg['ai_api_key']}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": cfg["ai_model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 120,
                "temperature": 0.2
            }
            url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
            resp = requests.post(url, headers=headers, json=payload, timeout=8)

            if resp.status_code == 200:
                raw_reply = resp.json()["choices"][0]["message"]["content"].strip()
                json_match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    return {
                        "is_approved": bool(parsed.get("approved", True)),
                        "quality_score": int(parsed.get("score", 7)),
                        "reason": parsed.get("reason", "APMix AI tarafından onaylandı"),
                        "source": "apmix_agent"
                    }
        except Exception:
            pass

    # 4. Aşama: Kural Tabanlı Uzman Puanlama (Heuristic / Agency Reality-Checker Fallback)
    score = 7
    if len(combined_text) > 15:
        score += 1
    if combined_text.count("#") > 12:
        score -= 2

    return {
        "is_approved": True,
        "quality_score": max(1, min(10, score)),
        "reason": "Kural Tabanlı Güvenlik Onayı (Temiz, reklamsız içerik).",
        "source": "heuristic_agent"
    }

def filter_and_rank_videos(video_list: list, platform: str = "reels") -> list:
    """
    Aday video listesini inceler:
    1. Dikey Reels formatında olmayanları eler.
    2. Reklam ve spam olanları eler.
    3. En popüler ilk 5 adayı seçip yalnızca onları AI ile puanlar (Performans & Kota Tasarrufu).
    """
    # 1. Format ve Reklam Filtresi
    pre_filtered = []
    for v in video_list:
        width = v.get("width", 0)
        height = v.get("height", 0)

        # Format kontrolü (Dikey Reels mi?)
        is_vert, _ = is_vertical_reels_format(width, height)
        if not is_vert:
            continue

        # Reklam & Spam kontrolü
        text = v.get("caption") or v.get("text") or ""
        meta = {
            "is_paid_partnership": v.get("is_paid_partnership", False),
            "sponsor_tags": v.get("sponsor_tags", [])
        }
        is_ad, _ = detect_ad_or_spam(text, meta)
        if is_ad:
            continue

        pre_filtered.append(v)

    if not pre_filtered:
        return []

    # Popülerliğe göre ön sıralama (En yüksek beğeni/izlenme en başta)
    pre_filtered.sort(
        key=lambda x: (x.get("plays", 0) or x.get("views", 0), x.get("likes", 0)),
        reverse=True
    )

    # 2. Yalnızca en popüler ilk 5 adayı AI ile detaylı incele
    approved = []
    candidates_to_eval = pre_filtered[:5]
    for v in candidates_to_eval:
        text = v.get("caption") or v.get("text") or ""
        thumb_url = v.get("video_thumbnail") or v.get("thumbnail_url") or v.get("image_url") or v.get("display_url")
        metrics = {
            "plays": v.get("plays", 0) or v.get("views", 0),
            "likes": v.get("likes", 0),
            "replies": v.get("replies", 0) or v.get("comment_count", 0),
            "retweets": v.get("retweets", 0)
        }
        ai_res = evaluate_video_with_ai(
            title="",
            text=text,
            author=v.get("username") or v.get("author") or "",
            platform=platform,
            metrics=metrics,
            thumbnail_url=thumb_url
        )
        if not ai_res.get("is_approved"):
            continue

        v["curator_score"] = ai_res.get("quality_score", 5)
        v["curator_reason"] = ai_res.get("reason", "")
        v["curator_source"] = ai_res.get("source", "rules")
        approved.append(v)

    # Sert filtre kuralı: Eğer AI tüm adayları reddettiyse, zorlama fallback yapma (boş dön)
    if not approved:
        return []

    # Son sıralama: Küratör kalite puanı ve etkileşim
    approved.sort(
        key=lambda x: (
            x.get("curator_score", 5),
            x.get("plays", 0) or x.get("views", 0),
            x.get("likes", 0)
        ),
        reverse=True
    )
    return approved
