"""
활동/잠수 관리 (cogs/activity.py) — 4단계 D (승급·잠수 부분)

레벨(cogs/leveling.py)과 '같은 음성시간 데이터'를 쓰지만, 목적이 달라 모듈을 분리:
  - ① 신입 → 정규 자동 승급: '전체 누적 레벨'이 기준 레벨 이상이면 (영구 기준)
  - ② 잠수 유저 추방 검토: '최근 N일 활동'이 기준 미만이면

명령어 그룹 /활동 (관리자 전용, 목록에서 숨김):
  /활동 승급   그 레벨 이상이면 역할 자동 부여
  /활동 기간   잠수 판단 기간(일) 설정
  /활동 잠수   기준 미만 멤버 목록 (추방은 수동)

자동 승급은 5분마다 백그라운드로 확인합니다.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

import voicetime as vt
from store import get_guild_config, update_guild_config


class Activity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.promote_loop.start()

    def cog_unload(self):
        self.promote_loop.cancel()

    활동 = app_commands.Group(
        name="활동",
        description="활동/승급/잠수 관리 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ---- 자동 승급 (5분마다): 전체 누적 '레벨' 기준 ----
    @tasks.loop(minutes=5)
    async def promote_loop(self):
        for guild in self.bot.guilds:
            cfg = get_guild_config(guild.id)
            role_id = cfg.get("promote_role_id")
            need_level = cfg.get("promote_level")
            if not role_id or not need_level:
                continue
            role = guild.get_role(role_id)
            if role is None:
                continue

            # 전체 누적 시간으로 각자의 레벨 계산
            conn = vt.db()
            rows = conn.execute(
                "SELECT user_id, SUM(seconds) AS total FROM voice_sessions WHERE guild_id=? GROUP BY user_id",
                (guild.id,),
            ).fetchall()
            conn.close()

            for user_id, total in rows:
                if vt.hours_to_level(total / 3600, guild.id) < need_level:
                    continue
                member = guild.get_member(user_id)
                if member and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Lv.{need_level} 달성 자동 승급")
                    except discord.Forbidden:
                        pass

    @promote_loop.before_loop
    async def before_promote(self):
        await self.bot.wait_until_ready()

    # ---- /활동 승급 · 기간 · 잠수 ----
    @활동.command(name="승급", description="특정 레벨에 도달하면 자동으로 줄 역할을 지정합니다")
    @app_commands.describe(역할="자동 부여할 역할 (예: 정규)", 레벨="이 레벨 이상이면 자동 승급")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def set_promote(self, interaction: discord.Interaction, 역할: discord.Role, 레벨: int):
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래라 부여할 수 없어요. 봇 역할을 위로 올려주세요.",
                ephemeral=True,
            )
            return
        update_guild_config(interaction.guild.id, {"promote_role_id": 역할.id, "promote_level": 레벨})
        need_hours = vt.level_to_hours(레벨, interaction.guild.id)
        await interaction.response.send_message(
            f"✅ **Lv.{레벨}**(총 {vt.format_duration(need_hours * 3600)}) 이상이면 "
            f"**{역할.name}** 역할을 자동 부여해요. (5분마다 확인)",
            ephemeral=True,
        )

    @활동.command(name="기간", description="승급·잠수를 판단할 기간(일)을 설정합니다")
    @app_commands.describe(일수="며칠 기준으로 최근 활동을 볼지 (기본 30일)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_window(self, interaction: discord.Interaction, 일수: int):
        if 일수 < 1:
            await interaction.response.send_message("1일 이상으로 설정해주세요.", ephemeral=True)
            return
        update_guild_config(interaction.guild.id, {"activity_window_days": 일수})
        await interaction.response.send_message(
            f"✅ 이제 **최근 {일수}일** 기준으로 승급·잠수를 판단해요.", ephemeral=True
        )

    @활동.command(name="잠수", description="최근 활동이 기준 미만인 멤버를 찾습니다 (추방 검토용)")
    @app_commands.describe(기준시간="이 시간(시간) 미만이면 잠수로 표시 (기본 1시간)", 제외역할="이 역할을 가진 사람은 목록에서 제외")
    @app_commands.checks.has_permissions(kick_members=True)
    async def find_inactive(
        self,
        interaction: discord.Interaction,
        기준시간: float = 1.0,
        제외역할: discord.Role = None,
    ):
        threshold = 기준시간 * 3600
        inactive = []
        for member in interaction.guild.members:
            if member.bot:
                continue
            if 제외역할 and 제외역할 in member.roles:
                continue
            recent = vt.recent_seconds(interaction.guild.id, member.id)
            if recent < threshold:
                inactive.append((member, recent))

        if not inactive:
            await interaction.response.send_message("기준 미만 잠수 멤버가 없어요. 👍", ephemeral=True)
            return

        days = vt.window_days(interaction.guild.id)
        inactive.sort(key=lambda x: x[1])
        lines = [f"• {m.display_name} — 최근 {days}일 {vt.format_duration(s)}" for m, s in inactive[:20]]
        more = f"\n…외 {len(inactive) - 20}명" if len(inactive) > 20 else ""
        embed = discord.Embed(
            title=f"💤 잠수 멤버 ({len(inactive)}명, {days}일 {기준시간}시간 미만)",
            description="\n".join(lines) + more,
            color=discord.Color.dark_orange(),
        )
        embed.set_footer(text="추방은 관리자가 직접 판단하세요 — 자동 추방은 하지 않습니다")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("관리자 권한이 필요한 명령어예요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Activity(bot))
