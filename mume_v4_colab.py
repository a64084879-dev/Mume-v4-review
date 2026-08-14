# -*- coding: utf-8 -*-
# ============================================================================
# kelly17_research_r1.py — 연구사양서 R1 v1 + 추록1 구현 (2026-08-13, Gemini 역할)
#   가설: "레버리지 언더의 켈리기준(최적 눈금)은 창의 실측 우위에 따라 이동하며,
#         48:52 대 60:40의 승자는 켈리기준 위치가 결정한다."
#   · 관찰 전용 연구. 산출물의 실전 매매·정본 파라미터 변경 준용(K13 관찰 원칙) 없음.
#   · 정본(fast_boxx_v3tax — 추록1 정정: 현행 150b88ef)·백포본 일체 무접촉(읽기 전용).
#   · 추록1 반영: 합성 3배 신규 제작 철회 — 정본 tqqq_full.csv를 그대로 재사용,
#     2010-02-11부터 실제 TQQQ를 정본 get_data의 splice와 동일 산식(경계일 비율 스케일)으로 접합.
#   · QQQDD 관련 파라미터·로직 없음(상시 금지 준수). 창별 개별 튜닝 없음(전 창 동일 파라미터).
#   · 감사역 반려 4건(2026-08-13) 반영판: F-1 코드 단일화(사양서 원문 미포함) / F-3 ^NDX 실거래일 달력 /
#     F-4 V1'-① 재설계(CSV 합성 겹침 vs 실측 직접 대조) / F-2는 업로드 절차로 대응(Create new file).
#   · 실행: Colab에서 %run kelly17_research_r1.py  (tqqq_full.csv는 로컬 또는 드라이브에서 자동 탐색)
# ============================================================================
import os, hashlib
import numpy as np
import pandas as pd

# ── [R1 파라미터 — 전 창 동일, 사양 고정] ──────────────────────────────────
ARM_A_W   = 0.48                      # A팔: 합성3배 48 : 현금 52 (눈금 1.44)
ARM_B_W   = 0.60                      # B팔: 합성3배 60 : 현금 40 (눈금 1.80)
SWEEP_W   = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84, 1.00]   # 눈금 0.36~3.00
WINDOW_Y  = 17                        # 창 길이(년)
START_YEARS = list(range(1986, 2010)) # 시작연도 1986~2009 = 24개 창
KELLY_CUT = 1.62                      # 판정 임계(1.44와 1.80의 중점 — 사양 고정)
FETCH_START = "1985-10-01"
TQQQ_REAL_START = "2010-02-11"
TQQQ_FULL_PATHS = ["tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]  # 정본 데이터(읽기 전용)

def _md5_file(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()

def _fetch_close(tk, start):
    import yfinance as yf
    df = yf.download(tk, start=start, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{tk} 다운로드 실패")
    s = df['Close']
    s = s.squeeze() if hasattr(s, 'squeeze') else s
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s = s[s > 0].dropna()
    return s                                   # ★F-3 반영: B리샘플 제거 — 실제 거래일 달력 유지

def load_tqqq_full():
    """정본 tqqq_full.csv 로드(읽기 전용). 없으면 드라이브 마운트 후 재시도."""
    for p in TQQQ_FULL_PATHS:
        if os.path.exists(p):
            df = pd.read_csv(p)
            d = pd.to_datetime(df[df.columns[0]])
            c = pd.to_numeric(df["TQQQ"], errors="coerce")
            s = pd.Series(c.values, index=d).dropna()
            print(f"  · tqqq_full.csv 로드: {p} ({len(s)}행, {s.index[0].date()}~{s.index[-1].date()}, "
                  f"md5={_md5_file(p)[:8]}) — 정본 데이터 재사용(추록1), 무수정")
            return s
    try:
        from google.colab import drive
        drive.mount('/content/drive')
    except Exception:
        pass
    for p in TQQQ_FULL_PATHS:
        if os.path.exists(p):
            return load_tqqq_full()
    raise RuntimeError("tqqq_full.csv를 찾지 못함 — 드라이브 MyDrive에 정본 파일이 있어야 함(신규 생성 금지)")

def build_lev_series():
    """3배 팔 가격 시계열 = tqqq_full.csv(합성분) + 실제 TQQQ(2010-02-11~) 스케일 접합.
       접합 산식은 정본 get_data의 splice와 동일: scale = 합성[경계일]/실제[경계일],
       경계일 이후 = 실제×scale. (정본 파이프라인이 메모리에서 만드는 것과 같은 시계열)"""
    syn = load_tqqq_full()
    real = _fetch_close('TQQQ', TQQQ_REAL_START)
    b = pd.Timestamp(TQQQ_REAL_START)
    if b not in syn.index or b not in real.index:
        raise RuntimeError("스플라이스 경계일(2010-02-11)이 한쪽 시계열에 없음")
    scale = syn.loc[b] / real.loc[b]
    lev = pd.concat([syn[syn.index < b], (real * scale)[real.index >= b]]).sort_index()
    lev = lev[~lev.index.duplicated()]          # ★F-3 반영: B리샘플 제거(달력은 main에서 ^NDX 실거래일로 통일)
    return lev, syn, real, scale

def main():
    print("=" * 100)
    print("  [R1] 켈리 17년 창 검증 — v1+추록1 (관찰 전용·정본 무접촉·QQQDD 금지 준수)")
    print("=" * 100)
    try:
        self_md5 = hashlib.md5(open(__file__, 'rb').read()).hexdigest()
    except Exception:
        self_md5 = "(셀 붙여넣기 실행 — %run으로 실행하면 파일 md5 출력)"
    print(f"  · 스크립트 md5: {self_md5}")
    print("  · f_frict 교정값: 해당 없음 — 추록1로 신규 합성(R1-3) 폐기, 정본 tqqq_full.csv 재사용")

    # ── 데이터 ──
    lev, syn, real, scale = build_lev_series()
    ndx = _fetch_close('^NDX', FETCH_START)
    irx = _fetch_close('^IRX', "1985-01-01")            # % 단위
    irx_daily = (1.0 + irx / 100.0) ** (1.0 / 252.0) - 1.0

    last = min(lev.index[-1], ndx.index[-1], irx_daily.index[-1])
    # ★F-3 반영: 기준 달력 = ^NDX 실제 거래일(미국 휴장일 제거 — bdate_range의 0% 희석·이자 과적립 방지)
    idx = ndx.index[(ndx.index >= FETCH_START) & (ndx.index <= last)]
    LEV = lev.reindex(idx).ffill()
    NDX = ndx.loc[idx]
    IRXD = irx_daily.reindex(idx).ffill().bfill()
    print(f"  · 기준 달력: ^NDX 실거래일 {idx[0].date()} ~ {idx[-1].date()} ({len(idx)}일) — 휴장일 미포함")
    print("  · 각주(R1-2): ^NDX는 가격지수(배당 미포함) — 배당 효과는 2010년대 평균으로 정본 보정계수에")
    print("    흡수되며 1986~2009 구간에는 시대별 배당률 차이(연 ±0.5%p 내외)의 잔차가 남는다.")
    print("    양팔 동일 적용이라 승자 판정 영향은 제한적이나, 절대 CAGR 해석 시 유의.")
    print("  · 각주(추1-5): 현금 팔 = ^IRX 시대별 일율 복리 — 정본의 RISK_FREE 4.5% 고정과 의도적으로 다름")
    print("    (1980년대 고금리 창의 우위 왜곡 방지가 R1의 목적 그 자체).")
    print("  · 확인 과제(추1-3) 답: 정본 ensure_tqqq_full의 합성 구간 차입비용은")
    print("    `close = cumprod(1 + lev − (m×EFFR일별 + b)/252)` — FRED DFF 일별 실효연방기금금리")
    print("    시계열 × 실측 승수 m + 고정비 b. 즉 **시대별 금리 반영 확정** → 고정금리 편향 각주 불요.")

    # ── 게이트 V1' ──
    print("\n" + "-" * 100)
    print("  [V1'] ① CSV 원본 대 실측 대조 — ★F-4 반영 재설계(동어반복 제거)")
    print("      ※ 사실관계: tqqq_full.csv에는 실측 구간이 없음(1985-10~2010-03 전부 합성 —")
    print("        정본은 메모리에서 2010-02-11부터 실제 TQQQ를 접합). 따라서 비교 가능한 유일한")
    print("        독립 대조 = CSV '합성' 겹침 구간(2010-02-11~2010-03-31) vs yfinance 실제 TQQQ.")
    b = pd.Timestamp(TQQQ_REAL_START)
    ov = idx[(idx >= b) & (idx <= syn.index.max())]
    syn_o = syn.reindex(ov).ffill()
    real_o = real.reindex(ov).ffill()
    rs = syn_o.pct_change().dropna(); rr_ = real_o.pct_change().dropna()
    cum_gap = ((syn_o.iloc[-1] / syn_o.iloc[0]) - (real_o.iloc[-1] / real_o.iloc[0])) * 100
    corr = float(np.corrcoef(rs.values, rr_.values)[0, 1])
    maxd = float((rs - rr_).abs().max()) * 100
    print(f"      겹침 {ov[0].date()}~{ov[-1].date()}({len(ov)}거래일) | 누적수익 차 {cum_gap:+.3f}%p | "
          f"일간상관 {corr:.4f} | 최대 일간 괴리 {maxd:.3f}%p")
    print("      ※ 겹침이 약 33거래일이라 원사양의 '연환산 ±0.3%p'는 무의미 — 잠정 합격선(감사역 재가 대상):")
    _v1ok = (abs(cum_gap) <= 1.0) and (corr >= 0.995)
    print(f"        |누적 차| ≤ 1.0%p AND 일간상관 ≥ 0.995 → {'PASS' if _v1ok else '★감사역 검토 필요'}")
    print("  [V1'] ② 스플라이스 경계 전후 5거래일 일수익(불연속 눈검사, 경계=2010-02-11):")
    r_all = LEV.pct_change()
    w5 = r_all.loc[b - pd.tseries.offsets.BDay(5): b + pd.tseries.offsets.BDay(5)]
    for d, v in w5.items():
        tag = " ← 경계일(합성 종가→실측×scale 종가)" if d == b else ""
        print(f"        {d.date()}  {v*100:+7.3f}%{tag}")
    print(f"      scale = {scale:.6f}")

    # ── 게이트 V2 ──
    bm = pd.Timestamp("1987-10-19")
    r_bm = float(r_all.loc[bm]) * 100
    ok2 = (-36.0 <= r_bm <= -30.0)
    print(f"\n  [V2] 1987-10-19(블랙먼데이) 합성 일일수익 = {r_bm:+.2f}% (기대 약 −33%±3%p) "
          f"{'PASS' if ok2 else '★범위 밖 — 감사역 보고'}")

    # ── 창 계산 ──
    def cagr_of(path_start, path_end, n_days_span):
        yrs2 = n_days_span / 365.25
        return (path_end / path_start) ** (1 / yrs2) - 1

    def run_arm(rl, rc, dates, w):
        a = w; c = 1.0 - w
        nav = np.empty(len(rl))
        for i in range(len(rl)):
            a *= (1.0 + rl[i]); c *= (1.0 + rc[i])
            nav[i] = a + c
            if i + 1 < len(rl) and dates[i + 1].year != dates[i].year:   # 매년 마지막 거래일 리밸런싱
                a = nav[i] * w; c = nav[i] * (1.0 - w)
        assert nav.min() > 0, "팔 순자산 0 이하 — 파산 플래그"
        return nav

    summary_rows = []; sweep_rows = []
    print("\n" + "-" * 100)
    print("  [V3] 창 무결(24개): 시작·종료·거래일수 — 결측 0건 확인")
    for y in START_YEARS:
        w_idx = idx[(idx >= f"{y}-01-01")]
        start = w_idx[0]
        end_ex = start + pd.DateOffset(years=WINDOW_Y)
        win = idx[(idx >= start) & (idx < end_ex)]
        sub_lev = LEV.loc[win]; sub_ndx = NDX.loc[win]; sub_irx = IRXD.loc[win]
        assert not (sub_lev.isna().any() or sub_ndx.isna().any() or sub_irx.isna().any()), f"{y} 창 결측"
        rl = sub_lev.pct_change().to_numpy()[1:]
        rn = sub_ndx.pct_change().to_numpy()[1:]
        rc = sub_irx.to_numpy()[1:]
        dts = win[1:]
        span = (win[-1] - win[0]).days
        ndx_cagr = cagr_of(sub_ndx.iloc[0], sub_ndx.iloc[-1], span)
        cash_path = np.cumprod(1.0 + rc)
        cash_cagr = cagr_of(1.0, cash_path[-1], span)
        ex = rn - rc
        edge = ex.mean() * 252.0                       # 우위(연)
        vol = ex.std(ddof=0) * np.sqrt(252.0)          # 출렁임(연)
        kelly = edge / (vol ** 2) if vol > 0 else float('nan')   # 사후 켈리기준
        res_w = {}
        for w in SWEEP_W:
            nav = run_arm(rl, rc, dts, w)
            c_ = cagr_of(1.0, nav[-1], span)
            m_ = float((nav / np.maximum.accumulate(nav) - 1.0).min())
            res_w[w] = (c_, m_)
            sweep_rows.append({"창시작연도": y, "비중%": int(round(w * 100)),
                               "CAGR%": round(c_ * 100, 3), "MDD%": round(m_ * 100, 2)})
        aC, aM = res_w[ARM_A_W]; bC, bM = res_w[ARM_B_W]
        actual = "A" if aC >= bC else "B"
        pred = "A" if kelly < KELLY_CUT else "B"
        summary_rows.append({"창시작연도": y, "시작일": str(win[0].date()), "종료일": str(win[-1].date()),
                             "거래일수": len(win), "NDX_CAGR%": round(ndx_cagr * 100, 3),
                             "현금_CAGR%": round(cash_cagr * 100, 3), "우위_연%": round(edge * 100, 3),
                             "출렁임_연%": round(vol * 100, 3), "사후켈리": round(kelly, 3),
                             "A_CAGR%": round(aC * 100, 3), "A_MDD%": round(aM * 100, 2),
                             "B_CAGR%": round(bC * 100, 3), "B_MDD%": round(bM * 100, 2),
                             "실측승자": actual, "예측승자": pred, "일치": int(actual == pred)})
        mean_irx = float(irx.reindex(win).ffill().mean())          # V4용: 창 평균 ^IRX(연%)
        v4 = abs(cash_cagr * 100 - mean_irx)
        print(f"    {y}: {win[0].date()}~{win[-1].date()} {len(win):>5,}일 | 켈리 {kelly:5.2f} | "
              f"예측 {pred} / 실측 {actual} {'✓' if actual == pred else '✗'} | "
              f"[V4] 현금 {cash_cagr*100:5.2f}% vs 평균IRX {mean_irx:5.2f}% (차 {v4:.2f}%p"
              f"{' PASS' if v4 <= 0.3 else ' ★FAIL'})")
        assert v4 <= 0.3, f"V4 실패: {y}"

    S = pd.DataFrame(summary_rows); W = pd.DataFrame(sweep_rows)
    S.to_csv("summary_r1.csv", index=False, encoding="utf-8-sig")
    W.to_csv("sweep_r1.csv", index=False, encoding="utf-8-sig")

    # ── 판정·사전 예측 대조(R1-6) ──
    match = int(S["일치"].sum()); rate = match / len(S)
    g1 = S[(S.창시작연도 >= 1986) & (S.창시작연도 <= 1995)]
    g2 = S[(S.창시작연도 >= 2003) & (S.창시작연도 <= 2009)]
    print("\n" + "=" * 100)
    print(f"  [판정] 켈리기준 임계 {KELLY_CUT} 예측 일치: {match}/{len(S)} = {rate*100:.0f}% "
          f"→ {'프레임 유지(≥75%)' if rate >= 0.75 else '★75% 미만 — 감사역 프레임 수정 보고서 대상'}")
    print(f"  [사전 예측 대조(R1-6)] 1986~1995 창 A승 비율: {(g1.실측승자=='A').mean()*100:.0f}% (예측: A 우세)")
    print(f"                         2003~2009 창 B승 비율: {(g2.실측승자=='B').mean()*100:.0f}% (예측: B 우세)")
    print("  · 해석·프레임 판정은 감사역 담당 — 본 스크립트는 측정·표만 산출.")

    # ── V5 무결성 ──
    print("\n  [V5] 산출물 md5 — 칠판 업로드 후 감사역이 raw+캐시버스팅으로 수신·대조:")
    print(f"      summary_r1.csv : {_md5_file('summary_r1.csv')}  ({len(S)}행)")
    print(f"      sweep_r1.csv   : {_md5_file('sweep_r1.csv')}  ({len(W)}행)")
    print(f"      script         : {self_md5}")
    print("=" * 100)

if __name__ == "__main__":
    main()
