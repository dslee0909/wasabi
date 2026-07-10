"""
임시 음성채널 (cogs/tempvoice.py) — 4단계 A (Join-to-Create)

명령어 그룹 /음성 (관리자 전용, 목록에서 숨김):
  /음성 생성   '방 만들기' 채널+카테고리+안내 자동 생성 (여러 개 만들 수 있음)
  /음성 지정   기존 음성채널을 '방 만들기' 트리거로 추가
  /음성 목록   현재 '방 만들기' 채널 목록 보기
  /음성 해제   임시 음성채널 기능 전부 끄기

여러 '방 만들기' 채널을 동시에 트리거로 쓸 수 있음 (temp_voice_triggers 목록).
동작: 트리거 채널 입장 → 개인 방 자동 생성 후 이동 / 방이 비면 자동 삭제
필요 권한: 봇에게 '채널 관리' + '멤버 이동'
"""

import discord
from discord import app_commands
from discord.ext import commands

from store import get_guild_config, update_guild_config


def _trigger_ids(cfg) -> list[int]:
    """현재 트리거 채널 ID 목록 (구버전 단일 trigger_id 도 호환)."""
    ids = list(cfg.get("temp_voice_triggers", []))
    legacy = cfg.get("temp_voice_trigger_id")
    if legacy and legacy not in ids:
        ids.append(legacy)
    return ids


class TempVoice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    음성 = app_commands.Group(
        name="음성",
        description="임시 음성채널 설정 (관리자)",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    # 봇 시작 시: 비어 있는 임시 방 정리
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            cfg = get_guild_config(guild.id)
            temp_ids = cfg.get("temp_voice_channels", [])
            if not temp_ids:
                continue
            remaining = []
            for cid in temp_ids:
                channel = guild.get_channel(cid)
                if channel is None:
                    continue
                if len(channel.members) == 0:
                    try:
                        await channel.delete(reason="임시 음성채널 정리")
                    except discord.HTTPException:
                        remaining.append(cid)
                else:
                    remaining.append(cid)
            update_guild_config(guild.id, {"temp_voice_channels": remaining})

    # 음성채널 입퇴장 감지
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        cfg = get_guild_config(member.guild.id)
        triggers = _trigger_ids(cfg)
        temp_ids = list(cfg.get("temp_voice_channels", []))

        # (1) 어떤 트리거든 입장하면 → 개인 방 생성 후 이동
        if after.channel and after.channel.id in triggers:
            try:
                new_channel = await member.guild.create_voice_channel(
                    name=f"🔊 {member.display_name}의 방",
                    category=after.channel.category,
                    reason="임시 음성채널 생성",
                )
                await member.move_to(new_channel)
                await new_channel.set_permissions(member, manage_channels=True, move_members=True)
                temp_ids.append(new_channel.id)
                changes = {"temp_voice_channels": temp_ids}
                # 그 트리거가 레벨 집계 제외 채널이면, 생성된 방도 제외 목록에 상속
                excluded = cfg.get("leveling_excluded_channels", [])
                if after.channel.id in excluded and new_channel.id not in excluded:
                    changes["leveling_excluded_channels"] = excluded + [new_channel.id]
                update_guild_config(member.guild.id, changes)
            except discord.Forbidden:
                print(f"[경고] 임시 음성채널 생성 실패(권한 부족): {member.guild.name}")

        # (2) 임시 방에서 나감 → 비었으면 삭제
        if before.channel and before.channel.id in temp_ids:
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="임시 음성채널 비어서 삭제")
                except discord.NotFound:
                    pass
                temp_ids = [c for c in temp_ids if c != before.channel.id]
                changes = {"temp_voice_channels": temp_ids}
                excluded = cfg.get("leveling_excluded_channels", [])
                if before.channel.id in excluded:
                    changes["leveling_excluded_channels"] = [c for c in excluded if c != before.channel.id]
                update_guild_config(member.guild.id, changes)

    # ---- /음성 생성 · 지정 · 목록 · 해제 ----
    @음성.command(name="생성", description="'방 만들기' 채널·카테고리·안내를 새로 만듭니다 (여러 개 가능)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def create(self, interaction: discord.Interaction):
        guild = interaction.guild
        try:
            category = await guild.create_category("🔊 음성 채널")
            guide = await guild.create_text_channel("📖-사용법", category=category)
            trigger = await guild.create_voice_channel("➕ 방 만들기", category=category)
        except discord.Forbidden:
            await interaction.response.send_message("채널을 만들 권한이 없어요.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔊 임시 음성채널 사용법",
            description=f"**{trigger.mention}** 채널에 들어가면 나만의 음성방이 자동으로 생겨요!",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="1️⃣ 방 만들기", value=f"**{trigger.name}** 에 입장하면 개인 방이 생기고 그리로 이동돼요.", inline=False)
        embed.add_field(name="2️⃣ 방장 권한", value="내 방의 이름 변경·인원 제한은 채널 옆 ⚙️(설정)에서 할 수 있어요.", inline=False)
        embed.add_field(name="3️⃣ 자동 삭제", value="방에 아무도 없으면 자동으로 사라져요.", inline=False)
        await guide.send(embed=embed)

        cfg = get_guild_config(guild.id)
        ids = _trigger_ids(cfg)
        if trigger.id not in ids:
            ids.append(trigger.id)
        update_guild_config(guild.id, {"temp_voice_triggers": ids, "temp_voice_trigger_id": None})
        await interaction.response.send_message(
            f"✅ **{trigger.name}** 채널을 만들었어요. (현재 방 만들기 채널 {len(ids)}개, 전부 작동)",
            ephemeral=True,
        )

    @음성.command(name="지정", description="기존 음성채널을 '방 만들기' 트리거로 추가합니다")
    @app_commands.describe(채널="트리거로 추가할 음성채널")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def assign(self, interaction: discord.Interaction, 채널: discord.VoiceChannel):
        cfg = get_guild_config(interaction.guild.id)
        ids = _trigger_ids(cfg)
        if 채널.id in ids:
            await interaction.response.send_message(f"**{채널.name}** 은(는) 이미 트리거예요.", ephemeral=True)
            return
        ids.append(채널.id)
        update_guild_config(interaction.guild.id, {"temp_voice_triggers": ids, "temp_voice_trigger_id": None})
        await interaction.response.send_message(
            f"✅ **{채널.name}** 을(를) '방 만들기' 채널로 추가했어요. (현재 {len(ids)}개)", ephemeral=True
        )

    @음성.command(name="목록", description="현재 '방 만들기' 트리거 채널 목록을 봅니다")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def list_triggers(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild.id)
        ids = _trigger_ids(cfg)
        lines = []
        for cid in ids:
            ch = interaction.guild.get_channel(cid)
            lines.append(f"• {ch.mention}" if ch else f"• (삭제된 채널 {cid})")
        if not lines:
            await interaction.response.send_message("지정된 '방 만들기' 채널이 없어요. `/음성 생성` 이나 `/음성 지정` 을 써보세요.", ephemeral=True)
        else:
            await interaction.response.send_message("🔊 방 만들기 채널 목록:\n" + "\n".join(lines), ephemeral=True)

    @음성.command(name="해제", description="임시 음성채널 기능을 전부 끕니다")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def clear(self, interaction: discord.Interaction):
        update_guild_config(interaction.guild.id, {"temp_voice_triggers": [], "temp_voice_trigger_id": None})
        await interaction.response.send_message("✅ 임시 음성채널 기능을 전부 껐어요.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "이 명령어는 '채널 관리' 권한이 있는 사람만 쓸 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoice(bot))
