"""폰트 경로 해석 (fonts.py)

assets/fonts/ 에 같이 넣어둔 폰트를 먼저 쓰고, 없으면 OS 시스템 폰트를 찾는다.
윈도우에서 돌리든 라즈베리파이에서 돌리든 같은 그림이 나오게 하는 게 목적.

이모지 폰트를 못 찾아도 그림은 그려지지만 이모지만 두부(□)로 나온다.
에러 없이 조용히 깨지는 형태라 임포트 시점에 경고를 찍는다.
"""

import os

from PIL import ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")

# 앞에서부터 실제로 존재하는 첫 파일을 쓴다.
TEXT_PATHS = (
    os.path.join(FONT_DIR, "BMJUA_ttf.ttf"),            # 주아체 (한글 본문)
    r"C:\Windows\Fonts\malgun.ttf",                     # 윈도우 폴백
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # 리눅스 폴백
)
# Segoe UI Emoji 는 벡터(COLR) 라 크기 제약 없이 쓸 수 있다.
# 리눅스 기본 Noto Color Emoji 는 비트맵이라 Pillow 가 특정 크기만 받으므로 폴백에 넣지 않는다
# (넣으면 크기 안 맞을 때 조용히 깨지는 대신 예외로 죽는다). 파이로 옮길 땐 이 폰트를 같이 가져갈 것.
EMOJI_PATHS = (
    os.path.join(FONT_DIR, "seguiemj.ttf"),  # 봇과 함께 옮기는 컬러 이모지
    r"C:\Windows\Fonts\seguiemj.ttf",        # 윈도우 시스템 폰트
)


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


TEXT_PATH = _first_existing(TEXT_PATHS)
EMOJI_PATH = _first_existing(EMOJI_PATHS)

if EMOJI_PATH is None:
    print("[경고] 컬러 이모지 폰트를 찾지 못했습니다 — 슬롯 심볼과 카드 아이콘이 □ 로 나옵니다.")
    print(f"        {os.path.join(FONT_DIR, 'seguiemj.ttf')} 에 폰트를 넣어주세요.")


def text_font(size):
    """주아체(한글) 폰트. 이모지는 이걸로 그리면 두부가 되니 emoji_font 를 쓸 것."""
    if TEXT_PATH is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(TEXT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def emoji_font(size):
    """컬러 이모지 폰트. draw.text(..., embedded_color=True) 와 함께 쓸 것."""
    if EMOJI_PATH is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(EMOJI_PATH, size)
    except OSError:
        return ImageFont.load_default()
