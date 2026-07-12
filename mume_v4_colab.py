
모든 파일 GitHub에서 재수집 완료. 결론부터 — 지금 상태로는 연결이 물리적으로 불가능합니다. 이유와 함께 정리합니다.

진단: 어댑터는 있는데 러너(글루)가 없다
vr_signal_bot.py 안의 어댑터 흔적:
  import vr_broker_adapter   → 0건
  LadderAutomator            → 0건
  daily_run                  → 0건
  KISAdapter                 → 0건
봇은 어댑터를 한 번도 import하지 않습니다. 어댑터 3종 + 프레임워크는 완성돼 있지만, 둘을 잇는 파일이 존재하지 않습니다. 이게 유일하게 빠진 조각입니다.
다행히 계약은 이미 맞습니다:
daily_run이 요구봇이 제공compute_ladder(shares, V, pool, budget_override=) → (buy,sell,lot)L678 동일 시그니처✅compute_signal(df,pos) → ks_evac/ks_recover/veff/is_cycle_startL958~961 전부 반환✅max_validity=="DAY" → 매일 재배치KIS=DAY✅
즉 글루 ~60줄이면 붙습니다. 다만 그 전에 막아야 할 구멍이 3개 있습니다.

🔴 치명 3건 — 붙이기 전 반드시
🔴1. 필드명 [부분확인] 상태 → 킬스위치 무음실패 경로가 열려 있음
python# vr_kis_adapter.py get_holdings (L406)
for h in rows:
    if h.get("ovrs_pdno")==symbol:   # ← 이 키 이름이 틀리면?
        return Position(...)
return Position(symbol, 0.0)          # ← 조용히 0주
ovrs_pdno가 실제와 다르면 → rows는 왔는데 매치 실패 → 0주 반환 → killswitch_evacuate의 else 브랜치 → "🔵 실보유 0 확인 — CASH 확정". 주식은 그대로 있는데 봇은 대피 완료로 기록합니다.
list_open_orders의 pdno도 동일 구조 → 빈 리스트 → cancel-first가 "0건" 통과 → 이중 사다리.
fable5가 잡은 🔴1/🔴4는 "API가 rt_cd≠0을 줄 때"만 막습니다. "200 OK인데 필드명이 다를 때"는 못 막습니다. 그리고 그 필드들이 지금 정확히 [부분확인] 상태입니다.
🔴2. AUTO_MODE 부재 → 체결 이중반영
pythonapply_command "/buy":  shares+=, pool-=, cyc_used+=   (L304~312)
sync_fills:            shares+=, pool-=, cyc_used+=   (adapter L154~158)
자동매매를 켠 상태에서 습관대로 /buy 10 @72를 보내면 같은 체결이 두 번 들어갑니다. 어댑터 헤더의 "③ AUTO_MODE 시 수동 명령 거부 — 봇 쪽"이 바로 이건데, 봇에 AUTO_MODE가 아예 없습니다(grep 0건).
🔴3. 실행 순서 — rollover가 sync보다 먼저면 V·예산 오염
어댑터 헤더 권고: "러너는 rollover(봇 main) → daily_run 순". 이 순서면 사이클 마지막 세션에 체결이 난 날:

rollover가 체결 반영 전 pool로 V = V + pool/G → 매수체결이었으면 V 과대
rollover가 같은 stale pool로 cyc_budget = pool×0.5 스냅샷, cyc_used = 0 리셋
그 다음 sync_fills가 구사이클 체결 cost를 새 cyc_used에 더함 → 새 사이클 매수한도 선소진

main() 주석은 이걸 "희귀 케이스, 보수적 방향"이라 허용했지만 — 그건 수동 /buy 지연보고 얘기입니다. 자동 sync에선 사이클 마지막날 체결이 날 때마다 매번 발생합니다.
→ sync_fills → rollover → 나머지 순서로 바꿔야 합니다. sync_fills는 fills_seen 멱등이므로 러너에서 먼저 한 번 부르고 daily_run 내부의 두 번째 sync는 자동 no-op이 됩니다.

모의 1단계 설계 결정
예약주문 쓰지 마십시오 (use_reserve=False)
어댑터 헤더는 예약주문(10:10 크론)을 지향하지만, 모의는 예약주문 조회(TTTT3039R)를 지원하지 않습니다(어댑터 스스로 "resv_list": {"mock": None}). 걸린 예약을 API로 확인할 방법이 없고, 유일한 진실원이 로컬 .kis_resv_mock.json뿐입니다.
검증 단계에서 검증 불가능한 경로를 쓰면 안 됩니다. 정규주문이면 nccs·ccnl·balance 전부 모의 지원 → 미확정 필드 6종을 전부 실측할 수 있습니다. 예약주문은 필드 확정 후 별도 2단계로.
크론: 07:37 → 23:40 KST
정규주문은 미국장 중에만 접수됩니다. 07:37 KST는 마감 후 → 주문 전량 거부. 그런데 신호 기준일(마지막 미국 종가 = D-1)은 07:37이든 23:40이든 동일합니다. → 단일 밤 크론으로 신호+주문 통합 가능. (미국장 KST 23:30~06:00 / 서머타임 22:30~05:00 → 23:40이면 양쪽 안전)

지금 할 일: 필드 실측 (주문 배선 전)
코드를 더 쓰기 전에 [부분확인] 6종을 실측으로 확정해야 합니다. 어댑터를 import하지 않고 raw 응답을 그대로 덤프하는 스크립트를 만들었습니다 — 어댑터의 가정 자체를 검증 대상으로 두기 위함입니다.KIS 모의투자 필드 실측 스크립트 — 어댑터의 [부분확인] 필드 6종을 raw 응답으로 확정KIS 모의투자 필드 실측 스크립트 — 어댑터의 [부분확인] 필드 6종을 raw 응답으로 확정이제 러너입니다. 치명 3건을 전부 봉합한 상태로 작성했고, vr_kis_adapter.py는 손대지 않았습니다 — 대신 서브클래스로 스키마 가드를 씌웠습니다(감사 완료된 파일에 기능 변경을 섞지 않기 위함).파일 생성됨, 파일 읽음파일 생성됨, 파일 읽음게이트 (순서대로, 건너뛰지 마십시오)
게이트명령통과 조건G0 조회 실측python kis_mock_preflight.py아무때나. balance/nccs/ccnl/psbl 원문 키 확인G1 주문 실측python kis_mock_preflight.py --order (★미국장 중)🔴 0건. 특히 ccnl 행구조·get_holdings 심볼 매치·SLL_TYPE=00G2 DRYDRY_RUN=on python vr_auto_runner.py주문 0건. 사다리 목록·킬스위치 판정이 리포트와 일치G3 소액 실주문DRY_RUN=off AUTO_MODE=on + 크론 23:401사이클(2주). 매일 reconcile 통과 = 봇 주수 ≡ 실보유G4 예약주문USE_RESERVE=on별도 검증. 모의는 예약조회 불가라 로컬 파일이 유일 진실원
G3까지는 AUTO_RECOVER=off(복귀는 /enter 수동) 유지를 권합니다. 킬스위치 대피는 자동, 복귀는 수동 — 비대칭이 안전 방향입니다.

G1에서 무엇을 보는가 — 최대 리스크 2개
① ccnl 행구조. 어댑터의 sync_fills는 *"(날짜:ODNO)당 1행, 수량은 누계"*를 전제합니다. 만약 체결건당 다행이면:
행1: odno=X qty=10 → delta=10-0=10  → shares+=10, seen[X]=10
행2: odno=X qty=8  → delta=8-10=-2  → continue  ← 8주 유실
→ shares 과소 → reconcile 불일치 → 매일 봇 정지. 안전 실패이긴 하지만 사다리는 부분체결이 흔해서 상시 정지 위험. 러너의 STRICT_CCNL 가드가 이걸 사전 감지합니다.
② get_holdings 심볼 매치. ovrs_pdno가 실제와 다르면 조용히 0주 → 킬스위치가 "실보유 0 확인 — CASH 확정". 대피 실패가 무음화되는 유일한 경로입니다. G1 P12가 정확히 이걸 찍습니다.

부수 관찰

레이트리밋: 모의 초당 2건. 1주문 = hashkey + order = 2콜. _order_sleep=1.0이면 딱 한계선입니다. 사다리 25~30건 = 취소+접수 ≈ 100콜 / 1분+. EGW00201이 뜨면 _place_ladder가 해당 건만 실패 처리 → 부분 사다리(알림은 감). G1/G3에서 실제로 뜨는지 관찰 후, 뜨면 지수백오프 재시도를 넣는 게 맞습니다.
.gitignore: gitignore.txt → .gitignore로 개명 필수(파일 자체 주석에도 있음). 그리고 커밋 전 git ls-files | grep -E "token|secret|appkey" 한 번.


G0 결과(원문 키 덤프)를 붙여주시면 필드 확정하고 G1로 넘어가겠습니다. G1 통과 전에는 vr_auto_runner.py를 DRY_RUN=off로 돌리지 마십시오 — 필드가 미확정인 상태에서 실주문이 나가면 위 ②가 정확히 발화하는 조건입니다.# -*- coding: utf-8 -*-
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
    "ccnl.output":     ["pdno", "odno", "ft_ccld_qty", "ft_ccld_unpr3", "sll_buy_dvsn_cd"],
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
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "psbl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "OVRS_ORD_UNPR": f"{px:.2f}", "ITEM_CD": SYMB}, "psbl")
    if ok:
        o = d.get("output") or {}
        audit("psbl.output", [o] if o else [])

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
    _fee_check(rows, hi)

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
    c = Counter(str(r.get("odno", "")) for r in rows)
    dup = {k: v for k, v in c.items() if v > 1}
    log(f"  행 {len(rows)}개 / 고유 ODNO {len(c)}개")
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


def _fee_check(rows, ref_px):
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
vr_auto_runner.py — vr_signal_bot ↔ vr_broker_adapter 글루 (KIS 모의투자)
════════════════════════════════════════════════════════════════════════
봇은 어댑터를 import하지 않는다(설계). 이 파일이 유일한 접점.
vr_signal_bot.py / vr_broker_adapter.py / vr_kis_adapter.py 는 무수정.

봉합한 치명 3건:
 🔴1 스키마 가드 — GuardedKIS 서브클래스.
     어댑터의 예외전파(fable5 🔴1/🔴4)는 'rt_cd≠0'만 막는다. '200 OK인데 필드명이
     다른 경우'는 못 막고, 그 필드들이 지금 [부분확인]이다.
       · get_holdings: ovrs_pdno 오인 → 0주 반환 → killswitch가 '실보유 0 확인 —
         CASH 확정'으로 무음실패(주식은 그대로).
       · list_open_orders: pdno 오인 → [] → cancel-first 통과 → 이중 사다리.
     → rows는 있는데 기대 키가 하나도 없으면 KISError로 큰소리로 죽인다.
 🔴2 AUTO_MODE — 체결보고성 명령 거부.
     apply_command '/buy'와 sync_fills가 둘 다 shares/pool/cyc_used를 건드린다.
     자동 켠 채 습관대로 /buy 보내면 같은 체결이 2번 반영.
     (어댑터 헤더 fable5 ③ "봇 쪽 소관" — 봇엔 미구현이었음)
 🔴3 실행순서 — sync_fills를 rollover보다 먼저.
     어댑터 헤더 권고는 'rollover → daily_run(=sync 시작)'인데, 그러면 사이클 마지막
     세션 체결이 난 날:
       ① rollover가 체결 반영 전 pool로 V=V+pool/G → V 왜곡
       ② 같은 stale pool로 cyc_budget 스냅샷 + cyc_used=0 리셋
       ③ 직후 sync가 구사이클 체결 cost를 새 cyc_used에 적재 → 새 사이클 매수한도 선소진
     sync_fills는 fills_seen 멱등 → 먼저 1회 호출해도 daily_run 내부 2차 sync는 no-op.

모의 1단계 설계(확정):
  · use_reserve=False (정규주문). 이유: 모의는 예약주문 조회(TTTT3039R) 미지원 →
    걸린 예약을 API로 확인할 수 없음. 검증 단계에서 검증 불가능한 경로 금지.
  · 크론 23:40 KST (미국 개장 직후). 정규주문은 미국장 중에만 접수.
    신호 기준일(마지막 미국 종가=D-1)은 07:37이든 23:40이든 동일 → 단일 크론 통합 가능.

환경변수:
  KIS_APPKEY / KIS_APPSECRET / KIS_CANO   (필수)
  KIS_ACNT_PRDT_CD=01  KIS_MOCK=on  USE_RESERVE=off
  DRY_RUN=on            ← 기본 ON. 주문 안 나감. 계약·크론·텔레그램 확인용.
  AUTO_MODE=off         ← ON이면 체결보고 명령 거부(자동 sync가 진실원)
  AUTO_RECOVER=off      ← 복귀는 기본 수동(/enter). 켜면 자동 복귀매수.
  STRICT_CCNL=on        ← ccnl 주문당 다행 감지 시 중단(sync_fills 전제 위반)
  + 기존 TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, sys, traceback

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
SYMBOL       = os.environ.get("KIS_SYMBOL", "TQQQ")

# 체결을 '보고'하는 명령 = sync_fills와 진실원이 겹침 → AUTO_MODE에서 거부.
# /setpos·/setv·/setcycle·/reset 은 의도적 '수리' 명령이라 허용(틀리면 reconcile이 잡음).
BLOCKED_IN_AUTO = {"/buy", "/sell", "/exit", "/enter", "/deposit_done", "/lumpsum_done"}


# ══ 🔴1 스키마 가드 ═════════════════════════════════════════════════
class GuardedKIS(KISAdapter):
    """어댑터 무수정 원칙 유지 — 필드 계약 검증만 서브클래스로 덧씌움.
       모의 실측(kis_mock_preflight.py)으로 필드가 확정되면 그대로 둬도 무해
       (KIS가 향후 필드명을 바꾸면 이 가드가 다시 잡아준다)."""
    _EXPECT = {"balance": "ovrs_pdno", "open_ord": "pdno", "fills": "pdno"}

    def _get_paged(self, path, tr_key, params, err, list_key="output", max_pages=10):
        rows = super()._get_paged(path, tr_key, params, err, list_key, max_pages)
        need = self._EXPECT.get(tr_key)
        if need and rows and not any(need in r for r in rows):
            raise KISError(
                f"🔴 스키마 불일치[{tr_key}]: 기대 키 '{need}' 없음. "
                f"조용한 0/[] 반환 = 킬스위치 무음실패·이중사다리 경로 → 중단. "
                f"실제 키={list(rows[0].keys())}")
        # ★ ccnl 행구조: sync_fills는 '(날짜:ODNO)당 누계 1행'을 전제한다.
        #   체결건당 다행이면 delta<=0 → continue → 체결 유실 → shares 과소.
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


# ══ 🔴2 AUTO_MODE 가드 ══════════════════════════════════════════════
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


# ══ 러너 ════════════════════════════════════════════════════════════
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
    auto   = LadderAutomator(broker, SYMBOL, dry_run=DRY_RUN, notify=bot._tg)
    since  = rolling_since(5)

    # ── 🔴3 순서: ① sync_fills 먼저 (구사이클 pool 확정) ──
    try:
        pos = auto.sync_fills(pos, since)
        bot.save_position(pos)
    except Exception as e:
        bot._tg(f"🚨 체결동기화 실패 — 전 단계 중단(안전): {e}")
        raise

    # 가격 힌트는 sync 이후 (봇 원본과 동일 소스)
    px_col = "TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
                             not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ"
    price_hint = float(df[px_col].iloc[-1])

    # ② ensure_V → rollover (이제 체결 반영된 pool로 V·cyc_budget 스냅샷)
    pos = bot.ensure_V(pos, price_hint)
    pos, roll_msg, cycle_changed = bot._cycle_rollover(pos, df)
    if cycle_changed:
        bot.save_position(pos)

    # ③ 명령 처리 (AUTO_MODE면 체결보고 명령 거부)
    V_tmp = pos.get("V", 0.0) or (pos.get("shares", 0.0) * price_hint)
    if ON(bot.VOLTGT_ON) and pos.get("cyc_scale") is not None:
        scale = float(pos["cyc_scale"])
    else:
        rv = float(df["RV"].iloc[-1]) if not bot.pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale = min(1.0, bot.VOLTGT_TARGET / rv) if (ON(bot.VOLTGT_ON) and rv == rv and rv > 0) else 1.0
    Veff_target = V_tmp * scale
    pos, cmd_results = bot.process_commands(pos, price_hint, Veff_target)

    # 포지션 미등록이면 자동매매 진입 금지
    if pos.get("shares", 0) == 0 and pos.get("pool", 0) == 0 and not cmd_results:
        bot._tg("⚠️ 포지션 미등록 — <code>/setpos</code> 먼저. 자동매매 스킵.")
        return

    # ④ daily_run — 내부 sync는 멱등 no-op. compute_ladder 필수(DAY-only 브로커).
    pos = daily_run(auto, pos, bot.compute_signal, df, since, bot.save_position,
                    auto_recover=AUTO_RECOVER, compute_ladder=bot.compute_ladder)

    # ⑤ 리포트 (daily_run이 중간 return해도 항상 발송)
    s = bot.compute_signal(df, pos)
    report = bot.build_report(s, df)
    head = [banner]
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg:
        head.append(f"🔄 {roll_msg}")
    report = "\n".join(head) + "\n\n" + report

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
