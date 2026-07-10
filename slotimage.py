"""
슬롯머신 이미지/애니메이션 생성 (slotimage.py)

- render_slot(grid, ...): 결과 정지 이미지 (PNG)
- spin_gif(): 릴이 굴러가는 애니메이션 (GIF, 캐시해서 재사용)

컬럼(세로)이 하나의 릴. 가운데 줄이 페이라인(당첨 판정).
컬러 심볼은 Segoe UI Emoji(embedded_color)로 그린다.
"""

import io
import os
import random

from PIL import Image, ImageDraw, ImageFont

EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"
TEXT_FONT = r"C:\Windows\Fonts\malgunbd.ttf"
SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "🍀", "💎"]

CELL = 100
GAP = 12
PAD = 24
TITLE_H = 56
BANNER_H = 70
COLS = 3
COL_H = 3 * CELL
REELS_W = COLS * CELL + (COLS - 1) * GAP
W = REELS_W + PAD * 2
H = TITLE_H + COL_H + BANNER_H + PAD * 2
RX = PAD
RY = TITLE_H + PAD

BG = (24, 18, 30, 255)
FRAME = (200, 60, 70, 255)
GOLD = (255, 205, 60, 255)
WINDOW = (250, 248, 242, 255)
PAYLINE = (255, 240, 175, 255)
WIN_C = (90, 210, 120, 255)
LOSE_C = (150, 150, 160, 255)


def _efont(size):
    try:
        return ImageFont.truetype(EMOJI_FONT, size)
    except OSError:
        return ImageFont.load_default()


def _tfont(size):
    try:
        return ImageFont.truetype(TEXT_FONT, size)
    except OSError:
        return ImageFont.load_default()


def random_grid():
    return [[random.choice(SYMBOLS) for _ in range(COLS)] for _ in range(3)]


def _col_x(c):
    return RX + c * (CELL + GAP)


def _draw_chrome(img, draw, banner="", sub="", win=False):
    """프레임/타이틀/릴창/페이라인/배너 (심볼 제외)."""
    draw.rounded_rectangle([6, 6, W - 6, H - 6], radius=18, outline=FRAME, width=6)
    draw.text((W / 2, PAD + 12), "★  S L O T  ★", font=_tfont(30), fill=GOLD, anchor="mm")
    # 릴 창 (컬럼별 흰 배경)
    for c in range(COLS):
        x = _col_x(c)
        draw.rounded_rectangle([x, RY, x + CELL, RY + COL_H], radius=12, fill=WINDOW)
    # 페이라인 (가운데 줄)
    ly = RY + CELL
    draw.rectangle([RX, ly, RX + REELS_W, ly + CELL], fill=PAYLINE)
    for c in range(COLS):  # 창 경계 다시 (페이라인이 넘치지 않게)
        x = _col_x(c)
        draw.rounded_rectangle([x, RY, x + CELL, RY + COL_H], radius=12, outline=(210, 205, 200, 255), width=3)
    draw.text((RX - 2, ly + CELL / 2), "▶", font=_tfont(30), fill=FRAME, anchor="mm")
    draw.text((RX + REELS_W + 2, ly + CELL / 2), "◀", font=_tfont(30), fill=FRAME, anchor="mm")
    # 배너
    if banner:
        by = RY + COL_H + 14
        draw.text((W / 2, by + 14), banner, font=_tfont(30), fill=(WIN_C if win else LOSE_C), anchor="mm")
        if sub:
            draw.text((W / 2, by + 46), sub, font=_tfont(24), fill=GOLD, anchor="mm")


def render_slot(grid, banner="", sub="", win=False) -> io.BytesIO:
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img)
    _draw_chrome(img, draw, banner, sub, win)
    efont = _efont(66)
    for r in range(3):
        for c in range(COLS):
            x = _col_x(c) + CELL / 2
            y = RY + r * CELL + CELL / 2 + 2
            draw.text((x, y), grid[r][c], font=efont, anchor="mm", embedded_color=True)
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


# ---- 굴러가는 스핀 GIF (한 번 만들어 캐시) ----
_spin_cache = None


def _build_spin_gif() -> bytes:
    efont = _efont(66)
    F = 12
    step = CELL // 3  # 프레임당 이동량
    # 컬럼별 심볼 시퀀스 (길게, 반복)
    col_syms = [[random.choice(SYMBOLS) for _ in range(8)] for _ in range(COLS)]
    speeds = [1, 1, 1]

    frames = []
    for f in range(F):
        img = Image.new("RGBA", (W, H), BG)
        draw = ImageDraw.Draw(img)
        _draw_chrome(img, draw, "돌리는 중...", "", win=False)
        for c in range(COLS):
            syms = col_syms[c]
            L = len(syms)
            voff = (f * step * speeds[c])
            base = voff // CELL
            frac = voff % CELL
            # 컬럼 레이어에 스크롤 심볼 그리기 (창 밖은 잘림)
            layer = Image.new("RGBA", (CELL, COL_H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            for r in range(-1, 4):
                sym = syms[(base + r) % L]
                cy = r * CELL + CELL / 2 - frac
                ld.text((CELL / 2, cy + 2), sym, font=efont, anchor="mm", embedded_color=True)
            img.alpha_composite(layer, (_col_x(c), RY))
        frames.append(img.convert("RGB"))

    out = io.BytesIO()
    frames[0].save(
        out, format="GIF", save_all=True, append_images=frames[1:],
        duration=70, loop=0, disposal=2, optimize=True,
    )
    out.seek(0)
    return out.getvalue()


def spin_gif() -> io.BytesIO:
    global _spin_cache
    if _spin_cache is None:
        _spin_cache = _build_spin_gif()
    return io.BytesIO(_spin_cache)


def spin_stop_gif(reels_final, slow=False):
    """릴이 왼쪽→가운데→오른쪽 순서로 멈추며 reels_final(가운데 줄)에 착지하는 GIF.
    slow=True면 더 천천히 조여오며 멈춤 (올인/절반용 박진감).
    (GIF바이트, 최종 3x3 grid) 반환."""
    efont = _efont(66)
    T = 18                      # 타깃 심볼 인덱스 (충분히 굴러가도록)
    if slow:
        stop, F, frame_dur, hold = [10, 17, 24], 26, 85, 1500
    else:
        stop, F, frame_dur, hold = [7, 11, 15], 17, 70, 900
    voff_rest = (T - 1) * CELL

    cols = []
    for tgt in reels_final:
        syms = [random.choice(SYMBOLS) for _ in range(T + 4)]
        syms[T] = tgt
        cols.append(syms)

    final_grid = [
        [cols[c][T - 1] for c in range(COLS)],
        list(reels_final),
        [cols[c][T + 1] for c in range(COLS)],
    ]

    frames = []
    for f in range(F):
        img = Image.new("RGBA", (W, H), BG)
        draw = ImageDraw.Draw(img)
        _draw_chrome(img, draw, "돌리는 중...", "", win=False)
        for c in range(COLS):
            syms = cols[c]
            L = len(syms)
            sfr = stop[c]
            if f >= sfr:
                voff = voff_rest
            else:
                t = f / sfr
                voff = (1 - (1 - t) ** 2) * voff_rest  # ease-out 감속
            base = int(voff // CELL)
            frac = voff - base * CELL
            layer = Image.new("RGBA", (CELL, COL_H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            for k in range(base - 1, base + 5):
                sym = syms[k % L]
                cy = (k - base) * CELL - frac + CELL / 2
                ld.text((CELL / 2, cy + 2), sym, font=efont, anchor="mm", embedded_color=True)
            img.alpha_composite(layer, (_col_x(c), RY))
        frames.append(img.convert("RGB"))

    durations = [frame_dur] * (F - 1) + [hold]  # 마지막 프레임은 길게 홀드
    out = io.BytesIO()
    frames[0].save(
        out, format="GIF", save_all=True, append_images=frames[1:],
        duration=durations, loop=0, disposal=2, optimize=True,
    )
    out.seek(0)
    return out, final_grid
