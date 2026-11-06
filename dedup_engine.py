#!/usr/bin/env python3
"""
Merkezi Tekilleştirme Motoru (DedupEngine)
Tüm radar, video, reels ve AI tweet içeriklerinin mükerrer (aynı) gönderilmesini engeller.
5 katmanlı savunma hattı:
1. Anlık uçuş kilidi (_in_flight_set): Aynı anda taranıp indirilen videoların çakışmasını engeller.
2. Append-Only Kalıcı Kütük (data/sent_ledger.txt): Disk yarışlarından (race condition) etkilenmeyen kalıcı kayıt.
3. ReelsStore (data/reels_radar_data.json): Instagram ve X video kodları.
4. RadarStore (data/radar_data.json): Tweet ID'leri.
5. HistoryStore (data/post_history.json): Botun şimdiye kadar attığı tüm postların URL ve metin geçmişi.
"""

import os
import re
import time
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LEDGER_FILE = os.path.join(DATA_DIR, "sent_ledger.txt")

class DedupEngine:
    def __init__(self, ledger_file=None, data_dir=None, sync_on_init=True):
        self.data_dir = data_dir or DATA_DIR
        self.ledger_file = ledger_file or os.path.join(self.data_dir, "sent_ledger.txt")
        self._lock = threading.RLock()
        self._in_flight = set()
        self._ensure_dir()
        self._cached_ledger = self._load_ledger()
        if sync_on_init:
            self._sync_from_existing_stores()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.ledger_file), exist_ok=True)

    def _load_ledger(self) -> set:
        """Kalıcı kütük dosyasını belleğe yükler."""
        if not os.path.exists(self.ledger_file):
            return set()
        try:
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                return {line.strip() for line in f if line.strip()}
        except Exception as e:
            print(f"Kütük okuma hatası: {e}")
            return set()

    def _sync_from_existing_stores(self):
        """Mevcut post_history, radar ve reels verilerindeki tüm eski ID'leri kütüğe aktarır."""
        with self._lock:
            # 1. post_history.json'dan URL ve ID'leri çek
            try:
                hist_file = os.path.join(self.data_dir, "post_history.json")
                if os.path.exists(hist_file):
                    import json
                    with open(hist_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        posts = data.get("posts", {})
                        for p in posts.values():
                            link = p.get("link", "")
                            if link:
                                self._cached_ledger.add(link)
                                # Tweet ID ayıkla
                                m = re.search(r"/status/(\d+)", link)
                                if m:
                                    tid = m.group(1)
                                    self._cached_ledger.add(tid)
                                    self._cached_ledger.add(f"x_{tid}")
                                    self._cached_ledger.add(f"ai_{tid}")
                                # Reels code ayıkla
                                r_m = re.search(r"/(?:reel|reels)/([a-zA-Z0-9_-]+)", link)
                                if r_m:
                                    rcode = r_m.group(1)
                                    self._cached_ledger.add(rcode)
                                    self._cached_ledger.add(f"ig_{rcode}")
            except Exception as e:
                print(f"Post history kütük eşleme hatası: {e}")

            # 2. radar_data.json'dan çek
            try:
                radar_file = os.path.join(self.data_dir, "radar_data.json")
                if os.path.exists(radar_file):
                    import json
                    with open(radar_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for tid in data.get("sent_tweets", {}).keys():
                            self._cached_ledger.add(str(tid))
            except Exception:
                pass

            # 3. reels_radar_data.json'dan çek
            try:
                reels_file = os.path.join(self.data_dir, "reels_radar_data.json")
                if os.path.exists(reels_file):
                    import json
                    with open(reels_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for code in data.get("sent_reels", {}).keys():
                            self._cached_ledger.add(str(code))
            except Exception:
                pass

            # Kütük dosyasına yaz
            self._save_ledger_bulk(self._cached_ledger)

    def _save_ledger_bulk(self, items: set):
        try:
            self._ensure_dir()
            with open(self.ledger_file, "w", encoding="utf-8") as f:
                for it in sorted(items):
                    f.write(f"{it}\n")
        except Exception as e:
            print(f"Kütük toplu kaydetme hatası: {e}")

    def _append_to_ledger(self, identifier: str):
        if not identifier:
            return
        identifier = str(identifier).strip()
        with self._lock:
            if identifier in self._cached_ledger:
                return
            self._cached_ledger.add(identifier)
            try:
                with open(self.ledger_file, "a", encoding="utf-8") as f:
                    f.write(f"{identifier}\n")
            except Exception as e:
                print(f"Kütük ekleme hatası: {e}")

    def reserve(self, identifier: str) -> bool:
        """İçerik indirilip gönderilene kadar geçici uçuş kilidi koyar."""
        if not identifier:
            return False
        with self._lock:
            clean_id = str(identifier).strip()
            if self.is_sent(clean_id):
                return False
            if clean_id in self._in_flight:
                return False
            self._in_flight.add(clean_id)
            return True

    def release(self, identifier: str):
        """Gönderim başarısız olursa uçuş kilidini kaldırır."""
        if not identifier:
            return
        with self._lock:
            self._in_flight.discard(str(identifier).strip())

    def is_sent(self, identifier: str = "", url: str = None, text: str = None) -> bool:
        """
        Herhangi bir tweet ID, reel kodu, URL veya metnin daha önce gönderilip
        gönderilmediğini tüm katmanlarda kontrol eder.
        """
        if not identifier and not url and not text:
            return False

        clean_id = str(identifier).strip() if identifier else ""
        clean_url = str(url).strip() if url else ""

        with self._lock:
            # 1. Katman: Uçuş Kilidi (Şu anda başka bir thread tarafından işleniyor mu?)
            if clean_id and clean_id in self._in_flight:
                return True
            if clean_url and clean_url in self._in_flight:
                return True

            # 2. Katman: Kalıcı Kütük (sent_ledger.txt)
            if clean_id and clean_id in self._cached_ledger:
                return True
            if clean_id and f"x_{clean_id}" in self._cached_ledger:
                return True
            if clean_id and f"ig_{clean_id}" in self._cached_ledger:
                return True
            if clean_id and f"ai_{clean_id}" in self._cached_ledger:
                return True
            if clean_url and clean_url in self._cached_ledger:
                return True

            # 3. Katman: URL ve ID eşleşmeleri
            if clean_id:
                for entry in self._cached_ledger:
                    if entry.startswith("http") and (f"/{clean_id}" in entry or f"={clean_id}" in entry):
                        return True

            if clean_url:
                m = re.search(r"/status/(\d+)", clean_url)
                if m and (m.group(1) in self._cached_ledger or f"x_{m.group(1)}" in self._cached_ledger):
                    return True
                r_m = re.search(r"/(?:reel|reels)/([a-zA-Z0-9_-]+)", clean_url)
                if r_m and (r_m.group(1) in self._cached_ledger or f"ig_{r_m.group(1)}" in self._cached_ledger):
                    return True

            # 4. Katman: HistoryStore üzerinden geçmiş post kontrolü (Sadece ana dizinde)
            if self.data_dir == DATA_DIR:
                try:
                    from history_store import history_store
                    if history_store.is_item_already_delivered(clean_id, link=clean_url, text=text):
                        if clean_id:
                            self._append_to_ledger(clean_id)
                        if clean_url:
                            self._append_to_ledger(clean_url)
                        return True
                except Exception:
                    pass

                # 5. Katman: ReelsStore ve RadarStore kontrolü
                try:
                    from reels_store import reels_store
                    if clean_id and (reels_store.is_sent(clean_id) or reels_store.is_sent(f"x_{clean_id}") or reels_store.is_sent(f"ig_{clean_id}")):
                        return True
                except Exception:
                    pass

                try:
                    from radar_store import radar_store
                    if clean_id and (radar_store.is_sent(clean_id) or radar_store.is_sent(f"ai_{clean_id}")):
                        return True
                except Exception:
                    pass

            return False

    def mark_sent(self, identifier: str, url: str = None, author: str = "", text: str = ""):
        """İçeriği kalıcı olarak gönderildi olarak işaretler."""
        if not identifier:
            return
        clean_id = str(identifier).strip()
        clean_url = str(url).strip() if url else ""

        with self._lock:
            # Uçuş kilidini kaldır
            self._in_flight.discard(clean_id)
            if clean_url:
                self._in_flight.discard(clean_url)

            # Kütüğe tüm varyantlarıyla ekle
            self._append_to_ledger(clean_id)
            self._append_to_ledger(f"x_{clean_id}")
            self._append_to_ledger(f"ai_{clean_id}")
            self._append_to_ledger(f"ig_{clean_id}")
            if clean_url:
                self._append_to_ledger(clean_url)

            # Store'lara da yaz (Sadece ana dizinde)
            if self.data_dir == DATA_DIR:
                try:
                    from reels_store import reels_store
                    reels_store.mark_sent(clean_id, username=author)
                    reels_store.mark_sent(f"x_{clean_id}", username=author)
                    reels_store.mark_sent(f"ig_{clean_id}", username=author)
                except Exception:
                    pass

                try:
                    from radar_store import radar_store
                    radar_store.mark_sent(clean_id, author=author)
                    radar_store.mark_sent(f"ai_{clean_id}", author=author)
                except Exception:
                    pass

dedup_engine = DedupEngine()
