#!/usr/bin/env python3
"""
Post Geçmişi ve Geri Bildirim Veritabanı (HistoryStore)
Botun gönderdiği tüm postları kısa ID (#1, #2) ile kaydeder.
Kullanıcı geri bildirimlerini (/tuttu, /tutmadi, /sonuc) ve A/B performansını yönetir.
"""

import os
import json
import time
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "post_history.json")

DEFAULT_STATE = {
    "next_id": 1,
    "posts": {}  # post_id_str -> post dict
}

class HistoryStore:
    def __init__(self, file_path=HISTORY_FILE):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._ensure_dir()
        self.data = self._load()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load(self):
        if not os.path.exists(self.file_path):
            return {"next_id": 1, "posts": {}}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                return {
                    "next_id": loaded.get("next_id", 1),
                    "posts": loaded.get("posts", {})
                }
        except Exception as e:
            print(f"Geçmiş veri okuma hatası: {e}")
            return {"next_id": 1, "posts": {}}

    def _save(self):
        try:
            self._ensure_dir()
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            print(f"Geçmiş veri kaydetme hatası: {e}")

    def add_post(self, source_type: str, delivery_mode: str, link: str, author: str,
                 text: str, metrics: dict = None, ai_score: int = None,
                 ai_reason: str = None, ai_model: str = None,
                 selected_replies: list = None, caption: str = "") -> int:
        """
        Yeni gönderilen bir postu #kısa_id ile kaydeder.
        source_type: 'tweet', 'twitter_video', 'instagram_reel'
        delivery_mode: 'standard', 'ai_curator'
        """
        with self._lock:
            self.data = self._load()
            post_id = int(self.data.get("next_id", 1))
            self.data["next_id"] = post_id + 1

            m = metrics or {}
            likes = m.get("likes") or 0
            views = m.get("views") or 0
            retweets = m.get("retweets") or 0
            replies = m.get("replies") or 0
            bookmarks = m.get("bookmarks") or 0

            rates = {
                "like_to_view": round(likes / views, 4) if views > 0 else 0.0,
                "save_to_like": round(bookmarks / likes, 4) if likes > 0 else 0.0,
                "reply_to_like": round(replies / likes, 4) if likes > 0 else 0.0,
                "rt_to_like": round(retweets / likes, 4) if likes > 0 else 0.0,
            }

            post_entry = {
                "id": post_id,
                "source_type": source_type,
                "delivery_mode": delivery_mode,
                "link": link or "",
                "author": author or "",
                "text": (text or "").strip(),
                "created_at": int(time.time()),
                "metrics": m,
                "rates": rates,
                "ai_score": ai_score,
                "ai_reason": ai_reason,
                "ai_model": ai_model,
                "selected_replies": selected_replies or [],
                "caption": caption or "",
                "results": {
                    "views": None,
                    "reach": None,
                    "likes": None,
                    "shares": None,
                    "saves": None,
                    "comments": None,
                    "tag": None,           # 'tuttu', 'orta', 'tutmadi'
                    "tagged_by": None,     # 'manual', 'auto'
                    "feedback_at": None
                }
            }

            self.data.setdefault("posts", {})[str(post_id)] = post_entry
            self._save()
            return post_id

    def get_post(self, post_id: int) -> dict:
        self.data = self._load()
        return self.data.get("posts", {}).get(str(post_id))

    def update_results(self, post_id: int, views: int = None, shares: int = None,
                       saves: int = None, likes: int = None, comments: int = None,
                       reach: int = None, tag: str = None, tagged_by: str = "manual") -> dict:
        """
        Postun izlenme ve etkileşim sonuçlarını kaydeder, gerekiyorsa dinamik etiketini hesaplar.
        """
        with self._lock:
            self.data = self._load()
            posts = self.data.get("posts", {})
            key = str(post_id)
            if key not in posts:
                return None

            post = posts[key]
            res = post.setdefault("results", {})

            if views is not None:
                res["views"] = int(views)
            if shares is not None:
                res["shares"] = int(shares)
            if saves is not None:
                res["saves"] = int(saves)
            if likes is not None:
                res["likes"] = int(likes)
            if comments is not None:
                res["comments"] = int(comments)
            if reach is not None:
                res["reach"] = int(reach)

            if tag is not None:
                res["tag"] = tag.lower()
                res["tagged_by"] = tagged_by
            elif res.get("tagged_by") != "manual":
                # Otomatik dinamik etiket hesapla
                auto_tag = self._calculate_auto_tag_locked(res.get("views"))
                if auto_tag:
                    res["tag"] = auto_tag
                    res["tagged_by"] = "auto"

            res["feedback_at"] = int(time.time())

            # 10 veya daha fazla izlenme verisi varsa tüm dinamik etiketleri yeniden kalibre et
            self._refresh_auto_tags_locked()

            self._save()
            return post

    def set_tag(self, post_id: int, tag: str, tagged_by: str = "manual") -> bool:
        """Postu doğrudan 'tuttu' veya 'tutmadi' olarak etiketler."""
        with self._lock:
            self.data = self._load()
            posts = self.data.get("posts", {})
            key = str(post_id)
            if key not in posts:
                return False

            post = posts[key]
            res = post.setdefault("results", {})
            res["tag"] = tag.lower()
            res["tagged_by"] = tagged_by
            res["feedback_at"] = int(time.time())
            self._save()
            return True

    def delete_post(self, post_id: int) -> bool:
        """Belirtilen postu geçmişten ve kütüphaneden siler."""
        with self._lock:
            self.data = self._load()
            posts = self.data.get("posts", {})
            key = str(post_id)
            if key in posts:
                del posts[key]
                self._save()
                return True
            return False

    def get_recent_posts(self, limit: int = 10) -> list:
        """En son gönderilen postları döner."""
        self.data = self._load()
        posts = list(self.data.get("posts", {}).values())
        posts.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
        return posts[:limit]

    def get_tagged_posts(self, tag: str = None) -> list:
        """Etiketlenmiş (tuttu / tutmadı) postları döner."""
        self.data = self._load()
        posts = list(self.data.get("posts", {}).values())
        tagged = [p for p in posts if p.get("results", {}).get("tag")]
        if tag:
            tagged = [p for p in tagged if p.get("results", {}).get("tag") == tag.lower()]
        tagged.sort(key=lambda x: int(x.get("id", 0)), reverse=True)
        return tagged

    def _calculate_auto_tag_locked(self, views: int) -> str:
        """
        Dinamik 'Tuttu' Hesaplaması:
        - 10'dan az izlenmesi girilmiş post varken otomatik etiketleme yapmaz (None döner).
        - 10 veya daha fazla veri varken kullanıcının post dağılımına bakar:
          En üst %25 -> 'tuttu'
          Orta %50 -> 'orta'
          Alt %25 -> 'tutmadi'
        """
        if views is None or views <= 0:
            return None

        posts = list(self.data.get("posts", {}).values())
        all_views = [
            p["results"]["views"] for p in posts
            if p.get("results", {}).get("views") is not None and p["results"]["views"] > 0
        ]

        if len(all_views) < 10:
            return None

        all_views.sort()
        n = len(all_views)
        p25 = all_views[int(n * 0.25)]
        p75 = all_views[int(n * 0.75)]

        if views >= p75:
            return "tuttu"
        elif views >= p25:
            return "orta"
        else:
            return "tutmadi"

    def _refresh_auto_tags_locked(self):
        """10 veya daha fazla izlenme girildiğinde auto-tagged postları dinamik günceller."""
        posts = self.data.get("posts", {})
        all_views = [
            p["results"]["views"] for p in posts.values()
            if p.get("results", {}).get("views") is not None and p["results"]["views"] > 0
        ]
        if len(all_views) < 10:
            return

        all_views.sort()
        n = len(all_views)
        p25 = all_views[int(n * 0.25)]
        p75 = all_views[int(n * 0.75)]

        for p in posts.values():
            res = p.get("results", {})
            if res.get("tagged_by") == "auto" or (res.get("tagged_by") != "manual" and res.get("views")):
                v = res.get("views")
                if v is not None and v > 0:
                    if v >= p75:
                        res["tag"] = "tuttu"
                    elif v >= p25:
                        res["tag"] = "orta"
                    else:
                        res["tag"] = "tutmadi"
                    res["tagged_by"] = "auto"

    def get_stats_summary(self) -> dict:
        """Kütüphane ve geri bildirim istatistiklerini hesaplar."""
        self.data = self._load()
        posts = list(self.data.get("posts", {}).values())
        total_posts = len(posts)
        all_views = [
            p["results"]["views"] for p in posts
            if p.get("results", {}).get("views") is not None and p["results"]["views"] > 0
        ]

        tuttu_count = sum(1 for p in posts if p.get("results", {}).get("tag") == "tuttu")
        tutmadi_count = sum(1 for p in posts if p.get("results", {}).get("tag") == "tutmadi")
        orta_count = sum(1 for p in posts if p.get("results", {}).get("tag") == "orta")
        sonucsuz_count = total_posts - (tuttu_count + tutmadi_count + orta_count)

        threshold_75 = None
        if len(all_views) >= 10:
            all_views.sort()
            threshold_75 = all_views[int(len(all_views) * 0.75)]

        avg_views = int(sum(all_views) / len(all_views)) if all_views else 0

        return {
            "total_posts": total_posts,
            "recorded_views_count": len(all_views),
            "avg_views": avg_views,
            "tuttu_count": tuttu_count,
            "tutmadi_count": tutmadi_count,
            "orta_count": orta_count,
            "sonucsuz_count": sonucsuz_count,
            "threshold_75": threshold_75,
            "is_dynamic_active": len(all_views) >= 10
        }

    def add_retroactive_post(self, link: str, tag: str, views: int = None,
                             shares: int = None, saves: int = None, likes: int = None,
                             comments: int = None, author: str = "eski_post",
                             text: str = "") -> int:
        """Botun atmadığı eski postları geriye dönük kütüphaneye ekler."""
        with self._lock:
            self.data = self._load()
            post_id = int(self.data.get("next_id", 1))
            self.data["next_id"] = post_id + 1

            post_entry = {
                "id": post_id,
                "source_type": "retroactive",
                "delivery_mode": "manual_add",
                "link": link or "",
                "author": author or "harici",
                "text": text or "",
                "created_at": int(time.time()),
                "metrics": {},
                "rates": {},
                "ai_score": None,
                "ai_reason": None,
                "ai_model": None,
                "selected_replies": [],
                "caption": "",
                "results": {
                    "views": views,
                    "reach": None,
                    "likes": likes,
                    "shares": shares,
                    "saves": saves,
                    "comments": comments,
                    "tag": tag.lower(),
                    "tagged_by": "manual",
                    "feedback_at": int(time.time())
                }
            }

            self.data.setdefault("posts", {})[str(post_id)] = post_entry
            self._refresh_auto_tags_locked()
            self._save()
            return post_id

history_store = HistoryStore()
