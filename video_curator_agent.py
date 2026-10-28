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
    """Önce .env dosyasından, ardından ortam değişkenlerinden AI ayarlarını okur."""
    gemini_key = ""
    gemini_model = "gemini-flash-lite-latest"
    ai_api_key = ""
    base_url = "https://api.apmix.ai/v1"
    ai_model = "claude-sonnet-4-6"

    env_path = os.path.join(PROJECT_DIR, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k == "GEMINI_API_KEY":
                        gemini_key = v
                    elif k == "GEMINI_MODEL":
                        gemini_model = v
                    elif k == "AI_API_KEY":
                        ai_api_key = v
                    elif k == "AI_BASE_URL":
                        base_url = v
                    elif k == "AI_MODEL":
                        ai_model = v
        except Exception:
            pass

    if not gemini_key:
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not ai_api_key:
        ai_api_key = os.getenv("AI_API_KEY", "").strip()

    return {
        "gemini_key": gemini_key,
        "gemini_model": gemini_model,
        "ai_api_key": ai_api_key,
        "base_url": base_url,
        "ai_model": ai_model
    }

# -------------------------------------------------------------
# 1. KURAL: FORMAT VE BOYUT DENETİMİ (DİKEY 9:16 REELS)
# -------------------------------------------------------------

def is_vertical_reels_format(width: int, height: int) -> tuple[bool, str]:
    """
    Videonun Instagram Reels / TikTok dikey boyutuna uygunluğunu denetler.
    Standart Reels: 9:16 (0.5625 en/boy oranı, yani height / width = 1.77).
    Tolerans: Dikey olmalı (height > width) ve height / width >= 1.25.
    """
    if not width or not height or width <= 0 or height <= 0:
        # Boyut bilgisi yoksa şimdilik geçir (fallback)
        return True, "Boyut bilgisi belirtilmemiş."

    # Yatay video kontrolü (Eni boyundan büyükse kesinlikle Reels değildir)
    if width >= height:
        ratio = round(width / height, 2)
        return False, f"Yatay veya kare video ({width}x{height}, oran: {ratio}:1). Reels boyutu (9:16 dikey) değil."

    ratio = height / width
    # 4:5 dikey (1.25) veya 9:16 dikey (1.77) kabul edilir.
    if ratio < 1.20:
        return False, f"Yetersiz dikey oran ({width}x{height}, oran: {round(ratio, 2)}). Tam Reels formatında değil."

    return True, f"Geçerli dikey Reels formatı ({width}x{height}, oran: {round(ratio, 2)})."

# -------------------------------------------------------------
# 2. KURAL: ANTİ-REKLAM, ANTİ-SPAM VE KALİTE FİLTRESİ
# -------------------------------------------------------------

SPAM_KEYWORDS = [
    # Reklam ve İş birliği
    r"#reklam\b", r"#işbirliği\b", r"#isbirligi\b", r"#sponsorlu\b", r"\bsponsorlu\b",
    r"\biş birliği\b", r"\bisbirligi\b", r"\bindirim kodu\b", r"\bkupon kodu\b", r"\bhediye çeki\b",
    # Satış ve Yönlendirme
    r"\blinki profilde\b", r"\blink biyografide\b", r"\bbio'daki link\b", r"\bbiodaki link\b",
    r"\bprofildeki link\b", r"\bprofildeki linkten\b", r"\bsatın al\b", r"\bsipariş için\b",
    r"\bfiyat için dm\b", r"\bdm atın\b", r"\bdm'den yazın\b", r"\bwhatsapp\b", r"\btelegram\b",
    r"\btrendyol\b", r"\bhepsiburada\b", r"\bamazon link\b",
    # Dolandırıcılık, Bahis, Kripto Sinyal
    r"\bkripto\b", r"\bforex\b", r"\byatırım tavsiyesi\b", r"\bgünlük kazanç\b",
    r"\bevdən qazanc\b", r"\bbahis\b", r"\bkumar\b", r"\bslot\b", r"\bcasino\b",
    r"\bdeneme bonusu\b", r"\byatırımsız kazanç\b",
    # Çekiliş ve Takipçi Tuzağı
    r"\bçekiliş\b", r"\bcekilis\b", r"\bhediye ediyoruz\b", r"\bbu gönderiyi beğen ve kaydet\b",
    r"\btakip et kazan\b"
]

SPAM_REGEX = re.compile("|".join(SPAM_KEYWORDS), re.IGNORECASE)

def detect_ad_or_spam(text: str, metadata: dict = None) -> tuple[bool, str]:
    """
    Video açıklamasında veya meta verisinde reklam, spam veya dolandırıcılık tespiti yapar.
    """
    if metadata:
        if metadata.get("is_paid_partnership"):
            return True, "Sponsorlu iş birliği etiketi (is_paid_partnership) tespit edildi."
        if metadata.get("sponsor_tags"):
            return True, "Sponsor etiketi (sponsor_tags) tespit edildi."

    if not text:
        return False, "Metin boş."

    match = SPAM_REGEX.search(text)
    if match:
        return True, f"Reklam/Spam ifadesi tespit edildi: '{match.group(0)}'"

    return False, "Temiz içerik."

# -------------------------------------------------------------
# 3. KURAL: AI DESTEKLİ VİRAL VE KALİTE DEĞERLENDİRMESİ
# -------------------------------------------------------------

# Google Gemini modellerinin kalite ve kota sırasına göre basamaklı zinciri:
# En akıllı modelden başlar, kota (429) veya yoğunluk (503) durumunda anında bir alt modele devreder.
GEMINI_MODELS_CASCADE = [
    "gemini-3.8-flash",      # 1. Öncelik: En üstün akıl ve kalite (RPD: 20)
    "gemini-3.6-flash",      # 2. Öncelik: Hızlı ve yüksek kalite (RPD: 20)
    "gemini-3.5-flash-lite", # 3. Öncelik: Günde 500 İSTEK (Çok geniş kota!)
    "gemini-3.1-flash-lite", # 4. Öncelik: Günde 500 İSTEK (Geniş kota!)
    "gemma-4-26b-a4b-it"     # 5. Öncelik: Günde 14.400 İSTEK (Sınırsıza yakın!)
]

def evaluate_video_with_ai(title: str, text: str, author: str = "", platform: str = "reels") -> dict:
    """
    Öncelikle Google Gemini API'nin en üst modelinden başlayarak (gemini-3.8 -> 3.6 -> 3.5-lite -> 3.1-lite -> gemma)
    basamaklı kota devriyle videonun kalitesini ve virallik potansiyelini puanlar.
    Eğer tüm AI kotaları aşılırsa kural tabanlı Agency Reality-Checker devreye girer.
    """
    cfg = get_ai_config()
    combined_text = f"{title} {text}".strip()

    # 1. Aşama: Hızlı Regex Anti-Spam Kontrolü
    is_spam, spam_reason = detect_ad_or_spam(combined_text)
    if is_spam:
        return {
            "is_approved": False,
            "quality_score": 0,
            "reason": f"Kural Tabanlı Eleme: {spam_reason}",
            "source": "rule_filter"
        }

    prompt = (
        f"Sen sosyal medya ve kısa video uzmanısın (Agency Agents - Short Video Curator).\n"
        f"Platform: {platform}\n"
        f"Yazar: @{author}\n"
        f"Video Açıklaması: \"{combined_text[:400]}\"\n\n"
        f"Görevin: Bu videoyu Instagram Reels hesabında paylaşılmak üzere değerlendir.\n"
        f"Kriterler:\n"
        f"1. Reklam, ürün satışı, spam, bahis, dolandırıcılık veya saçma/kalitesiz içerik OLMAMALIDIR.\n"
        f"2. Mizahi, düşündürücü, merak uyandırıcı, güncel veya eğlenceli kaliteli viral içerik olmalıdır.\n\n"
        f"Yalnızca şu JSON formatında cevap ver:\n"
        f'{{"approved": true/false, "score": 1-10, "reason": "kısa açıklama"}}'
    )

    # 2. Aşama: Google Gemini API (Basamaklı Akıllı Model Zinciri)
    if cfg["gemini_key"]:
        for model_name in GEMINI_MODELS_CASCADE:
            try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cfg['gemini_key']}"
                g_payload = {"contents": [{"parts": [{"text": prompt}]}]}
                g_resp = requests.post(gemini_url, headers={"Content-Type": "application/json"}, json=g_payload, timeout=12)
                if g_resp.status_code == 200:
                    raw_text = g_resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        return {
                            "is_approved": bool(parsed.get("approved", True)),
                            "quality_score": int(parsed.get("score", 7)),
                            "reason": parsed.get("reason", f"Gemini AI ({model_name}) tarafından onaylandı"),
                            "source": f"gemini_{model_name}"
                        }
                elif g_resp.status_code in (429, 503, 404):
                    # Kota sınırı, yoğunluk veya erişilememe durumunda bir sonraki modele geç
                    continue
            except Exception:
                continue

    # 3. Aşama: APMix / OpenAI Uyumlu API (İkinci Tercih)
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
    3. AI / Heuristik kalite puanına ve popülerliğe göre en iyiden en kötüye sıralar.
    """
    approved = []

    for v in video_list:
        width = v.get("width", 0)
        height = v.get("height", 0)

        # 1. Format kontrolü (Dikey Reels mi?)
        is_vert, vert_reason = is_vertical_reels_format(width, height)
        if not is_vert:
            continue

        # 2. Reklam & Spam kontrolü
        text = v.get("caption") or v.get("text") or ""
        meta = {
            "is_paid_partnership": v.get("is_paid_partnership", False),
            "sponsor_tags": v.get("sponsor_tags", [])
        }
        is_ad, ad_reason = detect_ad_or_spam(text, meta)
        if is_ad:
            continue

        # 3. AI / Heuristic Kalite Değerlendirmesi
        ai_res = evaluate_video_with_ai(
            title="",
            text=text,
            author=v.get("username") or v.get("author") or "",
            platform=platform
        )
        if not ai_res.get("is_approved"):
            continue

        v["curator_score"] = ai_res.get("quality_score", 5)
        v["curator_reason"] = ai_res.get("reason", "")
        v["curator_source"] = ai_res.get("source", "rules")
        approved.append(v)

    # Sıralama: Önce izlenme/beğeni, ardından küratör kalite puanı
    approved.sort(
        key=lambda x: (
            x.get("curator_score", 5),
            x.get("plays", 0) or x.get("views", 0),
            x.get("likes", 0)
        ),
        reverse=True
    )

    return approved
