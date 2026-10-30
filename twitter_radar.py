#!/usr/bin/env python3
"""
Twitter/X Viral Tweet Arama Motoru
Gelişmiş arama sözdizimi (min_faves:5000 lang:tr since:YYYY-MM-DD) ile
en popüler ve henüz gönderilmemiş viral Türkçe tweetleri tespit eder.
"""

import os
import json
import time
import html
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from radar_store import radar_store

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_JS = os.path.join(PROJECT_DIR, "shots", "tweet-shot", "tools", "x-search.js")

_search_lock = threading.Lock()
_last_search_cache = {
    "timestamp": 0,
    "query": "",
    "data": None
}

def load_twitter_credentials():
    """Twitter oturum çerezlerini yalnızca Coolify/container environment değişkenlerinden okur."""
    auth_token = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.getenv("TWITTER_CT0", "").strip()
    return auth_token, ct0

def get_dynamic_since_date(days_back=3):
    """Bugünün tarihinden geriye dönük dinamik since:YYYY-MM-DD oluşturur."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    return dt.strftime("%Y-%m-%d")

def search_viral_tweets(min_faves=5000, days_back=3):
    """
    X üzerinde popüler Türkçe tweetleri arar.
    Sorgu: min_faves:5000 lang:tr since:YYYY-MM-DD
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
    query = f"min_faves:{min_faves} lang:tr since:{since_date}"

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

    # Daha önce iletilmemiş olanları filtrele
    unseen = [t for t in raw_tweets if not radar_store.is_sent(t.get("id"))]

    if not unseen:
        return None, len(raw_tweets), "Bulunan tüm popüler tweetler daha önce iletilmiş."

    # En yüksek beğeniye sahip olanı seç
    unseen.sort(key=lambda x: int(x.get("likes") or 0), reverse=True)
    top_tweet = unseen[0]

    return top_tweet, len(unseen), None

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

    # Henüz iletilmemiş olanları filtrele
    unseen = [t for t in raw_tweets if not radar_store.is_sent(f"ai_{t.get('id')}") and not radar_store.is_sent(t.get('id'))]
    if exclude_id:
        unseen_filtered = [t for t in unseen if str(t.get("id")) != str(exclude_id)]
        if unseen_filtered:
            unseen = unseen_filtered

    if not unseen:
        unseen = [t for t in raw_tweets if not radar_store.is_sent(f"ai_{t.get('id')}")]
        if exclude_id:
            unseen_filtered = [t for t in unseen if str(t.get("id")) != str(exclude_id)]
            if unseen_filtered:
                unseen = unseen_filtered

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
        return best, len(unseen), best["ai_eval"], None

    # Fallback: En popüler olan
    unseen.sort(key=lambda x: int(x.get("likes") or 0), reverse=True)
    fallback_best = unseen[0]
    fallback_eval = {"approved": True, "score": 7, "reason": "Yüksek beğeni etkileşimi.", "model": "heuristic"}
    return fallback_best, len(unseen), fallback_eval, None

if __name__ == "__main__":
    print("Testing load_twitter_credentials:")
    tok, c = load_twitter_credentials()
    print("Found token:", bool(tok), "Found ct0:", bool(c))
