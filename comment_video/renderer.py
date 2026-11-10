#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
renderer.py: Seçilen yorumun orijinal platform görünümünü koruyarak
sadece o yorumu içeren kristal netliğinde (1080p hazır) şeffaf PNG kartı üretir.
Pillow ile sıfır bağımlılıkla ve ultra hızlı çalışır.
"""

import os
import io
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

FONT_CANDIDATES = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
]

def _get_font(size: int, bold: bool = False):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            try:
                # TTC fonts may have index
                return ImageFont.truetype(f, size, index=1 if bold and "ttc" in f else 0)
            except Exception:
                try:
                    return ImageFont.truetype(f, size)
                except Exception:
                    pass
    return ImageFont.load_default()

def format_likes(count: int) -> str:
    """Beğeni sayısını şık sosyal medya formatına çevirir (Örn: 14.2K)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 10_000:
        return f"{count / 1_000:.1f}K"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return f"{count:,}"

def fetch_avatar(avatar_url: str, size: int = 80) -> Image.Image:
    """Avatar görselini indirir, daire şeklinde maskeler."""
    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                raw_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                raw_img = raw_img.resize((size, size), Image.Resampling.LANCZOS)
                
                # Yuvarlak maske
                mask = Image.new("L", (size, size), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, size, size), fill=255)
                
                output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                output.paste(raw_img, (0, 0), mask=mask)
                return output
        except Exception:
            pass

    # Fallback: Şık varsayılan daire
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=(70, 80, 95, 255))
    return img

def render_comment_card(
    author_name: str,
    author_handle: str,
    comment_text: str,
    like_count: int,
    avatar_url: str = "",
    platform: str = "instagram",
    output_path: str = None,
    card_width: int = 940
) -> str:
    """
    Sadece ilgili yorumu içeren, şeffaf arka planlı, gölgeli ve yuvarlatılmış
    OLED koyu modda kristal netliğinde bir PNG kartı üretir.
    """
    if not output_path:
        output_path = f"/tmp/comment_{int(like_count)}_{author_handle}.png"

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Fontlar
    font_name = _get_font(28, bold=True)
    font_handle = _get_font(22, bold=False)
    font_text = _get_font(30, bold=False)
    font_likes = _get_font(24, bold=True)

    # Metin kaydırma (Word wrap)
    max_char_per_line = 38
    wrapped_lines = textwrap.wrap(comment_text, width=max_char_per_line)
    if not wrapped_lines:
        wrapped_lines = ["..."]

    # Kart Yükseklik Hesabı
    padding_x = 36
    padding_y = 32
    avatar_size = 72
    line_height = 42
    header_height = avatar_size
    text_height = len(wrapped_lines) * line_height
    has_likes_badge = bool(like_count and like_count > 10)
    footer_height = 42 if has_likes_badge else 0
    spacing = 18

    card_height = padding_y + header_height + spacing + text_height + (spacing + footer_height if has_likes_badge else 0) + padding_y

    # Şeffaf ana tuval (Gölge için fazladan boşluk bırakılır)
    margin = 30
    canvas_w = card_width + (margin * 2)
    canvas_h = card_height + (margin * 2)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # 1. Şık Yumuşak Gölge (Drop Shadow)
    shadow_mask = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_mask)
    s_box = [margin + 2, margin + 8, margin + card_width - 2, margin + card_height + 8]
    s_draw.rounded_rectangle(s_box, radius=24, fill=(0, 0, 0, 160))
    shadow_blur = shadow_mask.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(shadow_blur, (0, 0), mask=shadow_blur)

    # 2. Ana Kart Gövdesi (Koyu OLED Instagram/Twitter stili)
    card_img = Image.new("RGBA", (card_width, card_height), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(card_img)

    bg_color = (18, 18, 20, 245) if platform == "instagram" else (21, 24, 28, 245)
    border_color = (60, 64, 70, 200)

    c_box = [0, 0, card_width - 1, card_height - 1]
    c_draw.rounded_rectangle(c_box, radius=24, fill=bg_color, outline=border_color, width=2)

    # 3. Avatar
    avatar = fetch_avatar(avatar_url, size=avatar_size)
    card_img.paste(avatar, (padding_x, padding_y), mask=avatar)

    # 4. Header (İsim + Kullanıcı Adı)
    info_x = padding_x + avatar_size + 18
    info_y = padding_y + 8
    clean_name = author_name if author_name else author_handle
    c_draw.text((info_x, info_y), clean_name, font=font_name, fill=(255, 255, 255, 255))

    handle_display = f"@{author_handle}" if not author_handle.startswith("@") else author_handle
    c_draw.text((info_x, info_y + 34), handle_display, font=font_handle, fill=(150, 160, 175, 255))

    # 5. Yorum Metni
    body_y = padding_y + header_height + spacing
    for i, line in enumerate(wrapped_lines):
        line_y = body_y + (i * line_height)
        c_draw.text((padding_x, line_y), line, font=font_text, fill=(245, 245, 247, 255))

    # 6. Footer (Beğeni Kısmı - Sadece gerçek/anlamlı beğeni > 10 ise çiz)
    if has_likes_badge:
        footer_y = body_y + text_height + spacing
        likes_str = f"❤️  {format_likes(like_count)}"

        # Kristal netliğinde, yüksek kontrastlı OLED hap kutucuğu
        pill_w = 175
        pill_h = 38
        c_draw.rounded_rectangle(
            [padding_x, footer_y, padding_x + pill_w, footer_y + pill_h],
            radius=19,
            fill=(32, 36, 44, 240),
            outline=(65, 72, 85, 220),
            width=1
        )
        c_draw.text((padding_x + 16, footer_y + 6), likes_str, font=font_likes, fill=(255, 255, 255, 255))

    # Kartı tuvalin ortasına yapıştır
    canvas.paste(card_img, (margin, margin), mask=card_img)

    # Kaydet
    canvas.save(output_path, "PNG")
    print(f"[Renderer] Yorum görseli oluşturuldu: {output_path}")
    return output_path

if __name__ == "__main__":
    out = render_comment_card(
        author_name="Ahmet Yılmaz",
        author_handle="ahmetyilmaz",
        comment_text="Kardeşim araba resmen ışık hızına geçti, arka koltuktaki arkadaşın ifadesi her şeyi anlatıyor zaten 😂😂😂",
        like_count=24800,
        platform="instagram",
        output_path="/tmp/test_card.png"
    )
    print("Test render bitti:", out)
