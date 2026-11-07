#!/usr/bin/env python3
"""
Merkezi Tekilleştirme Motoru (DedupEngine)
Tüm radar, video, reels ve AI tweet içeriklerinin mükerrer (aynı) gönderilmesini engeller.
Claim / Confirm / Abort yaşam döngüsü ile ağ zaman aşımlarında içeriğin mükerrer seçilmesini önler.
Ayrıca başlık + yazar normalizasyonu (25 karakter eşiği) ile aynı içerik farklı ID ile gelse dahi yakalar.
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

def normalize_author(author: str) -> str:
    if not author:
        return ""
    a = str(author).strip().lower().lstrip("@")
    return re.sub(r"[^a-z0-9_]", "", a)

def normalize_text_content(text: str) -> str:
    if not text:
        return ""
    t = str(text).lower()
    # Linkleri temizle
    t = re.sub(r"https?://\S+", " ", t)
    # Mention'ları (@kullanici) temizle
    t = re.sub(r"@\w+", " ", t)
    # Noktalama ve özel karakterleri boşluğa çevir
    t = re.sub(r"[^\w\s]", " ", t)
    # Boşlukları normalize et
    t = re.sub(r"\s+", " ", t).strip()
    return t

def get_text_signature(author: str, text: str) -> str:
    """Yazar ve metin için tekilleştirme imzası üretir (eşik: 25 karakter)."""
    clean_t = normalize_text_content(text)
    if len(clean_t) < 25:
        return ""
    clean_a = normalize_author(author)
    return f"sig:{clean_a}:{clean_t[:100]}"

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

    def reload(self):
        """Kütüğü diskten yeniden yükler."""
        with self._lock:
            self._cached_ledger = self._load_ledger()

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
                            author = p.get("author", "")
                            text = p.get("text", "")
                            if link:
                                self._cached_ledger.add(link)
                                m = re.search(r"/status/(\d+)", link)
                                if m:
                                    tid = m.group(1)
                                    self._cached_ledger.add(tid)
                                    self._cached_ledger.add(f"x_{tid}")
                                    self._cached_ledger.add(f"ai_{tid}")
                                r_m = re.search(r"/(?:reel|reels)/([a-zA-Z0-9_-]+)", link)
                                if r_m:
                                    rcode = r_m.group(1)
                                    self._cached_ledger.add(rcode)
                                    self._cached_ledger.add(f"ig_{rcode}")
                            if author and text:
                                sig = get_text_signature(author, text)
                                if sig:
                                    self._cached_ledger.add(sig)
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

    def get_ledger_count(self) -> int:
        with self._lock:
            return len(self._cached_ledger)

    def is_sent(self, identifier: str = "", url: str = None, text: str = None, author: str = "") -> bool:
        """
        Herhangi bir tweet ID, reel kodu, URL, metin veya yazar imzasının
        daha önce gönderilip gönderilmediğini veya şu an işlenip işlenmediğini denetler.
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

        text_sig = get_text_signature(author, text) if (author and text) else ""

        with self._lock:
            # 1. Katman: Uçuş Kilidi (In-Flight)
            cands_to_check = [clean_id, clean_url, status_id, reel_code, text_sig]
            for cand in cands_to_check:
                if cand and cand in self._in_flight:
                    return True
                if cand and f"CLAIM:{cand}" in self._in_flight:
                    return True

            if status_id and (f"x_{status_id}" in self._in_flight or f"ai_{status_id}" in self._in_flight):
                return True
            if reel_code and (f"ig_{reel_code}" in self._in_flight):
                return True

            # 2. Katman: Kalıcı Kütük (sent_ledger.txt) ve CLAIM kayıtları
            for cand in [clean_id, f"x_{clean_id}", f"ig_{clean_id}", f"ai_{clean_id}", f"rp_{clean_id}"]:
                if cand and (cand in self._cached_ledger or f"CLAIM:{cand}" in self._cached_ledger):
                    return True

            if clean_url and (clean_url in self._cached_ledger or f"CLAIM:{clean_url}" in self._cached_ledger):
                return True

            if text_sig and (text_sig in self._cached_ledger or f"CLAIM:{text_sig}" in self._cached_ledger):
                return True

            if status_id:
                for cand in [status_id, f"x_{status_id}", f"ai_{status_id}", f"rp_{status_id}"]:
                    if cand in self._cached_ledger or f"CLAIM:{cand}" in self._cached_ledger:
                        return True
                for entry in self._cached_ledger:
                    if entry.startswith("http") and f"/status/{status_id}" in entry:
                        return True

            if reel_code:
                for cand in [reel_code, f"ig_{reel_code}"]:
                    if cand in self._cached_ledger or f"CLAIM:{cand}" in self._cached_ledger:
                        return True
                for entry in self._cached_ledger:
                    if entry.startswith("http") and (f"/reel/{reel_code}" in entry or f"/reels/{reel_code}" in entry):
                        return True

            # 3. Katman: HistoryStore üzerinden geçmiş post kontrolü
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
                    if text_sig:
                        self._append_to_ledger(text_sig)
                    return True
            except Exception as hs_err:
                print(f"Dedup HistoryStore kontrol hatası: {hs_err}")

            # 4. Katman: ReelsStore ve RadarStore kontrolü
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
                    if ct and (radar_store.is_sent(ct) or radar_store.is_sent(f"ai_{ct}") or radar_store.is_sent(f"x_{ct}") or radar_store.is_sent(f"rp_{ct}")):
                        return True
            except Exception:
                pass

            return False

    def claim(self, identifier: str, url: str = None, author: str = "", text: str = "") -> bool:
        """
        İçeriği göndermeden ÖNCE kalıcı olarak 'denendi' (CLAIM) diye kütüğe yazar.
        Ağ zaman aşımı (timeout=90) veya bağlantı kopmasında bu kayıt silinmez!
        """
        if not identifier and not url and not text:
            return False

        with self._lock:
            if self.is_sent(identifier=identifier, url=url, text=text, author=author):
                return False

            clean_id = str(identifier).strip() if identifier else ""
            clean_url = normalize_url(str(url).strip()) if url else ""
            text_sig = get_text_signature(author, text) if (author and text) else ""

            # In-flight'a ekle
            for item in [clean_id, clean_url, text_sig]:
                if item:
                    self._in_flight.add(item)
                    self._in_flight.add(f"CLAIM:{item}")

            # Kalıcı kütüğe CLAIM olarak yaz (disk garantisi)
            if clean_id:
                self._append_to_ledger(f"CLAIM:{clean_id}")
            if clean_url:
                self._append_to_ledger(f"CLAIM:{clean_url}")
            if text_sig:
                self._append_to_ledger(f"CLAIM:{text_sig}")

            return True

    def confirm(self, identifier: str, url: str = None, author: str = "", text: str = ""):
        """İçerik başarıyla teslim edildiğinde kesin gönderildi (CONFIRMED) olarak kütükler."""
        self.mark_sent(identifier=identifier, url=url, author=author, text=text)

    def abort(self, identifier: str, url: str = None, author: str = "", text: str = "",
              is_definitive_error: bool = False):
        """
        Gönderim net bir HTTP hatası (400 Bad Request vb.) verirse kilidi iptal eder.
        ZAMAN AŞIMI VEYA BAĞLANTI KOPMASINDA is_definitive_error=False OLACAĞI İÇİN
        KAYDI KORUR (mükerrer gönderimi garantili engeller).
        """
        clean_id = str(identifier).strip() if identifier else ""
        clean_url = normalize_url(str(url).strip()) if url else ""
        text_sig = get_text_signature(author, text) if (author and text) else ""

        with self._lock:
            if is_definitive_error:
                # Net hata: Uçuş kilidini kaldır
                for item in [clean_id, clean_url, text_sig]:
                    if item:
                        self._in_flight.discard(item)
                        self._in_flight.discard(f"CLAIM:{item}")
                        self._cached_ledger.discard(f"CLAIM:{item}")
                print(f"ℹ️ [DedupEngine] Net hata nedeniyle kilit iptal edildi: {clean_id or clean_url}")
            else:
                # Belirsiz hata veya timeout: Kaydı KORU!
                # Telegram videoyu/postu göndermiş olabilir, mükerrerliği önlemek için release YAPILMAZ!
                print(f"🛡️ [DedupEngine] Zaman aşımı/belirsiz bağlantı hatası: Kilit KORUNDU ({clean_id or clean_url})")

    def reserve(self, identifier: str) -> bool:
        """Geriye dönük uyumluluk: claim() çağırır."""
        return self.claim(identifier=identifier)

    def release(self, identifier: str):
        """Geriye dönük uyumluluk: Sadece net hata durumunda çağrılırsa iptal eder."""
        self.abort(identifier=identifier, is_definitive_error=True)

    def mark_sent(self, identifier: str, url: str = None, author: str = "", text: str = ""):
        """İçeriği kalıcı olarak gönderildi olarak kütüğe yazar ve mağazaları senkronize eder."""
        if not identifier and not url and not text:
            return

        clean_id = str(identifier).strip() if identifier else ""
        clean_url = normalize_url(str(url).strip()) if url else ""
        text_sig = get_text_signature(author, text) if (author and text) else ""

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
            for release_cand in [clean_id, clean_url, status_id, reel_code, text_sig]:
                if release_cand:
                    self._in_flight.discard(release_cand)
                    self._in_flight.discard(f"CLAIM:{release_cand}")

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

            if text_sig:
                self._append_to_ledger(text_sig)

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
