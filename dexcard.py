"""
낚시 도감 이미지 생성 (dexcard.py)

Pillow 로 물고기 썸네일 그리드를 그려 한 장의 이미지로 만든다.
- 잡은 물고기: 컬러 썸네일 + 이름/마릿수
- 못 잡은 물고기: 검은 실루엣 + '???'
- 반짝이 잡음: 금색 테두리 + ★수
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

THUMB = 128
PAD = 16
COLS = 4
CELL_W = THUMB + PAD * 2
TEXT_H = 48
CELL_H = THUMB + 8 + TEXT_H
HEADER = 56

BG = (30, 33, 40, 255)
SILHOUETTE = (70, 74, 82, 255)
GOLD = (255, 215, 0, 255)
WHITE = (240, 240, 240, 255)
GREY = (170, 174, 182, 255)


def _font(size):
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _centered(draw, cx, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def render_dex(entries: list[dict], title: str, assets_dir: str, shiny_dir: str = None) -> io.BytesIO:
    """entries: [{name, img, n(일반 수), s(반짝이 수)}]. 도감 PNG 를 BytesIO 로 반환.
    반짝이를 잡은 칸은 shiny_dir 의 반짝이 그림을 우선 사용."""
    rows = (len(entries) + COLS - 1) // COLS
    W = COLS * CELL_W
    H = HEADER + rows * CELL_H + PAD

    canvas = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, PAD), title, font=_font(24), fill=WHITE)

    name_font = _font(16)
    count_font = _font(15)

    for i, e in enumerate(entries):
        col, row = i % COLS, i // COLS
        x = col * CELL_W + PAD
        y = HEADER + row * CELL_H
        cx = x + THUMB / 2
        caught = e["n"] or e["s"]

        # 반짝이를 잡았고 반짝이 그림이 있으면 그걸 사용, 아니면 일반 그림
        use_shiny = e["s"] and shiny_dir and os.path.exists(os.path.join(shiny_dir, e["img"]))
        img_path = os.path.join(shiny_dir, e["img"]) if use_shiny else os.path.join(assets_dir, e["img"])
        if os.path.exists(img_path):
            im = Image.open(img_path).convert("RGBA").resize((THUMB, THUMB), Image.LANCZOS)
            if caught:
                canvas.alpha_composite(im, (x, y))
            else:
                # 실루엣: 알파를 마스크로 어두운 색 채움
                dark = Image.new("RGBA", (THUMB, THUMB), SILHOUETTE)
                blank = Image.new("RGBA", (THUMB, THUMB), (0, 0, 0, 0))
                canvas.alpha_composite(Image.composite(dark, blank, im.split()[3]), (x, y))

        # 반짝이 금테
        if e["s"]:
            draw.rectangle([x - 3, y - 3, x + THUMB + 3, y + THUMB + 3], outline=GOLD, width=3)

        # 이름 + 마릿수
        if caught:
            _centered(draw, cx, y + THUMB + 6, e["name"], name_font, WHITE)
            cnt = f"x{e['n']}" + (f"  ★{e['s']}" if e["s"] else "")
            _centered(draw, cx, y + THUMB + 26, cnt, count_font, GOLD if e["s"] else GREY)
        else:
            _centered(draw, cx, y + THUMB + 6, "???", name_font, GREY)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out
