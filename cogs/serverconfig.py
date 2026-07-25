"""서버 설정 현황 (cogs/serverconfig.py)

/설정현황 — 이 서버에 저장된 모든 설정을 한 화면에 보여준다.
config.json 의 키들을 사람이 읽을 수 있게 풀어서, 어느 채널·역할이 어떤 설정인지
클릭 가능한 멘션으로 표시한다.

봇이 나갔다 들어와도 설정은 guild_id 기준으로 유지되지만, 그 사이 채널·역할이
삭제되면 저장된 ID 가 없는 대상을 가리킨다. 그런 항목은 ⚠️ 로 표시해 정리를 돕는다.
"""

import discord
from discord import app_commands
from discord.ext import commands

from store import get_guild_config


class ServerConfig(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- 저장된 ID 를 클릭 가능한 멘션으로, 없어졌으면 경고로 ----
    @staticmethod
    def _channel(guild: discord.Guild, cid) -> str:
        if not cid:
            return "—"
        ch = guild.get_channel(int(cid))
        return ch.mention if ch else f"⚠️ 삭제됨 (`{cid}`)"

    @staticmethod
    def _role(guild: discord.Guild, rid) -> str:
        if not rid:
            return "—"
        role = guild.get_role(int(rid))
        return role.mention if role else f"⚠️ 삭제됨 (`{rid}`)"

    @classmethod
    def _channel_list(cls, guild: discord.Guild, ids) -> str:
        if not ids:
            return "—"
        return "\n".join(cls._channel(guild, c) for c in ids)

    @app_commands.command(name="설정현황", description="이 서버에 저장된 모든 봇 설정을 봅니다")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = get_guild_config(guild.id)
        stale = {"n": 0}

        def mark(text: str) -> str:
            if "⚠️" in text:
                stale["n"] += text.count("⚠️")
            return text

        embed = discord.Embed(
            title=f"⚙️ {guild.name} 설정 현황",
            description="이 서버에 저장된 봇 설정이에요. 채널·역할을 누르면 바로 이동해요.",
            color=discord.Color.blurple(),
        )

        # ── 역할 ──
        auto = mark(self._role(guild, cfg.get("auto_role_id")))
        promo_role = cfg.get("promote_role_id")
        promo_lv = cfg.get("promote_level")
        promote = (f"Lv.{promo_lv} 도달 시 {mark(self._role(guild, promo_role))}"
                   if promo_role and promo_lv is not None else "—")
        panels = cfg.get("reaction_panels", {})
        active = cfg.get("active_panel_by_channel", {})  # {채널: 메시지}
        if panels:
            chans = "\n".join(self._channel(guild, c) for c in active) or "채널 정보 없음"
            panel_txt = f"{len(panels)}개 패널\n{chans}"
        else:
            panel_txt = "—"
        embed.add_field(name="👋 입장 자동역할", value=auto, inline=True)
        embed.add_field(name="⬆️ 레벨 승급역할", value=promote, inline=True)
        embed.add_field(name="🎭 반응역할 패널", value=mark(panel_txt), inline=True)

        # ── 음성 / 레벨 ──
        triggers = list(cfg.get("temp_voice_triggers", []))
        legacy = cfg.get("temp_voice_trigger_id")
        if legacy and legacy not in triggers:
            triggers.append(legacy)
        excluded = cfg.get("leveling_excluded_channels", [])
        base_h = cfg.get("level_base_hours")
        expo = cfg.get("level_exponent")
        curve = (f"기준 {base_h}h · 곡선 {expo}"
                 if base_h is not None or expo is not None else "기본값")
        embed.add_field(name="➕ 임시음성 트리거",
                        value=mark(self._channel_list(guild, triggers)), inline=True)
        embed.add_field(name="🔇 집계 제외 채널",
                        value=mark(self._channel_list(guild, excluded)), inline=True)
        embed.add_field(name="📈 레벨 곡선", value=curve, inline=True)

        # ── 기타 ──
        party = mark(self._channel(guild, cfg.get("party_recruit_channel_id")))
        ach = mark(self._channel(guild, cfg.get("achievement_channel_id")))
        window = cfg.get("activity_window_days")
        window_txt = f"{window}일" if window is not None else "기본값"
        rate = cfg.get("bank_interest_rate")
        if rate is None:
            interest = "기본 1% / 12h"
        elif rate <= 0:
            interest = "꺼짐"
        else:
            interest = f"{rate * 100:g}% / 12h"
        embed.add_field(name="🎮 파티 모집 채널", value=party, inline=True)
        embed.add_field(name="🏆 업적 알림 채널", value=ach, inline=True)
        embed.add_field(name="🏦 은행 이자 · 📊 활동기간",
                        value=f"이자 {interest}\n활동 판정 {window_txt}", inline=True)

        # ── 낚시 장소 제한 (없으면 어디서나 가능) ──
        fishing = cfg.get("fishing_channels", [])
        forge = cfg.get("forge_channels", [])
        embed.add_field(name="🎣 낚시터",
                        value=mark(self._channel_list(guild, fishing)) if fishing else "어디서나", inline=True)
        embed.add_field(name="🔨 대장간",
                        value=mark(self._channel_list(guild, forge)) if forge else "어디서나", inline=True)
        embed.add_field(name="​", value="​", inline=True)  # 3열 정렬용 빈칸

        # ── 미달성 알림 채널 ──
        nc = mark(self._channel(guild, cfg.get("newcomer_alert_channel_id")))
        ac = mark(self._channel(guild, cfg.get("activity_alert_channel_id")))
        embed.add_field(name="🌱 신입 미달성 알림", value=nc, inline=True)
        embed.add_field(name="💤 활동 미달성 알림", value=ac, inline=True)
        embed.add_field(name="​", value="​", inline=True)

        if stale["n"]:
            embed.set_footer(
                text=f"⚠️ 삭제된 채널·역할 {stale['n']}개 — 해당 설정을 다시 지정하면 정리돼요."
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "서버 관리 권한이 필요한 명령어예요.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerConfig(bot))
