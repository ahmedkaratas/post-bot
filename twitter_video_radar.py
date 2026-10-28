#!/usr/bin/env python3
"""
Twitter/X Viral Video Arama ve İndirme Motoru
Twitter'da paylaşılmış, popüler (yüksek beğenili) ve güncel videoları ayıklar.
"""

import os
import json
import time
import requests
import subprocess
from datetime import datetime, timedelta, timezone
from reels_store import reels_store
from twitter_radar import load_twitter_credentials, get_dynamic_since_date
from video_curator_agent import filter_and_rank_videos, is_vertical_reels_format, detect_ad_or_spam

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRAPER_JS = os.path.join(PROJECT_DIR, "shots", "tweet-shot", "tools", "x-search.js")

# Puppeteer yavaş kaldığında veya timeout olduğunda taranacak popüler viral video hesapları (Fallback)
POPULAR_VIRAL_ACCOUNTS = [
    "solcugazete", "bpthaber", "yirmiucderece", "Darkwebhaber",
    "pusholder", "bosunatiklama", "vatansever__1", "bptmuzik"
]

def search_fallback_viral_videos(min_faves=1000):
    """
    Puppeteer timeout yediğinde veya oturum düştüğünde doğrudan popüler video hesaplarından
    en güncel popüler video tweetlerini FxTwitter API üzerinden çeker.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    found_tweets = []

    for acc in POPULAR_VIRAL_ACCOUNTS[:5]:
        try:
            url = f"https://api.fxtwitter.com/{acc}"
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                tweets = data.get("user", {}).get("tweets", []) or data.get("tweets", [])
                for tw in tweets:
                    media = tw.get("media", {})
                    videos = media.get("videos", [])
                    if videos:
                        likes = tw.get("likes", 0)
                        if likes >= min_faves:
                            found_tweets.append({
                                "id": tw.get("id"),
                                "author": tw.get("author", {}).get("screen_name", acc),
                                "name": tw.get("author", {}).get("name", acc),
                                "text": tw.get("text", ""),
                                "likes": likes,
                                "retweets": tw.get("retweets", 0),
                                "url": tw.get("url") or f"https://x.com/{acc}/status/{tw.get('id')}"
                            })
        except Exception:
            continue

    return found_tweets

def search_viral_video_tweets(min_faves=3000, days_back=3):
    """
    X üzerinde popüler Türkçe video tweetlerini arar.
    Sorgu: filter:videos min_faves:3000 lang:tr since:YYYY-MM-DD
    """
    auth_token, ct0 = load_twitter_credentials()
    if not auth_token or not ct0:
        fallback_res = search_fallback_viral_videos(min_faves=min_faves)
        if fallback_res:
            return {"success": True, "tweets": fallback_res, "source": "fallback"}
        return {"success": False, "error": "Twitter oturum çerezleri (.env) bulunamadı.", "tweets": []}

    since_date = get_dynamic_since_date(days_back=days_back)
    query = f"filter:videos min_faves:{min_faves} lang:tr since:{since_date}"

    try:
        res = subprocess.run(
            ["node", SCRAPER_JS, query, auth_token, ct0],
            capture_output=True,
            text=True,
            timeout=75
        )
        output = res.stdout.strip()
        if not output:
            fallback_res = search_fallback_viral_videos(min_faves=min_faves)
            if fallback_res:
                return {"success": True, "tweets": fallback_res, "source": "fallback"}
            err = res.stderr.strip() or "x-search çıktısı boş döndü."
            return {"success": False, "error": err, "tweets": []}

        data = json.loads(output)
        if not data.get("success") or not data.get("tweets"):
            fallback_res = search_fallback_viral_videos(min_faves=min_faves)
            if fallback_res:
                return {"success": True, "tweets": fallback_res, "source": "fallback"}

        return data

    except subprocess.TimeoutExpired:
        fallback_res = search_fallback_viral_videos(min_faves=min_faves)
        if fallback_res:
            return {"success": True, "tweets": fallback_res, "source": "fallback"}
        return {"success": False, "error": "Twitter arama zaman aşımı (75s).", "tweets": []}
    except Exception as e:
        fallback_res = search_fallback_viral_videos(min_faves=min_faves)
        if fallback_res:
            return {"success": True, "tweets": fallback_res, "source": "fallback"}
        return {"success": False, "error": str(e), "tweets": []}

def fetch_twitter_video_details(tweet_id: str, author: str = ""):
    """
    fxtwitter veya vxtwitter API'si üzerinden tweet'in MP4 video linkini ve istatistiklerini çeker.
    """
    author_str = author or "i"
    url = f"https://api.fxtwitter.com/{author_str}/status/{tweet_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tweet = data.get("tweet", {})
            media = tweet.get("media", {})
            videos = media.get("videos", [])
            if videos:
                # En yüksek kaliteli videoyu al
                v = videos[0]
                return {
                    "id": tweet_id,
                    "url": f"https://x.com/{tweet.get('author', {}).get('screen_name', author)}/status/{tweet_id}",
                    "author": tweet.get("author", {}).get("screen_name", author),
                    "name": tweet.get("author", {}).get("name", author),
                    "likes": tweet.get("likes", 0),
                    "retweets": tweet.get("retweets", 0),
                    "views": tweet.get("views", 0),
                    "text": tweet.get("text", ""),
                    "video_url": v.get("url"),
                    "width": v.get("width", 0),
                    "height": v.get("height", 0)
                }
    except Exception as e:
        print(f"fxtwitter video detay hatası: {e}")

    # Fallback: yt-dlp ile doğrudan dene
    try:
        cmd = ["yt-dlp", "-j", f"https://x.com/i/status/{tweet_id}"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if res.returncode == 0:
            d = json.loads(res.stdout)
            formats = [f for f in d.get("formats", []) if f.get("vcodec") != "none" and f.get("url")]
            if formats:
                best_fmt = formats[-1]
                return {
                    "id": tweet_id,
                    "url": f"https://x.com/i/status/{tweet_id}",
                    "author": d.get("uploader_id", d.get("uploader", "user")),
                    "name": d.get("uploader", "User"),
                    "likes": d.get("like_count", 0),
                    "retweets": d.get("repost_count", 0),
                    "views": d.get("view_count", 0),
                    "text": d.get("description", d.get("title", "")),
                    "video_url": best_fmt.get("url"),
                    "width": best_fmt.get("width", 0),
                    "height": best_fmt.get("height", 0)
                }
    except Exception as e:
        print(f"yt-dlp fallback video hatası: {e}")

    return None

def find_top_new_viral_twitter_video(min_faves=3000):
    """
    Henüz gönderilmemiş, kriterlere uyan, reklam/spam içermeyen ve
    dikey Reels (9:16) formatındaki en popüler Twitter videosunu bulur.
    Dönüş: (video_dict, total_candidates, error_msg)
    """
    res = search_viral_video_tweets(min_faves=min_faves)
    if not res.get("success"):
        return None, 0, res.get("error", "Twitter video arama hatası")

    raw_tweets = res.get("tweets", [])
    if not raw_tweets:
        return None, 0, f"Kriterlere ({min_faves:,}+ beğeni) uyan yeni video tweet bulunamadı."

    # Henüz iletilmemiş olanları filtrele (x_id olarak kaydedilir)
    unseen = [t for t in raw_tweets if not reels_store.is_sent(f"x_{t.get('id')}") and not reels_store.is_sent(t.get('id'))]
    if not unseen:
        return None, 0, "Bulunan tüm video tweetler daha önce gönderilmiş."

    # Beğeniye göre sırala (en çok beğenilen en başta)
    unseen.sort(key=lambda x: x.get("likes", 0), reverse=True)

    candidate_videos = []

    # İlk 10 tweeti incele ve video detaylarını topla
    for t in unseen[:10]:
        t_id = t.get("id")
        author = t.get("author", "")
        v_details = fetch_twitter_video_details(t_id, author=author)
        if v_details and v_details.get("video_url"):
            if not v_details.get("likes") and t.get("likes"):
                v_details["likes"] = t.get("likes")
            candidate_videos.append(v_details)

    if not candidate_videos:
        return None, len(unseen), "Bulunan tweetlerin video indirme linki çıkarılamadı."

    # Agency Agent Küratör Filtresi:
    # 1. Dikey Reels oranı (yatay videolar elenir)
    # 2. Anti-Reklam & Anti-Spam
    # 3. AI / Heuristik kalite sıralaması
    qualified = filter_and_rank_videos(candidate_videos, platform="twitter")

    if qualified:
        return qualified[0], len(qualified), None

    # Eğer katı dikey orana uyan bulunamadıysa ama reklamsız videolar varsa:
    clean_non_spam = [v for v in candidate_videos if not detect_ad_or_spam(v.get("text", ""))[0]]
    if clean_non_spam:
        # En azından en popüler reklamsız olanı seç
        clean_non_spam.sort(key=lambda x: x.get("likes", 0), reverse=True)
        return clean_non_spam[0], len(clean_non_spam), None

    return None, len(unseen), "Kriterlere ve dikey video formatına uyan yeni Twitter videosu bulunamadı."

def download_twitter_video_bytes(video_url: str):
    """Twitter MP4 video dosyasını indirir."""
    try:
        resp = requests.get(video_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if resp.status_code == 200:
            return resp.content, None
        return None, f"Video indirme hatası: HTTP {resp.status_code}"
    except Exception as e:
        return None, f"Video indirme bağlantı hatası: {str(e)}"
