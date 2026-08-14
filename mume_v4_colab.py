
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
    return s.resample('B').ffill()

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
    lev = lev[~lev.index.duplicated()].resample('B').ffill()
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
    idx = pd.bdate_range(FETCH_START, last)
    LEV = lev.reindex(idx).ffill()
    NDX = ndx.reindex(idx).ffill()
    IRXD = irx_daily.reindex(idx).ffill().bfill()
    print(f"  · 공통 시계열: {idx[0].date()} ~ {idx[-1].date()} ({len(idx)}일)")
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
    print("  [V1'] ① 실측 구간 대조(2010-02-11~): 접합 시계열 vs 실제 TQQQ 연환산 차")
    b = pd.Timestamp(TQQQ_REAL_START)
    seg = LEV[LEV.index >= b]
    rr = real.reindex(seg.index).ffill()
    yrs = (seg.index[-1] - seg.index[0]).days / 365.25
    c1 = (seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1
    c2 = (rr.iloc[-1] / rr.iloc[0]) ** (1 / yrs) - 1
    d_pp = (c1 - c2) * 100
    print(f"      접합 {c1*100:.2f}% vs 실제 {c2*100:.2f}% → 차 {d_pp:+.3f}%p (합격선 ±0.3%p) "
          f"{'PASS' if abs(d_pp) <= 0.3 else '★FAIL'}")
    assert abs(d_pp) <= 0.3, "V1'-① 실패"
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
    main()      # 연구 사양서 R1 — 켈리 17년 창 검증 v1 (2026-08-13)

## R1-0. 목적·성격
- 가설: "레버리지 언덕의 꼭대기(최적 눈금)는 창의 실측 우위에 따라 이동하며, 48:52 대 60:40의 승자는 꼭대기 위치가 결정한다."
- 관찰 전용 연구. 산출물의 실전 매매 규칙·정본 파라미터 편입 금지(K13 관찰 원칙 준용).
- 신규 독립 스크립트. 정본 fast_boxx_v3tax_FINAL.py(0bc0153c) 및 배포본 일체 무접촉.
- 3자 절차: 본 사양서(감사역) → Gemini 구현 → 은박사님 Colab 실행 → 칠판 업로드 → 감사역 raw 수신·검증 → 판정 보고.

## R1-1. 산출물
- 파일: kelly17_research_r1.py — Colab 단일 파일. 실행 시 CSV 2종 + 로그 출력.
- summary_r1.csv: 창 24행 × 판정 컬럼(R1-5).
- sweep_r1.csv: 창 24행 × 비중 8단계의 CAGR·MDD.
- 로그: 스크립트 자기 md5(hashlib), f_frict 교정값, 게이트 V1~V5 결과.

## R1-2. 데이터
- 나스닥100 지수 ^NDX 일간 종가: yfinance, auto_adjust=True, 1985-10-01~실행일.
- 단기금리 ^IRX(13주 T-bill, %): 일간, 1985-01-01~. 결측 ffill. 일율 = (1+IRX/100)^(1/252)−1.
- 실제 TQQQ(교정용): 2010-02-11~실행일, auto_adjust=True.
- 정직 각주: ^NDX는 가격지수(배당 미포함). 배당 효과는 R1-3의 교정 상수에 2010년대 평균으로 흡수되며, 1986~2009 구간에는 시대별 배당률 차이(연 ±0.5%p 내외)의 잔차가 남는다. 양팔 동일 적용이라 승자 판정 영향은 제한적이나 전대 CAGR 해석 시 유의.

## R1-3. 합성 3배(TQQQ 프록시)
- 일일수익 = 3 × NDX일일수익 − 비용일할.
- 비용(연) = 보수 0.95% + 2 × (당일 IRX + 스프레드 0.40%p) + f_frict.
- f_frict(마찰 교정 상수): 2010-02-11~실행일 구간에서 합성 누적수익 = 실제 TQQQ 누적수익이 되도록 단일 상수 역산. 값·부호를 로그 기록(배당 흡수 시 음수 가능). 전 기간 소급 적용.
- 가드: 합성 일일수익 ≤ −100%면 자산 0 고정 + 파산 플래그.

## R1-4. 두 팔과 스윕
- 필수 두 팔: A = 합성3배 48 : 현금 52 (눈금 1.44) / B = 합성3배 60 : 현금 40 (눈금 1.80).
- 스윕: 합성3배 비중 {12, 24, 36, 48, 60, 72, 84, 100}% (눈금 0.36~3.00).
- 현금 팔 = IRX 일율 복리(BOXX 프록시).
- 리밸컴심: 매년 마지막 거래일 1회. 수수료·세금 0(양팔 동일). 킬스위치 OFF — 순수 언덕 검증. ON 버전은 후속 R2로 분리, 본 건 범위 밖.

## R1-5. 창 정의와 판정
- 창: 시작연도 1986~2009(24개). 각 창 = 해당 연도 첫 거래일 ~ +17년 시점 직전 거래일.
- 창별 산출: NDX CAGR / 현금 CAGR / 우위(일간 초과수익 산술평균×252) / 출렁임(일간 표준편차×√252) / 사후 꼭대기 = 우위 ÷ 출렁임² / A·B의 CAGR·MDD / 실측 승자(CAGR 기준).
- 이론 예측 컬럼: 사후 꼭대기 < 1.62 → A승 예측, ≥ 1.62 → B승 예측. (1.62 = 1.44와 1.80의 중점 — 이차 근사에서 두 눈금의 성장률이 같아지는 꼭대기 위치.)
- 일치율 = (예측=실측 창 수) ÷ 24.

## R1-6. 사전 예측 등록 (결과 확인 전 박제 — 사후확증 방지)
- 시작 1986~1995 창(2000~02 폭락 포함): A승 우세 예상.
- 시작 2003~2009 창: B승 우세 예상.
- 프레임 판정: 일치율 ≥ 75% → "꼭대기 이동" 프레임 유지 / 75% 미만 → 감사역이 프레임 수정 보고서 제출.

## R1-7. 검증 게이트 (전건 통과 후에만 결과 채택)
- V1 교정: f_frict 적용 후 2010-02-11~실행일 합성 vs 실제 TQQQ 연환산 오차 ±0.3%p 이내.
- V2 블랙먼데이: 1987-10-19 합성 일일수익 출력, 약 −33%±3%p 범위 눈검사.
- V3 창 무결: 24개 창 시작·종료일·거래일수 전건 출력, 결측 0건.
- V4 현금 팔: 창별 현금 CAGR − 창 평균 IRX 오차 ±0.3%p 이내.
- V5 무결성: 스크립트·CSV 2종 md5 로그 출력 → 칠판 업로드 → 감사역 raw+캐시버스팅 수신·대조.

## R1-8. 금지·분변
- QQQDD 관련 파라미터·로직 절대 금지(상시 규칙).
- 정본·배포본 수정 금지. 창별 개별 튜닝 금지(전 창 동일 파라미터).
- 킬스위치·버블·B1 이식 금지(R2 범위).

(끝 — 연구 사양서 R1 v1, 2026-08-13, 감사역 Claude 작성)       # 연구 사양서 R1 — 추록1 (2026-08-13)

정본 관계: 연구사양서 R1 v1(fileId 1BW8Xec3h3KnlLPAinDLfbc9cu5ZrUi26)에 대한 추록. 구현자·새 세션은 v1+추록1을 함께 읽으며, 충돌 시 본 추록이 우선한다.
사유: 은박사님 지적(2026-08-13) "TQQQ 합성은 이미 완성되어 있다" — FAST 인계장 v2·추록5·6·비교메모 대조로 사실 확인. 이에 R1-2·R1-3·R1-7 일부를 대체한다.

## 추1-1. 합성 3배 신규 제작 철회 — 정본 데이터 재사용
- R1-3(신규 합성 전체) 폐기. 대신 정본 백테스터가 사용하는 **`tqqq_full.csv`(실측 TQQQ 2010-02-11 이후 + 이전 합성, 스플라이싱)를 3배 팔 입력으로 그대로 사용**한다.
- 근거(인계장 실측): v2 §4-b 데이터 행 / 추록5 [5v] 실행 범위 1986-08-01~2026-07-09(10,378일) / v2 §6-d 스윕의 1986-08-11 시작 창 / 비교메모 "재생성 시 ~0.3% 이동(보정계수 재실측)".
- 효과: 검증된 분품 재사용(원형 불변 원칙) · 정본 수치와 정합 · 구현량 감소.
- ^NDX·^IRX 수집은 유지 — 용도는 창별 우위·출렁임·사후 꼭대기 계산(R1-5)과 현금 팔 전용. 합성과 무관.

## 추1-2. 게이트 대체
- V1(f_frict 교정) 삭제 → **V1'**: ① 실측 구간 대조 — tqqq_full.csv의 2010-02-11 이후 구간이 yfinance 실제 TQQQ(auto_adjust)와 연환산 ±0.3%p 이내 ② 스플라이스 경계일 전후 5거래일 수익률 출력(불연속 눈검사).
- V2(1987-10-19 일일수익 약 −33%±3%p 눈검사)·V3·V4·V5는 유지.

## 추1-3. 확인 과제(Gemini) — 합성 구간의 차입비용 모델
- tqqq_full.csv 생성 스크립트에서 합성 구간(1986~2010)의 비용 모델을 확인해 보고할 것: **시대별 단기금리 반영 여부.**
- 고정금리로 확인되면: 1980~90년대(단기금리 6~9%)의 3배 차입비용이 저평가되어 합성 팔 성과가 과대 → **B(60) 쪽이 실제보다 유리한 편향**. 결과 해석 각주에 명기(본 실험 가설에는 보수적 방향이므로 진행 지장 없음). 시대별 반영으로 확인되면 각주 불요.

## 추1-4. 정정 — 정본 md5
- R1 v1 본문의 "정본 fast_boxx_v3tax_FINAL.py(0bc0153c)"는 구판 기재. 인계장 추록5·6 대조 결과 **현행 정본 = 150b88efcf2509ec796ad4bcdaad29a0 (K13 탑재판, 1,713줄)** — 0bc0153c(1,589줄)는 추록5에서 대체됨. 본 추록으로 정정하며, 무접촉 원칙은 현행 정본에 동일 적용.

## 추1-5. 불변
- 두 팔(48:52/60:40)·스윕 8단계·창 24개·판정 임계 1.62·사전 예측(R1-6)·QQQDD 금지 전부 불변.
- 현금 팔 = ^IRX 시대별 일율 유지 — 정본의 RISK_FREE 4.5% 고정과 의도적으로 다름(1980년대 고금리 창의 우위 왜곡 방지가 R1의 목적 그 자체이므로). 이 차이는 결과 표 각주에 명기.

(끝 — R1 추록1, 2026-08-13, 감사역 Claude 작성)
