#!/usr/bin/env python3
"""
Reels Radar Veritabanı ve Konfigürasyon Yöneticisi
Instagram viral reels radarı için hedef grup/konu ID'lerini ve gönderilen reels geçmişini yönetir.
"""

import os
import json
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "reels_radar_data.json")

def _get_default_reels_chat_id():
    val = os.getenv("REELS_TARGET_CHAT_ID", "-1004409412493")
    if val:
        try:
            return int(val)
        except ValueError:
            return val
    return -1004409412493

def _get_default_reels_thread_id():
    val = os.getenv("REELS_TARGET_THREAD_ID", "127")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return 127

def _get_default_reels_active():
    val = os.getenv("REELS_IS_ACTIVE", "true").strip().lower()
    return val in ("true", "1", "yes", "on")

DEFAULT_STATE = {
    "target_chat_id": _get_default_reels_chat_id(),
    "target_thread_id": _get_default_reels_thread_id(),
    "target_title": os.getenv("REELS_TARGET_TITLE", "ViralReels"),
    "is_active": _get_default_reels_active(),
    "interval_minutes": int(os.getenv("REELS_INTERVAL_MINUTES", "120")),   # Varsayılan 2 saat (120 dakika)
    "min_plays": int(os.getenv("REELS_MIN_PLAYS", "100000")),             # Minimum 100.000 izlenme
    "min_likes": int(os.getenv("REELS_MIN_LIKES", "5000")),               # Minimum 5.000 beğeni
    "max_age_hours": int(os.getenv("REELS_MAX_AGE_HOURS", "72")),         # Son 3 gün (72 saat) içinde paylaşılmış güncel videolar
    "last_run_timestamp": 0,
    "sent_reels": {}        # reel_code -> {"sent_at": timestamp, "username": ..., "plays": ..., "likes": ...}
}

class ReelsStore:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self._ensure_dir()
        self.data = self._load()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load(self):
        if not os.path.exists(self.file_path):
            return dict(DEFAULT_STATE)
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                merged = dict(DEFAULT_STATE)
                merged.update(loaded)
                return merged
        except Exception as e:
            print(f"Reels radar veri okuma hatası: {e}")
            return dict(DEFAULT_STATE)

    def _save(self):
        try:
            self._ensure_dir()
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            print(f"Reels radar veri kaydetme hatası: {e}")

    def get_config(self):
        self.data = self._load()
        chat_id = self.data.get("target_chat_id")
        if chat_id is None:
            chat_id = _get_default_reels_chat_id()
        thread_id = self.data.get("target_thread_id")
        if thread_id is None:
            thread_id = _get_default_reels_thread_id()
        is_active = self.data.get("is_active")
        if is_active is None:
            is_active = _get_default_reels_active()

        return {
            "target_chat_id": chat_id,
            "target_thread_id": thread_id,
            "target_title": self.data.get("target_title") or os.getenv("REELS_TARGET_TITLE", "ViralReels"),
            "is_active": is_active,
            "interval_minutes": self.data.get("interval_minutes", int(os.getenv("REELS_INTERVAL_MINUTES", "120"))),
            "min_plays": self.data.get("min_plays", int(os.getenv("REELS_MIN_PLAYS", "100000"))),
            "min_likes": self.data.get("min_likes", int(os.getenv("REELS_MIN_LIKES", "5000"))),
            "max_age_hours": self.data.get("max_age_hours", int(os.getenv("REELS_MAX_AGE_HOURS", "72"))),
            "last_run_timestamp": self.data.get("last_run_timestamp", 0),
            "sent_count": len(self.data.get("sent_reels", {}))
        }

    def set_target(self, chat_id, thread_id=None, title=None):
        self.data = self._load()
        self.data["target_chat_id"] = chat_id
        self.data["target_thread_id"] = thread_id
        if title:
            self.data["target_title"] = title
        self.data["is_active"] = True
        self._save()

    def set_active(self, active: bool):
        self.data = self._load()
        self.data["is_active"] = bool(active)
        self._save()

    def set_min_plays(self, min_plays: int):
        self.data = self._load()
        self.data["min_plays"] = max(1000, int(min_plays))
        self._save()

    def set_min_likes(self, min_likes: int):
        self.data = self._load()
        self.data["min_likes"] = max(100, int(min_likes))
        self._save()

    def set_interval(self, minutes: int):
        self.data = self._load()
        self.data["interval_minutes"] = max(5, int(minutes))
        self._save()

    def is_sent(self, code: str) -> bool:
        self.data = self._load()
        return str(code) in self.data.get("sent_reels", {})

    def mark_sent(self, code: str, username: str = "", plays: int = 0, likes: int = 0):
        self.data = self._load()
        sent = self.data.setdefault("sent_reels", {})
        sent[str(code)] = {
            "sent_at": int(time.time()),
            "username": username,
            "plays": plays,
            "likes": likes
        }
        # Geçmişi makul boyutta tut (en son 1000 reels)
        if len(sent) > 1000:
            oldest_keys = sorted(sent.keys(), key=lambda k: sent[k].get("sent_at", 0))[:200]
            for k in oldest_keys:
                sent.pop(k, None)

        self.data["last_run_timestamp"] = int(time.time())
        self._save()

    def touch_last_run(self, backoff_seconds: int = 0):
        self.data = self._load()
        if backoff_seconds > 0:
            interval_secs = self.data.get("interval_minutes", 120) * 60
            self.data["last_run_timestamp"] = int(time.time()) - interval_secs + backoff_seconds
        else:
            self.data["last_run_timestamp"] = int(time.time())
        self._save()

reels_store = ReelsStore()
