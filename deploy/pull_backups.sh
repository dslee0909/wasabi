#!/usr/bin/env bash
# 파이의 data.db 백업을 윈도우 PC 의 OneDrive 로 가져온다. (윈도우 Git Bash 에서 실행)
#
#   bash deploy/pull_backups.sh
#
# OneDrive 안에 두면 클라우드까지 자동으로 올라가서, SD 카드가 죽어도·집에 불이 나도
# 코인 데이터가 살아남는다. 파이 로컬 백업만으로는 카드와 함께 죽는다.
#
# 실행 전 확인: USB Wi-Fi 동글이 KT 망에 연결돼 있어야 파이가 보인다.
# (PC 내장 유선은 공인 IP 라 파이와 다른 네트워크다)

set -euo pipefail

PI="wasabi@wasabi.local"
DEST="${1:-/c/Users/user/OneDrive/wasabi-backups}"

mkdir -p "$DEST"

echo "파이에서 백업 목록 확인..."
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$PI" 'ls ~/bot-backups/*.db.gz >/dev/null 2>&1'; then
    echo "[중단] 파이에 백업이 없거나 접속이 안 됩니다."
    echo "       접속 실패라면 PC 의 Wi-Fi 동글 연결 상태부터 확인하세요."
    exit 1
fi

# -p 로 원본 시간 유지, 이미 있는 파일도 덮어쓰지만 내용이 같아 무해하다
scp -o BatchMode=yes -p -q "$PI":'~/bot-backups/*.db.gz' "$DEST/"

n=$(ls -1 "$DEST"/data-*.db.gz 2>/dev/null | wc -l)
echo "완료 — $DEST 에 백업 ${n}개"
echo "  최신: $(ls -1t "$DEST"/data-*.db.gz | head -1 | xargs basename)"
echo
echo "OneDrive 가 동기화하면 클라우드에도 사본이 생깁니다."
