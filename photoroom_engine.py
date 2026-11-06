#!/usr/bin/env python3
"""
PhotoRoom AI Background Removal & E-Commerce Canvas Engine
Uses PhotoRoom's segmentation inference API with autonomous Firebase sessions.
Produces 1500x2000 studio white canvas and transparent cutout PNGs.
"""

import io
import time
import requests
from PIL import Image, ImageOps

FIREBASE_API_KEY = "AIzaSyBEEHOLo47ucxzV2T1NLRoCAflGxTWb_sw"
SIGN_UP_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
SEGMENT_URL = "https://segmentation-inference.photoroom.com/v1/segment"

# In-memory token cache to avoid requesting a new token every call
_token_cache = {
    "token": None,
    "expires_at": 0
}

def get_auth_token():
    """
    Returns a valid Firebase JWT token.
    Uses cached token or requests a fresh anonymous token from Google Identity.
    """
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    try:
        resp = requests.post(
            SIGN_UP_URL,
            json={"returnSecureToken": True},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("idToken")
            expires_in = int(data.get("expiresIn", 3600))
            _token_cache["token"] = token
            _token_cache["expires_at"] = now + expires_in - 300  # Refresh 5 min early
            return token
    except Exception as e:
        print(f"⚠️ PhotoRoom Auth hatası: {e}")

    # Fallback to existing token if available
    return _token_cache.get("token")

def remove_background(image_bytes):
    """
    Calls PhotoRoom's segmentation AI API to remove background.
    Returns transparent PNG bytes.
    """
    token = get_auth_token()
    if not token:
        raise RuntimeError("PhotoRoom kimlik doğrulama token'ı alınamadı.")

    headers = {
        "pr-platform": "web",
        "pr-app-version": "2026.45.05 (edd9efb)",
        "Authorization": token
    }

    files = {
        "image_file": ("input.png", image_bytes, "image/png")
    }
    data = {
        "channels": "rgba",
        "format": "png",
        "size": "full",
        "crop": "false"
    }

    resp = requests.post(
        SEGMENT_URL,
        headers=headers,
        files=files,
        data=data,
        timeout=30
    )

    if resp.status_code == 200 and resp.content:
        return resp.content

    # If token expired unexpectedly, clear cache and retry once
    if resp.status_code in (401, 403):
        _token_cache["token"] = None
        _token_cache["expires_at"] = 0
        new_token = get_auth_token()
        headers["Authorization"] = new_token
        retry_resp = requests.post(
            SEGMENT_URL,
            headers=headers,
            files={"image_file": ("input.png", image_bytes, "image/png")},
            data=data,
            timeout=30
        )
        if retry_resp.status_code == 200 and retry_resp.content:
            return retry_resp.content
        raise RuntimeError(f"PhotoRoom API hatası (Retry): {retry_resp.status_code} - {retry_resp.text[:200]}")

    raise RuntimeError(f"PhotoRoom API hatası: {resp.status_code} - {resp.text[:200]}")

def process_ecommerce_photo(
    image_bytes,
    canvas_w=1500,
    canvas_h=2000,
    margin=0.96,
    bg_color=(255, 255, 255)
):
    """
    1. PhotoRoom AI ile arka planı temizler.
    2. Alfa kanalındaki mikroskobik pikselleri filtreleyerek nesnenin gerçek sınırlarını kırpar.
    3. Nesneyi tuvali en yüksek oranda dolduracak şekilde (%96+ doluluk) orantılı büyütüp ortalar.
    4. (white_jpg_io, cutout_png_io, orig_size, final_size) döner.
    """
    # 1. PhotoRoom'dan şeffaf dekupe PNG'yi al
    cutout_bytes = remove_background(image_bytes)

    # 2. PIL ile işle
    with Image.open(io.BytesIO(cutout_bytes)) as raw_cutout:
        cutout = ImageOps.exif_transpose(raw_cutout).convert("RGBA")
        orig_w, orig_h = cutout.size

        # Nesnenin gerçek sınırlarını bul (mikroskobik alfa gürültülerini filtrele: alpha > 15)
        alpha = cutout.split()[-1]
        real_bbox = alpha.point(lambda p: 255 if p > 15 else 0).getbbox()
        if real_bbox:
            cutout = cutout.crop(real_bbox)

        # 3. Tuvale tam oturacak şekilde büyüt (%96 - %100 doluluk)
        target_max_w = int(canvas_w * margin)
        target_max_h = int(canvas_h * margin)

        scale = min(target_max_w / cutout.width, target_max_h / cutout.height)
        new_w = max(1, int(round(cutout.width * scale)))
        new_h = max(1, int(round(cutout.height * scale)))

        resized_cutout = cutout.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 4. Saf Beyaz Tuval oluştur
        canvas = Image.new("RGBA", (canvas_w, canvas_h), (*bg_color, 255))

        # Tam merkeze yerleştir
        paste_x = (canvas_w - new_w) // 2
        paste_y = (canvas_h - new_h) // 2

        canvas.paste(resized_cutout, (paste_x, paste_y), resized_cutout)

        # 5. JPEG (Beyaz zemin) hazırla
        white_jpg_io = io.BytesIO()
        rgb_canvas = canvas.convert("RGB")
        rgb_canvas.save(white_jpg_io, format="JPEG", quality=95, optimize=True)
        white_jpg_io.seek(0)

        # 6. Şeffaf PNG kopyasını da hazırla (Kırpılmış temiz nesne)
        cutout_png_io = io.BytesIO()
        cutout.save(cutout_png_io, format="PNG", optimize=True)
        cutout_png_io.seek(0)

        return white_jpg_io, cutout_png_io, (orig_w, orig_h), (canvas_w, canvas_h)
