# -*- coding: utf-8 -*-
# ============================================================================
# kelly17_research_r3.py — 연구사양서 R3 방석재질 v1.1(md5 baaa1510) 구현 v2 (2026-08-14, Gemini 역할)
#   v2(감사 반영 1건): 위기일 보존력(평균·최악) = 이체 없는 '재질 순수 일수익' 기준으로 교정 —
#     단기채·금100·원자재는 원수익 그대로, 혼합은 (2/3×단기채+1/3×금) 고정 가중 근사(각주 인쇄).
#     낙폭·변동성·괴리·CAGR은 현행 유지(주머니·방석 경로 기준).
#   베이스: kelly17 R2 검증본(md5 cf9a976d5bb17dbd6edc19342b4c5ebe) 최소 수정.
#   목적: 방석(주머니 현금 대역) 재질 4팔의 기능 실측 — 눈금 1.44(48:52) 고정, 재질만 비교.
#   · 관찰 전용 — 실전 규칙·정본 파라미터 편입 금지. 정본·배포본 무접촉(읽기 전용).
#   · 판정은 기능 3기준(위기일 보존력·주머니 MDD·계기판 괴리) — **수익 순위로 재질 선택 금지.**
#   · fetch_yf·fetch_gold_intl 은 정본(fast_boxx_v3tax, K13 탑재판 150b88ef)에서 **바이트 그대로 이식**
#     (감사역 바이트 대조 대상). gold_full.csv 캐시 최초 생성 시 md5 로그(구현 지시 유의②).
#   · QQQDD 관련 파라미터·로직 없음. 창별 튜닝 없음(전 창 동일 파라미터).
#   · 실행: Colab에서 %run kelly17_research_r3.py (tqqq_full.csv·gold_full.csv 자동 탐색, 드라이브 자동 마운트)
# ============================================================================
import os, hashlib
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ── [R3 파라미터 — 전 창 동일, 사양 고정] ──────────────────────────────────
RISK_W    = 0.48                       # 주머니: 위험 팔(합성 3배) 48
CUSH_W    = 0.52                       # 방석 52 — 눈금 1.44 고정(비중 스윕 금지)
MIX_BOND  = 2.0 / 3.0                  # 혼합 방석: 단기채 2/3 + 금 1/3(방석 내부 연 1회 리밸)
CRISIS_DD = -0.05                      # 위기일 = 위험 팔 일수익 ≤ −5%
R1_YEARS  = list(range(1986, 2010))    # 주 판정: 완결 17년 창 24개
WINDOW_Y  = 17
START_YEARS = list(range(2010, 2026))  # 방향 관찰: R2 최신 창(E1/E2)
END_MODE_E2 = "2022-12-30"
E2_MAX_START_YEAR = 2021
MIN_YEARS_JUDGE = 5.0                  # 5년 미만 '참고' 딱지(E1/E2만 해당)
FETCH_START = "1985-10-01"
TQQQ_REAL_START = "2010-02-11"
TQQQ_FULL_PATHS = ["tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]
GOLD_FULL_PATHS = ["gold_full.csv", "/content/drive/MyDrive/gold_full.csv"]
GOLD_ANCHOR_LOW  = (250.0, 260.0)      # V7(a): 1999-07-20 부근 저점($/oz)
GOLD_ANCHOR_HIGH = (1880.0, 1930.0)    # V7(a): 2011-09-05/06 부근 고점($/oz)
COMMODITY_CANDS = [("^SPGSCI", "스팟 지수"), ("^BCOM", "선물 초과수익 지수"),
                   ("DBC", "ETF"), ("GSG", "ETF")]   # V7(b): 순서대로 실측, 최초 가용 1개 채택
# 정본 이식 함수(fetch_yf·fetch_gold_intl)의 의존 전역 — 원문 무변경 이식을 위한 이름 셋업
FETCH_START_DATE = FETCH_START
END_DATE = pd.Timestamp.today().strftime('%Y-%m-%d')

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

def fetch_yf(ticker, start=FETCH_START_DATE, end=END_DATE):
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            close = df['Close'].squeeze()
            open_p = df['Open'].squeeze() if 'Open' in df.columns.levels[0] else close
        else:
            close = df['Close']
            open_p = df['Open'] if 'Open' in df.columns else close
        close.index = pd.to_datetime(close.index).tz_localize(None)
        open_p.index = pd.to_datetime(open_p.index).tz_localize(None)
        return close.resample('B').ffill(), open_p.resample('B').ffill()
    except Exception as e:
        print(f"  - {ticker} 실패: {e}")
        return None, None


def fetch_gold_intl(start=FETCH_START_DATE, end=END_DATE):
    import io
    hf_close = None
    try:
        url = "https://huggingface.co/datasets/guydegnol/bulkhours/resolve/main/Gold.csv"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        r.raise_for_status()
        g = pd.read_csv(io.StringIO(r.text))
        g['date'] = pd.to_datetime(g['date'], errors='coerce')
        s = g.set_index('date')['Close'].dropna().sort_index()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s[s > 0]
        s = s[s.index >= pd.to_datetime(start)]
        if len(s) > 0:
            hf_close = s.resample('B').ffill()
    except Exception as e:
        print(f"  - HF guydegnol Gold.csv 실패({e}) -> GC=F 폴백")

    if hf_close is not None and len(hf_close) > 0:
        hf_first = hf_close.first_valid_index()
        hf_last = hf_close.last_valid_index()
        src = f"HF guydegnol Gold.csv (국제 금현물, {hf_first.strftime('%Y-%m-%d')}~{hf_last.strftime('%Y-%m-%d')})"
        if pd.to_datetime(end) > hf_last:
            gcf_c, _ = fetch_yf('GC=F', start=hf_last.strftime('%Y-%m-%d'), end=end)
            if gcf_c is not None and not gcf_c.dropna().empty:
                gcf_c = gcf_c[gcf_c > 0]
                overlap = gcf_c.index[gcf_c.index <= hf_last]
                if len(overlap) > 0 and not pd.isna(hf_close.get(overlap[-1])):
                    scale = hf_close.loc[overlap[-1]] / gcf_c.loc[overlap[-1]]
                else:
                    scale = hf_close.iloc[-1] / gcf_c.iloc[0]
                gcf_ext = (gcf_c * scale)
                gcf_ext = gcf_ext[gcf_ext.index > hf_last]
                hf_close = pd.concat([hf_close, gcf_ext]).sort_index()
                hf_close = hf_close[~hf_close.index.duplicated()].resample('B').ffill()
                src += f" + GC=F연장({hf_last.strftime('%Y-%m-%d')}이후, scale={scale:.4f})"
        return hf_close, hf_close.copy(), src

    gcf_c, gcf_o = fetch_yf('GC=F', start=start, end=end)
    if gcf_c is not None and not gcf_c.dropna().empty:
        fv = gcf_c.first_valid_index()
        return gcf_c, gcf_o, f"GC=F 금선물 폴백 ({fv.strftime('%Y-%m-%d')}~, 이전 횡보가정)"

    return None, None, "금 데이터 없음 (전구간 횡보)"

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

def load_gold():
    """정본 금 시계열 재사용(사양 R3-2). 캐시 gold_full.csv 우선 — 없으면 정본 fetch_gold_intl()
       (위 원문 이식본) 호출 후 종가를 캐시로 저장하고 md5 로그(구현 지시 유의②).
       참고: 정본은 소스 결측 사전 구간을 프록시 합성할 때만 일수익 ±15% 클립을 적용 —
       R3는 소스가 R1 첫 창(1986-01)을 덮는 경우만 진행(아래 검사)하므로 클립 경로 미발동."""
    _ensure_drive()
    for p in GOLD_FULL_PATHS:
        if os.path.exists(p):
            df = pd.read_csv(p)
            s = pd.Series(pd.to_numeric(df[df.columns[-1]], errors='coerce').values,
                          index=pd.to_datetime(df[df.columns[0]])).dropna().sort_index()
            print(f"  · gold_full.csv 캐시 사용: {p} ({len(s)}행, {s.index[0].date()}~{s.index[-1].date()}, "
                  f"md5={_md5_file(p)[:8]}) — 정본 데이터 재사용, 무수정")
            return s
    gc, go, src = fetch_gold_intl(start=FETCH_START, end=END_DATE)
    if gc is None or gc.dropna().empty:
        raise RuntimeError("금 데이터 확보 실패 — 드라이브에 gold_full.csv가 있으면 즉시 해결")
    s = gc.dropna()
    s.rename('gold').rename_axis('DATE').to_csv('gold_full.csv')
    print(f"  · 금 소스: {src}")
    print(f"  · gold_full.csv 캐시 최초 생성: {len(s)}행 {s.index[0].date()}~{s.index[-1].date()}, "
          f"md5={_md5_file('gold_full.csv')} (유의② 기록)")
    return s

def load_commodity():
    """V7(b): 후보를 순서대로 실측, 최초 가용 1개 채택. 실패는 조용히 다음 후보로."""
    for tk, kind in COMMODITY_CANDS:
        try:
            s = _fetch_close(tk, FETCH_START)
            if s is not None and len(s.dropna()) > 250:
                return tk, kind, s.dropna()
        except Exception:
            continue
    return None, None, None

def cagr_of(v0, v1, n_days_span):
    yrs2 = n_days_span / 365.25
    return (v1 / v0) ** (1 / yrs2) - 1

def run_pouch(rl, rA, rB, wA, wB, dates):
    """주머니 = 위험 48 + 방석(재질A wA + 재질B wB, wA+wB=0.52). 매년 마지막 거래일에
       주머니 48:52와 방석 내부 비율을 동시 복원(사양 R3-1). 반환: (주머니 경로, 방석 경로)."""
    r = RISK_W; a = wA; b = wB
    pouch = np.empty(len(rl)); cush = np.empty(len(rl))
    for i in range(len(rl)):
        r *= (1.0 + rl[i]); a *= (1.0 + rA[i]); b *= (1.0 + rB[i])
        pouch[i] = r + a + b; cush[i] = a + b
        if i + 1 < len(rl) and dates[i + 1].year != dates[i].year:
            r = pouch[i] * RISK_W; a = pouch[i] * wA; b = pouch[i] * wB
    assert pouch.min() > 0, "주머니 순자산 0 이하"
    return pouch, cush

def main():
    print("=" * 100)
    print("  [R3] 방석 재질 실측 — 사양 v1.1 (관찰 전용·정본 무접촉·QQQDD 금지 준수)")
    print("=" * 100)
    try:
        self_md5 = hashlib.md5(open(__file__, 'rb').read()).hexdigest()
    except Exception:
        self_md5 = "(셀 붙여넣기 실행 — 스크립트 md5는 칠판 raw 파일로 대조)"
    print(f"  · 스크립트 md5: {self_md5}")
    print("  · **판정 원칙: 수익 순위로 재질을 고르는 것을 금지한다(사양 R3-4).** CAGR은 참고 표기만.")
    print("  · 정직 각주: 이 주머니의 위험 팔은 실제 FAST(금 40%·킬스위치 포함)의 단순 근사 —")
    print("    결과는 재질 간 상대 비교 전용이며 절대 수익·절대 낙폭의 실전 해석 금지.")
    print("  · 각주(v2): 위기일 보존력은 재질 순수 일수익 기준(리밸 이체 미포함) — 혼합은")
    print("    (2/3×단기채+1/3×금) 고정 가중 근사(방석 내부 드리프트 미반영). 낙폭·변동성·괴리는 경로 기준.")

    lev, syn, real, scale = build_lev_series()
    ndx = _fetch_close('^NDX', FETCH_START)
    irx = _fetch_close('^IRX', "1985-01-01")
    irx_daily = (1.0 + irx / 100.0) ** (1.0 / 252.0) - 1.0
    gold = load_gold()
    c_tk, c_kind, comm = load_commodity()

    last = min(lev.index[-1], ndx.index[-1], irx_daily.index[-1], gold.index[-1])
    idx = ndx.index[(ndx.index >= FETCH_START) & (ndx.index <= last)]
    LEV = lev.reindex(idx).ffill()
    IRXD = irx_daily.reindex(idx).ffill().bfill()
    GOLD = gold.reindex(idx).ffill()
    print(f"  · 기준 달력: ^NDX 실거래일 {idx[0].date()} ~ {idx[-1].date()} ({len(idx)}일) — 휴장일 미포함")
    assert gold.index[0] <= pd.Timestamp("1986-01-02"), f"금 시계열 시작({gold.index[0].date()})이 R1 첫 창을 못 덮음"
    print("  · 각주(추1-5 유지): 단기채 팔 = ^IRX 시대별 일율 복리(정본 RISK_FREE 4.5% 고정과 의도적 상이).")

    # ── V7(a) 금 단위 앵커 ──
    print("\n" + "-" * 100)
    g_low = float(GOLD.loc["1999-07-01":"1999-08-31"].min())
    g_high = float(GOLD.loc["2011-08-15":"2011-09-30"].max())
    ok_l = GOLD_ANCHOR_LOW[0] <= g_low <= GOLD_ANCHOR_LOW[1]
    ok_h = GOLD_ANCHOR_HIGH[0] <= g_high <= GOLD_ANCHOR_HIGH[1]
    print(f"  [V7] (a) 금 단위 앵커: 1999-07 부근 저점 {g_low:.1f}$/oz (기대 {GOLD_ANCHOR_LOW[0]:.0f}~{GOLD_ANCHOR_LOW[1]:.0f}) "
          f"{'PASS' if ok_l else '★FAIL'} | 2011-09 부근 고점 {g_high:.1f}$/oz "
          f"(기대 {GOLD_ANCHOR_HIGH[0]:.0f}~{GOLD_ANCHOR_HIGH[1]:.0f}) {'PASS' if ok_h else '★FAIL'}")
    assert ok_l and ok_h, "V7(a) 금 단위 앵커 실패 — 산식 중단"

    # ── V7(b) 원자재 보고 ──
    if comm is not None:
        COMM = comm.reindex(idx).ffill()
        c_start = comm.index[0]
        exp_days = int((idx >= c_start).sum()); miss = exp_days - int(comm.reindex(idx[idx >= c_start]).notna().sum())
        print(f"  [V7] (b) 원자재 채택: {c_tk} ({c_kind}) | 실측 시작일 {c_start.date()} | "
              f"결측 {max(miss,0)}일(거래일 대비, ffill 전)")
        if c_kind == "스팟 지수":
            print("      각주(필수): 선물 롤 비용 미반영으로 원자재 팔에 유리한 편향 존재.")
    else:
        COMM = None; c_start = None
        print("  [V7] (b) 원자재: 전 후보 실측 실패 — 원자재 팔 전체 공란 처리(사유: 데이터 없음)")

    # ── V7(c) 위기일 스팟 눈검사 ──
    print("  [V7] (c) 위기일 스팟(기대값 미등록 — 감사역 눈검사):")
    rg_all = GOLD.pct_change()
    rc_all = None if COMM is None else COMM.pct_change()
    for d in ["2008-09-29", "2008-10-15", "2020-03-12", "2020-03-16"]:
        dd = pd.Timestamp(d)
        gtxt = f"금 {rg_all.loc[dd]*100:+.2f}%" if dd in rg_all.index else "금 —"
        ctxt = ""
        if rc_all is not None and dd in rc_all.index and dd >= c_start:
            ctxt = f" | 원자재 {rc_all.loc[dd]*100:+.2f}%"
        print(f"        {d}: {gtxt}{ctxt}")

    # ── 창 열거: R1 주판정 + E1/E2 방향 관찰 ──
    wins = []
    for y in R1_YEARS:
        w_all = idx[idx >= f"{y}-01-01"]; start = w_all[0]
        end_ex = start + pd.DateOffset(years=WINDOW_Y)
        wins.append(("R1", y, idx[(idx >= start) & (idx < end_ex)]))
    for y in START_YEARS:
        w_all = idx[idx >= f"{y}-01-01"]; start = w_all[0]
        wins.append(("E1", y, idx[(idx >= start) & (idx <= idx[-1])]))
        if y <= E2_MAX_START_YEAR:
            wins.append(("E2", y, idx[(idx >= start) & (idx <= pd.Timestamp(END_MODE_E2))]))

    rows = []
    print("\n" + "-" * 100)
    print(f"  [V3] 창 무결({len(wins)}창 = R1 24 + E1 16 + E2 12): 시작·종료·거래일수 — 결측 0건 확인")
    agg = {}
    for mode, y, win in wins:
        sub_lev = LEV.loc[win]; sub_irx = IRXD.loc[win]; sub_gold = GOLD.loc[win]
        assert not (sub_lev.isna().any() or sub_irx.isna().any() or sub_gold.isna().any()), f"{mode}/{y} 결측"
        rl = sub_lev.pct_change().to_numpy()[1:]
        rc = sub_irx.to_numpy()[1:]
        rg = sub_gold.pct_change().to_numpy()[1:]
        z = np.zeros_like(rl)
        dts = win[1:]
        span = (win[-1] - win[0]).days; years = span / 365.25
        note = "참고" if (mode != "R1" and years < MIN_YEARS_JUDGE) else ""
        mask = rl <= CRISIS_DD; ncr = int(mask.sum())
        mean_irx = float(irx.reindex(win).ffill().mean())
        # [V4] 단기채 팔 대조는 독립 현금 경로로(주머니 방석 팔은 연 리밸 이체가 섞여 부적합 — R2 방식 유지)
        cash_cagr = cagr_of(1.0, float(np.cumprod(1.0 + rc)[-1]), span)
        v4 = abs(cash_cagr * 100 - mean_irx)
        assert v4 <= 0.3, f"V4 실패 {mode}/{y}: {v4:.2f}%p"
        mats = [("단기채", rc, z, CUSH_W, 0.0), ("금100", rg, z, CUSH_W, 0.0),
                ("혼합", rc, rg, CUSH_W * MIX_BOND, CUSH_W * (1 - MIX_BOND))]
        has_comm = (COMM is not None) and (c_start <= win[0])
        if has_comm:
            rcm = COMM.loc[win].pct_change().to_numpy()[1:]
            mats.append(("원자재", rcm, z, CUSH_W, 0.0))
        vol_bond = None; line = []
        for name, rA, rB, wA, wB in mats:
            pouch, cush = run_pouch(rl, rA, rB, wA, wB, dts)
            r_pch = pouch / np.r_[1.0, pouch[:-1]] - 1.0
            # ★v2(감사 반영): 위기일 보존력은 이체 없는 '재질 순수 일수익'으로 측정 —
            #   단일 재질은 원수익 그대로(wB=0), 혼합은 (2/3×단기채+1/3×금) 고정 가중 근사.
            r_pure = (wA * rA + wB * rB) / (wA + wB)
            mdd = float((np.r_[1.0, pouch] / np.maximum.accumulate(np.r_[1.0, pouch]) - 1.0).min())
            vol = float(r_pch.std(ddof=0) * np.sqrt(252.0))
            if name == "단기채":
                vol_bond = vol
            cmean = float(r_pure[mask].mean() * 100) if ncr else float('nan')
            cworst = float(r_pure[mask].min() * 100) if ncr else float('nan')
            gap = (vol - vol_bond) * 100
            rows.append({"모드": mode, "창시작연도": y, "시작일": str(win[0].date()), "종료일": str(win[-1].date()),
                         "길이년": round(years, 2), "딱지": note, "거래일수": len(win), "재질": name,
                         "위기일수": ncr, "위기일_방석_평균%": round(cmean, 3) if ncr else "",
                         "위기일_방석_최악%": round(cworst, 3) if ncr else "",
                         "주머니_MDD%": round(mdd * 100, 2), "주머니_연변동성%": round(vol * 100, 2),
                         "괴리_%p": round(gap, 2),
                         "참고_주머니_CAGR%": round(cagr_of(1.0, pouch[-1], span) * 100, 3),
                         "참고_방석_CAGR%": round(cagr_of(CUSH_W, cush[-1], span) * 100, 3)})
            line.append(f"{name} 보존{cmean:+.2f}%/최악{cworst:+.2f}%·MDD{mdd*100:.1f}·괴리{gap:+.2f}p" if ncr
                        else f"{name} MDD{mdd*100:.1f}·괴리{gap:+.2f}p")
            a = agg.setdefault(name, {"crisis": [], "mdd_r1": [], "gap_r1": []})
            if ncr: a["crisis"].append(r_pure[mask])
            if mode == "R1":
                a["mdd_r1"].append(mdd * 100); a["gap_r1"].append(gap)
        if not has_comm:
            rows.append({"모드": mode, "창시작연도": y, "시작일": str(win[0].date()), "종료일": str(win[-1].date()),
                         "길이년": round(years, 2), "딱지": "데이터없음", "거래일수": len(win), "재질": "원자재",
                         "위기일수": ncr, "위기일_방석_평균%": "", "위기일_방석_최악%": "",
                         "주머니_MDD%": "", "주머니_연변동성%": "", "괴리_%p": "",
                         "참고_주머니_CAGR%": "", "참고_방석_CAGR%": ""})
        print(f"    [{mode}] {y}: {win[0].date()}~{win[-1].date()} {years:5.2f}년 {len(win):>5,}일 {note:4s}| "
              f"위기일 {ncr:>3} | " + " / ".join(line))

    S = pd.DataFrame(rows)
    S.to_csv("summary_r3.csv", index=False, encoding="utf-8-sig")
    n_blank = int((S["딱지"] == "데이터없음").sum())
    if COMM is not None:
        print(f"  [V7] (b) 보충: 원자재 공란 처리 창 {n_blank}건(시작일 {c_start.date()} 이전 시작 창)")

    # ── 전창 합산 표(사양 R3-7) ──
    print("\n" + "=" * 100)
    print("  [합산] 재질별 — 위기일 전 기간 합산(중복 없는 창 단위 병합) / R1 창 MDD·괴리")
    print(f"    {_c('재질',8)} | {_c('위기일 평균',12)} | {_c('위기일 최악',12)} | {_c('R1 MDD 중앙',12)} | {_c('R1 MDD 최악',12)} | {_c('R1 괴리 중앙',12)}")
    for name in ["단기채", "금100", "혼합"] + (["원자재"] if COMM is not None else []):
        a = agg.get(name, {})
        cr = np.concatenate(a["crisis"]) if a.get("crisis") else np.array([])
        cm = f"{cr.mean()*100:+.2f}%" if len(cr) else "—"
        cw = f"{cr.min()*100:+.2f}%" if len(cr) else "—"
        md = f"{np.median(a['mdd_r1']):.1f}%" if a.get("mdd_r1") else "—"
        mw = f"{min(a['mdd_r1']):.1f}%" if a.get("mdd_r1") else "—"
        gp = f"{np.median(a['gap_r1']):+.2f}p" if a.get("gap_r1") else "—"
        print(f"    {_c(name,8)} | {_c(cm,12)} | {_c(cw,12)} | {_c(md,12)} | {_c(mw,12)} | {_c(gp,12)}")
    print("  · 사전 예측(사양 R3-5, 박제 대조용 — 판정은 감사역): 보존력 단기채>혼합>금>원자재 / "
          "MDD 단기채≤혼합<금 / 괴리 단기채≈0·금100 상방.")
    print("  · 위기일 표는 창 중복 병합 표본(R1 이동창 겹침 포함) — 창별 수치는 CSV가 정본.")

    print("\n  [V5] 산출물 md5 — 칠판 업로드 후 감사역이 raw+캐시버스팅으로 수신·대조:")
    print(f"      summary_r3.csv : {_md5_file('summary_r3.csv')}  ({len(S)}행)")
    print(f"      script         : {self_md5}")
    print("=" * 100)

def _c(s, w):
    s = str(s); pad = w - sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)
    return s + " " * max(pad, 0)

if __name__ == "__main__":
    main()
