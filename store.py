"""
간단한 설정 저장소 (store.py)

서버(길드)별 설정을 config.json 파일에 저장/불러오기 합니다.
- 봇이 꺼졌다 켜져도 설정이 유지됩니다.
- 활동시간/레벨 같은 대용량 데이터는 나중에 SQLite(data.db)로 따로 관리합니다.
  여기(config.json)는 '자동 역할 ID', '리액션 역할 매핑' 같은 가벼운 설정만 담습니다.

사용 예:
    from store import get_guild_config, update_guild_config
    cfg = get_guild_config(guild_id)          # dict 반환
    update_guild_config(guild_id, {"auto_role_id": 123})
"""

import json
import os
from typing import Any

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_all() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_guild_config(guild_id: int) -> dict:
    """해당 서버의 설정 dict를 반환한다 (없으면 빈 dict)."""
    return _load_all().get(str(guild_id), {})


def update_guild_config(guild_id: int, changes: dict[str, Any]) -> dict:
    """해당 서버 설정에 changes를 병합 저장하고, 갱신된 설정을 반환한다."""
    data = _load_all()
    key = str(guild_id)
    cfg = data.get(key, {})
    cfg.update(changes)
    data[key] = cfg
    _save_all(data)
    return cfg
