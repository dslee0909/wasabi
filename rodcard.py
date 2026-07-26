"""
낚싯대 상점 이미지 생성 (rodcard.py)

배너형 레이아웃: 각 낚싯대를 가로 카드(아트 + 이름 + 효과 + 가격)로 세로 나열.
레어도별 색 스트라이프, 보유 시 금테. 아트만 있으면 나머지는 봇이 그림.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFilter

import fonts

# 상점 배너 레이아웃 (render_shop 전용 — 2열 그리드).
#
# 디스코드는 첨부 이미지를 대략 550x350 상자에 맞춰 축소해서 보여준다. 세로로 길수록
# 축소가 심해져 글씨가 작아진다(옛 560x608 단열은 58%로 줄어 14px 스펙이 8px가 됐다).
# 그래서 8개 낚싯대를 2열×4행으로 눕혀 가로세로비(≈1.5:1)를 상자에 맞춰 축소를 최소화한다.
PAD = 16
HEADER = 48
COL_GAP = 14
ROW_GAP = 10
CELL_H = 92
ART = 64
W = 720
COL_W = (W - 2 * PAD - COL_GAP) // 2

F_TITLE, F_NAME, F_EFF, F_PRICE = 26, 24, 19, 21

GOLD = (255, 205, 60, 255)
WHITE = (238, 238, 238, 255)
GREY = (178, 183, 190, 255)
GREEN = (110, 210, 130, 255)
BG = (22, 24, 28, 255)

# 레어도별 강조색 (나무·강철·황금·다이아·용왕·전설·영혼·와사비)
ACCENTS = [
    (170, 110, 60), (150, 160, 172), (222, 180, 70),
    (90, 200, 222), (210, 80, 95), (190, 130, 240),
    (90, 210, 200), (150, 215, 90),
]


_font = fonts.text_font
_efont = fonts.emoji_font


def _glow_color(enhance: int):
    """강화 구간별 후광 색: 1~3 초록 · 4~6 파랑 · 7~9 보라 · 10~12 핑크 · 13~15 빨강."""
    for cap, color in ((3, (70, 225, 90)), (6, (70, 150, 255)), (9, (175, 90, 245)),
                       (12, (255, 110, 200)), (15, (255, 75, 75))):
        if enhance <= cap:
            return color
    return (255, 75, 75)


def _draw_glow(canvas, im, x, y, enhance):
    """강화 레벨만큼 색 후광. 구간 안에서 강화가 오를수록 점점 진하게."""
    if enhance <= 0:
        return
    color = _glow_color(enhance)
    pos = ((enhance - 1) % 3) + 1  # 구간 내 위치 1~3 (진하기)
    glow = Image.new("RGBA", im.size, color + (0,))
    glow.putalpha(im.split()[3])
    glow = glow.filter(ImageFilter.GaussianBlur(7 + pos * 3))
    for _ in range(pos + 1):
        canvas.alpha_composite(glow, (x, y))


def _cover(im, W, H):
    """비율 유지하며 (W,H)를 꽉 채우고 중앙 크롭 (배경 찌그러짐 방지)."""
    im = im.convert("RGBA")
    if im.width / im.height > W / H:
        nh = H
        nw = round(im.width * H / im.height)
    else:
        nw = W
        nh = round(im.height * W / im.width)
    im = im.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - W) // 2, (nh - H) // 2
    return im.crop((x, y, x + W, y + H))


def render_shop(entries: list[dict], title: str, rod_dir: str) -> io.BytesIO:
    """entries: [{name, img, price_str, effect, owned}] 를 2열 그리드 카드로 그림."""
    n = len(entries)
    rows = (n + 1) // 2
    H = HEADER + rows * (CELL_H + ROW_GAP) - ROW_GAP + PAD
    canvas = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, PAD - 2), title, font=_font(F_TITLE), fill=GOLD)

    name_font = _font(F_NAME)
    eff_font = _font(F_EFF)
    price_font = _font(F_PRICE)

    for i, e in enumerate(entries):
        col, row = i % 2, i // 2
        x0 = PAD + col * (COL_W + COL_GAP)
        y = HEADER + row * (CELL_H + ROW_GAP)
        x1 = x0 + COL_W
        accent = ACCENTS[i % len(ACCENTS)]
        row_bg = (int(accent[0] * 0.18) + 24, int(accent[1] * 0.18) + 24, int(accent[2] * 0.18) + 24, 255)

        draw.rounded_rectangle([x0, y, x1, y + CELL_H], radius=12, fill=row_bg)
        # 왼쪽 레어도 색 스트라이프
        draw.rounded_rectangle([x0, y, x0 + 7, y + CELL_H], radius=4, fill=accent + (255,))
        # 보유 시 금테
        if e["owned"]:
            draw.rounded_rectangle([x0, y, x1, y + CELL_H], radius=12, outline=GOLD, width=3)

        # 아트 썸네일 (왼쪽, 세로 중앙)
        ax, ay = x0 + 14, y + (CELL_H - ART) // 2
        img_path = os.path.join(rod_dir, e["img"])
        if os.path.exists(img_path):
            im = Image.open(img_path).convert("RGBA").resize((ART, ART), Image.LANCZOS)
            canvas.alpha_composite(im, (ax, ay))

        # 오른쪽 텍스트 3줄: 이름 / 효과 / 가격(or 보유중)
        tx = ax + ART + 12
        draw.text((tx, y + 11), e["name"], font=name_font, fill=WHITE)
        draw.text((tx, y + 11 + F_NAME + 6), e["effect"], font=eff_font, fill=GREY)
        if e["owned"]:
            label, lcol = "보유중", GREEN
        else:
            label, lcol = e["price_str"], GOLD
        draw.text((tx, y + 11 + F_NAME + 6 + F_EFF + 6), label, font=price_font, fill=lcol)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


def render_profile(rod_img_path: str, title: str, rod_name: str, enhance: int, sections: list, bg_path: str = None) -> io.BytesIO:
    """낚시 종합 스탯창: 낚싯대(글로우) + 여러 섹션. bg_path 주면 그 배경 위에 그림."""
    W = 640
    content_h = 60 + sum(34 + len(lines) * 28 + 10 for _, _, lines in sections)
    H = max(360, content_h + 16)
    has_bg = bool(bg_path and os.path.exists(bg_path))
    if has_bg:
        canvas = _cover(Image.open(bg_path), W, H)
    else:
        canvas = Image.new("RGBA", (W, H), (24, 26, 32, 255))

    tx = 236  # 오른쪽 텍스트 칸 시작 x
    if has_bg:
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rounded_rectangle([tx - 12, 52, W - 12, H - 14], radius=14, fill=(12, 14, 18, 160))
        canvas.alpha_composite(scrim)
    draw = ImageDraw.Draw(canvas)

    # 제목 배경 바 (가독성)
    title_font = _font(24)
    tw = draw.textlength(title, font=title_font)
    if has_bg:
        bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(bar).rounded_rectangle([16, 10, 46 + tw, 48], radius=11, fill=(12, 14, 18, 180))
        canvas.alpha_composite(bar)
        draw = ImageDraw.Draw(canvas)
    draw.text((30, 15), title, font=title_font, fill=GOLD)

    def _shadow(x, y, t, font, fill):
        if has_bg:
            draw.text((x + 2, y + 2), t, font=font, fill=(0, 0, 0, 190))
        draw.text((x, y), t, font=font, fill=fill)

    # 낚싯대 (위쪽 타원 안)
    RS = 150
    rx, ry = 50, 56
    if os.path.exists(rod_img_path):
        im = Image.open(rod_img_path).convert("RGBA").resize((RS, RS), Image.LANCZOS)
        _draw_glow(canvas, im, rx, ry, enhance)
        canvas.alpha_composite(im, (rx, ry))
    w = draw.textlength(rod_name, font=_font(20))
    _shadow(rx + RS / 2 - w / 2, ry + RS + 4, rod_name, _font(20), WHITE)

    # 섹션: 색 강조바 + 헤딩, 줄마다 이모지 아이콘 + 텍스트
    efont = _efont(19)
    hfont = _font(20)
    lfont = _font(17)
    y = 58
    for heading, accent, lines in sections:
        draw.rounded_rectangle([tx, y + 3, tx + 6, y + 25], radius=3, fill=tuple(accent) + (255,))
        draw.text((tx + 16, y), heading, font=hfont, fill=GOLD)
        y += 34
        for emoji, text in lines:
            draw.text((tx + 14, y - 3), emoji, font=efont, embedded_color=True)
            draw.text((tx + 46, y), text, font=lfont, fill=(230, 230, 236, 255))
            y += 28
        y += 10

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


def render_status(img_path: str, name: str, enhance: int, effects: list[str], bg_path: str = None) -> io.BytesIO:
    """장착 낚싯대 상태 카드: 강화 글로우 + 이름 + 효과. bg_path 주면 그 배경 위에 그림."""
    W, H = 600, 250
    tx = 336  # 오른쪽 텍스트 패널 시작 (배경의 오른쪽 패널에 맞춤)
    if bg_path and os.path.exists(bg_path):
        canvas = _cover(Image.open(bg_path), W, H)
        # 텍스트 가독성용 반투명 어두운 판 (오른쪽 패널만)
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(scrim).rounded_rectangle([tx - 12, 22, W - 14, H - 22], radius=14, fill=(0, 0, 0, 140))
        canvas.alpha_composite(scrim)
    else:
        canvas = Image.new("RGBA", (W, H), (24, 26, 32, 255))
    draw = ImageDraw.Draw(canvas)

    # 낚싯대는 중앙(모루 위)에 배치 → 왼쪽 캐릭터와 안 겹치게
    RS = 150
    rx, ry = 140, (H - RS) // 2
    if os.path.exists(img_path):
        im = Image.open(img_path).convert("RGBA").resize((RS, RS), Image.LANCZOS)
        _draw_glow(canvas, im, rx, ry, enhance)
        canvas.alpha_composite(im, (rx, ry))

    def _sh(x, y, t, font, fill):
        if bg_path and os.path.exists(bg_path):
            draw.text((x + 2, y + 2), t, font=font, fill=(0, 0, 0, 190))
        draw.text((x, y), t, font=font, fill=fill)

    _sh(tx, 40, name, _font(26), GOLD)
    draw.line([tx, 80, W - 22, 80], fill=(150, 150, 162, 255), width=2)  # 이름 밑 구분선
    efont = _efont(18)
    y = 92
    for emoji, text in effects:
        draw.text((tx, y - 3), emoji, font=efont, embedded_color=True)
        _sh(tx + 30, y, text, _font(17), (228, 228, 234, 255))
        y += 32

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out
