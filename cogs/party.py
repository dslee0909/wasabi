"""
게임 파티 모집 (cogs/party.py) — 4단계 B

흐름:
  1) 관리자가 /모집채널설정 으로 '구인구직 채널'을 지정
  2) 그 채널에서 '@역할' 멘션으로 시작하는 글이 올라오면
     → 봇이 그 글에 스레드를 자동 생성
  3) 스레드에 안내 + [참여] 버튼 게시
  4) [참여] 버튼 클릭 → '✋ {닉네임} 참여!' 를 스레드에 자동 게시

'@역할로 시작' 판별: 역할 멘션은 원문에서 '<@&역할ID>' 형태 → content 가 '<@&' 로 시작하는지 확인.
[참여] 버튼은 영구(persistent) View 라 재시작 후에도 작동합니다.
"""

import discord
from discord import app_commands
from discord.ext import commands

from store import get_guild_config, update_guild_config

# 채널별 웹훅 캐시 (매번 새로 만들지 않도록)
_webhook_cache: dict[int, discord.Webhook] = {}

# 참여 메시지 추적: {스레드ID: {유저ID: [메시지ID, ...]}} — 취소(삭제)에 사용
# 메모리 저장이라 봇 재시작 시 초기화됨 (파티 스레드는 단기라 실용상 충분)
_participants: dict[int, dict[int, list[int]]] = {}


async def get_party_webhook(channel: discord.TextChannel):
    """구인구직 채널의 파티모집용 웹훅을 가져오거나 만든다. 실패 시 None."""
    if channel.id in _webhook_cache:
        return _webhook_cache[channel.id]
    try:
        hooks = await channel.webhooks()
    except discord.Forbidden:
        return None
    hook = discord.utils.get(hooks, name="파티모집")
    if hook is None:
        try:
            hook = await channel.create_webhook(name="파티모집")
        except discord.HTTPException:
            return None
    _webhook_cache[channel.id] = hook
    return hook


class PartyJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 영구 버튼

    @discord.ui.button(label="참여", emoji="✋", style=discord.ButtonStyle.success, custom_id="party:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        thread = interaction.channel
        parent = thread.parent if isinstance(thread, discord.Thread) else thread

        # 웹훅으로 '본인이 친 것처럼'(닉네임+아바타) 게시
        webhook = await get_party_webhook(parent)
        if webhook is not None:
            await interaction.response.defer()  # 버튼 클릭 조용히 확인
            msg = await webhook.send(
                content="참여합니다! ✋",
                username=member.display_name,
                avatar_url=member.display_avatar.url,
                thread=thread,
                wait=True,  # 보낸 메시지 정보를 받아 ID를 기록 (취소용)
            )
            _participants.setdefault(thread.id, {}).setdefault(member.id, []).append(msg.id)
            return

        # 폴백: 웹훅이 안 되면 아바타가 들어간 임베드로
        embed = discord.Embed(description="참여합니다! ✋", color=discord.Color.green())
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="취소", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="party:cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        thread = interaction.channel
        parent = thread.parent if isinstance(thread, discord.Thread) else thread

        msg_ids = _participants.get(thread.id, {}).get(member.id, [])
        if not msg_ids:
            await interaction.response.send_message(
                "취소할 참여 기록이 없어요. (봇이 재시작됐다면 기록이 초기화됐을 수 있어요)",
                ephemeral=True,
            )
            return

        webhook = await get_party_webhook(parent)
        deleted = 0
        for mid in list(msg_ids):
            try:
                await webhook.delete_message(mid, thread=thread)
                deleted += 1
            except discord.HTTPException:
                pass
        _participants[thread.id][member.id] = []
        await interaction.response.send_message(f"참여를 취소했어요. (메시지 {deleted}건 삭제)", ephemeral=True)


class Party(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    파티 = app_commands.Group(
        name="파티",
        description="파티 모집 설정 (관리자)",
        default_permissions=discord.Permissions(manage_channels=True),
    )

    # ---- 구인구직 채널 글 감지 ----
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        cfg = get_guild_config(message.guild.id)
        recruit_id = cfg.get("party_recruit_channel_id")
        # 지정된 구인구직 채널의 글이 아니면 무시
        if not recruit_id or message.channel.id != recruit_id:
            return
        # '@역할' 멘션으로 시작하는 글만 모집글로 인정
        if not (message.content.strip().startswith("<@&") and message.role_mentions):
            return

        role = message.role_mentions[0]
        try:
            thread = await message.create_thread(
                name=f"🎮 {role.name} 파티 모집",
                auto_archive_duration=1440,  # 24시간 후 자동 보관
            )
        except discord.HTTPException:
            return

        embed = discord.Embed(
            title="🎮 파티 모집 중!",
            description=f"{message.author.mention} 님이 **{role.name}** 파티를 모집해요.\n"
                        f"아래 **참여** 버튼을 눌러 참가하세요!",
            color=discord.Color.green(),
        )
        await thread.send(embed=embed, view=PartyJoinView())

    # ---- /파티 채널설정 · 채널해제 ----
    @파티.command(name="채널설정", description="이 채널(또는 지정 채널)을 파티 구인구직 채널로 설정합니다")
    @app_commands.describe(채널="구인구직으로 쓸 텍스트 채널 (비우면 현재 채널)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def set_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel = None):
        channel = 채널 or interaction.channel
        update_guild_config(interaction.guild.id, {"party_recruit_channel_id": channel.id})
        await interaction.response.send_message(
            f"✅ **{channel.mention}** 을(를) 파티 구인구직 채널로 설정했어요.\n"
            f"이제 이 채널에서 **@역할** 멘션으로 시작하는 글을 올리면 모집 스레드가 자동 생성돼요.",
            ephemeral=True,
        )

    @파티.command(name="채널해제", description="파티 구인구직 채널 설정을 해제합니다")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def clear_channel(self, interaction: discord.Interaction):
        update_guild_config(interaction.guild.id, {"party_recruit_channel_id": None})
        await interaction.response.send_message("✅ 파티 구인구직 채널 설정을 해제했어요.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "이 명령어는 '채널 관리' 권한이 있는 사람만 쓸 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Party(bot))
    bot.add_view(PartyJoinView())  # 영구 버튼 등록
