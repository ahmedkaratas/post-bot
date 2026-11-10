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

def _run_ytdlp_json(url: str, cookie_header: list = None) -> dict:
    """yt-dlp ile JSON verisini çeker. Çerez hatası olursa otomatik çerezsiz dener."""
    cmd = [
        YT_DLP_BIN,
        *(cookie_header or []),
        "--write-comments",
        "--dump-json",
        url
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return json.loads(out)
    except Exception as e:
        if cookie_header:
            print(f"[Fetcher] Çerezli istek başarısız oldu ({e}), çerezsiz deneniyor...")
            try:
                clean_cmd = [
                    YT_DLP_BIN,
                    "--write-comments",
                    "--dump-json",
                    url
                ]
                out = subprocess.check_output(clean_cmd, stderr=subprocess.DEVNULL)
                return json.loads(out)
            except Exception as e2:
                print(f"[Fetcher] Çerezsiz istek de başarısız: {e2}")
        else:
            print(f"[Fetcher] yt-dlp çalıştırma hatası: {e}")
    return {}

def shortcode_to_media_id(shortcode: str) -> str:
    """Instagram shortcode (Örn: DcWvIayM23B) değerini sayısal media_id değerine çevirir."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    media_id = 0
    for char in shortcode:
        if char in alphabet:
            media_id = (media_id * 64) + alphabet.index(char)
    return str(media_id)

def _fetch_instagram_comments_api(media_id: str, session_id: str) -> list:
    """
    Instagram Mobile Private API kullanarak gönderinin gerçek popüler yorumlarını çeker.
    Top comments, gerçek comment_like_count değerleri ve sayfalama içerir.
    """
    url = f"https://i.instagram.com/api/v1/media/{media_id}/comments/?can_support_threading=true"
    headers = {
        "User-Agent": "Instagram 300.0.0.18.110 (iPhone14,3; iOS 16_6; en_US; en-US; scale=3.00; 1170x2532; 513072223) AppleWebKit/420+",
        "Cookie": f"sessionid={session_id};",
        "Accept-Language": "tr-TR,en-US;q=0.9",
        "X-IG-App-ID": "936619743392459"
    }

    all_comments = []
    seen_ids = set()
    max_id = None
    page = 0
    max_pages = 4  # En fazla 4 sayfa (yaklaşık 80-120 yorum) tara

    while page < max_pages:
        page += 1
        params = {}
        if max_id:
            params["max_id"] = str(max_id)

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=12)
            if resp.status_code != 200:
                print(f"[Fetcher] Instagram API yanıtı: HTTP {resp.status_code}")
                break
            data = resp.json()
            raw_comments = data.get("comments") or []
            if not raw_comments:
                break

            for c in raw_comments:
                cid = str(c.get("pk") or c.get("id"))
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)

                text = (c.get("text") or "").strip()
                if not is_valid_comment(text):
                    continue

                user = c.get("user") or {}
                author_handle = user.get("username") or "kullanici"
                author_name = user.get("full_name") or author_handle
                avatar_url = user.get("profile_pic_url") or ""
                likes = int(c.get("comment_like_count") or 0)

                all_comments.append({
                    "id": cid,
                    "author_name": author_name,
                    "author_handle": author_handle,
                    "avatar_url": avatar_url,
                    "text": text,
                    "likes": likes,
                    "platform": "instagram"
                })

                # Yanıtlanan alt yorumlar (preview_child_comments) varsa onları da kontrol et
                child_comments = c.get("preview_child_comments") or []
                for cc in child_comments:
                    cc_id = str(cc.get("pk") or cc.get("id"))
                    if cc_id in seen_ids:
                        continue
                    seen_ids.add(cc_id)
                    cc_text = (cc.get("text") or "").strip()
                    if not is_valid_comment(cc_text):
                        continue
                    cc_user = cc.get("user") or {}
                    all_comments.append({
                        "id": cc_id,
                        "author_name": cc_user.get("full_name") or cc_user.get("username") or "kullanici",
                        "author_handle": cc_user.get("username") or "kullanici",
                        "avatar_url": cc_user.get("profile_pic_url") or "",
                        "text": cc_text,
                        "likes": int(cc.get("comment_like_count") or 0),
                        "platform": "instagram"
                    })

            has_more = data.get("has_more_comments") or data.get("has_more_headload_comments")
            next_max_id = data.get("next_max_id")
            if not has_more or not next_max_id:
                break
            max_id = next_max_id
        except Exception as e:
            print(f"[Fetcher] Instagram API sayfa çekme hatası: {e}")
            break

    return all_comments

def fetch_instagram_comments(shortcode: str, min_likes: int = 10000) -> tuple:
    """
    Instagram gönderisindeki yorumları çeker.
    1. Oturum çerezi (sessionid) varsa doğrudan Instagram Mobile API ile gerçek beğeni sayılarını ve popüler yorumları çeker.
    2. Oturum yoksa veya geçersizse yt-dlp anonim önizleme fallback'ini kullanır (is_anonymous=True).
    Dönüş: (comments: list, is_anonymous: bool)
    """
    media_id = shortcode_to_media_id(shortcode)

    # 1. Öncelik: Aktif oturum ile Instagram Mobile API üzerinden gerçek popüler yorumları çek
    sid = None
    try:
        from session_manager import session_manager
        sid = session_manager.get_instagram_session_id()
    except Exception:
        pass

    if sid:
        print(f"[Fetcher] Aktif Instagram oturumu ile API sorgusu yapılıyor (media_id: {media_id})...")
        api_comments = _fetch_instagram_comments_api(media_id, sid)
        if api_comments:
            # Beğeniye göre azalan sırala
            api_comments.sort(key=lambda x: x["likes"], reverse=True)
            high_likes = [c for c in api_comments if c["likes"] >= min_likes]
            if high_likes:
                return high_likes[:8], False
            # 10k üstü bulunamazsa en popüler yorumları dön
            return api_comments[:8], False
        else:
            print("[Fetcher] Instagram API yorum döndürmedi veya oturum geçersiz, yt-dlp fallback'ine geçiliyor...")

    # 2. Fallback: Anonim / Logged-out yt-dlp çekimi
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    comments = []
    try:
        data = _run_ytdlp_json(post_url)
        raw_comments = data.get("comments") or []

        # Eğer /p/ linki yorum döndürmediyse /reel/ linkini de dene
        if not raw_comments:
            reel_url = f"https://www.instagram.com/reel/{shortcode}/"
            data = _run_ytdlp_json(reel_url)
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
        return high_likes[:8], True

    # 10k üstü azsa veya beğeniler anonim çekilmişse, geçerli temiz yorumları al
    combined = list(high_likes)
    for c in comments:
        if c not in combined:
            combined.append(c)
        if len(combined) >= 8:
            break
    return combined, True

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
       "comments": list,
       "is_anonymous": bool
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
    is_anonymous = False
    if platform == "twitter":
        comments = fetch_twitter_comments(post_id, min_likes=min_likes)
    else:
        comments, is_anonymous = fetch_instagram_comments(post_id, min_likes=min_likes)

    return {
        "platform": platform,
        "post_id": post_id,
        "media_path": media_path,
        "is_video": is_video,
        "comments": comments,
        "is_anonymous": is_anonymous
    }
