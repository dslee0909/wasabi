"""
업적 / 도전과제 (cogs/achievements.py)

레벨과 다른 축의 성취감 — 뱃지를 모으는 재미.
저장하는 데이터(음성·메시지·레벨·접속시간대·듀오·낚시·코인)로 달성 여부를 판정.
일부는 히든 업적이라 달성 전엔 '???' 로 가려진다.

명령어:
  /업적 [멤버]        달성/미달성 업적 보기 (유저용, 볼 때 새로 달성한 건 자동 획득+축하)
  /업적채널 설정 [채널]  업적 축하 알림을 띄울 채널 지정 (관리자)
  /업적채널 해제        축하 알림 끄기 (관리자)

봇이 5분마다 자동으로 업적을 확인해, 새로 달성한 사람을 지정 채널에 축하합니다.
업적은 한 번 달성하면 영구 유지됩니다 (data.db 의 achievements 테이블).
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

import voicetime as vt
from store import get_guild_config, update_guild_config

# (key, 이모지, 이름, 설명, 조건함수, 히든여부)
#   조건함수는 stats dict 를 받아 bool 반환.
#   히든이면 미달성 시 /업적 에서 '???' 로 가려져 발견하는 재미를 준다.
ACHIEVEMENTS = [
    # ── 음성 ──
    ("first_voice", "🌱", "첫 발걸음", "음성채널에 처음 접속", lambda s: s["voice"] > 0, False),
    ("voice_10h", "🔊", "음성 10시간", "누적 음성 10시간 달성", lambda s: s["voice"] >= 10 * 3600, False),
    ("voice_100h", "🦉", "음성 100시간", "누적 음성 100시간 달성", lambda s: s["voice"] >= 100 * 3600, False),
    ("voice_500h", "🔥", "음성 500시간", "누적 음성 500시간 달성", lambda s: s["voice"] >= 500 * 3600, False),
    ("night_owl", "🌙", "올빼미", "새벽(0~4시)에 음성 접속", lambda s: bool(s["hours"] & {0, 1, 2, 3, 4}), False),
    ("early_bird", "🐦", "일찍 일어난 새", "아침(5~8시)에 음성 접속", lambda s: bool(s["hours"] & {5, 6, 7, 8}), False),
    # ── 메시지 ──
    ("msg_100", "💬", "수다쟁이", "메시지 100개 작성", lambda s: s["msgs"] >= 100, False),
    ("msg_1000", "📢", "인싸", "메시지 1000개 작성", lambda s: s["msgs"] >= 1000, False),
    # ── 레벨 ──
    ("level_10", "⭐", "레벨 10", "레벨 10 도달", lambda s: s["level"] >= 10, False),
    ("level_20", "👑", "레벨 20", "레벨 20 도달", lambda s: s["level"] >= 20, False),
    # ── 소셜 ──
    ("duo_10h", "💞", "단짝", "누군가와 10시간 이상 함께 음성", lambda s: s["duo"] >= 10 * 3600, False),
    ("friends_3", "👥", "인맥왕", "3명과 각각 10시간 이상 함께 음성", lambda s: s["duo3"] >= 3, False),
    # ── 낚시 ──
    ("fish_first", "🎣", "첫 손맛", "물고기를 처음 낚음", lambda s: s["fish"] >= 1, False),
    ("fish_100", "🐟", "낚시꾼", "물고기 100마리 낚음", lambda s: s["fish"] >= 100, False),
    ("fish_1000", "🎏", "강태공", "물고기 1000마리 낚음", lambda s: s["fish"] >= 1000, False),
    ("fish_5000", "🏆", "낚시왕", "물고기 5000마리 낚음", lambda s: s["fish"] >= 5000, False),
    ("fish_10000", "🌊", "바다의 전설", "물고기 10000마리 낚음", lambda s: s["fish"] >= 10000, False),
    ("fish_20000", "🔱", "심해의 지배자", "물고기 20000마리 낚음", lambda s: s["fish"] >= 20000, False),
    # 반짝이 사다리 — 강화로 반짝이 확률이 올라(최대 26%) 임계값 상향.
    # 'shiny_10' 키는 기존 획득자 badge 보존을 위해 유지(임계값만 10→50).
    ("shiny_10", "✨", "반짝이 수집가", "반짝이는 물고기 50마리 낚음", lambda s: s["shiny"] >= 50, False),
    ("shiny_300", "🌟", "반짝이 사냥꾼", "반짝이는 물고기 300마리 낚음", lambda s: s["shiny"] >= 300, False),
    ("shiny_1500", "💫", "반짝이 대가", "반짝이는 물고기 1500마리 낚음", lambda s: s["shiny"] >= 1500, False),
    ("dex_master", "📖", "도감 마스터", "모든 종류의 물고기 낚음", lambda s: s["dex"] >= s["dex_total"], False),
    ("catch_diamond", "💎", "인생 역전", "다이아몬드를 낚음", lambda s: s["diamond"], True),
    ("catch_boot", "🥾", "어부의 굴욕", "낡은 신발을 낚음", lambda s: s["boot"], True),
    # ── 경제 ──
    ("rich_10k", "🪙", "첫 재산", "코인 10,000 보유", lambda s: s["money"] >= 10_000, False),
    ("rich_1m", "💰", "백만장자", "코인 1,000,000 보유", lambda s: s["money"] >= 1_000_000, False),
    ("savings_500k", "🏦", "저축왕", "은행에 500,000 예치", lambda s: s["bank"] >= 500_000, False),
    # ── 히든: 종합 ──
    ("allrounder", "🌈", "만능 재주꾼", "낚시·음성·메시지·코인을 모두 경험",
     lambda s: s["fish"] > 0 and s["voice"] > 0 and s["msgs"] > 0 and s["money"] > 0, True),
]

ACH_BY_KEY = {a[0]: a for a in ACHIEVEMENTS}

# 도감 마스터 판정용: 낚여서 기록되는 물고기 종수 (economy.FISH 의 가격>0 종)
try:
    from cogs.economy import FISH as _FISH
    DEX_TOTAL = sum(1 for f in _FISH if f[2] > 0)
except Exception:
    DEX_TOTAL = 12  # 폴백 (현재 낚이는 종 수)


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    # 업적 그룹 (채널 설정 — 관리자)
    업적채널 = app_commands.Group(
        name="업적채널",
        description="업적 축하 알림 채널 설정 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def _build_stats(self, guild_id: int, user_id: int) -> dict:
        voice = vt.total_seconds(guild_id, user_id)
        duos = vt.best_duos(guild_id, user_id, days=3650, limit=1)
        fish, shiny, dex = vt.get_fishing_stats(guild_id, user_id)
        coins = vt.get_balance(guild_id, user_id)
        bank = vt.get_bank(guild_id, user_id)
        return {
            "voice": voice,
            "level": vt.hours_to_level(voice / 3600, guild_id),
            "msgs": vt.message_count_total(guild_id, user_id),
            "hours": vt.started_hours(guild_id, user_id),
            "duo": duos[0][1] if duos else 0,
            "duo3": vt.duo_count_over(guild_id, user_id, 10 * 3600),
            "fish": fish,
            "shiny": shiny,
            "dex": dex,
            "dex_total": DEX_TOTAL,
            "diamond": vt.has_caught(guild_id, user_id, "다이아몬드"),
            "boot": vt.has_caught(guild_id, user_id, "낡은 신발"),
            "coins": coins,
            "bank": bank,
            "money": coins + bank,
        }

    def _newly_unlock(self, guild_id: int, user_id: int) -> list[str]:
        """조건 충족한 미획득 업적을 획득 처리하고, 새로 획득한 key 목록 반환."""
        stats = self._build_stats(guild_id, user_id)
        owned = vt.unlocked_achievements(guild_id, user_id)
        newly = []
        for key, emoji, name, desc, cond, hidden in ACHIEVEMENTS:
            if key not in owned and cond(stats):
                vt.unlock_achievement(guild_id, user_id, key)
                newly.append(key)
        return newly

    async def _announce(self, guild: discord.Guild, member: discord.Member, newly_keys: list[str]):
        """새로 달성한 업적을 지정 채널에 축하."""
        if not newly_keys:
            return
        channel_id = get_guild_config(guild.id).get("achievement_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        badges = "\n".join(f"{ACH_BY_KEY[k][1]} **{ACH_BY_KEY[k][2]}**" for k in newly_keys)
        embed = discord.Embed(
            title="🎉 업적 달성!",
            description=f"{member.mention} 님이 새 업적을 달성했어요!\n\n{badges}",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    # ---- 5분마다 자동 확인 ----
    @tasks.loop(minutes=5)
    async def check_loop(self):
        for guild in self.bot.guilds:
            if not get_guild_config(guild.id).get("achievement_channel_id"):
                continue  # 알림 채널 없는 서버는 건너뜀
            for member in guild.members:
                if member.bot:
                    continue
                newly = self._newly_unlock(guild.id, member.id)
                await self._announce(guild, member, newly)

    @check_loop.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ---- /업적 ----
    @app_commands.command(name="업적", description="달성한 업적과 남은 업적을 봅니다")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def achievements(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        gid = interaction.guild.id

        newly = self._newly_unlock(gid, member.id)
        await self._announce(interaction.guild, member, newly)  # 채널에도 축하
        owned = vt.unlocked_achievements(gid, member.id)

        lines = []
        for key, emoji, name, desc, _, hidden in ACHIEVEMENTS:
            if key in owned:
                lines.append(f"{emoji} **{name}** — {desc} ✅")
            elif hidden:
                # 히든 업적: 달성 전엔 정체를 가려 발견하는 재미를 준다
                lines.append("❓ **???** — 숨겨진 업적")
            else:
                lines.append(f"🔒 ~~{name}~~ — {desc}")

        hidden_left = sum(1 for k, *_ , h in ACHIEVEMENTS if h and k not in owned)
        embed = discord.Embed(
            title=f"🏅 {member.display_name} 님의 업적 ({len(owned)}/{len(ACHIEVEMENTS)})",
            description="\n".join(lines),
            color=discord.Color.teal(),
        )
        if hidden_left:
            embed.set_footer(text=f"❓ 숨겨진 업적 {hidden_left}개가 당신의 발견을 기다려요.")
        if newly:
            embed.add_field(
                name="🎉 새로 달성!",
                value="\n".join(f"{ACH_BY_KEY[k][1]} {ACH_BY_KEY[k][2]}" for k in newly),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---- /업적채널 설정 · 해제 ----
    @업적채널.command(name="설정", description="업적 축하 알림을 띄울 채널을 지정합니다")
    @app_commands.describe(채널="알림 채널 (비우면 현재 채널)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel = None):
        channel = 채널 or interaction.channel
        await interaction.response.defer(ephemeral=True)
        update_guild_config(interaction.guild.id, {"achievement_channel_id": channel.id})
        # 기존에 이미 충족한 업적은 조용히 획득 처리(축하 X) → 앞으로의 달성만 알림
        for member in interaction.guild.members:
            if not member.bot:
                self._newly_unlock(interaction.guild.id, member.id)
        await interaction.followup.send(
            f"✅ 이제 **새로** 업적을 달성하면 {channel.mention} 에 축하 알림이 떠요.\n"
            f"(기존에 이미 달성한 것들은 조용히 처리했어요)",
            ephemeral=True,
        )

    @업적채널.command(name="해제", description="업적 축하 알림을 끕니다")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear_channel(self, interaction: discord.Interaction):
        update_guild_config(interaction.guild.id, {"achievement_channel_id": None})
        await interaction.response.send_message("✅ 업적 축하 알림을 껐어요.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("관리자 권한이 필요한 명령어예요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Achievements(bot))
