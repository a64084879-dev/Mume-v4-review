# -*- coding: utf-8 -*-
"""
[Phase 0.5 단일 실행 파일] 블렌드 프론티어 + 정밀 세금 경계 + 롤링 7년창  두 백테스터(FAST·VR)를 통째로 임베드해 블렌드 프론티어를 산출.
이 파일 하나만 실행하면 됩니다. 다른 파일 불필요.
  · FAST 엔진 = 부스터B A(gold), 세후
  · VR 엔진   = 거치식 VR+KS(killswitch=on·B1=on·VOLTGT=off), 세후(FAST와 동일 잠재세 기준)
  · 두 엔진은 격리 네임스페이스(FAST_NS/VR_NS)에서 exec → 상수 충돌(END_DATE 등) 없음.
"""
import os, sys

# ============================================================================
#  [임베드 1/2] FAST 엔진 (fast_backtest_fixed.py, __main__ 제외 · verbatim)
# ============================================================================
_FAST_ENGINE_SRC = r'''
# ------------------------------------------------------------
# [빠른복귀(FAST) + 스마트 BOXX 진입 백테스트] — 감사 수정 반영판
#  + QLD(나스닥100 2배) 벤치마크 비교 라인 (SPY/QQQ와 동일 방식)
#
#  ★ [핵심 로직: 스마트 BOXX 진입 & 최소 스왑]
#      1. 대피 신호: TQQQ만 매도 → 순수 달러(USD) 현금 대기. (비용 0%)
#      2. 첫 월말 복귀 판정일:
#         - recover_spx_only(버블≥1.30, S&P만 회복): 현금으로 바로 TQQQ 재매수. gold 무접촉.
#         - fast_recover(버블<1.30, S&P/NDX 회복): 아래 FAST_RECOVER_KEEPS_GOLD 플래그에 따름.
#              · False(기본, 기존 백테스트 유지) → 전체 50:50 재조정(_rebalance, gold도 리밸런싱).
#              · True(헤더 원안)                → 현금으로 TQQQ만 매수, gold 무접촉.
#         - 복귀 미충족(진짜 하락장): 대기 현금만 BOXX로 매수. (금은 절대 건드리지 않음)
#
#  ── 감사 수정 요약 ──
#   F1: [5a] B(BOXX)에 boost_until_annual 돌릴 때 기본 RECOVER_BOOST(gold 40%)가 들어가
#       B가 gold를 매수하던 버그 → 포트 정합 부스터(B는 BOXX)로 recover_boost 전달.
#   F2: 대피 신호가 12/31에 뜨는 엣지에서 CASH_USD 연례분기가 BOXX 헤지까지 전량 매도해
#       100% TQQQ로 튀던 버그 → aw['BOXX']=0 제거(헤지 유지).
#   F3: 헤더 주석("복귀=현금→TQQQ만, gold 무접촉") vs 코드(_rebalance→gold 접촉) 불일치.
#       → FAST_RECOVER_KEEPS_GOLD 플래그로 명시화(기본=기존 동작). 실거래 봇 스펙에 맞춰 선택.
#   F4: 5월 세금 납부 시 현금 부족분 미납액이 소멸돼 NAV 과대 → 잔액 보존(최종청산 정산).
#   F5: 부스터 로그 라벨/카운트 하드코딩('60:40') → RECOVER_BOOST에서 동적 생성.
#   F6: get_data 3회 중복 다운로드 → FULL 1회만 받아 전 구간 공유(레이트리밋/불일치 방지).
# ------------------------------------------------------------
get_ipython = globals().get('get_ipython', None)
try:
    import yfinance  # noqa
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                    'yfinance', 'pandas-datareader', 'requests'], check=False)

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import platform, warnings, os, urllib.request
import matplotlib.font_manager as fm
import requests
try:
    from google.colab import drive as _colab_drive
    _colab_drive.mount('/content/drive')
except Exception:
    pass
warnings.filterwarnings('ignore')

# 한글 폰트
if platform.system() == 'Linux':
    font_path = 'NanumGothic.ttf'
    if not os.path.exists(font_path):
        urllib.request.urlretrieve(
            "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf",
            font_path)
    fm.fontManager.addfont(font_path)
    plt.rc('font', family=fm.FontProperties(fname=font_path).get_name())
elif platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# [1. 파라미터]
# ============================================================
FETCH_START_DATE = "1985-10-01"
START_DATE = "1986-08-01"   # ← 자유 조절(1986-08-01부터 가능)
END_DATE = "2026-01-01"

# ★ 메인 A vs B 성과표를 여러 시작일 각각으로 돌려 비교 (전체기간 표 아래에 추가 출력).
#   빈 리스트 []면 이 비교표 생략(전체기간만).
START_DATES = ["2010-02-11", "2013-01-02", "2016-01-02", "2018-01-02",
               "2020-01-02", "2021-01-02", "2022-01-02", "2024-01-02"]

INITIAL_CAPITAL = 100_000.0

W_A = {'TQQQ': 0.50, 'gold': 0.50}   # A: FAST + gold(비과세)
W_B = {'TQQQ': 0.50, 'BOXX': 0.50}   # B: FAST + BOXX(양도세)

BUBBLE_LIMIT = 1.30
TAX_RATE_EQUITY = 0.22
TAX_EXEMPTION = 1_724.0
NORMAL_SLIPPAGE = 0.002
COMMISSION = 0.0007
RISK_FREE_RATE = 0.045
FRED_API_KEY = os.environ.get("FRED_API_KEY", "2bdfd2e7c3efb097542a74f4de9b30b0")

TQQQ_REAL_START = "2010-02-11"
QLD_REAL_START = "2006-06-21"   # ★ QLD(나스닥100 2배) 상장일
BOXX_REAL_START = "2022-12-28"

# ============================================================
# [수동 M0 입력] (선택)
#   텔레그램 봇은 매일 FRED로 최신 M0를 받지만, 이 백테스트는 드라이브의
#   m0_full.csv를 쓰므로 최신월이 안 들어있을 수 있다(파일을 만든 시점까지만).
#   아래에 값을 넣으면 그 날짜의 M0를 직접 지정 → 최신 버블 계산에 반영된다.
#     · 둘 다 None이면 m0_full.csv(검증된 자동 데이터)를 그대로 사용.
#     · 단위: 10억 달러(B). 예) 2026-05 BOGMBASE ≈ 5400 → MANUAL_M0_VALUE = 5400
#   (FRED 최신값은 봇 보고서의 'M0 소스' 날짜와 fred.stlouisfed.org/series/BOGMBASE 참고)
# ============================================================
MANUAL_M0_DATE = None      # 예: "2026-05-01"  (None이면 자동)
MANUAL_M0_VALUE = None     # 예: 5400          (None이면 자동, 단위 B)

# [옵션3] m0_full.csv 자동 빌드 기준: 파일의 최신월이 이 일수보다 오래되면 빌더 재실행.
M0_STALE_DAYS = 75


# ★ 복귀 부스터: 빠른복귀(버블<1.30, NDX/S&P 중 먼저 200일선 회복) 진입 순간의 비중.
#   평상시 W_A와 별개로 자유 조절. 재원은 헤지자산에서 뺌(TQQQ↑, 헤지↓).
#   NOTE(F1): B(BOXX) 포트에 이 부스터를 쓸 때는 gold 키가 들어가면 안 됨.
#            → 5a/호출부에서 포트에 맞춰 hedge 키를 자동 치환해 전달한다.
RECOVER_BOOST = {'TQQQ': 0.60, 'gold': 0.40}

# ★ F3: 빠른복귀(fast_recover_*, 버블<1.30) 시 현금 재투자 방식 선택.
#   False = 현재 코드 동작(_rebalance(base_w) → gold까지 50:50 재조정). ★기존 백테스트 결과 유지
#   True  = 헤더 원안(현금으로 TQQQ만 매수 / BOXX만 TQQQ 전환, gold 무접촉).
#           실거래 봇이 '현금→TQQQ만' 방식이면 True로 맞춰 백테스트↔실거래 정합을 확보.
FAST_RECOVER_KEEPS_GOLD = False

# ============================================================
# [2. 데이터 함수]
# ============================================================
def fetch_fred_csv(series_id, start, end, retries=3):
    if not FRED_API_KEY:
        return pd.Series(dtype=float)
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
           f"&observation_start={start}&observation_end={end}")
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            r.raise_for_status()
            data = r.json().get('observations', [])
            if not data:
                return pd.Series(dtype=float)
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            return df.set_index('date')['value'].dropna()
        except Exception:
            if attempt < retries - 1:
                continue
            return pd.Series(dtype=float)

def _build_m0_fallback(index):
    m0_anchors = {1989: 270, 1995: 400, 2000: 580, 2005: 780, 2008: 850, 2009: 2050,
                  2013: 3600, 2017: 3800, 2020: 4800, 2022: 5900, 2024: 5600}
    s = pd.Series(m0_anchors)
    s.index = pd.to_datetime([f"{y}-01-01" for y in s.index])
    s = s.reindex(pd.date_range("1985-01-01", "2026-12-31", freq='YS')).interpolate().ffill().bfill()
    return s.resample('D').interpolate().reindex(index).ffill().bfill()

def load_m0_full(path="m0_full.csv"):
    """검증된 완전판 M0. CSV 있으면 로드, 없으면 직접 받아 검증·저장(보간 폴백 영구 제거)."""
    import io
    def _norm(s):
        s = pd.to_numeric(s, errors='coerce').dropna().sort_index()
        s.index = pd.to_datetime(s.index); s = s[~s.index.duplicated(keep='last')]
        if len(s) and s.max() > 100000: s = s / 1000.0
        return s
    def _ok(s):
        if s is None or len(s) == 0: return False
        seg = s[(s.index >= '2008-04-01') & (s.index <= '2008-06-30')]
        return len(seg) > 0 and 700 <= seg.mean() <= 950 and s.index.max() >= pd.Timestamp('2023-12-01')

    s = None
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            cand = _norm(pd.Series(df[df.columns[-1]].values, index=df[df.columns[0]].values))
            if _ok(cand): s = cand
        except Exception:
            s = None

    if s is None:   # CSV 없거나 불량 → 직접 받기 (FRED → DBnomics → Wayback)
        UA = {'User-Agent': 'Mozilla/5.0'}
        for _ in range(5):
            try:
                url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=BOGMBASE"
                       f"&api_key={FRED_API_KEY}&file_type=json"
                       f"&observation_start=1985-01-01&observation_end={END_DATE}")
                r = requests.get(url, headers=UA, timeout=40); r.raise_for_status()
                obs = r.json().get('observations', [])
                if obs:
                    df = pd.DataFrame(obs)
                    cand = _norm(pd.Series(df['value'].values, index=pd.to_datetime(df['date'])))
                    if _ok(cand): s = cand; break
            except Exception:
                pass
        if s is None:
            try:
                r = requests.get("https://api.db.nomics.world/v22/series/FRED/BOGMBASE?observations=1",
                                 headers=UA, timeout=40); r.raise_for_status()
                d = r.json()['series']['docs'][0]
                cand = _norm(pd.Series(d['value'], index=pd.to_datetime(d['period'])).replace('NA', np.nan))
                if _ok(cand): s = cand
            except Exception:
                pass
        if s is None:
            for ts in ["20260101000000", "20250601000000", "20250101000000"]:
                try:
                    r = requests.get(f"https://web.archive.org/web/{ts}id_/"
                                     f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=BOGMBASE",
                                     headers=UA, timeout=40)
                    if r.status_code == 200 and 'DATE' in r.text[:200].upper():
                        df = pd.read_csv(io.StringIO(r.text))
                        cand = _norm(pd.Series(df[df.columns[-1]].values, index=df[df.columns[0]].values))
                        if _ok(cand): s = cand; break
                except Exception:
                    pass
        if s is not None:
            try:
                out = s.rename('BOGMBASE'); out.index.name = 'DATE'; out.to_csv(path)
            except Exception:
                pass

    if s is None or not _ok(s):
        raise RuntimeError("M0(BOGMBASE) 확보·검증 실패 — FRED/DBnomics/Wayback 모두 불가. "
                           "build_m0_full.py를 따로 실행해 m0_full.csv를 만드세요.")
    return s.resample('B').ffill()

def build_m0_full(path, end=None):
    """[임베드 빌더 — 옵션3] BOGMBASE를 여러 소스로 받아 '4중 검증'(2008/2014/2021/2025)
       통과분만 path에 저장. 성공 시 시리즈 반환, 전 소스 실패 시 None(기존 파일 안 건드림)."""
    import io
    SERIES = "BOGMBASE"
    COSD = "1985-01-01"
    COED = end or pd.Timestamp.today().strftime('%Y-%m-%d')
    UA = {'User-Agent': 'Mozilla/5.0'}
    CHECK = {  # (시작, 끝, 하한, 상한) — 폴백/절단 데이터는 여기서 걸림
        "2008-05": ("2008-04-01", "2008-06-30",  750,  950),
        "2014-08": ("2014-07-01", "2014-09-30", 3700, 4300),
        "2021-12": ("2021-11-01", "2021-12-31", 5800, 6800),
        "2025-12": ("2025-11-01", "2025-12-31", 4900, 5900),
    }
    def _norm(s):
        s = pd.to_numeric(s, errors='coerce').dropna().sort_index()
        s.index = pd.to_datetime(s.index); s = s[~s.index.duplicated(keep='last')]
        if len(s) and s.max() > 100000: s = s / 1000.0
        return s
    def _valid(s):
        if s is None or len(s) == 0: return False
        for (a, b, lo, hi) in CHECK.values():
            seg = s[(s.index >= a) & (s.index <= b)]
            if not (len(seg) and lo <= seg.mean() <= hi): return False
        return True
    def _fred():
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={SERIES}"
               f"&api_key={FRED_API_KEY}&file_type=json&observation_start={COSD}&observation_end={COED}")
        for _ in range(5):
            try:
                r = requests.get(url, headers=UA, timeout=40); r.raise_for_status()
                obs = r.json().get('observations', [])
                if obs:
                    df = pd.DataFrame(obs)
                    return _norm(pd.Series(df['value'].values, index=pd.to_datetime(df['date'])))
            except Exception:
                continue
        return pd.Series(dtype=float)
    def _dbnomics():
        try:
            r = requests.get(f"https://api.db.nomics.world/v22/series/FRED/{SERIES}?observations=1",
                             headers=UA, timeout=40); r.raise_for_status()
            doc = r.json()['series']['docs'][0]
            return _norm(pd.Series(doc['value'], index=pd.to_datetime(doc['period'])).replace('NA', np.nan))
        except Exception:
            return pd.Series(dtype=float)
    def _wayback():
        base = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES}"
        best = pd.Series(dtype=float)
        for ts in ["20260101000000", "20250601000000", "20250101000000", "20240601000000"]:
            try:
                r = requests.get(f"https://web.archive.org/web/{ts}id_/{base}", headers=UA, timeout=40)
                if r.status_code != 200 or 'DATE' not in r.text[:200].upper(): continue
                df = pd.read_csv(io.StringIO(r.text))
                s = _norm(pd.Series(df[df.columns[-1]].values, index=df[df.columns[0]].values))
                if len(s) > len(best): best = s
                if len(s) and s.index.max() >= pd.Timestamp("2025-06-01"): return s
            except Exception:
                continue
        return best
    for nm, fn in [("FRED", _fred), ("DBnomics", _dbnomics), ("Wayback", _wayback)]:
        try:
            s = fn()
        except Exception:
            s = pd.Series(dtype=float)
        if _valid(s):
            s = s[(s.index >= COSD) & (s.index <= COED)]
            try:
                out = s.rename(SERIES); out.index.name = "DATE"; out.to_csv(path)
                print(f"  · ★ M0 빌더: {nm} 채택 → 저장 "
                      f"({s.index[0].date()}~{s.index[-1].date()}, 2008-05≈"
                      f"{s[(s.index>='2008-04-01')&(s.index<='2008-06-30')].mean():.0f}B)")
            except Exception as e:
                print(f"  · [경고] M0 빌더 저장 실패: {e}")
            return s
    print("  · [경고] M0 빌더: 모든 소스 4중검증 실패 → 기존 파일 유지(있으면)")
    return None

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

# ============================================================
# [3. 메인 데이터 빌드]
# ============================================================
def get_data(slice_start=None):
    """slice_start=None → START_DATE로 자름. 날짜 문자열 → 그 날짜로 자름(다중 윈도우용).
       'FULL' → 자르지 않고 워밍업 포함 전체 반환(여러 시작점으로 잘라 쓰기 위함)."""
    print("=" * 100)
    print(f"  [빠른복귀(FAST) + 스마트 BOXX 대기] {START_DATE} ~ {END_DATE}")
    print("=" * 100)

    base_tickers = ['^GSPC', '^NDX', '^IRX']
    raw = yf.download(base_tickers, start=FETCH_START_DATE, end=END_DATE, progress=False)

    def extract(df, p):
        if isinstance(df.columns, pd.MultiIndex):
            if p in df.columns.levels[0]: return df[p]
            elif p in df.columns.levels[1]: return df.xs(p, level=1, axis=1)
        return pd.DataFrame(index=df.index)

    df_close = extract(raw, 'Close')
    df_open = extract(raw, 'Open')
    df_close.index = pd.to_datetime(df_close.index).tz_localize(None).normalize()
    df_open.index = pd.to_datetime(df_open.index).tz_localize(None).normalize()
    close_usd = df_close[~df_close.index.duplicated()].resample('B').ffill()
    open_usd = df_open[~df_open.index.duplicated()].resample('B').ffill()

    tqqq_real_close, tqqq_real_open = (fetch_yf('TQQQ', start=TQQQ_REAL_START)
                                       if pd.to_datetime(END_DATE) > pd.to_datetime(TQQQ_REAL_START) else (None, None))
    qld_real_close, qld_real_open = (fetch_yf('QLD', start=QLD_REAL_START)
                                     if pd.to_datetime(END_DATE) > pd.to_datetime(QLD_REAL_START) else (None, None))
    spy_real_close, spy_real_open = fetch_yf('SPY')
    qqq_real_close, qqq_real_open = fetch_yf('QQQ')

    gold_c, gold_o, gold_src = fetch_gold_intl()
    if gold_c is not None:
        close_usd['GOLD_SRC'] = gold_c.reindex(close_usd.index)
        open_usd['GOLD_SRC'] = (gold_o.reindex(open_usd.index) if gold_o is not None else gold_c.reindex(open_usd.index))
    else:
        close_usd['GOLD_SRC'] = np.nan
        open_usd['GOLD_SRC'] = np.nan

    for col in close_usd.columns: close_usd[col] = close_usd[col].where(close_usd[col] > 0, np.nan).ffill()
    for col in open_usd.columns: open_usd[col] = open_usd[col].where(open_usd[col] > 0, np.nan).ffill()

    irx_yield = close_usd['^IRX'].ffill().bfill() if '^IRX' in close_usd.columns else pd.Series(2.5, index=close_usd.index)
    irx_daily = (irx_yield / 100) / 252
    boxx_px = (1 + irx_daily.fillna(0)).cumprod() * 100

    def back_project(target, proxy, leverage=1.0, annual_drag=0.0):
        if proxy not in close_usd.columns: return
        pxy_c = close_usd[proxy]
        pxy_ret = pxy_c.pct_change().fillna(0)
        if target == 'gold': pxy_ret = pxy_ret.clip(-0.15, 0.15)
        else: pxy_ret = pxy_ret.clip(-0.5, 0.5)
        syn_ret = pxy_ret * leverage - (annual_drag / 252)
        syn_close = (1 + syn_ret).cumprod() * 100.0
        pxy_o = open_usd[proxy]
        gap = (pxy_o / pxy_c.shift(1) - 1).fillna(0)
        gap = gap.clip(-0.15, 0.15) if target == 'gold' else gap.clip(-0.5, 0.5)
        syn_open = syn_close.shift(1) * (1 + gap * leverage)
        close_usd[target] = syn_close
        open_usd[target] = syn_open.fillna(syn_close)

    def splice(target, real_close, real_open, splice_date_str):
        if real_close is None or real_close.empty: return
        real_first = real_close.first_valid_index()
        if real_first is None or real_first not in close_usd.index: return
        syn_at = close_usd.loc[real_first, target]
        real_at = real_close.loc[real_first]
        if pd.isna(syn_at) or pd.isna(real_at) or real_at <= 0: return
        scale = syn_at / real_at
        mask = close_usd.index >= real_first
        close_usd.loc[mask, target] = (real_close * scale).reindex(close_usd.index[mask]).ffill()
        open_usd.loc[mask, target] = ((real_open * scale) if real_open is not None else real_close * scale).reindex(open_usd.index[mask]).ffill()

    back_project('SPY', '^GSPC', 1.0, 0.0)
    splice('SPY', spy_real_close, spy_real_open, '1993-01-29')
    back_project('QQQ', '^NDX', 1.0, 0.0)
    splice('QQQ', qqq_real_close, qqq_real_open, '1999-03-10')
    tqqq_drag = (irx_yield / 100) * 2.0 + 0.0095 + 0.015
    back_project('TQQQ', 'QQQ', 3.0, tqqq_drag)
    splice('TQQQ', tqqq_real_close, tqqq_real_open, TQQQ_REAL_START)
    # ★ QLD(나스닥100 2배) 벤치마크용 합성+스플라이스 (2x → 차입 1x → IRX×1.0)
    qld_drag = (irx_yield / 100) * 1.0 + 0.0095 + 0.015
    back_project('QLD', 'QQQ', 2.0, qld_drag)
    splice('QLD', qld_real_close, qld_real_open, QLD_REAL_START)
    back_project('gold', 'GOLD_SRC', 1.0, 0.0)

    close_usd['BOXX'] = boxx_px
    open_usd['BOXX'] = boxx_px

    # 실제 BOXX 스플라이스 (상장일 2022-12-28 이후는 실데이터, 그 전은 IRX 합성 유지)
    boxx_real_close, boxx_real_open = (fetch_yf('BOXX', start=BOXX_REAL_START)
                                       if pd.to_datetime(END_DATE) > pd.to_datetime(BOXX_REAL_START) else (None, None))
    splice('BOXX', boxx_real_close, boxx_real_open, BOXX_REAL_START)

    # ★ [옵션3] m0_full.csv 자동 빌드: 없거나 / 2008-05 검증실패 / 오래됨이면 임베드 빌더 실행
    m0_path = '/content/drive/MyDrive/m0_full.csv'
    _need_build = True
    if os.path.exists(m0_path):
        try:
            _e = pd.read_csv(m0_path)
            _ev = pd.to_numeric(_e[_e.columns[-1]], errors='coerce')
            _ev.index = pd.to_datetime(_e[_e.columns[0]], errors='coerce')
            _ev = _ev.dropna()
            _seg = _ev[(_ev.index >= '2008-04-01') & (_ev.index <= '2008-06-30')]
            _ok2008 = len(_seg) > 0 and 700 <= _seg.mean() <= 950
            _stale = (pd.Timestamp.today().normalize() - _ev.index.max()).days > M0_STALE_DAYS
            _need_build = (not _ok2008) or _stale
            if _stale:
                print(f"  · M0 파일 오래됨(최신 {_ev.index.max().date()}, {M0_STALE_DAYS}일 초과) → 갱신 시도")
            elif not _ok2008:
                print("  · M0 파일 2008-05 검증 실패 → 재빌드 시도")
        except Exception:
            _need_build = True
    else:
        print("  · m0_full.csv 없음 → 임베드 빌더로 자동 생성 시도")
    if _need_build:
        build_m0_full(m0_path)   # 성공 시 드라이브 저장. 실패해도 기존 유효 파일 있으면 아래 load가 사용.

    m0_col = load_m0_full(m0_path)

    # ★ 수동 M0 입력 (선택): 최신 M0를 직접 지정 → 이 날짜 이후 버블에 반영
    if MANUAL_M0_VALUE is not None:
        _md = pd.to_datetime(MANUAL_M0_DATE) if MANUAL_M0_DATE else (m0_col.index[-1] + pd.Timedelta(days=1))
        m0_col.loc[_md] = float(MANUAL_M0_VALUE)
        m0_col = m0_col.sort_index().resample('B').ffill()
        print(f"  · ★ 수동 M0 적용: {_md.strftime('%Y-%m-%d')} = {float(MANUAL_M0_VALUE):.0f}B "
              f"(이 날짜 이후 버블에 반영)")

    # M0 소스 날짜 표시 (텔레그램 봇처럼: 검증값 + 최신 사용월)
    _m0_chk = m0_col['2008-04-01':'2008-06-30'].mean()
    print(f"  · M0 소스: m0_full.csv | 2008-05 검증={_m0_chk:.0f}B "
          f"| 최신 사용월 {m0_col.index[-1].strftime('%Y-%m')} = {m0_col.iloc[-1]:.0f}B")

    df_usd = pd.DataFrame(index=close_usd.index)
    for col in ['SPY', 'QQQ', 'TQQQ', 'QLD', 'BOXX', 'gold']:
        if col in close_usd.columns:
            df_usd[col] = close_usd[col]
            df_usd[f'{col}_OPEN'] = open_usd[col]
    df_usd['GSPC_RAW'] = close_usd['^GSPC']
    df_usd['SPY_SMA200'] = df_usd['GSPC_RAW'].rolling(200).mean()
    df_usd['NDX_RAW'] = close_usd['^NDX']
    df_usd['NDX_SMA200'] = df_usd['NDX_RAW'].rolling(200).mean()
    df_usd['M0'] = m0_col.reindex(df_usd.index).ffill().bfill()
    df_usd['Bubble_Value'] = df_usd['GSPC_RAW'] / df_usd['M0']

    _need = ['SPY', 'QQQ', 'TQQQ', 'BOXX', 'gold', 'GSPC_RAW', 'SPY_SMA200', 'NDX_RAW', 'NDX_SMA200', 'Bubble_Value']
    if slice_start == 'FULL':
        df_usd = df_usd.dropna(subset=_need)           # 자르지 않고 전체(다중 윈도우용)
    else:
        _sd = slice_start if slice_start else START_DATE
        df_usd = df_usd.loc[_sd:].dropna(subset=_need)
    return df_usd

# ============================================================
# [4. 시뮬레이터]
# ============================================================
def _is_taxable_equity(t):
    return t in ['TQQQ', 'QLD', 'SPY', 'QQQ', 'BOXX']

def _get_slip_comm(t, slip=NORMAL_SLIPPAGE):
    if t == 'BOXX': return 0.0005 + COMMISSION
    if t == 'gold': return slip + 0.003
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

def _calc_tax(hold, eq_p, row):
    latent_eq = 0
    for t, h in hold.items():
        if h['units'] > 0:
            px = _exec_px(row, t)
            if not pd.isna(px) and px > 0:
                sl = _get_slip_comm(t)
                net = px * (1 - sl)
                pr = (net - h['entry_price_usd']) * h['units']
                if _is_taxable_equity(t): latent_eq += pr
    return max(0, eq_p + latent_eq - TAX_EXEMPTION) * TAX_RATE_EQUITY

def run_simulation(df_usd, initial_cap, target_w, port_name="", method='fast_recover',
                   recover_boost=None):
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

            if method == 'fast_recover':
                if state == 'INVESTED':
                    if bub >= BUBBLE_LIMIT and gspc < gsma:
                        pending = 'go_cash'; trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'exit'}

                elif state in ['CASH_USD', 'CASH_BOXX'] and is_month_end:
                    spx_ok = gspc > gsma
                    if bub < BUBBLE_LIMIT:
                        ndx_ok = ndx > nsma
                        if spx_ok or ndx_ok:
                            who = 'S&P+NDX' if (spx_ok and ndx_ok) else ('S&P' if spx_ok else 'NDX')
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'ndx': ndx, 'ndx_sma200': nsma, 'note': f'fast_recover_{who}'}
                    else:
                        if spx_ok:
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'recover_spx_only'}

                    if state == 'CASH_USD' and not pending:
                        pending = 'go_boxx'
                        trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'buy_boxx'}

            elif method == 'boost_until_annual':
                # 원안 fast_recover와 신호 동일. 단, 복귀 트리거가 'NDX 단독'(S&P 아직 200일선 아래)일 때
                # 평상시 비중 대신 부스터 비중(예: 60:40)으로 진입. 환원은 연례 리밸런싱(12/31).
                if state == 'INVESTED':
                    if bub >= BUBBLE_LIMIT and gspc < gsma:
                        pending = 'go_cash'; trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'exit'}
                        is_boosted = False

                elif state in ['CASH_USD', 'CASH_BOXX'] and is_month_end:
                    spx_ok = gspc > gsma
                    if bub < BUBBLE_LIMIT:
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
                        if spx_ok:
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'recover_spx_only'}

                    if state == 'CASH_USD' and not pending:
                        pending = 'go_boxx'
                        trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'buy_boxx'}

        latent = _calc_tax(hold, eq_p, p)
        history.append(max(0, _val(hold, cash, p) - tax_bill - latent))

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

def run_bh_aftertax(df, ic, t):
    px = df[t]
    units = ic / px.iloc[0]
    gross = units * px
    entry = px.iloc[0]
    latent_profit = (px - entry) * units
    tax = (latent_profit - TAX_EXEMPTION).clip(lower=0) * TAX_RATE_EQUITY
    return (gross - tax).clip(lower=0)

def calc_stats(nav, ic):
    days = (nav.index[-1] - nav.index[0]).days
    cagr = (nav.iloc[-1] / ic) ** (365 / days) - 1
    mdd = (nav / nav.cummax() - 1).min()
    vol = nav.pct_change().dropna().std() * np.sqrt(252)
    sharpe = (cagr - RISK_FREE_RATE) / vol if vol > 0 else 0
    return cagr, mdd, sharpe

# ── [표 정렬 유틸] 한글(전각)=2칸으로 계산해 패딩 (칸 어긋남 방지) ──
import unicodedata as _ud
def _dw(s):
    return sum(2 if _ud.east_asian_width(str(c)) in 'WF' else 1 for c in str(s))
def _pad(s, width, align='^'):
    s = str(s); gap = width - _dw(s)
    if gap <= 0: return s
    if align == '>': return ' ' * gap + s
    if align == '<': return s + ' ' * gap
    return ' ' * (gap // 2) + s + ' ' * (gap - gap // 2)

# ── [F1 헬퍼] 포트에 맞는 부스터 비중 생성(B는 gold 금지, hedge=BOXX) ──
def _boost_for(w):
    hedge = 'gold' if 'gold' in w else ('BOXX' if 'BOXX' in w else None)
    tq = RECOVER_BOOST['TQQQ']
    if hedge is None:
        return {'TQQQ': tq}
    return {'TQQQ': tq, hedge: round(1 - tq, 10)}


# ============================================================
# [5. 실행]
# ============================================================

'''

# ============================================================================
#  [임베드 2/2] VR 엔진 (laoer_vr_compare.py, __main__ 제외 · verbatim)
# ============================================================================
_VR_ENGINE_SRC = r'''
# -*- coding: utf-8 -*-
"""라오어 VR v2 (검증용 저장본 — 문서 verbatim의 핵심부)"""
import os, sys, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

FETCH_START = "1985-10-01"
START_DATES = ["1986-08-11", "1994-01-02", "1998-01-02", "2000-01-02", "2010-02-11",
               "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]
END_DATE    = "2026-07-10"
SIGNAL_LAG = 1
RUN_HOLD, RUN_DCA, RUN_WD = "on", "on", "on"
KILLSWITCH = "on"
CHART_ON   = "on"
CHART_MODE = "hold"
CHART_START = "2010-02-11"
def ON(x): return str(x).strip().lower() == "on"

HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT = 100000.0, 0.10, 10, 0.50
DCA_INIT, DCA_MONTHLY, DCA_POOL, DCA_G, DCA_LIMIT = 500.0, 50.0, 0.00, 10, 0.75
WD_CAP, WD_MONTHLY, WD_POOL, WD_G, WD_LIMIT = 100000.0, 300.0, 0.20, 20, 0.25
LUMP_EVENTS = {}
BAND_LOW, BAND_HIGH = 0.85, 1.15
TAX_RATE, TAX_DEDUCTION = 0.22, 250.0
BUBBLE_LIMIT = 1.30
FAST_RECOVER = "on"
SKILL_ON     = "off"
B1_ON    = "on"
B1_PCTL  = 0.75
B1_WIN_Y = 10
VOLTGT_ON       = "off"
VOLTGT_TARGET   = 0.60
VOLTGT_LOOKBACK = 20
TQQQ_DRAG_MULT, TQQQ_DRAG_ADD = 2.0, 0.0095 + 0.015
TQQQ_REAL_START, QQQ_REAL_START = "2010-02-11", "1999-03-10"


def _drive_base():
    if 'google.colab' in sys.modules:
        try:
            from google.colab import drive
            drive.mount('/content/drive')
            return '/content/drive/MyDrive/'
        except Exception:
            return ''
    return ''


def _first(*c):
    return next((x for x in c if x and os.path.exists(x)), None)

def _flat(path, col):
    df = pd.read_csv(path)
    df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df = df.set_index(df.columns[0]).sort_index()
    if col in df.columns:
        return df[col].dropna()
    tail = col.split("|")[-1]
    for c in df.columns:
        if str(c).endswith("|" + tail) or str(c).lower().startswith(tail.lower()):
            return df[c].dropna()
    return None

def get_sources(db):
    ndx = irx = gspc = qqq_real = tqqq_real = m0 = None
    try:
        import yfinance as yf
        def _c(t, s):
            d = yf.download(t, start=s, end=END_DATE, auto_adjust=True, progress=False)["Close"]
            d = d.squeeze() if hasattr(d, "squeeze") else d
            d.index = pd.to_datetime(d.index).tz_localize(None)
            return d.dropna()
        ndx = _c("^NDX", FETCH_START); irx = _c("^IRX", FETCH_START); gspc = _c("^GSPC", FETCH_START)
        qqq_real = _c("QQQ", QQQ_REAL_START); tqqq_real = _c("TQQQ", TQQQ_REAL_START)
        print("  · 지수: yfinance 실시간")
    except Exception as e:
        print(f"  · yfinance 불가({str(e)[:36]}) → 캐시 폴백")
    if ndx is None or gspc is None:
        bp = _first("base_indices.csv", db + "price_cache_base_indices.csv",
                    "price_cache_base_indices.csv")
        if bp:
            ndx = ndx if ndx is not None else _flat(bp, "Close|^NDX")
            irx = irx if irx is not None else _flat(bp, "Close|^IRX")
            gspc = gspc if gspc is not None else _flat(bp, "Close|^GSPC")
            print(f"  · base_indices 캐시: {bp}")
    if qqq_real is None:
        qp = _first("qqq_drive.csv", db + "price_cache_tk_QQQ.csv", "price_cache_tk_QQQ.csv")
        if qp: qqq_real = _flat(qp, "Close|QQQ")
    if tqqq_real is None:
        tp = _first("tqqq_drive.csv", db + "price_cache_tk_TQQQ.csv", "price_cache_tk_TQQQ.csv")
        if tp: tqqq_real = _flat(tp, "Close|TQQQ")
    mp = _first("m0_full.csv", db + "m0_full.csv")
    if mp:
        md = pd.read_csv(mp)
        md.index = pd.to_datetime(md[md.columns[0]])
        m0 = pd.to_numeric(md[md.columns[-1]], errors="coerce").dropna()
    if ndx is None or gspc is None or m0 is None:
        raise RuntimeError("^NDX/^GSPC/M0 확보 실패.")
    return ndx, irx, gspc, qqq_real, tqqq_real, m0


def build_data(db=""):
    ndx, irx, gspc, qqq_real, tqqq_real, m0 = get_sources(db)
    idx = pd.date_range(ndx.index[0], ndx.index[-1], freq="B")
    ndx = ndx.reindex(idx).ffill(); gspc = gspc.reindex(idx).ffill()
    irx = (irx.reindex(idx).ffill().bfill() if irx is not None
           else pd.Series(2.5, index=idx))
    m0 = m0.reindex(idx).ffill().bfill()

    def splice(syn, real, name):
        if real is None or real.empty:
            print(f"  · {name} 실데이터 없음 → 합성만"); return syn
        real = real.reindex(idx).ffill(); rf = real.first_valid_index()
        if rf is None or pd.isna(syn.loc[rf]): return syn
        sc = syn.loc[rf] / real.loc[rf]
        out = syn.copy(); mk = idx >= rf
        out[mk] = (real * sc).reindex(idx[mk]).ffill()
        print(f"  · {name} 스플라이스 @ {rf.date()} (scale {sc:.3f})")
        return out

    qqq = splice((1 + ndx.pct_change().fillna(0).clip(-.5, .5)).cumprod() * 100, qqq_real, "QQQ")
    r_ndx = qqq.pct_change().fillna(0)
    daily_lev = np.where(r_ndx <= -0.3333, -0.99, r_ndx * 3)
    daily_cost = (irx / 100 + 0.0084) / 252
    tqqq_syn = (1 + (pd.Series(daily_lev, index=qqq.index) - daily_cost)).cumprod() * 100
    tqqq = splice(tqqq_syn, tqqq_real, "TQQQ")

    out = pd.DataFrame({"TQQQ": tqqq, "QQQ": qqq, "GSPC": gspc, "NDX": ndx, "IRX": irx,
                        "GSMA": gspc.rolling(200).mean(), "NSMA": ndx.rolling(200).mean(),
                        "BUB": gspc / m0}).dropna()

    w = int(252 * B1_WIN_Y)
    out["BUB_PCTL"] = out["BUB"].rolling(w, min_periods=int(252 * 3)).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)

    tqqq_real_al = tqqq_real.reindex(out.index).ffill() if tqqq_real is not None else None
    ret_syn = out["TQQQ"].pct_change()
    if tqqq_real_al is not None:
        ret_real = tqqq_real_al.pct_change()
        ret_for_rv = ret_real.where(ret_real.notna(), ret_syn)
    else:
        ret_for_rv = ret_syn
    out["RV"] = ret_for_rv.rolling(VOLTGT_LOOKBACK).std() * np.sqrt(252)
    return out


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
    lag = int(SIGNAL_LAG)
    sh = (lambda s: s.shift(lag)) if lag > 0 else (lambda s: s)
    dts = list(d.index)
    me_raw = pd.Series(
        [(i < len(dts) - 1 and dts[i + 1].month != dts[i].month) for i in range(len(dts))],
        index=d.index)
    sig = {
        "G":    sh(d["GSPC"]),
        "GS":   sh(d["GSMA"]),
        "NX":   sh(d["NDX"]),
        "NS":   sh(d["NSMA"]),
        "BU":   sh(d["BUB"]),
        "PCTL": sh(d["BUB_PCTL"]) if "BUB_PCTL" in d.columns else pd.Series(np.nan, index=d.index),
        "RV":   sh(d["RV"]) if "RV" in d.columns else pd.Series(np.nan, index=d.index),
        "ME":   sh(me_raw.astype(float)).fillna(0.0).astype(bool),
    }
    return sig


def _vscale(sig, day):
    if not ON(VOLTGT_ON):
        return 1.0
    rv = sig["RV"].get(day, np.nan)
    if pd.isna(rv) or rv <= 0:
        return 1.0
    return min(1.0, VOLTGT_TARGET / float(rv))


def _exit_sig(sig, dd):
    g = sig["G"].get(dd, np.nan); gs = sig["GS"].get(dd, np.nan)
    if pd.isna(g) or pd.isna(gs) or g >= gs:
        return False
    bub = sig["BU"].get(dd, np.nan)
    if not pd.isna(bub) and bub >= BUBBLE_LIMIT:
        return True
    if ON(B1_ON):
        pc = sig["PCTL"].get(dd, np.nan)
        if not pd.isna(pc) and pc >= B1_PCTL:
            return True
    return False


def _recover_sig(sig, dd):
    if not bool(sig["ME"].get(dd, False)):
        return False
    g = sig["G"].get(dd, np.nan); gs = sig["GS"].get(dd, np.nan)
    if pd.isna(g) or pd.isna(gs):
        return False
    spx_ok = g > gs
    bub = sig["BU"].get(dd, np.nan)
    if not pd.isna(bub) and bub < BUBBLE_LIMIT:
        nx = sig["NX"].get(dd, np.nan); ns = sig["NS"].get(dd, np.nan)
        ndx_ok = (not pd.isna(nx) and not pd.isna(ns) and nx > ns)
        return spx_ok or (ON(FAST_RECOVER) and ndx_ok)
    return spx_ok


def run_vr(d, init_capital, pool_ratio, G, buy_limit, dep=0.0, wd=0.0, killswitch=True):
    px = d["TQQQ"]; flow = dep - wd
    sig = _signals(d)
    stock = init_capital * (1 - pool_ratio); pool = init_capital * pool_ratio
    shares = stock / float(px.iloc[0]); V = shares * float(px.iloc[0])
    cum_in = cum_out = 0.0
    nb = ns = n_exit = n_rec = 0
    daily = []; state = "INVESTED"; cf_on_day = {}
    lumps = sorted((pd.Timestamp(k), float(v)) for k, v in LUMP_EVENTS.items()); li = 0
    while li < len(lumps) and lumps[li][0] < px.index[0]:
        li += 1
    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]])
        while li < len(lumps) and lumps[li][0] <= cd[0] and state == "INVESTED":
            amt = lumps[li][1]; ev0 = shares * p0; total = ev0 + pool
            if total > 0 and V > 0:
                if amt < 0 and -amt >= total:
                    cum_out += total
                    cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) - total
                    shares = pool = 0.0
                    for rdd in px.index[px.index >= cd[0]]:
                        daily.append((rdd, 0.0))
                    li = len(lumps); state = "BUST"; break
                w = ev0 / total; pv = pool / V
                shares += (amt * w) / p0; pool += amt * (1 - w)
                if pool < 0:
                    need = -pool; ss = min(need / p0, shares)
                    shares -= ss; pool += ss * p0
                    if pool < 0: pool = 0.0
                V = (pool / pv) if pv > 1e-12 else (shares * p0 + pool)
                if amt > 0: cum_in += amt
                else: cum_out += -amt
                cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) + amt
            li += 1
        if state == "BUST":
            break
        if wd > 0 and state == "INVESTED" and (shares * p0 + pool) < wd:
            cum_out += max(0.0, shares * p0 + pool)
            shares = pool = 0.0
            for rdd in px.index[px.index >= cd[0]]:
                daily.append((rdd, 0.0))
            break
        if state == "INVESTED":
            pool += flow; cum_in += dep; cum_out += wd
            if flow != 0:
                cf_on_day[cd[0]] = cf_on_day.get(cd[0], 0.0) + flow
            if pool < 0:
                need = -pool; sell_sh = min(need / p0, shares)
                shares -= sell_sh; pool += sell_sh * p0
                if pool < 0: pool = 0.0
        Veff = V * _vscale(sig, cd[0])
        bmin, bmax = Veff * BAND_LOW, Veff * BAND_HIGH
        budget = max(0, pool) * buy_limit; used = 0.0
        for dd in cd:
            p = float(px.loc[dd])
            if killswitch:
                if state == "INVESTED" and _exit_sig(sig, dd):
                    pool += shares * p; shares = 0.0
                    state = "CASH"; n_exit += 1
                    daily.append((dd, pool)); continue
                if state == "CASH" and _recover_sig(sig, dd):
                    buy = min(Veff, pool)
                    shares = buy / p; pool -= buy
                    state = "INVESTED"; n_rec += 1
            if state == "INVESTED":
                ev = shares * p
                if ev < bmin:
                    b = min(bmin - ev, pool, max(0, budget - used))
                    if b > 1e-9:
                        shares += b / p; pool -= b; used += b; nb += 1
                elif ev > bmax:
                    s = ev - bmax
                    if s > 1e-9:
                        shares -= s / p; pool += s; ns += 1
            daily.append((dd, shares * p + pool))
        if state == "INVESTED":
            E = shares * float(px.loc[cd[-1]])
            skill = (E - V) / (2 * np.sqrt(G)) if ON(SKILL_ON) else 0.0
            V = V + pool / G + skill + flow
    dd_ = pd.DataFrame(daily, columns=["d", "t"]).set_index("d")
    mdd = float((dd_.t / dd_.t.cummax() - 1).min())
    nav = float(dd_.t.iloc[-1])
    yrs = (dd_.index[-1] - dd_.index[0]).days / 365.25
    cum = init_capital + cum_in
    result = nav + cum_out
    tax = max(0, result - cum - TAX_DEDUCTION) * TAX_RATE
    at = result - tax
    cagr = (at / cum) ** (1 / yrs) - 1 if at > 0 else float('nan')
    nav_s = dd_.t; prev = nav_s.shift(1)
    cf = pd.Series(0.0, index=nav_s.index)
    for dt, amt in cf_on_day.items():
        if dt in cf.index:
            cf.loc[dt] = amt
    ret = ((nav_s - cf) / prev - 1.0).dropna()
    ret = ret[np.isfinite(ret)]
    rf = float(d["IRX"].reindex(dd_.index).ffill().mean()) / 100.0 if "IRX" in d.columns else 0.0
    sd = ret.std()
    sharpe = ((ret.mean() - rf / 252) / sd * np.sqrt(252)) if sd > 0 else float('nan')
    return dict(yrs=yrs, nav=nav, result=result, aftertax=at, cum=cum, cum_out=cum_out,
                cagr=cagr, mdd=mdd, sharpe=sharpe, nb=nb, ns=ns, n_exit=n_exit, n_rec=n_rec)


def run_hold_bench(px, init_capital, dep=0.0, wd=0.0):
    shares = init_capital / float(px.iloc[0]); cum_in = cum_out = 0.0
    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]])
        if dep > 0: shares += dep / p0; cum_in += dep
        if wd > 0:  shares -= min(wd / p0, shares); cum_out += wd
    nav = shares * float(px.iloc[-1])
    cum = init_capital + cum_in; result = nav + cum_out
    tax = max(0, result - cum - TAX_DEDUCTION) * TAX_RATE
    return result - tax


def _nav_series_vr(d, init, pool_ratio, G, buy_limit, killswitch, dep=0.0, wd=0.0):
    px = d["TQQQ"]; flow = dep - wd
    sig = _signals(d)
    stock = init * (1 - pool_ratio); pool = init * pool_ratio
    shares = stock / float(px.iloc[0]); V = shares * float(px.iloc[0])
    daily = []; state = "INVESTED"
    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]])
        if wd > 0 and state == "INVESTED" and (shares * p0 + pool) < wd:
            for rdd in px.index[px.index >= cd[0]]:
                daily.append((rdd, 0.0))
            break
        if state == "INVESTED":
            pool += flow
            if pool < 0:
                need = -pool; ss = min(need / p0, shares)
                shares -= ss; pool += ss * p0
                if pool < 0: pool = 0.0
        Veff = V * _vscale(sig, cd[0])
        bmin, bmax = Veff * BAND_LOW, Veff * BAND_HIGH
        budget = max(0, pool) * buy_limit; used = 0.0
        for dd in cd:
            p = float(px.loc[dd])
            if killswitch:
                if state == "INVESTED" and _exit_sig(sig, dd):
                    pool += shares * p; shares = 0.0; state = "CASH"
                    daily.append((dd, pool)); continue
                if state == "CASH" and _recover_sig(sig, dd):
                    buy = min(Veff, pool); shares = buy / p; pool -= buy; state = "INVESTED"
            if state == "INVESTED":
                ev = shares * p
                if ev < bmin:
                    b = min(bmin - ev, pool, max(0, budget - used))
                    if b > 1e-9:
                        shares += b / p; pool -= b; used += b
                elif ev > bmax:
                    s = ev - bmax
                    if s > 1e-9:
                        shares -= s / p; pool += s
            daily.append((dd, shares * p + pool))
        if state == "INVESTED":
            E = shares * float(px.loc[cd[-1]])
            skill = (E - V) / (2 * np.sqrt(G)) if ON(SKILL_ON) else 0.0
            V = V + pool / G + skill + flow
    return pd.DataFrame(daily, columns=["d", "t"]).set_index("d")["t"]



'''

# ── 격리 네임스페이스에서 두 엔진 로드(각자의 __main__은 없음) ──
FAST_NS = {'__name__': '_fast_engine'}
exec(compile(_FAST_ENGINE_SRC, '<fast_engine>', 'exec'), FAST_NS)
VR_NS = {'__name__': '_vr_engine'}
exec(compile(_VR_ENGINE_SRC, '<vr_engine>', 'exec'), VR_NS)

# ============================================================================
#  [Phase 0 · 단일 파일] 블렌드 프론티어 오케스트레이션
#  두 엔진(위에 임베드)을 격리 네임스페이스에서 실행 → 세후 NAV → 블렌드.
# ============================================================================
def _phase0_main():
    import os, sys
    import numpy as np
    import pandas as pd

    START = "2010-02-11"
    W_GRID = [0.0, 0.25, 0.50, 0.75, 1.0]
    RISK_FREE_RATE = 0.045
    CRASH_WINDOWS = [("2018 Q4","2018-09-01","2018-12-31"),
                     ("2020 COVID","2020-02-01","2020-04-30"),
                     ("2022 긴축","2021-11-01","2022-12-31")]

    def _dbase():
        if 'google.colab' in sys.modules:
            try:
                from google.colab import drive
                drive.mount('/content/drive'); return '/content/drive/MyDrive/'
            except Exception:
                return ''
        return ''
    DB = _dbase()

    print("=" * 100)
    print("  [Phase 0.5 · 단일파일] 프론티어 + 세금경계 + 롤링강건성")
    print("=" * 100)

    # ---- FAST NAV (부스터B A(gold), fresh START, 세후) ----
    print("\n▶ FAST 엔진 실행 (부스터B A(gold), fresh %s)..." % START)
    _fget = FAST_NS['get_data']; _frun = FAST_NS['run_simulation']
    _FIC = FAST_NS['INITIAL_CAPITAL']; _FWA = FAST_NS['W_A']; _FEND = FAST_NS.get('END_DATE', None)
    df_full = _fget('FULL')
    dff = df_full.loc[START:]
    if _FEND: dff = dff[dff.index <= _FEND]
    nav_fast, _ = _frun(dff, _FIC, _FWA, method='boost_until_annual')
    nav_fast = nav_fast[nav_fast > 0].copy(); nav_fast.name = 'FAST'
    print("  · FAST NAV: %s~%s (%d행), 최종 %s" %
          (nav_fast.index[0].date(), nav_fast.index[-1].date(), len(nav_fast), format(nav_fast.iloc[-1], ",.0f")))

    # ---- VR NAV (거치식 VR+KS, fresh START) : 세전경로 → FAST와 동일 잠재세 차감 ----
    print("\n▶ VR 엔진 실행 (거치식 VR+KS, fresh %s)..." % START)
    _vbuild = VR_NS['build_data']; _vnav = VR_NS['_nav_series_vr']; _vrun = VR_NS['run_vr']
    _VON = VR_NS['ON']
    _HC, _HP, _HG, _HL = VR_NS['HOLD_CAP'], VR_NS['HOLD_POOL'], VR_NS['HOLD_G'], VR_NS['HOLD_LIMIT']
    _KS = VR_NS['KILLSWITCH']; _TR = VR_NS['TAX_RATE']; _TD = VR_NS['TAX_DEDUCTION']
    _VEND = VR_NS.get('END_DATE', None)
    dfv = _vbuild(DB)
    sub = dfv[dfv.index >= START]
    if _VEND: sub = sub[sub.index <= _VEND]
    nav_pre = _vnav(sub, _HC, _HP, _HG, _HL, killswitch=_VON(_KS))
    gain = nav_pre - _HC
    tax = (gain - _TD).clip(lower=0) * _TR
    nav_vr = (nav_pre - tax).clip(lower=0); nav_vr = nav_vr[nav_vr > 0].copy(); nav_vr.name = 'VR'
    try:
        _r = _vrun(sub, _HC, _HP, _HG, _HL, killswitch=_VON(_KS))
        print("  · VR 세후 정합: 변환최종=%s vs run_vr.aftertax=%s (대피 %d회)" %
              (format(nav_vr.iloc[-1], ",.0f"), format(_r['aftertax'], ",.0f"), _r['n_exit']))
    except Exception as e:
        print("  · [경고] VR 정합 확인 생략:", e)
    print("  · VR NAV: %s~%s (%d행), 최종 %s" %
          (nav_vr.index[0].date(), nav_vr.index[-1].date(), len(nav_vr), format(nav_vr.iloc[-1], ",.0f")))

    # ---- 블렌드 코어 ----
    def align_and_norm(a, b):
        df = pd.concat([a.rename('VR'), b.rename('FAST')], axis=1).dropna()
        if len(df) < 250: raise RuntimeError("공통구간 부족(%d행)" % len(df))
        return df / df.iloc[0]
    def blend_bh(df, w): return w*df['VR'] + (1-w)*df['FAST']
    def blend_rebal(df, w):
        ra = df['VR'].pct_change().fillna(0.0).values; rb = df['FAST'].pct_change().fillna(0.0).values
        idx = df.index; ba, bb = w, 1.0-w; out = np.empty(len(idx))
        for i in range(len(idx)):
            ba *= (1+ra[i]); bb *= (1+rb[i]); total = ba+bb; out[i] = total
            if i < len(idx)-1 and idx[i].year != idx[i+1].year: ba, bb = total*w, total*(1-w)
        return pd.Series(out, index=idx)
    def stats(nav, rf=RISK_FREE_RATE):
        days = (nav.index[-1]-nav.index[0]).days
        cagr = (nav.iloc[-1]/nav.iloc[0])**(365.0/days)-1 if days>0 else 0.0
        mdd = (nav/nav.cummax()-1).min(); dr = nav.pct_change().dropna()
        vol = dr.std()*np.sqrt(252); down = dr[dr<0]
        dd = down.std()*np.sqrt(252) if len(down)>1 else np.nan
        sharpe = (cagr-rf)/vol if vol>0 else np.nan
        sortino = (cagr-rf)/dd if (dd is not None and dd>0) else np.nan
        return dict(cagr=cagr, mdd=mdd, vol=vol, sharpe=sharpe, sortino=sortino, final=nav.iloc[-1])
    def crash_mdd(nav, s, e):
        seg = nav.loc[(nav.index>=s)&(nav.index<=e)]
        if len(seg) < 5: return None
        seg = seg/seg.iloc[0]; return (seg/seg.cummax()-1).min()

    df = align_and_norm(nav_vr, nav_fast)
    sd, ed = df.index[0].date(), df.index[-1].date()
    yrs = (df.index[-1]-df.index[0]).days/365.25
    print("\n" + "=" * 100)
    print("  [Phase 0] 블렌드 프론티어 | 공통구간 %s ~ %s (%.1f년, %d행)" % (sd, ed, yrs, len(df)))
    print("  w = VR 비중 (1-w = FAST). 0=순수FAST · 1=순수VR. 둘 다 세후·fresh %s 시작" % START)
    print("=" * 100)

    rows = []
    for w in W_GRID:
        for mode, nav in [('BH', blend_bh(df, w)), ('Rebal', blend_rebal(df, w))]:
            rows.append(dict(w=w, mode=mode, **stats(nav)))
    fr = pd.DataFrame(rows)
    def _f(v, pct=True):
        if pd.isna(v): return "   n/a"
        return ("%7.2f%%" % (v*100)) if pct else ("%7.2f" % v)
    for mode in ['BH', 'Rebal']:
        tag = '무리밸런싱(독립계좌·세후)' if mode=='BH' else '연례리밸런싱(★낙관: 리밸비용 미반영)'
        print("\n  ── [%s] %s ──" % (mode, tag))
        print("  %10s | %8s | %8s | %8s | %7s | %7s | %9s" %
              ('w(VR)','CAGR','MDD','Vol','Sharpe','Sortino','최종배수'))
        print("  " + "-"*82)
        for _, r in fr[fr['mode']==mode].sort_values('w').iterrows():
            lbl = ("%.2f" % r['w']) + (" (FAST)" if r['w']==0 else " (VR)" if r['w']==1 else "")
            print("  %10s | %s | %s | %s | %7s | %7s | %7.2fx" %
                  (lbl, _f(r['cagr']), _f(r['mdd']), _f(r['vol']),
                   _f(r['sharpe'],False), _f(r['sortino'],False), r['final']))

    print("\n" + "=" * 100)
    print("  🔬 저버블 크래시창 MDD (BH 블렌드) — Phase 1(gold 통합)이 겨눌 표적")
    print("     ※ MDD는 경로의존 → w에 단조 아닐 수 있음. 끝점 순서와 최소점 위치를 볼 것.")
    print("=" * 100)
    crows = []
    hdr = "  %10s |" % '창' + "".join([" w=%.2f |" % w for w in W_GRID])
    print(hdr); print("  " + "-"*(len(hdr)-2))
    for cn, cs, ce in CRASH_WINDOWS:
        line = "  %10s |" % cn
        for w in W_GRID:
            m = crash_mdd(blend_bh(df, w), cs, ce); crows.append(dict(window=cn, w=w, mdd=m))
            line += (" %6.1f%%|" % (m*100)) if m is not None else "   n/a |"
        print(line)
    print("  " + "-"*(len(hdr)-2))
    print("  · 값이 0에 가까울수록 낙폭 얕음. FAST 비중↑(w↓)에서 얕아지면 gold 완충 작동.")

    fr.to_csv('phase0_frontier.csv', index=False)
    pd.DataFrame(crows).to_csv('phase0_crash_mdd.csv', index=False)
    df.rename(columns={'VR':'VR_norm','FAST':'FAST_norm'}).to_csv('phase0_navs.csv')
    print("\n  저장: phase0_frontier.csv · phase0_crash_mdd.csv · phase0_navs.csv")

    # 차트
    try:
        import matplotlib
        in_nb = ('google.colab' in sys.modules)
        if not in_nb: matplotlib.use('Agg')
        import matplotlib.pyplot as plt, glob
        from matplotlib import font_manager
        fp = None
        for pat in ["NanumGothic.ttf","/usr/share/fonts/truetype/nanum/*.ttf","/usr/share/fonts/**/NotoSansCJK*.otf"]:
            h = glob.glob(pat, recursive=True)
            if h: fp = h[0]; break
        if fp:
            font_manager.fontManager.addfont(fp)
            plt.rcParams['font.family'] = font_manager.FontProperties(fname=fp).get_name()
        plt.rcParams['axes.unicode_minus'] = False
        fig, ax = plt.subplots(figsize=(10,7))
        for mode, mk, cl in [('BH','o-','crimson'),('Rebal','s--','steelblue')]:
            s2 = fr[fr['mode']==mode].sort_values('w')
            ax.plot(s2['mdd']*100, s2['cagr']*100, mk, color=cl, lw=1.6, label='%s 블렌드' % mode)
            for _, r in s2.iterrows():
                ax.annotate("w=%.2f" % r['w'], (r['mdd']*100, r['cagr']*100),
                            textcoords="offset points", xytext=(6,4), fontsize=8, color=cl)
        pf = fr[(fr['w']==0)&(fr['mode']=='BH')].iloc[0]; pv = fr[(fr['w']==1)&(fr['mode']=='BH')].iloc[0]
        ax.scatter([pf['mdd']*100],[pf['cagr']*100], s=120, color='green', zorder=5, label='순수 FAST')
        ax.scatter([pv['mdd']*100],[pv['cagr']*100], s=120, color='black', zorder=5, label='순수 VR')
        ax.set_xlabel('MDD (%)  ← 깊음    얕음 →'); ax.set_ylabel('CAGR (%)')
        ax.set_title('Phase 0 블렌드 프론티어 (%s~%s)\nPhase 1은 이 선의 위-왼쪽에 앉아야 통합 정당' % (sd, ed))
        ax.legend(loc='best'); ax.grid(True, alpha=0.3); plt.tight_layout()
        plt.savefig('phase0_frontier.png', dpi=120, bbox_inches='tight'); print("  차트: phase0_frontier.png")
        if in_nb:
            try: plt.show()
            except Exception: pass
        plt.close()
    except Exception as e:
        print("  [차트 생략]", e)

    print("\n" + "=" * 100)
    print("  판정: Phase 1(gold 통합)의 V1/V2가 위 BH 프론티어의 '위-왼쪽'에 유의미하게")
    print("        앉지 못하면 → 통합 무의미. 그냥 이 블렌드를 쓰는 게 더 단순·투명.")
    print("  · 1차 기준은 BH(세금 정합 완전). Rebal은 리밸비용 뺀 낙관 기준선.")
    print("=" * 100)

    # ========================================================================
    # [정밀 세금 경계] 별도 계좌 2개 — 리밸이 세금 내고도 BH보다 나은가
    #   하한(무세금 Rebal) ↔ 상한(최악세금 Rebal, 원가=최초납입) 사이에 BH 위치 판정.
    #   최악세금: 매년 승자계좌 매도분 실현이익에 22%(공제 2.5M KRW≈1724$/계좌).
    # ========================================================================
    INIT = 100000.0; EX = 1724.0; RATE = 0.22
    def _ye(idx): return [(i < len(idx)-1 and idx[i].year != idx[i+1].year) for i in range(len(idx))]
    def blend_rebal_taxed(dfn, w):
        ra = dfn['VR'].pct_change().fillna(0).values; rb = dfn['FAST'].pct_change().fillna(0).values
        idx = dfn.index; ye = _ye(idx)
        av=w*INIT; ab=w*INIT; fv=(1-w)*INIT; fb=(1-w)*INIT
        out = np.empty(len(idx)); taxc = 0.0
        for i in range(len(idx)):
            av*=(1+ra[i]); fv*=(1+rb[i]); total=av+fv; out[i]=total
            if ye[i] and 0 < w < 1:
                a_tgt = w*total
                if av > a_tgt:
                    sell=av-a_tgt; frac=sell/av if av>0 else 0.0
                    gain=sell-ab*frac; tax=max(0.0,gain-EX)*RATE; taxc+=tax
                    ab-=ab*frac; av-=sell; net=sell-tax; fv+=net; fb+=net
                elif fv > (1-w)*total:
                    sell=fv-(1-w)*total; frac=sell/fv if fv>0 else 0.0
                    gain=sell-fb*frac; tax=max(0.0,gain-EX)*RATE; taxc+=tax
                    fb-=fb*frac; fv-=sell; net=sell-tax; av+=net; ab+=net
        return pd.Series(out, index=idx), taxc

    print("\n" + "=" * 100)
    print("  🔬 [정밀 세금 경계] 별도 계좌 2개 — 리밸이 세금 내고도 BH보다 나은가")
    print("     하한=무세금Rebal(낙관) · 상한세금=최악(원가 최초납입, 보수적) · BH=리밸안함")
    print("=" * 100)
    print("  %10s | %20s | %20s | %20s" % ('w(VR)','BH(리밸X)','Rebal 무세금(하한)','Rebal 최악세금(보수)'))
    print("  %10s | %9s %9s | %9s %9s | %9s %9s" % ('','CAGR','MDD','CAGR','MDD','CAGR','MDD'))
    print("  " + "-"*76)
    tax_summary = []
    for w in W_GRID:
        bh = blend_bh(df, w); rfree = blend_rebal(df, w)
        rtax, taxc = blend_rebal_taxed(df, w)
        s_bh = stats(bh); s_rf = stats(rfree); s_rt = stats(rtax/rtax.iloc[0])
        tax_summary.append(dict(w=w, bh_cagr=s_bh['cagr'], bh_mdd=s_bh['mdd'],
                                rf_cagr=s_rf['cagr'], rt_cagr=s_rt['cagr'], rt_mdd=s_rt['mdd'], taxc=taxc))
        lbl = ("%.2f"%w)+(" (FAST)" if w==0 else " (VR)" if w==1 else "")
        print("  %10s | %8.1f%% %8.1f%% | %8.1f%% %8.1f%% | %8.1f%% %8.1f%%" %
              (lbl, s_bh['cagr']*100, s_bh['mdd']*100, s_rf['cagr']*100, s_bh['mdd']*100,
               s_rt['cagr']*100, s_rt['mdd']*100))
    print("  " + "-"*76)
    # 판정: 최악세금 Rebal이 여전히 BH보다 위-왼쪽인 w가 있는가
    verdict = "불명확(정밀 원가추적 필요)"
    for t in tax_summary:
        if 0 < t['w'] < 1:
            better_cagr = t['rt_cagr'] > tax_summary[0]['bh_cagr']  # vs 순수 FAST BH
            shallower = t['rt_mdd'] > tax_summary[-1]['bh_mdd']     # vs 순수 VR MDD
    # 간단 판정 로직
    rt_beats_bh = any((t['rt_cagr'] >= tax_summary[int(t['w']*0)]['bh_cagr']) for t in tax_summary if 0<t['w']<1)
    print("  · 해석: 최악세금 Rebal(보수적 하한)이 BH 프론티어를 여전히 넘으면 → 리밸 채택 강건.")
    print("         넘지 못하면 → BH(리밸 안 함)가 별도계좌 2개에선 사실상 정답.")
    print("  · 진실은 [무세금 하한 ~ 최악세금 상한] 사이. 둘 다 BH보다 나으면 리밸, 둘 다 못하면 BH.")

    # ========================================================================
    # [롤링 7년창 강건성] 스윗스팟이 창마다 일관된가 (BH 기준, 실제 채택가능 전략)
    #   엔진은 위에서 1회만 실행 → 여기선 NAV 슬라이싱만(가벼움).
    # ========================================================================
    def _rolling_windows(idx, years=7):
        starts=[]; seen=set()
        for ts in idx:
            key=(ts.year, ts.month)
            if key in seen: continue
            seen.add(key)
            end = ts + pd.DateOffset(years=years)
            if end <= idx[-1]: starts.append((ts, end))
        return starts
    wins = _rolling_windows(df.index, 7)
    print("\n" + "=" * 100)
    print("  🔬 [롤링 7년창 강건성] BH 기준 — 스윗스팟이 창마다 일관된가 (%d개 창)" % len(wins))
    print("     엔진 1회 실행 → NAV 슬라이싱. 각 창 재베이스 후 w별 BH 성과.")
    print("=" * 100)
    import collections
    best_w=[]; rrows=[]
    for s, e in wins:
        sub = df.loc[(df.index>=s)&(df.index<=e)]
        if len(sub) < 250: continue
        sub = sub/sub.iloc[0]; shs={}
        for w in W_GRID:
            st = stats(blend_bh(sub, w)); rrows.append((w, st['cagr'], st['mdd'], st['sharpe'])); shs[w]=st['sharpe']
        best_w.append(max(shs, key=shs.get))
    hist = collections.Counter(best_w)
    print("  [최적 w 히스토그램] 창별 Sharpe 최대 w — 특정 w에 몰리면 그게 강건한 스윗스팟")
    for w in W_GRID:
        print("    w=%.2f: %3d창  %s" % (w, hist.get(w,0), '█'*hist.get(w,0)))
    rdf = pd.DataFrame(rrows, columns=['w','cagr','mdd','sharpe'])
    print("\n  [w별 롤링 분포] 중앙값 (25%%~75%% 사분위)")
    print("    %5s | %22s | %22s | %18s" % ('w','CAGR','MDD','Sharpe'))
    for w in W_GRID:
        g = rdf[rdf['w']==w]
        print("    %5.2f | %6.1f%% (%5.1f~%5.1f) | %6.1f%% (%6.1f~%5.1f) | %5.2f (%4.2f~%4.2f)" %
              (w, g['cagr'].median()*100, g['cagr'].quantile(.25)*100, g['cagr'].quantile(.75)*100,
               g['mdd'].median()*100, g['mdd'].quantile(.25)*100, g['mdd'].quantile(.75)*100,
               g['sharpe'].median(), g['sharpe'].quantile(.25), g['sharpe'].quantile(.75)))
    print("  " + "-"*72)
    print("  · 최적 w가 한두 값에 몰리면 → 그 비중이 기간에 강건한 스윗스팟.")
    print("  · Sharpe 중앙값이 중간 w에서 최고면 → 다각화가 표본 전반에서 실재(1개 표본 착시 아님).")
    pd.DataFrame(tax_summary).to_csv('phase05_tax_bounds.csv', index=False)
    rdf.to_csv('phase05_rolling.csv', index=False)
    print("\n  저장: phase05_tax_bounds.csv · phase05_rolling.csv")

    return fr

if __name__ == "__main__":
    _phase0_main()
