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

def _clean_cookie_val(val: str, prefix: str = "") -> str:
    """Çerez değerinden tırnakları, noktalı virgülleri ve 'sessionid=' gibi ön ekleri temizler."""
    if not val:
        return ""
    val = str(val).strip().strip('"\'').strip(';')
    if prefix:
        if val.startswith(f"{prefix}="):
            val = val[len(prefix) + 1:].strip().strip('"\'').strip(';')
        elif f"{prefix}=" in val:
            import re
            m = re.search(rf"{prefix}=([^;\s]+)", val)
            if m:
                val = m.group(1).strip().strip('"\'')
    return val.strip()

def is_storage_mount_separate() -> bool:
    """os.stat st_dev karşılaştırması ile data dizininin ayrı bir mount/volume olup olmadığını denetler."""
    try:
        data_stat = os.stat(DATA_DIR)
        parent_stat = os.stat(os.path.dirname(DATA_DIR) or "/")
        return data_stat.st_dev != parent_stat.st_dev
    except Exception:
        return False

def is_persistent_storage_mounted() -> bool:
    """
    Kalıcı depolama kontrolü:
    1. os.stat st_dev karşılaştırması (ayrı cihaz mı?)
    2. .boot_log'un korunmuş olması (yeniden başlatmalarda hayatta kaldı mı?)
    """
    separate = is_storage_mount_separate()
    boot_log_file = os.path.join(DATA_DIR, ".boot_log")
    survived = os.path.exists(boot_log_file) and os.path.getsize(boot_log_file) > 0
    return separate or survived

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
        """Yeni Instagram sessionid kaydeder. Otomatik temizleme uygular."""
        if not session_id:
            return False
        clean_sid = _clean_cookie_val(session_id, "sessionid")
        if not clean_sid:
            return False
        with self._lock:
            data = self._load()
            data["instagram_session_id"] = clean_sid
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
        """Yeni Twitter/X auth_token ve ct0 kaydeder. Karışıklığı ve ön ekleri otomatik düzeltir."""
        if not auth_token or not ct0:
            return False
        c_auth = _clean_cookie_val(auth_token, "auth_token")
        c_ct0 = _clean_cookie_val(ct0, "ct0")

        # Kullanıcı auth_token ve ct0 sırasını ters yazarsa akıllıca düzelt:
        # ct0 genelde ~160 karakterdir, auth_token ise ~40 karakterdir.
        if len(c_auth) > 100 and len(c_ct0) <= 50:
            c_auth, c_ct0 = c_ct0, c_auth

        with self._lock:
            data = self._load()
            data["twitter_auth_token"] = c_auth
            data["twitter_ct0"] = c_ct0
            data["twitter_updated_at"] = int(time.time())
            self._save(data)
            return True

    def verify_instagram_session(self, session_id: str = None) -> tuple:
        """Instagram sessionid değerini Instagram API'sine canlı sorgu atarak doğrular."""
        import requests
        import urllib.parse
        sid = session_id or self.get_instagram_session_id()
        if not sid:
            return False, "Tanımsız / Eksik"
            
        uid = ""
        try:
            decoded = urllib.parse.unquote(sid)
            parts = decoded.split(":")
            if parts and parts[0].isdigit():
                uid = parts[0]
        except Exception:
            pass

        cookie_str = f"sessionid={sid};"
        if uid:
            cookie_str += f" ds_user_id={uid};"

        headers = {
            "User-Agent": "Instagram 300.0.0.18.110 (iPhone14,3; iOS 16_6; en_US; en-US; scale=3.00; 1170x2532; 513072223) AppleWebKit/420+",
            "Cookie": cookie_str,
            "X-IG-App-ID": "936619743392459"
        }
        try:
            resp = requests.post(
                "https://i.instagram.com/api/v1/clips/discover/",
                headers=headers,
                data={"container_module": "clips_viewer_clips_netego"},
                timeout=8
            )
            if resp.status_code == 200:
                return True, "🟢 Geçerli & Aktif (HTTP 200)"
            elif resp.status_code == 403:
                try:
                    data = resp.json()
                    msg = data.get("message") or ""
                    if "checkpoint" in msg or "challenge" in msg:
                        return False, "⚠️ Güvenlik Onayı Gerekli (Instagram uygulamanızdan 'Bunu Ben Yaptım' onayını verin)"
                    elif "login_required" in msg:
                        return False, "🔴 Oturum Kapanmış / Çıkış Yapılmış (login_required)"
                    elif "feedback_required" in msg:
                        return False, "⚠️ Geçici Hız Sınırı (feedback_required - birkaç dakika bekleyin)"
                    else:
                        return False, f"🔴 HTTP 403: {msg or 'Erişim Engellendi'}"
                except Exception:
                    return False, "🔴 Süresi Dolmuş veya Engellenmiş (HTTP 403)"
            else:
                return False, f"⚠️ HTTP {resp.status_code}"
        except Exception as e:
            return False, f"⚠️ Bağlantı hatası: {str(e)[:30]}"

    def get_status(self, verify_live: bool = False) -> dict:
        """Oturum durumunu maskelenmiş olarak döner. verify_live=True ise canlı API testi yapar."""
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

        ig_live_msg = None
        if verify_live and ig_session:
            _, ig_live_msg = self.verify_instagram_session(ig_session)

        return {
            "instagram": {
                "active": bool(ig_session),
                "live_status": ig_live_msg,
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
            },
            "storage_persistent": is_persistent_storage_mounted()
        }

session_manager = SessionManager()
