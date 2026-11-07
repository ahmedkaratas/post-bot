#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
topic_manager.py: Telegram forum / konu (oda) bazlı görev ayrıştırma ve rol yönetimi.
Her konunun (oda) sadece kendi görevini yapmasını sağlar (Sorun 2).
"""

import os
import re
import json
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TOPICS_FILE = os.path.join(DATA_DIR, "topics.json")

VALID_ROLES = {
    "reels": "ViralReels (Sadece reels ve video radarı)",
    "tweet": "ViralTweet (Sadece viral tweet radarı)",
    "photo": "SadeceFotoğraf (Sadece 1080x1350 tuval görsel işleme)",
    "link": "Link & Paket (/url, /url2, /ig ve doğrudan X linkleri)",
    "general": "General (Genel yönetim, durum, oturum ve yedek)",
    "test": "Test/Deneme (Tüm komutlar serbest, filtresiz)",
    "notes": "Notlar & Geçmiş (/gecmis, /tuttu, /not, /sil vb.)",
    "comments": "Yorumlar (Tamamen sessiz oda)"
}

ROLE_EMOJIS = {
    "reels": "🎬",
    "tweet": "🛰️",
    "photo": "📸",
    "link": "🔗",
    "general": "⚙️",
    "test": "🧪",
    "notes": "📝",
    "comments": "💬"
}

class TopicManager:
    def __init__(self, topics_file=None):
        self.topics_file = topics_file or TOPICS_FILE
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        d = os.path.dirname(self.topics_file)
        if d and not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

    def _load(self) -> dict:
        if os.path.exists(self.topics_file):
            try:
                with open(self.topics_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data.setdefault("roles", {})
                        data.setdefault("threads", {})
                        return data
            except Exception as e:
                print(f"[TopicManager] topics.json okuma hatası: {e}")
        return {"roles": {}, "threads": {}}

    def _save(self, data: dict):
        self._ensure_dir()
        temp_file = self.topics_file + ".tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.topics_file)
        except Exception as e:
            print(f"[TopicManager] topics.json yazma hatası: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def set_topic_role(self, role: str, chat_id: int, thread_id=None, title: str = "") -> (bool, str):
        """Bir konuya/odaya (chat_id + thread_id) belirtilen rolü atar."""
        role = (role or "").strip().lower()
        if role not in VALID_ROLES:
            valid_list = ", ".join(f"<code>{r}</code>" for r in VALID_ROLES.keys())
            return False, f"❌ Geçersiz rol: <code>{role}</code>\nGeçerli roller: {valid_list}"

        t_key = f"{chat_id}:{thread_id}"
        with self._lock:
            data = self._load()
            roles = data.setdefault("roles", {})
            threads = data.setdefault("threads", {})

            # Eğer bu rol daha önce başka bir odaya atanmışsa, eski thread bağını temizle
            old_assignment = roles.get(role)
            if old_assignment:
                old_key = f"{old_assignment.get('chat_id')}:{old_assignment.get('thread_id')}"
                if old_key in threads and threads[old_key] == role:
                    del threads[old_key]

            # Yeni odaya bu rolü bağla
            roles[role] = {
                "chat_id": chat_id,
                "thread_id": thread_id,
                "title": title or "",
            }
            threads[t_key] = role
            self._save(data)

        emoji = ROLE_EMOJIS.get(role, "📌")
        desc = VALID_ROLES.get(role, "")
        thread_info = f"Thread: <code>{thread_id}</code>" if thread_id else "Genel Akış"
        return True, (
            f"✅ {emoji} <b>Oda Rolü Atandı:</b> <code>{role}</code>\n"
            f"• <b>Görev:</b> {desc}\n"
            f"• <b>Konu:</b> {thread_info}\n"
            f"• <b>Chat ID:</b> <code>{chat_id}</code>"
        )

    def delete_topic_role(self, role: str) -> (bool, str):
        """Belirtilen role ait oda atamasını kaldırır."""
        role = (role or "").strip().lower()
        with self._lock:
            data = self._load()
            roles = data.setdefault("roles", {})
            threads = data.setdefault("threads", {})

            if role not in roles:
                return False, f"⚠️ <code>{role}</code> rolü zaten herhangi bir odaya atanmamış."

            old_assignment = roles.pop(role, None)
            if old_assignment:
                old_key = f"{old_assignment.get('chat_id')}:{old_assignment.get('thread_id')}"
                threads.pop(old_key, None)

            # Threads içinde bu role işaret eden başka anahtar kalmışsa temizle
            threads_to_del = [k for k, v in threads.items() if v == role]
            for k in threads_to_del:
                del threads[k]

            self._save(data)

        return True, f"🗑️ <b>'{role}' rol ataması başarıyla kaldırıldı.</b>"

    def get_role_for_thread(self, chat_id: int, thread_id=None) -> str:
        """Verilen chat ve thread için atanmış rolü döner (yoksa None)."""
        t_key = f"{chat_id}:{thread_id}"
        with self._lock:
            data = self._load()
            threads = data.get("threads", {})
            if t_key in threads:
                return threads[t_key]
            # Genel grupta thread_id 1 veya None gelebilir
            if thread_id is None and f"{chat_id}:1" in threads:
                return threads[f"{chat_id}:1"]
            if thread_id == 1 and f"{chat_id}:None" in threads:
                return threads[f"{chat_id}:None"]
        return None

    def get_target_for_role(self, role: str) -> dict:
        """Belirtilen rolün kayıtlı chat_id ve thread_id bilgilerini döner."""
        role = (role or "").strip().lower()
        with self._lock:
            data = self._load()
            return data.get("roles", {}).get(role)

    def get_all_roles(self) -> dict:
        """Kayıtlı tüm oda rollerini döner."""
        with self._lock:
            data = self._load()
            return dict(data.get("roles", {}))

    def determine_command_role(self, text: str, message: dict = None) -> str:
        """
        Mesaj veya komutun ait olduğu doğru oda rolünü tespit eder.
        Dönüş: 'reels', 'tweet', 'photo', 'link', 'general', 'test', 'notes', 'management' veya None
        """
        t = (text or "").strip()
        msg = message or {}

        # 1. Oda yönetim komutları (her odada çalışabilir)
        if (t.startswith("/oda_ata") or t == "/oda" or t.startswith("/oda ") or
                t.startswith("/odalar") or t.startswith("/oda_sil")):
            return "management"

        # 2. Viral Reels / Video Komutları
        if (t.startswith("/reels_now") or t.startswith("/reels_start") or
                t.startswith("/reels_stop") or t.startswith("/reels_status") or
                t.startswith("/reels_interval") or t.startswith("/reels_plays") or
                t.startswith("/reels_likes") or t.startswith("/reels_age") or
                t.startswith("/reels_config") or t.startswith("/reels_target")):
            return "reels"

        # 3. Viral Tweet Radarı Komutları
        if (t.startswith("/radar_now") or t.startswith("/ai_radar_now") or
                t.startswith("/repost_now") or t.startswith("/radar_start") or
                t.startswith("/radar_stop") or t.startswith("/radar_status") or
                t.startswith("/radar_interval") or t.startswith("/radar_set") or
                t.startswith("/radar_config") or t.startswith("/radar_target")):
            return "tweet"

        # 4. Link & Tam Paket Komutları
        if (t.startswith("/url") or t.startswith("/url2") or
                t.startswith("/ig") or t.startswith("/img")):
            return "link"
        if re.search(r"https?://(?:twitter\.com|x\.com|fixupx\.com|vxtwitter\.com|fxtwitter\.com)/[a-zA-Z0-9_]+/status/\d+", t):
            return "link"

        # 5. Notlar & Geçmiş & Geri Bildirim Komutları
        if (t.startswith("/gecmis") or t.startswith("/tuttu") or
                t.startswith("/tutmadi") or t.startswith("/sonuc") or
                t.startswith("/ekle") or t.startswith("/ornekler") or
                t.startswith("/not") or t.startswith("/sil") or t.startswith("/stats")):
            return "notes"

        # 6. Genel Yönetim & Durum Komutları
        if (t.startswith("/durum") or t.startswith("/help") or
                t.startswith("/start") or t.startswith("/session_status") or
                t.startswith("/oturum") or t.startswith("/yedek_ata") or
                t.startswith("/yedek_al") or t.startswith("/set_ig") or
                t.startswith("/set_x")):
            return "general"

        # 7. Fotoğraf / Dekupe
        caption = (msg.get("caption") or "").strip()
        if caption.startswith("/d") or caption.startswith("/dekupe") or re.search(r'(^|\s)/d(\s|$)', caption):
            return "photo"
        if "photo" in msg or ("document" in msg and (msg["document"].get("mime_type") or "").startswith("image/")):
            return "photo"

        # Eğer '/' ile başlayan bilinmeyen bir komutsa 'general' kabul et
        if t.startswith("/"):
            return "general"

        return None

topic_manager = TopicManager()
