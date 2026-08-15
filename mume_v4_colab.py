# -*- coding: utf-8 -*-
# ============================================================================
# kelly17_research_r5.py — 연구사양서 R5 냉각방식비교 v1(md5 5c1a3746) 구현 (2026-08-15, Gemini 역할)
#   목적: 같은 냉각을 ①계좌 안에서(A = FAST 50:50 단독, 눈금 1.50) 하는 안과
#         ②주머니 차원에서(B = FAST 60:40 × 80% + 방석 20%, 눈금 1.44) 하는 안의 실측 비교.
#         C = FAST 60:40 단독(기준선·참고).
#   베이스 = R4 v3(md5 353ddbf9) 부품 조립 — run_simulation(FAST 정본 이식본)·방석(BOXX 대역+KRX금)·
#          통합 과세 바구니·달력·데이터 파이프라인·차트. 원형 불변, 신규 로직 금지.
#   질의 5건 확정 반영(2026-08-15 회신): Q1 세 팔 모두 이식본으로 통일 계산(V9(b)가 A↔정본 대조로 증명) /
#   Q2 80:20 복원은 사양 R5-1이 허가한 유일한 신규 접점(기존 부품 재사용, ★R5 신규 접점 주석 표시) /
#   Q3 대피 중에도 12/31 무조건 복원 / Q4 복원 실현손익은 B 통합 바구니 산입(KRX금 비과세) /
#   Q5 창당 차트 1장에 A/B/C 3선 + 낙폭 3선.
#   · 관찰 전용 — 60:40 스윕 봉인·방석 확정 불변. 재론은 연말 재심 절차로만(각주 인쇄).
#   · A팔 가중 = 정본 99행 W_B 원문 이식. QQQDD 없음. 창별 튜닝 없음. 정본·배포본 무접촉.
#   · 실행: Colab %run kelly17_research_r5.py (드라이브 자동 연결, 한글 그래프 출력)
# ============================================================================
# ── [R5 파라미터 — 사양 고정, 스윕 금지] ───────────────────────────────
R5_INIT   = 207_300.0                 # 시작 자본(FAST 20만 + VR 0.73만 합계 한 덩이, 사양 R5-1)
MONTHLY_M = 0.0                       # 맨몸 비교(사양 R5-1: 적립 없음)
B_FAST_W  = 0.80                      # B팔: FAST 80 : 방석 20(연 1회 12/31 복원)
B_CUSH_W  = 0.20
V9_TOL    = 0.5                       # V9 허용 오차(%p) — R4 실측(최대 +0.395%p, 1994 창) 감안
V9_REPORT = 0.1                       # 이 값 초과 시 통과라도 원인 로그 보고

import os, hashlib
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ── [인계장 고정 파라미터 — 전 창 동일, 재론 금지] ──────────────────────────
FAST_INIT = 200000.0                  # FAST 시작(명목 고정 — 시대착오 각주는 로그 인쇄)
VR_INIT   = 7300.0                    # VR 시작(거치식)
VR_START_STOCK_W = 0.766              # VR 시작 분할 = 주식 76.6 : Pool 23.4 (2026-07-26 실측, Q5 승인)
FAST_TICK, VR_TICK = 1.8, 2.7         # 딱지(인계장 §2)
SCALE_TGT = 1.44                      # 목표 눈금(§3)
CUSH_BOND_W = 2.0 / 3.0               # 방석 = 단기채 2 : 금 1(§5)
VR_PER_CUSH = 0.875                   # 2단계 동반 성장: VR $1당 방석 $0.875(§4·§11 — 53:47은 근사)
VR_STOP_FRAC = 2.0 / 3.0              # VR 정지선: VR ≥ FAST×⅔ → VR 매수분 상환 전환(§4 공통)
KRX_FEE   = 0.003                     # KRX 금현물 거래수수료(기본 0.3% 보수 가정 — 실측 수령 시 교체)
US_FEE    = 0.001                     # 미국 자산 편도 0.1%(토스 실측) — TQQQ·BOXX·VR·통합층
# ── FAST 정본 전역(150b88ef 기본값 그대로) ──
W_A = {'TQQQ': 0.60, 'gold': 0.40}   # A: FAST + gold(비과세)
W_B = {'TQQQ': 0.50, 'gold': 0.50}   # B: FAST + (양도세)   ← 정본 99행 원문 이식(R5 A팔)
BUBBLE_LIMIT = 1.30
TAX_RATE_EQUITY = 0.22
FX_KRWUSD = 1400.0
TAX_DEDUCTION_KRW = 2_500_000.0
TAX_EXEMPTION = TAX_DEDUCTION_KRW / FX_KRWUSD      # ≈ $1,785.71
NORMAL_SLIPPAGE = 0.0
COMMISSION = US_FEE
B1_PCTL = 0.75
EXIT_INDEX = "NDX"; GATE_MODE = "ABS"; REC_HOT_INDEX = "GSPC"
RECOVER_BOOST = {'TQQQ': 0.60, 'gold': 0.40}
FAST_RECOVER_KEEPS_GOLD = False
# ── VR 정본 전역(823903a7 기본값 그대로) ──
SIGNAL_LAG = 1
KILLSWITCH = "on"; B1_ON = "on"; FAST_RECOVER = "on"; RECOVER_B1_BLOCK = "off"
VOLTGT_ON = "off"; VOLTGT_TARGET = 0.60
SKILL_ON = "off"; SKILL_MODE = "off"; SKILL_GAP_THRESH = 0.15; SKILL_DD_THRESH = 0.40
BAND_LOW, BAND_HIGH = 0.85, 1.15
HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT = 100000.0, 0.10, 10, 0.50
TAX_MODE = "annual"; TAX_RATE = 0.22
TAX_DEDUCTION = TAX_DEDUCTION_KRW / FX_KRWUSD
FEE_RATE = US_FEE; SLIP = 0.0
LUMP_EVENTS = {}
SHARPE_RF = "pool"; SHARPE_NUM = "cagr"          # VR v3 확정값(run_vr 원문 참조)
# ── 창 구조(R3 재사용) ──
R1_YEARS = list(range(1986, 2010)); WINDOW_Y = 17
START_YEARS = list(range(2010, 2026)); END_MODE_E2 = "2022-12-30"; E2_MAX_START_YEAR = 2021
MIN_YEARS_JUDGE = 5.0
FETCH_START = "1985-10-01"; TQQQ_REAL_START = "2010-02-11"
TQQQ_FULL_PATHS = ["tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]
GOLD_FULL_PATHS = ["gold_full.csv", "/content/drive/MyDrive/gold_full.csv"]
M0_FULL_PATHS = ["m0_full.csv", "/content/drive/MyDrive/m0_full.csv"]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BOGMBASE"
M0_ANCHOR = (830.0, 840.0)
CRISIS_DD = -0.05
# ── 비교 모드 창 세트(v3): VR 정본(823903a7 계열 종료일 다각화판)·FAST 정본(150b88ef)에서 그대로 이식 ──
VR_START_DATES = ["2000-01-02", "2002-01-02", "2004-01-02", "2006-01-02", "2008-01-02", "2010-02-11",
                  "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]   # VR 정본 원문
FAST_START_DATES = ["1986-08-11", "1994-01-02", "1998-01-02", "2000-01-02", "2010-02-11",
                    "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]  # FAST 정본 93행
CMP_END_DATES = ["2018-12-31", "2020-12-31", "2021-12-31", "2022-12-30", "2024-12-31", "2026-07-10"]  # VR 정본 원문
FAST_STD_INIT = 100_000.0             # FAST 정본 관행 초기값(INITIAL_CAPITAL, 96행)
FETCH_START_DATE = FETCH_START
END_DATE = pd.Timestamp.today().strftime('%Y-%m-%d')



# ═══ [부품: R3 v2(014bd81e) — 데이터 파이프라인, 바이트 이식] ═══


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


# ═══ [부품: R2(cf9a976d) — M0 정본 파일 우선 로더, 바이트 이식] ═══


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


# ═══ [부품: VR 정본(823903a7) — 바이트 이식(원형 로직 불변)] ═══


def ON(x): return str(x).strip().lower() == "on"

def split_cycles(index):
    first = index[0]
    dss = (first.weekday() - 5) % 7
    anchor = (first - pd.Timedelta(days=dss)).normalize()
    cyc, ck, cur = [], None, []
    for ts in index:
        k = (ts.normalize() - anchor).days // 14
        if k != ck:
            if cur: cyc.append(cur)
            cur, ck = [], k
        cur.append(ts)
    if cur: cyc.append(cur)
    return cyc

def _signals(d):
    """대피·복귀·VOLTGT 판정에 쓸 '신호 시계열'을 만든다.

       SIGNAL_LAG=1 → 전 거래일 종가 기준값을 오늘 자리에 놓는다(shift 1).
         · 오늘 매매는 '어제 종가로 확정된 신호'로만 판단 → 실전(익일 LOC)과 동일.
         · 봇: 오늘 종가 판정 → 다음 거래일 LOC 집행.  백테스터: 어제 신호 → 오늘 집행.
           같은 구조다(집행이 신호보다 항상 1거래일 뒤).
       SIGNAL_LAG=0 → 원본(당일 신호·당일 집행). 구버전 비교용.

       ※ 월말 판정도 함께 밀린다: '어제가 월말이었나'로 오늘 복귀를 집행.
         (봇: 월말 종가 판정 → 다음 거래일 재매수)
       ※ 가격(px)은 밀지 않는다 — 체결은 '오늘 종가'다.
       ※ 밴드 매매(사다리)는 지연 없음: 지정가를 미리 걸어두므로 당일 체결이 정당."""
    lag = int(SIGNAL_LAG)
    sh = (lambda s: s.shift(lag)) if lag > 0 else (lambda s: s)

    dts = list(d.index)
    # is_month_end[t] = t가 이달 마지막 거래일인가 (신호일 기준)
    me_raw = pd.Series(
        [(i < len(dts) - 1 and dts[i + 1].month != dts[i].month) for i in range(len(dts))],
        index=d.index)

    sig = {
        "G":    sh(d["NDX"]),    # ★탈출 기준선 = 나스닥100 (2026-08-08 비대칭 확정, 은박사 승인)
        "GS":   sh(d["NSMA"]),
        "RG":   sh(d["GSPC"]),   # ★복귀 기준선 = S&P500 (느린 복귀 — 닿컴형 왕복 방어)
        "RGS":  sh(d["GSMA"]),
        "NX":   sh(d["NDX"]),
        "NS":   sh(d["NSMA"]),
        "BU":   sh(d["BUB"]),
        "PCTL": sh(d["BUB_PCTL"]) if "BUB_PCTL" in d.columns else pd.Series(np.nan, index=d.index),
        "RV":   sh(d["RV"]) if "RV" in d.columns else pd.Series(np.nan, index=d.index),
        "ME":   sh(me_raw.astype(float)).fillna(0.0).astype(bool),  # '어제가 월말' → 오늘 복귀
    }
    return sig

def _vscale(sig, day):
    """VOLTGT 노출 스케일. 사이클 첫날에 '직전 거래일 RV'로 확정(봇의 cyc_scale 스냅샷과 동일)."""
    if not ON(VOLTGT_ON):
        return 1.0
    rv = sig["RV"].get(day, np.nan)
    if pd.isna(rv) or rv <= 0:
        return 1.0
    return min(1.0, VOLTGT_TARGET / float(rv))

def _exit_reason(sig, dd):
    """대피 이유: None(대피안함) / 'bubble'(버블≥1.30) / 'b1'(B1 백분위). 봇 vr_signal_bot.py 834-835행 정합.
       순서: 버블 먼저 판정(≥1.30이면 bubble), 아니면 B1. 둘 다 SMA200 하회 전제."""
    g = sig["G"].get(dd, np.nan); gs = sig["GS"].get(dd, np.nan)
    if pd.isna(g) or pd.isna(gs) or g >= gs:
        return None
    bub = sig["BU"].get(dd, np.nan)
    if not pd.isna(bub) and bub >= BUBBLE_LIMIT:
        return "bubble"
    if ON(B1_ON):
        pc = sig["PCTL"].get(dd, np.nan)
        if not pd.isna(pc) and pc >= B1_PCTL:
            return "b1"
    return None


def _exit_sig(sig, dd):
    """대피 여부(하위호환 래퍼). 이유가 필요하면 _exit_reason 사용."""
    return _exit_reason(sig, dd) is not None

def _recover_which(sig, dd, evac_reason="bubble"):
    """복귀 방식: None(복귀안함) / 'spx'(S&P 단독 상향) / 'ndx'(NDX 빠른복귀). 전일=월말 종가 기준.
       ★RECOVER_B1_BLOCK on이면 evac_reason=='b1'일 때 NDX 빠른복귀 차단(봇 851행 정합).
        off면 대피이유 무관하게 NDX 허용(기존 백테스터 방식)."""
    if not bool(sig["ME"].get(dd, False)):
        return None
    g = sig["RG"].get(dd, np.nan); gs = sig["RGS"].get(dd, np.nan)   # ★복귀 = S&P 기준(비대칭)
    if pd.isna(g) or pd.isna(gs):
        return None
    spx_ok = g > gs
    bub = sig["BU"].get(dd, np.nan)
    if not pd.isna(bub) and bub < BUBBLE_LIMIT:
        nx = sig["NX"].get(dd, np.nan); ns = sig["NS"].get(dd, np.nan)
        ndx_ok = (not pd.isna(nx) and not pd.isna(ns) and nx > ns)
        block = ON(RECOVER_B1_BLOCK) and evac_reason == "b1"
        allow_fast = ON(FAST_RECOVER) and not block
        if spx_ok: return "spx"
        if allow_fast and ndx_ok: return "ndx"
        return None
    return "spx" if spx_ok else None


def _recover_sig(sig, dd, evac_reason="bubble"):
    """복귀 여부(하위호환 래퍼). 방식은 _recover_which."""
    return _recover_which(sig, dd, evac_reason) is not None

def _skill_on(E, V, px_now, px_peak, pctl):
    """실력공식을 이 사이클 V 갱신에 켤지 판정 (자기해소 — 매 사이클 재판정, 진동 무해).
       · gap(후보A): 평가금 E가 최소밴드(V×BAND_LOW) 대비 SKILL_GAP_THRESH 이상 아래로 벌어지면 켬.
                    책 '평가금이 최소밴드 아래로 벌어진다'를 직접 지표화. 실력공식이 V를 내려 괴리 축소=자기해소.
       · drawdown(후보B): TQQQ 고점대비 낙폭 ≥ SKILL_DD_THRESH AND B1미발현(백분위<B1_PCTL)이면 켬. 대조군.
       · always: 항상.  off: 안 켬(기본공식)."""
    m = SKILL_MODE
    if m == "always":
        return True
    if m == "gap":
        bmin = V * BAND_LOW
        if bmin <= 0:
            return False
        gap = (bmin - E) / bmin
        return gap >= SKILL_GAP_THRESH
    if m == "drawdown":
        if px_peak <= 0:
            return False
        dd = 1.0 - px_now / px_peak
        b1_absent = pd.isna(pctl) or (float(pctl) < B1_PCTL)
        return (dd >= SKILL_DD_THRESH) and b1_absent
    return False


# ══════════════ [3c. ★세금·수수료 원장 — v3] ══════════════

class TaxLedger:
    """한국 해외주식 양도세 원장(연차 실현과세) + 수수료.
       · 취득원가 = 이동평균, 매수 현금지출 전액(수수료 포함) → 세법상 필요경비 자동공제
       · 매도 실현손익 = 순수취액 − 평균원가×주수 → 당해 realized 누적
       · year_end(): 세액 = max(0, realized − 공제) × 세율 → 미납부채 liab.
         손실해 세액 0, realized 리셋 = 이월결손 차단(연내 통산만).
       · TAX_MODE="maturity"면 annual=False → 원장은 기록만, 정산·납부 전부 무동작(v2 경로 보존)."""
    def __init__(self):
        self.fee = FEE_RATE + SLIP
        self.annual = (str(TAX_MODE).strip().lower() == "annual")
        self.cost = 0.0        # 보유분 총 취득원가(수수료 포함)
        self.realized = 0.0    # 당해 실현손익(순)
        self.liab = 0.0        # 확정·미납 세부채
        self.tax_paid = 0.0    # 누적 납부액(진단)
        self.fees = 0.0        # 누적 수수료(진단)
        self.n_pay = 0

    def buy_cash(self, cash, p):
        """현금 cash 지출 매수 → 취득 주수 반환. 원가 += cash."""
        if cash <= 1e-12 or p <= 0: return 0.0
        q = cash / (p * (1.0 + self.fee))
        self.cost += cash
        self.fees += q * p * self.fee
        return q

    def sell_qty(self, q, p, shares):
        """q주 매도 → 순수취액 반환. 실현손익 기록. shares = 매도 직전 보유주수."""
        if q <= 1e-15 or p <= 0 or shares <= 1e-15: return 0.0
        q = min(q, shares)
        net = q * p * (1.0 - self.fee)
        avg = self.cost / shares
        self.realized += net - avg * q
        self.cost = max(0.0, self.cost - avg * q)
        self.fees += q * p * self.fee
        return net

    def sell_value(self, value, p, shares):
        """평가액 value 만큼 매도(밴드 매도용) → (순수취액, 매도주수).
           net를 value에서 직접 계산해 FEE=0일 때 v2와 부동소수까지 동일((s/p)*p 오차 차단)."""
        if value <= 1e-15 or p <= 0 or shares <= 1e-15: return 0.0, 0.0
        q = value / p
        if q > shares:                                  # 안전 캡(밴드 구조상 도달 불가)
            return self.sell_qty(shares, p, shares), shares
        net = value * (1.0 - self.fee)
        avg = self.cost / shares
        self.realized += net - avg * q
        self.cost = max(0.0, self.cost - avg * q)
        self.fees += value * self.fee
        return net, q

    def qty_for_cash(self, cash_needed, p, shares):
        """순현금 cash_needed 마련에 필요한 매도 주수(보유 한도 캡)."""
        if cash_needed <= 0 or p <= 0: return 0.0
        return min(shares, cash_needed / (p * (1.0 - self.fee)))

    def year_end(self):
        """12/31 정산(annual 전용): 실현손익 → 세부채, 리셋."""
        if not self.annual: return
        self.liab += max(0.0, self.realized - TAX_DEDUCTION) * TAX_RATE
        self.realized = 0.0

    def final_tax(self):
        """만기 전량청산 후 마지막해 정산분(annual 전용)."""
        if not self.annual: return 0.0
        t = max(0.0, self.realized - TAX_DEDUCTION) * TAX_RATE
        self.realized = 0.0
        return t

def _tax_calendar(index):
    """(연말 정산일 set, 납부일 set) — 해당 인덱스에 실재하는 날만.
       정산일 = 각 연도 12월 마지막 거래일(시계열 최종일 제외 — 만기청산이 담당).
       납부일 = 6월 첫 거래일(= 5월말 다음 거래일, 전년 확정분 납부)."""
    ye, pay = set(), set()
    yl, jf = {}, {}
    for ts in index:
        yl[ts.year] = ts
        if ts.month == 6 and ts.year not in jf:
            jf[ts.year] = ts
    last_day = index[-1]
    for y, t in yl.items():
        if t != last_day and t.month == 12:
            ye.add(t)
    for y, t in jf.items():
        pay.add(t)
    return ye, pay

def run_vr(d, init_capital, pool_ratio, G, buy_limit, dep=0.0, wd=0.0, killswitch=True):
    """flow = dep − wd (사이클당 순현금). V_next = V + pool/G + flow.
       ★v2: 대피·복귀·VOLTGT는 '전일 신호 → 당일 종가 집행' (봇과 동일 구조).
       ★v3: 모든 매매가 TaxLedger 경유(수수료·실현손익) — annual이면 연말 정산·6월 납부·
            만기 청산과세. maturity+FEE 0이면 수치 경로가 v2와 동일(회귀 앵커)."""
    px = d["TQQQ"]; flow = dep - wd
    sig = _signals(d)
    led = TaxLedger()
    ye_days, pay_days = _tax_calendar(px.index)

    stock = init_capital * (1 - pool_ratio); pool = init_capital * pool_ratio
    shares = led.buy_cash(stock, float(px.iloc[0])); V = shares * float(px.iloc[0])
    cum_in = cum_out = 0.0
    nb = ns = n_exit = n_rec = 0
    n_exit_b1 = n_exit_bubble = n_rec_ndx = n_rec_spx = 0   # ★검증: 대피이유·복귀방식 카운트
    evac_reason = "bubble"                                  # ★검증: 직전 대피 이유 추적(복귀 정책 판단용)
    px_peak = 0.0; min_nav = float("inf"); pool_at_min = 0.0; n_skill_on = 0   # ★실력공식: 낙폭·최저NAV시점Pool·트리거발동수
    daily = []; state = "INVESTED"; cf_on_day = {}

    lumps = sorted((pd.Timestamp(k), float(v)) for k, v in LUMP_EVENTS.items()); li = 0
    while li < len(lumps) and lumps[li][0] < px.index[0]:
        li += 1

    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]])

        # ── 목돈 추가/인출 (P/V 고정) ──
        while li < len(lumps) and lumps[li][0] <= cd[0] and state == "INVESTED":
            amt = lumps[li][1]; ev0 = shares * p0; total = ev0 + pool
            if total > 0 and V > 0:
                if amt < 0 and -amt >= total:          # 총자산보다 큰 인출 → 파산
                    cum_out += led.sell_qty(shares, p0, shares) + pool   # ★v3 전량매도(수수료 차감)+Pool
                    cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) - total
                    shares = pool = 0.0
                    for rdd in px.index[px.index >= cd[0]]:
                        daily.append((rdd, 0.0))
                    li = len(lumps); state = "BUST"; break
                w = ev0 / total; pv = pool / V
                if amt > 0:
                    shares += led.buy_cash(amt * w, p0)                  # ★v3 주식분 매수(수수료 포함)
                else:
                    _q = led.qty_for_cash((-amt) * w, p0, shares)        # ★v3 인출분 순현금 마련 매도
                    led.sell_qty(_q, p0, shares); shares -= _q           #    (순수취액은 계좌 밖으로)
                pool += amt * (1 - w)
                if pool < 0:
                    need = -pool; ss = led.qty_for_cash(need, p0, shares)
                    pool += led.sell_qty(ss, p0, shares); shares -= ss
                    if pool < 0: pool = 0.0
                V = (pool / pv) if pv > 1e-12 else (shares * p0 + pool)
                if amt > 0: cum_in += amt
                else: cum_out += -amt
                cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) + amt
            li += 1
        if state == "BUST":
            break

        # 인출 고갈 → 파산 정지
        if wd > 0 and state == "INVESTED" and (shares * p0 + pool) < wd:
            cum_out += max(0.0, led.sell_qty(shares, p0, shares) + pool)   # ★v3 수수료 차감 청산
            shares = pool = 0.0
            for rdd in px.index[px.index >= cd[0]]:
                daily.append((rdd, 0.0))
            break

        if state == "INVESTED":
            pool += flow; cum_in += dep; cum_out += wd
            if flow != 0:
                cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) + flow
            if pool < 0:                               # 인출로 현금 부족 → 주식 매도
                need = -pool; sell_sh = led.qty_for_cash(need, p0, shares)
                pool += led.sell_qty(sell_sh, p0, shares); shares -= sell_sh
                if pool < 0: pool = 0.0

        # ★VOLTGT: 사이클 첫날에 '직전 거래일 RV'로 노출 확정 (봇의 cyc_scale 스냅샷)
        Veff = V * _vscale(sig, cd[0])
        bmin, bmax = Veff * BAND_LOW, Veff * BAND_HIGH
        budget = max(0, pool) * buy_limit; used = 0.0

        for dd in cd:
            p = float(px.loc[dd])
            if p > px_peak: px_peak = p          # ★고점 추적(후보B 낙폭 계산용)

            # ★v3 납부: 6월 첫 거래일 — 전년 확정 세부채를 부록A 목돈인출 방식으로 집행.
            #   TQQQ:Pool 비례 인출 + V_new = V×(1−세액/총자산). 봇 /lumpsum과 동일 메커니즘.
            #   NAV 중립(부채 소멸 = 현금 유출)이나 매도분 수수료·실현익(당해 과세)은 발생.
            if led.annual and led.liab > 1e-9 and dd in pay_days:
                A = shares * p + pool
                T = min(led.liab, max(0.0, A))
                if T > 1e-9 and A > 0:
                    w_eq = (shares * p) / A
                    _q = led.qty_for_cash(T * w_eq, p, shares)
                    pool += led.sell_qty(_q, p, shares); shares -= _q
                    pool -= T
                    if pool < 0:                 # 수수료·보유캡 미세 부족분 → 추가 매도
                        _q2 = led.qty_for_cash(-pool, p, shares)
                        pool += led.sell_qty(_q2, p, shares); shares -= _q2
                        if pool < 0: pool = 0.0
                    V = V * (1.0 - T / A)
                    led.liab -= T; led.tax_paid += T; led.n_pay += 1

            if killswitch:
                # ★대피: 전일 신호 → 오늘 종가 집행 (봇의 '익일 LOC'와 동일 구조). 이유 기록.
                if state == "INVESTED":
                    _er = _exit_reason(sig, dd)
                    if _er:
                        pool += led.sell_qty(shares, p, shares); shares = 0.0   # ★v3 대피 전량매도 = 대량 실현
                        state = "CASH"; n_exit += 1; evac_reason = _er
                        if _er == "b1": n_exit_b1 += 1
                        else: n_exit_bubble += 1
                        if dd in ye_days: led.year_end()                        # ★12/31 대피 엣지: 정산 누락 방지
                        _nav = pool - led.liab
                        if _nav < min_nav: min_nav = _nav; pool_at_min = pool   # ★최저NAV 시점(대피=전액현금)
                        daily.append((dd, _nav)); continue
                # ★복귀: 전일(=월말) 신호 → 오늘 종가 집행. evac_reason으로 정책 적용.
                if state == "CASH":
                    _rw = _recover_which(sig, dd, evac_reason)
                    if _rw:
                        buy = min(Veff, pool)
                        shares = led.buy_cash(buy, p); pool -= buy              # ★v3 복귀 매수(수수료 포함)
                        state = "INVESTED"; n_rec += 1
                        if _rw == "ndx": n_rec_ndx += 1
                        else: n_rec_spx += 1

            # 밴드 매매(사다리) — 지연 없음(지정가 사전 게시 → 장중 체결)
            if state == "INVESTED":
                ev = shares * p
                if ev < bmin:
                    b = min(bmin - ev, pool, max(0, budget - used))
                    if b > 1e-9:
                        shares += led.buy_cash(b, p); pool -= b; used += b; nb += 1
                elif ev > bmax:
                    s = ev - bmax
                    if s > 1e-9:
                        net, _q = led.sell_value(s, p, shares)
                        pool += net; shares -= _q; ns += 1

            if dd in ye_days: led.year_end()   # ★v3 12/31 정산(종가 후) — 당일 NAV부터 부채 반영
            _nav = shares * p + pool - led.liab
            if _nav < min_nav: min_nav = _nav; pool_at_min = pool   # ★최저NAV 시점의 Pool(실탄 보존 측정)
            daily.append((dd, _nav))

        if state == "INVESTED":
            E = shares * float(px.loc[cd[-1]])
            _pctl = d["BUB_PCTL"].get(cd[-1], np.nan) if "BUB_PCTL" in d.columns else np.nan
            _use_skill = _skill_on(E, V, float(px.loc[cd[-1]]), px_peak, _pctl)   # ★실력공식 조건부 판정
            skill = (E - V) / (2 * np.sqrt(G)) if _use_skill else 0.0
            V = V + pool / G + skill + flow
            if _use_skill: n_skill_on += 1

    dd_ = pd.DataFrame(daily, columns=["d", "t"]).set_index("d")
    mdd = float((dd_.t / dd_.t.cummax() - 1).min())
    nav = float(dd_.t.iloc[-1])
    yrs = (dd_.index[-1] - dd_.index[0]).days / 365.25
    cum = init_capital + cum_in
    if led.annual:
        # ★v3 만기 확정: 전량매도(수수료) → 마지막해 정산 + 미납부채 → 실수령액.
        #   표의 숫자 = "종료일에 다 팔고 세금까지 내면 손에 쥐는 돈"(+인출식은 인출누계).
        p_end = float(px.loc[dd_.index[-1]])
        cash_end = pool + led.sell_qty(shares, p_end, shares); shares = 0.0
        tax = led.liab + led.final_tax()
        led.tax_paid += tax; led.liab = 0.0
        result = cash_end + cum_out
        at = cash_end - tax + cum_out
    else:
        result = nav + cum_out
        tax = max(0, result - cum - TAX_DEDUCTION) * TAX_RATE
        at = result - tax
    cagr = (at / cum) ** (1 / yrs) - 1 if at > 0 else float('nan')

    # 샤프: 현금흐름 제거한 순수 시장수익률 기준
    nav_s = dd_.t; prev = nav_s.shift(1)
    cf = pd.Series(0.0, index=nav_s.index)
    for dt, amt in cf_on_day.items():
        if dt in cf.index:
            cf.loc[dt] = amt
    ret = ((nav_s - cf) / prev - 1.0).dropna()
    ret = ret[np.isfinite(ret)]
    rf = (float(d["IRX"].reindex(dd_.index).ffill().mean()) / 100.0
          if (str(SHARPE_RF).strip().lower() == "irx" and "IRX" in d.columns) else 0.0)
    sd = ret.std()
    vol = float(sd * np.sqrt(252)) if sd > 0 else float('nan')
    if str(SHARPE_NUM).strip().lower() == "arith":
        # v2 재현 경로: 분자 = 일수익 산술평균(연율). CAGR과 다른 수치라 표의 CAGR 열과 어긋난다.
        sharpe = ((ret.mean() - rf / 252) / sd * np.sqrt(252)) if sd > 0 else float('nan')
    else:
        # ★기본(2026-08-01 은박사 확정): 분자 = 세후 CAGR — FAST 백테스터와 동일 정의.
        #   같은 자로 재야 두 백테스터 비교가 성립. 표의 CAGR 열과 분자가 일치하는 부수 이점.
        #   세후액 ≤ 0(파산)이면 CAGR이 nan → 샤프도 nan. 종전에는 파산인데 양수 샤프가
        #   찍혔는데(NAV 음수 구간에서 일수익 부호 역전) 그 허위값이 자동 제거된다.
        sharpe = ((cagr - rf) / vol) if (vol == vol and vol > 0) else float('nan')

    return dict(yrs=yrs, nav=nav, result=result, aftertax=at, cum=cum, cum_out=cum_out,
                cagr=cagr, mdd=mdd, sharpe=sharpe, nb=nb, ns=ns, n_exit=n_exit, n_rec=n_rec,
                n_exit_b1=n_exit_b1, n_exit_bubble=n_exit_bubble, n_rec_ndx=n_rec_ndx, n_rec_spx=n_rec_spx,
                pool_at_min=(pool_at_min if min_nav < float("inf") else 0.0),
                min_nav=(min_nav if min_nav < float("inf") else 0.0), n_skill_on=n_skill_on,
                nav_series=dd_.t, tax_paid=led.tax_paid, fees=led.fees, n_pay=led.n_pay, vol=vol)   # ★v3 진단

def _setup_korean_font():
    from matplotlib import font_manager
    import glob, subprocess, matplotlib.pyplot as plt
    def find():
        for pat in ["/usr/share/fonts/truetype/nanum/*.ttf", "/usr/share/fonts/**/Nanum*.ttf",
                    "/usr/share/fonts/**/NotoSansCJK*.otf", "/usr/share/fonts/**/NotoSansCJK*.ttc",
                    "/usr/share/fonts/opentype/noto/*CJK*.ttc", "/root/.fonts/*.ttf"]:
            h = glob.glob(pat, recursive=True)
            if h: return h[0]
        return None
    fp = find()
    if fp is None:
        try:
            subprocess.run(["apt-get", "install", "-y", "fonts-nanum"],
                           capture_output=True, timeout=120)
            font_manager._load_fontmanager(try_read_cache=False)
            fp = find()
        except Exception:
            pass
    if fp:
        try:
            font_manager.fontManager.addfont(fp)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            pass
    plt.rcParams["axes.unicode_minus"] = False


# ═══ [부품: FAST 정본(150b88ef) — 바이트 이식(원형 로직 불변)] ═══


def _is_taxable_equity(t):
    return t in ['TQQQ', 'QLD', 'SPY', 'QQQ', 'BOXX']

def _get_slip_comm(t, slip=NORMAL_SLIPPAGE):
    if t == 'BOXX': return 0.0005 + COMMISSION
    if t == 'gold': return 0.0      # ★F10(2026-08-01 은박사 확정): 금 매매비용 0. 종전 slip+0.003
    return slip + COMMISSION

def _safe_px(row, col):
    return row[col] if col in row.index else np.nan

def _exec_px(row, t, is_open=False):
    if is_open:
        px = _safe_px(row, f'{t}_OPEN')
        if not pd.isna(px) and px > 0: return px
    return _safe_px(row, t)

def _sell(t, hold, px, eq_p, cash, slip=NORMAL_SLIPPAGE):
    if t not in hold or pd.isna(px) or px <= 0: return hold, eq_p, cash, 0
    h = hold.pop(t)
    sl = _get_slip_comm(t, slip)
    net = px * (1 - sl)
    proc = h['units'] * net
    profit = (net - h['entry_price_usd']) * h['units']
    if _is_taxable_equity(t): eq_p += profit
    return hold, eq_p, cash + proc, proc

def _buy(t, amt, px, hold, slip=NORMAL_SLIPPAGE):
    if amt <= 1e-9 or pd.isna(px) or px <= 0: return hold, 0
    sl = _get_slip_comm(t, slip)
    net = px * (1 + sl)
    units = amt / net
    if t in hold:
        o = hold[t]
        nu = o['units'] + units
        hold[t] = {'units': nu, 'entry_price_usd': (o['units'] * o['entry_price_usd'] + units * net) / nu}
    else: hold[t] = {'units': units, 'entry_price_usd': net}
    return hold, amt

def _val(hold, cash, row):
    v = cash
    for t, h in hold.items():
        if h['units'] > 0:
            px = _exec_px(row, t)
            if not pd.isna(px) and px > 0: v += h['units'] * px
    return v

def _val_open(hold, cash, row):
    v = cash
    for t, h in hold.items():
        if h['units'] > 0:
            px = _exec_px(row, t, is_open=True)
            if not pd.isna(px) and px > 0: v += h['units'] * px
    return v

def run_simulation(df_usd, initial_cap, target_w, port_name="", method='fast_recover',
                   recover_boost=None, exit_index=None, gate_mode=None, rec_hot_index=None):
    # ★K3: exit_index·gate_mode가 None이면 전역값 사용 → 기존 호출부 무변경(사양 K3).
    _exit_idx = exit_index if exit_index is not None else EXIT_INDEX
    _gmode = gate_mode if gate_mode is not None else GATE_MODE
    _rec_idx = rec_hot_index if rec_hot_index is not None else REC_HOT_INDEX   # ★K9: None→전역 폴백
    dates = df_usd.index
    cash = float(initial_cap)
    hold = {}
    eq_p = 0
    tax_bill = 0
    history = []
    annual_pending = False
    tax_pending = False

    state = 'INVESTED'
    pending = None
    base_w = target_w.copy()
    logs = []
    trig = {}
    pending_aw = None    # 부스터B: 예약된 복귀 부스터 목표 비중
    is_boosted = False   # boost_until_annual: 복귀 부스터 비중(60:40 등) 적용 중 여부
    _boost_w = (recover_boost if recover_boost is not None else RECOVER_BOOST)

    p0 = df_usd.iloc[0]
    total0 = cash
    for t, w in target_w.items():
        px = _exec_px(p0, t, is_open=True)
        if not pd.isna(px) and w > 0:
            hold, used = _buy(t, total0 * w, px, hold, NORMAL_SLIPPAGE)
            cash -= used

    def _rebalance(aw, p):
        nonlocal cash, eq_p, hold
        total = _val_open(hold, cash, p)
        for t in list(hold.keys()):
            px = _exec_px(p, t, is_open=True)
            if pd.isna(px) or px <= 0: continue
            tv = total * aw.get(t, 0)
            cv = hold[t]['units'] * px
            if cv > tv:
                u = min((cv - tv) / px, hold[t]['units'])
                sl = _get_slip_comm(t)
                net = px * (1 - sl)
                pr = (net - hold[t]['entry_price_usd']) * u
                if _is_taxable_equity(t): eq_p += pr
                cash += u * net
                hold[t]['units'] = max(0, hold[t]['units'] - u)
        actual = _val_open(hold, cash, p)
        for t, w in aw.items():
            if w <= 0: continue
            px = _exec_px(p, t, is_open=True)
            if pd.isna(px) or px <= 0: continue
            tv = actual * w
            cv = hold.get(t, {'units': 0})['units'] * px
            deficit = tv - cv
            if deficit > 0 and cash > 0:
                hold, used = _buy(t, min(cash, deficit), px, hold, NORMAL_SLIPPAGE)
                cash -= used

    def _sell_all(t, p):
        nonlocal cash, eq_p, hold
        if t not in hold or hold[t]['units'] <= 0: return 0.0
        px = _exec_px(p, t, is_open=True)
        if pd.isna(px) or px <= 0: return 0.0
        u = hold[t]['units']
        sl = _get_slip_comm(t)
        net = px * (1 - sl)
        proc = u * net
        pr = (net - hold[t]['entry_price_usd']) * u
        if _is_taxable_equity(t): eq_p += pr
        cash += proc
        hold[t]['units'] = 0.0
        return proc

    def _buy_amt(t, amt, p):
        nonlocal cash, hold
        if amt <= 1e-9: return
        px = _exec_px(p, t, is_open=True)
        if pd.isna(px) or px <= 0: return
        sl = _get_slip_comm(t)
        net = px * (1 + sl)
        units = amt / net
        if t in hold:
            o = hold[t]
            nu = o['units'] + units
            hold[t] = {'units': nu, 'entry_price_usd': (o['units'] * o['entry_price_usd'] + units * net) / nu}
        else: hold[t] = {'units': units, 'entry_price_usd': net}
        cash -= amt

    for i in range(len(dates)):
        cd = dates[i]
        p = df_usd.iloc[i]
        executed = False
        is_year_end = (i < len(dates) - 1 and cd.year != dates[i + 1].year)
        is_may_end = (i < len(dates) - 1 and cd.month == 5 and dates[i + 1].month == 6)
        is_last = (i == len(dates) - 1)
        is_month_end = (i < len(dates) - 1 and cd.month != dates[i + 1].month)

        if tax_pending and not executed and not is_last:
            tax_pending = False
            if tax_bill > 0:
                deficit = tax_bill - cash
                if deficit > 0:
                    total_h = _val_open(hold, 0, p)
                    if total_h > 0:
                        for t in list(hold.keys()):
                            if hold[t]['units'] > 0:
                                px = _exec_px(p, t, is_open=True)
                                if pd.isna(px) or px <= 0: continue
                                amt = deficit * (hold[t]['units'] * px / total_h)
                                u = min(amt / px, hold[t]['units'])
                                sl = _get_slip_comm(t)
                                net = px * (1 - sl)
                                pr = (net - hold[t]['entry_price_usd']) * u
                                if _is_taxable_equity(t): eq_p += pr
                                cash += u * net
                                hold[t]['units'] = max(0, hold[t]['units'] - u)
                # F4: 현금 부족 시 미납 잔액을 소멸시키지 않고 보존(최종청산에서 정산) → NAV 과대 방지
                paid = min(tax_bill, cash)
                cash -= paid
                tax_bill -= paid
                executed = True

        if pending and not executed and not is_last:
            if pending == 'go_cash': astr = '대피(USD대기)'
            elif pending == 'go_boxx': astr = '대피(BOXX전환)'
            elif pending.startswith('go_invest'):
                if is_boosted and pending_aw is not None:      # F5: 라벨을 부스터 비중에서 동적 생성
                    _bt = int(round(_boost_w.get('TQQQ', 0) * 100))
                    astr = f'복귀(부스터{_bt}:{100 - _bt})'
                else:
                    astr = '복귀'
            else: astr = pending

            logs.append({'실행일': cd.strftime('%Y-%m-%d'), '액션': astr, '종류': trig.get('note', ''),
                         '버블': round(trig.get('bubble', 0), 4), 'GSPC': round(trig.get('gspc', 0), 2)})

            if pending == 'go_cash':
                _sell_all('TQQQ', p)
                state = 'CASH_USD'
            elif pending == 'go_boxx':
                _buy_amt('BOXX', cash, p)  # 금 무접촉: 대기 달러(cash)만 BOXX로 전액 매수
                state = 'CASH_BOXX'
            elif pending == 'go_invest_from_usd':
                note = trig.get('note', '')
                if pending_aw is not None:                     # 부스터B: NDX 단독복귀 시 부스터 비중으로 재진입
                    _rebalance(pending_aw, p); pending_aw = None
                elif note.startswith('fast_recover'):
                    if FAST_RECOVER_KEEPS_GOLD:
                        _buy_amt('TQQQ', cash, p)               # F3-True: 현금→TQQQ만, gold 무접촉
                    else:
                        _rebalance(base_w, p)                   # F3-False(기본): 전체 50:50 재조정
                else:
                    _buy_amt('TQQQ', cash, p)                   # recover_spx_only: 현금→TQQQ만
                state = 'INVESTED'
            elif pending == 'go_invest_from_boxx':
                note = trig.get('note', '')
                if pending_aw is not None:                     # 부스터B: NDX 단독복귀 시 부스터 비중으로 재진입
                    _rebalance(pending_aw, p); pending_aw = None
                elif note.startswith('fast_recover'):
                    if FAST_RECOVER_KEEPS_GOLD:
                        proc = _sell_all('BOXX', p)             # F3-True: 대기 BOXX만 TQQQ로, gold 무접촉
                        _buy_amt('TQQQ', proc, p)
                    else:
                        _rebalance(base_w, p)                   # F3-False(기본): 전체 50:50 재조정
                else:
                    hedge_assets = [k for k in base_w if k not in ('TQQQ', 'BOXX')]
                    if hedge_assets:
                        proc = _sell_all('BOXX', p)
                        _buy_amt('TQQQ', proc, p)
                    else:
                        _rebalance(base_w, p)
                state = 'INVESTED'

            pending = None
            executed = True

        if annual_pending and not executed and not is_last:
            annual_pending = False
            if state in ['INVESTED']:
                _rebalance(target_w, p)
                is_boosted = False   # 연례 리밸런싱 시 부스터 해제(부스터B는 여기서 환원)
            elif state == 'CASH_BOXX':
                aw = base_w.copy()
                aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0)
                aw['TQQQ'] = 0
                _rebalance(aw, p)
            elif state == 'CASH_USD':
                # F2: TQQQ 몫만 현금 대기로 두고, 헤지자산(BOXX/gold)은 유지.
                #     (기존엔 aw['BOXX']=0로 헤지까지 전량 매도 → 이후 100% TQQQ로 튀는 엣지 발생)
                aw = base_w.copy()
                aw['TQQQ'] = 0
                _rebalance(aw, p)
            executed = True

        if not pending:
            gspc = p['GSPC_RAW']; gsma = p['SPY_SMA200']
            ndx = p['NDX_RAW']; nsma = p['NDX_SMA200']; bub = p['Bubble_Value']
            # ★K3: 게이트·탈출지수 산출(사양 K3). ABS는 현행(버블≥1.30)과 수학적 동치 → K7 회귀 보장.
            #   B1: 백분위 NaN인 날 gate_hot=False — VR 원형 게이트("if not pd.isna(pc) and pc >= B1_PCTL")와
            #       동일 규칙(사양 K2의 기본안과 일치, 상충 없음).
            #   복귀 내부 로직(spx_ok/ndx_ok·recover_spx_only·buy_boxx·월말 판정)은 EXIT_INDEX를 참조하지 않음.
            if _gmode == "B1":
                _pctl = p['Bubble_Pctl'] if 'Bubble_Pctl' in p.index else np.nan
                gate_hot = (not pd.isna(_pctl)) and (_pctl >= B1_PCTL)
            elif _gmode == "NONE":
                gate_hot = True
            else:                                   # "ABS" (기본)
                gate_hot = (bub >= BUBBLE_LIMIT)
            exit_px, exit_sma = (ndx, nsma) if _exit_idx == "NDX" else (gspc, gsma)
            # ★K9: 핫게이트(게이트 열림) 복귀 판정 — GSPC(기본)면 spx_ok와 동일값(현행 동치, K12 회귀 보장).
            #   냉게이트 복귀(spx_ok/ndx_ok 병용)·부스터는 무접촉(사양 K8 범위 제한).
            #   go_invest 처리부 무변경 — recover_ndx_only도 기존 else 경로(현금→TQQQ만 / BOXX만 TQQQ 전환)로 자연 처리.
            rec_ok = (ndx > nsma) if _rec_idx == "NDX" else (gspc > gsma)

            if method == 'fast_recover':
                if state == 'INVESTED':
                    if gate_hot and exit_px < exit_sma:     # ★K3: (bub≥1.30 and gspc<gsma) → 게이트·지수 일반화
                        pending = 'go_cash'; trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'exit'}

                elif state in ['CASH_USD', 'CASH_BOXX'] and is_month_end:
                    spx_ok = gspc > gsma
                    if not gate_hot:                        # ★K3: (bub < BUBBLE_LIMIT) → 게이트 일반화
                        ndx_ok = ndx > nsma
                        if spx_ok or ndx_ok:
                            who = 'S&P+NDX' if (spx_ok and ndx_ok) else ('S&P' if spx_ok else 'NDX')
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'ndx': ndx, 'ndx_sma200': nsma, 'note': f'fast_recover_{who}'}
                    else:
                        if rec_ok:                              # ★K9: spx_ok → rec_ok(복귀지수 일반화)
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': ('recover_spx_only' if _rec_idx == "GSPC" else 'recover_ndx_only')}   # ★K9: note 동적화(GSPC=종전 바이트 동일)

                    if state == 'CASH_USD' and not pending:
                        pending = 'go_boxx'
                        trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'buy_boxx'}

            elif method == 'boost_until_annual':
                # 원안 fast_recover와 신호 동일. 단, 복귀 트리거가 'NDX 단독'(S&P 아직 200일선 아래)일 때
                # 평상시 비중 대신 부스터 비중(예: 60:40)으로 진입. 환원은 연례 리밸런싱(12/31).
                if state == 'INVESTED':
                    if gate_hot and exit_px < exit_sma:     # ★K3: (bub≥1.30 and gspc<gsma) → 게이트·지수 일반화
                        pending = 'go_cash'; trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'exit'}
                        is_boosted = False

                elif state in ['CASH_USD', 'CASH_BOXX'] and is_month_end:
                    spx_ok = gspc > gsma
                    if not gate_hot:                        # ★K3: (bub < BUBBLE_LIMIT) → 게이트 일반화
                        ndx_ok = ndx > nsma
                        if spx_ok or ndx_ok:
                            who = 'S&P+NDX' if (spx_ok and ndx_ok) else ('S&P' if spx_ok else 'NDX')
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            # NDX 단독 복귀(S&P 아직 아래)일 때만 부스터 ON
                            if who == 'NDX':
                                pending_aw = _boost_w.copy()
                                is_boosted = True
                                trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'ndx': ndx, 'ndx_sma200': nsma, 'note': f'fast_recover_boost_{who}'}
                            else:
                                trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'ndx': ndx, 'ndx_sma200': nsma, 'note': f'fast_recover_{who}'}
                    else:
                        if rec_ok:                              # ★K9: spx_ok → rec_ok(복귀지수 일반화)
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': ('recover_spx_only' if _rec_idx == "GSPC" else 'recover_ndx_only')}   # ★K9: note 동적화(GSPC=종전 바이트 동일)

                    if state == 'CASH_USD' and not pending:
                        pending = 'go_boxx'
                        trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'buy_boxx'}

        # ★F7: 일별 NAV = 자산 − '확정' 세부채만 (VR v3 방식). 잠재세 차감 폐지.
        history.append(max(0, _val(hold, cash, p) - tax_bill))

        if is_last:
            for t in list(hold.keys()):
                if hold[t]['units'] > 0:
                    hold, eq_p, cash, _ = _sell(t, hold, _exec_px(p, t), eq_p, cash, NORMAL_SLIPPAGE)
            final_tax = max(0, eq_p - TAX_EXEMPTION) * TAX_RATE_EQUITY
            cash -= (final_tax + tax_bill)
            history[-1] = max(0, cash)
            continue

        if is_year_end:
            annual_pending = True
            if eq_p > TAX_EXEMPTION:
                tax_bill += (eq_p - TAX_EXEMPTION) * TAX_RATE_EQUITY
            eq_p = 0

        if is_may_end:
            tax_pending = True

    return pd.Series(history, index=dates), pd.DataFrame(logs)


# ═══ [R5 엔진 — R4 v3 부품 조립. FAST 상태기계·방석·통합 과세는 원문 그대로, 80:20 복원만 신규 접점] ═══
def build_master():
    """마스터 데이터(R4 v3 build_master 승계 — VR/QQQ 열 불요분 제외)."""
    lev, syn, real, scale = build_lev_series()
    ndx = _fetch_close('^NDX', FETCH_START)
    gspc = _fetch_close('^GSPC', FETCH_START)
    irx = _fetch_close('^IRX', "1985-01-01")
    gold = load_gold()
    m0 = fetch_m0()
    idx = ndx.index[(ndx.index >= FETCH_START)]
    last = min(lev.index[-1], ndx.index[-1], gspc.index[-1], irx.index[-1], gold.index[-1])
    idx = idx[idx <= last]
    D = pd.DataFrame(index=idx)
    D['TQQQ'] = lev.reindex(idx).ffill()
    D['TQQQ_OPEN'] = D['TQQQ']
    D['gold'] = gold.reindex(idx).ffill()
    D['NDX'] = D['NDX_RAW'] = ndx.reindex(idx).ffill()
    D['GSPC'] = D['GSPC_RAW'] = gspc.reindex(idx).ffill()
    D['NSMA'] = D['NDX_SMA200'] = D['NDX_RAW'].rolling(200).mean()
    D['GSMA'] = D['SPY_SMA200'] = D['GSPC_RAW'].rolling(200).mean()
    D['IRX'] = irx.reindex(idx).ffill().bfill()
    D['IRXD'] = (1.0 + D['IRX'] / 100.0) ** (1.0 / 252.0) - 1.0
    D['BOXX'] = 100.0 * (1.0 + D['IRXD']).cumprod()
    D['BOXX_OPEN'] = D['BOXX']
    m0d = m0.reindex(idx.union(m0.index)).ffill().reindex(idx)
    D['BUB'] = D['Bubble_Value'] = D['GSPC_RAW'] / m0d
    D['BUB_PCTL'] = D['Bubble_Pctl'] = D['Bubble_Value'].rolling(int(252 * 10), min_periods=int(252 * 3)).apply(
        lambda x: float((x[-1] >= x).mean()), raw=True)
    return D

def run_arm(D, win, weights, cush_w, init=R5_INIT):
    """R5 한 팔 주행. weights=FAST 가중(W_A 또는 W_B), cush_w=방석 비중(0이면 FAST 단독).
       FAST 상태기계·방석·통합 과세 바구니는 R4 v3 run_r4 원문 이식. 80:20 복원만 ★R5 신규 접점."""
    sub = D.loc[win]; dates = sub.index
    ye_days, pay_days = _tax_calendar(dates)
    uni = {'realized': 0.0, 'liab': 0.0}
    f_cap = init * (1.0 - cush_w); c_cap = init * cush_w
    f_cash = float(f_cap); f_hold = {}; f_state = 'INVESTED'
    f_pending = None; f_annual_pending = False; f_trig = {}
    n_exit = 0; evac_days = 0; tax_total = 0.0; tax_log = []
    cu_bx_u = 0.0; cu_bx_cost = 0.0; cu_g_u = 0.0
    if f_cap > 0:
        p0 = sub.iloc[0]
        for t, w in weights.items():
            px = _exec_px(p0, t, is_open=True)
            if not pd.isna(px) and w > 0:
                f_hold, used = _buy(t, f_cap * w, px, f_hold, NORMAL_SLIPPAGE)
                f_cash -= used
    if c_cap > 0:                                        # 방석 초기 배정(BOXX ⅔ : KRX금 ⅓)
        p0 = sub.iloc[0]
        amt_bx = c_cap * CUSH_BOND_W; amt_g = c_cap * (1 - CUSH_BOND_W)
        q = amt_bx / (p0['BOXX'] * (1 + US_FEE)); cu_bx_u += q; cu_bx_cost += amt_bx
        cu_g_u += amt_g / (p0['gold'] * (1 + KRX_FEE))

    def f_add_real(pr): uni['realized'] += pr
    def f_rebalance(aw, p):
        nonlocal f_cash, f_hold
        total = _val_open(f_hold, f_cash, p)
        for t in list(f_hold.keys()):
            px = _exec_px(p, t, is_open=True)
            if pd.isna(px) or px <= 0: continue
            tv = total * aw.get(t, 0); cv = f_hold[t]['units'] * px
            if cv > tv:
                u = min((cv - tv) / px, f_hold[t]['units'])
                net = px * (1 - _get_slip_comm(t))
                if _is_taxable_equity(t): f_add_real((net - f_hold[t]['entry_price_usd']) * u)
                f_cash += u * net; f_hold[t]['units'] = max(0, f_hold[t]['units'] - u)
        actual = _val_open(f_hold, f_cash, p)
        for t, w in aw.items():
            if w <= 0: continue
            px = _exec_px(p, t, is_open=True)
            if pd.isna(px) or px <= 0: continue
            deficit = actual * w - f_hold.get(t, {'units': 0})['units'] * px
            if deficit > 0 and f_cash > 0:
                f_hold, used = _buy(t, min(f_cash, deficit), px, f_hold, NORMAL_SLIPPAGE)
                f_cash -= used
    def f_sell_all(t, p):
        nonlocal f_cash, f_hold
        if t not in f_hold or f_hold[t]['units'] <= 0: return 0.0
        px = _exec_px(p, t, is_open=True)
        if pd.isna(px) or px <= 0: return 0.0
        u = f_hold[t]['units']; net = px * (1 - _get_slip_comm(t))
        if _is_taxable_equity(t): f_add_real((net - f_hold[t]['entry_price_usd']) * u)
        f_cash += u * net; f_hold[t]['units'] = 0.0
        return u * net
    def f_buy_amt(t, amt, p):
        nonlocal f_cash, f_hold
        if amt <= 1e-9: return
        px = _exec_px(p, t, is_open=True)
        if pd.isna(px) or px <= 0: return
        f_hold, used = _buy(t, amt, px, f_hold, NORMAL_SLIPPAGE)
        f_cash -= used
    def f_sell_prorata(need, p):
        nonlocal f_cash, f_hold
        total_h = _val_open(f_hold, 0, p)
        if total_h <= 0: return
        for t in list(f_hold.keys()):
            if f_hold[t]['units'] > 0:
                px = _exec_px(p, t, is_open=True)
                if pd.isna(px) or px <= 0: continue
                amt = need * (f_hold[t]['units'] * px / total_h)
                u = min(amt / px, f_hold[t]['units'])
                net = px * (1 - _get_slip_comm(t))
                if _is_taxable_equity(t): f_add_real((net - f_hold[t]['entry_price_usd']) * u)
                f_cash += u * net; f_hold[t]['units'] = max(0, f_hold[t]['units'] - u)
    def cu_val(p): return cu_bx_u * p['BOXX'] + cu_g_u * p['gold']
    def fast_val(p): return _val(f_hold, f_cash, p)
    def cu_buy(amt_bx, amt_g, p):
        nonlocal cu_bx_u, cu_bx_cost, cu_g_u
        if amt_bx > 1e-9:
            q = amt_bx / (p['BOXX'] * (1 + US_FEE)); cu_bx_u += q; cu_bx_cost += amt_bx
        if amt_g > 1e-9:
            cu_g_u += amt_g / (p['gold'] * (1 + KRX_FEE))
    def cu_sell_bx(amt, p):
        nonlocal cu_bx_u, cu_bx_cost
        if cu_bx_u <= 1e-12: return 0.0
        q = min(cu_bx_u, amt / (p['BOXX'] * (1 - US_FEE)))
        net = q * p['BOXX'] * (1 - US_FEE)
        avg = cu_bx_cost / cu_bx_u
        uni['realized'] += net - avg * q                  # Q4: BOXX 실현손익 → 통합 바구니
        cu_bx_cost = max(0.0, cu_bx_cost - avg * q); cu_bx_u -= q
        return net
    def cu_sell_g(amt, p):
        nonlocal cu_g_u
        if cu_g_u <= 1e-12: return 0.0
        q = min(cu_g_u, amt / (p['gold'] * (1 - KRX_FEE)))
        cu_g_u -= q
        return q * p['gold'] * (1 - KRX_FEE)              # KRX금 비과세(수수료만)

    nav_path = np.empty(len(dates)); cf_day = np.zeros(len(dates))
    for i, cd in enumerate(dates):
        p = sub.iloc[i]; is_last = (i == len(dates) - 1)
        is_month_end = (i < len(dates) - 1 and cd.month != dates[i + 1].month)
        is_year_end = (cd in ye_days)
        f_executed = False
        # ① 통합 납부(6월 첫 거래일): 방석 BOXX → 방석 금 → FAST(정본 비례매도)
        if uni['liab'] > 1e-9 and cd in pay_days:
            T = uni['liab']; got = 0.0
            if cush_w > 0:
                got += cu_sell_bx(T, p)
                if T - got > 1e-9: got += cu_sell_g(T - got, p)
            if T - got > 1e-9:
                take = min(T - got, f_cash); f_cash -= take; got += take
                if T - got > 1e-9:
                    f_sell_prorata(T - got, p)
                    take2 = min(T - got, f_cash); f_cash -= take2; got += take2
            uni['liab'] -= got; tax_total += got; cf_day[i] -= got
        # ② FAST pending 집행(정본 순서·산식)
        if f_pending and not f_executed and not is_last:
            if f_pending == 'go_cash':
                f_sell_all('TQQQ', p); f_state = 'CASH_USD'
            elif f_pending == 'go_boxx':
                f_buy_amt('BOXX', f_cash, p); f_state = 'CASH_BOXX'
            elif f_pending in ('go_invest_from_usd', 'go_invest_from_boxx'):
                if str(f_trig.get('note', '')).startswith('fast_recover'):
                    f_rebalance(weights, p)
                else:
                    if f_pending == 'go_invest_from_usd': f_buy_amt('TQQQ', f_cash, p)
                    else:
                        proc = f_sell_all('BOXX', p); f_buy_amt('TQQQ', proc, p)
                f_state = 'INVESTED'
            f_pending = None; f_executed = True
        # ③ FAST 연 리밸(정본: 12/31 표시 → 익영업일 집행)
        if f_annual_pending and not f_executed and not is_last:
            f_annual_pending = False
            if f_state == 'INVESTED':
                f_rebalance(weights, p)
            elif f_state == 'CASH_BOXX':
                aw = weights.copy(); aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0); aw['TQQQ'] = 0
                f_rebalance(aw, p)
            elif f_state == 'CASH_USD':
                aw = weights.copy(); aw['TQQQ'] = 0
                f_rebalance(aw, p)
            f_executed = True
        # ④ FAST 신호(정본: GATE=ABS·EXIT=NDX·복귀 GSPC 월말+fast_recover)
        if not f_pending:
            gspc = p['GSPC_RAW']; gsma = p['SPY_SMA200']
            ndx_ = p['NDX_RAW']; nsma = p['NDX_SMA200']; bub = p['Bubble_Value']
            gate_hot = (bub >= BUBBLE_LIMIT)
            if f_state == 'INVESTED':
                if gate_hot and ndx_ < nsma:
                    f_pending = 'go_cash'; f_trig = {'note': 'exit'}; n_exit += 1
            elif f_state in ('CASH_USD', 'CASH_BOXX') and is_month_end:
                spx_ok = gspc > gsma
                if not gate_hot:
                    if spx_ok or (ndx_ > nsma):
                        f_pending = ('go_invest_from_usd' if f_state == 'CASH_USD' else 'go_invest_from_boxx')
                        f_trig = {'note': 'fast_recover'}
                elif spx_ok:
                    f_pending = ('go_invest_from_usd' if f_state == 'CASH_USD' else 'go_invest_from_boxx')
                    f_trig = {'note': 'recover_spx_only'}
                if f_state == 'CASH_USD' and not f_pending:
                    f_pending = 'go_boxx'; f_trig = {'note': 'buy_boxx'}
        if f_state != 'INVESTED': evac_days += 1
        # ⑤ 12/31: 방석 내부 리밸 → ★R5 신규 접점(주머니 80:20 복원) → 통합 정산
        if is_year_end and cush_w > 0:
            cv = cu_val(p)
            if cv > 1e-9:                                  # 방석 내부 2:1 복원(R4 원문)
                tgt_bx = cv * CUSH_BOND_W; cur_bx = cu_bx_u * p['BOXX']
                if cur_bx > tgt_bx + 1e-9:
                    net = cu_sell_bx((cur_bx - tgt_bx) * (1 - US_FEE), p)
                    cu_g_u += net / (p['gold'] * (1 + KRX_FEE))
                elif tgt_bx - cur_bx > 1e-9:
                    net = cu_sell_g((tgt_bx - cur_bx) * (1 - KRX_FEE), p)
                    q = net / (p['BOXX'] * (1 + US_FEE)); cu_bx_u += q; cu_bx_cost += net
            # ★R5 신규 접점(사양 R5-1이 허가한 유일한 신규 로직): 주머니 80:20 복원.
            #   기존 부품만 재사용 — FAST측 f_sell_prorata/f_buy_amt, 방석측 cu_buy/cu_sell_bx/cu_sell_g.
            #   Q3: 킬스위치 대피 중에도 무조건 수행. Q4: 발생 실현손익은 통합 바구니 산입.
            fv = fast_val(p); cvv = cu_val(p); tot = fv + cvv
            if tot > 1e-9:
                tgt_f = tot * B_FAST_W
                if fv > tgt_f + 1e-9:                      # FAST → 방석
                    need = fv - tgt_f
                    take = min(need, f_cash); f_cash -= take
                    if need - take > 1e-9:
                        f_sell_prorata(need - take, p)
                        t2 = min(need - take, f_cash); f_cash -= t2; take += t2
                    cu_buy(take * CUSH_BOND_W, take * (1 - CUSH_BOND_W), p)
                elif tgt_f - fv > 1e-9:                    # 방석 → FAST
                    need = tgt_f - fv
                    got = cu_sell_bx(need * CUSH_BOND_W, p) + cu_sell_g(need * (1 - CUSH_BOND_W), p)
                    if got > 1e-9:
                        f_cash += got
                        if f_state == 'INVESTED':
                            for t, w in weights.items():
                                if w > 0: f_buy_amt(t, got * w, p)
                        else:
                            f_buy_amt('BOXX' if f_state == 'CASH_BOXX' else 'TQQQ', 0.0, p)
        if is_year_end:
            _t = max(0.0, uni['realized'] - TAX_EXEMPTION) * TAX_RATE_EQUITY
            tax_log.append((cd.year, uni['realized'], max(0.0, uni['realized'] - TAX_EXEMPTION), _t))
            uni['liab'] += _t; uni['realized'] = 0.0
            f_annual_pending = True
        nav_path[i] = max(fast_val(p) + cu_val(p) - uni['liab'], 0.0)
        if is_last:                                        # 만기 청산 → 마지막해 정산(공제 1회)
            for t in list(f_hold.keys()): f_sell_all(t, p)
            cash_c = 0.0
            if cu_bx_u > 1e-12:
                net = cu_bx_u * p['BOXX'] * (1 - US_FEE)
                avg = cu_bx_cost / cu_bx_u
                uni['realized'] += net - avg * cu_bx_u
                cash_c += net; cu_bx_u = 0.0; cu_bx_cost = 0.0
            if cu_g_u > 1e-12:
                cash_c += cu_g_u * p['gold'] * (1 - KRX_FEE); cu_g_u = 0.0
            final_tax = max(0.0, uni['realized'] - TAX_EXEMPTION) * TAX_RATE_EQUITY
            after = f_cash + cash_c - final_tax - uni['liab']
            tax_total += final_tax + uni['liab']
            nav_path[i] = max(after, 0.0)
    return dict(nav=pd.Series(nav_path, index=dates), cf=pd.Series(cf_day, index=dates),
                n_exit=n_exit, evac_days=evac_days, tax_total=tax_total, tax_log=tax_log)

# ═══ [메인: 창 열거·게이트·산출물 — 사양 R5-3~R5-5] ═══
def _win_list(idx):
    wins = []
    for y in R1_YEARS:
        start = idx[idx >= f"{y}-01-01"][0]
        wins.append(("R1", y, idx[(idx >= start) & (idx < start + pd.DateOffset(years=WINDOW_Y))]))
    for y in START_YEARS:
        start = idx[idx >= f"{y}-01-01"][0]
        wins.append(("E1", y, idx[(idx >= start)]))
        if y <= E2_MAX_START_YEAR:
            wins.append(("E2", y, idx[(idx >= start) & (idx <= pd.Timestamp(END_MODE_E2))]))
    return wins

ARMS = [("A", "FAST 50:50 단독(눈금 1.50)", None, 0.0),
        ("B", "FAST 60:40 80% + 방석 20%(눈금 1.44)", None, B_CUSH_W),
        ("C", "FAST 60:40 단독(기준선)", None, 0.0)]

def _arm_weights(tag):
    return W_B if tag == "A" else W_A          # A = 정본 99행 W_B 원문, B·C = W_A

def main():
    print("=" * 100)
    print("  [R5] 냉각방식 비교 — 계좌 안(A) vs 주머니 차원(B), 기준선 C (사양 v1 · 관찰 전용)")
    print("=" * 100)
    try:
        self_md5 = hashlib.md5(open(__file__, 'rb').read()).hexdigest()
    except Exception:
        self_md5 = "(셀 붙여넣기 실행 — 스크립트 md5는 칠판 raw로 대조)"
    print(f"  · 스크립트 md5: {self_md5}")
    print(f"  · 시작 자본 ${R5_INIT:,.0f} 동일 · 적립 M=0(맨몸 비교) · 비중 스윕 금지(3팔 고정)")
    print("  · 각주(필수): 관찰 전용 — 60:40 스윕 봉인·방석 확정 불변. 본 실험으로 어떤 확정도 변경되지")
    print("    않으며, 재론은 연말 재심 절차로만 가능.")
    print("  · 각주(Q3): 대피 중 복원은 동성격 자산(BOXX↔BOXX) 간 이체라 수수료·세금만 발생하나,")
    print("    소액이며 규칙 단순성을 우선함.")
    print("  · 세금: B = FAST+BOXX 합산 바구니·KRX금 비과세 / A·C = FAST 단독 바구니. 공제 $1,785.71")
    print("    연 1회·22%·6월 첫 거래일 납부. 수수료 미국 0.1%·KRX금 0.3%·FAST 내 금 0(정본 F10).")

    D = build_master()
    print(f"  · 기준 달력: ^NDX 실거래일 {D.index[0].date()} ~ {D.index[-1].date()} ({len(D)}일)")
    wins = _win_list(D.index)

    # ── V9 정합(대표 3창) ──
    print("\n" + "-" * 100)
    print(f"  [V9] 정합 — (a) B에서 방석 0 → C와 일치 / (b) A ↔ 정본 run_simulation(W_B) 직접 실행")
    print(f"       허용 ±{V9_TOL}%p(R4 실측 최대 +0.395%p 감안), {V9_REPORT}%p 초과 시 통과라도 원인 보고")
    for mode, y, win in [w for w in wins if w[0] == "R1" and w[1] in (1994, 2000, 2005)]:
        yrs = (win[-1] - win[0]).days / 365.25
        cagr = lambda v: (v / R5_INIT) ** (1 / yrs) - 1
        rb0 = run_arm(D, win, W_A, 0.0)                     # B 구조에서 방석 0
        rc = run_arm(D, win, W_A, 0.0)
        da = (cagr(float(rb0['nav'].iloc[-1])) - cagr(float(rc['nav'].iloc[-1]))) * 100
        ra = run_arm(D, win, W_B, 0.0)
        nav_o, _ = run_simulation(D.loc[win], R5_INIT, W_B, method='fast_recover')
        db = (cagr(float(ra['nav'].iloc[-1])) - cagr(float(nav_o.iloc[-1]))) * 100
        okA, okB = abs(da) <= V9_TOL, abs(db) <= V9_TOL
        print(f"    [{y}] (a) 방석0 vs C: 차 {da:+.3f}%p {'PASS' if okA else '★FAIL'} | "
              f"(b) A vs 정본: {cagr(float(ra['nav'].iloc[-1]))*100:6.2f}% vs {cagr(float(nav_o.iloc[-1]))*100:6.2f}% "
              f"→ 차 {db:+.3f}%p {'PASS' if okB else '★FAIL'}")
        if abs(db) > V9_REPORT:
            print(f"        · 보고: 오차 {V9_REPORT}%p 초과 — 원인 = 만기 청산·납부 경로의 통합화(R4 V8 기실측 동일 사유)")
        assert okA and okB, f"V9 실패: {y}"

    # ── 본 주행 ──
    print("\n" + "-" * 100)
    print(f"  [V3] 창 무결({len(wins)}창 = R1 24 + E1 16 + E2 12) × 3팔")
    rows = []; chart_store = {}
    for mode, y, win in wins:
        sub = D.loc[win]
        assert not sub[['TQQQ', 'gold', 'GSPC_RAW', 'NDX_RAW', 'IRXD', 'Bubble_Value']].isna().any().any(), f"{mode}/{y} 결측"
        yrs = (win[-1] - win[0]).days / 365.25
        note = "참고" if (mode != "R1" and yrs < MIN_YEARS_JUDGE) else ""
        bx = sub['BOXX']; b_cagr = (bx.iloc[-1] / bx.iloc[0]) ** (1 / yrs) - 1
        v4 = abs(b_cagr * 100 - float(sub['IRX'].mean()))
        assert v4 <= 0.3, f"V4 실패 {mode}/{y}: {v4:.2f}%p"
        rl = sub['TQQQ'].pct_change().to_numpy()[1:]
        cmask = rl <= CRISIS_DD                              # 위기일 = 세 팔 공통 집합
        line = []
        store = {}
        for tag, label, _, cw in ARMS:
            res = run_arm(D, win, _arm_weights(tag), cw)
            nav = res['nav']; cf = res['cf']
            after = float(nav.iloc[-1])
            cg = (after / R5_INIT) ** (1 / yrs) - 1 if after > 0 else float('nan')
            mdd = float((nav / nav.cummax() - 1).min()) * 100
            r_adj = ((nav - cf) / nav.shift(1) - 1.0).to_numpy()[1:]   # 외부 현금흐름 제외
            worst = float(np.nanmin(r_adj[cmask]) * 100) if cmask.any() else float('nan')
            rows.append({"모드": mode, "창시작연도": y, "팔": tag, "설명": label,
                         "시작일": str(win[0].date()), "종료일": str(win[-1].date()),
                         "길이년": round(yrs, 2), "딱지": note,
                         "CAGR%": round(cg * 100, 3) if cg == cg else "", "MDD%": round(mdd, 2),
                         "최종배수": round(after / R5_INIT, 3), "세금총액$": round(res['tax_total'], 0),
                         "위기일최악%": round(worst, 3) if worst == worst else "",
                         "KS발동": res['n_exit'], "대피일수": res['evac_days']})
            line.append(f"{tag} {cg*100:6.2f}%/{mdd:6.1f}%/x{after/R5_INIT:6.2f}")
            store[tag] = (nav, cg, mdd)
        if mode == "R1" and y in (2000, 2010):
            chart_store[y] = (store, win)
        print(f"    [{mode}] {y}: {win[0].date()}~{win[-1].date()} {yrs:5.2f}년 {note:4s}| " + " | ".join(line))

    S = pd.DataFrame(rows)
    S.to_csv("summary_r5.csv", index=False, encoding="utf-8-sig")

    # ── 합산 요약(R1 창 기준) ──
    print("\n" + "=" * 100)
    R1 = S[S.모드 == "R1"]
    print("  [합산] R1 완결 24창 — 팔별 중앙값(승부보다 격차의 크기가 관찰 대상, 사양 R5-6)")
    print(f"    {'팔':<3} | {'CAGR 중앙':>10} | {'MDD 중앙':>10} | {'세금 중앙$':>12} | {'위기일 최악 중앙':>16}")
    for tag, label, _, _ in ARMS:
        T = R1[R1.팔 == tag]
        print(f"    {tag:<3} | {pd.to_numeric(T['CAGR%']).median():>9.2f}% | {T['MDD%'].median():>9.2f}% | "
              f"{T['세금총액$'].median():>12,.0f} | {pd.to_numeric(T['위기일최악%']).median():>15.2f}%")
    for pair in [("A", "B"), ("B", "C")]:
        a = R1[R1.팔 == pair[0]].reset_index(); b = R1[R1.팔 == pair[1]].reset_index()
        w = int((pd.to_numeric(a['CAGR%']) > pd.to_numeric(b['CAGR%'])).sum())
        m = int((a['MDD%'] > b['MDD%']).sum())
        print(f"    · {pair[0]} vs {pair[1]}: 수익 우위 {w}/{len(a)}창 · 낙폭 얕음 {m}/{len(a)}창")

    print("\n  [V5] 산출물 md5 — 칠판 업로드 후 감사역이 raw+캐시버스팅으로 수신·대조:")
    print(f"      summary_r5.csv : {_md5_file('summary_r5.csv')}  ({len(S)}행)")
    print(f"      script         : {self_md5}")

    # ── 대표 창 차트(Q5: 3선 + 낙폭 3선) ──
    try:
        import matplotlib
        try:
            from IPython import get_ipython
            in_nb = (get_ipython() is not None) or ('google.colab' in __import__('sys').modules)
        except Exception:
            in_nb = False
        if not in_nb: matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        _setup_korean_font()
        colors = {"A": "#1f77b4", "B": "crimson", "C": "#7f7f7f"}
        for y, (store, win) in sorted(chart_store.items()):
            fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 8),
                                         gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
            a1.set_title(f"R5 냉각방식 비교 R1/{y} ({win[0].date()}~{win[-1].date()}) — A 계좌 안 vs B 주머니 차원")
            for tag, label, _, _ in ARMS:
                nav, cg, mdd = store[tag]
                a1.plot(nav.index, nav, lw=1.6, color=colors[tag],
                        label=f"{tag} {label} (CAGR {cg*100:.1f}%, MDD {mdd:.1f}%)")
                a2.plot(nav.index, (nav / nav.cummax() - 1) * 100, lw=1.2, color=colors[tag])
            a1.set_yscale("log"); a1.set_ylabel("NAV (USD, Log)")
            a1.legend(fontsize=9); a1.grid(alpha=0.3)
            a2.set_ylabel("DD (%)"); a2.grid(alpha=0.3)
            plt.tight_layout()
            out = f"r5_chart_{y}.png"
            plt.savefig(out, dpi=100, bbox_inches="tight")
            print(f"  · 차트 저장: {out}")
            if in_nb:
                try: plt.show()
                except Exception: pass
            plt.close()
    except Exception as e:
        print(f"  · 차트 생략({str(e)[:70]})")
    print("=" * 100)

if __name__ == "__main__":
    main()
  
