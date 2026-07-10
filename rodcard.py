"""
낚싯대 상점 이미지 생성 (rodcard.py)

배너형 레이아웃: 각 낚싯대를 가로 카드(아트 + 이름 + 효과 + 가격)로 세로 나열.
레어도별 색 스트라이프, 보유 시 금테. 아트만 있으면 나머지는 봇이 그림.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

TEXT_FONT = r"C:\Windows\Fonts\malgunbd.ttf"

PAD = 20
ROW_H = 112
ROW_GAP = 12
ART = 88
HEADER = 52
W = 660

GOLD = (255, 205, 60, 255)
WHITE = (238, 238, 238, 255)
GREY = (165, 170, 178, 255)
GREEN = (110, 210, 130, 255)
BG = (22, 24, 28, 255)

# 레어도별 강조색 (나무·강철·황금·다이아·용왕·전설)
ACCENTS = [
    (170, 110, 60), (150, 160, 172), (222, 180, 70),
    (90, 200, 222), (210, 80, 95), (190, 130, 240),
]


def _font(size):
    try:
        return ImageFont.truetype(TEXT_FONT, size)
    except OSError:
        return ImageFont.load_default()


def render_shop(entries: list[dict], title: str, rod_dir: str) -> io.BytesIO:
    """entries: [{name, img, price_str, effect, owned}] 순서대로 배너 카드로 그림."""
    n = len(entries)
    H = HEADER + n * (ROW_H + ROW_GAP) + PAD - ROW_GAP
    canvas = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, PAD - 4), title, font=_font(26), fill=GOLD)

    name_font = _font(25)
    eff_font = _font(16)
    price_font = _font(20)

    for i, e in enumerate(entries):
        accent = ACCENTS[i % len(ACCENTS)]
        y = HEADER + i * (ROW_H + ROW_GAP)
        x0, x1 = PAD, W - PAD
        row_bg = (int(accent[0] * 0.18) + 24, int(accent[1] * 0.18) + 24, int(accent[2] * 0.18) + 24, 255)

        draw.rounded_rectangle([x0, y, x1, y + ROW_H], radius=14, fill=row_bg)
        # 왼쪽 레어도 색 스트라이프
        draw.rounded_rectangle([x0, y, x0 + 8, y + ROW_H], radius=4, fill=accent + (255,))
        # 보유 시 금테
        if e["owned"]:
            draw.rounded_rectangle([x0, y, x1, y + ROW_H], radius=14, outline=GOLD, width=3)

        # 아트 썸네일
        ax, ay = x0 + 22, y + (ROW_H - ART) // 2
        img_path = os.path.join(rod_dir, e["img"])
        if os.path.exists(img_path):
            im = Image.open(img_path).convert("RGBA").resize((ART, ART), Image.LANCZOS)
            canvas.alpha_composite(im, (ax, ay))

        tx = ax + ART + 20
        draw.text((tx, y + 20), e["name"], font=name_font, fill=WHITE)
        draw.text((tx, y + 54), e["effect"], font=eff_font, fill=GREY)

        # 오른쪽: 가격 또는 보유중
        if e["owned"]:
            label, col = "✅ 보유중", GREEN
        else:
            label, col = e["price_str"], GOLD
        lw = draw.textlength(label, font=price_font)
        draw.text((x1 - 20 - lw, y + ROW_H / 2 - 12), label, font=price_font, fill=col)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out
