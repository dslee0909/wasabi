"""
업적 / 도전과제 (cogs/achievements.py)

레벨과 다른 축의 성취감 — 숨은 뱃지를 모으는 재미.
저장하는 데이터(음성시간·메시지·레벨·접속시간대·듀오)로 달성 여부를 판정.

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

# (key, 이모지, 이름, 설명, 조건함수)  — 조건함수는 stats dict 를 받아 bool 반환
ACHIEVEMENTS = [
    ("first_voice", "🌱", "첫 발걸음", "음성채널에 처음 접속", lambda s: s["voice"] > 0),
    ("voice_10h", "🔊", "음성 10시간", "누적 음성 10시간 달성", lambda s: s["voice"] >= 10 * 3600),
    ("voice_100h", "🦉", "음성 100시간", "누적 음성 100시간 달성", lambda s: s["voice"] >= 100 * 3600),
    ("night_owl", "🌙", "올빼미", "새벽(0~4시)에 음성 접속", lambda s: bool(s["hours"] & {0, 1, 2, 3, 4})),
    ("early_bird", "🐦", "일찍 일어난 새", "아침(5~8시)에 음성 접속", lambda s: bool(s["hours"] & {5, 6, 7, 8})),
    ("msg_100", "💬", "수다쟁이", "메시지 100개 작성", lambda s: s["msgs"] >= 100),
    ("msg_1000", "📢", "인싸", "메시지 1000개 작성", lambda s: s["msgs"] >= 1000),
    ("level_10", "⭐", "레벨 10", "레벨 10 도달", lambda s: s["level"] >= 10),
    ("level_20", "👑", "레벨 20", "레벨 20 도달", lambda s: s["level"] >= 20),
    ("duo_10h", "💞", "단짝", "누군가와 10시간 이상 함께 음성", lambda s: s["duo"] >= 10 * 3600),
]

ACH_BY_KEY = {a[0]: a for a in ACHIEVEMENTS}


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
        return {
            "voice": voice,
            "level": vt.hours_to_level(voice / 3600, guild_id),
            "msgs": vt.message_count_total(guild_id, user_id),
            "hours": vt.started_hours(guild_id, user_id),
            "duo": duos[0][1] if duos else 0,
        }

    def _newly_unlock(self, guild_id: int, user_id: int) -> list[str]:
        """조건 충족한 미획득 업적을 획득 처리하고, 새로 획득한 key 목록 반환."""
        stats = self._build_stats(guild_id, user_id)
        owned = vt.unlocked_achievements(guild_id, user_id)
        newly = []
        for key, emoji, name, desc, cond in ACHIEVEMENTS:
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
        for key, emoji, name, desc, _ in ACHIEVEMENTS:
            if key in owned:
                lines.append(f"{emoji} **{name}** — {desc} ✅")
            else:
                lines.append(f"🔒 ~~{name}~~ — {desc}")

        embed = discord.Embed(
            title=f"🏅 {member.display_name} 님의 업적 ({len(owned)}/{len(ACHIEVEMENTS)})",
            description="\n".join(lines),
            color=discord.Color.teal(),
        )
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
