"""
환영/퇴장 기능 (cogs/welcome.py) — 1단계

- 새 멤버 입장 시: 환영 메시지(임베드) 자동 전송
- 멤버 퇴장 시: 퇴장 로그 메시지 전송

메시지가 나가는 채널은 서버의 '시스템 메시지 채널'입니다.
  설정 위치: 디스코드 → 서버 설정 → 개요(Overview) → 시스템 메시지 채널
시스템 채널이 없으면, 봇이 글을 쓸 수 있는 첫 번째 텍스트 채널로 보냅니다.
"""

import discord
from discord import app_commands
from discord.ext import commands


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    환영 = app_commands.Group(
        name="환영",
        description="환영 메시지 설정 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def build_welcome_embed(self, member: discord.Member) -> discord.Embed:
        """환영 임베드를 만든다 (실제 입장/미리보기에서 공통 사용)."""
        embed = discord.Embed(
            title="🎉 환영합니다!",
            description=f"{member.mention} 님, **{member.guild.name}** 서버에 오신 걸 환영해요!",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="시작하기",
            value="규칙을 확인하고 자유롭게 인사해주세요 😊",
            inline=False,
        )
        embed.set_footer(text=f"현재 멤버 수: {member.guild.member_count}명")
        return embed

    def find_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        """메시지를 보낼 채널을 찾는다: 시스템 채널 우선, 없으면 쓸 수 있는 첫 채널."""
        channel = guild.system_channel
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                return ch
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = self.find_channel(member.guild)
        if channel is None:
            return
        await channel.send(embed=self.build_welcome_embed(member))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = self.find_channel(member.guild)
        if channel is None:
            return
        await channel.send(f"👋 **{member.display_name}** 님이 서버를 떠났습니다.")

    @환영.command(name="미리보기", description="환영 메시지가 어떻게 보이는지 미리 확인합니다")
    async def preview(self, interaction: discord.Interaction):
        # 명령어를 쓴 사람을 대상으로 환영 임베드를 보여준다 (나만 보임)
        embed = self.build_welcome_embed(interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# 봇이 이 파일을 불러올 때 호출하는 필수 함수
async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
