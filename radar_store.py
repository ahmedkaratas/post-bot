#!/usr/bin/env python3
"""
Radar Veritabanı ve Konfigürasyon Yöneticisi
Otomatik viral tweet radarı için hedef grup/konu ID'lerini ve gönderilen tweet geçmişini yönetir.
"""

import os
import json
import time
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "radar_data.json")

def _get_default_radar_chat_id():
    val = os.getenv("RADAR_TARGET_CHAT_ID", "-1004409412493")
    if val:
        try:
            return int(val)
        except ValueError:
            return val
    return -1004409412493

def _get_default_radar_thread_id():
    val = os.getenv("RADAR_TARGET_THREAD_ID", "4")
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return 4

def _get_default_radar_active():
    val = os.getenv("RADAR_IS_ACTIVE", "true").strip().lower()
    return val in ("true", "1", "yes", "on")

DEFAULT_STATE = {
    "target_chat_id": _get_default_radar_chat_id(),
    "target_thread_id": _get_default_radar_thread_id(),
    "target_title": os.getenv("RADAR_TARGET_TITLE", "ViralGrup"),
    "is_active": _get_default_radar_active(),
    "interval_minutes": int(os.getenv("RADAR_INTERVAL_MINUTES", "120")),
    "min_faves": int(os.getenv("RADAR_MIN_FAVES", "5000")),
    "last_run_timestamp": 0,
    "sent_tweets": {}  # tweet_id -> {"sent_at": timestamp, "author": ..., "likes": ...}
}

class RadarStore:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()
        self._ensure_dir()
        with self._lock:
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
            print(f"Radar veri okuma hatası: {e}")
            return dict(DEFAULT_STATE)

    def _save(self):
        try:
            self._ensure_dir()
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            print(f"Radar veri kaydetme hatası: {e}")

    def get_config(self):
        with self._lock:
            self.data = self._load()
            chat_id = self.data.get("target_chat_id")
            if chat_id is None:
                chat_id = _get_default_radar_chat_id()
            thread_id = self.data.get("target_thread_id")
            if thread_id is None:
                thread_id = _get_default_radar_thread_id()
            is_active = self.data.get("is_active")
            if is_active is None:
                is_active = _get_default_radar_active()

            return {
                "target_chat_id": chat_id,
                "target_thread_id": thread_id,
                "target_title": self.data.get("target_title") or os.getenv("RADAR_TARGET_TITLE", "ViralGrup"),
                "is_active": is_active,
                "interval_minutes": self.data.get("interval_minutes", int(os.getenv("RADAR_INTERVAL_MINUTES", "120"))),
                "min_faves": self.data.get("min_faves", int(os.getenv("RADAR_MIN_FAVES", "5000"))),
                "last_run_timestamp": self.data.get("last_run_timestamp", 0),
                "sent_count": len(self.data.get("sent_tweets", {}))
            }

    def set_target(self, chat_id, thread_id=None, title=None):
        with self._lock:
            self.data = self._load()
            self.data["target_chat_id"] = chat_id
            self.data["target_thread_id"] = thread_id
            if title:
                self.data["target_title"] = title
            self.data["is_active"] = True
            self._save()

    def set_active(self, active: bool):
        with self._lock:
            self.data = self._load()
            self.data["is_active"] = bool(active)
            self._save()

    def set_min_faves(self, min_faves: int):
        with self._lock:
            self.data = self._load()
            self.data["min_faves"] = max(100, int(min_faves))
            self._save()

    def set_interval(self, minutes: int):
        with self._lock:
            self.data = self._load()
            self.data["interval_minutes"] = max(5, int(minutes))
            self._save()

    def is_sent(self, tweet_id: str) -> bool:
        with self._lock:
            self.data = self._load()
            return str(tweet_id) in self.data.get("sent_tweets", {})

    def mark_sent(self, tweet_id: str, author: str = "", likes: int = 0):
        with self._lock:
            self.data = self._load()
            sent = self.data.setdefault("sent_tweets", {})
            sent[str(tweet_id)] = {
                "sent_at": int(time.time()),
                "author": author,
                "likes": likes
            }
            # Geçmişi makul boyutta tut (en son 1000 tweet)
            if len(sent) > 1000:
                oldest_keys = sorted(sent.keys(), key=lambda k: sent[k].get("sent_at", 0))[:200]
                for k in oldest_keys:
                    sent.pop(k, None)

            self.data["last_run_timestamp"] = int(time.time())
            self._save()

    def touch_last_run(self, backoff_seconds: int = 0):
        with self._lock:
            self.data = self._load()
            if backoff_seconds > 0:
                interval_secs = self.data.get("interval_minutes", 120) * 60
                self.data["last_run_timestamp"] = int(time.time()) - interval_secs + backoff_seconds
            else:
                self.data["last_run_timestamp"] = int(time.time())
            self._save()

# Global tekil örnek
radar_store = RadarStore()
