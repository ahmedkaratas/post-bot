#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_config.py: Yorum videosu üretim ayarlarını (min beğeni, max yorum, geçiş süresi)
yöneten ve data/video_config.json dosyasında kalıcı olarak saklayan modül.
"""

import os
import json
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CONFIG_FILE = os.path.join(DATA_DIR, "video_config.json")

DEFAULT_CONFIG = {
    "min_likes": 10000,
    "max_comments": 5,
    "pause_duration": 0.40,
    "auto_generate": False
}

_lock = threading.Lock()

def _ensure_dir():
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
        except Exception:
            pass

def load_config() -> dict:
    _ensure_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                res = dict(DEFAULT_CONFIG)
                res.update(data)
                return res
        except Exception as e:
            print(f"[VideoConfig] Okuma hatası: {e}")
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict) -> bool:
    _ensure_dir()
    with _lock:
        temp_file = CONFIG_FILE + ".tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, CONFIG_FILE)
            return True
        except Exception as e:
            print(f"[VideoConfig] Yazma hatası: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            return False

def get_min_likes() -> int:
    return load_config().get("min_likes", 10000)

def set_min_likes(min_likes: int) -> bool:
    cfg = load_config()
    cfg["min_likes"] = max(0, int(min_likes))
    return save_config(cfg)

def get_auto_generate() -> bool:
    return load_config().get("auto_generate", False)

def set_auto_generate(enabled: bool) -> bool:
    cfg = load_config()
    cfg["auto_generate"] = bool(enabled)
    return save_config(cfg)
