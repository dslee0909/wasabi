"""
미니게임 — 낚시터 🎣 + 도박장 🎰 (cogs/economy.py)

🪙 코인 시스템: 낚시로 벌고, 도박으로 건다.

명령어 (모두 유저용):
  /지갑 [멤버]        코인 잔액 확인
  /코인순위          부자 순위 TOP 10
  /낚시              물고기를 낚아 코인 획득 (5초 쿨다운)
  /슬롯 베팅          슬롯머신 (3개 맞추면 대박)
  /동전 베팅 선택     동전 던지기 (앞/뒤 맞히면 2배)

코인은 data.db 의 balances 테이블에 서버별로 저장됩니다.
"""

import asyncio
import os
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import dexcard
import forge
import rodcard
import slotimage
import voicetime as vt
from store import get_guild_config, update_guild_config

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")


def owner_only():
    """봇 소유자 또는 서버 소유자만 통과시키는 체크.

    경제 관리 명령(코인 지급 등)은 코인을 무제한으로 찍어낼 수 있다. 원래는
    manage_guild('서버 관리') 권한자 전원에게 열려 있었는데, 그러면 관리자가
    여럿인 서버에서는 사실상 여러 명이 통화를 발행할 수 있다.
    실제로 한 서버의 통화량이 지급 명령으로 3,442억까지 부풀었다
    (같은 시기 정상 서버는 152만. 잔액은 guild_id 별로 분리돼 있어 서로 영향은 없다).

    Discord 의 default_permissions 는 UI 노출만 제어할 뿐 서버에서 덮어쓸 수 있으므로
    보안 경계가 아니다. 실제 차단은 이 체크가 한다.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild and interaction.user.id == interaction.guild.owner_id:
            return True
        return await interaction.client.is_owner(interaction.user)

    return app_commands.check(predicate)


DEFAULT_INTEREST = 0.01  # 12시간마다 1%
INTEREST_PERIOD = 12 * 3600  # 12시간

SHINY_MULT = 10      # 반짝이는 물고기 가격 배수
SHINY_DIR = os.path.join(ASSETS_DIR, "shiny")  # 반짝이 이미지 폴더 (같은 파일명)

ROD_DIR = os.path.join(ASSETS_DIR, "rods")
FORGE_SUCCESS_BG = os.path.join(ASSETS_DIR, "forge_success.png")  # 강화 성공 배경 (선택)
FORGE_FAIL_BG = os.path.join(ASSETS_DIR, "forge_fail.png")        # 강화 실패 배경 (선택)
FORGE_IDLE_BG = os.path.join(ASSETS_DIR, "forge_idle.png")        # 강화 대기화면 배경 (선택)
STATUS_BG = os.path.join(ASSETS_DIR, "status_bg.png")            # 낚시 스탯창 배경 (선택)

# 낚싯대 상점 (tier: 이름, 이모지, 가격, 코인배수, 반짝이확률, 쿨다운, 이미지파일)
RODS = {
    0: {"name": "기본 낚싯대", "emoji": "🎣", "price": 0,         "mult": 1.0, "shiny": 0.08, "cd": 2.0, "cap": 0,  "img": "rod_0_basic.png"},
    1: {"name": "나무 낚싯대", "emoji": "🪵", "price": 50_000,    "mult": 1.2, "shiny": 0.10, "cd": 2.0, "cap": 2,  "img": "rod_1_wood.png"},
    2: {"name": "강철 낚싯대", "emoji": "⚙️", "price": 150_000,   "mult": 1.5, "shiny": 0.11, "cd": 1.8, "cap": 4,  "img": "rod_2_steel.png"},
    3: {"name": "황금 낚싯대", "emoji": "🥇", "price": 300_000,   "mult": 2.0, "shiny": 0.12, "cd": 1.5, "cap": 6,  "img": "rod_3_gold.png"},
    4: {"name": "다이아 낚싯대", "emoji": "💎", "price": 800_000,   "mult": 2.5, "shiny": 0.14, "cd": 1.2, "cap": 8,  "img": "rod_4_diamond.png"},
    5: {"name": "용왕의 낚싯대", "emoji": "🐉", "price": 2_200_000, "mult": 3.0, "shiny": 0.16, "cd": 1.0, "cap": 10, "img": "rod_5_dragon.png"},
    6: {"name": "전설의 낚싯대", "emoji": "👑", "price": 8_000_000, "mult": 4.0, "shiny": 0.18, "cd": 0.8, "cap": 12, "img": "rod_6_legendary.png"},
    7: {"name": "입고중", "emoji": "⚡", "price": '?', "mult": 5.0, "shiny": 0.20, "cd": 0.5, "cap": 15, "img": "rod_7_god.png"}
}
ROD_TIERS = (1, 2, 3, 4, 5, 6, 7)  # 상점에 나오는 낚싯대 티어

ENHANCE_BONUS = 0.015  # 강화 +1당 코인 +1.5% (미미)


def enhance_cost(level: int) -> int:
    """강화도(level)에서 +1 하는 비용. 낚싯대 티어와 무관하게 고정 (강화도는 승계되므로 일관성 유지)."""
    return 20_000 * (level + 1)


def enhance_rate(level: int) -> float:
    """현재 강화레벨 level 에서 +1 성공 확률 (레벨 오를수록 낮아짐)."""
    return max(0.15, 1.0 - level * 0.08)


# 실제 구매 가능한 티어 (가격이 정수인 것만; '입고중' 등 문자열 가격 제외)
BUYABLE_TIERS = tuple(t for t in ROD_TIERS if isinstance(RODS[t]["price"], int))


def _price_label(tier: int) -> str:
    p = RODS[tier]["price"]
    return f"{p:,} 코인" if isinstance(p, int) else "🚧 입고중"

POLICE_ID = 0  # 경찰서 금고를 담는 가상 계정 (balances 테이블의 user_id 0)

# 도둑질 설정
STEAL_SUCCESS = 0.5      # 성공 확률 50%
STEAL_MIN = 100          # 상대 지갑에 이 이상 있어야 털 가치 있음
STEAL_CAPITAL = 0.5      # 내 지갑이 '상대 지갑의 50%' 이상이어야 시도 가능 (밑천)
STEAL_PCT = (0.10, 0.30) # 성공 시 상대 지갑의 10~30% 획득
STEAL_FINE = 0.20        # 실패 시 내 지갑의 20% 벌금 → 경찰서
STEAL_CD = 3600          # 쿨다운 1시간

# 경찰서 털기 설정
ROB_SUCCESS = 0.20       # 성공 확률 20% (하이리스크)
ROB_MIN_POOL = 100       # 금고에 이 이상 있어야 시도 가능
ROB_MIN_WALLET = 10_000  # 경찰서 털려면 지갑에 최소 1만원 보유
ROB_PCT = (0.30, 0.60)   # 성공 시 금고의 30~60% 획득
ROB_FINE = 0.30          # 실패 시 내 지갑의 30% 벌금 → 경찰서
ROB_CD = 7200            # 쿨다운 2시간


def format_cd(seconds: float) -> str:
    m = int(seconds // 60)
    if m >= 60:
        return f"{m // 60}시간 {m % 60}분"
    if m >= 1:
        return f"{m}분 {int(seconds % 60)}초"
    return f"{int(seconds)}초"

# 낚시 결과 (이름, 이모지, 가치, 가중치%, 이미지파일)
FISH = [
    ("꽝", "🪹", 0, 15.90, "01_no_catch_15_90.png"),
    ("낡은 신발", "🥾", 1, 9, "02_old_boot_09_00.png"),
    ("멸치", "🐟", 5, 20.85, "03_anchovy_20_85.png"),
    ("고등어", "🐠", 15, 16.95, "04_mackerel_16_95.png"),
    ("오징어", "🦑", 30, 12, "06_squid_12_00.png"),
    ("게", "🦀", 40, 8, "05_crab_08_00.png"),
    ("문어", "🐙", 60, 7, "07_octopus_07_00.png"),
    ("복어", "🐡", 100, 4, "08_pufferfish_04_00.png"),
    ("보물상자", "💵", 150, 2.9, "10_treasure_chest_02_90.png"),
    ("상어", "🦈", 200, 2, "09_shark_02_00.png"),
    ("고래", "🐋", 600, 1, "11_whale_01_00.png"),
    ("전설의 황금잉어", "🎏", 2000, 0.3, "12_legendary_carp_00_30.png"),
    ("다이아몬드", "💎", 5000, 0.1, "13_diamond_00_10.png"),
]

SLOT_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "🍀", "💎"]


def coins(n: int) -> str:
    return f"{n:,} 🪙"


def _slot_spin():
    """가중 추첨으로 결과를 먼저 정하고 릴을 거기에 맞춰 생성 (환수율 ≈96% 정밀 제어).
    반환: (릴 3개, 배수, 결과문구). 확률은 아래 주석 참고."""
    x = random.random()
    others = [s for s in SLOT_SYMBOLS if s not in ("💎", "🍀")]
    if x < 0.004:                     # 0.4%  💎💎💎 x8
        reels, mult, result = ["💎"] * 3, 8, "JACKPOT!"
    elif x < 0.010:                   # 0.6%  🍀🍀🍀 x5
        reels, mult, result = ["🍀"] * 3, 5, "JACKPOT!"
    elif x < 0.030:                   # 2%    그 외 3개 일치 x3
        s = random.choice(others)
        reels, mult, result = [s] * 3, 3, "JACKPOT!"
    elif x < 0.450:                   # 42%   2개 일치 x2
        a = random.choice(SLOT_SYMBOLS)
        b = random.choice([s for s in SLOT_SYMBOLS if s != a])
        reels = [a, a, b]
        random.shuffle(reels)
        mult, result = 2, "두 개 일치!"
    else:                             # 55%   꽝
        reels = random.sample(SLOT_SYMBOLS, 3)  # 서로 다른 3개
        mult, result = 0, "꽝"
    return reels, mult, result


def _slot_row():
    return [random.choice(SLOT_SYMBOLS) for _ in range(3)]


class GambleView(discord.ui.View):
    """도박 결과에 붙는 [다시][절반][올인] 버튼. 본인만 사용 가능."""

    def __init__(self, cog, game: str, owner_id: int, bet: int, choice: str = None):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game        # "slot" | "coin"
        self.owner_id = owner_id
        self.bet = bet
        self.choice = choice    # 동전: 앞/뒤

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인 게임에서만 쓸 수 있어요.", ephemeral=True)
            return False
        return True

    async def _replay(self, interaction: discord.Interaction, bet: int, slow: bool = False):
        if self.game == "slot":
            await self.cog._start_slot(interaction, interaction.user, bet, from_button=True, slow=slow)
        else:
            await self.cog._start_coin(interaction, interaction.user, bet, self.choice, from_button=True)

    @discord.ui.button(label="다시", emoji="🔁", style=discord.ButtonStyle.primary)
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._replay(interaction, self.bet)

    @discord.ui.button(label="½ 절반", style=discord.ButtonStyle.secondary)
    async def half(self, interaction: discord.Interaction, button: discord.ui.Button):
        wallet = vt.get_balance(interaction.guild.id, interaction.user.id)
        await self._replay(interaction, wallet // 2, slow=True)  # 박진감 있게 천천히

    @discord.ui.button(label="올인", emoji="💰", style=discord.ButtonStyle.danger)
    async def allin(self, interaction: discord.Interaction, button: discord.ui.Button):
        wallet = vt.get_balance(interaction.guild.id, interaction.user.id)
        await self._replay(interaction, wallet, slow=True)  # 박진감 있게 천천히


class FishView(discord.ui.View):
    """낚시 결과에 붙는 [🎣 다시 낚기] 버튼. 본인 것만 갱신(채팅 안 밀림)."""

    def __init__(self, cog, owner_id: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "본인 낚시대에서만 낚을 수 있어요! `/낚시` 로 시작하세요.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="다시 낚기", emoji="🎣", style=discord.ButtonStyle.primary)
    async def again(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._do_fish(interaction, from_button=True)


class ForgeView(discord.ui.View):
    """대장간 강화 패널의 [🔨 강화하기] 버튼. 본인만 사용."""

    def __init__(self, cog, owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("본인 대장간에서만 강화할 수 있어요. `/강화` 로 시작하세요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="강화하기", emoji="🔨", style=discord.ButtonStyle.danger)
    async def forge_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._do_forge(interaction)


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.interest_loop.start()
        # 수동 쿨다운 {(guild_id, user_id): 마지막 시도 시각} — 검증 통과한 시도만 소모
        self._steal_cd: dict[tuple[int, int], float] = {}
        self._rob_cd: dict[tuple[int, int], float] = {}
        self._fish_cd: dict[tuple[int, int], float] = {}

    def _cooldown_left(self, store: dict, key, cd: float) -> float:
        left = cd - (time.time() - store.get(key, 0))
        return left if left > 0 else 0

    def cog_unload(self):
        self.interest_loop.cancel()

    # 관리자 전용 코인 관리 그룹 (목록에서 숨김)
    코인 = app_commands.Group(
        name="코인",
        description="코인 지급/회수 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    은행 = app_commands.Group(
        name="은행",
        description="은행 이자 설정 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    낚시관리 = app_commands.Group(
        name="낚시관리",
        description="낚싯대/강화 회수·설정 (관리자)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @낚시관리.command(name="낚싯대", description="멤버의 낚싯대 티어를 설정합니다")
    @app_commands.describe(멤버="대상", 티어="0=기본, 1~6")
    @app_commands.choices(티어=[
        app_commands.Choice(name=f"{t}: {RODS[t]['name']}", value=t) for t in range(0, 7)
    ])
    @owner_only()
    async def admin_set_rod(self, interaction: discord.Interaction, 멤버: discord.Member, 티어: app_commands.Choice[int]):
        gid = interaction.guild.id
        tier = 티어.value
        vt.set_rod(gid, 멤버.id, tier)
        # 강화가 새 티어 상한을 넘으면 상한으로 낮춤
        if vt.get_rod_enhance(gid, 멤버.id) > RODS[tier]["cap"]:
            vt.set_rod_enhance(gid, 멤버.id, RODS[tier]["cap"])
        await interaction.response.send_message(
            f"✅ {멤버.mention} 의 낚싯대를 **{RODS[tier]['name']}** 로 설정했어요.", ephemeral=True
        )

    @낚시관리.command(name="강화", description="멤버의 강화 수치를 설정합니다")
    @app_commands.describe(멤버="대상", 레벨="설정할 강화 레벨")
    @owner_only()
    async def admin_set_enhance(self, interaction: discord.Interaction, 멤버: discord.Member, 레벨: int):
        gid = interaction.guild.id
        cap = RODS[vt.get_rod(gid, 멤버.id)]["cap"]
        lvl = max(0, min(레벨, cap))
        vt.set_rod_enhance(gid, 멤버.id, lvl)
        await interaction.response.send_message(
            f"✅ {멤버.mention} 의 강화를 **+{lvl}** 로 설정했어요. (현재 낚싯대 최대 +{cap})", ephemeral=True
        )

    @낚시관리.command(name="회수", description="멤버의 낚싯대를 기본으로 되돌립니다 (강화도 초기화)")
    @app_commands.describe(멤버="대상")
    @owner_only()
    async def admin_reset_rod(self, interaction: discord.Interaction, 멤버: discord.Member):
        gid = interaction.guild.id
        vt.set_rod(gid, 멤버.id, 0)
        vt.set_rod_enhance(gid, 멤버.id, 0)
        await interaction.response.send_message(
            f"✅ {멤버.mention} 의 낚싯대를 **회수**했어요. (기본 낚싯대 + 강화 0 초기화)", ephemeral=True
        )

    # ---- 은행 이자 (12시간마다) ----
    @tasks.loop(minutes=30)
    async def interest_loop(self):
        now = time.time()
        for guild in self.bot.guilds:
            cfg = get_guild_config(guild.id)
            rate = cfg.get("bank_interest_rate", DEFAULT_INTEREST)
            if rate <= 0:
                continue
            last = cfg.get("bank_interest_last", 0)
            if last == 0:
                # 처음 만난 서버는 이자를 붙이지 않고 시계만 시작
                update_guild_config(guild.id, {"bank_interest_last": now})
            elif now - last >= INTEREST_PERIOD:
                vt.apply_interest(guild.id, rate)
                update_guild_config(guild.id, {"bank_interest_last": now})

    @interest_loop.before_loop
    async def before_interest(self):
        await self.bot.wait_until_ready()

    @은행.command(name="이자설정", description="은행 이자율(12시간마다 %)을 설정합니다")
    @app_commands.describe(이율="12시간마다 붙는 이자 % (예: 1 = 1%, 0 = 이자 끄기)")
    @owner_only()
    async def set_interest(self, interaction: discord.Interaction, 이율: float):
        if 이율 < 0:
            await interaction.response.send_message("0 이상으로 설정해주세요.", ephemeral=True)
            return
        update_guild_config(interaction.guild.id, {"bank_interest_rate": 이율 / 100})
        msg = "이자를 껐어요." if 이율 == 0 else f"이제 **12시간마다 {이율}%** 이자가 붙어요."
        await interaction.response.send_message(f"✅ {msg}", ephemeral=True)

    @코인.command(name="지급", description="멤버에게 코인을 지급합니다")
    @app_commands.describe(멤버="지급 대상", 금액="지급할 코인 (1 이상)")
    @owner_only()
    async def give_coins(self, interaction: discord.Interaction, 멤버: discord.Member, 금액: int):
        if 금액 < 1:
            await interaction.response.send_message("1 이상 지급해주세요.", ephemeral=True)
            return
        new_bal = vt.add_balance(interaction.guild.id, 멤버.id, 금액)
        await interaction.response.send_message(
            f"✅ {멤버.mention} 님에게 **{coins(금액)}** 지급! (잔액 {coins(new_bal)})"
        )

    @코인.command(name="회수", description="멤버의 코인을 회수합니다")
    @app_commands.describe(멤버="회수 대상", 금액="회수할 코인 (1 이상)")
    @owner_only()
    async def take_coins(self, interaction: discord.Interaction, 멤버: discord.Member, 금액: int):
        if 금액 < 1:
            await interaction.response.send_message("1 이상 회수해주세요.", ephemeral=True)
            return
        current = vt.get_balance(interaction.guild.id, 멤버.id)
        removed = min(금액, current)  # 잔액보다 많이 회수하면 0까지만
        new_bal = vt.add_balance(interaction.guild.id, 멤버.id, -removed)
        await interaction.response.send_message(
            f"✅ {멤버.mention} 님의 코인 **{coins(removed)}** 회수! (잔액 {coins(new_bal)})", ephemeral=True
        )

    # ---- 지갑 / 순위 ----
    @app_commands.command(name="지갑", description="지갑·은행 잔액을 확인합니다")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def wallet(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        w = vt.get_balance(interaction.guild.id, member.id)
        b = vt.get_bank(interaction.guild.id, member.id)
        embed = discord.Embed(title=f"💰 {member.display_name} 님의 자산", color=discord.Color.gold())
        embed.add_field(name="👛 지갑", value=coins(w), inline=True)
        embed.add_field(name="🏦 은행", value=coins(b), inline=True)
        embed.add_field(name="합계", value=coins(w + b), inline=True)
        rate = get_guild_config(interaction.guild.id).get("bank_interest_rate", DEFAULT_INTEREST)
        if rate > 0:
            embed.set_footer(text=f"🏦 은행 이자: 12시간마다 {rate * 100:g}%")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="송금", description="다른 멤버에게 지갑 코인을 보냅니다")
    @app_commands.describe(멤버="받을 사람", 금액="보낼 코인 (1 이상)")
    async def send_money(self, interaction: discord.Interaction, 멤버: discord.Member, 금액: int):
        if 멤버.id == interaction.user.id:
            await interaction.response.send_message("자기 자신에게는 보낼 수 없어요.", ephemeral=True)
            return
        if 멤버.bot:
            await interaction.response.send_message("봇에게는 보낼 수 없어요.", ephemeral=True)
            return
        if 금액 < 1:
            await interaction.response.send_message("1 코인 이상 보내주세요.", ephemeral=True)
            return
        if not vt.transfer(interaction.guild.id, interaction.user.id, 멤버.id, 금액):
            await interaction.response.send_message("지갑 코인이 부족해요. (은행 돈은 먼저 `/출금`)", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} → {멤버.mention}  **{coins(금액)}** 송금 완료!"
        )

    @app_commands.command(name="입금", description="지갑 코인을 은행에 안전하게 보관합니다")
    @app_commands.describe(금액="입금할 코인 (1 이상)")
    async def deposit(self, interaction: discord.Interaction, 금액: int):
        if 금액 < 1:
            await interaction.response.send_message("1 코인 이상 입금해주세요.", ephemeral=True)
            return
        if not vt.deposit(interaction.guild.id, interaction.user.id, 금액):
            await interaction.response.send_message("지갑 코인이 부족해요.", ephemeral=True)
            return
        w = vt.get_balance(interaction.guild.id, interaction.user.id)
        b = vt.get_bank(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            f"🏦 **{coins(금액)}** 입금 완료! (지갑 {coins(w)} / 은행 {coins(b)})", ephemeral=True
        )

    @app_commands.command(name="출금", description="은행에서 지갑으로 코인을 꺼냅니다")
    @app_commands.describe(금액="출금할 코인 (1 이상)")
    async def withdraw(self, interaction: discord.Interaction, 금액: int):
        if 금액 < 1:
            await interaction.response.send_message("1 코인 이상 출금해주세요.", ephemeral=True)
            return
        if not vt.withdraw(interaction.guild.id, interaction.user.id, 금액):
            await interaction.response.send_message("은행 잔액이 부족해요.", ephemeral=True)
            return
        w = vt.get_balance(interaction.guild.id, interaction.user.id)
        b = vt.get_bank(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            f"👛 **{coins(금액)}** 출금 완료! (지갑 {coins(w)} / 은행 {coins(b)})", ephemeral=True
        )

    @app_commands.command(name="코인순위", description="코인 부자 순위 TOP 10")
    async def rich_list(self, interaction: discord.Interaction):
        rows = vt.top_balances(interaction.guild.id, 10)
        rows = [(uid, c) for uid, c in rows if c > 0]
        if not rows:
            await interaction.response.send_message("아직 코인을 가진 사람이 없어요. `/낚시`로 벌어보세요!", ephemeral=True)
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, c) in enumerate(rows):
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else "(나간 유저)"
            rank = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{rank} **{name}** — {coins(c)}")
        embed = discord.Embed(title="💰 코인 부자 순위", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    # ---- 상점 🏪 ----
    @app_commands.command(name="상점", description="낚싯대 상점 — 코인으로 낚싯대를 삽니다")
    async def shop(self, interaction: discord.Interaction):
        my = vt.get_rod(interaction.guild.id, interaction.user.id)
        cur = RODS[my]

        # 구매 가능한 티어(1~6) 이미지가 다 있으면 이미지 상점, 아니면 텍스트
        # (입고중 등 가격 미정 티어는 아트가 없어도 됨 — render_shop이 썸네일을 비움)
        all_imgs = all(os.path.exists(os.path.join(ROD_DIR, RODS[t]["img"])) for t in BUYABLE_TIERS)
        if all_imgs:
            # 이미지 안에는 이모지가 두부(□)로 나오므로 이모지 없는 라벨 사용
            entries = [{
                "name": RODS[t]["name"], "img": RODS[t]["img"],
                "price_str": ("입고중" if not isinstance(RODS[t]["price"], int)
                              else f"{RODS[t]['price']:,} 코인"),
                "effect": f"x{RODS[t]['mult']} · 반짝이 {int(RODS[t]['shiny']*100)}% · 쿨 {RODS[t]['cd']}s",
                "owned": my >= t,
            } for t in ROD_TIERS]
            title = f"낚싯대 상점   (장착: {cur['name']})"
            try:
                buf = rodcard.render_shop(entries, title, ROD_DIR)
                await interaction.response.send_message(
                    content="`/구매` 로 구입하세요.", file=discord.File(buf, "shop.png"), ephemeral=True
                )
                return
            except Exception as e:
                print(f"[경고] 상점 이미지 생성 실패, 텍스트로 대체: {e}")

        lines = []
        for tier in ROD_TIERS:
            r = RODS[tier]
            status = "✅ 보유중" if my >= tier else _price_label(tier)
            lines.append(
                f"{r['emoji']} **{r['name']}** — {status}\n"
                f"┗ 코인 **x{r['mult']}** · 반짝이 **{int(r['shiny']*100)}%** · 쿨 **{r['cd']}초**"
            )
        embed = discord.Embed(title="🏪 낚싯대 상점", description="\n\n".join(lines), color=discord.Color.dark_teal())
        embed.set_footer(text=f"현재 장착: {cur['emoji']} {cur['name']}  ·  /구매 로 구입")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="구매", description="낚싯대를 구매합니다 (지갑 코인 사용)")
    @app_commands.describe(낚싯대="구매할 낚싯대")
    @app_commands.choices(낚싯대=[
        app_commands.Choice(name=f"{RODS[t]['name']} ({RODS[t]['price']:,}원)", value=t)
        for t in BUYABLE_TIERS
    ])
    async def buy(self, interaction: discord.Interaction, 낚싯대: app_commands.Choice[int]):
        gid, uid = interaction.guild.id, interaction.user.id
        tier = 낚싯대.value
        r = RODS[tier]
        if not isinstance(r["price"], int):
            await interaction.response.send_message("아직 입고 전인 낚싯대예요. 조금만 기다려주세요! 🚧", ephemeral=True)
            return
        my = vt.get_rod(gid, uid)
        if my >= tier:
            await interaction.response.send_message(
                f"이미 **{RODS[my]['name']}**(이상)을 보유하고 있어요.", ephemeral=True
            )
            return
        wallet = vt.get_balance(gid, uid)
        if wallet < r["price"]:
            await interaction.response.send_message(
                f"코인이 부족해요. (지갑 {coins(wallet)} / 가격 {coins(r['price'])})\n"
                f"은행에 있으면 `/출금` 먼저 하세요.", ephemeral=True
            )
            return
        vt.add_balance(gid, uid, -r["price"])
        vt.set_rod(gid, uid, tier)
        text = (f"🎉 **{r['emoji']} {r['name']}** 구매 & 장착 완료!\n"
                f"코인 x{r['mult']} · 반짝이 {int(r['shiny']*100)}% · 쿨 {r['cd']}초")
        rod_path = os.path.join(ROD_DIR, r["img"])
        if os.path.exists(rod_path):
            await interaction.response.send_message(text, file=discord.File(rod_path, "rod.png"))
        else:
            await interaction.response.send_message(text)

    # ---- 낚싯대 강화 / 상태 ----
    @app_commands.command(name="낚시스탯", description="낚시 종합 스탯 (낚싯대·효과·강화·기록·순위·자산)")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def rod_status(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        gid = interaction.guild.id
        tier = vt.get_rod(gid, member.id)
        enh = vt.get_rod_enhance(gid, member.id)
        r = RODS[tier]
        bonus = enh * ENHANCE_BONUS
        eff_mult = r["mult"] * (1 + bonus)

        total, shiny_cnt, species = vt.get_fishing_stats(gid, member.id)
        rank, _ = vt.fishing_rank(gid, member.id)
        species_total = sum(1 for f in FISH if f[2] > 0)
        assets = vt.get_balance(gid, member.id) + vt.get_bank(gid, member.id)
        earned = vt.get_fish_earned(gid, member.id)

        name = r["name"] + (f" +{enh}" if enh else "")
        sections = [
            ("낚싯대 효과", (90, 205, 120), [
                ("💰", f"코인 배수  x{eff_mult:.2f}" + (f"  (+강화 {int(bonus*100)}%)" if enh else "")),
                ("✨", f"반짝이 확률  {int(r['shiny']*100)}%"),
                ("⏱️", f"쿨다운  {r['cd']}초"),
                ("🔨", f"강화  +{enh} / 최대 +{r['cap']}"),
            ]),
            ("낚시 기록", (85, 160, 235), [
                ("🐟", f"총 낚은 물고기  {total:,}마리"),
                ("🌟", f"반짝이  {shiny_cnt:,}마리"),
                ("📖", f"도감  {species} / {species_total}종"),
                ("🏆", f"낚시 순위  " + (f"#{rank}" if rank else "-")),
            ]),
            ("자산", (235, 180, 70), [
                ("👛", f"총 자산  {assets:,} 코인"),
                ("🎣", f"낚시 누적 수익  {earned:,} 코인"),
            ]),
        ]
        title = f"{member.display_name} 님의 낚시 스탯"
        rod_path = os.path.join(ROD_DIR, r["img"])
        try:
            bg = STATUS_BG if os.path.exists(STATUS_BG) else None
            buf = rodcard.render_profile(rod_path, title, name, enh, sections, bg_path=bg)
            await interaction.response.send_message(file=discord.File(buf, "fishing_status.png"))
        except Exception as e:
            print(f"[경고] 낚시 스탯 이미지 실패: {e}")
            desc = "\n".join(f"**{h}**\n" + "\n".join(f"{em} {t}" for em, t in lines) for h, _, lines in sections)
            embed = discord.Embed(title=title, description=desc, color=discord.Color.gold())
            await interaction.response.send_message(embed=embed)

    def _forge_status_file(self, gid: int, uid: int, bg_path: str = None) -> discord.File:
        tier = vt.get_rod(gid, uid)
        enh = vt.get_rod_enhance(gid, uid)
        r = RODS[tier]
        bonus = enh * ENHANCE_BONUS
        name = r["name"] + (f" +{enh}" if enh else "")
        effects = [
            ("💰", f"코인 배수  x{r['mult'] * (1 + bonus):.2f}"),
            ("✨", f"반짝이 확률  {int(r['shiny']*100)}%"),
            ("🔨", f"강화  +{enh} / 최대 +{r['cap']}"),
        ]
        buf = rodcard.render_status(os.path.join(ROD_DIR, r["img"]), name, enh, effects, bg_path=bg_path)
        return discord.File(buf, "forge.png")

    def _forge_panel_text(self, gid: int, uid: int, result: str = "") -> str:
        tier = vt.get_rod(gid, uid)
        enh = vt.get_rod_enhance(gid, uid)
        r = RODS[tier]
        head = (result + "\n") if result else ""
        if enh >= r["cap"]:
            return f"{head}🏆 **{r['name']} +{enh}** — 최대 강화 달성!"
        cost = enhance_cost(enh)
        rate = enhance_rate(enh)
        wallet = vt.get_balance(gid, uid)
        return (f"{head}🔨 **대장간** — {r['name']} **+{enh}** → +{enh+1}\n"
                f"성공확률 **{int(rate*100)}%** · 비용 **{coins(cost)}** · 지갑 {coins(wallet)}\n"
                f"아래 **🔨 강화하기** 버튼을 눌러 두드리세요!")

    @app_commands.command(name="강화", description="대장간에서 장착 낚싯대를 강화합니다 (버튼으로 두드리기)")
    async def enhance(self, interaction: discord.Interaction):
        gid, uid = interaction.guild.id, interaction.user.id
        if vt.get_rod(gid, uid) == 0:
            await interaction.response.send_message("먼저 `/상점` 에서 낚싯대를 사세요! (기본 낚싯대는 강화 불가)", ephemeral=True)
            return
        enh = vt.get_rod_enhance(gid, uid)
        r = RODS[vt.get_rod(gid, uid)]
        view = ForgeView(self, uid) if enh < r["cap"] else None
        idle_bg = FORGE_IDLE_BG if os.path.exists(FORGE_IDLE_BG) else None
        await interaction.response.send_message(
            content=self._forge_panel_text(gid, uid),
            file=self._forge_status_file(gid, uid, bg_path=idle_bg),
            view=view,
        )

    async def _do_forge(self, interaction: discord.Interaction):
        gid, uid = interaction.guild.id, interaction.user.id
        tier = vt.get_rod(gid, uid)
        r = RODS[tier]
        enh = vt.get_rod_enhance(gid, uid)
        if enh >= r["cap"]:
            await interaction.response.send_message("이미 최대 강화예요!", ephemeral=True)
            return
        cost = enhance_cost(enh)
        if vt.get_balance(gid, uid) < cost:
            await interaction.response.send_message(f"코인이 부족해요. (비용 {coins(cost)})", ephemeral=True)
            return

        vt.add_balance(gid, uid, -cost)  # 성공/실패 무관 소모
        await interaction.response.defer()
        message = interaction.message

        # 망치질 애니메이션
        gif = forge.render_forge(os.path.join(ROD_DIR, r["img"]))
        await message.edit(
            content=f"🔨 **{r['name']} +{enh}** 두드리는 중...  땅! 땅!",
            attachments=[discord.File(gif, "forge.gif")], view=None,
        )
        await asyncio.sleep(1.6)

        rate = enhance_rate(enh)
        if random.random() < rate:
            vt.set_rod_enhance(gid, uid, enh + 1)
            result = f"✨ **강화 성공!** → **+{enh + 1}**"
            bg = FORGE_SUCCESS_BG
        else:
            result = f"💥 **강화 실패...** (+{enh} 유지)"
            bg = FORGE_FAIL_BG

        new_enh = vt.get_rod_enhance(gid, uid)
        view = ForgeView(self, uid) if new_enh < r["cap"] else None
        await message.edit(
            content=self._forge_panel_text(gid, uid, result=result),
            attachments=[self._forge_status_file(gid, uid, bg_path=bg)],
            view=view,
        )

    @app_commands.command(name="낚시순위", description="물고기를 가장 많이 낚은 순위 TOP 10")
    async def fish_rank(self, interaction: discord.Interaction):
        rows = vt.fishing_leaderboard(interaction.guild.id, 10)
        if not rows:
            await interaction.response.send_message("아직 낚은 기록이 없어요. `/낚시`로 시작!", ephemeral=True)
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, total, shiny, species) in enumerate(rows):
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else "(나간 유저)"
            rank = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{rank} **{name}** — {total}마리  (✨{shiny} · 도감 {species}종)")
        embed = discord.Embed(
            title="🎣 낚시 순위 (총 마릿수)",
            description="\n".join(lines),
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed)

    # ---- 낚시터 🎣 (/낚시 = /ㄴㅅ, 쿨다운 공유) ----
    async def _do_fish(self, interaction: discord.Interaction, from_button=False):
        user = interaction.user
        gid = interaction.guild.id
        key = (gid, user.id)
        rod = RODS[vt.get_rod(gid, user.id)]  # 장착 낚싯대 효과
        enh = vt.get_rod_enhance(gid, user.id)  # 강화 레벨
        left = self._cooldown_left(self._fish_cd, key, rod["cd"])
        if left:
            await interaction.response.send_message(f"⏳ {left:.1f}초 후에 다시 낚시할 수 있어요.", ephemeral=True)
            return
        self._fish_cd[key] = time.time()

        name, emoji, value, _, img = random.choices(FISH, weights=[f[3] for f in FISH])[0]

        # 꽝이 아니면 (낚싯대별) 확률로 '반짝이는' 버전 (가격 10배, 전용 이미지)
        shiny = value > 0 and random.random() < rod["shiny"]
        if shiny:
            value *= SHINY_MULT
            shiny_path = os.path.join(SHINY_DIR, img)
            path = shiny_path if os.path.exists(shiny_path) else os.path.join(ASSETS_DIR, img)
        else:
            path = os.path.join(ASSETS_DIR, img)
        if value > 0:
            value = int(value * rod["mult"] * (1 + enh * ENHANCE_BONUS))  # 낚싯대 배수 + 강화 보너스
            vt.add_catch(gid, user.id, name, shiny)  # 도감 기록
            vt.add_fish_earned(gid, user.id, value)  # 낚시 누적 수익
        file = discord.File(path, filename="fish.png") if os.path.exists(path) else None

        plus = f" +{enh}" if enh else ""
        head = f"🎣 **{user.display_name}** 님의 낚시  ·  {rod['emoji']} {rod['name']}{plus}"
        if value <= 0:
            text = f"{head}\n{emoji} **{name}**... 이번엔 허탕이에요!"
        elif shiny:
            bal = vt.add_balance(gid, user.id, value)
            text = f"{head}\n✨🎉 **반짝이는 {name}** 🎉✨ 낚음!! **+{coins(value)}**\n잔액: {coins(bal)}"
        else:
            bal = vt.add_balance(gid, user.id, value)
            text = f"{head}\n{emoji} **{name}** 낚음! **+{coins(value)}**\n잔액: {coins(bal)}"

        view = FishView(self, user.id)
        no_ping = discord.AllowedMentions.none()
        if from_button:
            await interaction.response.defer()
            await interaction.message.edit(
                content=text, attachments=([file] if file else []), view=view, allowed_mentions=no_ping
            )
        elif file:
            await interaction.response.send_message(text, file=file, view=view, allowed_mentions=no_ping)
        else:
            await interaction.response.send_message(text, view=view, allowed_mentions=no_ping)

    @app_commands.command(name="낚시", description="물고기를 낚아 코인을 법니다 (3초 쿨다운)")
    async def fish(self, interaction: discord.Interaction):
        await self._do_fish(interaction)

    @app_commands.command(name="ㄴㅅ", description="낚시 (짧은 명령어) 🎣")
    async def fish_short(self, interaction: discord.Interaction):
        await self._do_fish(interaction)

    @app_commands.command(name="도감", description="지금까지 낚은 물고기 컬렉션을 봅니다")
    @app_commands.describe(멤버="확인할 멤버 (비우면 나)")
    async def dex(self, interaction: discord.Interaction, 멤버: discord.Member = None):
        member = 멤버 or interaction.user
        catches = vt.get_catches(interaction.guild.id, member.id)
        catchable = [f for f in FISH if f[2] > 0]  # 꽝 제외

        entries, found, shiny_found = [], 0, 0
        for name, emoji, value, weight, img in catchable:
            n = catches.get((name, 0), 0)
            s = catches.get((name, 1), 0)
            if n or s:
                found += 1
            if s:
                shiny_found += 1
            entries.append({"name": name, "img": img, "n": n, "s": s})

        total = len(catchable)
        title = f"{member.display_name} 님의 낚시 도감   발견 {found}/{total}  ·  ★반짝이 {shiny_found}/{total}"
        try:
            buf = dexcard.render_dex(entries, title, ASSETS_DIR, SHINY_DIR)
            await interaction.response.send_message(file=discord.File(buf, filename="dex.png"))
        except Exception as e:
            print(f"[경고] 도감 이미지 생성 실패, 텍스트로 대체: {e}")
            lines = [
                (f"{en['name']} ×{en['n']}" + (f" ★{en['s']}" if en["s"] else ""))
                if (en["n"] or en["s"]) else f"🔒 {en['name']}"
                for en in entries
            ]
            embed = discord.Embed(
                title=f"📖 {member.display_name} 님의 낚시 도감 ({found}/{total})",
                description="\n".join(lines),
                color=discord.Color.teal(),
            )
            await interaction.response.send_message(embed=embed)

    # ---- 도박 공통 ----
    def _validate_bet(self, gid: int, uid: int, bet: int):
        wallet = vt.get_balance(gid, uid)
        if bet < 1:
            return "1 코인 이상 걸어주세요."
        if bet > wallet:
            return f"코인이 부족해요. (잔액 {coins(wallet)})"
        return None

    # ---- 도박장: 슬롯 🎰 ----
    @app_commands.command(name="슬롯", description="슬롯머신 — 3개 맞추면 대박! (다시/절반/올인 버튼)")
    @app_commands.describe(베팅="걸 코인 (1 이상)")
    async def slot(self, interaction: discord.Interaction, 베팅: int):
        await self._start_slot(interaction, interaction.user, 베팅, from_button=False)

    async def _start_slot(self, interaction, user, bet, from_button, slow=False):
        gid = interaction.guild.id
        err = self._validate_bet(gid, user.id, bet)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        vt.add_balance(gid, user.id, -bet)  # 베팅 즉시 차감 (중복 클릭 방지)

        # GIF 렌더는 느린 기기(라즈베리파이 등)에서 수 초까지 걸린다. 응답부터 열어
        # 3초 제한을 피하고(슬래시는 '생각 중', 버튼은 조용히 — discord.py 가 알아서 구분),
        # 렌더는 스레드로 넘겨 그리는 동안 봇이 다른 명령어를 계속 받게 한다.
        await interaction.response.defer()

        reels, mult, result = _slot_spin()
        gif_buf, final_grid = await asyncio.to_thread(slotimage.spin_stop_gif, reels, slow=slow)
        content = f"🎰 **{coins(bet)}** 베팅!" + ("  😳 두근두근..." if slow else "")
        if from_button:
            message = interaction.message
            await message.edit(content=content, attachments=[discord.File(gif_buf, "slot.gif")], view=None)
        else:
            await interaction.edit_original_response(content=content, attachments=[discord.File(gif_buf, "slot.gif")])
            message = await interaction.original_response()

        await asyncio.sleep(2.3 if slow else 1.5)  # 릴이 순차로 멈추는 동안 대기

        payout = int(bet * mult)  # mult 이 소수(1.8)일 수 있어 정수화
        bal = vt.add_balance(gid, user.id, payout) if payout > 0 else vt.get_balance(gid, user.id)
        net = payout - bet
        sub = f"+{net:,}" if net >= 0 else f"-{-net:,}"
        result_img = slotimage.render_slot(final_grid, result, sub, win=mult > 0)
        await message.edit(
            content=f"잔액: {coins(bal)}",
            attachments=[discord.File(result_img, "slot.png")],
            view=GambleView(self, "slot", user.id, bet),
        )

    # ---- 도박장: 동전 🪙 ----
    @app_commands.command(name="동전", description="동전 던지기 — 앞/뒤 맞히면 2배 (다시/절반/올인 버튼)")
    @app_commands.describe(베팅="걸 코인 (1 이상)", 선택="앞 또는 뒤")
    @app_commands.choices(선택=[
        app_commands.Choice(name="앞", value="앞"),
        app_commands.Choice(name="뒤", value="뒤"),
    ])
    async def coinflip(self, interaction: discord.Interaction, 베팅: int, 선택: app_commands.Choice[str]):
        await self._start_coin(interaction, interaction.user, 베팅, 선택.value, from_button=False)

    async def _start_coin(self, interaction, user, bet, choice, from_button):
        gid = interaction.guild.id
        err = self._validate_bet(gid, user.id, bet)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return
        vt.add_balance(gid, user.id, -bet)  # 베팅 즉시 차감
        if from_button:
            await interaction.response.defer()
            message = interaction.message
        else:
            await interaction.response.send_message(f"🪙 **{choice}**에 {coins(bet)}! 동전을 던집니다...")
            message = await interaction.original_response()
        await self._animate_coin(message, user, bet, choice)

    async def _animate_coin(self, message, user, bet, choice):
        gid = message.guild.id
        result = random.choice(["앞", "뒤"])
        try:
            for frame in ("🪙 빙글~", "🔄 빙글빙글~", "🪙 빙글빙글빙글~"):
                await message.edit(content=f"**{choice}**에 {coins(bet)}\n{frame}", view=None)
                await asyncio.sleep(0.45)
        except discord.HTTPException:
            pass

        if result == choice:
            bal = vt.add_balance(gid, user.id, bet * 2)  # 원금 + 상금
            outcome = f"🎉 결과 **{result}**! 맞혔어요 **+{coins(bet)}**"
        else:
            bal = vt.get_balance(gid, user.id)
            outcome = f"😢 결과 **{result}**... 아쉽네요 **-{coins(bet)}**"
        await message.edit(
            content=f"🪙 **{choice}**에 베팅\n{outcome}\n잔액: {coins(bal)}",
            view=GambleView(self, "coin", user.id, bet, choice),
        )

    # ---- 도둑질 🕵️ ----
    @app_commands.command(name="도둑질", description="다른 사람의 지갑을 털어봅니다 (실패 시 벌금 → 경찰서)")
    @app_commands.describe(멤버="털 대상")
    async def steal(self, interaction: discord.Interaction, 멤버: discord.Member):
        gid, thief = interaction.guild.id, interaction.user
        if 멤버.id == thief.id or 멤버.bot:
            await interaction.response.send_message("제 지갑은 건드시면 안돼요!.", ephemeral=True)
            return

        left = self._cooldown_left(self._steal_cd, (gid, thief.id), STEAL_CD)
        if left:
            await interaction.response.send_message(f"⏳ 몸 좀 사려요. {format_cd(left)} 후에 다시!", ephemeral=True)
            return

        my_wallet = vt.get_balance(gid, thief.id)
        target_wallet = vt.get_balance(gid, 멤버.id)
        if target_wallet < STEAL_MIN:
            await interaction.response.send_message(
                f"{멤버.display_name} 님 지갑이 너무 비었어요. (은행 돈은 못 털어요 🏦)", ephemeral=True
            )
            return
        required = int(target_wallet * STEAL_CAPITAL)
        if my_wallet < required:
            await interaction.response.send_message(
                f"밑천이 부족해요! 이 사람을 털려면 지갑에 최소 **{coins(required)}** "
                f"(상대 지갑의 {int(STEAL_CAPITAL * 100)}%) 필요해요.",
                ephemeral=True,
            )
            return

        self._steal_cd[(gid, thief.id)] = time.time()  # 시도 소모

        if random.random() < STEAL_SUCCESS:
            amount = max(1, int(target_wallet * random.uniform(*STEAL_PCT)))
            vt.transfer(gid, 멤버.id, thief.id, amount)
            await interaction.response.send_message(
                f"🕵️ {thief.mention} 님이 {멤버.mention} 님의 지갑에서 **{coins(amount)}** 을(를) 훔쳤어요! 😈"
            )
        else:
            fine = max(1, int(my_wallet * STEAL_FINE))
            vt.add_balance(gid, thief.id, -fine)
            new_pool = vt.add_balance(gid, POLICE_ID, fine)
            await interaction.response.send_message(
                f"🚨 {thief.mention} 님이 도둑질에 실패! 벌금 **{coins(fine)}** 을(를) 냈어요.\n"
                f"🏛️ 경찰서 금고: {coins(new_pool)}"
            )

    # ---- 경찰서 금고 보기 ----
    @app_commands.command(name="경찰서", description="경찰서 금고에 쌓인 코인을 봅니다")
    async def police(self, interaction: discord.Interaction):
        pool = vt.get_balance(interaction.guild.id, POLICE_ID)
        await interaction.response.send_message(f"🏛️ 경찰서 금고: **{coins(pool)}**\n`/경찰서털기` 로 한탕 노려볼 수 있어요 (위험!)")

    # ---- 경찰서 털기 💣 ----
    @app_commands.command(name="경찰서털기", description="경찰서 금고를 통째로 노립니다 (하이리스크!)")
    async def rob_police(self, interaction: discord.Interaction):
        gid, thief = interaction.guild.id, interaction.user
        left = self._cooldown_left(self._rob_cd, (gid, thief.id), ROB_CD)
        if left:
            await interaction.response.send_message(f"⏳ 경계가 삼엄해요. {format_cd(left)} 후에!", ephemeral=True)
            return

        pool = vt.get_balance(gid, POLICE_ID)
        if pool < ROB_MIN_POOL:
            await interaction.response.send_message(f"🏛️ 경찰서 금고에 털 돈이 별로 없어요. (현재 {coins(pool)})", ephemeral=True)
            return
        my_wallet = vt.get_balance(gid, thief.id)
        if my_wallet < ROB_MIN_WALLET:
            await interaction.response.send_message(
                f"밑천이 부족해요! 경찰서를 털려면 지갑에 최소 **{coins(ROB_MIN_WALLET)}** 필요해요.",
                ephemeral=True,
            )
            return

        self._rob_cd[(gid, thief.id)] = time.time()

        if random.random() < ROB_SUCCESS:
            amount = max(1, int(pool * random.uniform(*ROB_PCT)))
            vt.transfer(gid, POLICE_ID, thief.id, amount)
            await interaction.response.send_message(
                f"💣🏛️ 대성공! {thief.mention} 님이 경찰서 금고에서 **{coins(amount)}** 을(를) 털었어요!! 🎉"
            )
        else:
            fine = max(1, int(my_wallet * ROB_FINE))
            vt.add_balance(gid, thief.id, -fine)
            new_pool = vt.add_balance(gid, POLICE_ID, fine)
            await interaction.response.send_message(
                f"🚔 {thief.mention} 님이 경찰서 털이에 실패! 체포되어 벌금 **{coins(fine)}** 납부.\n"
                f"🏛️ 경찰서 금고: {coins(new_pool)} (더 커졌어요!)"
            )

    # ---- 쿨다운 안내 ----
    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ 잠깐! {error.retry_after:.1f}초 후에 다시 시도해주세요.", ephemeral=True
            )
        elif isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("관리자 권한이 필요한 명령어예요.", ephemeral=True)
        elif isinstance(error, app_commands.CheckFailure):
            # owner_only() 가 막은 경우. 명령은 목록에 보이지만(서버 관리자에게)
            # 실행은 안 되므로, 왜 안 되는지 알려준다.
            await interaction.response.send_message(
                "이 명령은 **서버 소유자**만 쓸 수 있어요.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
