"""
신박한 통계 (cogs/insights.py) — 케미 / 골든타임 / 개인 결산

음성 세션 데이터(채널·시작시각·시간)를 활용한 다른 봇엔 잘 없는 기능들:
  /케미 [멤버]     함께 음성에 가장 오래 있던 '베스트 듀오' 찾기
  /골든타임        서버가 가장 활발한 시간대 (한국시간)
  /결산 [멤버]     개인 활동 결산 (음성·메시지·듀오·피크타임·레벨)

모두 유저용 (모두에게 보임).
"""

import discord
from discord import app_commands
from discord.ext import commands

import voicetime as vt


def _name(guild: discord.Guild, user_id: int) -> str:
    m = guild.get_member(user_id)
    return m.display_name if m else f"(나간 유저)"


class Insights(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- /케미 ----
    @app_commands.command(name="케미", description="함께 음성에 가장 오래 있던 베스트 듀오를 찾습니다")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def chemistry(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        duos = vt.best_duos(interaction.guild.id, member.id, days=30)
        if not duos:
            await interaction.response.send_message(
                "아직 함께한 음성 기록이 부족해요. 음성채널에서 같이 놀아보세요! 🎧", ephemeral=True
            )
            return

        top_uid, top_secs = duos[0]
        embed = discord.Embed(
            title=f"💞 {member.display_name} 님의 케미",
            description=f"최근 30일 베스트 듀오는 **{_name(interaction.guild, top_uid)}** 님! "
                        f"({vt.format_duration(top_secs)} 함께함)",
            color=discord.Color.magenta(),
        )
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        lines = [
            f"{medals[i]} **{_name(interaction.guild, uid)}** — {vt.format_duration(secs)}"
            for i, (uid, secs) in enumerate(duos)
        ]
        embed.add_field(name="함께한 시간 순위", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed)

    # ---- /골든타임 ----
    @app_commands.command(name="골든타임", description="서버가 가장 활발한 시간대를 봅니다 (한국시간)")
    async def golden_time(self, interaction: discord.Interaction):
        hours = vt.activity_by_hour(interaction.guild.id, days=30)
        if max(hours) <= 0:
            await interaction.response.send_message("아직 음성 활동 데이터가 부족해요.", ephemeral=True)
            return

        peak_h = max(range(24), key=lambda h: hours[h])
        # 0~23시를 6칸씩 4줄로 스파크라인 표시
        rows = []
        for start in (0, 6, 12, 18):
            seg = hours[start:start + 6]
            labels = " ".join(f"{start + i:02d}" for i in range(6))
            rows.append(f"`{labels}`\n{vt.sparkline(seg)}")
        embed = discord.Embed(
            title="⏰ 서버 골든타임 (최근 30일)",
            description=f"가장 활발한 시간: **{peak_h:02d}시~{(peak_h + 1) % 24:02d}시** 🔥\n\n" + "\n".join(rows),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="막대가 높을수록 그 시간대에 음성이 활발해요 · 기준: 한국시간(KST)")
        await interaction.response.send_message(embed=embed)

    # ---- /결산 ----
    @app_commands.command(name="결산", description="개인 활동 결산 카드 (음성·메시지·듀오·피크타임·레벨)")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def wrapped(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        gid = interaction.guild.id

        v30 = vt.voice_seconds_days(gid, member.id, 30)
        m30 = vt.message_count_days(gid, member.id, 30)
        level = vt.hours_to_level((vt.total_seconds(gid, member.id)) / 3600, gid)
        vrank, _ = vt.voice_rank(gid, member.id)

        duos = vt.best_duos(gid, member.id, days=30)
        duo_str = f"{_name(interaction.guild, duos[0][0])} ({vt.format_duration(duos[0][1])})" if duos else "아직 없음"

        my_hours = vt.activity_by_hour(gid, days=30, user_id=member.id)
        if max(my_hours) > 0:
            ph = max(range(24), key=lambda h: my_hours[h])
            peak_str = f"{ph:02d}시대"
        else:
            peak_str = "기록 없음"

        embed = discord.Embed(
            title=f"📅 {member.display_name} 님의 이번 달 결산",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🔊 음성", value=vt.format_duration(v30), inline=True)
        embed.add_field(name="💬 메시지", value=f"{m30}회", inline=True)
        embed.add_field(name="🏆 음성 순위", value=f"#{vrank}" if vrank else "—", inline=True)
        embed.add_field(name="⭐ 레벨", value=f"Lv. {level}", inline=True)
        embed.add_field(name="🌙 주로 활동", value=peak_str, inline=True)
        embed.add_field(name="💞 베스트 듀오", value=duo_str, inline=True)
        embed.set_footer(text="최근 30일 기준 · 캡처해서 자랑해보세요!")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Insights(bot))
