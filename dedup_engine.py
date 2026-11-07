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

def normalize_url(url: str) -> str:
    if not url:
        return ""
    u = str(url).strip()
    u = re.sub(r"^https?://(?:www\.)?twitter\.com", "https://x.com", u)
    u = re.sub(r"^http://", "https://", u)
    u = u.split("?")[0].rstrip("/")
    return u

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
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
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
            clean_id = str(identifier).strip()
            self._in_flight.discard(clean_id)

    def is_sent(self, identifier: str = "", url: str = None, text: str = None) -> bool:
        """
        Herhangi bir tweet ID, reel kodu, URL veya metnin daha önce gönderilip
        gönderilmediğini tüm katmanlarda kontrol eder.
        """
        if not identifier and not url and not text:
            return False

        clean_id = str(identifier).strip() if identifier else ""
        clean_url = normalize_url(str(url).strip()) if url else ""

        status_id = None
        if clean_id.isdigit():
            status_id = clean_id
        elif clean_url:
            m = re.search(r"/status/(\d+)", clean_url)
            if m:
                status_id = m.group(1)

        reel_code = None
        if clean_url:
            rm = re.search(r"/(?:reel|reels)/([a-zA-Z0-9_-]+)", clean_url)
            if rm:
                reel_code = rm.group(1)
        elif clean_id and not clean_id.isdigit() and not clean_id.startswith("http"):
            reel_code = clean_id

        with self._lock:
            # 1. Katman: Uçuş Kilidi (Şu anda başka bir thread tarafından işleniyor mu?)
            if clean_id and clean_id in self._in_flight:
                return True
            if clean_url and clean_url in self._in_flight:
                return True
            if status_id and (status_id in self._in_flight or f"x_{status_id}" in self._in_flight or f"ai_{status_id}" in self._in_flight):
                return True
            if reel_code and (reel_code in self._in_flight or f"ig_{reel_code}" in self._in_flight):
                return True

            # 2. Katman: Kalıcı Kütük (sent_ledger.txt)
            for cand in [clean_id, f"x_{clean_id}", f"ig_{clean_id}", f"ai_{clean_id}"]:
                if cand and cand in self._cached_ledger:
                    return True

            if clean_url and clean_url in self._cached_ledger:
                return True

            if status_id:
                for cand in [status_id, f"x_{status_id}", f"ai_{status_id}"]:
                    if cand in self._cached_ledger:
                        return True
                for entry in self._cached_ledger:
                    if entry.startswith("http") and f"/status/{status_id}" in entry:
                        return True

            if reel_code:
                for cand in [reel_code, f"ig_{reel_code}"]:
                    if cand in self._cached_ledger:
                        return True
                for entry in self._cached_ledger:
                    if entry.startswith("http") and (f"/reel/{reel_code}" in entry or f"/reels/{reel_code}" in entry):
                        return True

            # 3. Katman: URL ve ID eşleşmeleri
            if clean_id:
                for entry in self._cached_ledger:
                    if entry.startswith("http") and (f"/{clean_id}" in entry or f"={clean_id}" in entry):
                        return True

            # 4. Katman: HistoryStore üzerinden geçmiş post kontrolü
            try:
                from history_store import history_store
                target_check_id = clean_id or status_id or reel_code
                if history_store.is_item_already_delivered(target_check_id, link=clean_url, text=text):
                    if status_id:
                        self._append_to_ledger(status_id)
                        self._append_to_ledger(f"x_{status_id}")
                        self._append_to_ledger(f"ai_{status_id}")
                    if reel_code:
                        self._append_to_ledger(reel_code)
                        self._append_to_ledger(f"ig_{reel_code}")
                    if clean_id:
                        self._append_to_ledger(clean_id)
                    if clean_url:
                        self._append_to_ledger(clean_url)
                    return True
            except Exception as hs_err:
                print(f"Dedup HistoryStore kontrol hatası: {hs_err}")

            # 5. Katman: ReelsStore ve RadarStore kontrolü
            try:
                from reels_store import reels_store
                for ct in [clean_id, reel_code, status_id]:
                    if ct and (reels_store.is_sent(ct) or reels_store.is_sent(f"x_{ct}") or reels_store.is_sent(f"ig_{ct}")):
                        return True
            except Exception:
                pass

            try:
                from radar_store import radar_store
                for ct in [clean_id, status_id]:
                    if ct and (radar_store.is_sent(ct) or radar_store.is_sent(f"ai_{ct}") or radar_store.is_sent(f"x_{ct}")):
                        return True
            except Exception:
                pass

            return False

    def mark_sent(self, identifier: str, url: str = None, author: str = "", text: str = ""):
        """İçeriği kalıcı olarak gönderildi olarak işaretler."""
        if not identifier and not url:
            return
        clean_id = str(identifier).strip() if identifier else ""
        clean_url = normalize_url(str(url).strip()) if url else ""

        status_id = None
        if clean_id.isdigit():
            status_id = clean_id
        elif clean_url:
            m = re.search(r"/status/(\d+)", clean_url)
            if m:
                status_id = m.group(1)

        reel_code = None
        if clean_url:
            rm = re.search(r"/(?:reel|reels)/([a-zA-Z0-9_-]+)", clean_url)
            if rm:
                reel_code = rm.group(1)
        elif clean_id and not clean_id.isdigit() and not clean_id.startswith("http"):
            reel_code = clean_id

        with self._lock:
            # Uçuş kilitlerini kaldır
            for release_cand in [clean_id, clean_url, status_id, reel_code]:
                if release_cand:
                    self._in_flight.discard(release_cand)

            # Kütüğe tüm varyantlarıyla ekle
            if clean_id:
                self._append_to_ledger(clean_id)
                self._append_to_ledger(f"x_{clean_id}")
                self._append_to_ledger(f"ai_{clean_id}")
                self._append_to_ledger(f"ig_{clean_id}")

            if status_id:
                self._append_to_ledger(status_id)
                self._append_to_ledger(f"x_{status_id}")
                self._append_to_ledger(f"ai_{status_id}")

            if reel_code:
                self._append_to_ledger(reel_code)
                self._append_to_ledger(f"ig_{reel_code}")

            if clean_url:
                self._append_to_ledger(clean_url)
            if url and str(url).strip() != clean_url:
                self._append_to_ledger(str(url).strip())

            # Store'lara da yaz
            try:
                from reels_store import reels_store
                for sid in [clean_id, reel_code, status_id]:
                    if sid:
                        reels_store.mark_sent(sid, username=author)
                        reels_store.mark_sent(f"x_{sid}", username=author)
                        reels_store.mark_sent(f"ig_{sid}", username=author)
            except Exception:
                pass

            try:
                from radar_store import radar_store
                for sid in [clean_id, status_id]:
                    if sid:
                        radar_store.mark_sent(sid, author=author)
                        radar_store.mark_sent(f"ai_{sid}", author=author)
                        radar_store.mark_sent(f"x_{sid}", author=author)
            except Exception:
                pass

dedup_engine = DedupEngine()
