"""
이모지로 역할 받기 (cogs/reactionroles.py) — 2단계 ②

명령어 그룹 /반응역할 (관리자 전용, 목록에서 숨김):
  /반응역할 패널   이모지로 역할받는 선택판 생성
  /반응역할 추가   이 채널 최신 선택판에 이모지↔역할 연결

멤버가 선택판의 이모지를 클릭하면 역할 부여, 떼면 회수. (봇 재시작해도 config.json 으로 동작)
"""

import discord
from discord import app_commands
from discord.ext import commands

from store import get_guild_config, update_guild_config


def build_panel_embed(title: str, description: str, options: list[dict]) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    if options:
        lines = [f"{opt['emoji']}  →  **{opt['label']}**" for opt in options]
        embed.add_field(name="역할 목록", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="역할 목록", value="(아직 없음 — /반응역할 추가 로 추가하세요)", inline=False)
    embed.set_footer(text="원하는 이모지를 눌러 역할을 받으세요")
    return embed


class ReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    반응역할 = app_commands.Group(
        name="반응역할",
        description="이모지로 역할 받기 설정 (관리자)",
        default_permissions=discord.Permissions(manage_roles=True),
    )

    # ---- /반응역할 패널 ----
    @반응역할.command(name="패널", description="이모지로 역할을 받는 선택판을 만듭니다")
    @app_commands.describe(제목="선택판 제목", 설명="선택판 설명")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def panel(self, interaction: discord.Interaction, 제목: str, 설명: str = "아래 이모지를 눌러 역할을 받으세요."):
        embed = build_panel_embed(제목, 설명, [])
        message = await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            "✅ 선택판을 만들었어요! 이제 `/반응역할 추가` 로 이모지를 추가하세요.", ephemeral=True
        )

        cfg = get_guild_config(interaction.guild.id)
        panels = cfg.get("reaction_panels", {})
        panels[str(message.id)] = {
            "channel_id": interaction.channel.id,
            "title": 제목,
            "description": 설명,
            "options": [],
        }
        active = cfg.get("active_panel_by_channel", {})
        active[str(interaction.channel.id)] = str(message.id)
        update_guild_config(interaction.guild.id, {"reaction_panels": panels, "active_panel_by_channel": active})

    # ---- /반응역할 추가 ----
    @반응역할.command(name="추가", description="이 채널의 최신 선택판에 이모지↔역할을 추가합니다")
    @app_commands.describe(이모지="누를 이모지", 역할="부여할 역할", 라벨="역할 설명(표시용)")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def add(self, interaction: discord.Interaction, 이모지: str, 역할: discord.Role, 라벨: str = None):
        cfg = get_guild_config(interaction.guild.id)
        active = cfg.get("active_panel_by_channel", {})
        message_id = active.get(str(interaction.channel.id))
        panels = cfg.get("reaction_panels", {})
        if not message_id or message_id not in panels:
            await interaction.response.send_message(
                "이 채널에 선택판이 없어요. 먼저 `/반응역할 패널` 로 만들어주세요.", ephemeral=True
            )
            return

        if 역할 >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                f"⚠️ 제 역할이 **{역할.name}** 보다 아래라 부여할 수 없어요. 봇 역할을 위로 올려주세요.",
                ephemeral=True,
            )
            return

        panel = panels[message_id]
        channel = interaction.channel

        # 이모지 유효성 검사 (반응 달기는 '수정됨' 표시를 만들지 않음)
        try:
            old_message = await channel.fetch_message(int(message_id))
            await old_message.add_reaction(이모지)
        except discord.HTTPException:
            await interaction.response.send_message(
                "그 이모지는 쓸 수 없어요. 기본 이모지나 이 서버의 이모지를 사용해주세요.", ephemeral=True
            )
            return
        except (discord.NotFound, AttributeError):
            await interaction.response.send_message("선택판 메시지를 찾을 수 없어요. 새로 만들어주세요.", ephemeral=True)
            return

        label = 라벨 or 역할.name
        options = [o for o in panel["options"] if o["emoji"] != str(이모지)]
        options.append({"emoji": str(이모지), "role_id": 역할.id, "label": label})
        panel["options"] = options
        panel["channel_id"] = channel.id

        # '(수정됨)' 표시를 피하려고 편집 대신 재게시: 기존 메시지 삭제 → 새로 올림
        try:
            await old_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        new_message = await channel.send(
            embed=build_panel_embed(panel["title"], panel["description"], options)
        )
        for opt in options:
            try:
                await new_message.add_reaction(opt["emoji"])
            except discord.HTTPException:
                pass

        del panels[message_id]
        panels[str(new_message.id)] = panel
        active = cfg.get("active_panel_by_channel", {})
        active[str(channel.id)] = str(new_message.id)
        update_guild_config(
            interaction.guild.id,
            {"reaction_panels": panels, "active_panel_by_channel": active},
        )
        await interaction.response.send_message(f"✅ {이모지} → **{label}** 추가 완료!", ephemeral=True)

    # ---- 리액션 감지 (부여/회수) ----
    def _find_role_id(self, guild_id: int, message_id: int, emoji: str):
        cfg = get_guild_config(guild_id)
        panel = cfg.get("reaction_panels", {}).get(str(message_id))
        if not panel:
            return None
        for opt in panel["options"]:
            if opt["emoji"] == emoji:
                return opt["role_id"]
        return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        role_id = self._find_role_id(payload.guild_id, payload.message_id, str(payload.emoji))
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.add_roles(role, reason="리액션 역할")
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        role_id = self._find_role_id(payload.guild_id, payload.message_id, str(payload.emoji))
        if not role_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.remove_roles(role, reason="리액션 역할 해제")
            except discord.Forbidden:
                pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "이 명령어는 '역할 관리' 권한이 있는 사람만 쓸 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
