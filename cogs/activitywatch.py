"""활동 감시 / 미달성 알림 (cogs/activitywatch.py)

최소 활동량을 못 채운 멤버를 두 갈래로 자동 추적해, 각각 다른 관리자 채널에
'현재 명단 전체'를 올린다. 명단이 바뀔 때(추가/해결)만 다시 보낸다.

① 신입 미달성  — 입장 2주(336h)가 지났는데 레벨10 역할이 없는 멤버
                  (레벨10 = /활동 승급 으로 지정한 promote_role. 없으면 계산 레벨로 폴백)
② 활동 미달성  — 레벨10 역할을 가진 정착 멤버 중 최근 30일 음성이 20시간 미만

역할 유무로 갈리므로 한 사람이 두 명단에 동시에 오르지 않는다.
명단 멤버는 멘션 형태로 '이름만' 보이고 알림(핑)은 가지 않는다(allowed_mentions=none).
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

import voicetime as vt
from store import get_guild_config, update_guild_config

NEWCOMER_GRACE_DAYS = 14      # 입장 후 이 기간이 지나면 신입 판정
DEFAULT_PROMOTE_LEVEL = 10    # promote_level 미설정 시 기준 레벨
ACTIVITY_PERIOD_DAYS = 30     # 활동 판정 기간
ACTIVITY_MIN_HOURS = 20       # 이 기간에 채워야 하는 음성 시간

CHECK_INTERVAL_MIN = 15       # 감시 주기(분)


class ActivityWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.watch_loop.start()

    def cog_unload(self):
        self.watch_loop.cancel()

    # ---- 판정 헬퍼 ----
    @staticmethod
    def _has_level_role(guild: discord.Guild, member: discord.Member, cfg: dict) -> bool:
        """레벨10 역할 보유 여부. 역할 미설정 시 계산 레벨로 폴백."""
        role_id = cfg.get("promote_role_id")
        level = cfg.get("promote_level", DEFAULT_PROMOTE_LEVEL)
        if role_id:
            role = guild.get_role(role_id)
            if role is not None:
                return role in member.roles
        total = vt.total_seconds(guild.id, member.id)
        return vt.hours_to_level(total / 3600, guild.id) >= level

    @staticmethod
    def _days_since_join(member: discord.Member) -> float | None:
        if member.joined_at is None:
            return None
        return (discord.utils.utcnow() - member.joined_at).total_seconds() / 86400

    # ---- 명단 계산 ----
    def _newcomer_list(self, guild: discord.Guild, cfg: dict):
        """(member, 입장경과일) 목록 — 입장 2주+ · 레벨10 역할 없음."""
        out = []
        for m in guild.members:
            if m.bot:
                continue
            days = self._days_since_join(m)
            if days is None or days < NEWCOMER_GRACE_DAYS:
                continue
            if self._has_level_role(guild, m, cfg):
                continue
            out.append((m, days))
        out.sort(key=lambda x: -x[1])  # 오래된 미달성부터
        return out

    def _activity_list(self, guild: discord.Guild, cfg: dict):
        """(member, 최근30일_음성시간) 목록 — 레벨10 보유 · 30일 음성 20h 미만."""
        out = []
        limit = ACTIVITY_MIN_HOURS * 3600
        for m in guild.members:
            if m.bot:
                continue
            if not self._has_level_role(guild, m, cfg):
                continue
            secs = vt.voice_seconds_days(guild.id, m.id, ACTIVITY_PERIOD_DAYS)
            if secs < limit:
                out.append((m, secs))
        out.sort(key=lambda x: x[1])  # 가장 적게 한 사람부터
        return out

    # ---- 메시지 ----
    @staticmethod
    def _newcomer_embed(rows) -> discord.Embed:
        if rows:
            lines = []
            for m, days in rows:
                joined = m.joined_at.astimezone(vt.KST).strftime("%Y-%m-%d") if m.joined_at else "?"
                lines.append(f"• {m.mention} — {int(days)}일째 (입장 {joined})")
            desc = "\n".join(lines)
            color = discord.Color.orange()
        else:
            desc = "✅ 현재 미달성 신입이 없어요."
            color = discord.Color.green()
        e = discord.Embed(title=f"🌱 신입 미달성 ({len(rows)}명)", description=desc, color=color)
        e.set_footer(text=f"입장 {NEWCOMER_GRACE_DAYS}일 경과 · 레벨10 미달 · 레벨10 달성 시 자동 제외")
        return e

    @staticmethod
    def _activity_embed(rows) -> discord.Embed:
        if rows:
            lines = [f"• {m.mention} — 최근 {ACTIVITY_PERIOD_DAYS}일 {secs/3600:.1f}시간"
                     for m, secs in rows]
            desc = "\n".join(lines)
            color = discord.Color.orange()
        else:
            desc = "✅ 현재 활동 미달성 멤버가 없어요."
            color = discord.Color.green()
        e = discord.Embed(title=f"💤 활동 미달성 ({len(rows)}명)", description=desc, color=color)
        e.set_footer(text=f"최근 {ACTIVITY_PERIOD_DAYS}일 음성 {ACTIVITY_MIN_HOURS}시간 미만 (레벨10 정착 멤버 대상)")
        return e

    async def _sync_list(self, guild, channel_id, state_key, rows, embed):
        """명단이 직전 발송과 다를 때만 전체를 다시 보낸다."""
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        current = sorted(m.id for m, _ in rows)
        prev = get_guild_config(guild.id).get(state_key)
        if prev is not None and sorted(prev) == current:
            return  # 변화 없음 → 재발송 안 함
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            update_guild_config(guild.id, {state_key: current})
        except discord.HTTPException:
            pass

    # ---- 주기 감시 ----
    @tasks.loop(minutes=CHECK_INTERVAL_MIN)
    async def watch_loop(self):
        for guild in self.bot.guilds:
            cfg = get_guild_config(guild.id)
            nc_ch = cfg.get("newcomer_alert_channel_id")
            ac_ch = cfg.get("activity_alert_channel_id")
            if nc_ch:
                rows = self._newcomer_list(guild, cfg)
                await self._sync_list(guild, nc_ch, "newcomer_watch_state", rows,
                                      self._newcomer_embed(rows))
            if ac_ch:
                rows = self._activity_list(guild, cfg)
                await self._sync_list(guild, ac_ch, "activity_watch_state", rows,
                                      self._activity_embed(rows))

    @watch_loop.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()

    # ---- 관리자 명령: 알림 채널 설정 ----
    신입알림 = app_commands.Group(
        name="신입알림",
        description="신입 미달성 명단 알림 채널 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )
    활동알림 = app_commands.Group(
        name="활동알림",
        description="활동 미달성 명단 알림 채널 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    async def _set_channel(self, interaction, key, label, channel):
        ch = channel or interaction.channel
        update_guild_config(interaction.guild.id, {key: ch.id})
        await interaction.response.send_message(
            f"✅ **{label}** 명단을 {ch.mention} 에 보낼게요. (명단이 바뀔 때마다 갱신)",
            ephemeral=True)

    async def _off_channel(self, interaction, key, state_key, label):
        update_guild_config(interaction.guild.id, {key: None, state_key: None})
        await interaction.response.send_message(f"✅ **{label}** 알림을 껐어요.", ephemeral=True)

    @신입알림.command(name="채널", description="신입 미달성 명단을 보낼 채널을 지정합니다")
    @app_commands.describe(채널="알림 채널 (비우면 현재 채널)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_newcomer(self, interaction: discord.Interaction, 채널: discord.TextChannel = None):
        await self._set_channel(interaction, "newcomer_alert_channel_id", "신입 미달성", 채널)

    @신입알림.command(name="끄기", description="신입 미달성 알림을 끕니다")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def off_newcomer(self, interaction: discord.Interaction):
        await self._off_channel(interaction, "newcomer_alert_channel_id", "newcomer_watch_state", "신입 미달성")

    @활동알림.command(name="채널", description="활동 미달성 명단을 보낼 채널을 지정합니다")
    @app_commands.describe(채널="알림 채널 (비우면 현재 채널)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_activity(self, interaction: discord.Interaction, 채널: discord.TextChannel = None):
        await self._set_channel(interaction, "activity_alert_channel_id", "활동 미달성", 채널)

    @활동알림.command(name="끄기", description="활동 미달성 알림을 끕니다")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def off_activity(self, interaction: discord.Interaction):
        await self._off_channel(interaction, "activity_alert_channel_id", "activity_watch_state", "활동 미달성")

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("서버 관리 권한이 필요한 명령어예요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityWatch(bot))
