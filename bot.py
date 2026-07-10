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
# - message_content: 메시지 내용 읽기 (파티 모집 양식 감지)
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True


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
@bot.tree.command(name="ping", description="봇이 살아있는지 확인합니다")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"pong! (지연시간: {latency_ms}ms)")


def main():
    if not TOKEN:
        print("[오류] DISCORD_TOKEN 이 설정되지 않았습니다.")
        print(".env.example 을 복사해 .env 로 만들고 토큰을 넣어주세요.")
        return
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
