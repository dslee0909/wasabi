"""
역할 자동화 (cogs/roles.py) — 2단계

명령어 그룹 /역할 (관리자 전용, 목록에서 숨김):
  /역할 자동설정   입장 시 자동으로 줄 역할 지정
  /역할 자동확인   현재 자동 역할 확인
  /역할 자동해제   자동 부여 끄기
  /역할 부여       특정 멤버에게 역할 부여
  /역할 회수       특정 멤버의 역할 회수

권한 참고: 봇 역할이 '부여할 역할'보다 위에 있어야 부여됩니다.
"""

import discord
from discord import app_commands
from discord.ext import commands

from store import get_guild_config, update_guild_config


class Roles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # 관리자 전용 그룹 (역할 관리 권한 없는 유저에겐 목록에서 숨김)
    역할 = app_commands.Group(
        name="역할",
        description="역할 관리 (관리자)",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # ---- 입장 시 자동 역할 부여 ----
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = get_guild_config(member.guild.id)
        role_id = cfg.get("auto_role_id")
        if not role_id:
            return
        role = member.guild.get_role(role_id)
        if role is None:
            return
        try:
            await member.add_roles(role, reason="입장 시 자동 역할 부여")
        except discord.Forbidden:
            print(f"[경고] 자동 역할 부여 실패(권한 부족): {member.guild.name}")

    # ---- /역할 자동설정 · 자동확인 · 자동해제 ----
    @역할.command(name="자동설정", description="새 멤버 입장 시 자동으로 줄 역할을 지정합니다")
    @app_commands.describe(역할="입장한 멤버에게 자동으로 부여할 역할")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def auto_set(self, interaction: discord.Interaction, 역할: discord.Role):
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래에 있어서 부여할 수 없어요.\n"
                f"서버 설정 → 역할 에서 봇 역할을 **{역할.name} 위로** 올려주세요.",
                ephemeral=True,
            )
            return
        update_guild_config(interaction.guild.id, {"auto_role_id": 역할.id})
        await interaction.response.send_message(
            f"✅ 이제 새 멤버가 입장하면 **{역할.name}** 역할이 자동 부여됩니다.", ephemeral=True
        )

    @역할.command(name="자동확인", description="현재 자동 부여 역할을 확인합니다")
    async def auto_check(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild.id)
        role_id = cfg.get("auto_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None
        if role is None:
            await interaction.response.send_message("자동 역할이 설정되어 있지 않습니다.", ephemeral=True)
        else:
            await interaction.response.send_message(f"현재 자동 역할: **{role.name}**", ephemeral=True)

    @역할.command(name="자동해제", description="입장 시 자동 역할 부여를 끕니다")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def auto_clear(self, interaction: discord.Interaction):
        update_guild_config(interaction.guild.id, {"auto_role_id": None})
        await interaction.response.send_message("✅ 자동 역할 부여를 껐습니다.", ephemeral=True)

    # ---- /역할 부여 · 회수 ----
    @역할.command(name="부여", description="특정 멤버에게 역할을 부여합니다")
    @app_commands.describe(멤버="역할을 줄 멤버", 역할="부여할 역할")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def give(self, interaction: discord.Interaction, 멤버: discord.Member, 역할: discord.Role):
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래라 부여할 수 없어요. 봇 역할을 위로 올려주세요.",
                ephemeral=True,
            )
            return
        if 역할 in 멤버.roles:
            await interaction.response.send_message(
                f"{멤버.display_name} 님은 이미 **{역할.name}** 역할이 있어요.", ephemeral=True
            )
            return
        try:
            await 멤버.add_roles(역할, reason=f"{interaction.user} 가 부여")
        except discord.Forbidden:
            await interaction.response.send_message("권한이 부족해서 부여하지 못했어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {멤버.mention} 님에게 **{역할.name}** 역할을 부여했어요.", ephemeral=True
        )

    @역할.command(name="회수", description="특정 멤버의 역할을 회수합니다")
    @app_commands.describe(멤버="역할을 뺄 멤버", 역할="회수할 역할")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def take(self, interaction: discord.Interaction, 멤버: discord.Member, 역할: discord.Role):
        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래라 회수할 수 없어요. 봇 역할을 위로 올려주세요.",
                ephemeral=True,
            )
            return
        if 역할 not in 멤버.roles:
            await interaction.response.send_message(
                f"{멤버.display_name} 님은 **{역할.name}** 역할이 없어요.", ephemeral=True
            )
            return
        try:
            await 멤버.remove_roles(역할, reason=f"{interaction.user} 가 회수")
        except discord.Forbidden:
            await interaction.response.send_message("권한이 부족해서 회수하지 못했어요.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {멤버.mention} 님의 **{역할.name}** 역할을 회수했어요.", ephemeral=True
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "이 명령어는 '역할 관리' 권한이 있는 사람만 사용할 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
