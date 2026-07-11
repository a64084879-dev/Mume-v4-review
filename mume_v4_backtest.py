# ============================================================================
#  무한매수법 V4.0 백테스터 — 실 TQQQ 2010~2026 전용 (Colab 단일 셀)
#  ★무매는 정수주 매매라 합성 초고가 구간에서 스케일 왜곡 → 실 TQQQ만 사용.
#  ★다중 시작일: 2010 이후 여러 시점에서 시작했을 때 성과 비교.
#  ★세전 확인(카페 인증 비교)은 TAX_RATE = 0.0
#  검증: core(별% 7/7·원글표), state(T규칙·리버스), backtest(봇일치·항등식닫힘)
#  라오어 원글 기준. 개인 실행 전용(재가공·외부배포 금지).
# ============================================================================
!pip -q install yfinance 2>/dev/null

import numpy as np, pandas as pd, math
from dataclasses import dataclass, field
from typing import List, Optional
from collections import defaultdict

# ═══ [설정] 여기만 바꾸면 됩니다 ═══
TICKER      = "TQQQ"       # "TQQQ" / "SOXL"
SPLIT       = 40           # 20 / 40
SEED        = 20000.0      # 시드(원금)
COMPOUND    = True         # True=복리 / False=단리(원금 고정)
DATA_START  = "2010-02-11" # TQQQ 상장 부근
DATA_END    = None         # None=오늘
WARMUP      = 5            # 워밍업일(이력적재)
FEE_RATE    = 0.0015       # 편도 수수료
TAX_RATE    = 0.22         # 양도세 (세전 확인은 0.0)
TAX_DEDUCT  = 1850.0       # 연 공제
FIRST_PREMIUM = 0.12       # 처음매수 프리미엄
INTRADAY_MDD  = True       # 장중MDD(저가반영)
# 다중 시작일(2010 이후만 유효). []=단일 실행
START_DATES = ["2010-02-11","2013-01-02","2016-01-02","2018-01-02",
               "2020-01-02","2021-01-02","2022-01-02","2024-01-02"]
RUN_VOLTGT = True          # VOLTGT 실험: 순수무매 vs A(unit축소·T지연) vs B(수량만축소)
VOLTGT_TARGET = 0.60       # 목표변동성
VOLTGT_LOOKBACK = 20       # RV 룩백

# ═══ [코어] 주문계산 ═══
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




# ═══ [상태갱신] ═══
from dataclasses import dataclass, field
from typing import List, Optional

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
    st.closes = st.closes[-10:]
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




# ═══ [백테스트 엔진 + 진단] ═══
# ══════════════ 체결 판정 (봇 infer_fills와 동일 규칙) ══════════════
def judge_fills(orders, high: float, low: float, close: float) -> List[Fill]:
    fills = []
    for o in orders:
        if o.qty <= 0:
            continue
        if o.kind == "MOC":
            fills.append(Fill(o.role, close, o.qty))
        elif o.side == "buy":                 # LOC 매수: 종가 ≤ 지정가
            if o.price is not None and close <= o.price:
                fills.append(Fill(o.role, close, o.qty))
        elif o.kind == "LOC":                 # LOC 매도: 종가 ≥ 지정가
            if o.price is not None and close >= o.price:
                fills.append(Fill(o.role, close, o.qty))
        else:                                 # 지정가 매도: 고가 ≥ 지정가 → 지정가 체결
            if o.price is not None and high >= o.price:
                fills.append(Fill(o.role, o.price, o.qty))
    return fills

# ══════════════ 백테스트 엔진 ══════════════
@dataclass
class BTResult:
    dates: list
    nav: list                 # 일별 평가액
    realized: float = 0.0     # 누적 실현손익(세전)
    tax_paid: float = 0.0
    n_cycle: int = 0
    n_reverse: int = 0
    seed0: float = 0.0
    nav_low: list = field(default_factory=list)   # 장중 저가 NAV(장중 MDD용)
    diag: dict = field(default_factory=dict)       # 진단 계측

def run_backtest(df: pd.DataFrame, ticker=TICKER, split=SPLIT, seed=SEED,
                 compound=COMPOUND, fee=FEE_RATE, warmup=WARMUP, verbose=False) -> BTResult:
    """df: index=날짜, columns=[Open,High,Low,Close]. 하루씩 흘려보내며 V4 실행.

    실현손익 회계: update_state는 평단(평균법)을 유지하므로, 매도 체결의 실현손익을
    백테스터가 직접 계산한다. 매도 실현손익 = Σ 체결수량 × (체결가 − 갱신전 평단) − 수수료.
    매수는 실현손익 0(수수료만 비용). 연말에 yr_realized 통산 → 22% 과세(공제·이월없음).

    워밍업(warmup일): 봇의 부트스트랩(첫 N일 이력적재)과 동일하게, 초기 warmup일은
    종가 이력만 쌓고 매수하지 않는다. → 봇과 타이밍 정합 + 오버레이 지표(SMA200 등) 워밍업.
    """
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    dates  = list(df.index)
    n = len(df)

    st = State(ticker, split, seed, seed, 0, 0.0, 0.0, prev_close=None, closes=[])
    from collections import defaultdict
    yr_realized = defaultdict(float)
    realized_cum = 0.0
    tax_cum = 0.0
    n_cycle = 0
    n_reverse = 0
    nav_series = []
    nav_low_series = []    # 장중 저점 NAV(보유×저가) — 장중 MDD용
    profit_pool = 0.0
    # ── 진단 계측 ──
    diag = {
        "days_active": 0,        # 보유 중인 날(사이클 진행 중)
        "days_idle": 0,          # 보유 0 = 현금 방치(사이클 사이 빈 기간)
        "first_buy_attempt": 0,  # 처음매수 주문을 낸 날(보유0·T0에서 시도)
        "first_buy_fail": 0,     # 그날 처음매수가 미체결된 횟수
        "cash_idle_frac": 0.0,   # 잔금/NAV 평균(현금 놀린 비율)
        "invested_frac_sum": 0.0,
        "reverse_days": 0,       # 리버스모드였던 날
        "cycle_lengths": [],     # 각 사이클 길이(일)
        "_cur_cycle_len": 0,
    }

    for i in range(n):
        close = float(closes[i]); high = float(highs[i]); low = float(lows[i])
        yr = dates[i].year

        # ── 워밍업: 첫 warmup일은 종가 이력만 적재(매수 안 함) ──
        if i < warmup:
            st.closes = (st.closes + [close])[-10:]
            st.prev_close = close
            if len(st.closes) >= 5:
                st.close5_avg = _round2(sum(st.closes[-5:]) / 5)
            nav = st.balance
            nav_series.append(nav); nav_low_series.append(nav)
            continue

        # ── 1. 전일 상태로 주문 계산 ──
        orders = suggest_orders(st) if st.prev_close is not None else []

        # ── 진단: 처음매수 시도 여부(보유0·T0) ──
        is_first_attempt = (st.shares == 0 and st.T == 0 and
                            any(o.role == "first_big" for o in orders))
        if is_first_attempt:
            diag["first_buy_attempt"] += 1

        # ── 2. 오늘 OHLC로 체결 판정 ──
        fills = judge_fills(orders, high, low, close)

        # ── 진단: 처음매수 미체결(시도했으나 first_big 체결 없음) ──
        if is_first_attempt and not any(f.role == "first_big" for f in fills):
            diag["first_buy_fail"] += 1

        # ── 3. 실현손익 계산 (매도 체결분, 갱신 '전' 평단 기준) ──
        avg_before = st.avg
        realized_today = 0.0
        for f in fills:
            is_sell = f.role in ("quarter_sell", "tp_sell", "rev_first_sell", "rev_sell")
            if is_sell and avg_before > 0:
                realized_today += f.qty * (f.price - avg_before)
            realized_today -= f.price * f.qty * fee
        yr_realized[yr] += realized_today
        realized_cum += realized_today

        # ── 4. 상태 갱신 ──
        res = update_state(st, fills, close)
        st.balance -= sum(f.price * f.qty * fee for f in fills)

        for ev in res.events:
            if "사이클종료" in ev: n_cycle += 1
            if "리버스전환" in ev: n_reverse += 1

        # ── 5. 사이클 종료 시 재시작 ──
        if any("사이클종료" in e for e in res.events):
            if compound:
                new_seed = st.balance
            else:
                profit_pool += (st.balance - seed)
                new_seed = seed
            start_new_cycle(st, new_seed)

        # ── 6. 연말 세금 ──
        if i == n - 1 or (i + 1 < n and dates[i + 1].year != yr):
            gain = yr_realized[yr]
            tax = max(0.0, gain - TAX_DEDUCT) * TAX_RATE
            if tax > 0:
                if not compound and profit_pool >= tax:
                    profit_pool -= tax
                else:
                    st.balance -= tax
                tax_cum += tax

        # ── 7. 일별 평가액 (종가 NAV + 장중 저가 NAV) ──
        extra = profit_pool if not compound else 0.0
        nav = st.balance + st.shares * close + extra
        nav_low = st.balance + st.shares * low + extra      # 보유분 저가 평가(장중 낙폭)
        nav_series.append(nav); nav_low_series.append(nav_low)

        # ── 진단: 활성/유휴, 현금비율, 리버스, 사이클 길이 ──
        if st.shares > 0:
            diag["days_active"] += 1
            diag["_cur_cycle_len"] += 1
        else:
            diag["days_idle"] += 1
            if diag["_cur_cycle_len"] > 0:
                diag["cycle_lengths"].append(diag["_cur_cycle_len"])
                diag["_cur_cycle_len"] = 0
        if nav > 0:
            diag["invested_frac_sum"] += (st.shares * close) / nav
        if st.mode == "reverse":
            diag["reverse_days"] += 1

        if verbose and (i < warmup + 5 or i % 250 == 0):
            print(f"{dates[i].date()} C={close:.2f} T={st.T:.2f} sh={st.shares} "
                  f"bal={st.balance:.0f} nav={nav:.0f} pool={profit_pool:.0f} mode={st.mode}")

    r = BTResult(dates=dates, nav=nav_series, realized=realized_cum,
                 tax_paid=tax_cum, n_cycle=n_cycle, n_reverse=n_reverse, seed0=seed)
    r.nav_low = nav_low_series
    # 진단 마무리
    active = diag["days_active"]
    diag["invested_frac_avg"] = diag["invested_frac_sum"] / max(1, active + diag["days_idle"])
    if diag["_cur_cycle_len"] > 0:
        diag["cycle_lengths"].append(diag["_cur_cycle_len"])
    r.diag = diag
    return r

# ══════════════ 벤치마크·지표 ══════════════
def buy_hold_aftertax(df, seed):
    """TQQQ 단순보유 세후."""
    p0 = float(df["Close"].iloc[0]); p1 = float(df["Close"].iloc[-1])
    sh = int(seed // (p0 * (1 + FEE_RATE)))
    cost = sh * p0 * (1 + FEE_RATE)
    cash = seed - cost
    gross = sh * p1 * (1 - FEE_RATE) + cash
    gain = gross - seed
    tax = max(0.0, gain - TAX_DEDUCT) * TAX_RATE
    return gross - tax

def metrics(nav, dates, seed, nav_low=None):
    """CAGR·MDD·샤프. nav_low 주면 장중 MDD(고점 대비 장중 저가 낙폭)로 계산."""
    s = pd.Series(nav, index=dates)
    yrs = (dates[-1] - dates[0]).days / 365.25
    cagr = (s.iloc[-1] / seed) ** (1 / yrs) - 1 if s.iloc[-1] > 0 else float('nan')
    if nav_low is not None and INTRADAY_MDD:
        # 장중 MDD: 고점(종가 기준 cummax) 대비 장중 저가 NAV의 최대 낙폭
        peak = s.cummax()
        low = pd.Series(nav_low, index=dates)
        mdd = float((low / peak - 1).min())
    else:
        mdd = float((s / s.cummax() - 1).min())
    ret = s.pct_change().dropna()
    sharpe = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else float('nan')
    return cagr, mdd, sharpe

# ══════════════ 데이터 ══════════════
def load_data(ticker, start="2010-01-01", end=None):
    """실데이터 로드. Colab/로컬에서 yfinance 사용. 실패 시 예외."""
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df[["Open", "High", "Low", "Close"]].dropna()
    if len(df) == 0:
        raise RuntimeError("데이터 0행 — 네트워크/티커 확인")
    return df

def make_synthetic(seed=7, start="2015-01-02", end="2020-12-31", crash=True):
    """합성 OHLC(3배 레버리지 특성). 엔진 검증용."""
    idx = pd.date_range(start, end, freq="B")
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0005, 0.028, len(idx))     # TQQQ류 고변동
    if crash:
        c1 = (idx >= "2018-10-01") & (idx <= "2018-12-31"); ret[np.where(c1)[0]] -= 0.006
        c2 = (idx >= "2020-02-20") & (idx <= "2020-03-23"); ret[np.where(c2)[0]] -= 0.030
        c3 = (idx >= "2020-03-24") & (idx <= "2020-06-01"); ret[np.where(c3)[0]] += 0.015
    close = pd.Series(50 * np.exp(np.cumsum(ret)), index=idx)
    # OHLC: 일중 변동 근사(고가/저가를 종가 기준 ±일변동으로)
    dr = np.abs(rng.normal(0, 0.02, len(idx)))
    high = close * (1 + dr); low = close * (1 - dr)
    op = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame({"Open": op, "High": np.maximum(high, close),
                         "Low": np.minimum(low, close), "Close": close})




# ═══ [다중 시작일 표] ═══
def run_multi(df_full, start_dates):
    print("="*118)
    print(f"  무한매수법 V4 {TICKER} {SPLIT}분할 (시드 ${SEED:,.0f}, {'복리' if COMPOUND else '단리'}, 세후) · 다중 시작일 · 종료 {df_full.index[-1].date()}")
    print("="*118)
    print(f"{'시작일':<12}{'년수':>6}{'원금':>12}{'무매세후':>16}{'TQQQ보유':>16}{'CAGR':>8}{'MDD':>9}{'샤프':>7}{'사이클':>8}{'리버스':>7}{'투자%':>7}")
    print("-"*118)
    data_start = df_full.index[0]; seen=set()
    for sd in start_dates:
        sd_ts = pd.Timestamp(sd); eff = max(sd_ts, data_start)
        if eff in seen:
            print(f"{sd:<12}  (데이터 {data_start.date()}부터 — 위 행과 동일, 스킵)"); continue
        seen.add(eff)
        sub = df_full[df_full.index >= eff]
        if len(sub) < WARMUP + 30:
            print(f"{sd:<12}  데이터 부족(스킵)"); continue
        r = run_backtest(sub, ticker=TICKER, split=SPLIT, seed=SEED, compound=COMPOUND, fee=FEE_RATE, warmup=WARMUP)
        cg, md, sh = metrics(r.nav, r.dates, SEED, r.nav_low)
        bh = buy_hold_aftertax(sub, SEED)
        yrs = (r.dates[-1]-r.dates[0]).days/365.25
        inv = r.diag.get("invested_frac_avg",0)*100
        note = "" if sd_ts >= data_start else f" *실제 {eff.date()}"
        print(f"{sd:<12}{yrs:>6.1f}{SEED:>12,.0f}{r.nav[-1]:>16,.0f}{bh:>16,.0f}{cg*100:>7.1f}%{md*100:>8.1f}%{sh:>7.2f}{r.n_cycle:>8}{r.n_reverse:>7}{inv:>6.0f}%{note}")
    print("="*118)
    print("  ※ 무매세후=V4(세금22%·수수료0.15%) / TQQQ보유=단순보유 세후 / MDD=장중")
    print("="*118)

# ═══ [VOLTGT 오버레이] 순수무매 위에 변동성타겟 (core 무수정) ═══
def rv_series(closes, lookback=VOLTGT_LOOKBACK):
    return closes.pct_change().rolling(lookback).std() * np.sqrt(252)

def _scale_orders(orders, scale):
    out=[]
    for o in orders:
        if o.side=="buy" and o.role in ("first_big","star_buy","avg_buy"):
            q=int(o.qty*scale)
            if q>0: out.append(Order(o.side,o.kind,o.price,q,o.tag,role=o.role))
        else: out.append(o)
    for o in orders:
        if o.role=="extra_buy": out.append(o)
    return out

def run_voltgt(df, mode="PURE", ticker=None, split=None, seed=None, compound=None, fee=None, warmup=None):
    ticker=ticker or TICKER; split=split or SPLIT; seed=seed or SEED
    compound=COMPOUND if compound is None else compound; fee=FEE_RATE if fee is None else fee
    warmup=WARMUP if warmup is None else warmup
    cvals=df["Close"].values; highs=df["High"].values; lows=df["Low"].values; dates=list(df.index)
    rv=rv_series(df["Close"]).values; n=len(df)
    st=State(ticker,split,seed,seed,0,0.0,0.0,prev_close=None,closes=[])
    yr_realized=defaultdict(float); realized_cum=0.0; tax_cum=0.0
    n_cycle=n_reverse=0; nav_series=[]; nav_low=[]; profit_pool=0.0; inv_sum=0.0; active=idle=0
    for i in range(n):
        close=float(cvals[i]); high=float(highs[i]); low=float(lows[i]); yr=dates[i].year
        if i<warmup:
            st.closes=(st.closes+[close])[-10:]; st.prev_close=close
            if len(st.closes)>=5: st.close5_avg=_round2(sum(st.closes[-5:])/5)
            nav_series.append(st.balance); nav_low.append(st.balance); continue
        scale=1.0
        if mode in ("A","B") and not np.isnan(rv[i]) and rv[i]>0:
            scale=min(1.0, VOLTGT_TARGET/rv[i])
        if mode=="A" and scale<1.0:
            rb=st.balance; st.balance=rb*scale
            orders=suggest_orders(st) if st.prev_close is not None else []
            st.balance=rb
        else:
            orders=suggest_orders(st) if st.prev_close is not None else []
            if mode=="B" and scale<1.0: orders=_scale_orders(orders,scale)
        fills=judge_fills(orders,high,low,close)
        ab=st.avg; rt=0.0
        for f in fills:
            if f.role in ("quarter_sell","tp_sell","rev_first_sell","rev_sell") and ab>0:
                rt+=f.qty*(f.price-ab)
            rt-=f.price*f.qty*fee
        yr_realized[yr]+=rt; realized_cum+=rt
        res=update_state(st,fills,close); st.balance-=sum(f.price*f.qty*fee for f in fills)
        for ev in res.events:
            if "사이클종료" in ev: n_cycle+=1
            if "리버스전환" in ev: n_reverse+=1
        if any("사이클종료" in e for e in res.events):
            if compound: ns=st.balance
            else: profit_pool+=(st.balance-seed); ns=seed
            start_new_cycle(st,ns)
        if i==n-1 or (i+1<n and dates[i+1].year!=yr):
            g=yr_realized[yr]; tx=max(0.0,g-TAX_DEDUCT)*TAX_RATE
            if tx>0:
                if not compound and profit_pool>=tx: profit_pool-=tx
                else: st.balance-=tx
                tax_cum+=tx
        extra=profit_pool if not compound else 0.0
        nav=st.balance+st.shares*close+extra
        nav_series.append(nav); nav_low.append(st.balance+st.shares*low+extra)
        if st.shares>0: active+=1
        else: idle+=1
        if nav>0: inv_sum+=(st.shares*close)/nav
    class R: pass
    r=R(); r.nav=nav_series; r.nav_low=nav_low; r.dates=dates
    r.realized=realized_cum; r.tax_paid=tax_cum; r.n_cycle=n_cycle; r.n_reverse=n_reverse
    r.invested=inv_sum/max(1,active+idle); return r

def print_voltgt(df):
    rv=rv_series(df["Close"])
    print("\n"+"="*82)
    print(f"  VOLTGT 실험 — 순수무매 vs A(unit축소·T지연) vs B(수량만축소)")
    print(f"  RV 중앙 {rv.median()*100:.0f}% / 목표 {VOLTGT_TARGET*100:.0f}% / scale<1 비율 {(np.minimum(1,VOLTGT_TARGET/rv.dropna())<1).mean()*100:.0f}%")
    print("="*82)
    print(f"{'방식':<8}{'최종NAV':>14}{'CAGR':>8}{'MDD장중':>10}{'샤프':>7}{'사이클':>8}{'리버스':>7}{'투자%':>7}")
    print("-"*82)
    base=None
    for mode in ["PURE","A","B"]:
        r=run_voltgt(df,mode=mode)
        cg,md,sh=metrics(r.nav,r.dates,SEED,r.nav_low)
        if mode=="PURE": base=(cg,md)
        tag=""
        if mode!="PURE": tag=f"  (MDD {(md-base[1])*100:+.1f}%p, CAGR {(cg-base[0])*100:+.1f}%p)"
        print(f"{mode:<8}{r.nav[-1]:>14,.0f}{cg*100:>7.1f}%{md*100:>9.1f}%{sh:>7.2f}{r.n_cycle:>8}{r.n_reverse:>7}{r.invested*100:>6.0f}%{tag}")
    print("="*82)
    print("  A=변동성 클 때 매수규모↓+진행도 느려짐 / B=규모만↓ / +값이면 순수무매보다 개선")
    print("="*82)


def print_voltgt_multi(df_full, start_dates):
    """각 시작일마다 PURE vs A vs B의 MDD·CAGR 비교 (VOLTGT 일관성 확인)."""
    print("\n"+"="*116)
    print(f"  VOLTGT 다중 시작일 — 각 시점에서 MDD 개선 일관성 (목표변동성 {VOLTGT_TARGET*100:.0f}%)")
    print("="*116)
    print(f"{'시작일':<12}{'PURE CAGR':>11}{'PURE MDD':>10} |{'A CAGR':>9}{'A MDD':>9}{'AΔMDD':>8}{'A샤프':>7} |"
          f"{'B CAGR':>9}{'B MDD':>9}{'BΔMDD':>8}{'B샤프':>7}")
    print("-"*116)
    data_start=df_full.index[0]; seen=set()
    for sd in start_dates:
        eff=max(pd.Timestamp(sd),data_start)
        if eff in seen: continue
        seen.add(eff)
        sub=df_full[df_full.index>=eff]
        if len(sub)<WARMUP+30: continue
        rows={}
        for mode in ["PURE","A","B"]:
            r=run_voltgt(sub,mode=mode)
            cg,md,sh=metrics(r.nav,r.dates,SEED,r.nav_low)
            rows[mode]=(cg,md,sh)
        pc,pm,ps=rows["PURE"]; ac,am,ash=rows["A"]; bc,bm,bsh=rows["B"]
        print(f"{sd:<12}{pc*100:>10.1f}%{pm*100:>9.1f}% |{ac*100:>8.1f}%{am*100:>8.1f}%"
              f"{(am-pm)*100:>+7.1f}{ash:>7.2f} |{bc*100:>8.1f}%{bm*100:>8.1f}%{(bm-pm)*100:>+7.1f}{bsh:>7.2f}")
    print("="*116)
    print("  ΔMDD: + 면 VOLTGT가 낙폭 개선(얕아짐). 모든 시작일서 +면 일관된 효과.")
    print("  샤프 PURE 대비 오르면 위험조정수익 개선 = VOLTGT 채택 근거.")
    print("="*116)

# ═══ [실행] ═══
print("="*70)
print(f"  무한매수법 V4.0 — {TICKER} {SPLIT}분할, 시드 ${SEED:,.0f}, {'복리' if COMPOUND else '단리'}")
print("="*70)
import yfinance as yf
df = yf.download(TICKER, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
if hasattr(df.columns,"levels"): df.columns=[c[0] for c in df.columns]
df = df[["Open","High","Low","Close"]].dropna()
print(f"  데이터(실 {TICKER}): {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}일)")

if START_DATES:
    run_multi(df, START_DATES)
    print()

r = run_backtest(df, ticker=TICKER, split=SPLIT, seed=SEED, compound=COMPOUND, fee=FEE_RATE, warmup=WARMUP)
cagr, mdd, sharpe = metrics(r.nav, r.dates, SEED, r.nav_low)
bh = buy_hold_aftertax(df, SEED)
tqqq_mdd = float((df["Close"]/df["Close"].cummax()-1).min())

print("-"*70)
print(f"  V4 최종 NAV     : ${r.nav[-1]:,.0f}   ({r.nav[-1]/SEED*100-100:+.0f}%)")
print(f"  V4 CAGR         : {cagr*100:.1f}%")
print(f"  V4 MDD({'장중' if INTRADAY_MDD else '종가'}) : {mdd*100:.1f}%")
print(f"  V4 샤프         : {sharpe:.2f}")
print(f"  사이클 종료 {r.n_cycle}회 / 리버스 진입 {r.n_reverse}회")
print(f"  세금 ${r.tax_paid:,.0f} / 누적 실현손익 ${r.realized:,.0f}")
print("-"*70)
print(f"  TQQQ 보유(세후) : ${bh:,.0f}   ({bh/SEED*100-100:+.0f}%)")
print(f"  TQQQ MDD        : {tqqq_mdd*100:.1f}%")
print("="*70)

# ── 진단 ──
d = r.diag; total = d["days_active"]+d["days_idle"]
idle_pct = d["days_idle"]/max(1,total)*100
fail_pct = d["first_buy_fail"]/max(1,d["first_buy_attempt"])*100
print("\n" + "="*70)
print("  진단")
print("="*70)
print(f"  현금 방치(빈 기간) : {d['days_idle']}일 / {total}일 ({idle_pct:.1f}%)   [20%↑면 문제]")
print(f"  평균 투자 비율     : {d.get('invested_frac_avg',0)*100:.1f}%   [무매 보통 40~70%]")
print(f"  처음매수 시도/미체결: {d['first_buy_attempt']}회 / {d['first_buy_fail']}회 ({fail_pct:.0f}% 실패)")
print(f"  리버스모드 일수    : {d['reverse_days']}일 ({d['reverse_days']/max(1,total)*100:.1f}%)")
cl = d.get("cycle_lengths",[])
if cl: print(f"  사이클 길이(일)    : 평균 {np.mean(cl):.0f} / 중앙 {np.median(cl):.0f} / 최대 {max(cl)} (n={len(cl)})")
print("-"*70)
if idle_pct<=20 and fail_pct<=40: print(f"  ✅ 사이클 정상 회전 — 저조함은 세금·벤치마크(TQQQ 강세장) 탓.")
else:
    if idle_pct>20: print(f"  ⚠ 현금 방치 {idle_pct:.0f}%")
    if fail_pct>40: print(f"  ⚠ 처음매수 미체결 {fail_pct:.0f}%")
print("="*70)

# ── VOLTGT 비교 ──
if RUN_VOLTGT:
    print_voltgt(df)
    if START_DATES:
        print_voltgt_multi(df, START_DATES)

# ── 차트 ──
import matplotlib.pyplot as plt
fig,(a1,a2)=plt.subplots(2,1,figsize=(13,8),gridspec_kw={"height_ratios":[3,1]},sharex=True)
s=pd.Series(r.nav,index=r.dates); tq=SEED/float(df["Close"].iloc[0])*df["Close"]
a1.set_title(f"MuMe V4 - {TICKER} {SPLIT}split vs TQQQ-hold (real TQQQ, {'compound' if COMPOUND else 'simple'})")
a1.plot(s.index,s,lw=1.8,color="crimson",label=f"V4 (CAGR {cagr*100:.1f}%, MDD {mdd*100:.1f}%)")
a1.plot(tq.index,tq,lw=1.0,color="steelblue",ls=":",label=f"TQQQ-hold (MDD {tqqq_mdd*100:.1f}%)")
a1.set_yscale("log"); a1.set_ylabel("NAV ($,log)"); a1.legend(); a1.grid(alpha=0.3)
dd=(s/s.cummax()-1)*100
a2.fill_between(dd.index,dd,0,color="crimson",alpha=0.3); a2.set_ylabel("Drawdown(%)"); a2.grid(alpha=0.3)
plt.tight_layout(); plt.show()
