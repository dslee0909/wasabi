"""
게임 파티 모집 (cogs/party.py) — 4단계 B

흐름:
  1) 관리자가 /모집채널설정 으로 '구인구직 채널'을 지정
  2) 그 채널에서 '@역할' 멘션으로 시작하는 글이 올라오면
     → 봇이 그 글에 스레드를 자동 생성
  3) 스레드에 안내 + [참여][취소][쫑] 버튼 게시
  4) [참여] → 본인 이름·아바타로 참여 메시지 게시 / [취소] → 그 메시지 삭제
     [쫑] → 참여한 사람만, 본인 이름으로 '쫑' 메시지 게시. 다시 누르면 토글로 삭제.

모집글 판별: 글이 '역할을 멘션했는지'(message.role_mentions)로만 본다.
이 정보는 게이트웨이 페이로드에서 오므로 message_content 인텐트(글 내용 읽기) 없이도 동작.
버튼은 영구(persistent) View 라 재시작 후에도 작동합니다(단, 참여/쫑 추적은 메모리라 초기화됨).
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

# 쫑 메시지 추적: {스레드ID: {유저ID: 메시지ID}} — 토글(다시 누르면 삭제)에 사용
_jjong_msgs: dict[int, dict[int, int]] = {}


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
        # 참여 취소 시 걸어둔 쫑도 같이 정리 (고아 메시지 방지)
        jjong_id = _jjong_msgs.get(thread.id, {}).pop(member.id, None)
        if jjong_id:
            try:
                await webhook.delete_message(jjong_id, thread=thread)
            except discord.HTTPException:
                pass
        await interaction.response.send_message(f"참여를 취소했어요. (메시지 {deleted}건 삭제)", ephemeral=True)

    @discord.ui.button(label="쫑", emoji="🔚", style=discord.ButtonStyle.primary, custom_id="party:jjong")
    async def jjong(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        thread = interaction.channel
        parent = thread.parent if isinstance(thread, discord.Thread) else thread

        # 참여한 사람만 쫑 가능 (취소했거나 참여 기록이 없으면 불가)
        if not _participants.get(thread.id, {}).get(member.id):
            await interaction.response.send_message(
                "참여한 사람만 **쫑** 할 수 있어요. 먼저 **참여** 버튼을 눌러주세요.", ephemeral=True
            )
            return

        webhook = await get_party_webhook(parent)
        if webhook is None:
            await interaction.response.send_message("지금은 쫑 기능을 쓸 수 없어요.", ephemeral=True)
            return

        existing = _jjong_msgs.get(thread.id, {}).get(member.id)
        if existing:
            # 토글 오프: 쫑 메시지 삭제
            try:
                await webhook.delete_message(existing, thread=thread)
            except discord.HTTPException:
                pass
            _jjong_msgs[thread.id].pop(member.id, None)
            await interaction.response.send_message("쫑을 취소했어요.", ephemeral=True)
        else:
            # 토글 온: 쫑 메시지 게시 (본인 이름·아바타로)
            await interaction.response.defer()
            msg = await webhook.send(
                content="쫑이요! 🔚",
                username=member.display_name,
                avatar_url=member.display_avatar.url,
                thread=thread,
                wait=True,
            )
            _jjong_msgs.setdefault(thread.id, {})[member.id] = msg.id


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
        # 역할을 멘션한 글만 모집글로 인정.
        # role_mentions 는 게이트웨이 페이로드(mention_roles)에서 오므로
        # message_content 인텐트 없이도 채워진다 → 글 내용을 읽지 않아도 된다.
        if not message.role_mentions:
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
