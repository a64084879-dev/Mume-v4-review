# -*- coding: utf-8 -*-
"""
VOLTGT A/B 실험 — 무매 V4에 변동성 타겟 오버레이 (mume_v4_voltgt.py)
════════════════════════════════════════════════════════════════════════
목적: VOLTGT가 무매에 도움 되는지 백테스트로 확인. core·state 무수정.

■ VOLTGT (확정 스펙): 목표변동성 60%, lookback 20일,
  scale = min(1, 0.60 / RV),  RV = 실TQQQ 20일수익률 std × √252
  → 변동성 높을 때 매수 규모를 scale만큼 줄임.

■ 3가지 비교:
  · PURE  : VOLTGT 없음 (순수 무매, 기준선)
  · A     : scale을 1회매수금에 곱함 → 매수량↓ + T진행도 함께 느려짐
            (unit이 줄어 별지점/평단 수량 감소 → 체결시 T가산은 그대로지만
             1주도 못 살 만큼 줄면 미체결 → T 진행 지연. '변동성 클 때 천천히')
  · B     : 매수 '수량'만 scale로 줄이고, T는 정상 진행
            (unit은 원래대로 두고 최종 주문 qty에만 scale 적용 → 규모만 축소)

■ 핵심 차이(은박사·감사 확인): A는 T진행 지연 부수효과 있음, B는 없음.
  둘 다 구현해 백테스트로 어느 쪽이 나은지 확인 (미리 정하지 않음).
════════════════════════════════════════════════════════════════════════
"""
import numpy as np, pandas as pd
from collections import defaultdict

from mume_v4_core import State, suggest_orders, unit_amount, Order
from mume_v4_state import Fill, update_state, start_new_cycle
import mume_v4_backtest as bt

VOLTGT_TARGET = 0.60
VOLTGT_LOOKBACK = 20

def rv_series(closes: pd.Series, lookback=VOLTGT_LOOKBACK) -> pd.Series:
    """실현변동성 RV = 20일 수익률 std × √252 (실 TQQQ 가격 기준)."""
    ret = closes.pct_change()
    return ret.rolling(lookback).std() * np.sqrt(252)

def scale_orders(orders, scale):
    """주문 리스트의 매수 수량에 scale 적용 (방식 B용). 매도는 그대로."""
    out = []
    for o in orders:
        if o.side == "buy" and o.role in ("first_big", "star_buy", "avg_buy"):
            q = int(o.qty * scale)
            if q > 0:
                out.append(Order(o.side, o.kind, o.price, q, o.tag, role=o.role))
            # extra_buy(1주 사다리)는 scale 안 함 (폭락 대비 유지)
        else:
            out.append(o)
    # extra_buy는 원본 유지
    for o in orders:
        if o.role == "extra_buy":
            out.append(o)
    return out


def run_voltgt(df, mode="PURE", ticker="TQQQ", split=40, seed=20000,
               compound=True, fee=0.0015, warmup=5):
    """mode: PURE / A / B. bt.run_backtest를 VOLTGT 주입 버전으로 재구현."""
    closes = df["Close"]; highs = df["High"].values
    lows = df["Low"].values; dates = list(df.index)
    rv = rv_series(closes).values
    cvals = closes.values
    n = len(df)

    st = State(ticker, split, seed, seed, 0, 0.0, 0.0, prev_close=None, closes=[])
    yr_realized = defaultdict(float); realized_cum = 0.0; tax_cum = 0.0
    n_cycle = n_reverse = 0; nav_series = []; nav_low = []; profit_pool = 0.0
    inv_sum = 0.0; active = idle = 0

    for i in range(n):
        close = float(cvals[i]); high = float(highs[i]); low = float(lows[i])
        yr = dates[i].year

        if i < warmup:
            st.closes = (st.closes + [close])[-10:]; st.prev_close = close
            if len(st.closes) >= 5:
                st.close5_avg = bt._round2(sum(st.closes[-5:]) / 5)
            nav_series.append(st.balance); nav_low.append(st.balance); continue

        # ── VOLTGT scale ──
        scale = 1.0
        if mode in ("A", "B") and not np.isnan(rv[i]) and rv[i] > 0:
            scale = min(1.0, VOLTGT_TARGET / rv[i])

        # ── 주문 계산 (방식 A: unit 자체를 줄임) ──
        if mode == "A" and scale < 1.0:
            # unit_amount를 줄이려면 balance를 임시 축소해 suggest → 원복
            real_bal = st.balance
            st.balance = real_bal * scale
            orders = suggest_orders(st) if st.prev_close is not None else []
            st.balance = real_bal
        else:
            orders = suggest_orders(st) if st.prev_close is not None else []
            if mode == "B" and scale < 1.0:
                orders = scale_orders(orders, scale)

        fills = bt.judge_fills(orders, high, low, close)

        avg_before = st.avg; realized_today = 0.0
        for f in fills:
            if f.role in ("quarter_sell","tp_sell","rev_first_sell","rev_sell") and avg_before > 0:
                realized_today += f.qty * (f.price - avg_before)
            realized_today -= f.price * f.qty * fee
        yr_realized[yr] += realized_today; realized_cum += realized_today

        res = update_state(st, fills, close)
        st.balance -= sum(f.price * f.qty * fee for f in fills)
        for ev in res.events:
            if "사이클종료" in ev: n_cycle += 1
            if "리버스전환" in ev: n_reverse += 1
        if any("사이클종료" in e for e in res.events):
            if compound: new_seed = st.balance
            else: profit_pool += (st.balance - seed); new_seed = seed
            start_new_cycle(st, new_seed)

        if i == n-1 or (i+1 < n and dates[i+1].year != yr):
            gain = yr_realized[yr]; tax = max(0.0, gain - bt.TAX_DEDUCT) * bt.TAX_RATE
            if tax > 0:
                if not compound and profit_pool >= tax: profit_pool -= tax
                else: st.balance -= tax
                tax_cum += tax

        extra = profit_pool if not compound else 0.0
        nav = st.balance + st.shares*close + extra
        nav_series.append(nav); nav_low.append(st.balance + st.shares*low + extra)
        if st.shares > 0: active += 1
        else: idle += 1
        if nav > 0: inv_sum += (st.shares*close)/nav

    class R: pass
    r = R()
    r.nav = nav_series; r.nav_low = nav_low; r.dates = dates
    r.realized = realized_cum; r.tax_paid = tax_cum
    r.n_cycle = n_cycle; r.n_reverse = n_reverse
    r.invested = inv_sum / max(1, active+idle)
    return r


if __name__ == "__main__":
    # 로컬 검증: 합성으로 A/B/PURE가 다른 결과 내는지
    idx = pd.date_range("2010-02-11","2026-07-10",freq="B")
    rng = np.random.default_rng(7)
    ret = rng.normal(0.0009,0.028,len(idx))
    for cs,ce in [("2020-02-20","2020-03-23"),("2022-01-01","2022-10-01")]:
        m=(idx>=cs)&(idx<=ce); ret[np.where(m)[0]]-=0.012
    c = pd.Series(1.5*np.exp(np.cumsum(ret)),index=idx)
    op=c.shift(1).fillna(c.iloc[0]); dr=np.abs(rng.normal(0,0.02,len(idx)))
    df=pd.DataFrame({"Open":op,"High":c*(1+dr),"Low":c*(1-dr),"Close":c})

    print("="*78)
    print("  VOLTGT A/B 실험 (합성 검증 — 실행 확인용)")
    print("="*78)
    print(f"{'방식':<8}{'최종NAV':>14}{'CAGR':>8}{'MDD':>9}{'샤프':>7}{'사이클':>8}{'리버스':>7}{'투자%':>7}")
    print("-"*78)
    for mode in ["PURE","A","B"]:
        r = run_voltgt(df, mode=mode)
        cg, md, sh = bt.metrics(r.nav, r.dates, 20000, r.nav_low)
        print(f"{mode:<8}{r.nav[-1]:>14,.0f}{cg*100:>7.1f}%{md*100:>8.1f}%{sh:>7.2f}"
              f"{r.n_cycle:>8}{r.n_reverse:>7}{r.invested*100:>6.0f}%")
    print("="*78)
    print("  PURE=순수무매 / A=unit축소(T지연) / B=수량만축소(T정상)")
    print("  MDD 개선 vs CAGR 손실 트레이드오프를 실데이터에서 확인")
