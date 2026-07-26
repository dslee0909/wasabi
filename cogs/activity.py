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
from store import get_guild_config, update_guild_config, level_role_ladder


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

    # ---- 자동 승급 (5분마다): 전체 누적 '레벨' 기준, 상호배타 사다리 ----
    @tasks.loop(minutes=5)
    async def promote_loop(self):
        for guild in self.bot.guilds:
            cfg = get_guild_config(guild.id)
            ladder = level_role_ladder(cfg)
            # 사다리를 실제 역할 객체로 (존재하는 것만), 레벨 오름차순
            tiers = [(t["level"], guild.get_role(t["role_id"])) for t in ladder]
            tiers = [(lv, r) for lv, r in tiers if r is not None]
            if not tiers:
                continue
            ladder_roles = {r for _, r in tiers}
            # 사다리 진입(Lv10+ 승급) 시 함께 뺄 '등업 제거' 역할 (예: newbie)
            strip_roles = {r for r in (guild.get_role(rid)
                           for rid in cfg.get("graduation_strip_roles", [])) if r is not None}

            # 전체 누적 시간으로 각자의 레벨 계산
            conn = vt.db()
            rows = conn.execute(
                "SELECT user_id, SUM(seconds) AS total FROM voice_sessions WHERE guild_id=? GROUP BY user_id",
                (guild.id,),
            ).fetchall()
            conn.close()

            for user_id, total in rows:
                member = guild.get_member(user_id)
                if member is None:
                    continue
                level = vt.hours_to_level(total / 3600, guild.id)
                # 자격 되는 '가장 높은' 티어 하나만 목표 역할
                target = None
                for lv, role in tiers:  # 오름차순이라 마지막으로 통과한 게 최고 티어
                    if level >= lv:
                        target = role
                have = set(member.roles)
                to_add = [target] if target and target not in have else []
                # 목표를 제외한 다른 사다리 역할은 전부 제거 (하위 레벨 역할 자동 탈락)
                to_remove = [r for r in ladder_roles if r in have and r is not target]
                # 사다리에 진입한 멤버(target 있음)면 등업 제거 역할(newbie 등)도 뺀다.
                # 사다리 밖(target 없음, 아직 신입)은 건드리지 않음.
                if target:
                    to_remove += [r for r in strip_roles if r in have]
                try:
                    if to_add:
                        await member.add_roles(*to_add, reason=f"Lv.{level} 레벨 사다리 승급")
                    if to_remove:
                        await member.remove_roles(*to_remove, reason="상위 레벨 역할로 대체(하위 제거)")
                except discord.Forbidden:
                    pass

    @promote_loop.before_loop
    async def before_promote(self):
        await self.bot.wait_until_ready()

    # ---- /활동 승급 · 기간 · 잠수 ----
    @활동.command(name="승급", description="레벨 역할 사다리에 단계를 추가/수정 (상위 달성 시 하위 자동 제거)")
    @app_commands.describe(역할="부여할 역할", 레벨="이 레벨 이상이면 이 역할")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def set_promote(self, interaction: discord.Interaction, 역할: discord.Role, 레벨: int):
        if 레벨 < 1:
            await interaction.response.send_message("레벨은 1 이상이어야 해요.", ephemeral=True)
            return
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래라 부여할 수 없어요. 봇 역할을 위로 올려주세요.",
                ephemeral=True,
            )
            return
        # 기존 사다리(레거시 단일설정 승계 포함)에서 같은 레벨/같은 역할 항목은 교체
        ladder = level_role_ladder(get_guild_config(interaction.guild.id))
        ladder = [t for t in ladder if t["level"] != 레벨 and t["role_id"] != 역할.id]
        ladder.append({"level": 레벨, "role_id": 역할.id})
        ladder.sort(key=lambda t: t["level"])
        update_guild_config(interaction.guild.id, {"level_roles": ladder})
        lines = "\n".join(f"Lv.{t['level']} → <@&{t['role_id']}>" for t in ladder)
        await interaction.response.send_message(
            f"✅ 레벨 역할 사다리 등록 (총 {len(ladder)}단계):\n{lines}\n\n"
            f"상위 레벨을 달성하면 하위 레벨 역할은 자동으로 빠져요. (5분마다 확인)",
            ephemeral=True,
        )

    @활동.command(name="승급목록", description="레벨 역할 사다리와 등업 제거 역할을 봅니다")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def list_promote(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild.id)
        ladder = level_role_ladder(cfg)
        if not ladder:
            await interaction.response.send_message(
                "등록된 레벨 역할이 없어요. `/활동 승급` 으로 추가하세요.", ephemeral=True)
            return
        lines = "\n".join(f"Lv.{t['level']} → <@&{t['role_id']}>" for t in ladder)
        msg = f"🪜 **레벨 역할 사다리**\n{lines}"
        strip = cfg.get("graduation_strip_roles", [])
        if strip:
            msg += "\n\n⬆️ **등업 제거** (Lv10+ 승급 시 제거): " + ", ".join(f"<@&{r}>" for r in strip)
        await interaction.response.send_message(msg, ephemeral=True)

    @활동.command(name="등업제거", description="사다리 진입(Lv10+ 승급) 시 자동으로 뺄 역할을 토글합니다 (예: newbie)")
    @app_commands.describe(역할="승급 시 제거할 역할 (같은 역할 다시 실행하면 해제)")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def toggle_grad_strip(self, interaction: discord.Interaction, 역할: discord.Role):
        cfg = get_guild_config(interaction.guild.id)
        strip = list(cfg.get("graduation_strip_roles", []))
        if 역할.id in strip:
            strip.remove(역할.id)
            update_guild_config(interaction.guild.id, {"graduation_strip_roles": strip})
            msg = f"✅ **{역할.name}** 을 등업 제거 목록에서 뺐어요."
        else:
            strip.append(역할.id)
            update_guild_config(interaction.guild.id, {"graduation_strip_roles": strip})
            msg = f"✅ 이제 Lv10+ 로 승급(사다리 진입)하면 **{역할.name}** 을 자동으로 뺄게요."
        if strip:
            msg += "\n현재 등업 제거 대상: " + ", ".join(f"<@&{r}>" for r in strip)
        await interaction.response.send_message(msg, ephemeral=True)

    @활동.command(name="승급해제", description="레벨 역할 사다리에서 특정 레벨 단계를 제거")
    @app_commands.describe(레벨="제거할 단계의 레벨")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def remove_promote(self, interaction: discord.Interaction, 레벨: int):
        ladder = level_role_ladder(get_guild_config(interaction.guild.id))
        new = [t for t in ladder if t["level"] != 레벨]
        if len(new) == len(ladder):
            await interaction.response.send_message(f"Lv.{레벨} 단계가 사다리에 없어요.", ephemeral=True)
            return
        update_guild_config(interaction.guild.id, {"level_roles": new})
        await interaction.response.send_message(
            f"✅ Lv.{레벨} 단계를 사다리에서 뺐어요. (멤버의 기존 역할·역할 자체는 그대로 두었어요)",
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
