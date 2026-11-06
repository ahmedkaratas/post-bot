#!/usr/bin/env python3
"""
Oturum ve Çerez Yöneticisi (SessionManager)
Instagram ve Twitter/X oturum çerezlerini data/cookies.json dosyasında kalıcı olarak saklar.
Coolify yeniden deploy'a veya git commit'e gerek kalmadan Telegram üzerinden canlı güncellenmesini sağlar.
"""

import os
import json
import time
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
COOKIES_FILE = os.path.join(DATA_DIR, "cookies.json")

class SessionManager:
    def __init__(self, file_path=COOKIES_FILE):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load(self):
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Çerez okuma hatası: {e}")
            return {}

    def _save(self, data):
        try:
            self._ensure_dir()
            temp_file = f"{self.file_path}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.file_path)
        except Exception as e:
            print(f"Çerez kaydetme hatası: {e}")

    def get_instagram_session_id(self) -> str:
        """Önce data/cookies.json dosyasına, yoksa INSTAGRAM_SESSION_ID env değişkenine bakar."""
        with self._lock:
            data = self._load()
            from_file = (data.get("instagram_session_id") or "").strip()
            if from_file:
                return from_file
        return os.getenv("INSTAGRAM_SESSION_ID", "").strip()

    def set_instagram_session_id(self, session_id: str) -> bool:
        """Yeni Instagram sessionid kaydeder."""
        if not session_id:
            return False
        with self._lock:
            data = self._load()
            data["instagram_session_id"] = session_id.strip()
            data["instagram_updated_at"] = int(time.time())
            self._save(data)
            return True

    def get_twitter_credentials(self) -> tuple:
        """Önce data/cookies.json dosyasına, yoksa TWITTER_AUTH_TOKEN ve TWITTER_CT0 env değişkenlerine bakar."""
        with self._lock:
            data = self._load()
            auth_token = (data.get("twitter_auth_token") or "").strip()
            ct0 = (data.get("twitter_ct0") or "").strip()
            if auth_token and ct0:
                return auth_token, ct0

        env_auth = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
        env_ct0 = os.getenv("TWITTER_CT0", "").strip()
        return env_auth, env_ct0

    def set_twitter_credentials(self, auth_token: str, ct0: str) -> bool:
        """Yeni Twitter/X auth_token ve ct0 kaydeder."""
        if not auth_token or not ct0:
            return False
        with self._lock:
            data = self._load()
            data["twitter_auth_token"] = auth_token.strip()
            data["twitter_ct0"] = ct0.strip()
            data["twitter_updated_at"] = int(time.time())
            self._save(data)
            return True

    def get_status(self) -> dict:
        """Oturum durumunu maskelenmiş olarak döner."""
        ig_session = self.get_instagram_session_id()
        tw_auth, tw_ct0 = self.get_twitter_credentials()
        with self._lock:
            data = self._load()

        def mask(s):
            if not s:
                return "Yok"
            if len(s) <= 8:
                return s[:2] + "****" + s[-2:]
            return s[:4] + "****" + s[-4:]

        return {
            "instagram": {
                "active": bool(ig_session),
                "masked": mask(ig_session),
                "source": "Kalıcı Dosya (data/cookies.json)" if data.get("instagram_session_id") else ("Environment Variable" if ig_session else "Yok"),
                "updated_at": data.get("instagram_updated_at")
            },
            "twitter": {
                "active": bool(tw_auth and tw_ct0),
                "auth_token_masked": mask(tw_auth),
                "ct0_masked": mask(tw_ct0),
                "source": "Kalıcı Dosya (data/cookies.json)" if (data.get("twitter_auth_token") and data.get("twitter_ct0")) else ("Environment Variable" if (tw_auth and tw_ct0) else "Yok"),
                "updated_at": data.get("twitter_updated_at")
            }
        }

session_manager = SessionManager()
