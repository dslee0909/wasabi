"""
재미 기능 (cogs/fun.py)

/재롱 — assets/ 의 wasabi_*.gif 중 랜덤으로 하나를 보여줍니다.
새 GIF 를 assets/ 에 넣으면(wasabi_ 로 시작, .gif) 자동으로 포함돼요.

원본 GIF 의 배경은 투명이 아니라 실제 검정 픽셀이라, 그대로 올리면 디스코드에서
검은 사각형으로 보입니다. 그래서 바깥쪽 검정만 투명으로 빼고(_key_black_bg)
애니메이션 WebP 로 변환해 보냅니다. APNG 는 디스코드가 정지 이미지로 취급해서 안 됩니다.
(원본 파일은 건드리지 않습니다.)
"""

import asyncio
import io
import os
import random

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageSequence

GIF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
CACHE_DIR = os.path.join(GIF_DIR, ".webp_cache")
KEY_THRESH = 60  # 배경 검정 제거 임계값 (클수록 어두운 가장자리까지 제거)

# 변환 결과 메모리 캐시: {path: (mtime, bytes)}
_cache: dict[str, tuple[float, bytes]] = {}


def _gif_files() -> list[str]:
    """assets/ 안의 재롱 GIF 파일명 목록. 새 파일을 넣으면 코드 수정 없이 잡힌다."""
    try:
        return [f for f in os.listdir(GIF_DIR)
                if f.startswith("wasabi_") and f.lower().endswith(".gif")]
    except OSError:
        return []


def _key_black_bg(rgba: Image.Image) -> Image.Image:
    """모서리에서 연결된 검정 배경만 flood-fill 로 투명 처리 (안쪽 검정은 유지)."""
    w, h = rgba.size
    rgb = rgba.convert("RGB")
    marker = (1, 254, 2)  # 배경 표시용 (원본에 없는 색)
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if rgb.getpixel(corner) == marker:
            continue
        ImageDraw.floodfill(rgb, corner, marker, thresh=KEY_THRESH)
    alpha = Image.new("L", (w, h))
    alpha.putdata([0 if p == marker else 255 for p in rgb.getdata()])
    out = rgba.copy()
    out.putalpha(alpha)
    return out


def _convert(path: str) -> bytes:
    """검정 배경 GIF를 투명 배경 애니메이션 WebP 로 변환 (디스코드에서 투명+움직임 재생).

    프레임마다 전 픽셀을 훑기 때문에 느리다 (512x512 4프레임에 PC 약 1초, 파이는 수 초).
    그래서 이 함수는 _to_webp 의 캐시가 빈 경우에만 불린다.
    """
    src = Image.open(path)
    frames, durations = [], []
    for frame in ImageSequence.Iterator(src):
        frames.append(_key_black_bg(frame.convert("RGBA")))
        durations.append(frame.info.get("duration", 120))

    out = io.BytesIO()
    frames[0].save(
        out, format="WEBP", save_all=True, append_images=frames[1:],
        duration=durations, loop=0, lossless=True, quality=90,
    )
    return out.getvalue()


def _to_webp(path: str) -> io.BytesIO:
    """변환 결과를 메모리+디스크에 캐싱해서 돌려준다.

    재롱 GIF 는 안 바뀌는 고정 파일이라 결과도 항상 같다. 디스크에 남겨두면
    봇을 재시작해도 다시 안 굽는다 — GIF 당 평생 한 번만 변환하면 된다.
    원본보다 캐시가 오래됐으면(=GIF 를 갈아끼웠으면) 다시 굽는다.
    """
    mtime = os.path.getmtime(path)
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return io.BytesIO(hit[1])

    cached = os.path.join(CACHE_DIR, os.path.basename(path) + ".webp")
    if os.path.exists(cached) and os.path.getmtime(cached) >= mtime:
        with open(cached, "rb") as f:
            data = f.read()
    else:
        data = _convert(path)
        os.makedirs(CACHE_DIR, exist_ok=True)
        # 임시 파일에 쓰고 교체 — 동시에 두 명이 불러도 반쪽짜리 파일이 남지 않는다
        tmp = f"{cached}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, cached)

    _cache[path] = (mtime, data)
    return io.BytesIO(data)


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._warm_task = None

    async def cog_load(self):
        # 봇이 뜨자마자 백그라운드로 캐시를 데운다. 디스크 캐시가 있으면 바로 끝나고,
        # 없으면(첫 배포·새 GIF 추가) 여기서 미리 구워둬서 첫 /재롱 도 즉시 응답한다.
        # 참조를 남겨둬야 태스크가 도중에 GC 되지 않는다.
        self._warm_task = asyncio.create_task(self._warm_cache())

    async def _warm_cache(self):
        for f in _gif_files():
            try:
                await asyncio.to_thread(_to_webp, os.path.join(GIF_DIR, f))
            except Exception as e:  # 캐시 준비 실패가 봇 기동을 막으면 안 된다
                print(f"[재롱] 캐시 준비 실패 ({f}): {e}")

    @app_commands.command(name="재롱", description="와사비가 랜덤으로 귀여운 재롱을 부려요 🥑")
    async def aegyo(self, interaction: discord.Interaction):
        gifs = _gif_files()
        if not gifs:
            await interaction.response.send_message("아직 재롱 GIF가 없어요. 😢", ephemeral=True)
            return
        pick = random.choice(gifs)
        # 보통은 캐시가 데워져 있어 즉시 끝난다. 아직 안 데워졌으면 여기서 굽는데,
        # 3초 제한에 안 걸리도록 응답부터 열고 변환은 스레드로 넘긴다.
        await interaction.response.defer()
        data = await asyncio.to_thread(_to_webp, os.path.join(GIF_DIR, pick))
        await interaction.followup.send(
            content=f"🥑 **{interaction.user.display_name}** 님을 위한 와사비의 재롱!",
            file=discord.File(data, filename="wasabi.webp"),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
