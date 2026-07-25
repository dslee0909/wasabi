"""
디스코드 봇 진입점 (bot.py)
- 1단계 목표: 봇 온라인 + 슬래시 명령어 /ping 응답

실행 방법:
    1) pip install -r requirements.txt
    2) .env.example 을 복사해 .env 로 만들고 토큰 입력
    3) python bot.py
"""

import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# .env 파일에서 환경변수(토큰) 읽어오기
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# 봇이 사용할 권한(Intents) 설정
# - members: 멤버 입장/퇴장 감지 (환영 메시지, 역할)
# - voice_states: 음성채널 입퇴장 감지 (임시 음성채널, 활동시간)
# message_content(글 내용 읽기)는 쓰지 않는다 — 파티 감지는 역할 멘션(role_mentions)
# 으로만 하고, 메시지 카운트는 on_message 이벤트만 있으면 되므로 내용이 필요 없다.
# 이 특권 인텐트를 안 켜두면 100+ 서버 인증(정식 출시) 심사가 훨씬 수월하다.
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True


class MyBot(commands.Bot):
    def __init__(self):
        # prefix 는 !ping 같은 접두사 명령어용(익힘용), 주력은 슬래시 명령어
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # cogs 폴더의 기능 모듈들을 자동으로 불러오기
        await self.load_all_cogs()
        # 슬래시 명령어를 디스코드에 동기화(등록)
        await self.tree.sync()
        print("슬래시 명령어 동기화 완료")

    async def load_all_cogs(self):
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if not os.path.isdir(cogs_dir):
            return
        for filename in os.listdir(cogs_dir):
            # __init__.py 등 밑줄로 시작하는 파일은 제외
            if filename.endswith(".py") and not filename.startswith("_"):
                ext_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(ext_name)
                    print(f"기능 불러옴: {ext_name}")
                except Exception as e:
                    print(f"[오류] {ext_name} 불러오기 실패: {e}")


bot = MyBot()


@bot.event
async def on_ready():
    print(f"로그인 성공: {bot.user} (ID: {bot.user.id})")
    print("봇이 온라인 상태입니다.")


# ---- 슬래시 명령어 ----
# 봇 상태 점검용(개발/관리자). default_permissions 로 일반 유저 목록에서 숨기고,
# has_permissions 로 실제 실행도 막는다 (기본권한만으론 서버에서 덮어쓸 수 있으므로 둘 다).
@bot.tree.command(name="ping", description="봇 지연시간을 확인합니다 (관리자)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"pong! (지연시간: {latency_ms}ms)", ephemeral=True)


# cog 밖 명령어(/ping)의 권한 실패 등을 깔끔하게 안내한다.
# cog 명령어는 각자의 cog_app_command_error 가 먼저 처리하므로 여기 오지 않는다.
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "서버 관리 권한이 필요한 명령어예요."
    else:
        msg = "명령을 처리하는 중 문제가 생겼어요."
        print(f"[명령 오류] {interaction.command} : {error!r}")
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


def main():
    if not TOKEN:
        print("[오류] DISCORD_TOKEN 이 설정되지 않았습니다.")
        print(".env.example 을 복사해 .env 로 만들고 토큰을 넣어주세요.")
        return
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
