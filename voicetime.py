"""
음성시간 공용 도구 (voicetime.py)

레벨(cogs/leveling.py)과 활동/잠수 관리(cogs/activity.py)가 함께 쓰는
데이터 접근 + 시간 계산 함수 모음. 두 모듈은 같은 음성시간 데이터를 공유하되
기능(파일)만 분리되어 있습니다.

데이터: SQLite (data.db)
  voice_sessions(guild_id, user_id, seconds, ended_at)  # 종료된 세션 기록
"""

import math
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import discord

from store import get_guild_config

KST = timezone(timedelta(hours=9))  # 한국 시간

SPECTATE_PREFIX = "[관전] "  # cogs/spectate.py 와 동일해야 함
DEFAULT_WINDOW_DAYS = 30  # 활동 판단 기본 기간 (서버별로 /활동기간설정 으로 변경)
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


# ---- DB ----
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS voice_sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               guild_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               seconds INTEGER NOT NULL,
               ended_at REAL NOT NULL,
               channel_id INTEGER,
               started_at REAL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS messages (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               guild_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               channel_id INTEGER NOT NULL,
               ts REAL NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS achievements (
               guild_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               key TEXT NOT NULL,
               unlocked_at REAL NOT NULL,
               PRIMARY KEY (guild_id, user_id, key)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS balances (
               guild_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               coins INTEGER NOT NULL DEFAULT 0,
               bank INTEGER NOT NULL DEFAULT 0,
               rod INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (guild_id, user_id)
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fish_catches (
               guild_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               fish_key TEXT NOT NULL,
               shiny INTEGER NOT NULL DEFAULT 0,
               count INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (guild_id, user_id, fish_key, shiny)
           )"""
    )
    # 기존 DB 마이그레이션: 없으면 컬럼 추가 (이미 있으면 무시)
    for col, decl in (("channel_id", "INTEGER"), ("started_at", "REAL")):
        try:
            conn.execute(f"ALTER TABLE voice_sessions ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE balances ADD COLUMN bank INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE balances ADD COLUMN rod INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE balances ADD COLUMN rod_enhance INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE balances ADD COLUMN fish_earned INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return conn


def add_session(guild_id: int, user_id: int, seconds: int, channel_id: int = None, started_at: float = None):
    conn = db()
    conn.execute(
        "INSERT INTO voice_sessions (guild_id, user_id, seconds, ended_at, channel_id, started_at) "
        "VALUES (?,?,?,?,?,?)",
        (guild_id, user_id, seconds, time.time(), channel_id, started_at),
    )
    conn.commit()
    conn.close()


def total_seconds(guild_id: int, user_id: int) -> int:
    """전체 누적 음성 시간(초). 레벨(영구)에 사용."""
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) FROM voice_sessions WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchone()
    conn.close()
    return int(row[0])


def recent_seconds(guild_id: int, user_id: int) -> int:
    """최근 (설정 기간) 음성 시간(초). 승급/잠수 판단에 사용."""
    cutoff = time.time() - window_seconds(guild_id)
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) FROM voice_sessions "
        "WHERE guild_id=? AND user_id=? AND ended_at>=?",
        (guild_id, user_id, cutoff),
    ).fetchone()
    conn.close()
    return int(row[0])


def voice_seconds_days(guild_id: int, user_id: int, days: float) -> int:
    """최근 N일 음성 시간(초). 스탯 카드의 1/7/30일 표시에 사용."""
    cutoff = time.time() - days * 86400
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(SUM(seconds), 0) FROM voice_sessions "
        "WHERE guild_id=? AND user_id=? AND ended_at>=?",
        (guild_id, user_id, cutoff),
    ).fetchone()
    conn.close()
    return int(row[0])


# ---- 메시지 ----
def add_message(guild_id: int, user_id: int, channel_id: int):
    conn = db()
    conn.execute(
        "INSERT INTO messages (guild_id, user_id, channel_id, ts) VALUES (?,?,?,?)",
        (guild_id, user_id, channel_id, time.time()),
    )
    conn.commit()
    conn.close()


def message_count_days(guild_id: int, user_id: int, days: float) -> int:
    """최근 N일 메시지 수."""
    cutoff = time.time() - days * 86400
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE guild_id=? AND user_id=? AND ts>=?",
        (guild_id, user_id, cutoff),
    ).fetchone()
    conn.close()
    return int(row[0])


def message_count_total(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchone()
    conn.close()
    return int(row[0])


def started_hours(guild_id: int, user_id: int) -> set:
    """이 사람이 음성 세션을 시작한 적 있는 시간대(0~23, 한국시간) 집합."""
    conn = db()
    rows = conn.execute(
        "SELECT started_at FROM voice_sessions "
        "WHERE guild_id=? AND user_id=? AND started_at IS NOT NULL",
        (guild_id, user_id),
    ).fetchall()
    conn.close()
    return {datetime.fromtimestamp(s, KST).hour for (s,) in rows}


# ---- 업적 ----
def unlocked_achievements(guild_id: int, user_id: int) -> set:
    conn = db()
    rows = conn.execute(
        "SELECT key FROM achievements WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def unlock_achievement(guild_id: int, user_id: int, key: str):
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO achievements (guild_id, user_id, key, unlocked_at) VALUES (?,?,?,?)",
        (guild_id, user_id, key, time.time()),
    )
    conn.commit()
    conn.close()


# ---- 코인(재화) ----
def get_balance(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT coins FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def add_balance(guild_id: int, user_id: int, amount: int) -> int:
    """코인을 더하거나(음수면 빼고) 갱신 후 잔액 반환."""
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO balances (guild_id, user_id, coins) VALUES (?,?,0)",
        (guild_id, user_id),
    )
    conn.execute(
        "UPDATE balances SET coins = coins + ? WHERE guild_id=? AND user_id=?",
        (amount, guild_id, user_id),
    )
    row = conn.execute(
        "SELECT coins FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.commit()
    conn.close()
    return int(row[0])


def add_catch(guild_id: int, user_id: int, fish_key: str, shiny: bool):
    """낚시 도감에 한 마리 기록 (일반/반짝이 구분)."""
    s = 1 if shiny else 0
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO fish_catches (guild_id, user_id, fish_key, shiny, count) VALUES (?,?,?,?,0)",
        (guild_id, user_id, fish_key, s),
    )
    conn.execute(
        "UPDATE fish_catches SET count = count + 1 "
        "WHERE guild_id=? AND user_id=? AND fish_key=? AND shiny=?",
        (guild_id, user_id, fish_key, s),
    )
    conn.commit()
    conn.close()


def fishing_leaderboard(guild_id: int, limit: int = 10):
    """(user_id, 총 마릿수, 반짝이 수, 도감 종수) 상위 목록."""
    conn = db()
    rows = conn.execute(
        "SELECT user_id, SUM(count) AS total, "
        "SUM(CASE WHEN shiny=1 THEN count ELSE 0 END) AS shiny, "
        "COUNT(DISTINCT fish_key) AS species "
        "FROM fish_catches WHERE guild_id=? GROUP BY user_id ORDER BY total DESC LIMIT ?",
        (guild_id, limit),
    ).fetchall()
    conn.close()
    return rows


def get_fishing_stats(guild_id: int, user_id: int):
    """(총 마릿수, 반짝이 수, 도감 종수)."""
    conn = db()
    row = conn.execute(
        "SELECT COALESCE(SUM(count),0), "
        "COALESCE(SUM(CASE WHEN shiny=1 THEN count ELSE 0 END),0), "
        "COUNT(DISTINCT fish_key) FROM fish_catches WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchone()
    conn.close()
    return int(row[0]), int(row[1]), int(row[2])


def fishing_rank(guild_id: int, user_id: int):
    """(내 순위, 전체 인원) — 총 마릿수 기준."""
    conn = db()
    rows = conn.execute(
        "SELECT user_id FROM fish_catches WHERE guild_id=? GROUP BY user_id ORDER BY SUM(count) DESC",
        (guild_id,),
    ).fetchall()
    conn.close()
    for i, (uid,) in enumerate(rows, start=1):
        if uid == user_id:
            return i, len(rows)
    return None, len(rows)


def get_catches(guild_id: int, user_id: int) -> dict:
    """{(fish_key, shiny): count} 형태로 도감 데이터 반환."""
    conn = db()
    rows = conn.execute(
        "SELECT fish_key, shiny, count FROM fish_catches WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    ).fetchall()
    conn.close()
    return {(k, s): c for k, s, c in rows}


def top_balances(guild_id: int, limit: int = 10):
    """(user_id, 총자산=지갑+은행) 상위 목록."""
    conn = db()
    rows = conn.execute(
        "SELECT user_id, coins + bank AS total FROM balances "
        "WHERE guild_id=? AND user_id <> 0 ORDER BY total DESC LIMIT ?",  # user_id 0 = 경찰서 금고(제외)
        (guild_id, limit),
    ).fetchall()
    conn.close()
    return rows


# ---- 은행 / 송금 ----
def get_bank(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT bank FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def deposit(guild_id: int, user_id: int, amount: int) -> bool:
    """지갑 → 은행. 지갑 잔액 부족하면 False."""
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
    row = conn.execute(
        "SELECT coins FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    if row is None or row[0] < amount:
        conn.close()
        return False
    conn.execute(
        "UPDATE balances SET coins = coins - ?, bank = bank + ? WHERE guild_id=? AND user_id=?",
        (amount, amount, guild_id, user_id),
    )
    conn.commit()
    conn.close()
    return True


def withdraw(guild_id: int, user_id: int, amount: int) -> bool:
    """은행 → 지갑. 은행 잔액 부족하면 False."""
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
    row = conn.execute(
        "SELECT bank FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    if row is None or row[0] < amount:
        conn.close()
        return False
    conn.execute(
        "UPDATE balances SET bank = bank - ?, coins = coins + ? WHERE guild_id=? AND user_id=?",
        (amount, amount, guild_id, user_id),
    )
    conn.commit()
    conn.close()
    return True


def apply_interest(guild_id: int, rate: float):
    """은행 잔액에 이자를 붙인다 (bank += floor(bank * rate))."""
    conn = db()
    conn.execute(
        "UPDATE balances SET bank = bank + CAST(bank * ? AS INTEGER) WHERE guild_id=? AND bank > 0",
        (rate, guild_id),
    )
    conn.commit()
    conn.close()


def get_rod(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT rod FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def set_rod(guild_id: int, user_id: int, tier: int):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
    conn.execute("UPDATE balances SET rod=? WHERE guild_id=? AND user_id=?", (tier, guild_id, user_id))
    conn.commit()
    conn.close()


def get_fish_earned(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT fish_earned FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0


def add_fish_earned(guild_id: int, user_id: int, amount: int):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
    conn.execute("UPDATE balances SET fish_earned = fish_earned + ? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
    conn.commit()
    conn.close()


def get_rod_enhance(guild_id: int, user_id: int) -> int:
    conn = db()
    row = conn.execute(
        "SELECT rod_enhance FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0


def set_rod_enhance(guild_id: int, user_id: int, level: int):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
    conn.execute("UPDATE balances SET rod_enhance=? WHERE guild_id=? AND user_id=?", (level, guild_id, user_id))
    conn.commit()
    conn.close()


def transfer(guild_id: int, from_id: int, to_id: int, amount: int) -> bool:
    """지갑 → 다른 사람 지갑. 보내는 사람 지갑 부족하면 False."""
    conn = db()
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, from_id))
    conn.execute("INSERT OR IGNORE INTO balances (guild_id, user_id) VALUES (?,?)", (guild_id, to_id))
    row = conn.execute(
        "SELECT coins FROM balances WHERE guild_id=? AND user_id=?", (guild_id, from_id)
    ).fetchone()
    if row is None or row[0] < amount:
        conn.close()
        return False
    conn.execute(
        "UPDATE balances SET coins = coins - ? WHERE guild_id=? AND user_id=?", (amount, guild_id, from_id)
    )
    conn.execute(
        "UPDATE balances SET coins = coins + ? WHERE guild_id=? AND user_id=?", (amount, guild_id, to_id)
    )
    conn.commit()
    conn.close()
    return True


# ---- 순위 (최근 30일 기준) ----
def voice_rank(guild_id: int, user_id: int, days: int = 30) -> tuple[int | None, int]:
    """(내 순위, 전체 인원). 순위는 최근 N일 음성 시간 기준."""
    cutoff = time.time() - days * 86400
    conn = db()
    rows = conn.execute(
        "SELECT user_id FROM voice_sessions WHERE guild_id=? AND ended_at>=? "
        "GROUP BY user_id ORDER BY SUM(seconds) DESC",
        (guild_id, cutoff),
    ).fetchall()
    conn.close()
    for i, (uid,) in enumerate(rows, start=1):
        if uid == user_id:
            return i, len(rows)
    return None, len(rows)


def message_rank(guild_id: int, user_id: int, days: int = 30) -> tuple[int | None, int]:
    """(내 순위, 전체 인원). 순위는 최근 N일 메시지 수 기준."""
    cutoff = time.time() - days * 86400
    conn = db()
    rows = conn.execute(
        "SELECT user_id FROM messages WHERE guild_id=? AND ts>=? "
        "GROUP BY user_id ORDER BY COUNT(*) DESC",
        (guild_id, cutoff),
    ).fetchall()
    conn.close()
    for i, (uid,) in enumerate(rows, start=1):
        if uid == user_id:
            return i, len(rows)
    return None, len(rows)


# ---- 기간(윈도우) ----
def window_days(guild_id: int) -> int:
    return int(get_guild_config(guild_id).get("activity_window_days", DEFAULT_WINDOW_DAYS))


def window_seconds(guild_id: int) -> int:
    return window_days(guild_id) * 24 * 60 * 60


# ---- 레벨/표시 계산 ----
def level_params(guild_id: int) -> tuple[float, float]:
    """(기준시간, 곡선). 서버별 /레벨설정 으로 조절. 기본 (1.0, 2.0) = 기존 √곡선."""
    cfg = get_guild_config(guild_id)
    base = float(cfg.get("level_base_hours", 1.0))
    exponent = float(cfg.get("level_exponent", 2.0))
    return base, exponent


def hours_to_level(hours: float, guild_id: int) -> int:
    """누적 시간(시간) → 레벨. 레벨 n = 기준시간 × n^곡선 시간 필요."""
    base, exponent = level_params(guild_id)
    if hours < base:
        return 0
    return int((hours / base) ** (1 / exponent))


def level_to_hours(level: int, guild_id: int) -> float:
    """레벨 n 에 도달하는 데 필요한 누적 시간(시간)."""
    base, exponent = level_params(guild_id)
    return base * (level ** exponent)


def format_duration(seconds: float) -> str:
    """초 → '1시간 5분' / '12분' 형태의 읽기 쉬운 문자열."""
    total_min = int(seconds // 60)
    h, m = divmod(total_min, 60)
    if h and m:
        return f"{h}시간 {m}분"
    if h:
        return f"{h}시간"
    return f"{m}분"


# ---- 집계 대상 판단 ----
def is_spectating(member: discord.Member) -> bool:
    return member.display_name.startswith(SPECTATE_PREFIX)


def channel_countable(guild_id: int, channel) -> bool:
    if channel is None:
        return False
    excluded = get_guild_config(guild_id).get("leveling_excluded_channels", [])
    return channel.id not in excluded


def countable(member: discord.Member, channel) -> bool:
    """이 멤버의 지금 상태를 시간 집계 대상으로 볼지 (제외채널·관전 반영)."""
    return channel_countable(member.guild.id, channel) and not is_spectating(member)


# ---- 분석: 케미(듀오) / 골든타임 ----
def best_duos(guild_id: int, user_id: int, days: int = 30, limit: int = 5):
    """(상대 user_id, 함께 음성에 있던 초) 목록. 같은 방·같은 시간대 겹침으로 계산."""
    cutoff = time.time() - days * 86400
    conn = db()
    mine = conn.execute(
        "SELECT channel_id, started_at, ended_at FROM voice_sessions "
        "WHERE guild_id=? AND user_id=? AND started_at IS NOT NULL AND ended_at>=?",
        (guild_id, user_id, cutoff),
    ).fetchall()
    others = conn.execute(
        "SELECT user_id, channel_id, started_at, ended_at FROM voice_sessions "
        "WHERE guild_id=? AND user_id<>? AND started_at IS NOT NULL AND ended_at>=?",
        (guild_id, user_id, cutoff),
    ).fetchall()
    conn.close()

    overlap: dict[int, float] = defaultdict(float)
    for mc, ms, me in mine:
        for ouid, oc, os_, oe in others:
            if oc != mc:
                continue
            lo, hi = max(ms, os_), min(me, oe)
            if hi > lo:
                overlap[ouid] += hi - lo
    ranked = sorted(overlap.items(), key=lambda x: -x[1])
    return ranked[:limit]


def activity_by_hour(guild_id: int, days: int = 30, user_id: int = None) -> list[float]:
    """한국시간 기준 시간대(0~23)별 음성 초 합계. user_id 주면 그 사람만."""
    cutoff = time.time() - days * 86400
    query = (
        "SELECT started_at, seconds FROM voice_sessions "
        "WHERE guild_id=? AND started_at IS NOT NULL AND ended_at>=?"
    )
    params = [guild_id, cutoff]
    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)
    conn = db()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    hours = [0.0] * 24
    for started_at, seconds in rows:
        h = datetime.fromtimestamp(started_at, KST).hour
        hours[h] += seconds
    return hours


def sparkline(values: list[float]) -> str:
    """숫자 목록 → 미니 막대그래프 문자열 (▁▂▃▄▅▆▇█)."""
    blocks = "▁▂▃▄▅▆▇█"
    peak = max(values) if values else 0
    if peak <= 0:
        return blocks[0] * len(values)
    return "".join(blocks[min(7, int(v / peak * 7))] for v in values)
