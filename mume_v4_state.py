# -*- coding: utf-8 -*-
"""
무한매수법 V4.0 상태 갱신 로직 (mume_v4_state.py)
════════════════════════════════════════════════════════════════════════
체결 결과(fills)를 받아 T·평단·잔금·보유·모드를 갱신한다. 개인 실행 전용.

T값 규칙 (라오어 원글 posts/043·044 + 개발자 댓글 확정):
  일반모드:
    평단매수 체결(별지점도 체결됨)      → T += 1
    별지점만 체결(평단 미체결)          → T += 0.5
    처음매수(큰수) 체결                 → T = 1
    추가매수(사다리)만 체결             → T += 0
    쿼터매도 체결                       → T ×= 0.75
    지정가매도(+15/20%) 체결            → T ×= 0.25 (같은날 LOC매수 있으면 +1/+0.5)
                                          → 보유 0이면 사이클 종료
    소진: T > N−1                       → 리버스 전환(다음날부터)
  리버스모드:
    매도 체결                           → T ×= 0.95(40분할) / 0.9(20분할)
    쿼터매수 체결                       → T += (N−T)×0.25
    추가매수 체결                       → T += 0
    복귀: 종가 > 평단×(1−tp) 확인       → 다음날부터 일반모드(T·잔금 승계)
    복귀 직후에도 T > N−1이면           → 다시 리버스
  하루 T증가는 0.5 또는 1뿐(원글). ×0.75/×0.95/×0.25는 매도 배수.

평단·잔금:
  매수: 잔금 −= 체결금액, 원가 += 체결금액, 평단 = 원가/보유.
  매도: 잔금 += 체결금액, 원가 −= 평단×수량(평균법: 평단 불변).
  ※ 실전 증권사 평단(수수료 포함 등)과 미세 차이 가능 → 제안형에서는
    사용자가 증권사 앱 평단으로 State.avg를 덮어쓸 수 있음(원글도 실평단 기준).
════════════════════════════════════════════════════════════════════════
"""
from dataclasses import dataclass, field
from typing import List, Optional
from mume_v4_core import State, Order, _round2

CLOSES_KEEP = 30   # 종가 이력 보관수 — VOLTGT RV(20일)+여유. 봇·state 공용.

@dataclass
class Fill:
    """하루 체결 1건. role은 Order.role과 동일."""
    role: str            # first_big/star_buy/avg_buy/extra_buy/quarter_sell/tp_sell/
                         # rev_first_sell/rev_sell/rev_quarter_buy
    price: float         # 체결가
    qty: int             # 체결수량

@dataclass
class UpdateResult:
    state: State
    events: List[str] = field(default_factory=list)   # "사이클종료"/"리버스전환"/"복귀예약" 등
    t_before: float = 0.0
    t_after: float = 0.0
    note: str = ""

def _apply_buy(st: State, f: Fill):
    cost_before = st.avg * st.shares
    st.shares += f.qty
    cost_after = cost_before + f.price * f.qty
    st.avg = cost_after / st.shares if st.shares > 0 else 0.0
    st.balance -= f.price * f.qty

def _apply_sell(st: State, f: Fill):
    q = min(f.qty, st.shares)
    st.shares -= q
    st.balance += f.price * q
    # 평균법: 매도해도 평단 불변. 보유 0이면 평단 리셋은 사이클 종료 처리에서.

def update_state(st: State, fills: List[Fill], today_close: float) -> UpdateResult:
    """하루 체결을 반영해 상태 갱신. 반환: 갱신 상태 + 이벤트."""
    ev: List[str] = []
    t0 = st.T
    shares0 = st.shares
    N = float(st.split)
    tp = st.spec()["tp"]
    rev_mul = 0.95 if st.split == 40 else 0.90

    roles = {f.role for f in fills}

    if st.mode == "normal":
        # ── ① 매도 먼저 (지정가는 장중, 쿼터는 종가) — T 배수 적용 ──
        for f in fills:
            if f.role == "tp_sell":
                _apply_sell(st, f); st.T *= 0.25
        for f in fills:
            if f.role == "quarter_sell":
                _apply_sell(st, f); st.T *= 0.75
        # ── ② 매수 (종가 LOC) — T 가산 ──
        for f in fills:
            if f.role in ("first_big", "star_buy", "avg_buy", "extra_buy"):
                _apply_buy(st, f)
        if "first_big" in roles:
            st.T = 1.0
        elif "avg_buy" in roles:
            st.T += 1.0            # 평단 체결 = 별지점도 체결된 것 (개발자 확정)
        elif "star_buy" in roles:
            # 전반전: 별지점만 = 절반 체결 → +0.5
            # 후반전: 별지점 주문 = 1회매수금 '전액' → +1
            #   [1차 근거] 라오어 원글 posts/79263: T정의(2) "1회매수시 (+1)" + 후반전매수(3)
            #             "1회매수액 전체를 별지점LOC 매수로" → 전액 체결 = 1회매수 = +1
            #   [2차 근거] firegate 개발자 댓글(posts/79413): "후반전 매수 1건... 1증가시켜야",
            #             "절반 초과 결제건은 1로 계산" — 은박사 업로드 스크린샷 원문 확인됨
            #   판정 기준 = 주문 생성 시점 T(t0). 당일 매도(×0.25/×0.75) 후에도 t0로 판정.
            st.T += 0.5 if t0 < N / 2.0 else 1.0
        # extra_buy만: T += 0
        # ── ③ 종료/전환 판정 (사이클종료는 보유>0→0 '전이'에서만 — 데드락 방지) ──
        if st.shares == 0 and shares0 > 0:
            ev.append("사이클종료(보유0)")
            st.T = 0.0; st.avg = 0.0
            # 시드/잔금 재설정은 start_new_cycle()에서 (복리/단리 사용자 선택)
        elif st.shares > 0 and st.T > N - 1.0:
            ev.append("리버스전환(다음날부터)")
            st.mode = "reverse"; st.rev_first = True

    else:  # ── 리버스모드 ──
        for f in fills:
            if f.role in ("rev_first_sell", "rev_sell"):
                _apply_sell(st, f); st.T *= rev_mul
        for f in fills:
            if f.role == "rev_quarter_buy":
                _apply_buy(st, f); st.T += (N - st.T) * 0.25
            elif f.role == "extra_buy":
                _apply_buy(st, f)            # T += 0
        if st.rev_first and ("rev_first_sell" in roles
                             or (st.shares > 0 and st.shares // st.spec()["rev_div"] == 0)):
            st.rev_first = False             # [D] 첫날 MOC가 실제 나간(체결) 경우에만 소모
        if st.shares == 0 and shares0 > 0:
            ev.append("사이클종료(보유0)")
            st.T = 0.0; st.avg = 0.0; st.mode = "normal"
        elif st.avg > 0 and today_close > st.avg * (1.0 - tp):
            ev.append("복귀예약(다음날 일반모드)")
            st.mode = "normal"
            if st.T > N - 1.0:               # 복귀 즉시 재소진 → 다시 리버스
                st.mode = "reverse"; st.rev_first = True
                ev.append("재소진→리버스 유지")

    # ── ④ 종가 이력(리버스 별지점용 5일평균) ──
    st.prev_close = today_close
    if not hasattr(st, "closes") or st.closes is None:
        st.closes = []
    st.closes.append(today_close)
    st.closes = st.closes[-CLOSES_KEEP:]
    if len(st.closes) >= 5:
        # 원글: 리버스 별지점 = '직전 5거래일 종가 평균' — 다음 세션 기준 최근 5개 종가.
        #   (bot.to_State와 동일 정의로 통일 — 이중 정의 제거)
        st.close5_avg = _round2(sum(st.closes[-5:]) / 5.0)

    return UpdateResult(state=st, events=ev, t_before=t0, t_after=st.T)

def start_new_cycle(st: State, new_seed: float) -> State:
    """사이클 종료 후 재시작. new_seed = 사용자가 정한 원금(복리/단리 선택 반영)."""
    st.seed = new_seed
    st.balance = new_seed
    st.shares = 0; st.avg = 0.0; st.T = 0.0
    st.mode = "normal"; st.rev_first = False
    return st


if __name__ == "__main__":
    print("="*70)
    print("  상태 갱신 검증 — 원글 T값 예시 재현")
    print("="*70)
    ok_all = True
    def chk(name, got, exp, tol=1e-9):
        global ok_all
        m = "✅" if abs(got-exp) < tol else f"❌ (got {got})"
        if "❌" in m: ok_all = False
        print(f"  {name}: {got if isinstance(got,int) else round(got,6)} [기대 {exp}] {m}")

    # ① 원글 T 예시: T=7 → 1회매수 8 / 절반 7.5 / 쿼터 5.25
    st = State("TQQQ",40, 20000, 10000, 100, 50.0, 7.0)
    r = update_state(st, [Fill("avg_buy",50.0,4), Fill("star_buy",52.0,3)], 49.0)
    chk("T=7 +1회매수", r.t_after, 8.0)
    st.T=7.0
    update_state(st, [Fill("star_buy",52.0,3)], 53.0); chk("T=7 +절반", st.T, 7.5)
    st.T=7.0
    update_state(st, [Fill("quarter_sell",55.0,25)], 55.0); chk("T=7 쿼터매도", st.T, 5.25)

    # ② 지정가매도 후 LOC매수: T=8 → ×0.25+1 = 3
    st2 = State("TQQQ",40, 20000, 5000, 100, 50.0, 8.0)
    r2 = update_state(st2, [Fill("tp_sell",57.50,75), Fill("avg_buy",50.0,4), Fill("star_buy",52.0,3)], 49.0)
    chk("지정가매도+LOC매수 (×0.25+1)", r2.t_after, 3.0)

    # ③ 리버스 원글 예시: 39.5 → 첫날매도 37.525 → 쿼터매수 38.14375
    st3 = State("TQQQ",40, 20000, 400, 200, 60.0, 39.5, mode="reverse", rev_first=True)
    update_state(st3, [Fill("rev_first_sell",30.0,10)], 30.0)
    chk("리버스 첫날매도", st3.T, 37.525)
    update_state(st3, [Fill("rev_quarter_buy",29.0,5)], 29.0)
    chk("리버스 쿼터매수", st3.T, 38.14375)

    # ④ 사이클 종료: 전량 매도 → 보유0 → T=0, 이벤트
    st4 = State("TQQQ",40, 20000, 5000, 100, 50.0, 8.0)
    r4 = update_state(st4, [Fill("tp_sell",57.50,75), Fill("quarter_sell",57.51,25)], 58.0)
    chk("전량매도 후 보유", st4.shares, 0)
    print(f"  이벤트: {r4.events} {'✅' if '사이클종료(보유0)' in r4.events else '❌'}")

    # ⑤ 소진 → 리버스 전환: 후반전 T=38.7, 별지점 전액 체결 → +1 → 39.7 > 39
    #    (후반전엔 core가 star_buy 전액만 생성 — avg_buy 없음. A패치 반영)
    st5 = State("TQQQ",40, 20000, 600, 300, 45.0, 38.7)
    r5 = update_state(st5, [Fill("star_buy",41.0,13)], 40.0)
    chk("소진 T (후반전 전액 +1)", r5.t_after, 39.7)
    print(f"  이벤트: {r5.events} {'✅' if any('리버스전환' in e for e in r5.events) else '❌'}")
    print(f"  모드: {st5.mode}, rev_first: {st5.rev_first}")

    # ⑥ 리버스 복귀: 종가 > 평단×0.85
    st6 = State("TQQQ",40, 20000, 800, 150, 50.0, 39.6, mode="reverse", rev_first=False,
                close5_avg=41.0)
    r6 = update_state(st6, [], 43.0)   # 종가 43 > 50×0.85=42.5 → 복귀
    print(f"  복귀 이벤트: {r6.events} {'✅' if any('복귀' in e for e in r6.events) else '❌'} (모드={st6.mode})")

    # ⑦ 평단·잔금 회계 검증
    st7 = State("TQQQ",40, 20000, 20000, 0, 0.0, 0.0)
    update_state(st7, [Fill("first_big",51.44,12)], 45.93)
    chk("처음매수 후 T", st7.T, 1.0)
    chk("평단", st7.avg, 51.44, 0.001)
    chk("잔금", st7.balance, 20000-51.44*12, 0.01)
    chk("보유", st7.shares, 12)

    # ⑧ [회귀 A] 전반전 star만 +0.5 / 후반전 star 전액 +1
    stA1 = State("TQQQ",40, 20000, 10000, 100, 50.0, 5.0)
    update_state(stA1, [Fill("star_buy",52.0,4)], 52.0); chk("전반전 star만 +0.5", stA1.T, 5.5)
    stA2 = State("TQQQ",40, 20000, 8000, 200, 50.0, 25.0)
    update_state(stA2, [Fill("star_buy",48.0,11)], 47.5); chk("후반전 star 전액 +1", stA2.T, 26.0)

    # ⑨ [회귀 B] shares 0→0은 사이클종료 미발화 (restart·첫매수미체결 데드락 방지)
    stB = State("TQQQ",40, 21000, 21000, 0, 0.0, 0.0, closes=[45]*5)
    rB = update_state(stB, [], 45.0)
    print(f"  0→0 이벤트 없음: {rB.events} {'✅' if not rB.events else '❌'}")
    if rB.events: ok_all=False

    print("\n  ★ 상태 갱신 검증:", "전건 통과 ✅" if ok_all else "실패 있음 ❌")
