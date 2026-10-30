#!/usr/bin/env python3
"""
Instagram Viral Reels Arama ve İndirme Motoru
Instagram Reels akışından popüler, güncel ve yüksek izlenmeli videoları ayıklar.
"""

import os
import time
import requests
from reels_store import reels_store
from video_curator_agent import filter_and_rank_videos, is_vertical_reels_format, detect_ad_or_spam

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_instagram_session_id():
    """Instagram sessionid değerini yalnızca Coolify/container environment değişkeninden okur."""
    return os.getenv("INSTAGRAM_SESSION_ID", "").strip()

def fetch_reels_feed(session_id: str, count: int = 25):
    """
    Instagram Reels akışından (Clips Discover API) videoları çeker.
    Genişletilmiş havuz için çoklu sayfalama desteği içerir.
    """
    if not session_id:
        return None, "INSTAGRAM_SESSION_ID bulunamadı. Lütfen Coolify Environment Variables bölümüne ekleyin."

    headers = {
        "User-Agent": "Instagram 300.0.0.18.110 (iPhone14,3; iOS 16_6; en_US; en-US; scale=3.00; 1170x2532; 513072223) AppleWebKit/420+",
        "Cookie": f"sessionid={session_id};",
        "Accept-Language": "tr-TR,en-US;q=0.9",
        "X-IG-App-ID": "936619743392459"
    }

    url = "https://i.instagram.com/api/v1/clips/discover/"
    all_items = []

    try:
        # 1. Sayfa
        data = {"container_module": "clips_viewer_clips_netego"}
        resp = requests.post(url, headers=headers, data=data, timeout=15)
        if resp.status_code != 200:
            if resp.status_code == 403:
                return None, "Instagram oturum süresi dolmuş veya sessionid geçersiz (HTTP 403)."
            return None, f"Instagram API hatası: HTTP {resp.status_code}"

        json_data = resp.json()
        raw_items = json_data.get("items", [])
        all_items.extend(raw_items)

        # Çoklu Sayfalama (Pagination): Instagram API max_id değerini paging_info içinde döner
        paging_info = json_data.get("paging_info", {})
        max_id = paging_info.get("max_id") or json_data.get("max_id")

        # Havuzu 30-40 videoya genişletmek için sonraki sayfaları çek
        page_count = 1
        while max_id and len(all_items) < 40 and page_count < 4:
            try:
                page_data = {
                    "container_module": "clips_viewer_clips_netego",
                    "max_id": str(max_id)
                }
                resp_next = requests.post(url, headers=headers, data=page_data, timeout=12)
                if resp_next.status_code == 200:
                    j_next = resp_next.json()
                    next_items = j_next.get("items", [])
                    if not next_items:
                        break
                    all_items.extend(next_items)
                    max_id = j_next.get("paging_info", {}).get("max_id") or j_next.get("max_id")
                    page_count += 1
                else:
                    break
            except Exception:
                break

        return all_items, None

    except Exception as e:
        return None, f"Bağlantı hatası: {str(e)}"

def parse_reel_item(item):
    """Instagram raw item nesnesini temiz sözlük yapısına dönüştürür."""
    media = item.get("media") or item
    code = media.get("code")
    if not code:
        return None

    user = media.get("user", {})
    username = user.get("username", "bilinmeyen")
    full_name = user.get("full_name", username)
    like_count = media.get("like_count") or 0
    play_count = media.get("play_count") or media.get("view_count") or 0
    taken_at = media.get("taken_at") or 0
    caption_obj = media.get("caption") or {}
    caption_text = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""

    is_paid = bool(media.get("is_paid_partnership") or media.get("sponsor_tags"))
    sponsor_tags = media.get("sponsor_tags", [])

    video_versions = media.get("video_versions", [])
    if not video_versions:
        return None

    # En yüksek çözünürlüklü video versiyonu
    best_v = video_versions[0]
    video_url = best_v.get("url")
    width = best_v.get("width", 0)
    height = best_v.get("height", 0)

    return {
        "code": code,
        "url": f"https://www.instagram.com/reel/{code}/",
        "username": username,
        "full_name": full_name,
        "likes": like_count,
        "plays": play_count,
        "taken_at": taken_at,
        "caption": caption_text,
        "video_url": video_url,
        "width": width,
        "height": height,
        "is_paid_partnership": is_paid,
        "sponsor_tags": sponsor_tags
    }

def find_top_new_viral_reel(min_plays=50000, min_likes=2000, max_age_hours=96):
    """
    Henüz gönderilmemiş, kriterlere uyan, reklam/spam içermeyen ve
    kesinlikle dikey Reels (9:16) formatındaki en popüler Reels videosunu bulur.
    Dönüş: (reel_dict, total_candidates, error_msg)
    """
    session_id = load_instagram_session_id()
    if not session_id:
        return None, 0, "INSTAGRAM_SESSION_ID Coolify Environment Variables içinde tanımlanmamış."

    raw_items, err = fetch_reels_feed(session_id)
    if err or not raw_items:
        return None, 0, err or "Reels akışından video alınamadı."

    now = int(time.time())
    max_age_secs = max_age_hours * 3600
    parsed_candidates = []

    for raw in raw_items:
        reel = parse_reel_item(raw)
        if not reel:
            continue

        code = reel["code"]
        # Daha önce gönderildiyse atla
        if reels_store.is_sent(code) or reels_store.is_sent(f"ig_{code}"):
            continue

        # Tarih kontrolü (Çok eski değilse)
        age_secs = now - reel["taken_at"]
        if age_secs > max_age_secs:
            continue

        # Popülerlik kontrolü: İzlenme veya beğeni eşiğini aşıyor mu?
        if reel["plays"] >= min_plays or reel["likes"] >= min_likes:
            parsed_candidates.append(reel)

    # Agency Agent Küratör Filtresi:
    # 1. Dikey Reels oranı olmayanlar elenir.
    # 2. Reklam/Spam olanlar elenir.
    # 3. AI / Heuristik kaliteye göre sıralanır.
    qualified = filter_and_rank_videos(parsed_candidates, platform="reels")

    if qualified:
        return qualified[0], len(qualified), None

    # Eğer katı popülerlik eşiğine tam uymadıysa ama henüz gönderilmemiş temiz videolar varsa:
    fallback_unseen = []
    for raw in raw_items:
        r = parse_reel_item(raw)
        if r and not reels_store.is_sent(r["code"]) and not reels_store.is_sent(f"ig_{r['code']}"):
            fallback_unseen.append(r)

    # Fallback havuzunu da kalite ve format filtresinden geçir
    clean_fallbacks = filter_and_rank_videos(fallback_unseen, platform="reels")
    if clean_fallbacks:
        return clean_fallbacks[0], len(clean_fallbacks), None

    return None, 0, "Kriterlere ve dikey Reels formatına uyan yeni bir viral Reels bulunamadı."

def download_video_bytes(video_url: str):
    """Video dosyasını belleğe indirir."""
    try:
        resp = requests.get(video_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
        if resp.status_code == 200:
            return resp.content, None
        return None, f"Video indirme hatası: HTTP {resp.status_code}"
    except Exception as e:
        return None, f"Video indirme bağlantı hatası: {str(e)}"
