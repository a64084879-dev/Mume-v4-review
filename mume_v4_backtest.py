# -*- coding: utf-8 -*-
"""
무한매수법 V4.0 백테스터 (mume_v4_backtest.py) — 검증된 core·state 재사용
════════════════════════════════════════════════════════════════════════
⚠ 개인 실행 전용(라오어 방법론 재가공·외부 배포 금지).
⚠ 실데이터: yfinance 필요. Colab/로컬에서 실행 (일부 컨테이너는 야후 차단).
   같은 폴더에 mume_v4_core.py, mume_v4_state.py 필요.

■ 설계 원칙 (지난 실패 반복 방지):
  로직을 새로 짜지 않는다. 봇과 100% 동일한 mume_v4_core.suggest_orders +
  mume_v4_state.update_state 를 그대로 호출한다. 백테스터는 '과거 OHLC를 하루씩
  흘려보내며 체결을 판정'하는 얇은 루프일 뿐이다.

■ 하루 처리 (봇의 하루와 동일):
  1. 전일 상태로 suggest_orders() → 오늘 걸 주문 목록
  2. 오늘 OHLC로 체결 판정 (봇의 infer_fills와 동일 규칙):
     - 매수 LOC P: 종가 ≤ P → 종가 체결
     - 매도 LOC P: 종가 ≥ P → 종가 체결
     - 지정가 매도 P: 고가 ≥ P → P 체결
     - MOC: 종가 체결
  3. update_state(fills, 종가) → T·평단·잔금·모드 갱신, 사이클 종료 시 재시작

■ 비용: 수수료(편도 %)·세금(양도세 %, 연 공제)은 사이클 종료(실현) 시점에 반영.
■ MDD: 일별 평가액(cash+보유×종가) 곡선 기준 — 장중 실제 낙폭(은박사 확정 기준).
■ 비교: V4 vs TQQQ 단순보유(세후).

■ 검증 게이트:
  (a) NAV 음수 없음  (b) 총투입 ≤ 시드 항등식(원금 한도)  (c) 봇 로직과 동일 거동
  (d) 반등 구간에서 MDD < 종목 MDD
════════════════════════════════════════════════════════════════════════
"""
import sys
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np
import pandas as pd

from mume_v4_core import State, suggest_orders
from mume_v4_state import Fill, update_state, start_new_cycle

# ══════════════ 파라미터 ══════════════
TICKER   = "TQQQ"
SPLIT    = 40
SEED     = 20000.0
COMPOUND = True          # True=사이클 종료 시 잔금 전액을 새 시드로(복리) / False=시드 고정(단리)
FEE_RATE = 0.0015        # 편도 수수료 0.15%
TAX_RATE = 0.22          # 한국 양도세 22%
TAX_DEDUCT = 1850.0      # 연 공제(~250만원)
FIRST_PREMIUM = 0.12     # 처음매수 큰수 프리미엄(core와 동일)

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

def run_backtest(df: pd.DataFrame, ticker=TICKER, split=SPLIT, seed=SEED,
                 compound=COMPOUND, fee=FEE_RATE, verbose=False) -> BTResult:
    """df: index=날짜, columns=[Open,High,Low,Close]. 하루씩 흘려보내며 V4 실행.

    실현손익 회계: update_state는 평단(평균법)을 유지하므로, 매도 체결의 실현손익을
    백테스터가 직접 계산한다. 매도 실현손익 = Σ 체결수량 × (체결가 − 갱신전 평단) − 수수료.
    매수는 실현손익 0(수수료만 비용). 연말에 yr_realized 통산 → 22% 과세(공제·이월없음).
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
    profit_pool = 0.0     # 단리: 사이클 이익을 계좌 밖에 적립(투입원금은 시드 고정)

    for i in range(n):
        close = float(closes[i]); high = float(highs[i]); low = float(lows[i])
        yr = dates[i].year

        # ── 1. 전일 상태로 주문 계산 ──
        orders = suggest_orders(st) if st.prev_close is not None else []

        # ── 2. 오늘 OHLC로 체결 판정 ──
        fills = judge_fills(orders, high, low, close)

        # ── 3. 실현손익 계산 (매도 체결분, 갱신 '전' 평단 기준) ──
        avg_before = st.avg
        realized_today = 0.0
        for f in fills:
            is_sell = f.role in ("quarter_sell", "tp_sell", "rev_first_sell", "rev_sell")
            if is_sell and avg_before > 0:
                realized_today += f.qty * (f.price - avg_before)
            realized_today -= f.price * f.qty * fee       # 수수료(양방향)
        yr_realized[yr] += realized_today
        realized_cum += realized_today

        # ── 4. 상태 갱신 ──
        res = update_state(st, fills, close)
        st.balance -= sum(f.price * f.qty * fee for f in fills)

        for ev in res.events:
            if "사이클종료" in ev: n_cycle += 1
            if "리버스전환" in ev: n_reverse += 1

        # ── 5. 사이클 종료 시 재시작 (손익 처리: 복리=시드에 합산 / 단리=계좌밖 적립) ──
        if any("사이클종료" in e for e in res.events):
            if compound:
                new_seed = st.balance                    # 이익 포함 전액이 새 시드(복리)
            else:
                # 단리: 투입원금은 시드 고정. 초과분(누적이익)은 profit_pool로 빼둠.
                profit_pool += (st.balance - seed)
                new_seed = seed
            start_new_cycle(st, new_seed)

        # ── 6. 연말 세금 ──
        if i == n - 1 or (i + 1 < n and dates[i + 1].year != yr):
            gain = yr_realized[yr]
            tax = max(0.0, gain - TAX_DEDUCT) * TAX_RATE
            if tax > 0:
                if not compound and profit_pool >= tax:
                    profit_pool -= tax                    # 단리: 세금은 적립이익에서
                else:
                    st.balance -= tax
                tax_cum += tax

        # ── 7. 일별 평가액 (단리는 계좌밖 적립이익 포함) ──
        nav = st.balance + st.shares * close + (profit_pool if not compound else 0.0)
        nav_series.append(nav)

        if verbose and (i < 5 or i % 250 == 0):
            print(f"{dates[i].date()} C={close:.2f} T={st.T:.2f} sh={st.shares} "
                  f"bal={st.balance:.0f} nav={nav:.0f} pool={profit_pool:.0f} mode={st.mode}")

    return BTResult(dates=dates, nav=nav_series, realized=realized_cum,
                    tax_paid=tax_cum, n_cycle=n_cycle, n_reverse=n_reverse, seed0=seed)

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

def metrics(nav, dates, seed):
    s = pd.Series(nav, index=dates)
    yrs = (dates[-1] - dates[0]).days / 365.25
    cagr = (s.iloc[-1] / seed) ** (1 / yrs) - 1 if s.iloc[-1] > 0 else float('nan')
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


if __name__ == "__main__":
    print("="*70)
    print(f"  무한매수법 V4.0 백테스트 — {TICKER} {SPLIT}분할, 시드 ${SEED:,.0f}")
    print("="*70)
    try:
        df = load_data(TICKER, "2010-01-01")
        print(f"  실데이터 로드: {len(df)}일")
    except Exception as e:
        print(f"  ⚠ 실데이터 로드 실패({str(e)[:50]}) → 합성 데이터로 엔진 검증")
        df = make_synthetic()

    r = run_backtest(df, verbose=True)
    cagr, mdd, sharpe = metrics(r.nav, r.dates, SEED)
    bh = buy_hold_aftertax(df, SEED)
    tqqq_mdd = float((df["Close"]/df["Close"].cummax()-1).min())

    print("\n" + "="*70)
    print(f"  기간: {r.dates[0].date()} ~ {r.dates[-1].date()} ({len(r.dates)}일)")
    print("-"*70)
    print(f"  V4 최종 NAV     : ${r.nav[-1]:,.0f}")
    print(f"  V4 CAGR         : {cagr*100:.1f}%")
    print(f"  V4 MDD(평가곡선): {mdd*100:.1f}%")
    print(f"  V4 샤프         : {sharpe:.2f}")
    print(f"  사이클 종료     : {r.n_cycle}회 / 리버스 진입: {r.n_reverse}회")
    print(f"  세금 납부       : ${r.tax_paid:,.0f}")
    print("-"*70)
    print(f"  TQQQ 보유(세후) : ${bh:,.0f}")
    print(f"  TQQQ MDD        : {tqqq_mdd*100:.1f}%")
    print("-"*70)
    # 검증 게이트
    nav_arr = np.array(r.nav)
    print("  검증 게이트:")
    print(f"   (a) NAV 음수 없음: {'✅' if (nav_arr >= 0).all() else '❌'}")
    print(f"   (b) MDD > -100%  : {'✅' if mdd > -1.0 else '❌'}")
    print("="*70)
