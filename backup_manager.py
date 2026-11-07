#!/usr/bin/env python3
"""
Telegram Veri Yedeği ve Geri Yükleme Yöneticisi (BackupManager)
Tüm kalıcı bot verilerini (sent_ledger.txt, post_history.json, radar_data.json,
reels_radar_data.json, topics.json, cookies.json) özel bir Telegram kanalında
zip + manifest.json olarak saklar ve açılışta otomatik geri yükler.
"""

import os
import io
import json
import time
import zipfile
import threading
from datetime import datetime, timezone
import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BACKUP_TARGET_FILE = os.path.join(DATA_DIR, "backup_target.json")
BACKUP_META_FILE = os.path.join(DATA_DIR, "backup_meta.json")
BOOT_LOG_FILE = os.path.join(DATA_DIR, ".boot_log")
ADMIN_CONFIG_FILE = os.path.join(DATA_DIR, "admin_config.json")

# Kullanıcı /yedek_ata çalıştırdıktan sonra verilen ID buraya yazılabilir (opsiyonel kod sabiti)
BACKUP_CHAT_ID_DEFAULT = ""
ADMIN_CHAT_ID_DEFAULT = ""

_backup_lock = threading.RLock()
_debounce_timer = None
_has_unsaved_changes = False

BACKUP_FILES = [
    "sent_ledger.txt",
    "post_history.json",
    "radar_data.json",
    "reels_radar_data.json",
    "topics.json",
    "cookies.json"
]

def get_admin_chat_id() -> str:
    """Admin kullanıcı / sohbet ID'sini döner."""
    env_id = (os.getenv("ADMIN_CHAT_ID") or os.getenv("OWNER_USER_ID") or "").strip()
    if env_id:
        return env_id
    if os.path.exists(ADMIN_CONFIG_FILE):
        try:
            with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cid = str(data.get("admin_chat_id") or "").strip()
                if cid:
                    return cid
        except Exception:
            pass
    return BACKUP_CHAT_ID_DEFAULT or ADMIN_CHAT_ID_DEFAULT

def set_admin_chat_id(chat_id) -> bool:
    """Admin kullanıcı / sohbet ID'sini kaydeder."""
    if not chat_id:
        return False
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ADMIN_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "admin_chat_id": str(chat_id).strip(),
                "updated_at": int(time.time())
            }, f, indent=2)
        return True
    except Exception as e:
        print(f"Admin ID kaydetme hatası: {e}")
        return False

def notify_admin(api_url: str, message_text: str):
    """Admin'e özel mesaj (DM) ile bildirim iletir ve konsola yazar."""
    admin_id = get_admin_chat_id()
    print(f"📢 [ADMIN BİLDİRİMİ]: {message_text}")
    if admin_id and api_url:
        try:
            requests.post(
                f"{api_url}/sendMessage",
                json={
                    "chat_id": admin_id,
                    "text": message_text,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
        except Exception as e:
            print(f"Admin DM gönderme hatası: {e}")

def get_backup_chat_id() -> str:
    """Önce BACKUP_CHAT_ID env değişkenine, sonra backup_target.json'a, sonra koddaki sabite bakar."""
    env_id = os.getenv("BACKUP_CHAT_ID", "").strip()
    if env_id:
        return env_id
    if os.path.exists(BACKUP_TARGET_FILE):
        try:
            with open(BACKUP_TARGET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                tid = str(data.get("backup_chat_id") or "").strip()
                if tid:
                    return tid
        except Exception:
            pass
    return BACKUP_CHAT_ID_DEFAULT.strip()

def set_backup_chat_id(chat_id: str | int) -> bool:
    """Yedek hedef Telegram kanalı ID'sini kalıcı kaydeder."""
    if not chat_id:
        return False
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BACKUP_TARGET_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "backup_chat_id": str(chat_id).strip(),
                "updated_at": int(time.time()),
                "updated_iso": datetime.now(timezone.utc).isoformat()
            }, f, indent=2)
        return True
    except Exception as e:
        print(f"Yedek hedefi kaydetme hatası: {e}")
        return False

def record_boot(instance_id: str) -> dict:
    """
    Açılışta data/.boot_log dosyasına kayıt ekler.
    Dosya yoksa ve geri yükleme de yapılamadıysa veri sıfırlanmasını tespit eder.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    previous_lines = []
    if os.path.exists(BOOT_LOG_FILE):
        try:
            with open(BOOT_LOG_FILE, "r", encoding="utf-8") as f:
                previous_lines = [l.strip() for l in f if l.strip()]
        except Exception as e:
            print(f"Boot log okuma hatası: {e}")

    boot_count = len(previous_lines) + 1
    boot_id = f"boot_{boot_count}_{int(time.time())}"
    is_wiped_or_first = (len(previous_lines) == 0)

    try:
        with open(BOOT_LOG_FILE, "a", encoding="utf-8") as f:
            now_iso = datetime.now(timezone.utc).isoformat()
            f.write(f"{boot_id}\t{int(time.time())}\t{now_iso}\t{instance_id}\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception as e:
        print(f"Boot log yazma hatası: {e}")

    return {
        "boot_id": boot_id,
        "boot_count": boot_count,
        "is_wiped_or_first": is_wiped_or_first
    }

def get_storage_mount_info() -> dict:
    """os.stat st_dev karşılaştırması ile /app/data mount durumunu denetler."""
    try:
        data_stat = os.stat(DATA_DIR)
        parent_dir = os.path.dirname(DATA_DIR) or "/"
        parent_stat = os.stat(parent_dir)
        is_separate = (data_stat.st_dev != parent_stat.st_dev)
        return {
            "is_separate": is_separate,
            "data_dev": data_stat.st_dev,
            "parent_dev": parent_stat.st_dev,
            "path": DATA_DIR
        }
    except Exception as e:
        return {
            "is_separate": False,
            "error": str(e),
            "data_dev": 0,
            "parent_dev": 0,
            "path": DATA_DIR
        }

def _count_ledger_lines(filepath: str = None) -> int:
    target = filepath or os.path.join(DATA_DIR, "sent_ledger.txt")
    if not os.path.exists(target):
        return 0
    try:
        with open(target, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0

def _count_history_posts(filepath: str = None) -> int:
    target = filepath or os.path.join(DATA_DIR, "post_history.json")
    if not os.path.exists(target):
        return 0
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
            return len(data.get("posts", {}))
    except Exception:
        return 0

def create_backup_zip_bytes(instance_id: str, boot_id: str = "") -> tuple[bytes, dict]:
    """Tüm kalıcı dosyaları tek zip arşivine toplar ve manifest.json iliştirir."""
    zip_buffer = io.BytesIO()
    ledger_lines = _count_ledger_lines()
    post_count = _count_history_posts()

    manifest = {
        "timestamp": int(time.time()),
        "iso_time": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id,
        "boot_id": boot_id,
        "ledger_lines": ledger_lines,
        "post_count": post_count,
        "files_included": []
    }

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in BACKUP_FILES:
            fpath = os.path.join(DATA_DIR, fname)
            if os.path.exists(fpath):
                zf.write(fpath, arcname=fname)
                manifest["files_included"].append(fname)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return zip_buffer.getvalue(), manifest

def get_backup_meta() -> dict:
    if not os.path.exists(BACKUP_META_FILE):
        return {}
    try:
        with open(BACKUP_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_backup_meta(meta: dict):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BACKUP_META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Backup meta kaydetme hatası: {e}")

def create_and_upload_backup(api_url: str, instance_id: str, boot_id: str = "",
                             is_sigterm: bool = False, force: bool = False) -> tuple[bool, str]:
    """
    Yerel verileri zipleyip özel Telegram kanalına gönderir ve mesajı sabitler.
    Güvenlik: Yerel veri son yedekten belirgin küçükse (<%80) yeni yedek yüklemez!
    """
    global _has_unsaved_changes
    target_chat = get_backup_chat_id()
    if not target_chat:
        return False, "Yedek hedef chat ID tanımlanmamış (/yedek_ata komutu ile ayarlayın)."

    with _backup_lock:
        local_ledger_count = _count_ledger_lines()
        meta = get_backup_meta()
        last_manifest = meta.get("last_manifest") or {}
        last_backup_ledger = last_manifest.get("ledger_lines", 0)

        # Güvenlik Kontrolü: Boş durum veya bozulmuş yerel veri, iyi yedeği ezmesin!
        if not force and last_backup_ledger > 5 and local_ledger_count < (last_backup_ledger * 0.8):
            err_msg = (
                f"🚨 <b>GÜVENLİK ENGELİ: Veri Kaybı Şüphesi!</b>\n\n"
                f"Yerel kütük ({local_ledger_count} satır), son yedeğin ({last_backup_ledger} satır) "
                f"%80'inden daha küçük. Telegram'daki sağlam yedeğin ezilmemesi için yedekleme durduruldu."
            )
            notify_admin(api_url, err_msg)
            return False, "Güvenlik engeli: Yerel kütük yedeğin %80'inden küçük."

        try:
            zip_bytes, manifest = create_backup_zip_bytes(instance_id, boot_id)
            tag = " [KAPANIŞ YEDEĞİ]" if is_sigterm else ""
            caption = (
                f"📦 <b>Bot Veri Yedeği{tag}</b>\n\n"
                f"• <b>Tarih:</b> {manifest['iso_time'][:19].replace('T', ' ')} UTC\n"
                f"• <b>Instance:</b> <code>{instance_id}</code>\n"
                f"• <b>Ledger Kütüğü:</b> {manifest['ledger_lines']} kayıt\n"
                f"• <b>Post Geçmişi:</b> {manifest['post_count']} adet\n"
                f"• <b>Dosyalar:</b> {', '.join(manifest['files_included'])}"
            )

            file_name = f"bot_backup_{manifest['timestamp']}.zip"
            resp = requests.post(
                f"{api_url}/sendDocument",
                data={
                    "chat_id": target_chat,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "disable_notification": True
                },
                files={"document": (file_name, zip_bytes, "application/zip")},
                timeout=45
            ).json()

            if not resp.get("ok"):
                return False, f"Telegram sendDocument hatası: {resp.get('description')}"

            new_msg_id = resp["result"]["message_id"]

            # Yeni yedeği kanalda sabitle (pin)
            try:
                requests.post(
                    f"{api_url}/pinChatMessage",
                    json={
                        "chat_id": target_chat,
                        "message_id": new_msg_id,
                        "disable_notification": True
                    },
                    timeout=10
                )
            except Exception as pin_err:
                print(f"Yedek sabitleme (pin) hatası: {pin_err}")

            # Son 5 sabitlemeyi tut, eskisini unpin et
            pinned_ids = meta.get("pinned_message_ids", [])
            pinned_ids.append(new_msg_id)
            if len(pinned_ids) > 5:
                to_unpin = pinned_ids[:-5]
                pinned_ids = pinned_ids[-5:]
                for old_id in to_unpin:
                    try:
                        requests.post(
                            f"{api_url}/unpinChatMessage",
                            json={"chat_id": target_chat, "message_id": old_id},
                            timeout=10
                        )
                    except Exception:
                        pass

            meta["last_backup_time"] = int(time.time())
            meta["last_msg_id"] = new_msg_id
            meta["last_manifest"] = manifest
            meta["pinned_message_ids"] = pinned_ids
            save_backup_meta(meta)

            _has_unsaved_changes = False
            return True, f"Yedek başarıyla yüklendi ve sabitlendi (Mesaj ID: {new_msg_id})."

        except Exception as e:
            print(f"Yedek oluşturma/yükleme hatası: {e}")
            return False, str(e)

def notify_data_changed(api_url: str, instance_id: str, boot_id: str = "", delay: int = 60):
    """
    Veri değiştiğinde 60 saniyelik debounce süreciyle yedeklemeyi sıraya alır.
    """
    global _debounce_timer, _has_unsaved_changes
    _has_unsaved_changes = True

    def _worker():
        create_and_upload_backup(api_url, instance_id, boot_id=boot_id)

    with _backup_lock:
        if _debounce_timer and _debounce_timer.is_alive():
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(delay, _worker)
        _debounce_timer.daemon = True
        _debounce_timer.start()

def run_periodic_backup_loop(api_url: str, instance_id: str, boot_id: str = ""):
    """30 dakikada bir veri değişikliği varsa yedek alır."""
    global _has_unsaved_changes
    while True:
        time.sleep(30 * 60)
        try:
            if _has_unsaved_changes and get_backup_chat_id():
                create_and_upload_backup(api_url, instance_id, boot_id=boot_id)
        except Exception as e:
            print(f"Periyodik yedekleme döngü hatası: {e}")

def restore_from_telegram_if_needed(api_url: str, instance_id: str,
                                    boot_id: str = "") -> dict:
    """
    Açılışta, zamanlayıcılar başlamadan ÖNCE:
    Yedek hedef kanalının sabitlenmiş (pinned) mesajından son yedeği indirir.
    - Yerel veri boş/eksikse: Arşivi doğrudan açar.
    - Yerel veri varsa: Kütük satırlarını küme birleşimi ile birleştirir,
      post_history'de id çakışırsa yerel kalır, next_id büyüğü olur.
    """
    target_chat = get_backup_chat_id()
    if not target_chat:
        return {"status": "no_target", "restored": False, "msg": "Yedek kanalı atanmamış."}

    try:
        # 1. getChat ile sabitlenmiş son mesajı çek
        chat_resp = requests.get(f"{api_url}/getChat?chat_id={target_chat}", timeout=15).json()
        if not chat_resp.get("ok"):
            return {
                "status": "chat_error",
                "restored": False,
                "msg": f"Kanal bilgisi alınamadı: {chat_resp.get('description')}"
            }

        chat_data = chat_resp.get("result", {})
        pinned_msg = chat_data.get("pinned_message")
        if not pinned_msg:
            return {
                "status": "no_pinned",
                "restored": False,
                "msg": "Yedek kanalında sabitlenmiş mesaj bulunamadı."
            }

        doc = pinned_msg.get("document")
        if not doc:
            return {
                "status": "not_document",
                "restored": False,
                "msg": "Sabitlenmiş mesaj bir dosya (document) değil."
            }

        file_id = doc.get("file_id")
        file_resp = requests.get(f"{api_url}/getFile?file_id={file_id}", timeout=15).json()
        if not file_resp.get("ok"):
            return {
                "status": "file_info_error",
                "restored": False,
                "msg": f"getFile başarısız: {file_resp.get('description')}"
            }

        file_path = file_resp["result"]["file_path"]
        token = api_url.split("bot")[-1]
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"

        dl_resp = requests.get(download_url, timeout=60)
        if dl_resp.status_code != 200:
            return {
                "status": "download_failed",
                "restored": False,
                "msg": f"Yedek dosyası indirilemedi (HTTP {dl_resp.status_code})"
            }

        zip_bytes = io.BytesIO(dl_resp.content)
        with zipfile.ZipFile(zip_bytes, "r") as zf:
            file_names = zf.namelist()
            manifest = {}
            if "manifest.json" in file_names:
                try:
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                except Exception:
                    pass

            local_ledger_count = _count_ledger_lines()
            local_post_count = _count_history_posts()
            is_local_empty = (local_ledger_count == 0 and local_post_count == 0)

            os.makedirs(DATA_DIR, exist_ok=True)

            if is_local_empty:
                # Yerel veri boş: Arşivdeki tüm dosyaları doğrudan aç
                for fname in BACKUP_FILES:
                    if fname in file_names:
                        with open(os.path.join(DATA_DIR, fname), "wb") as out_f:
                            out_f.write(zf.read(fname))

                restored_ledger = _count_ledger_lines()
                restored_posts = _count_history_posts()

                # Meta kaydını güncelle
                meta = get_backup_meta()
                meta["last_manifest"] = manifest
                meta["last_backup_time"] = manifest.get("timestamp", int(time.time()))
                meta["last_msg_id"] = pinned_msg.get("message_id")
                save_backup_meta(meta)

                return {
                    "status": "full_restore",
                    "restored": True,
                    "ledger_count": restored_ledger,
                    "post_count": restored_posts,
                    "msg": f"Sıfırdan tam geri yükleme yapıldı ({restored_ledger} kütük satırı, {restored_posts} post)."
                }
            else:
                # Yerel veri mevcut: Akıllı küme birleşimi (Merge)
                # 1. sent_ledger.txt küme birleşimi
                local_lines = set()
                local_ledger_file = os.path.join(DATA_DIR, "sent_ledger.txt")
                if os.path.exists(local_ledger_file):
                    with open(local_ledger_file, "r", encoding="utf-8") as f:
                        local_lines = {l.strip() for l in f if l.strip()}

                backup_lines = set()
                if "sent_ledger.txt" in file_names:
                    try:
                        b_text = zf.read("sent_ledger.txt").decode("utf-8")
                        backup_lines = {l.strip() for l in b_text.splitlines() if l.strip()}
                    except Exception:
                        pass

                merged_ledger = local_lines | backup_lines
                with open(local_ledger_file, "w", encoding="utf-8") as f:
                    for item in sorted(merged_ledger):
                        f.write(f"{item}\n")

                # 2. post_history.json birleşimi
                local_hist_file = os.path.join(DATA_DIR, "post_history.json")
                local_hist = {"next_id": 1, "posts": {}}
                if os.path.exists(local_hist_file):
                    try:
                        with open(local_hist_file, "r", encoding="utf-8") as f:
                            local_hist = json.load(f)
                    except Exception:
                        pass

                backup_hist = {"next_id": 1, "posts": {}}
                if "post_history.json" in file_names:
                    try:
                        backup_hist = json.loads(zf.read("post_history.json").decode("utf-8"))
                    except Exception:
                        pass

                merged_posts = dict(backup_hist.get("posts", {}))
                # Çakışmada yerel postlar esası oluşturur
                merged_posts.update(local_hist.get("posts", {}))

                numeric_keys = [int(k) for k in merged_posts.keys() if str(k).isdigit()]
                max_key = max(numeric_keys) if numeric_keys else 0
                merged_next = max(
                    int(local_hist.get("next_id", 1)),
                    int(backup_hist.get("next_id", 1)),
                    max_key + 1
                )

                with open(local_hist_file, "w", encoding="utf-8") as f:
                    json.dump({"next_id": merged_next, "posts": merged_posts}, f, ensure_ascii=False, indent=2)

                # 3. radar_data.json birleşimi
                for radar_name, store_key in [("radar_data.json", "sent_tweets"), ("reels_radar_data.json", "sent_reels")]:
                    r_local_file = os.path.join(DATA_DIR, radar_name)
                    r_local = {}
                    if os.path.exists(r_local_file):
                        try:
                            with open(r_local_file, "r", encoding="utf-8") as f:
                                r_local = json.load(f)
                        except Exception:
                            pass
                    if radar_name in file_names:
                        try:
                            r_backup = json.loads(zf.read(radar_name).decode("utf-8"))
                            b_items = r_backup.get(store_key, {})
                            l_items = r_local.setdefault(store_key, {})
                            for k, v in b_items.items():
                                if k not in l_items:
                                    l_items[k] = v
                            with open(r_local_file, "w", encoding="utf-8") as f:
                                json.dump(r_local, f, ensure_ascii=False, indent=2)
                        except Exception:
                            pass

                # 4. topics.json ve cookies.json (yerelde yoksa yedekten al)
                for extra in ["topics.json", "cookies.json"]:
                    extra_local = os.path.join(DATA_DIR, extra)
                    if not os.path.exists(extra_local) and extra in file_names:
                        with open(extra_local, "wb") as out_f:
                            out_f.write(zf.read(extra))

                meta = get_backup_meta()
                meta["last_manifest"] = manifest
                meta["last_backup_time"] = manifest.get("timestamp", int(time.time()))
                meta["last_msg_id"] = pinned_msg.get("message_id")
                save_backup_meta(meta)

                return {
                    "status": "merged",
                    "restored": True,
                    "ledger_count": len(merged_ledger),
                    "post_count": len(merged_posts),
                    "msg": f"Mevcut veriler Telegram yedeğiyle birleştirildi (Kütük: {len(merged_ledger)}, Post: {len(merged_posts)})."
                }

    except Exception as e:
        print(f"Geri yükleme hatası: {e}")
        return {"status": "error", "restored": False, "msg": str(e)}
