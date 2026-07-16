#!/usr/bin/env bash
# 라즈베리파이에 와사비 봇을 설치한다. 여러 번 돌려도 안전(멱등).
#
# 사용법:  cd ~/Bot && bash deploy/setup_pi.sh
#
# 주의: 이 스크립트는 마지막에 봇을 띄운다. 윈도우 PC 의 봇이 아직 켜져 있으면
#       한 명령어에 봇이 두 번 응답하므로, 먼저 윈도우 쪽을 꺼야 한다.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(id -un)"
SERVICE="wasabi-bot"
cd "$DIR"

echo "설치 위치  : $DIR"
echo "실행 사용자: $RUN_USER"
echo

# --- 1. 수동으로 옮겨왔어야 하는 파일 확인 -----------------------------------
# .env / data.db / config.json / seguiemj.ttf 는 전부 .gitignore 대상이라
# git clone 으로는 따라오지 않는다. 없어도 봇은 뜨지만 조용히 잘못 동작한다.
if [ ! -f .env ]; then
    echo "[중단] .env 가 없습니다 — 토큰이 없으면 봇이 로그인하지 못합니다."
    echo "       윈도우 PC 에서 .env 를 복사해 오세요."
    exit 1
fi
chmod 600 .env  # 토큰은 본인만 읽게

warn=0
if [ ! -f assets/fonts/seguiemj.ttf ]; then
    echo "[경고] assets/fonts/seguiemj.ttf 없음 → 슬롯 심볼과 카드 아이콘이 □ 로 나옵니다."
    warn=1
fi
if [ ! -f data.db ]; then
    echo "[경고] data.db 없음 → 코인·물고기·레벨이 전부 빈 새 DB 로 시작합니다."
    warn=1
fi
if [ ! -f config.json ]; then
    echo "[경고] config.json 없음 → 서버별 설정(자동 역할 등)이 초기화됩니다."
    warn=1
fi
if [ "$warn" = 1 ]; then
    echo "       위 파일들을 옮긴 뒤 다시 실행하는 걸 권장합니다."
    echo
fi

# --- 2. 파이썬 환경 -----------------------------------------------------------
echo "== 시스템 패키지"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip

echo "== 가상환경 + 의존성"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --upgrade -q pip
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/python -c "import discord, PIL; print(f'  discord.py {discord.__version__} / Pillow {PIL.__version__}')"

# --- 3. 봇을 띄우기 전에 렌더러/폰트 점검 -------------------------------------
# 폰트가 빠지면 예외가 아니라 두부(□)로 조용히 깨지므로 여기서 미리 확인한다.
echo "== 폰트/렌더러 점검"
./.venv/bin/python - <<'PY'
import fonts
print(f"  텍스트 폰트: {fonts.TEXT_PATH}")
print(f"  이모지 폰트: {fonts.EMOJI_PATH}")
import dexcard, forge, rodcard, slotimage  # noqa: F401
print("  렌더러 임포트 OK")
PY

# --- 4. systemd 서비스 --------------------------------------------------------
echo "== systemd 서비스 설치"
install_unit() {  # $1: deploy/ 안의 유닛 파일명
    sed -e "s|__USER__|$RUN_USER|g" -e "s|__DIR__|$DIR|g" \
        "deploy/$1" | sudo tee "/etc/systemd/system/$1" >/dev/null
}
install_unit wasabi-bot.service
install_unit wasabi-backup.service
install_unit wasabi-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE" >/dev/null
sudo systemctl restart "$SERVICE"

# 매일 data.db 백업 (~/bot-backups, 최근 30개 보관)
sudo systemctl enable --now wasabi-backup.timer >/dev/null

sleep 3
echo
sudo systemctl status "$SERVICE" --no-pager --lines=5 || true
echo
echo "완료."
echo "  로그 보기   : journalctl -u $SERVICE -f"
echo "  재시작      : sudo systemctl restart $SERVICE"
echo "  끄기        : sudo systemctl stop $SERVICE"
echo "  백업 상태   : systemctl list-timers wasabi-backup"
echo "  지금 백업   : sudo systemctl start wasabi-backup.service"
