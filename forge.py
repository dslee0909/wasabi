"""
대장간 강화 애니메이션 (forge.py)

와사비 캐릭터가 모루를 두드리는 4프레임(assets/wasabi_forge_1~4.png)을
순서대로 재생하는 GIF 를 만든다. (3번 = 타격, 불꽃)
프레임에 모루·불꽃이 이미 그려져 있어 그대로 사용.
"""

import io
import os

from PIL import Image

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
BG_IMG = os.path.join(ASSETS_DIR, "wasabi_forge_background_543x724.png")  # 대장간 뒷배경 (선택)
FRAME_H = 380              # 출력 높이 (비율 유지)
BG = (250, 248, 242)       # 배경 이미지 없을 때 대체 색
DURATIONS = [130, 80, 170, 80]  # 1→2→3(타격,홀드)→4

_cache = None


def render_forge(rod_img_path=None) -> io.BytesIO:
    """와사비가 두드리는 애니메이션 GIF (rod_img_path는 호환용, 미사용)."""
    global _cache
    if _cache is not None:
        return io.BytesIO(_cache)

    srcs = []
    for i in (1, 2, 3, 4):
        p = os.path.join(ASSETS_DIR, f"wasabi_forge_{i}.png")
        if os.path.exists(p):
            srcs.append(Image.open(p).convert("RGBA"))

    if not srcs:  # 프레임 없으면 빈 이미지 폴백
        out = io.BytesIO()
        Image.new("RGB", (300, FRAME_H), BG).save(out, "GIF")
        out.seek(0)
        return out

    w0, h0 = srcs[0].size
    W = round(w0 * FRAME_H / h0)
    bg_img = None
    if os.path.exists(BG_IMG):
        bg_img = Image.open(BG_IMG).convert("RGBA").resize((W, FRAME_H), Image.LANCZOS)
    frames = []
    for im in srcs:
        im = im.resize((W, FRAME_H), Image.LANCZOS)
        canvas = bg_img.copy() if bg_img else Image.new("RGBA", (W, FRAME_H), BG + (255,))
        canvas.alpha_composite(im)
        frames.append(canvas.convert("RGB"))

    durations = DURATIONS[:len(frames)] or [120] * len(frames)
    out = io.BytesIO()
    frames[0].save(
        out, format="GIF", save_all=True, append_images=frames[1:],
        duration=durations, loop=0, disposal=2, optimize=True,
    )
    out.seek(0)
    _cache = out.getvalue()
    return io.BytesIO(_cache)
