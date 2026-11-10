#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher.py: Instagram ve X (Twitter) bağlantılarından
medyayı (video/fotoğraf) indiren ve en çok beğeni alan (10.000+) yorumları toplayan modül.
"""

import os
import re
import json
import shutil
import requests
import subprocess
import tempfile

YT_DLP_BIN = shutil.which("yt-dlp") or ("/Users/qwerty/.local/bin/yt-dlp" if os.path.exists("/Users/qwerty/.local/bin/yt-dlp") else "yt-dlp")

def is_valid_comment(text: str) -> bool:
    """Yorumun okunabilir, geçerli ve seslendirmeye uygun olup olmadığını denetler."""
    if not text:
        return False
    t = text.strip()
    # Çok kısa (< 4 karakter) veya aşırı uzun (> 220 karakter) yorumları ele
    if len(t) < 4 or len(t) > 220:
        return False

    # URL veya reklam linki içeriyorsa ele
    if "http://" in t or "https://" in t or ".com" in t or ".net" in t:
        return False

    # Herhangi bir kelime 20 karakterden uzunsa (klavye randomu / harf spam) ele
    for word in t.split():
        if not word.startswith("@") and len(word) > 20:
            return False

    # 6 veya daha fazla ardışık sessiz harf (Türkçe klavye spam: SÇDÇWĞ, asdfghj, zxcvbn vb.)
    if re.search(r"[bcçdfgğhjklmnprsştvyzxwqBCÇDFGĞHJKLMNPRSŞTVYZXWQ]{6,}", t):
        return False

    # Yorum sadece @etiketlerden veya sadece emojilerden ibaretse ele
    t_clean = re.sub(r"@[A-Za-z0-9_.\-]+", "", t)
    t_clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe00-\ufe0f\u200d\u200c]", "", t_clean).strip()
    if len(t_clean) < 3:
        return False

    return True

def extract_platform_and_id(url: str):
    """Verilen URL'den platformu ve içerik ID'sini tespit eder."""
    u = (url or "").strip()
    
    # Twitter / X
    tw_match = re.search(r"(?:twitter\.com|x\.com|fxtwitter\.com|vxtwitter\.com)/([a-zA-Z0-9_]+)/status/(\d+)", u)
    if tw_match:
        return "twitter", tw_match.group(2)
        
    # Instagram Reel / Post
    ig_match = re.search(r"instagram\.com/(?:reel|p|reels)/([a-zA-Z0-9_-]+)", u)
    if ig_match:
        return "instagram", ig_match.group(1)
        
    return None, None

def download_media(url: str, output_dir: str) -> tuple:
    """
    yt-dlp kullanarak gönderideki videoyu veya görseli en yüksek kalitede indirir.
    Dönüş: (dosya_yolu, is_video: bool)
    """
    os.makedirs(output_dir, exist_ok=True)
    out_tmpl = os.path.join(output_dir, "media_bg.%(ext)s")
    
    cmd = [
        YT_DLP_BIN,
        "--no-playlist",
        "-o", out_tmpl,
        url
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for fname in os.listdir(output_dir):
            if fname.startswith("media_bg."):
                full_path = os.path.join(output_dir, fname)
                ext = fname.split(".")[-1].lower()
                is_vid = ext in ("mp4", "mov", "mkv", "webm")
                return full_path, is_vid
    except Exception as e:
        print(f"[Fetcher] yt-dlp indirme hatası: {e}")
        
    return None, False

def fetch_twitter_comments(tweet_id: str, min_likes: int = 10000) -> list:
    """
    fxtwitter conversation API'sinden tweet yorumlarını çeker.
    Öncelikli olarak min_likes (varsayılan 10.000) üzerindeki yorumları eler.
    Eğer 10k üstü yorum yoksa, en çok beğeni alan ilk 6 yorumu döner.
    """
    api_url = f"https://api.fxtwitter.com/2/conversation/{tweet_id}"
    comments = []
    
    try:
        resp = requests.get(api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            raw_replies = data.get("replies") or []
            
            for r in raw_replies:
                likes = r.get("likes") or 0
                author = r.get("author") or {}
                text = (r.get("text") or "").strip()
                
                # Temizleme ve spam kontrolü
                if not is_valid_comment(text):
                    continue
                    
                comments.append({
                    "id": r.get("id"),
                    "author_name": author.get("name") or author.get("screen_name") or "Kullanıcı",
                    "author_handle": author.get("screen_name") or "user",
                    "avatar_url": author.get("avatar_url") or "",
                    "text": text,
                    "likes": likes,
                    "platform": "twitter"
                })
    except Exception as e:
        print(f"[Fetcher] Twitter yorumları çekme hatası: {e}")

    # Beğeniye göre azalan sırala
    comments.sort(key=lambda x: x["likes"], reverse=True)
    
    # 10.000 ve üzeri olanları filtrele
    high_likes = [c for c in comments if c["likes"] >= min_likes]
    if high_likes:
        return high_likes
        
    # Eğer 10k üstü yoksa en popüler ilk 6'yı dön (kullanıcıyı cevapsız bırakmamak için)
    return comments[:6]

def fetch_instagram_comments(shortcode: str, min_likes: int = 10000) -> list:
    """
    Instagram gönderisindeki yorumları çeker.
    Varsayılan 10.000+ beğeni alanları filtreler, yoksa en popüler/komik yorumları döner.
    """
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    comments = []
    try:
        # Oturum çerezi varsa ekle
        cookie_header = []
        try:
            from session_manager import session_manager
            sid = session_manager.get_instagram_session_id()
            if sid:
                cookie_header = ["--add-header", f"Cookie: sessionid={sid}"]
        except Exception:
            pass

        cmd = [
            YT_DLP_BIN,
            *cookie_header,
            "--write-comments",
            "--dump-json",
            post_url
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out)
        raw_comments = data.get("comments") or []
        
        for c in raw_comments:
            text = (c.get("text") or "").strip()
            # Anlamsız spam, klavye randomu ve reklam filtrelemesi
            if not is_valid_comment(text):
                continue
                
            author = c.get("author") or "kullanici"
            likes = c.get("like_count") or 0
            
            comments.append({
                "id": c.get("id"),
                "author_name": author,
                "author_handle": author,
                "avatar_url": "",
                "text": text,
                "likes": likes,
                "platform": "instagram"
            })
    except Exception as e:
        print(f"[Fetcher] Instagram yt-dlp yorum çekme hatası: {e}")

    # Beğeniye göre azalan sırala
    comments.sort(key=lambda x: x["likes"], reverse=True)
    high_likes = [c for c in comments if c["likes"] >= min_likes]
    if len(high_likes) >= 5:
        return high_likes[:10]
    
    # 10k üstü azsa veya beğeniler anonim çekilmişse, geçerli temiz yorumları al
    combined = list(high_likes)
    for c in comments:
        if c not in combined:
            combined.append(c)
        if len(combined) >= 8:
            break
    return combined

def fetch_post_and_comments(url: str, min_likes: int = 10000, working_dir: str = None) -> dict:
    """
    Uçtan uca ana fonksiyon:
    1. Medyayı indirir.
    2. Yorumları toplar ve filtreler.
    Dönüş:
    {
       "platform": "twitter" | "instagram",
       "media_path": str,
       "is_video": bool,
       "comments": list
    }
    """
    if not working_dir:
        working_dir = tempfile.mkdtemp(prefix="comment_fetch_")
        
    platform, post_id = extract_platform_and_id(url)
    if not platform:
        return {"error": "Desteklenmeyen URL formatı. Lütfen geçerli bir Instagram veya Twitter/X linki verin."}

    print(f"[Fetcher] Algılandı: {platform.upper()} ID: {post_id} | Min Beğeni: {min_likes}")
    
    # 1. Medyayı İndir
    media_path, is_video = download_media(url, working_dir)
    if not media_path:
        return {"error": "Gönderideki video/görsel indirilemedi."}
        
    # 2. Yorumları Çek
    if platform == "twitter":
        comments = fetch_twitter_comments(post_id, min_likes=min_likes)
    else:
        comments = fetch_instagram_comments(post_id, min_likes=min_likes)
        
    return {
        "platform": platform,
        "post_id": post_id,
        "media_path": media_path,
        "is_video": is_video,
        "comments": comments
    }
