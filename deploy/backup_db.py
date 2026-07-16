#!/usr/bin/env python3
"""data.db 스냅샷 (deploy/backup_db.py)

sqlite3 의 온라인 백업 API 를 쓰므로 봇이 돌아가는 중에 실행해도 안전하다.
파일을 그냥 cp 로 복사하면 봇이 쓰는 도중의 DB 를 뜰 수 있어 깨진 사본이 나온다.

표준 라이브러리만 쓰므로 시스템 python3 로 돌린다 (봇의 venv 가 깨져도 백업은 돌아야 한다).

사용:  python3 deploy/backup_db.py [보관개수]     # 기본 30

백업 위치는 저장소 바깥(~/bot-backups)이다. git pull·재클론·저장소 삭제에
백업이 휩쓸리지 않게 하기 위함.
"""

import gzip
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data.db")
DEST = os.path.join(os.path.expanduser("~"), "bot-backups")
KEEP = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def snapshot() -> str:
    """봇을 멈추지 않고 일관된 스냅샷을 떠서 gzip 으로 저장한다."""
    os.makedirs(DEST, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(DEST, f"data-{stamp}.db.gz")

    tmp = os.path.join(DEST, f".tmp-{stamp}.db")
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)  # 온라인 백업 — 쓰기와 겹쳐도 일관성이 보장된다
    finally:
        dst.close()
        src.close()

    with open(tmp, "rb") as f_in, gzip.open(out, "wb") as f_out:
        f_out.writelines(f_in)
    os.remove(tmp)
    return out


def verify(path: str) -> tuple[str, int]:
    """압축을 풀어 실제로 열리는지 확인한다. 못 여는 백업은 백업이 아니다."""
    with gzip.open(path, "rb") as f:
        data = f.read()
    fd, tmp = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(tmp)
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]
        conn.close()
        return ok, rows
    finally:
        os.remove(tmp)


def prune() -> int:
    """최근 KEEP 개만 남기고 삭제."""
    files = sorted(
        (f for f in os.listdir(DEST)
         if f.startswith("data-") and f.endswith(".db.gz")),
        reverse=True,  # 파일명이 시간순이라 이름 정렬 = 시간 정렬
    )
    for f in files[KEEP:]:
        os.remove(os.path.join(DEST, f))
    return len(files[KEEP:])


def main() -> int:
    if not os.path.exists(DB):
        print(f"[오류] {DB} 가 없습니다.", file=sys.stderr)
        return 1

    out = snapshot()
    ok, rows = verify(out)
    if ok != "ok":
        print(f"[오류] 백업이 손상됐습니다: {ok}", file=sys.stderr)
        return 1

    removed = prune()
    print(f"백업 완료: {os.path.basename(out)} "
          f"({os.path.getsize(out):,} bytes, balances {rows}행, 무결성 {ok})")
    if removed:
        print(f"  오래된 백업 {removed}개 삭제 (최근 {KEEP}개 보관)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
