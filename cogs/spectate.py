"""
관전 모드 버튼 (cogs/spectate.py) — 4단계 C

명령어 그룹 /관전 (관리자 전용, 목록에서 숨김):
  /관전 패널   관전 모드 버튼 패널을 올림

버튼:
  [관전 적용] → 서버 닉네임 앞에 '[관전] ' 붙임
  [원래대로]  → '[관전] ' 떼고 원래 닉네임 복원
버튼은 영구(persistent) View 라 재시작 후에도 작동. (서버 주인 닉네임은 디스코드 규칙상 변경 불가)
"""

import discord
from discord import app_commands
from discord.ext import commands

PREFIX = "[관전] "


class SpectateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="관전 적용", style=discord.ButtonStyle.primary, custom_id="spectate:apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        current = member.display_name
        if current.startswith(PREFIX):
            await interaction.response.send_message("이미 관전 상태예요.", ephemeral=True)
            return
        new_nick = (PREFIX + current)[:32]
        try:
            await member.edit(nick=new_nick, reason="관전 모드 적용")
        except discord.Forbidden:
            await interaction.response.send_message(
                "닉네임을 바꿀 권한이 없어요. (서버 주인이거나, 봇보다 높은 역할이면 변경 불가)",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f"✅ 관전 모드 적용: **{new_nick}**", ephemeral=True)

    @discord.ui.button(label="원래대로", style=discord.ButtonStyle.secondary, custom_id="spectate:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        current = member.display_name
        if not current.startswith(PREFIX):
            await interaction.response.send_message("관전 상태가 아니에요.", ephemeral=True)
            return
        base = current[len(PREFIX):]
        new_nick = None if base in (member.name, member.global_name) else base
        try:
            await member.edit(nick=new_nick, reason="관전 모드 해제")
        except discord.Forbidden:
            await interaction.response.send_message(
                "닉네임을 바꿀 권한이 없어요. (서버 주인이거나, 봇보다 높은 역할이면 변경 불가)",
                ephemeral=True,
            )
            return
        await interaction.response.send_message("✅ 원래 닉네임으로 복원했어요.", ephemeral=True)


class Spectate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    관전 = app_commands.Group(
        name="관전",
        description="관전 모드 설정 (관리자)",
        default_permissions=discord.Permissions(manage_nicknames=True),
    )

    @관전.command(name="패널", description="관전 모드 버튼 패널을 올립니다")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏷️ 관전 모드",
            description="아래 버튼을 눌러 닉네임 앞에 `[관전]` 을 붙이거나 뗄 수 있어요.",
            color=discord.Color.dark_grey(),
        )
        embed.add_field(name="관전 적용", value="`[관전] 닉네임` 형태로 변경", inline=False)
        embed.add_field(name="원래대로", value="원래 닉네임으로 복원", inline=False)
        await interaction.channel.send(embed=embed, view=SpectateView())
        await interaction.response.send_message("✅ 관전 패널을 올렸어요.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "이 명령어는 '닉네임 관리' 권한이 있는 사람만 쓸 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Spectate(bot))
    bot.add_view(SpectateView())
