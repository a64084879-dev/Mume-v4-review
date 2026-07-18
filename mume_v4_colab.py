#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
# a1_retry.sh — 오라클 A1.Flex(무료 ARM 4core/24GB) 자동 재시도 생성기
#   Tokyo AD-1이 상시 용량부족이라, 자리가 날 때까지 5분 간격으로 계속 시도한다.
#   성공하면 텔레그램으로 알리고 중단. (E2 봇은 그대로 두고, A1은 여유될 때 이전.)
#
# 사용법: bash a1_retry.sh
#   (Cloud Shell에서 실행. 세션 끊기면 멈추니, 가끔 Cloud Shell을 확인할 것.)
#
# ★ 이미 수집한 정보(2026-07-18):
#   Compartment = 테넌시 루트
#   AD          = AGlr:AP-TOKYO-1-AD-1  (Tokyo는 AD 1개뿐)
#   Subnet      = 기존 VCN의 public subnet
#   ARM 이미지·SSH키는 아래에서 자동 조회/생성.
# ══════════════════════════════════════════════════════════════════════
set -uo pipefail

# ── 고정 정보(수집 완료) ──
COMPARTMENT="ocid1.tenancy.oc1..aaaaaaaafem3npnlzmxizihnscnmd7xhytrszmp4ha37tjwtodhzlwxxxuna"
AD="AGlr:AP-TOKYO-1-AD-1"
SUBNET="ocid1.subnet.oc1.ap-tokyo-1.aaaaaaaamg4haby6s5madbgkhwkw3kiqzblmof7cq3oucahhl3lixvroonvq"
DISPLAY_NAME="toss-bot-arm"
OCPUS=4
MEM_GB=24

# ── 텔레그램(토스 봇과 동일) — 성공 시 알림 ──
TG_TOKEN="${TG_TOKEN:-}"
TG_CHAT="${TG_CHAT:-267024555}"

tg() {  # 텔레그램 메시지 전송
  curl -s -m 10 "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT}" \
    --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

echo "════════════════════════════════════════"
echo " A1.Flex 자동 재시도 시작"
echo "════════════════════════════════════════"

# ── 1) ARM용 Oracle Linux 9 이미지 자동 조회 ──
echo "[1/3] ARM 이미지 조회 중..."
IMAGE=$(~/.local/bin/oci compute image list \
  --compartment-id "$COMPARTMENT" \
  --operating-system "Oracle Linux" \
  --operating-system-version "9" \
  --shape "VM.Standard.A1.Flex" \
  --sort-by TIMECREATED --sort-order DESC \
  --query "data[0].id" --raw-output 2>/dev/null)

if [ -z "$IMAGE" ] || [ "$IMAGE" = "null" ]; then
  echo "❌ ARM 이미지 조회 실패. 수동 확인 필요."
  exit 1
fi
echo "    이미지: ${IMAGE:0:50}..."

# ── 2) SSH 공개키 준비(없으면 생성) ──
echo "[2/3] SSH 키 준비 중..."
KEY="$HOME/.ssh/a1_toss_key"
if [ ! -f "${KEY}.pub" ]; then
  ssh-keygen -t rsa -b 2048 -f "$KEY" -N "" -q
  echo "    새 키 생성: ${KEY}(.pub)"
else
  echo "    기존 키 사용: ${KEY}.pub"
fi
PUBKEY_FILE="${KEY}.pub"

# ── 3) 자리 날 때까지 재시도 ──
echo "[3/3] 인스턴스 생성 재시도(5분 간격)..."
echo ""
ATTEMPT=0
tg "🔄 A1.Flex 자동 재시도 시작(5분 간격). 자리 나면 알림 갑니다."

while true; do
  ATTEMPT=$((ATTEMPT+1))
  TS=$(date '+%Y-%m-%d %H:%M:%S')
  echo -n "[시도 ${ATTEMPT} · ${TS}] "

  OUT=$(~/.local/bin/oci compute instance launch \
    --availability-domain "$AD" \
    --compartment-id "$COMPARTMENT" \
    --shape "VM.Standard.A1.Flex" \
    --shape-config "{\"ocpus\":${OCPUS},\"memoryInGBs\":${MEM_GB}}" \
    --subnet-id "$SUBNET" \
    --image-id "$IMAGE" \
    --display-name "$DISPLAY_NAME" \
    --assign-public-ip true \
    --ssh-authorized-keys-file "$PUBKEY_FILE" \
    --wait-for-state RUNNING \
    2>&1)
  RC=$?

  if [ $RC -eq 0 ]; then
    echo "✅ 성공!"
    NEWID=$(echo "$OUT" | grep -o 'ocid1.instance[a-z0-9.]*' | head -1)
    echo ""
    echo "════════════════════════════════════════"
    echo " 🎉 A1.Flex 생성 성공!"
    echo " 인스턴스: $NEWID"
    echo " SSH 키: $KEY"
    echo "════════════════════════════════════════"
    tg "🎉 A1.Flex(4core/24GB) 확보 성공! 시도 ${ATTEMPT}회 만에. 이제 봇 이전 작업 하세요. SSH키: a1_toss_key"
    break
  fi

  # 실패 원인 판정
  #  · 용량부족(Out of capacity): 자리 없음 → 계속 재시도
  #  · TooManyRequests(429): API 호출 과다 → 잠깐 더 쉬고 재시도(중단 아님)
  #  · 그 외(설정오류 등): 재시도해도 소용없음 → 중단
  if echo "$OUT" | grep -qi "Out of capacity\|out of host capacity"; then
    echo "용량부족 → 10분 후 재시도"
    sleep 600    # 10분
  elif echo "$OUT" | grep -qi "TooManyRequests\|Too Many Requests\|429\|rate.*limit"; then
    echo "API 제한(TooManyRequests) → 15분 쉬고 재시도"
    sleep 900    # 15분 (API 제한은 더 오래 쉼)
  else
    # 용량부족·API제한이 아닌 진짜 에러(설정 문제 등) → 중단
    echo "❌ 설정 오류 의심 — 중단하고 확인 필요:"
    echo "$OUT" | head -5
    tg "⚠️ A1 재시도 중단 — 설정 오류 의심(용량·API제한 아님). 로그 확인 필요."
    exit 1
  fi
done
