"""
활동시간 레벨 (cogs/leveling.py) — 4단계 D (레벨 부분)

역할:
  - 음성채널 접속 시간을 추적해 DB(data.db)에 기록 (이 봇의 '음성시간 추적기')
  - '전체 누적시간' 기준 레벨을 보여줌 → 레벨은 영구(절대 안 내려감)

집계 규칙: 음성 접속 시간만 집계. 아래는 미집계 (voicetime.countable):
  · 마이크를 끈(음소거) 상태  · '[관전] ' 접두사 닉네임  · 제외 채널  · 봇

명령어:
  /레벨 [멤버]        레벨·누적시간·최근활동 보기
  /레벨순위          전체 누적(레벨) 순위 TOP 10
  /레벨제외채널추가   이 채널은 시간 집계에서 제외 (관리자)
  /레벨제외채널제거   제외 해제 (관리자)

승급·잠수 관리는 별도 모듈(cogs/activity.py)에서 담당합니다. (같은 음성시간 데이터 공유)
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

import voicetime as vt
from store import get_guild_config, update_guild_config


def bot_owner_only():
    """봇 소유자만 통과 (서버 소유자는 불가 — economy.owner_only 와 다름)."""
    async def predicate(interaction: discord.Interaction) -> bool:
        return await interaction.client.is_owner(interaction.user)
    return app_commands.check(predicate)


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 진행 중인 세션: {(guild_id, user_id): (시작시각, 채널ID)}
        self.active: dict[tuple[int, int], tuple[float, int]] = {}

    def cog_unload(self):
        # 종료(재시작) 시 진행 중이던 음성 세션을 모두 저장한다.
        # 이게 없으면 재시작마다 그 순간 음성 중이던 사람의 '진행 중 시간'이 유실된다.
        # (close() 가 remove_cog 로 이 함수를 부른다 — SIGINT 종료여야 close() 가 불린다)
        now = time.time()
        saved = 0
        for (gid, uid), (start, channel_id) in list(self.active.items()):
            seconds = int(now - start)
            if seconds > 0:
                vt.add_session(gid, uid, seconds, channel_id=channel_id, started_at=start)
                saved += 1
        self.active.clear()
        if saved:
            print(f"[레벨] 종료 전 진행 중 음성 세션 {saved}건 저장 완료")

    # 레벨 시스템 관리 그룹 (관리자 전용, 목록에서 숨김)
    레벨설정 = app_commands.Group(
        name="레벨설정",
        description="레벨 시스템 관리 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ---- 세션 시작/종료 ----
    def _start(self, member: discord.Member, channel):
        key = (member.guild.id, member.id)
        if key not in self.active:
            # (시작시각, 채널ID) 저장 — 채널ID는 케미/골든타임 분석에 사용
            self.active[key] = (time.time(), channel.id)

    def _stop(self, member: discord.Member):
        key = (member.guild.id, member.id)
        info = self.active.pop(key, None)
        if info is None:
            return
        start, channel_id = info
        seconds = int(time.time() - start)
        if seconds > 0:
            vt.add_session(member.guild.id, member.id, seconds, channel_id=channel_id, started_at=start)

    def _sync(self, member: discord.Member, channel):
        """현재 상태에 맞춰 세션을 시작하거나 종료한다."""
        if vt.countable(member, channel):
            self._start(member, channel)
        else:
            self._stop(member)

    def _ongoing(self, guild_id: int, user_id: int) -> int:
        key = (guild_id, user_id)
        return int(time.time() - self.active[key][0]) if key in self.active else 0

    # ---- 이벤트 (음성시간 추적) ----
    @commands.Cog.listener()
    async def on_ready(self):
        # 봇 시작 시, 이미 음성채널에 있는 멤버들의 세션을 시작
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot and vt.countable(member, channel):
                        self._start(member, channel)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 채널 이동뿐 아니라 마이크 음소거 토글도 이 이벤트로 온다.
        # 매번 _sync 를 다시 돌려서, 마이크를 끄면 세션이 멈추고 켜면 다시 시작된다.
        if member.bot:
            return
        self._sync(member, after.channel)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # 닉네임(관전 접두사)이 바뀌면, 음성 중일 때 집계 상태를 다시 맞춘다
        if after.bot or before.display_name == after.display_name:
            return
        if after.voice and after.voice.channel:
            self._sync(after, after.voice.channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 메시지 수집 (스탯 카드의 메시지 통계·순위용)
        if message.author.bot or message.guild is None:
            return
        vt.add_message(message.guild.id, message.author.id, message.channel.id)

    # ---- 명령어 ----
    @app_commands.command(name="레벨", description="내 스탯 카드(레벨·음성·메시지·순위)를 봅니다")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def level(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        gid = interaction.guild.id
        ongoing = self._ongoing(gid, member.id)

        # 레벨(영구, 전체 누적)
        total = vt.total_seconds(gid, member.id) + ongoing
        level = vt.hours_to_level(total / 3600, gid)
        remain = max(0, vt.level_to_hours(level + 1, gid) * 3600 - total)

        # 음성 활동 1/7/30일 (진행 중 세션 포함)
        v1 = vt.voice_seconds_days(gid, member.id, 1) + ongoing
        v7 = vt.voice_seconds_days(gid, member.id, 7) + ongoing
        v30 = vt.voice_seconds_days(gid, member.id, 30) + ongoing

        # 메시지 1/7/30일
        m1 = vt.message_count_days(gid, member.id, 1)
        m7 = vt.message_count_days(gid, member.id, 7)
        m30 = vt.message_count_days(gid, member.id, 30)

        # 순위 (최근 30일 기준)
        vrank, _ = vt.voice_rank(gid, member.id)
        mrank, _ = vt.message_rank(gid, member.id)
        rank_str = lambda r: f"#{r}" if r else "—"
        fd = vt.format_duration

        embed = discord.Embed(title=f"📊 {member.display_name} 님의 스탯", color=discord.Color.gold())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="레벨", value=f"**Lv. {level}**", inline=True)
        embed.add_field(name="🔊 음성 순위", value=rank_str(vrank), inline=True)
        embed.add_field(name="💬 메시지 순위", value=rank_str(mrank), inline=True)
        embed.add_field(
            name="🔊 음성 활동",
            value=f"`1일`  {fd(v1)}\n`7일`  {fd(v7)}\n`30일` {fd(v30)}",
            inline=True,
        )
        embed.add_field(
            name="💬 메시지",
            value=f"`1일`  {m1}회\n`7일`  {m7}회\n`30일` {m30}회",
            inline=True,
        )
        embed.add_field(
            name="📈 누적",
            value=f"총 {fd(total)}\n다음 레벨까지 {fd(remain)}",
            inline=False,
        )
        if vt.is_spectating(member):
            embed.set_footer(text="현재 [관전] 상태 — 음성 시간이 집계되지 않아요")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="레벨순위", description="전체 누적 음성 시간(레벨) 순위 TOP 10")
    async def leaderboard(self, interaction: discord.Interaction):
        conn = vt.db()
        rows = conn.execute(
            "SELECT user_id, SUM(seconds) AS total FROM voice_sessions "
            "WHERE guild_id=? GROUP BY user_id ORDER BY total DESC LIMIT 10",
            (interaction.guild.id,),
        ).fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("아직 집계된 활동이 없어요.", ephemeral=True)
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, total) in enumerate(rows):
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"(나간 유저 {user_id})"
            rank = medals[i] if i < 3 else f"{i + 1}."
            lv = vt.hours_to_level(total / 3600, interaction.guild.id)
            lines.append(f"{rank} **{name}** — Lv.{lv} ({vt.format_duration(total)})")

        embed = discord.Embed(
            title="🏆 레벨 순위 (전체 누적)",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @레벨설정.command(name="제외추가", description="이 음성채널을 시간 집계에서 제외합니다")
    @app_commands.describe(채널="집계에서 제외할 음성채널")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add_excluded(self, interaction: discord.Interaction, 채널: discord.VoiceChannel):
        cfg = get_guild_config(interaction.guild.id)
        excluded = cfg.get("leveling_excluded_channels", [])
        if 채널.id not in excluded:
            excluded.append(채널.id)
            update_guild_config(interaction.guild.id, {"leveling_excluded_channels": excluded})
        await interaction.response.send_message(f"✅ **{채널.name}** 은(는) 이제 시간 집계에서 제외돼요.", ephemeral=True)

    @레벨설정.command(name="제외해제", description="채널 집계 제외를 해제합니다")
    @app_commands.describe(채널="다시 집계할 음성채널")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_excluded(self, interaction: discord.Interaction, 채널: discord.VoiceChannel):
        cfg = get_guild_config(interaction.guild.id)
        excluded = [c for c in cfg.get("leveling_excluded_channels", []) if c != 채널.id]
        update_guild_config(interaction.guild.id, {"leveling_excluded_channels": excluded})
        await interaction.response.send_message(f"✅ **{채널.name}** 을(를) 다시 집계해요.", ephemeral=True)

    @레벨설정.command(name="제외목록", description="시간 집계에서 제외된 음성채널을 모두 봅니다")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_excluded(self, interaction: discord.Interaction):
        guild = interaction.guild
        excluded = get_guild_config(guild.id).get("leveling_excluded_channels", [])

        lines, stale = [], 0
        for cid in excluded:
            ch = guild.get_channel(cid)
            if ch is None:
                # 봇이 없는 사이 채널이 삭제되면 ID만 남는다 (제외해제로 정리 가능)
                lines.append(f"⚠️ 삭제된 채널 (`{cid}`)")
                stale += 1
            else:
                lines.append(f"🔇 {ch.mention}")

        body = "\n".join(lines) if lines else "제외된 채널이 없어요. 모든 음성채널이 집계돼요."
        embed = discord.Embed(
            title="🔇 음성 시간 집계 제외 채널",
            description=body,
            color=discord.Color.orange(),
        )
        # 채널 제외 외에 항상 적용되는 규칙도 함께 안내
        embed.add_field(
            name="이 채널들은 명령어와 무관하게 항상 제외",
            value=f"닉네임이 `{vt.SPECTATE_PREFIX.strip()}` 로 시작하는 관전 멤버",
            inline=False,
        )
        if stale:
            embed.set_footer(text=f"삭제된 채널 {stale}개 — /레벨설정 제외해제 로 정리할 수 있어요.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @레벨설정.command(name="곡선", description="레벨업 곡선을 조정합니다 (선형/비선형, 속도)")
    @app_commands.describe(
        기준시간="Lv.1 도달에 필요한 시간(시간). 작을수록 전체가 빨라짐 (기본 1)",
        곡선="1=선형(균일 간격), 2=기본, 클수록 고레벨이 더 귀해짐 (기본 2)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_level_curve(self, interaction: discord.Interaction, 기준시간: float = 1.0, 곡선: float = 2.0):
        if 기준시간 <= 0 or 곡선 <= 0:
            await interaction.response.send_message("기준시간과 곡선은 0보다 커야 해요.", ephemeral=True)
            return
        gid = interaction.guild.id
        update_guild_config(gid, {"level_base_hours": 기준시간, "level_exponent": 곡선})
        # 바뀐 곡선으로 예시 표를 만들어 보여주기
        preview = "\n".join(
            f"Lv.{n} = {vt.format_duration(vt.level_to_hours(n, gid) * 3600)}"
            for n in (1, 2, 3, 5, 10)
        )
        embed = discord.Embed(
            title="✅ 레벨 곡선 변경됨",
            description=f"기준시간 **{기준시간}h**, 곡선 **{곡선}**\n\n{preview}",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @레벨설정.command(name="시간조정", description="특정 멤버의 누적 음성 시간을 더하거나 뺍니다 (봇 소유자)")
    @app_commands.describe(멤버="대상 멤버", 시간="더할 시간(시간 단위, 음수면 차감). 예: 1.5=1시간30분")
    @bot_owner_only()
    async def adjust_time(self, interaction: discord.Interaction, 멤버: discord.Member, 시간: float):
        gid, uid = interaction.guild.id, 멤버.id
        seconds = int(시간 * 3600)
        current = vt.total_seconds(gid, uid)
        if seconds < 0 and -seconds > current:
            seconds = -current  # 총합이 음수가 되지 않게 클램프
        # 보정용 세션: channel_id·started_at 없이 넣어 듀오/골든타임 분석은 오염시키지 않고
        # 누적(레벨)·최근시간에만 반영한다.
        vt.add_session(gid, uid, seconds)
        new_total = vt.total_seconds(gid, uid)
        new_level = vt.hours_to_level(new_total / 3600, gid)
        sign = "+" if seconds >= 0 else ""
        await interaction.response.send_message(
            f"✅ {멤버.mention} 의 음성 시간을 **{sign}{seconds/3600:.2f}시간** 조정했어요.\n"
            f"누적: **{vt.format_duration(new_total)}** · **Lv.{new_level}**\n"
            f"(레벨10 넘으면 자동 역할·정착 판정은 잠시 후 반영돼요)",
            ephemeral=True,
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("관리자 권한이 필요한 명령어예요.", ephemeral=True)
        elif isinstance(error, app_commands.CheckFailure):
            # bot_owner_only 가 막은 경우 (MissingPermissions 는 위에서 먼저 처리됨)
            await interaction.response.send_message("이 명령은 **봇 소유자**만 쓸 수 있어요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
