# -*- coding: utf-8 -*-
# ============================================================================
# kelly17_research_r2.py — 연구사양서 R1 v1 + 추록1 + ★추록2 구현 (2026-08-14, Gemini 역할)
#   베이스: 검증본 kelly17 R1 구현(md5 1bb4c60bf04b4cf8b21dba25bf4490b5) 최소 수정 — 추2-6.
#   가설(추록2): "출발 고도가 높은 창은 낮은 눈금(48:52)이 우세하다" — 최신 시작 창 2010~2025 실측.
#   · ★증거 등급: 미완결 창 포함 = **방향 관찰 등급**(완결 17년 창인 R1 본편보다 낮음).
#     관찰 전용 — 실전 규칙·정본 파라미터 편입 금지. 본 실험 단독 프레임 확정·기각 불가(추2-4).
#   · 관찰 전용 연구. 산출물의 실전 매매·정본 파라미터 변경 준용(K13 관찰 원칙) 없음.
#   · 정본(fast_boxx_v3tax — 추록1 정정: 현행 150b88ef)·백포본 일체 무접촉(읽기 전용).
#   · 추록1 반영: 합성 3배 신규 제작 철회 — 정본 tqqq_full.csv를 그대로 재사용,
#     2010-02-11부터 실제 TQQQ를 정본 get_data의 splice와 동일 산식(경계일 비율 스케일)으로 접합.
#   · QQQDD 관련 파라미터·로직 없음(상시 금지 준수). 창별 개별 튜닝 없음(전 창 동일 파라미터).
#   · 감사역 반려 4건(2026-08-13) 반영 유지: F-1 코드 단일화 / F-3 ^NDX 실거래일 달력 / F-2 업로드 절차.
#   · 추록2 신규: ①종료일 2모드(E1 최신 / E2 2022-12-30) ②출발 고도 라벨(버블·10년 롤링 백분위) ③게이트 V6.
#     V1'·V2는 추2-5에 따라 본 범위에서 생략(2010 이후 창은 실측 접합 구간이 지배, R1 본편 기통과).
#   · 실행: Colab에서 %run kelly17_research_r2.py  (tqqq_full.csv는 로컬 또는 드라이브에서 자동 탐색)
# ============================================================================
import os, hashlib
import numpy as np
import pandas as pd

# ── [R1 파라미터 — 전 창 동일, 사양 고정] ──────────────────────────────────
ARM_A_W   = 0.48                      # A팔: 합성3배 48 : 현금 52 (눈금 1.44)
ARM_B_W   = 0.60                      # B팔: 합성3배 60 : 현금 40 (눈금 1.80)
SWEEP_W   = [0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84, 1.00]   # 눈금 0.36~3.00
START_YEARS = list(range(2010, 2026)) # ★추2-1: 시작연도 2010~2025 = 16개 창
END_MODE_E2 = "2022-12-30"            # ★추2-1: E2 = 하락 바닥 결산(시작 ≤ 2021 창에만 적용)
E2_MAX_START_YEAR = 2021
MIN_YEARS_JUDGE = 5.0                 # ★추2-1/추2-4: 5년 미만 창은 "참고" 딱지·판정 제외
KELLY_CUT = 1.62                      # (참고 표기용 — 추2-4 판정 규칙은 백분위 기준)
PCTL_HI   = 75.0                      # ★추2-2: 고지대 임계 — B1과 동일 사상, 새 숫자 신설 금지
B1_WIN_D  = int(252 * 10)             # 직전 10년 롤링 창(B1 원형)
B1_MINP_D = int(252 * 3)              # 최소 관측(B1 원형)
M0_FULL_PATHS = ["m0_full.csv", "/content/drive/MyDrive/m0_full.csv"]   # ★1순위: 정본 M0(네트워크 불요)
FRED_CSV  = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BOGMBASE"   # 2순위: 추2-2 공개 경로(키 불요)
M0_ANCHOR = (830.0, 840.0)            # ★추2-5 V6①: 2008-05 M0 단위 앵커(십억$)
FETCH_START = "1985-10-01"
TQQQ_REAL_START = "2010-02-11"
TQQQ_FULL_PATHS = ["tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]  # 정본 데이터(읽기 전용)

def _md5_file(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()

def _ensure_drive():
    """Colab이면 드라이브 마운트 보장(이미 마운트면 무동작). 로컬이면 조용히 통과."""
    if os.path.exists('/content/drive/MyDrive'):
        return
    try:
        from google.colab import drive
        drive.mount('/content/drive')
    except Exception:
        pass

def fetch_m0():
    """★추2-2: FRED BOGMBASE(월간). 주 경로 = fredgraph.csv 공개 경로(API 키 불요).
       Colab에서 FRED 응답 지연이 잦아 짧은 타임아웃·재시도·대체 경로(DBnomics, 키 불요)·로컬 캐시를 둔다.
       정본 load_m0_full과 동일 사상(여러 소스 시도 → 단위 정규화). 최종 단위 판정은 게이트 V6①."""
    import io, requests
    UA = {'User-Agent': 'Mozilla/5.0'}
    CACHE = "m0_bogmbase_cache.csv"

    def _norm(df):
        d = pd.to_datetime(df[df.columns[0]], errors='coerce')
        v = pd.to_numeric(df[df.columns[-1]], errors='coerce')
        s = pd.Series(v.values, index=d).dropna().sort_index()
        if len(s) and s.max() > 100000:
            s = s / 1000.0                      # 백만$ → 십억$ (정본 _norm과 동일)
        return s

    def _ok(s):
        if s is None or len(s) == 0:
            return False
        seg = s[(s.index >= '2008-05-01') & (s.index <= '2008-05-31')]
        return len(seg) > 0 and M0_ANCHOR[0] <= float(seg.iloc[0]) <= M0_ANCHOR[1]

    _ensure_drive()
    for _p in M0_FULL_PATHS:                    # 0) ★정본 m0_full.csv 우선 — 네트워크 0회(tqqq_full.csv와 동일 사상)
        if os.path.exists(_p):
            try:
                s = _norm(pd.read_csv(_p))
                if _ok(s):
                    print(f"  · M0 정본 파일 사용: {_p} ({len(s)}개월 ~{s.index[-1].date()}, "
                          f"md5={_md5_file(_p)[:8]}) — 정본 데이터 재사용, 무수정·네트워크 불요")
                    return s
            except Exception:
                pass

    if os.path.exists(CACHE):                   # 1) 같은 세션 재실행은 캐시로 즉시
        try:
            s = _norm(pd.read_csv(CACHE))
            if _ok(s):
                print(f"  · M0 로컬 캐시 사용: {CACHE} ({len(s)}개월 ~{s.index[-1].date()})")
                return s
        except Exception:
            pass

    s = None; tried = []
    for _ in range(3):                          # 1) 주 경로: fredgraph.csv(사양 지정, 키 불요)
        try:
            r = requests.get(FRED_CSV, headers=UA, timeout=(5, 20))
            r.raise_for_status()
            s = _norm(pd.read_csv(io.StringIO(r.text)))
            if _ok(s):
                print("  · M0 소스: fredgraph.csv(공개 경로)")
                break
            tried.append("fredgraph 앵커 불합격")
        except Exception as e:
            tried.append(f"fredgraph {type(e).__name__}")
            s = None
    if not _ok(s):                              # 2) 대체: DBnomics(키 불요, FRED 미러)
        try:
            r = requests.get("https://api.db.nomics.world/v22/series/FRED/BOGMBASE?observations=1",
                             headers=UA, timeout=(5, 25))
            r.raise_for_status()
            d = r.json()['series']['docs'][0]
            s = _norm(pd.DataFrame({'d': d['period'], 'v': d['value']}))
            if _ok(s):
                print("  · M0 소스: DBnomics(FRED 미러) — 주 경로 지연으로 대체 사용")
        except Exception as e:
            tried.append(f"dbnomics {type(e).__name__}")
    if not _ok(s):
        raise RuntimeError("M0 확보 실패 — 드라이브에 m0_full.csv(정본)가 있으면 네트워크 없이 즉시 해결됩니다. "
                           "시도: " + " / ".join(tried))
    try:
        s.rename('BOGMBASE').rename_axis('DATE').to_csv(CACHE)
    except Exception:
        pass
    print(f"  · M0(BOGMBASE): {len(s)}개월 {s.index[0].date()}~{s.index[-1].date()}")
    return s

def _fetch_close(tk, start):
    import yfinance as yf, time
    df = None
    for _i in range(3):                        # 간헐 지연 대비 재시도
        try:
            df = yf.download(tk, start=start, progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                break
        except Exception:
            df = None
        time.sleep(2)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{tk} 다운로드 실패 — 셀 재실행 권장")
    s = df['Close']
    s = s.squeeze() if hasattr(s, 'squeeze') else s
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s = s[s > 0].dropna()
    return s                                   # ★F-3 반영: B리샘플 제거 — 실제 거래일 달력 유지

def load_tqqq_full():
    """정본 tqqq_full.csv 로드(읽기 전용). 없으면 드라이브 마운트 후 재시도."""
    _ensure_drive()
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
    print("  [R2] 켈리 최신 창 확장 — R1 v1+추록1+★추록2 (방향 관찰 등급·정본 무접촉·QQQDD 금지 준수)")
    print("=" * 100)
    try:
        self_md5 = hashlib.md5(open(__file__, 'rb').read()).hexdigest()
    except Exception:
        self_md5 = "(셀 붙여넣기 실행 — 스크립트 md5는 칠판 raw 파일로 대조)"
    print(f"  · 스크립트 md5: {self_md5}")
    print("  · f_frict 교정값: 해당 없음 — 추록1로 신규 합성(R1-3) 폐기, 정본 tqqq_full.csv 재사용")

    # ── 데이터 ──
    lev, syn, real, scale = build_lev_series()
    ndx = _fetch_close('^NDX', FETCH_START)
    gspc = _fetch_close('^GSPC', FETCH_START)           # ★추2-2: 출발 고도(버블) 주 지표
    irx = _fetch_close('^IRX', "1985-01-01")            # % 단위
    m0 = fetch_m0()                                     # ★추2-2: 십억$ 월간
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

    # ── ★추2-2: 출발 고도(버블·백분위) — 창 분류 라벨 전용(R1-8 위반 아님: 매매 로직 이식 없음) ──
    M0D = m0.reindex(idx.union(m0.index)).ffill().reindex(idx)     # 월간 → 일간 ffill
    GSPC = gspc.reindex(idx).ffill()
    BUB = GSPC / M0D                                               # 버블 = ^GSPC ÷ M0
    PCTL = BUB.rolling(B1_WIN_D, min_periods=B1_MINP_D).apply(
        lambda x: (x[-1] >= x).mean(), raw=True) * 100.0           # 직전 10년 롤링 백분위(B1 원형, 0~100)
    NDX_PEAK = NDX.cummax()                                        # 보조 지표: 사상 고점 대비 %

    # ── 게이트 V6(신규, 추2-5) ──
    print("\n" + "-" * 100)
    m0_0805 = m0[(m0.index >= '2008-05-01') & (m0.index <= '2008-05-31')]
    v6a = (len(m0_0805) > 0) and (M0_ANCHOR[0] <= float(m0_0805.iloc[0]) <= M0_ANCHOR[1])
    print(f"  [V6] ① M0 단위 앵커: 2008-05 = {float(m0_0805.iloc[0]) if len(m0_0805) else float('nan'):.1f}십억$ "
          f"(기대 {M0_ANCHOR[0]:.0f}~{M0_ANCHOR[1]:.0f}) → {'PASS' if v6a else '★FAIL — 중단'}")
    assert v6a, "V6① M0 단위 앵커 실패 — 산식 중단(추록3 결함 전례의 게이트화)"
    _p_valid = PCTL.dropna()
    v6b_range = bool(((_p_valid >= 0.0) & (_p_valid <= 100.0)).all())
    print(f"  [V6] ② 백분위 자가검증: 범위 0~100 {'PASS' if v6b_range else '★FAIL'} "
          f"(유효 {len(_p_valid):,}일 / 최소 {_p_valid.min():.1f} / 최대 {_p_valid.max():.1f})")
    assert v6b_range, "V6② 백분위 범위 실패"

    print("  · V1'·V2는 추2-5에 따라 본 범위 생략 — 2010 이후 창은 실측 접합 구간이 지배"
          "(합성 의존은 2010-01~02-10 몇 주뿐), R1 본편(1bb4c60b)에서 기통과.")

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
    end_modes = [("E1", idx[-1]), ("E2", pd.Timestamp(END_MODE_E2))]
    print("\n" + "-" * 100)
    print(f"  [V3] 창 무결({len(START_YEARS)}개 시작연도 × 종료 2모드): 시작·종료·거래일수 — 결측 0건 확인")
    print(f"       E1 = 데이터 끝({idx[-1].date()}) / E2 = {END_MODE_E2}(시작 ≤ {E2_MAX_START_YEAR} 창에만)")
    v6b2_max = 0.0
    for mode, e_dt in end_modes:
        for y in START_YEARS:
            if mode == "E2" and y > E2_MAX_START_YEAR:
                continue
            w_all = idx[idx >= f"{y}-01-01"]
            if len(w_all) == 0:
                continue
            start = w_all[0]
            win = idx[(idx >= start) & (idx <= e_dt)]
            if len(win) < 30:
                print(f"    [{mode}] {y}: 거래일 {len(win)}일 — 창 성립 불가, 건너뜀")
                continue
            sub_lev = LEV.loc[win]; sub_ndx = NDX.loc[win]; sub_irx = IRXD.loc[win]
            assert not (sub_lev.isna().any() or sub_ndx.isna().any() or sub_irx.isna().any()), f"{mode}/{y} 창 결측"
            rl = sub_lev.pct_change().to_numpy()[1:]
            rn = sub_ndx.pct_change().to_numpy()[1:]
            rc = sub_irx.to_numpy()[1:]
            dts = win[1:]
            span = (win[-1] - win[0]).days
            years = span / 365.25
            note = "참고" if years < MIN_YEARS_JUDGE else ""
            # ★추2-2 출발 고도 라벨(시작일 기준)
            bub0 = float(BUB.loc[start]); pctl0 = float(PCTL.loc[start])
            # V6② 시작일 값 재계산 일치(직접 산출 vs 롤링 결과)
            _hist = BUB.loc[:start].iloc[-B1_WIN_D:]
            _recalc = float((_hist.iloc[-1] >= _hist).mean() * 100.0)
            v6b2_max = max(v6b2_max, abs(_recalc - pctl0))
            grade = "고지대" if pctl0 >= PCTL_HI else "저지대"
            ndx_dd = float(NDX.loc[start] / NDX_PEAK.loc[start] - 1.0) * 100.0
            ndx_cagr = cagr_of(sub_ndx.iloc[0], sub_ndx.iloc[-1], span)
            cash_path = np.cumprod(1.0 + rc)
            cash_cagr = cagr_of(1.0, cash_path[-1], span)
            ex = rn - rc
            edge = ex.mean() * 252.0
            vol = ex.std(ddof=0) * np.sqrt(252.0)
            kelly = edge / (vol ** 2) if vol > 0 else float('nan')
            res_w = {}
            for w in SWEEP_W:
                nav = run_arm(rl, rc, dts, w)
                c_ = cagr_of(1.0, nav[-1], span)
                m_ = float((nav / np.maximum.accumulate(nav) - 1.0).min())
                res_w[w] = (c_, m_)
                sweep_rows.append({"종료모드": mode, "창시작연도": y, "비중%": int(round(w * 100)),
                                   "CAGR%": round(c_ * 100, 3), "MDD%": round(m_ * 100, 2)})
            aC, aM = res_w[ARM_A_W]; bC, bM = res_w[ARM_B_W]
            actual = "A" if aC >= bC else "B"
            pred = "A" if pctl0 >= PCTL_HI else "B"      # ★추2-4 규칙 예측(백분위 기준)
            summary_rows.append({"종료모드": mode, "창시작연도": y, "시작일": str(win[0].date()),
                                 "종료일": str(win[-1].date()), "길이년": round(years, 2), "딱지": note,
                                 "거래일수": len(win), "고도_버블": round(bub0, 4),
                                 "고도_백분위%": round(pctl0, 1), "고도등급": grade,
                                 "NDX_고점대비%": round(ndx_dd, 2),
                                 "NDX_CAGR%": round(ndx_cagr * 100, 3),
                                 "현금_CAGR%": round(cash_cagr * 100, 3), "우위_연%": round(edge * 100, 3),
                                 "출렁임_연%": round(vol * 100, 3), "사후켈리": round(kelly, 3),
                                 "A_CAGR%": round(aC * 100, 3), "A_MDD%": round(aM * 100, 2),
                                 "B_CAGR%": round(bC * 100, 3), "B_MDD%": round(bM * 100, 2),
                                 "실측승자": actual, "규칙예측": pred, "일치": int(actual == pred)})
            mean_irx = float(irx.reindex(win).ffill().mean())
            v4 = abs(cash_cagr * 100 - mean_irx)
            print(f"    [{mode}] {y}: {win[0].date()}~{win[-1].date()} {years:5.2f}년 {len(win):>5,}일 "
                  f"{note:2s}| 고도 {bub0:6.3f}/{pctl0:5.1f}% {grade} | NDX고점대비 {ndx_dd:6.1f}% | "
                  f"켈리 {kelly:5.2f} | 예측 {pred}/실측 {actual} {'O' if actual == pred else 'X'} | "
                  f"[V4] 현금 {cash_cagr*100:5.2f}% vs IRX {mean_irx:5.2f}% ({v4:.2f}%p"
                  f"{' PASS' if v4 <= 0.3 else ' FAIL'})")
            assert v4 <= 0.3, f"V4 실패: {mode}/{y}"
    print(f"  [V6] ② 시작일 백분위 재계산 일치: 최대 편차 {v6b2_max:.6f}%p "
          f"→ {'PASS' if v6b2_max <= 1e-6 else '★FAIL'}")
    assert v6b2_max <= 1e-6, "V6② 재계산 불일치"

    S = pd.DataFrame(summary_rows); W = pd.DataFrame(sweep_rows)
    S.to_csv("summary_r2.csv", index=False, encoding="utf-8-sig")
    W.to_csv("sweep_r2.csv", index=False, encoding="utf-8-sig")

    # ── 판정(추2-4): 길이 5년 이상 창의 규칙 일치율 ≥70% ──
    print("\n" + "=" * 100)
    J = S[S["길이년"] >= MIN_YEARS_JUDGE]
    for mode in ["E1", "E2"]:
        Jm = J[J["종료모드"] == mode]
        if len(Jm) == 0:
            continue
        r = Jm["일치"].mean()
        print(f"  [판정·{mode}] 5년 이상 창 규칙 일치: {int(Jm['일치'].sum())}/{len(Jm)} = {r*100:.0f}%")
    rate = J["일치"].mean() if len(J) else float('nan')
    print(f"  [판정·통합] 5년 이상 창 {int(J['일치'].sum())}/{len(J)} = {rate*100:.0f}% "
          f"→ {'고도 가설 방향 확인(≥70%)' if rate >= 0.70 else '★70% 미만 — 감사역 수정 보고 대상'}")
    print(f"  · 판정 제외(길이 5년 미만 '참고' 창): {len(S) - len(J)}건 — 산출표에는 포함, 판정에서만 제외.")

    # ── 사전 예측 등록 대조(추2-4) ──
    hi = S[S["고도등급"] == "고지대"]; lo = S[S["고도등급"] == "저지대"]
    print(f"  [사전 예측] 고지대(백분위 ≥{PCTL_HI:.0f}%) 창 A승 비율: "
          f"{(hi['실측승자']=='A').mean()*100 if len(hi) else float('nan'):.0f}% ({len(hi)}건, 예측: A 우세)")
    print(f"              저지대(<{PCTL_HI:.0f}%) 창 B승 비율: "
          f"{(lo['실측승자']=='B').mean()*100 if len(lo) else float('nan'):.0f}% ({len(lo)}건, 예측: B 우세)")
    for mode in ["E1", "E2"]:
        h2 = hi[hi["종료모드"] == mode]
        if len(h2):
            print(f"              고지대 A승 비율({mode}): {(h2['실측승자']=='A').mean()*100:.0f}% ({len(h2)}건)"
                  f"{'  ← E2가 E1보다 뚜렷할 것으로 예측(추2-4)' if mode == 'E2' else ''}")
    est_hi = {2021, 2022, 2024, 2025}; est_lo = {2010, 2011, 2012, 2013, 2016, 2023}
    e1 = S[S["종료모드"] == "E1"]
    act_hi = set(e1[e1["고도등급"] == "고지대"]["창시작연도"])
    print(f"  · 잠정 분류(추정) 대 실측 백분위(정본): 고지대 추정 {sorted(est_hi)} / 실측 {sorted(act_hi)}")
    print(f"    저지대 추정 {sorted(est_lo)} / 실측 {sorted(set(e1['창시작연도']) - act_hi)}")
    print("  · 해석·프레임 판정은 감사역 담당 — 본 스크립트는 측정·표만 산출. 본 실험 단독 확정·기각 불가(추2-4).")

    # ── V5 무결성 ──
    print("\n  [V5] 산출물 md5 — 칠판 업로드 후 감사역이 raw+캐시버스팅으로 수신·대조:")
    print(f"      summary_r2.csv : {_md5_file('summary_r2.csv')}  ({len(S)}행)")
    print(f"      sweep_r2.csv   : {_md5_file('sweep_r2.csv')}  ({len(W)}행)")
    print(f"      script         : {self_md5}")
    print("=" * 100)

if __name__ == "__main__":
    main()
