#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_handler.py: Telegram botu ile Yorum Videosu motorunu (pipeline) bağlayan modül.
- Link geldiğinde gönderiyi ve yorumları arka planda çeker.
- İnteraktif butonlar (Hemen Üret / Yorum Seç) sunar.
- Arka planda videoyu render edip Telegram'a yükler.
- /video_min, /video_status, /video_auto komutlarını yönetir.
"""

import os
import re
import time
import threading
from html import escape

try:
    from .video_config import (
        get_min_likes, set_min_likes,
        get_auto_generate, set_auto_generate,
        load_config
    )
    from .fetcher import fetch_post_and_comments
    from .pipeline import create_funny_comments_video
    from .renderer import format_likes
except ImportError:
    from video_config import (
        get_min_likes, set_min_likes,
        get_auto_generate, set_auto_generate,
        load_config
    )
    from fetcher import fetch_post_and_comments
    from pipeline import create_funny_comments_video
    from renderer import format_likes

# Aktif seçim oturumları: {session_id: {...}}
CV_SESSIONS = {}
_session_lock = threading.Lock()

def parse_stat_number(val_str):
    """'120k', '1.5m', '120.000', '120,000' veya '5000' gibi metinleri int sayıya çevirir."""
    if not val_str:
        return None
    val = str(val_str).strip().lower()
    multiplier = 1
    if val.endswith("k"):
        multiplier = 1_000
        val = val[:-1]
    elif val.endswith("m"):
        multiplier = 1_000_000
        val = val[:-1]
    elif val.endswith("b"):
        multiplier = 1_000
        val = val[:-1]
    else:
        val = val.replace(".", "").replace(",", "")
    try:
        return int(float(val) * multiplier)
    except (ValueError, TypeError):
        return None

def build_session_keyboard(session_id: str, comments: list, selected_indices: list) -> dict:
    """Yorum seçim inline butonlarını oluşturur."""
    buttons = []
    
    # 1. Satır: Ana Çalıştır Butonu
    sel_count = len(selected_indices)
    run_btn_text = f"🎬 Videoyu Hemen Oluştur ({sel_count} Yorum)" if sel_count > 0 else "⚠️ En Az 1 Yorum Seçin"
    buttons.append([{"text": run_btn_text, "callback_data": f"cv_run:{session_id}"}])
    
    # 2. Satır: Yorum toggle butonları (Maksimum ilk 8 yorum)
    max_display = min(8, len(comments))
    toggle_row = []
    for i in range(max_display):
        is_sel = i in selected_indices
        label = f"✅ {i+1}" if is_sel else f"⬜ {i+1}"
        toggle_row.append({"text": label, "callback_data": f"cv_tog:{session_id}:{i}"})
        if len(toggle_row) == 4:
            buttons.append(toggle_row)
            toggle_row = []
    if toggle_row:
        buttons.append(toggle_row)
        
    # 3. Satır: Kontrol butonları
    buttons.append([
        {"text": "🔄 İlk 5'i Seç", "callback_data": f"cv_top5:{session_id}"},
        {"text": "❌ İptal", "callback_data": f"cv_cancel:{session_id}"}
    ])
    
    return {"inline_keyboard": buttons}

def build_session_message_text(comments: list, selected_indices: list, min_likes: int, url: str) -> str:
    """Kullanıcıya gösterilecek şık yorum listesi metnini oluşturur."""
    lines = [
        "🎬 <b>Popüler Yorumlar Tespit Edildi!</b>",
        f"• <b>Gönderi:</b> <code>{escape(url[:45])}...</code>",
        f"• <b>Filtre:</b> En az {min_likes:,} beğeni",
        f"• <b>Seçilen:</b> {len(selected_indices)} / {len(comments)} yorum\n"
    ]
    
    num_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
    for i, c in enumerate(comments[:8]):
        prefix = num_emojis[i] if i < len(num_emojis) else f"{i+1}."
        check = "✅" if i in selected_indices else "▫️"
        handle = escape(c.get("author_handle") or "kullanici")
        likes_str = format_likes(c.get("likes") or 0)
        # Yorum metnini ilk 75 karakterle sınırla
        t_short = escape(c.get("text", "")[:75].replace("\n", " "))
        if len(c.get("text", "")) > 75:
            t_short += "..."
            
        lines.append(f"{prefix} {check} <b>@{handle}</b> (❤️ {likes_str}):\n   <i>\"{t_short}\"</i>\n")
        
    lines.append("👇 <i>Numaralara basarak yorumları değiştirebilir veya doğrudan 'Videoyu Hemen Oluştur' butonuna basabilirsiniz:</i>")
    return "\n".join(lines)

def handle_comment_video_message(
    chat_id: int,
    msg_id: int,
    text: str,
    message_thread_id=None,
    send_msg_func=None,
    edit_msg_func=None,
    send_video_func=None,
    delete_msg_func=None
) -> bool:
    """Yorum videosu odasına gelen komut ve linkleri yönetir."""
    t = (text or "").strip()
    
    # 1. /video_min veya /yorum_min: Beğeni eşiğini ayarlar
    if t.startswith("/video_min") or t.startswith("/video_set") or t.startswith("/yorum_min") or t.startswith("/min_likes"):
        parts = t.split()
        if len(parts) > 1:
            val = parse_stat_number(parts[1])
            if val is not None and val >= 0:
                set_min_likes(val)
                msg = (
                    "✅ <b>Yorum Videosu Beğeni Eşiği Güncellendi!</b>\n\n"
                    f"• <b>Yeni Eşik:</b> En az <b>{val:,}</b> beğeni\n"
                    "• <b>Etki:</b> Bundan sonra bu kanala atılan linklerde bu eşik ve üzerindeki en popüler yorumlar önceliklendirilecektir.\n\n"
                    "💡 <i>Geri dönmek için:</i> <code>/video_min 10000</code>"
                )
                send_msg_func(chat_id, msg, reply_to_message_id=msg_id, message_thread_id=message_thread_id)
                return True
        send_msg_func(
            chat_id,
            "⚠️ <b>Kullanım:</b> <code>/video_min &lt;sayı&gt;</code>\n"
            "Örnekler:\n"
            "• <code>/video_min 5000</code> (En az 5.000 beğeni)\n"
            "• <code>/video_min 10k</code> (En az 10.000 beğeni)\n"
            "• <code>/video_min 25000</code> (En az 25.000 beğeni)",
            reply_to_message_id=msg_id,
            message_thread_id=message_thread_id
        )
        return True
        
    # 2. /video_status veya /video_ayar: Mevcut ayarları gösterir
    if t.startswith("/video_status") or t.startswith("/video_ayar") or t.startswith("/video_bilgi"):
        cfg = load_config()
        min_l = cfg.get("min_likes", 10000)
        auto_g = "🟢 Açık (Direkt Üret)" if cfg.get("auto_generate") else "⚪ Kapalı (Butonlu / Seçimli)"
        pause_d = cfg.get("pause_duration", 0.40)
        
        msg = (
            "⚙️ <b>Yorum Videosu Motoru Ayarları</b>\n\n"
            f"• <b>Min Beğeni Eşiği:</b> <code>{min_l:,}</code> beğeni (Değiştirmek için: <code>/video_min 5000</code>)\n"
            f"• <b>Otomatik Mod:</b> {auto_g} (Değiştirmek için: <code>/video_auto on/off</code>)\n"
            f"• <b>Yorum Duraklama Payı:</b> <code>{pause_d:.2f} sn</code> (Akıcı kesintisiz akış)\n"
            "• <b>Ses Motoru:</b> Microsoft Edge-TTS (Ahmet / Doğal Türkçe)\n"
            "• <b>Platform Desteği:</b> Instagram (Reels & Post) + Twitter/X (Video & Tweet)\n\n"
            "🎬 <i>Video üretmek için bu odaya bir Instagram veya Twitter/X linki atmanız yeterlidir!</i>"
        )
        send_msg_func(chat_id, msg, reply_to_message_id=msg_id, message_thread_id=message_thread_id)
        return True

    # 3. /video_auto: Otomatik mod aç/kapat
    if t.startswith("/video_auto"):
        parts = t.split()
        if len(parts) > 1 and parts[1].lower() in ("on", "ac", "aç", "1", "true"):
            set_auto_generate(True)
            send_msg_func(chat_id, "🟢 <b>Otomatik Üretim Modu Açıldı:</b> Artık link atıldığında buton sormadan en iyi 5 yorumla doğrudan video kurgulanacaktır.", reply_to_message_id=msg_id, message_thread_id=message_thread_id)
            return True
        elif len(parts) > 1 and parts[1].lower() in ("off", "kapat", "0", "false"):
            set_auto_generate(False)
            send_msg_func(chat_id, "⚪ <b>İnteraktif / Butonlu Mod Açıldı:</b> Artık link atıldığında yorum listesi ve seçim butonları sunulacaktır.", reply_to_message_id=msg_id, message_thread_id=message_thread_id)
            return True
        send_msg_func(chat_id, "⚠️ <b>Kullanım:</b> <code>/video_auto on</code> veya <code>/video_auto off</code>", reply_to_message_id=msg_id, message_thread_id=message_thread_id)
        return True

    # 4. Link Tespiti (Instagram veya Twitter/X)
    link_match = re.search(r"https?://(?:www\.)?(?:instagram\.com/(?:p|reel|reels)/[a-zA-Z0-9_\-]+|(?:twitter\.com|x\.com|fixupx\.com|vxtwitter\.com|fxtwitter\.com)/[a-zA-Z0-9_]+/status/\d+)", t)
    if not link_match:
        # Eğer doğrudan link yoksa ama /video <link> denmişse
        if t.startswith("/video"):
            send_msg_func(
                chat_id,
                "⚠️ <b>Kullanım:</b> Bu odaya doğrudan bir Instagram veya Twitter linki gönderebilir veya <code>/video https://...</code> yazabilirsiniz.",
                reply_to_message_id=msg_id,
                message_thread_id=message_thread_id
            )
            return True
        return False

    target_url = link_match.group(0)
    min_likes = get_min_likes()
    auto_mode = get_auto_generate()

    # İlk bekleme mesajını gönder
    status_resp = send_msg_func(
        chat_id,
        f"⏳ <b>Gönderi ve Popüler Yorumlar İnceleniyor...</b>\n"
        f"• <i>En az {min_likes:,} beğeni almış komik yorumlar taranıyor...</i>",
        reply_to_message_id=msg_id,
        message_thread_id=message_thread_id
    )
    status_msg_id = None
    if status_resp and hasattr(status_resp, "json"):
        try:
            status_msg_id = status_resp.json().get("result", {}).get("message_id")
        except Exception:
            pass

    # Arka plan iş parçacığında gönderiyi çek ve süreci başlat (Ana döngüyü ASLA bloklama!)
    def worker():
        try:
            fetch_res = fetch_post_and_comments(target_url, min_likes=min_likes)
            if "error" in fetch_res:
                err_text = f"❌ <b>Gönderi Alınamadı:</b>\n{fetch_res['error']}"
                if status_msg_id and edit_msg_func:
                    edit_msg_func(chat_id, status_msg_id, err_text)
                else:
                    send_msg_func(chat_id, err_text, reply_to_message_id=msg_id, message_thread_id=message_thread_id)
                return

            comments = fetch_res.get("comments") or []
            if not comments:
                no_c_text = "⚠️ <b>Uygun Yorum Bulunamadı:</b>\nBu gönderide seçilen kriterlere uygun yorum bulunamadı."
                if status_msg_id and edit_msg_func:
                    edit_msg_func(chat_id, status_msg_id, no_c_text)
                else:
                    send_msg_func(chat_id, no_c_text, reply_to_message_id=msg_id, message_thread_id=message_thread_id)
                return

            # Otomatik mod aktifse buton sormadan direkt derle
            if auto_mode:
                if status_msg_id and edit_msg_func:
                    edit_msg_func(
                        chat_id,
                        status_msg_id,
                        f"🎬 <b>Video Kurgulanıyor...</b>\n"
                        f"• {min(5, len(comments))} popüler yorum seçildi.\n"
                        f"• Yorum kartları ve doğal sesler hazırlanıyor...\n"
                        f"• Video duraklatma ve 0.40s geçişler uygulanıyor...\n"
                        f"<i>(Lütfen 15-20 saniye bekleyin)</i>"
                    )
                _run_build_and_upload(
                    chat_id=chat_id,
                    thread_id=message_thread_id,
                    url=target_url,
                    fetch_res=fetch_res,
                    selected_indices=list(range(min(5, len(comments)))),
                    status_msg_id=status_msg_id,
                    send_video_func=send_video_func,
                    delete_msg_func=delete_msg_func,
                    edit_msg_func=edit_msg_func
                )
                return

            # İnteraktif / Hibrit Mod: Kullanıcıya yorumları ve butonları sun
            session_id = f"cv_{int(time.time())}_{chat_id}_{msg_id}"
            default_selected = list(range(min(5, len(comments))))
            with _session_lock:
                CV_SESSIONS[session_id] = {
                    "url": target_url,
                    "fetch_res": fetch_res,
                    "comments": comments,
                    "selected": default_selected,
                    "min_likes": min_likes,
                    "chat_id": chat_id,
                    "thread_id": message_thread_id,
                    "status_msg_id": status_msg_id
                }

            msg_text = build_session_message_text(comments, default_selected, min_likes, target_url)
            keyboard = build_session_keyboard(session_id, comments, default_selected)

            if status_msg_id and edit_msg_func:
                edit_msg_func(chat_id, status_msg_id, msg_text, reply_markup=keyboard)
            else:
                send_msg_func(
                    chat_id,
                    msg_text,
                    reply_to_message_id=msg_id,
                    message_thread_id=message_thread_id,
                    reply_markup=keyboard
                )

        except Exception as e:
            print(f"[CommentVideo] İşleme hatası: {e}")
            if status_msg_id and edit_msg_func:
                edit_msg_func(chat_id, status_msg_id, f"❌ <b>Hata oluştu:</b> {e}")

    threading.Thread(target=worker, daemon=True).start()
    return True

def handle_comment_video_callback(
    callback_query: dict,
    edit_msg_func=None,
    send_video_func=None,
    answer_cb_func=None,
    delete_msg_func=None
) -> bool:
    """Inline buton tıklamalarını (seçim değiştirme, video derleme) yönetir."""
    data = (callback_query.get("data") or "").strip()
    if not data.startswith("cv_"):
        return False

    cb_id = callback_query.get("id")
    msg = callback_query.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")

    parts = data.split(":")
    action = parts[0]
    session_id = parts[1] if len(parts) > 1 else ""

    with _session_lock:
        session = CV_SESSIONS.get(session_id)

    if not session and action != "cv_cancel":
        if answer_cb_func:
            answer_cb_func(cb_id, text="⚠️ Bu oturumun süresi dolmuş veya geçersiz.", show_alert=True)
        return True

    # 1. Yorum Aç/Kapat (Toggle)
    if action == "cv_tog" and len(parts) >= 3:
        idx = int(parts[2])
        with _session_lock:
            sel = session["selected"]
            if idx in sel:
                sel.remove(idx)
            else:
                sel.append(idx)
                sel.sort()

        if answer_cb_func:
            status_txt = "Eklendi" if idx in session["selected"] else "Çıkarıldı"
            answer_cb_func(cb_id, text=f"Yorum #{idx+1} {status_txt}")

        new_text = build_session_message_text(session["comments"], session["selected"], session["min_likes"], session["url"])
        new_kb = build_session_keyboard(session_id, session["comments"], session["selected"])
        if edit_msg_func:
            edit_msg_func(chat_id, message_id, new_text, reply_markup=new_kb)
        return True

    # 2. İlk 5'i Seç
    if action == "cv_top5":
        with _session_lock:
            session["selected"] = list(range(min(5, len(session["comments"]))))
        if answer_cb_func:
            answer_cb_func(cb_id, text="İlk 5 popüler yorum seçildi.")
        new_text = build_session_message_text(session["comments"], session["selected"], session["min_likes"], session["url"])
        new_kb = build_session_keyboard(session_id, session["comments"], session["selected"])
        if edit_msg_func:
            edit_msg_func(chat_id, message_id, new_text, reply_markup=new_kb)
        return True

    # 3. İptal
    if action == "cv_cancel":
        with _session_lock:
            CV_SESSIONS.pop(session_id, None)
        if answer_cb_func:
            answer_cb_func(cb_id, text="İşlem iptal edildi.")
        if delete_msg_func:
            delete_msg_func(chat_id, message_id)
        return True

    # 4. Videoyu Derle (Run)
    if action == "cv_run":
        if not session["selected"]:
            if answer_cb_func:
                answer_cb_func(cb_id, text="⚠️ Lütfen videoya eklenecek en az 1 yorum seçin!", show_alert=True)
            return True

        if answer_cb_func:
            answer_cb_func(cb_id, text="🎬 Video kurgulanıyor, lütfen bekleyin...")

        sel_count = len(session["selected"])
        loading_text = (
            f"🎬 <b>Yorum Videosu Kurgulanıyor...</b>\n\n"
            f"• <b>Seçilen Yorum:</b> {sel_count} adet\n"
            "• 🎨 1080p OLED dark kartlar hazırlanıyor...\n"
            "• 🎙️ Edge-TTS doğal Türkçe seslendirmesi üretiliyor...\n"
            "• ⏱️ Video duraklatma ve 0.40s geçişler ekleniyor...\n\n"
            "<i>⏳ 15-25 saniye içinde videonuz burada paylaşılacaktır...</i>"
        )
        if edit_msg_func:
            edit_msg_func(chat_id, message_id, loading_text, reply_markup=None)

        # Arka planda derle
        def worker_build():
            with _session_lock:
                sess_data = CV_SESSIONS.pop(session_id, session)
            _run_build_and_upload(
                chat_id=chat_id,
                thread_id=sess_data.get("thread_id"),
                url=sess_data["url"],
                fetch_res=sess_data["fetch_res"],
                selected_indices=sess_data["selected"],
                status_msg_id=message_id,
                send_video_func=send_video_func,
                delete_msg_func=delete_msg_func,
                edit_msg_func=edit_msg_func
            )

        threading.Thread(target=worker_build, daemon=True).start()
        return True

    return False

def _run_build_and_upload(
    chat_id: int,
    thread_id,
    url: str,
    fetch_res: dict,
    selected_indices: list,
    status_msg_id: int,
    send_video_func,
    delete_msg_func,
    edit_msg_func
):
    """Videonun FFmpeg ile kurgulanıp Telegram'a yüklenmesini yöneten arka plan fonksiyonu."""
    try:
        res = create_funny_comments_video(
            url=url,
            selected_indices=selected_indices,
            pre_fetched_data=fetch_res
        )

        if not res.get("success"):
            err_msg = res.get("error", "Bilinmeyen kurgu hatası.")
            if edit_msg_func and status_msg_id:
                edit_msg_func(chat_id, status_msg_id, f"❌ <b>Video Kurgu Hatası:</b>\n{err_msg}")
            return

        video_path = res["video_path"]
        fsize_mb = os.path.getsize(video_path) / (1024 * 1024)
        c_count = res.get("comments_used", len(selected_indices))

        caption = (
            f"🎉 <b>Komik Yorum Videosu Hazır!</b>\n\n"
            f"• <b>Yorum Sayısı:</b> {c_count} adet\n"
            f"• <b>Boyut:</b> {fsize_mb:.1f} MB\n"
            f"• <b>Orijinal:</b> {escape(url)}"
        )

        # Telegram'a yükle
        upload_resp = send_video_func(
            chat_id=chat_id,
            video_path=video_path,
            caption=caption,
            message_thread_id=thread_id
        )

        # Yükleme başarılıysa geçici bekleme mesajını sil
        if upload_resp and hasattr(upload_resp, "status_code") and upload_resp.status_code == 200:
            if delete_msg_func and status_msg_id:
                delete_msg_func(chat_id, status_msg_id)
        else:
            if edit_msg_func and status_msg_id:
                edit_msg_func(chat_id, status_msg_id, f"✅ Video hazırlandı ancak Telegram'a yüklenirken hata oluştu.")

        # Üretilen geçici video dosyasını temizle
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
        except Exception:
            pass

    except Exception as e:
        print(f"[CommentVideo] Build hatası: {e}")
        if edit_msg_func and status_msg_id:
            edit_msg_func(chat_id, status_msg_id, f"❌ <b>Beklenmeyen Hata:</b> {e}")
