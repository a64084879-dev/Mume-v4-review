자기 감사하겠습니다. 파일을 디스크에 올리고 기계적 검사부터 돌립니다.Static verification of both files against the bot/adapter surfaceStatic verification of both files against the bot/adapter surface문법은 통과. 이제 논리 검증 — 가드가 실제로 막는지 시뮬레이션으로 확인합니다.명령 2개 실행함명령 2개 실행함가드가 뚫렸습니다. 시뮬레이션이 증명합니다:
시나리오결과A ovrs_pdno ✅ 있는데 ovrs_cblc_qty만 이름 다름가드 통과 → get_holdings=0주 → "🔵 실보유 0 확인 — CASH 확정" ← 3000주 그대로 있는데 대피 완료로 기록. 막으려던 무음실패가 그대로 재현B pdno ✅ 있는데 nccs_qty만 이름 다름가드 통과 → list_open_orders=[] → cancel-first 통과 → 이중 사다리C ord_dt 이름 다름가드 발동 — 단 우연히. 진단명은 "ccnl 다행"인데 실제 원인은 ord_dt 누락
원인: _EXPECT가 식별자 필드(pdno)만 검사하고 수량 필드를 안 봤습니다. 그런데 무음실패를 만드는 건 수량 필드입니다. 어댑터가 실제로 dereference 하는 건:
balance : ovrs_pdno, ovrs_cblc_qty, pchs_avg_pric
nccs    : pdno, odno, nccs_qty, sll_buy_dvsn_cd, ft_ord_unpr3
ccnl    : pdno, odno, ft_ccld_qty, ft_ccld_unpr3, sll_buy_dvsn_cd, ord_dt
ord_dt가 특히 중요합니다. sync_fills의 dedup 키가 {filled_at}:{odno}:{side}인데, KIS ODNO는 일자별 채번입니다. ord_dt가 누락되면 filled_at="" → 다른 날 같은 번호 주문이 키 충돌 → delta 음수 → 체결 유실.
수정 후 재검증:Patch _EXPECT to cover all dereferenced fields and re-run the three scenariosPatch _EXPECT to cover all dereferenced fields and re-run the three scenarios가드가 수정 후 3건 모두 정상 발동합니다 (A는 이제 INVESTED 유지 + evac_pending + 🚨🚨).
이제 발견 사항 전체를 정리하고 두 파일을 고쳐 다시 냅니다.

🔴 치명 3건 (내 코드의 결함)
F1. 스키마 가드가 정작 위험한 필드를 안 본다 — 위 시나리오 A/B로 실증. 식별자(pdno)만 보고 수량 필드를 안 봐서, 가드가 막겠다고 선언한 두 실패(킬스위치 무음실패·이중 사다리)가 그대로 통과했습니다.
F2. ord_dt 누락 위험 미검사 — KIS ODNO는 일자별 채번이라, filled_at=""이 되면 다른 날 같은 번호가 dedup 키에서 충돌 → 체결 유실. 덤으로 sync_fills의 프루닝(k.split(":")[0])도 빈 문자열이 되어 fills_seen이 무한 증가합니다.
F3. preflight _row_structure가 ODNO만으로 중복 판정 — P5는 14일 창을 조회하는데 ODNO는 일자별 채번 → 다른 날 같은 ODNO를 "주문당 다행 🔴🔴"으로 오탐. 러너 쪽은 ord_dt:odno로 맞게 짰는데 preflight만 틀려서, 두 도구의 판정이 서로 어긋납니다.
🟠 중대 4건
F4. DRY_RUN=on은 KIS를 아무것도 테스트하지 않는다 — G2가 공회전.
sync_fills·reconcile·rotate_cycle이 전부 if dry_run: return → get_holdings/list_open_orders/get_fills 한 번도 호출 안 됨 → 스키마 가드가 단 한 번도 발동하지 않습니다. 제가 설계한 G2 게이트는 봇 원본이 이미 하던 일만 반복하는 셈이었습니다. → 조회 전용 probe 필요.
F5. 프리플라이트 체결이 러너 첫 실행에 빨려들어간다. since=rolling_since(5) 창 안에 preflight의 1주 매수/매도가 들어 있어 첫 sync_fills가 그걸 포지션에 반영합니다. → SYNC_SINCE 하한 필요.
F6. 기존 07:37 크론을 끄지 않으면 AUTO_MODE 가드가 무력. 가드는 러너의 monkeypatch입니다. vr_signal_bot.py가 자기 크론으로 계속 돌면 **패치 안 된 apply_command**가 /buy를 그대로 받습니다 → 이중반영. 게다가 두 프로세스가 vr_position.json·offset 파일을 동시에 씁니다. 기존 워크플로 삭제가 전제조건입니다 (코드로 못 막습니다).
F7. preflight P13 판정 오염. P10 매수가 20초 내 미체결이면 보유 0 → P13 매도는 잔고부족으로 거부 → SLL_TYPE=00 🔴 거부로 오판정.
🟡 정합성 질문 1건 — 답이 필요합니다
F8. 확정 스펙은 LOC인데, 코드는 LOC를 한 번도 호출하지 않습니다.
_place_ladder      → OrderReq(..., "LIMIT", ...)   하드코딩
killswitch_evacuate → "LIMIT"
recover_enter       → "LIMIT"
→ 어댑터의 _ord_dvsn LOC(34)/MOC(33)/MOO(31) 매핑은 호출자가 없는 데드코드입니다. "LOC 채택 확정"과 "지정가 사다리 실행"이 병존합니다. 어느 쪽이 확정인지 확인이 필요하고, 만약 LOC가 맞다면 실전 전환 시 LOC 경로가 단 한 번도 검증 안 된 채 처음 쓰이게 됩니다(모의는 ORD_DVSN=00만 지원).

수정본:명령 2개 실행함, 파일 읽음명령 2개 실행함, 파일 읽음rev.2 반영 내역
수정F1_EXPECT를 어댑터가 실제 dereference 하는 필드 전부로 확장 (ovrs_cblc_qty, nccs_qty, ft_ccld_qty 포함). 시나리오 A/B 재검증 → 이제 🚨🚨 + INVESTED 유지F2ord_dt를 _EXPECT["fills"]·preflight 가정 필드에 필수 포함F3preflight 행구조 판정을 (ord_dt, odno) 복합키로 — 러너의 dedup 키와 일치. ord_dt 부재 시 별도 🔴 경보F4probe() 추가 — DRY에서도 get_price/get_holdings/list_open_orders/get_fills를 실제로 호출. G2가 비로소 스키마 가드를 발동시킴F5SYNC_SINCE 하한 옵션 (프리플라이트 체결 차단)F7preflight P13이 보유 0이면 ⚪ 스킵 (잔고부족을 SLL_TYPE 거부로 오판 방지)🟢알림 버퍼링(경보는 즉시, 나머지는 리포트에 합류) / P3가 어댑터 실제 파라미터(unpr=0) 시험 / USD 예수금 0 조기경보

은박사님 결정이 필요한 2건 — 코드로 못 막습니다
F6. 기존 07:37 크론. AUTO_MODE 가드는 러너의 monkeypatch입니다. vr_signal_bot.py가 자기 워크플로로 계속 돌면 **패치 안 된 apply_command**가 /buy를 그대로 받고, 두 프로세스가 vr_position.json을 동시에 씁니다.
→ 선택: (a) 기존 워크플로 삭제 (권장, 러너가 리포트도 보냄) 또는 (b) 봇에 3줄 이식(봇 무수정 원칙 파기). (a)를 권합니다.
F8. LOC vs 지정가 사다리. _place_ladder·killswitch_evacuate·recover_enter 전부 order_kind="LIMIT" 하드코딩 → 어댑터의 LOC(34)/MOC(33)/MOO(31) 매핑은 호출자가 없는 데드코드입니다. 확정 스펙("LOC 채택")과 실행 코드가 어긋나 있습니다.
→ 어느 쪽이 확정인지 알려주시면 정리하겠습니다. LOC가 맞다면, 모의는 ORD_DVSN=00만 지원하므로 LOC 경로는 실전 전환 때 처음 실행됩니다 — 게이트에 "실전 1주로 LOC(34) 실측" 항목을 추가해야 합니다.

게이트 (rev.2)
G0  python kis_mock_preflight.py            아무때나   조회 필드 확정
G1  python kis_mock_preflight.py --order    ★미국장★  ord_dt·행구조·SLL_TYPE·보유매치
    ↓ 🔴 0건 확인 후에만
G2  DRY_RUN=on  vr_auto_runner_kis.py       아무때나   probe가 스키마 가드 발동 + 사다리 예고
G3  DRY_RUN=off AUTO_MODE=on  크론 23:40    2주 1사이클  매일 reconcile 통과
G3 진입 전 SYNC_SINCE를 G1 다음날로 설정하고, 모의계좌 잔고를 정리한 뒤 /setpos로 실제 상태를 등록하십시오. 그러지 않으면 프리플라이트 테스트 체결이 첫 sync에 흡수됩니다.
G0 원문 덤프 주시면 필드 확정하겠습니다.알겠습니다. 코드 없이 조언만 드립니다.
지금 상태 한 줄 요약
어댑터·프레임워크·봇은 다 있는데 셋을 잇는 러너가 없습니다. 그리고 KIS 응답 필드 6종이 아직 [부분확인]이라, 그 상태로 배선하면 필드명 하나 틀린 것만으로 킬스위치가 조용히 실패합니다(get_holdings가 0주 반환 → "실보유 0 확인 — CASH 확정"). 이게 최우선 리스크입니다.
순서
1. 먼저 필드 실측. 코드 짜기 전에, 모의계좌에서 잔고·미체결·체결·매수가능 응답을 원문 그대로 한 번 받아보십시오. 어댑터를 통해 조회하면 안 됩니다 — 틀린 가정이 0이나 빈 리스트로 은폐됩니다. 확인할 것:

잔고: 종목코드 필드와 수량 필드 (수량 필드가 핵심입니다. 종목코드만 맞고 수량 필드가 틀리면 0주 → 무음실패)
미체결: 종목·주문번호·미체결수량 (수량 필드 틀리면 빈 리스트 → cancel-first 통과 → 이중 사다리)
체결: 수량·단가·주문일자 + 행구조
매수가능: 단가를 0으로 넣어도 받는지

2. 체결 행구조가 최대 관문. sync_fills는 "주문 하나당 1행, 수량은 누계"를 전제합니다. 만약 체결 건별로 여러 행이 오면 두 번째 행부터 델타가 음수가 되어 그냥 버려집니다 → 주수 과소 → reconcile 불일치 → 봇이 매일 멈춥니다. 부분체결이 흔한 사다리에선 치명적입니다.
3. 주문번호는 일자별 채번입니다. 체결 dedup 키가 날짜:주문번호인데 날짜 필드가 누락되면 다른 날 같은 번호끼리 충돌합니다. 날짜 필드를 반드시 확인하십시오.
설계 결정 3가지
예약주문 쓰지 마십시오(모의 단계에선). 모의는 예약주문 조회를 지원하지 않습니다. 걸린 예약을 API로 확인할 방법이 없고 로컬 파일이 유일한 진실원이 됩니다. 검증 단계에서 검증 불가능한 경로를 쓰면 안 됩니다. 정규주문은 미체결·체결·잔고 조회가 다 되므로 필드를 전부 실측할 수 있습니다. 예약은 필드 확정 후 별도로.
크론을 밤으로 옮기십시오. 정규주문은 미국장 중에만 접수됩니다. 07:37은 마감 후라 주문이 전량 거부됩니다. 신호 기준일(마지막 미국 종가)은 아침이든 밤이든 동일하므로, 23:40 KST 단일 크론으로 신호+주문을 통합하면 됩니다.
기존 신호봇 크론은 반드시 끄십시오. 이건 코드로 못 막습니다. 자동매매를 켠 상태에서 옛 봇이 계속 돌면, 습관대로 보낸 /buy가 옛 봇에서 그대로 처리되어 같은 체결이 두 번 반영됩니다(수동 명령 + 자동 sync). 두 프로세스가 포지션 파일을 동시에 쓰는 문제도 있습니다.
러너를 짤 때 반드시 지킬 것

체결동기화를 사이클 롤오버보다 먼저. 반대로 하면 사이클 마지막날 체결이 난 경우, 체결 반영 전 pool로 V와 매수한도를 스냅샷한 뒤 곧바로 구사이클 체결이 새 사이클 한도를 깎아먹습니다.
자동매매 모드에선 체결보고 명령(/buy /sell /exit /enter 등)을 거부. 진실원은 하나여야 합니다.
DRY 모드는 아무것도 검증하지 못합니다. 동기화·리컨실·주문취소가 전부 스킵되므로 KIS 조회가 한 번도 안 일어납니다. DRY에서도 조회 4종은 실제로 태워야 의미가 있습니다.

함정 2개

프리플라이트 테스트 체결이 첫 동기화에 빨려들어옵니다. 체결조회 창이 며칠 뒤로 잡히니까요. 실주문 테스트를 했다면 모의계좌를 정리하고 조회 시작일을 잘라야 합니다.
확정 스펙은 LOC인데 코드는 전부 지정가입니다. 사다리·킬스위치·복귀 전부 LIMIT 하드코딩이라, 어댑터의 LOC 매핑은 호출자가 없는 데드코드입니다. 어느 쪽이 확정인지 정리가 필요하고, LOC가 맞다면 모의는 LOC를 지원하지 않으므로 실전 전환 때 처음 실행되는 미검증 경로가 됩니다.

게이트
조회 실측 → 실주문 1주 실측(미국장 중) → DRY(조회는 실제로) → 소액 실주문 1사이클(2주). 각 단계에서 🔴이 하나라도 남으면 다음으로 넘어가지 마십시오. 복귀는 당분간 수동(/enter)으로 두시고, 대피만 자동으로 — 비대칭이 안전 방향입니다.# -*- coding: utf-8 -*-
"""
kis_mock_preflight.py — KIS 모의투자 '필드 실측기'
════════════════════════════════════════════════════════════════════════
목적: 자동매매 배선 전에 vr_kis_adapter.py가 [부분확인]/[실측확정 대기]로
      남겨둔 필드명·행구조를 raw 응답으로 확정한다.

⚠️ 설계 원칙: 어댑터를 import하지 않는다.
   어댑터의 가정(ovrs_pdno, ft_ccld_qty …)이 '검증 대상'이므로,
   어댑터를 통해 조회하면 틀린 가정이 그대로 0/[]로 은폐된다.
   → 여기서는 tr_id·params만 어댑터와 동일하게 쓰고, 응답은 생짜로 본다.

확정 대상 6종:
  ① balance  output1 : ovrs_pdno / ovrs_cblc_qty / pchs_avg_pric
  ② nccs             : pdno / odno / nccs_qty / sll_buy_dvsn_cd / ft_ord_unpr3
  ③ ccnl             : pdno / odno / ft_ccld_qty / ft_ccld_unpr3 / sll_buy_dvsn_cd
                       + ★행구조(주문당 1행 누계 vs 체결건당 다행) ← 최대 리스크
  ④ psbl             : ord_psbl_frcr_amt
  ⑤ SLL_TYPE="00"    : 매도 수용 여부
  ⑥ 수수료 실제 필드 : frcr_ccld_amt2가 수수료인가 체결금액인가

실행:
  export KIS_APPKEY=...  KIS_APPSECRET=...  KIS_CANO=8자리
  python kis_mock_preflight.py              # 조회만 (주문 없음, 아무때나 실행 가능)
  python kis_mock_preflight.py --order      # 1주 실주문 사이클 (★미국장 중에만★)

--order 시나리오 (모두 1주, 모의계좌):
  P6  매수 1주 @ 현재가-20%  → 미체결 유도 → ODNO 확보
  P7  nccs 재조회            → ② 필드 확정 + 방금 주문이 보이는가
  P8  취소 (ORGN_ODNO, ORD_QTY=1)
  P9  nccs 재조회            → 0건 확인 (cancel-first 신뢰성)
  P10 매수 1주 @ 현재가+3%   → 체결 유도
  P11 ccnl 원문              → ③ 필드·행구조·수수료 확정  ★핵심
  P12 balance 재조회         → ① 필드 확정 (1주 반영되는가)
  P13 매도 1주 SLL_TYPE="00" → ⑤ 수용 여부
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, sys, json, time, datetime, requests

MOCK = "https://openapivts.koreainvestment.com:29443"
AK   = os.environ.get("KIS_APPKEY", "")
SK   = os.environ.get("KIS_APPSECRET", "")
CANO = os.environ.get("KIS_CANO", "")
ACNT = os.environ.get("KIS_ACNT_PRDT_CD", "01")
SYMB = os.environ.get("KIS_SYMBOL", "TQQQ")
EXCD_ORD = "NASD"   # 주문·잔고
EXCD_PRC = "NAS"    # 시세

DO_ORDER = "--order" in sys.argv

TR = {  # 어댑터와 동일 (모의)
    "buy": "VTTT1002U", "sell": "VTTT1001U", "cancel": "VTTT1004U",
    "balance": "VTTS3012R", "nccs": "VTTS3018R", "ccnl": "VTTS3035R",
    "psbl": "VTTS3007R", "price": "HHDFS00000300",
}

# 어댑터가 '가정'하고 있는 필드명 — 이게 맞는지 보는 게 이 스크립트의 전부
ASSUMED = {
    "balance.output1": ["ovrs_pdno", "ovrs_cblc_qty", "pchs_avg_pric"],
    "nccs.output":     ["pdno", "odno", "nccs_qty", "sll_buy_dvsn_cd", "ft_ord_unpr3"],
    "ccnl.output":     ["pdno", "odno", "ft_ccld_qty", "ft_ccld_unpr3", "sll_buy_dvsn_cd",
                       "ord_dt"],   # ★ord_dt = sync_fills dedup 키. ODNO는 일자별 채번이라 필수.
    "psbl.output":     ["ord_psbl_frcr_amt"],
}

S = requests.Session()
_tok = {"v": None, "exp": 0}
VERDICT = []   # (항목, 상태, 메모)


def log(*a): print(*a, flush=True)
def hr(t=""): log("\n" + "━" * 68); log(t) if t else None


def auth():
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    r = S.post(f"{MOCK}/oauth2/tokenP",
               headers={"content-type": "application/json"},
               data=json.dumps({"grant_type": "client_credentials",
                                "appkey": AK, "appsecret": SK}), timeout=10)
    r.raise_for_status(); d = r.json()
    if "access_token" not in d:
        raise SystemExit(f"❌ 인증 실패: {d}")
    _tok["v"] = d["access_token"]
    _tok["exp"] = time.time() + int(d.get("expires_in", 86400))
    return _tok["v"]


def H(tr_id, hashkey=None):
    h = {"content-type": "application/json", "authorization": f"Bearer {auth()}",
         "appkey": AK, "appsecret": SK, "tr_id": tr_id, "custtype": "P"}
    if hashkey: h["hashkey"] = hashkey
    return h


def hashkey(body):
    r = S.post(f"{MOCK}/uapi/hashkey",
               headers={"content-type": "application/json", "appkey": AK, "appsecret": SK},
               data=json.dumps(body), timeout=10)
    r.raise_for_status(); return r.json()["HASH"]


def GET(path, tr, params, label):
    r = S.get(f"{MOCK}{path}", headers=H(TR[tr]), params=params, timeout=10)
    r.raise_for_status(); d = r.json()
    time.sleep(0.6)   # 모의 초당 2건
    ok = str(d.get("rt_cd")) == "0"
    log(f"  rt_cd={d.get('rt_cd')} msg_cd={d.get('msg_cd')} msg1={(d.get('msg1') or '').strip()}")
    if not ok:
        VERDICT.append((label, "❌ 호출실패", d.get("msg1")))
    return d, ok


def POST(path, tr, body, label):
    hk = hashkey(body)
    r = S.post(f"{MOCK}{path}", headers=H(TR[tr], hk), data=json.dumps(body), timeout=10)
    r.raise_for_status(); d = r.json()
    time.sleep(1.0)
    ok = str(d.get("rt_cd")) == "0"
    log(f"  rt_cd={d.get('rt_cd')} msg_cd={d.get('msg_cd')} msg1={(d.get('msg1') or '').strip()}")
    return d, ok


def audit(key, rows):
    """어댑터 가정 필드 vs 실제 키 대조."""
    want = ASSUMED[key]
    if not rows:
        log(f"  ⚪ {key}: 행 0개 — 필드 확정 불가(보유/주문 생긴 뒤 재실행)")
        VERDICT.append((key, "⚪ 미확정", "행 0개"))
        return
    actual = list(rows[0].keys())
    miss = [f for f in want if f not in actual]
    log(f"  실제 키({len(actual)}): {actual}")
    if miss:
        log(f"  🔴 어댑터 가정 필드 없음: {miss}")
        # 비슷한 후보 제안
        for m in miss:
            cand = [a for a in actual if any(t in a for t in m.split("_") if len(t) > 2)]
            log(f"      '{m}' 후보 → {cand or '없음'}")
        VERDICT.append((key, "🔴 필드불일치", f"없음: {miss}"))
    else:
        log(f"  ✅ 어댑터 가정 필드 전부 존재: {want}")
        VERDICT.append((key, "✅ 확정", "가정 일치"))
    log(f"  샘플 행: {json.dumps(rows[0], ensure_ascii=False)[:400]}")


# ══════════════════════════════════════════════════════════════
def main():
    if not (AK and SK and CANO):
        raise SystemExit("환경변수 필요: KIS_APPKEY / KIS_APPSECRET / KIS_CANO")

    hr("P0  인증")
    auth(); log("  ✅ 토큰 발급")

    hr("P1  현재가  (HHDFS00000300, EXCD=NAS)")
    d, ok = GET("/uapi/overseas-price/v1/quotations/price", "price",
                {"AUTH": "", "EXCD": EXCD_PRC, "SYMB": SYMB}, "price")
    px = float((d.get("output") or {}).get("last", 0) or 0)
    log(f"  {SYMB} last = ${px}")
    if px <= 0:
        raise SystemExit("❌ 현재가 0 — 지연시세/휴장/심볼 확인 필요. 중단.")
    VERDICT.append(("price", "✅ 확정", f"${px}"))

    hr("P2  잔고 원문  ① ovrs_pdno / ovrs_cblc_qty")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-balance", "balance",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "balance")
    if ok: audit("balance.output1", d.get("output1") or [])

    hr("P3  매수가능금액  ④ ord_psbl_frcr_amt")
    # 어댑터 get_cash_usd()는 OVRS_ORD_UNPR="0"으로 호출한다 → 그 파라미터를 그대로 시험.
    _d0, _ok0 = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "psbl",
                    {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                     "OVRS_ORD_UNPR": "0", "ITEM_CD": SYMB}, "psbl(어댑터 파라미터 unpr=0)")
    if not _ok0:
        log("  🟠 어댑터의 OVRS_ORD_UNPR='0'이 거부됨 → get_cash_usd() 상시 예외.")
        log("     (reconcile은 정보성 로그라 무해하나, 어댑터 수정 권장)")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "psbl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "OVRS_ORD_UNPR": f"{px:.2f}", "ITEM_CD": SYMB}, "psbl")
    if ok:
        o = d.get("output") or {}
        audit("psbl.output", [o] if o else [])
        _amt = float((o or {}).get("ord_psbl_frcr_amt", 0) or 0)
        log(f"  주문가능 USD = {_amt:,.2f}")
        if _amt <= 0:
            log("  🔴 외화 주문가능금액 0 — 모의계좌에 USD 예수금이 없다.")
            log("     → P6~P13(실주문) 전부 실패한다. KIS 모의투자 해외주식 신청/환전 확인 후 재실행.")
            VERDICT.append(("USD 예수금", "🔴 없음", "실주문 시험 불가"))

    hr("P4  미체결 원문  ② pdno / odno / nccs_qty / sll_buy_dvsn_cd")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    if ok: audit("nccs.output", d.get("output") or [])

    hr("P5  체결 원문  ③ ft_ccld_qty / 행구조 / 수수료")
    since = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%Y%m%d")
    today = datetime.date.today().strftime("%Y%m%d")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-ccnl", "ccnl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT,
                 "ORD_STRT_DT": since, "ORD_END_DT": today,
                 "SORT_SQN": "DS", "OVRS_EXCG_CD": "",
                 "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00",
                 "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "ccnl")
    if ok:
        rows = d.get("output") or []
        audit("ccnl.output", rows)
        _row_structure(rows)

    if not DO_ORDER:
        _summary()
        log("\n💡 실주문 검증(P6~P13)은  --order  플래그 + ★미국장 시간★에.")
        return

    # ── 실주문 사이클 ──────────────────────────────────────────
    hr("P6  매수 1주 @ 현재가-20% (미체결 유도)")
    lo = round(px * 0.80, 2)
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
            "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{lo:.2f}",
            "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": ""}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "buy", body, "buy")
    if not ok:
        VERDICT.append(("정규매수", "❌ 실패", d.get("msg1")))
        _summary(); raise SystemExit("❌ 매수 접수 실패 — 이후 단계 중단")
    odno = (d.get("output") or {}).get("ODNO", "")
    log(f"  ODNO = {odno!r}")
    VERDICT.append(("정규매수", "✅ 접수", f"@{lo} ODNO={odno}"))

    hr("P7  nccs 재조회 — 방금 주문이 보이는가?")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    rows = d.get("output") or []
    audit("nccs.output", rows)
    hit = [r for r in rows if str(r.get("odno", "")).lstrip("0") == str(odno).lstrip("0")]
    if hit:
        log(f"  ✅ 방금 ODNO 발견 — list_open_orders 신뢰 가능")
        log(f"     sll_buy_dvsn_cd = {hit[0].get('sll_buy_dvsn_cd')!r}  (매수인데 이 값 → 02가 매수)")
        VERDICT.append(("nccs 추적", "✅ 확정", f"매수 코드={hit[0].get('sll_buy_dvsn_cd')!r}"))
    else:
        log("  🔴 방금 ODNO를 nccs에서 못 찾음 → cancel-first 무력 → 이중 사다리 위험!")
        VERDICT.append(("nccs 추적", "🔴 실패", "접수한 주문이 미체결조회에 없음"))

    hr("P8  취소 (ORGN_ODNO, ORD_QTY=1)")
    cb = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD, "PDNO": SYMB,
          "ORGN_ODNO": odno, "RVSE_CNCL_DVSN_CD": "02", "ORD_QTY": "1", "OVRS_ORD_UNPR": "0"}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order-rvsecncl", "cancel", cb, "cancel")
    VERDICT.append(("정규취소", "✅ 성공" if ok else "🔴 실패", d.get("msg1")))

    hr("P9  nccs 재조회 — 0건 확인")
    d, _ = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
               {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    rows = d.get("output") or []
    left = [r for r in rows if str(r.get("odno", "")).lstrip("0") == str(odno).lstrip("0")]
    log("  ✅ 취소 반영됨" if not left else f"  🔴 취소했는데 잔존: {left}")

    hr("P10 매수 1주 @ 현재가+3% (체결 유도)")
    hi = round(px * 1.03, 2)
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
            "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{hi:.2f}",
            "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": ""}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "buy", body, "buy2")
    odno2 = (d.get("output") or {}).get("ODNO", "")
    log(f"  ODNO = {odno2!r} @ {hi}")
    log("  ⏳ 체결 대기 20초…"); time.sleep(20)

    hr("P11 ccnl 원문  ★핵심: 행구조 + 수수료")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-ccnl", "ccnl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT,
                 "ORD_STRT_DT": today, "ORD_END_DT": today,
                 "SORT_SQN": "DS", "OVRS_EXCG_CD": "",
                 "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00",
                 "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "ccnl")
    rows = d.get("output") or []
    audit("ccnl.output", rows)
    _row_structure(rows)
    _fee_check(rows)

    hr("P12 잔고 재조회  ① 1주 반영 확인")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-balance", "balance",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "balance")
    r1 = d.get("output1") or []
    audit("balance.output1", r1)
    mine = [h for h in r1 if h.get("ovrs_pdno") == SYMB]
    if mine:
        log(f"  ✅ get_holdings 경로 정상: {mine[0].get('ovrs_cblc_qty')}주")
        VERDICT.append(("get_holdings", "✅ 확정", f"{mine[0].get('ovrs_cblc_qty')}주"))
    else:
        log(f"  🔴🔴 ovrs_pdno=={SYMB} 매치 실패 → get_holdings가 0주 반환 →")
        log(f"       killswitch가 '실보유 0 확인 — CASH 확정' 로 무음실패한다!")
        VERDICT.append(("get_holdings", "🔴🔴 치명", "심볼 매치 실패 = 킬스위치 무음실패"))

    hr("P13 매도 1주  ⑤ SLL_TYPE='00' 수용?")
    # ★[F7] P10이 미체결이면 보유 0 → 매도는 '잔고부족'으로 거부된다.
    #   그걸 'SLL_TYPE 거부'로 읽으면 오판정 → 실제로 멀쩡한 경로를 🔴로 낙인.
    _hq = float((mine[0].get("ovrs_cblc_qty", 0) or 0)) if mine else 0.0
    if _hq < 1:
        log("  ⚪ 보유 0주 (P10 미체결) — 매도 시험 스킵.")
        log("     보유 없이 매도하면 '잔고부족' 거부가 SLL_TYPE 거부로 오판된다.")
        VERDICT.append(("매도 SLL_TYPE=00", "⚪ 미확정", "P10 미체결 → 시험 불가"))
        _summary(); return
    sb = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
          "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{round(px*0.90,2):.2f}",
          "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": "00"}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "sell", sb, "sell")
    VERDICT.append(("매도 SLL_TYPE=00", "✅ 수용" if ok else "🔴 거부", d.get("msg1")))
    if ok:
        log("  ✅ 킬스위치 매도 경로 유효")
    else:
        log("  🔴 매도 거부 → 사다리 매도 + 킬스위치 매도 전부 불가. SLL_TYPE 재확인 필요.")

    _summary()


def _row_structure(rows):
    """★ sync_fills의 delta dedup 전제 검증: 주문당 1행인가, 체결건당 다행인가."""
    if not rows:
        log("  ⚪ 체결 0건 — 행구조 판정 불가")
        return
    from collections import Counter
    # ★[F3] KIS ODNO는 '일자별 채번' → 다른 날 같은 번호가 존재한다.
    #   ODNO 단독으로 세면 14일 창에서 가짜 '주문당 다행'이 뜬다(오탐).
    #   반드시 (ord_dt, odno) 복합키. 이건 sync_fills의 dedup 키와도 동일해야 한다.
    if not any("ord_dt" in r for r in rows):
        log("  🔴 ord_dt 필드 없음 — sync_fills의 filled_at이 빈 문자열이 된다.")
        log("     → dedup 키가 ':ODNO:side'로 붕괴 → 다른 날 같은 ODNO끼리 충돌 → 체결 유실.")
        log("     → 실제 날짜 필드명을 찾아 어댑터 get_fills의 o.get('ord_dt') 교체 필요.")
        VERDICT.append(("ccnl ord_dt", "🔴🔴 치명", "dedup 키 붕괴"))
    c = Counter((str(r.get("ord_dt", "")), str(r.get("odno", ""))) for r in rows)
    dup = {f"{d}:{o}": v for (d, o), v in c.items() if v > 1}
    log(f"  행 {len(rows)}개 / 고유 (일자,ODNO) {len(c)}개")
    if dup:
        log(f"  🔴🔴 같은 ODNO 다행 발견: {dup}")
        log("       → sync_fills 전제('주문당 1행 누계') 위반!")
        log("         delta=f.qty-done 에서 2번째 행이 delta<=0 → continue → 체결 유실")
        log("         → shares 과소 → reconcile 불일치 → 매일 봇 정지")
        log("       → 수정 필요: seen[key] 를 '행별 누계 합산'으로 (key에 체결일련번호 추가)")
        VERDICT.append(("ccnl 행구조", "🔴🔴 치명", f"주문당 다행: {dup}"))
    else:
        log("  ✅ ODNO당 1행 — sync_fills의 delta dedup 전제 성립")
        VERDICT.append(("ccnl 행구조", "✅ 확정", "주문당 1행 누계"))


def _fee_check(rows):
    """⑥ frcr_ccld_amt2가 수수료인가 체결금액인가."""
    if not rows: return
    r = rows[0]
    q = float(r.get("ft_ccld_qty", 0) or 0)
    p = float(r.get("ft_ccld_unpr3", 0) or 0)
    if q <= 0 or p <= 0:
        log("  ⚪ 수량/단가 0 — 수수료 판정 불가"); return
    gross = q * p
    log(f"  체결금액(계산) = {q} × {p} = {gross:.2f}")
    for f in ("frcr_ccld_amt2", "cmsn", "frcr_ccld_amt1", "ovrs_excg_fee"):
        if f in r:
            try:
                v = float(r[f] or 0)
            except Exception:
                continue
            if v == 0:
                kind = "0"
            elif abs(v - gross) / gross < 0.02:
                kind = "🔴 체결금액! (수수료 아님 — Pool 이중차감 위험)"
            elif 0 < v <= gross * 0.01:
                kind = f"✅ 수수료 후보 (요율 {v/gross:.4%})"
            else:
                kind = "❓ 정체불명"
            log(f"  {f} = {v}  → {kind}")
    log(f"  ※ 어댑터 현재 추정요율 FEE_RATE=0.0035 → 예상 {gross*0.0035:.4f}")
    VERDICT.append(("수수료 필드", "🟡 수동판정", "위 출력 확인"))


def _summary():
    hr("판정 요약")
    w = max(len(a) for a, _, _ in VERDICT) if VERDICT else 10
    for item, st, memo in VERDICT:
        log(f"  {item.ljust(w)}  {st}   {str(memo or '')[:60]}")
    bad = [v for v in VERDICT if "🔴" in v[1]]
    log("\n" + ("🔴 치명 항목 있음 — 자동매매 배선 금지" if bad else
                "✅ 치명 항목 없음 — 다음 게이트 진행 가능"))


if __name__ == "__main__":
    main()




    # -*- coding: utf-8 -*-
"""
vr_auto_runner_kis.py — vr_signal_bot <-> vr_kis_adapter 글루 [KIS 전용]  rev.2
════════════════════════════════════════════════════════════════════════
봇은 어댑터를 import하지 않는다(설계). 이 파일이 유일한 접점.
vr_signal_bot.py / vr_broker_adapter.py / vr_kis_adapter.py 는 무수정.

★★ KIS 전용 ★★ 스키마 가드가 KIS 응답 필드명에 묶여 있다.
   토스/키움은 make_broker() + GuardedXXX 서브클래스만 교체(핵심 로직은 증권사 무관).
   단 스키마 가드는 해당 증권사 필드가 '실측 확정'된 뒤에만 작성 가능(추측이면 무의미).

━━ rev.2 수정 (rev.1 자기감사에서 실증된 결함) ━━━━━━━━━━━━━━━━━━━━━━━
 [F1] 🔴 스키마 가드가 식별자(pdno)만 보고 '수량 필드'를 안 봤다.
      재현: ovrs_pdno는 맞고 ovrs_cblc_qty만 이름이 다르면 →
            가드 통과 → get_holdings=0주 → killswitch "🔵 실보유 0 확인 — CASH 확정"
            → 3000주 보유 중인데 대피 완료로 기록(막으려던 무음실패 그대로 재현).
      동일하게 nccs_qty만 틀리면 → list_open_orders=[] → cancel-first 통과 → 이중 사다리.
      → _EXPECT를 '어댑터가 실제로 dereference 하는 필드 전부'로 확장.
 [F2] 🔴 ord_dt 미검사. sync_fills dedup 키 = {filled_at}:{odno}:{side} 인데
      KIS ODNO는 '일자별 채번' → ord_dt 누락 시 filled_at="" → 다른 날 같은 번호가
      키 충돌 → delta 음수 → 체결 유실. 프루닝(k.split(":")[0])도 무력화 → seen 무한증가.
      → ord_dt를 _EXPECT["fills"]에 필수 포함.
 [F4] 🟠 DRY_RUN=on이 KIS를 하나도 검증하지 않았다.
      sync_fills/reconcile/rotate_cycle 전부 `if dry_run: return` → get_holdings·
      list_open_orders·get_fills 미호출 → 스키마 가드가 한 번도 발동 안 함.
      → probe(): 주문 없이 조회 4종만 실제로 태운다. DRY에서도 항상 실행.
 [F5] 🟠 프리플라이트(kis_mock_preflight --order)의 테스트 체결이 rolling_since(5) 창에
      들어와 첫 sync에서 포지션에 반영된다 → SYNC_SINCE 하한 옵션 추가.
 [F6] 🟠 [코드로 못 막음] AUTO_MODE 가드는 이 러너의 monkeypatch다.
      기존 vr_signal_bot.py 크론이 살아있으면 패치 안 된 apply_command가 /buy를 받는다
      → 이중반영. 게다가 두 프로세스가 vr_position.json·offset 파일을 동시에 쓴다.
      ★ 기존 워크플로(07:37 신호봇)를 반드시 삭제/비활성화할 것. ★
 [🟢] 체결 다수 시 TG 메시지 폭주(체결당 1건) → 429 → 알림 유실.
      경보(🚨🔴⚠️)는 즉시, 나머지는 버퍼링 후 1건으로 flush.

━━ 봉합 유지 (rev.1) ━━
 🔴2 AUTO_MODE — apply_command '/buy'와 sync_fills가 둘 다 shares/pool/cyc_used를
     건드린다. 자동 켠 채 /buy 보내면 같은 체결이 2번 반영.
 🔴3 실행순서 — sync_fills를 rollover보다 먼저.
     'rollover → sync' 순이면 사이클 마지막 세션 체결이 난 날:
       ① 체결 반영 전 pool로 V=V+pool/G → V 왜곡
       ② 같은 stale pool로 cyc_budget 스냅샷 + cyc_used=0 리셋
       ③ 직후 sync가 구사이클 체결 cost를 새 cyc_used에 적재 → 새 사이클 매수한도 선소진
     sync_fills는 fills_seen 멱등 → 먼저 1회 호출해도 daily_run 내부 2차 sync는 no-op.

모의 1단계 설계(확정):
  · use_reserve=False (정규주문). 모의는 예약주문 조회(TTTT3039R) 미지원 →
    걸린 예약을 API로 확인 불가. 검증 단계에서 검증 불가능한 경로 금지.
  · 크론 23:40 KST (미국 개장 직후). 정규주문은 미국장 중에만 접수.
    신호 기준일(마지막 미국 종가=D-1)은 07:37이든 23:40이든 동일 → 단일 크론 통합.

환경변수:
  KIS_APPKEY / KIS_APPSECRET / KIS_CANO      (필수)
  KIS_ACNT_PRDT_CD=01  KIS_MOCK=on  USE_RESERVE=off  KIS_SYMBOL=TQQQ
  DRY_RUN=on        ← 기본 ON. 주문 안 나감. probe는 실행(가드 검증됨).
  AUTO_MODE=off     ← ON이면 체결보고 명령 거부(자동 sync가 진실원)
  AUTO_RECOVER=off  ← 복귀는 기본 수동(/enter)
  STRICT_CCNL=on    ← ccnl 주문당 다행 감지 시 중단
  SYNC_SINCE=       ← YYYY-MM-DD. 체결조회 시작일 하한(프리플라이트 체결 차단용).
                       가동 안정 후 반드시 제거(안 그러면 창이 계속 좁혀짐).
  + TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, traceback

import vr_signal_bot as bot                       # main()은 __main__ 가드 안이라 import 안전
from vr_broker_adapter import LadderAutomator, daily_run, rolling_since
from vr_kis_adapter import KISAdapter, KISError

ON = bot.ON
DRY_RUN      = ON(os.environ.get("DRY_RUN", "on"))
AUTO_MODE    = ON(os.environ.get("AUTO_MODE", "off"))
AUTO_RECOVER = ON(os.environ.get("AUTO_RECOVER", "off"))
USE_RESERVE  = ON(os.environ.get("USE_RESERVE", "off"))
KIS_MOCK     = ON(os.environ.get("KIS_MOCK", "on"))
STRICT_CCNL  = ON(os.environ.get("STRICT_CCNL", "on"))
SYNC_SINCE   = os.environ.get("SYNC_SINCE", "").strip()
SYMBOL       = os.environ.get("KIS_SYMBOL", "TQQQ")

# 체결을 '보고'하는 명령 = sync_fills와 진실원이 겹침 → AUTO_MODE에서 거부.
# /setpos·/setv·/setcycle·/reset 은 의도적 '수리' 명령이라 허용(틀리면 reconcile이 잡음).
BLOCKED_IN_AUTO = {"/buy", "/sell", "/exit", "/enter", "/deposit_done", "/lumpsum_done"}


# ══ [🟢] 알림 버퍼 — 경보는 즉시, 나머지는 묶어서 1건 ═══════════════
class Notifier:
    URGENT = ("🚨", "🔴", "⚠️", "⛔")
    def __init__(self, sink):
        self.sink = sink; self.buf = []
    def __call__(self, m):
        if any(m.lstrip().startswith(u) or u in m[:4] for u in self.URGENT):
            self.sink(m)                    # 경보는 즉시(크래시해도 남는다)
        else:
            self.buf.append(m)
    def drain(self):
        out, self.buf = self.buf, []
        return out


# ══ [F1][F2] 스키마 가드 ═══════════════════════════════════════════
class GuardedKIS(KISAdapter):
    """어댑터 무수정 원칙 유지 — 필드 계약 검증만 서브클래스로 덧씌움.
       ★ 어댑터가 실제로 .get() 하는 필드를 '전부' 검사해야 한다.
         식별자(pdno)만 검사하면 수량 필드가 틀렸을 때 조용히 0/[]로 떨어져
         가드가 막겠다고 선언한 무음실패가 그대로 재현된다(rev.1 실증)."""
    _EXPECT = {
        "balance":  ["ovrs_pdno", "ovrs_cblc_qty"],                       # pchs_avg_pric은 정보성
        "open_ord": ["pdno", "odno", "nccs_qty"],                         # nccs_qty=0 → [] → 이중사다리
        "fills":    ["pdno", "odno", "ft_ccld_qty", "ft_ccld_unpr3",
                     "ord_dt"],                                           # ord_dt=dedup 키 (ODNO 일자별 채번!)
    }
    # sll_buy_dvsn_cd는 어댑터가 이미 fail-fast(KISError) → 중복 검사 불필요.

    def _get_paged(self, path, tr_key, params, err, list_key="output", max_pages=10):
        rows = super()._get_paged(path, tr_key, params, err, list_key, max_pages)
        need = self._EXPECT.get(tr_key, [])
        if rows and need:
            miss = [k for k in need if not any(k in r for r in rows)]
            if miss:
                raise KISError(
                    f"🔴 스키마 불일치[{tr_key}]: 누락 {miss}. "
                    f"조용한 0/[] 반환 = 킬스위치 무음실패·이중사다리 경로 → 중단. "
                    f"실제 키={list(rows[0].keys())}")
        # ★ ccnl 행구조: sync_fills는 '(ord_dt:ODNO)당 누계 1행'을 전제한다.
        #   체결건당 다행이면 delta<=0 → continue → 체결 유실 → shares 과소.
        #   (ODNO는 일자별 채번이므로 반드시 ord_dt와 함께 키를 잡는다.)
        if STRICT_CCNL and tr_key == "fills" and rows:
            seen = {}
            for r in rows:
                k = f"{r.get('ord_dt','')}:{r.get('odno','')}"
                seen[k] = seen.get(k, 0) + 1
            dup = {k: v for k, v in seen.items() if v > 1}
            if dup:
                raise KISError(
                    f"🔴 ccnl 주문당 다행 감지 {dup} — sync_fills의 delta dedup 전제 위반. "
                    f"체결 유실 위험 → 중단. (STRICT_CCNL=off 로 무시 가능하나 비권장)")
        return rows


# ══ [🔴2] AUTO_MODE 가드 ═══════════════════════════════════════════
_orig_apply = bot.apply_command

def _guarded_apply(pos, text, price_hint, Veff_target=None):
    t = (text or "").strip().split()
    cmd = t[0].lower().split("@", 1)[0] if t else ""
    if AUTO_MODE and cmd in BLOCKED_IN_AUTO:
        return pos, (f"⛔ AUTO_MODE — <code>{cmd}</code> 거부.\n"
                     f"   체결은 증권사 API로 자동 동기화됩니다(이중반영 방지).\n"
                     f"   수동 개입이 필요하면 AUTO_MODE=off 후 실행.")
    return _orig_apply(pos, text, price_hint, Veff_target)

bot.apply_command = _guarded_apply


# ══ [F4] 조회 전용 프로브 — DRY에서도 반드시 실행 ═══════════════════
def probe(broker, pos, since):
    """dry_run이면 sync_fills/reconcile/rotate_cycle이 전부 스킵되어
       get_holdings·list_open_orders·get_fills가 한 번도 호출되지 않는다.
       = 스키마 가드가 발동할 기회가 없다 = DRY가 KIS를 아무것도 검증 못 한다.
       → 주문은 내지 않고 조회 4종만 실제로 태워 가드를 발동시킨다."""
    L = ["🔍 <b>조회 프로브</b> (주문 없음)"]
    px = broker.get_price(SYMBOL)
    L.append(f"   현재가 ${px:,.2f}")

    held = broker.get_holdings(SYMBOL)                      # ← balance 스키마 가드
    bs = float(pos.get("shares", 0.0))
    ok = abs(held.shares - bs) <= 0.5
    L.append(f"   실보유 {held.shares:g}주 vs 봇 {bs:g}주  {'✅' if ok else '🚨 불일치'}")

    opens = broker.list_open_orders(SYMBOL)                 # ← nccs 스키마 가드
    L.append(f"   미체결 {len(opens)}건" + (f" {[o['order_id'] for o in opens][:5]}" if opens else ""))

    fills = broker.get_fills(SYMBOL, since)                 # ← ccnl 스키마 + 행구조 가드
    L.append(f"   체결({since}~) {len(fills)}건")

    try:
        L.append(f"   주문가능 ${broker.get_cash_usd():,.0f} "
                 f"(Pool ${float(pos.get('pool',0)):,.0f} · 증거금 차감분이라 참고용)")
    except Exception as e:
        L.append(f"   주문가능 조회 생략: {e}")
    return "\n".join(L), ok


# ══ 러너 ═══════════════════════════════════════════════════════════
def make_broker():
    ak, sk, cano = (os.environ.get("KIS_APPKEY"), os.environ.get("KIS_APPSECRET"),
                    os.environ.get("KIS_CANO"))
    if not (ak and sk and cano):
        raise SystemExit("환경변수 필요: KIS_APPKEY / KIS_APPSECRET / KIS_CANO")
    return GuardedKIS(ak, sk, cano,
                      acnt_prdt_cd=os.environ.get("KIS_ACNT_PRDT_CD", "01"),
                      mock=KIS_MOCK, use_reserve=USE_RESERVE)


def run():
    mode = ("DRY" if DRY_RUN else "LIVE") + ("/모의" if KIS_MOCK else "/실전")
    banner = (f"⚙️ 자동매매 {mode} · AUTO_MODE={'on' if AUTO_MODE else 'off'} · "
              f"자동복귀={'on' if AUTO_RECOVER else 'off'} · "
              f"예약주문={'on' if USE_RESERVE else 'off'}")
    print(banner)

    df  = bot.build_data()
    pos = bot.load_position()

    broker = make_broker()
    notifier = Notifier(bot._tg)
    auto = LadderAutomator(broker, SYMBOL, dry_run=DRY_RUN, notify=notifier)

    # [F5] 체결조회 창 하한 — 프리플라이트 테스트 체결이 빨려들어오는 것 차단
    since = rolling_since(5)
    if SYNC_SINCE and SYNC_SINCE > since:
        since = SYNC_SINCE
        notifier(f"ℹ️ SYNC_SINCE={SYNC_SINCE} 적용 — 안정화 후 제거할 것")

    # [F4] ① 프로브 — DRY 포함 항상. 스키마 가드가 여기서 발동한다.
    probe_msg, recon_ok = probe(broker, pos, since)
    notifier(probe_msg)

    # [🔴3] ② sync_fills 먼저 (구사이클 pool 확정). DRY면 어차피 no-op → 스킵(중복 알림 방지).
    if not DRY_RUN:
        try:
            pos = auto.sync_fills(pos, since)
            bot.save_position(pos)
        except Exception as e:
            bot._tg(f"🚨 체결동기화 실패 — 전 단계 중단(안전): {e}")
            raise

    px_col = "TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
                             not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ"
    price_hint = float(df[px_col].iloc[-1])

    # ③ ensure_V → rollover (이제 체결 반영된 pool로 V·cyc_budget 스냅샷)
    pos = bot.ensure_V(pos, price_hint)
    pos, roll_msg, cycle_changed = bot._cycle_rollover(pos, df)
    if cycle_changed:
        bot.save_position(pos)

    # ④ 명령 처리 (AUTO_MODE면 체결보고 명령 거부)
    V_tmp = pos.get("V", 0.0) or (pos.get("shares", 0.0) * price_hint)
    if ON(bot.VOLTGT_ON) and pos.get("cyc_scale") is not None:
        scale = float(pos["cyc_scale"])
    else:
        rv = float(df["RV"].iloc[-1]) if not bot.pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale = (min(1.0, bot.VOLTGT_TARGET / rv)
                 if (ON(bot.VOLTGT_ON) and rv == rv and rv > 0) else 1.0)
    pos, cmd_results = bot.process_commands(pos, price_hint, V_tmp * scale)

    if pos.get("shares", 0) == 0 and pos.get("pool", 0) == 0 and not cmd_results:
        bot._tg("⚠️ 포지션 미등록 — <code>/setpos</code> 먼저. 자동매매 스킵.")
        return

    # ⑤ daily_run — 내부 sync는 멱등 no-op. compute_ladder 필수(DAY-only 브로커).
    pos = daily_run(auto, pos, bot.compute_signal, df, since, bot.save_position,
                    auto_recover=AUTO_RECOVER, compute_ladder=bot.compute_ladder)

    # ⑥ 리포트 (daily_run이 중간 return해도 항상 발송) + 버퍼 알림 flush
    s = bot.compute_signal(df, pos)
    head = [banner]
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg:
        head.append(f"🔄 {roll_msg}")
    buffered = notifier.drain()
    if buffered:
        head.append("")
        head += buffered
    report = "\n".join(head) + "\n\n" + bot.build_report(s, df)

    if bot._tg(report):
        bot._save_last(str(s["today"].date()))
        bot._ping()
        if s.get("is_cycle_start"):
            pos["ladder_placed_for"] = str(s["cyc_start"]); bot.save_position(pos)
        rcd = s.get("recover_check_date")
        recovering = bool(s.get("ks_recover")) or (s.get("action_ks") == "🔵 복귀")
        if rcd and not recovering and rcd != pos.get("last_recover_check", ""):
            pos["last_recover_check"] = rcd; bot.save_position(pos)
    else:
        print("[경고] 텔레그램 전송 실패"); print(report)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        bot._emergency_tg(e)
        print(f"[크래시] {e}"); traceback.print_exc()
        raise
