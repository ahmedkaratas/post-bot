#!/usr/bin/env python3
"""
Twitter/X Viral Tweet Arama Motoru
Gelişmiş arama sözdizimi (min_faves:5000 lang:tr since:YYYY-MM-DD) ile
en popüler ve henüz gönderilmemiş viral Türkçe tweetleri tespit eder.
"""

import os
import re
import json
import time
import html
import math
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from radar_store import radar_store
from session_manager import session_manager
from dedup_engine import dedup_engine

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_JS = os.path.join(PROJECT_DIR, "shots", "tweet-shot", "tools", "x-search.js")

_search_lock = threading.Lock()
_last_search_cache = {
    "timestamp": 0,
    "query": "",
    "data": None
}

def load_twitter_credentials():
    """Twitter oturum çerezlerini önce data/cookies.json'dan, yoksa ortam değişkenlerinden okur."""
    return session_manager.get_twitter_credentials()

def get_dynamic_since_date(days_back=3):
    """Bugünün tarihinden geriye dönük dinamik since:YYYY-MM-DD oluşturur."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    return dt.strftime("%Y-%m-%d")

def search_viral_tweets(min_faves=5000, days_back=3, min_retweets=None):
    """
    X üzerinde popüler Türkçe tweetleri arar.
    Sorgu: min_faves:5000 [min_retweets:300] lang:tr since:YYYY-MM-DD
    Dönüş: {"success": bool, "tweets": list, "error": str}
    """
    auth_token, ct0 = load_twitter_credentials()
    if not auth_token or not ct0:
        return {
            "success": False,
            "error": "Twitter oturum çerezleri (TWITTER_AUTH_TOKEN ve TWITTER_CT0) tanımlanmamış. Lütfen Coolify Environment Variables bölümüne ekleyin.",
            "tweets": []
        }

    since_date = get_dynamic_since_date(days_back=days_back)
    rt_clause = f" min_retweets:{min_retweets}" if min_retweets is not None else ""
    query = f"min_faves:{min_faves}{rt_clause} lang:tr since:{since_date}"

    # 120 saniyelik önbellek kontrolü (aynı tarama sorgusu için tekrar headless Chrome açmayı engeller)
    now = time.time()
    if _last_search_cache["data"] and (now - _last_search_cache["timestamp"] < 120) and _last_search_cache["query"] == query:
        return _last_search_cache["data"]

    if not _search_lock.acquire(blocking=False):
        # Eğer kilit meşgulse ama önbellekte yakın tarihli veri varsa onu dön
        if _last_search_cache["data"] and (now - _last_search_cache["timestamp"] < 300):
            return _last_search_cache["data"]
        return {
            "success": False,
            "error": "Şu anda devam eden başka bir tweet taraması var. Lütfen biraz bekleyin.",
            "tweets": []
        }

    try:
        res = subprocess.run(
            ["node", SCRAPER_JS, query, auth_token, ct0],
            capture_output=True,
            text=True,
            timeout=70
        )

        output = res.stdout.strip()
        if not output:
            err = res.stderr.strip() or "Node x-search çıktısı boş döndü."
            return {"success": False, "error": err, "tweets": []}

        data = json.loads(output)
        if data.get("success"):
            _last_search_cache["timestamp"] = time.time()
            _last_search_cache["query"] = query
            _last_search_cache["data"] = data
        return data

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Arama işlemi zaman aşımına uğradı (70s). X sunucuları yanıt vermedi.", "tweets": []}
    except Exception as e:
        return {"success": False, "error": str(e), "tweets": []}
    finally:
        _search_lock.release()

def find_top_new_viral_tweet(min_faves=5000):
    """
    Henüz kullanıcıya gönderilmemiş en popüler yeni tweeti bulur ve döner.
    Dönüş: (tweet_dict, total_candidates, error_msg)
    """
    res = search_viral_tweets(min_faves=min_faves)
    if not res.get("success"):
        return None, 0, res.get("error", "Bilinmeyen arama hatası")

    raw_tweets = res.get("tweets", [])
    if not raw_tweets:
        dbg_url = res.get("currentUrl", "")
        detail = f" (URL: {html.escape(dbg_url)})" if dbg_url else ""
        return None, 0, f"Arama kriterlerine ({min_faves:,}+ beğeni) uyan yeni tweet bulunamadı.{detail}"

    # Daha önce iletilmemiş olanları filtrele (5 katmanlı tekilleştirme motoru)
    unseen = []
    for t in raw_tweets:
        t_id = str(t.get("id", "")).strip()
        t_url = t.get("url", "")
        t_text = t.get("text", "")
        t_author = t.get("author", "")
        if not dedup_engine.is_sent(t_id, url=t_url, text=t_text, author=t_author):
            unseen.append(t)

    if not unseen:
        return None, len(raw_tweets), "Bulunan tüm popüler tweetler daha önce iletilmiş."

    from video_curator_agent import detect_ad_or_spam

    # Sert filtreler: Promoted/reklam, yabancı dil ve spam olanları ele
    valid_unseen = []
    for t in unseen:
        if t.get("is_promoted"):
            continue
        lang = (t.get("lang") or "").strip().lower()
        if lang and lang != "tr":
            continue
        if detect_ad_or_spam(t.get("text", ""))[0]:
            continue
        valid_unseen.append(t)

    if not valid_unseen:
        return None, len(unseen), "Sert filtrelere (Türkçe, reklamsız) uyan yeni tweet bulunamadı."

    # En yüksek beğeniye sahip olanı seç
    valid_unseen.sort(key=lambda x: int(x.get("likes") or 0), reverse=True)
    top_tweet = valid_unseen[0]

    # Kalıcı kilit koy (claim)
    dedup_engine.claim(
        top_tweet.get("id"),
        url=top_tweet.get("url"),
        author=top_tweet.get("author", ""),
        text=top_tweet.get("text", "")
    )

    return top_tweet, len(valid_unseen), None

from tweet_curator_agent import evaluate_tweet_for_instagram

def find_ai_curated_viral_tweet(min_faves=3000, exclude_id=None):
    """
    X arama havuzundaki popüler tweetleri Gemini AI Ajanı ile inceler.
    Virallik puanı en yüksek olanı ve gerekçesini seçer.
    exclude_id belirtilirse, standart seçilen tweet hariç diğer en iyi adayı seçer.
    Dönüş: (top_ai_tweet, total_candidates, ai_eval_dict, err_msg)
    """
    res = search_viral_tweets(min_faves=min_faves)
    if not res.get("success"):
        return None, 0, None, res.get("error", "Bilinmeyen arama hatası")

    raw_tweets = res.get("tweets", [])
    if not raw_tweets:
        return None, 0, None, "Arama kriterlerine uyan tweet bulunamadı."

    # Henüz iletilmemiş olanları filtrele (5 katmanlı tekilleştirme motoru)
    unseen = []
    for t in raw_tweets:
        t_id = str(t.get("id", "")).strip()
        t_url = t.get("url", "")
        t_text = t.get("text", "")
        t_author = t.get("author", "")
        if exclude_id and t_id == str(exclude_id):
            continue
        if not dedup_engine.is_sent(t_id, url=t_url, text=t_text, author=t_author):
            unseen.append(t)

    if not unseen:
        return None, len(raw_tweets), None, "Tüm tweetler daha önce iletilmiş."

    # Adayların ilk 6 tanesini AI ile değerlendir
    evaluated = []
    for tw in unseen[:6]:
        eval_res = evaluate_tweet_for_instagram(tw)
        if eval_res.get("approved"):
            tw["ai_eval"] = eval_res
            evaluated.append(tw)

    if evaluated:
        evaluated.sort(key=lambda x: x["ai_eval"].get("score", 0), reverse=True)
        best = evaluated[0]
        # Kalıcı kilit koy (claim)
        dedup_engine.claim(
            best.get("id"),
            url=best.get("url"),
            author=best.get("author", ""),
            text=best.get("text", "")
        )
        return best, len(unseen), best["ai_eval"], None

    # Sert filtre kuralı: AI onaylamadıysa zorlama fallback yapma, bu turu boş geç
    return None, len(unseen), None, "Bu turda AI küratör onayını geçen (Türkçe, reklamsız ve kaliteli) yeni viral tweet bulunamadı."

BAIT_OR_SPAM_PATTERNS = [
    r"\b(?:rt|retweet)\b",
    r"çekiliş",
    r"takip et",
    r"kazan\b",
    r"hediye",
    r"beğen.+paylaş",
    r"bizi takip",
    r"rt eden"
]

def contains_bait_or_spam_terms(text: str) -> tuple[bool, str]:
    if not text:
        return False, ""
    t = text.lower()
    for p in BAIT_OR_SPAM_PATTERNS:
        m = re.search(p, t)
        if m:
            return True, m.group(0)
    return False, ""

def find_high_repost_viral_tweet(min_faves=3000, min_rt=300, exclude_ids=None):
    """
    Havuzdaki tweetler arasından hem yüksek beğeni hem de yüksek retweet almış,
    organik yayılım gösteren en viral tweeti tespit eder (Sorun 3).
    - İkili sorgu (min_faves + min_retweets ve min_faves) ile GraphQL yanıtları birleştirilir.
    - Beğeni ve retweet yüzdelik sıralarının geometrik ortalaması hesaplanır.
    - Alt eşikler: beğeni >= min_faves, retweet >= min_rt (karşılanmazsa fallback yapılmaz).
    - RT/beğeni oranı 0.03-0.35 aralığında ödüllendirilir; >0.35 ise yem/bot şüphesiyle cezalandırılır.
    - 'rt', 'retweet', 'çekiliş', 'takip et' gibi yem ifadeleri içerenler elenir.
    - Alıntı sayısı puana düşük ağırlıkla katılır.
    """
    exclude_set = {str(eid).strip() for eid in (exclude_ids or []) if eid}

    # 1. İkili Arama: Hem min_retweets filtreli hem de genel popüler havuzu tara
    res_targeted = search_viral_tweets(min_faves=min_faves, min_retweets=min_rt)
    tweets_targeted = res_targeted.get("tweets", []) if res_targeted.get("success") else []

    res_general = search_viral_tweets(min_faves=min_faves)
    tweets_general = res_general.get("tweets", []) if res_general.get("success") else []

    # İki aramanın sonuçlarını tekilleştirerek birleştir
    combined_tweets = []
    seen_ids = set()
    for tw in tweets_targeted + tweets_general:
        tid = str(tw.get("id", "")).strip()
        if tid and tid not in seen_ids:
            seen_ids.add(tid)
            combined_tweets.append(tw)

    if not combined_tweets:
        return None, 0, None, f"Arama kriterlerine (min {min_faves:,} beğeni) uyan tweet bulunamadı."

    # 2. Gönderilmiş olanları 5 katmanlı motorla filtrele
    unseen = []
    for t in combined_tweets:
        t_id = str(t.get("id", "")).strip()
        t_url = t.get("url", "")
        t_text = t.get("text", "")
        t_author = t.get("author", "")
        if t_id in exclude_set:
            continue
        if not dedup_engine.is_sent(t_id, url=t_url, text=t_text, author=t_author):
            unseen.append(t)

    if not unseen:
        return None, len(combined_tweets), None, "Tüm tweetler daha önce iletilmiş."

    from video_curator_agent import detect_ad_or_spam

    # 3. Sert filtreler: Sponsorlu, yabancı dil, reklam ve 'yem/çekiliş/takip et' temizliği
    valid_unseen = []
    for t in unseen:
        if t.get("is_promoted"):
            continue
        lang = (t.get("lang") or "").strip().lower()
        if lang and lang != "tr":
            continue
        t_text = t.get("text", "")
        if detect_ad_or_spam(t_text)[0]:
            continue
        has_bait, bait_term = contains_bait_or_spam_terms(t_text)
        if has_bait:
            continue
        valid_unseen.append(t)

    if not valid_unseen:
        return None, len(unseen), None, "Sert filtrelere ve yem/çekiliş kurallarına uyan tweet bulunamadı."

    # 4. Alt Eşikler: Hem beğeni >= min_faves hem de retweet >= min_rt olmak ZORUNDA
    candidates = []
    for t in valid_unseen:
        likes = int(t.get("likes") or 0)
        retweets = int(t.get("retweets") or 0)
        quotes = int(t.get("quotes") or 0)
        views = int(t.get("views") or 0)

        if likes >= min_faves and retweets >= min_rt:
            candidates.append({
                "tweet": t,
                "likes": likes,
                "retweets": retweets,
                "quotes": quotes,
                "views": views
            })

    # Hiç aday alt eşikleri geçemezse: ZORLAMA YEDEK SEÇME, NET MESAJ DÖN
    if not candidates:
        return None, len(valid_unseen), None, f"Bu turda şartları (min {min_faves:,} beğeni, min {min_rt:,} retweet) geçen tweet yok."

    # 5. Geometrik Yüzdelik Sıralama (Percentile Ranking & Geometric Mean)
    N = len(candidates)
    scored = []
    for cand in candidates:
        c_likes = cand["likes"]
        c_rt = cand["retweets"]
        c_quotes = cand["quotes"]

        # Havuzdaki yüzdelik sıralar (0.05 - 1.0)
        cnt_likes = sum(1 for c in candidates if c["likes"] <= c_likes)
        pct_likes = max(0.05, cnt_likes / N)

        cnt_rt = sum(1 for c in candidates if c["retweets"] <= c_rt)
        pct_rt = max(0.05, cnt_rt / N)

        # Geometrik Ortalama: İki metriğin de yüksek olması şartını matematiksel zorlar
        geo_score = math.sqrt(pct_likes * pct_rt) * 100.0

        # RT / Beğeni Yayılım Oranı
        ratio = c_rt / max(c_likes, 1)

        # 0.03 - 0.35 aralığı ödüllendirilir; >0.35 çekiliş/bot şüphesiyle cezalandırılır
        if 0.03 <= ratio <= 0.35:
            ratio_mult = 1.15
            reason = f"Dengeli beğeni ve %{ratio * 100:.1f} organik yayılım"
        elif ratio > 0.35:
            ratio_mult = 0.40  # %60 Ceza
            reason = f"Aşırı RT oranı (%{ratio * 100:.1f} > 0.35, ceza uygulandı)"
        else:
            ratio_mult = 0.85
            reason = f"Düşük retweet oranı (%{ratio * 100:.1f})"

        # Alıntı sayısını düşük ağırlıkla puana kat
        quote_bonus = min(8.0, (c_quotes / max(c_likes, 1)) * 50.0)

        final_score = round((geo_score * ratio_mult) + quote_bonus, 1)

        cand["geo_score"] = round(geo_score, 1)
        cand["final_score"] = final_score
        cand["ratio_pct"] = round(ratio * 100, 1)
        cand["reason"] = reason
        scored.append(cand)

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    best_cand = scored[0]
    best_tweet = best_cand["tweet"]

    # İçeriğe claim kilidi koy
    dedup_engine.claim(
        best_tweet.get("id"),
        url=best_tweet.get("url"),
        author=best_tweet.get("author", ""),
        text=best_tweet.get("text", "")
    )

    stats = {
        "score": best_cand["final_score"],
        "geo_score": best_cand["geo_score"],
        "likes": best_cand["likes"],
        "retweets": best_cand["retweets"],
        "quotes": best_cand["quotes"],
        "views": best_cand["views"],
        "ratio_pct": best_cand["ratio_pct"],
        "reason": best_cand["reason"]
    }

    return best_tweet, len(scored), stats, None

if __name__ == "__main__":
    print("Testing load_twitter_credentials:")
    tok, c = load_twitter_credentials()
    print("Found token:", bool(tok), "Found ct0:", bool(c))
