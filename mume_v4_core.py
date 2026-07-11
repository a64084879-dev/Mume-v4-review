# -*- coding: utf-8 -*-
"""
무한매수법 V4.0 주문계산 코어 (mume_v4_core.py)
════════════════════════════════════════════════════════════════════════
라오어 원글 posts/043(일반)·044(리버스) 기준. 개인 실행 전용.
⚠ 저작권: 라오어(네이버 카페 무한매수법&밸류리밸런싱). 방법론 재가공·외부 배포 금지.
   이 코드는 은박사 개인 투자 실행 보조용으로만 사용. private 유지.

이 모듈은 '순수 계산'만 담당한다 (외부 API·파일·네트워크 없음).
  입력: 현재 상태(평단·보유·잔금·T·모드·전일종가·5일평균)
  출력: 오늘 걸 LOC/지정가 주문 목록 (제안)
→ 순수 함수라 계산기 표와 1:1 대조 검증이 명확하다.

용어: T=진행회차, 별지점=매수매도 기준가, 잔금=미사용 원금.
════════════════════════════════════════════════════════════════════════
"""
from dataclasses import dataclass, field
from typing import List, Optional
import math

# ══════════════ 종목·분할 설정 ══════════════
# 별% = (STAR0 − SLOPE×T) %.  분할수/2 초과 시 후반전(별% 음수).
TICKER_SPEC = {
    ("TQQQ", 20): {"star0": 15.0, "slope": 1.5,  "tp": 0.15, "rev_div": 10},
    ("TQQQ", 40): {"star0": 15.0, "slope": 0.75, "tp": 0.15, "rev_div": 20},
    ("SOXL", 20): {"star0": 20.0, "slope": 2.0,  "tp": 0.20, "rev_div": 10},
    ("SOXL", 40): {"star0": 20.0, "slope": 1.0,  "tp": 0.20, "rev_div": 20},
}

# 처음매수 큰수 프리미엄(전일종가 대비) — 원글 예시 45.93×1.12=51.44로 12% 확정
FIRST_PREMIUM = 0.12
# 아래 추가매수(폭락 대비, 각 1주, T 안 올림) — 개발자 공식 + 원글 표 4개 30/30 검증:
#   k번째 지점 = 1회매수금 / (기본수량합 + k),  k=1..EXTRA_COUNT
#   (기본수량합 = 처음매수: 큰수수량 / 전반: 별+평단수량 / 후반: 별수량 / 리버스: 쿼터수량)
EXTRA_COUNT   = 8             # 원글 표는 7~8칸. 조정 가능.

def _round2(x): return round(x + 1e-9, 2)   # 소수 2자리(달러)

@dataclass
class State:
    ticker: str                 # "TQQQ" / "SOXL"
    split: int                  # 20 / 40
    seed: float                 # 원금(시드)
    balance: float              # 잔금(미사용 원금)
    shares: int                 # 보유수량
    avg: float                  # 평단
    T: float                    # 진행회차
    mode: str = "normal"        # "normal" / "reverse"
    prev_close: Optional[float] = None       # 전일 종가(처음매수용)
    close5_avg: Optional[float] = None        # 직전 5거래일 종가평균(리버스 별지점)
    rev_first: bool = False      # 리버스 첫날 여부
    closes: Optional[list] = None            # 최근 종가 이력(리버스 5일평균용, 상태갱신이 관리)

    def spec(self): return TICKER_SPEC[(self.ticker, self.split)]

@dataclass
class Order:
    side: str        # "buy" / "sell"
    kind: str        # "LOC" / "지정가" / "MOC"
    price: Optional[float]   # 지정가/LOC 가격 (MOC는 None)
    qty: int
    tag: str         # 표시용
    role: str = ""   # 기계판독용: first_big/star_buy/avg_buy/extra_buy/
                     #             quarter_sell/tp_sell/rev_first_sell/rev_sell/rev_quarter_buy

    def __repr__(self):
        p = "MOC" if self.price is None else f"${self.price:.2f}"
        return f"[{self.side}/{self.kind}] {p} × {self.qty}주 ({self.tag})"

# ══════════════ 공식 ══════════════
def star_pct(state: State) -> float:
    """별% (소수, 예: 0.1425). 후반전이면 음수."""
    s = state.spec()
    return (s["star0"] - s["slope"] * state.T) / 100.0

def star_price(state: State) -> float:
    """별지점 = 평단 × (1+별%)."""
    return _round2(state.avg * (1.0 + star_pct(state)))

def unit_amount(state: State) -> float:
    """1회매수금 = 잔금 / (분할수 − T)."""
    denom = state.split - state.T
    if denom <= 0: return 0.0
    return state.balance / denom

def is_first_half(state: State) -> bool:
    """전반전 = T < 분할수/2."""
    return state.T < state.split / 2.0

# ══════════════ 매수 주문 계산 ══════════════
def _extra_buys(unit: float, base_qty: int, count=EXTRA_COUNT) -> List[Order]:
    """폭락 대비 아래 추가 LOC(각 1주, T 안 올림).
    k번째 지점 = unit/(base_qty+k) — 원글 표 4개(처음/전반/후반/리버스) 30/30 검증."""
    out = []
    if unit <= 0 or base_qty <= 0: return out
    for k in range(1, count + 1):
        p = _round2(unit / (base_qty + k))
        if p <= 0: break
        out.append(Order("buy", "LOC", p, 1, "추가(T무관)", role="extra_buy"))
    return out

def calc_buy_orders(state: State) -> List[Order]:
    orders: List[Order] = []
    star = star_price(state)
    buy_star = _round2(star - 0.01)          # 매수점 = 별지점 − 0.01

    if state.shares == 0 and state.T == 0:
        # ── 처음매수: 전일종가×(1+프리미엄) 큰수 LOC로 1회 의도 ──
        if state.prev_close is None:
            return []   # 전일종가 필요
        big = _round2(state.prev_close * (1.0 + FIRST_PREMIUM))
        unit = state.seed / state.split       # 처음은 시드/분할수
        qty = int(unit // big) if big > 0 else 0
        if qty > 0:
            orders.append(Order("buy", "LOC", big, qty, "처음매수·큰수", role="first_big"))
        orders += _extra_buys(unit, qty)
        return orders

    unit = unit_amount(state)
    if unit <= 0:
        return orders

    if is_first_half(state):
        # ── 전반전: 별지점 절반 + 평단 나머지 ──
        star_qty = int((unit / 2.0) // buy_star) if buy_star > 0 else 0     # (1회/2)/별지점
        total_qty = int(unit // state.avg) if state.avg > 0 else 0          # 1회/평단
        avg_qty = max(0, total_qty - star_qty)                             # 나머지
        if star_qty > 0:
            orders.append(Order("buy", "LOC", buy_star, star_qty, "별지점", role="star_buy"))
        if avg_qty > 0:
            orders.append(Order("buy", "LOC", _round2(state.avg), avg_qty, "평단", role="avg_buy"))
        orders += _extra_buys(unit, star_qty + avg_qty)
    else:
        # ── 후반전: 1회 전액 별지점(평단 아래) ──
        qty = int(unit // buy_star) if buy_star > 0 else 0
        if qty > 0:
            orders.append(Order("buy", "LOC", buy_star, qty, "별지점(후반)", role="star_buy"))
        orders += _extra_buys(unit, qty)
    return orders

# ══════════════ 매도 주문 계산 ══════════════
def calc_sell_orders(state: State) -> List[Order]:
    orders: List[Order] = []
    if state.shares <= 0:
        return orders
    star = star_price(state)                          # 매도점 = 별지점 그대로
    tp = state.spec()["tp"]
    quarter = state.shares // 4                        # 쿼터매도 = 보유 1/4
    rest = state.shares - quarter
    if quarter > 0:
        orders.append(Order("sell", "LOC", star, quarter, "쿼터매도(체결시 T×0.75)", role="quarter_sell"))
    if rest > 0:
        tp_price = _round2(state.avg * (1.0 + tp))
        orders.append(Order("sell", "지정가", tp_price, rest,
                            f"지정가매도+{int(tp*100)}%(체결시 전량종료)", role="tp_sell"))
    return orders

# ══════════════ 리버스모드 주문 계산 ══════════════
def calc_reverse_orders(state: State) -> List[Order]:
    orders: List[Order] = []
    if state.shares <= 0:
        return orders
    div = state.spec()["rev_div"]                      # 40분할=20등분, 20분할=10등분
    if state.rev_first:
        # 첫날: 전체//div MOC 무조건매도 (매수 없음)
        q = state.shares // div
        if q > 0:
            orders.append(Order("sell", "MOC", None, q, "리버스 첫날 MOC매도(T×0.95)", role="rev_first_sell"))
        return orders
    # 둘째날~: 별지점(5일평균) 위 매도 + 별지점 아래 쿼터매수
    if state.close5_avg is None:
        return orders   # 5일평균 필요
    star = _round2(state.close5_avg)
    q_sell = state.shares // div
    if q_sell > 0:
        orders.append(Order("sell", "LOC", star, q_sell, "리버스 무한매도(별지점 위, T×0.95)", role="rev_sell"))
    # 쿼터매수: (잔금+누적매도금)/4 를 별지점−0.01 LOC (원글 예시 48.62→48.61 검증)
    buy_amt = state.balance / 4.0
    buy_price = _round2(star - 0.01)
    q_buy = int(buy_amt // buy_price) if buy_price > 0 else 0
    if q_buy > 0:
        orders.append(Order("buy", "LOC", buy_price, q_buy, "리버스 쿼터매수(T+(N−T)×0.25)", role="rev_quarter_buy"))
    orders += _extra_buys(buy_amt, q_buy)
    return orders

# ══════════════ 통합: 오늘의 주문 제안 ══════════════
def suggest_orders(state: State) -> List[Order]:
    """모드에 따라 오늘 걸 주문 목록 반환."""
    if state.mode == "reverse":
        return calc_reverse_orders(state)
    return calc_buy_orders(state) + calc_sell_orders(state)


if __name__ == "__main__":
    # ── 계산기 대조 검증: 별% 표 (posts/043 · quantstack 계산기) ──
    print("="*70)
    print("  V4 별% 검증 (40분할 TQQQ) — quantstack 계산기 표 대조")
    print("="*70)
    expected = {1:14.25, 2:13.50, 10:7.50, 19:0.75, 20:0.00, 21:-0.75, 40:-15.00}
    st = State("TQQQ",40, 100000,100000, 100, 50.0, 0)
    ok=0
    for T,exp in expected.items():
        st.T=T; got=star_pct(st)*100
        mark = "✅" if abs(got-exp)<1e-9 else "❌"
        if mark=="✅": ok+=1
        print(f"  T={T:>2}: 별% {got:+.2f}%  [계산기 {exp:+.2f}%] {mark}")
    print(f"  → {ok}/{len(expected)} 일치")

    # ── 별지점 검증: 평단 50, 계산기 표(T=1→57.13, T=20→50.00, T=40→42.50) ──
    print("\n  별지점 검증 (평단 $50.00):")
    for T,exp in {1:57.13, 20:50.00, 40:42.50}.items():
        st.T=T; sp=star_price(st)
        print(f"  T={T:>2}: 별지점 ${sp:.2f}  [계산기 ${exp:.2f}] {'✅' if abs(sp-exp)<0.01 else '❌'}")

    # ── 매수 수량 검증: 카페 예시 2건 (별개 상황) ──
    print("\n  매수 수량·별지점 검증 (카페 원글 예시):")
    # 예시A(이즈): SOXL 평단43.46, 별%15%(T=2.5) → 별지점49.98, 별5·평6
    stA = State("SOXL",20, 20000, 504.38*(20-2.5), 110, 43.46, 2.5)
    u=unit_amount(stA); star=star_price(stA); bs=_round2(star-0.01)
    sq=int((u/2.0)//bs); tq=int(u//stA.avg); aq=tq-sq
    print(f"  예시A SOXL: 1회 ${u:.2f}[504.38] 별지점 ${star:.2f}[49.98] 별{sq}주[5] 평{aq}주[6] "
          f"{'✅' if (abs(u-504.38)<0.5 and sq==5 and aq==6) else '❌'}")
    # 예시B(이미지): 20분할SOXL 평단38.30 T=8.6 → 별%2.8% 별지점39.37
    stB = State("SOXL",20, 20000, 20000, 110, 38.30, 8.6)
    print(f"  예시B SOXL: 별% {star_pct(stB)*100:.1f}%[2.8%] 별지점 ${star_price(stB):.2f}[39.37] "
          f"{'✅' if abs(star_price(stB)-39.37)<0.01 else '❌'}")

    # ── 원글 표 4개 전체 재현 (추가매수 사다리 포함) ──
    print("\n"+"="*70)
    print("  원글 주문표 재현 검증 (추가매수 조화급수 공식)")
    print("="*70)
    def _check_ladder(name, orders, exp_main, exp_extras):
        mains=[(o.price,o.qty) for o in orders if "추가" not in o.tag and o.side=="buy"]
        extras=[o.price for o in orders if "추가" in o.tag]
        ok_m = all(any(abs(p-ep)<0.015 and q==eq for p,q in mains) for ep,eq in exp_main)
        ok_e = len(extras)>=len(exp_extras) and all(abs(a-b)<0.015 for a,b in zip(extras,exp_extras))
        print(f"  [{name}] 본매수 {'✅' if ok_m else '❌ '+str(mains)} | 추가 {len(exp_extras)}칸 {'✅' if ok_e else '❌ '+str(extras[:8])}")
        return ok_m and ok_e
    allok=True
    # ① 처음매수: 시드/40=617.89, 전일종가 45.93 → 큰수 51.44×12 + 추가 47.53...32.52
    stF=State("TQQQ",40, 617.89*40, 617.89*40, 0, 0.0, 0, prev_close=45.93)
    allok &= _check_ladder("처음매수", calc_buy_orders(stF),
        [(51.44,12)], [47.53,44.13,41.19,38.61,36.34,34.32,32.52])
    # ② 전반전: unit 539.23 ← 잔금=539.23×(40−T). 평단 69.75, 별매수점 78.11(별% 12% → T=4)
    stH=State("TQQQ",40, 100000, 539.23*(40-4), 100, 69.75, 4.0)
    allok &= _check_ladder("전반전", calc_buy_orders(stH),
        [(78.11,3),(69.75,4)], [67.40,59.91,53.92,49.02,44.93,41.47,38.51])
    # ③ 후반전: unit 568.50, 별지점수량 9 → 사다리 unit/(9+k)
    ext=[_round2(568.50/(9+k)) for k in range(1,9)]
    exp=[56.85,51.68,47.37,43.73,40.60,37.90,35.53,33.44]
    ok3=all(abs(a-b)<0.015 for a,b in zip(ext,exp))
    print(f"  [후반전] 추가 8칸 {'✅' if ok3 else '❌'}"); allok &= ok3
    # ④ 리버스: 잔금/4=544.47, 5일평균 48.62 → 매수점 48.61×11 + 추가 45.37...28.65
    stR=State("TQQQ",40, 100000, 544.47*4, 200, 60.0, 39.5, mode="reverse",
              close5_avg=48.62, rev_first=False)
    allok &= _check_ladder("리버스", [o for o in calc_reverse_orders(stR) if o.side=="buy"],
        [(48.61,11)], [45.37,41.88,38.89,36.29,34.02,32.02,30.24,28.65])
    print(f"\n  ★ 원글 표 재현: {'전건 통과 ✅' if allok else '실패 항목 있음 ❌'}")

    # ── 전체 주문 제안 샘플 ──
    print("\n"+"="*70)
    print("  주문 제안 샘플 (TQQQ 40분할, 평단 $50, 보유 100주, T=5)")
    print("="*70)
    st3 = State("TQQQ",40, 100000, 80000, 100, 50.0, 5.0, prev_close=None)
    for o in suggest_orders(st3):
        print(" ", o)
