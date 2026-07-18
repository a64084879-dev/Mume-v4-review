# ------------------------------------------------------------
# [빠른복귀(FAST) + 스마트 BOXX 진입 백테스트] - 버그 수정 완료
#  + QLD(나스닥100 2배) 벤치마크 비교 라인 추가 (SPY/QQQ와 동일 방식)
#
#  ★ [핵심 로직: 스마트 BOXX 진입 & 최소 스왑]
#      1. 대피 신호 발생 시: TQQQ만 매도하고 순수 달러(USD) 현금으로 대기. (비용 0%)
#      2. 첫 번째 월말 복귀 판정일:
#         - 복귀 조건 충족(휩소): 현금으로 바로 TQQQ 재매수. (BOXX 왕복 수수료 방어!)
#         - 복귀 조건 미충족(진짜 하락장): 대기하던 현금만 BOXX로 매수. (금은 절대 건드리지 않음)
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
from google.colab import drive
drive.mount('/content/drive')
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
# (M0는 월간 데이터라 보통 1개월 지연 → 75일이면 갓 만든 파일은 갱신 안 하고, 진짜 낡은 것만 갱신)
M0_STALE_DAYS = 75

# ============================================================
# [복귀규칙 비교] (선택, 백테스트 비교용 — 실전 봇과 무관)
#   split_recover 방식: '대피 시점의 버블'에 따라 복귀 방식을 분기한다.
# ============================================================
# [복귀규칙: split (신중복귀)] — 보험용 보관 (상시 채택 아님)
#   목적: 닷컴급 초거품(버블 2.0+)에서 대피했을 때, 어설픈 반등에 복귀하지 않고
#         거품이 빠질 때까지 기다렸다 복귀. 2000 닷컴 구간에서 −39%를 +8%로 방어.
#   [중요] 다중윈도우상 닷컴 안 오는 시작점(1986/1995)에선 −2.5~3.3%p (시작점 편향).
#          → 상시 켜면 손해. '버블 2.0+ 초거품이 실제로 오면' 그때 고려하는 카드로만 보관.
#   동작: 대피 시점 버블 ≥ 임계 → 신중복귀(고버블 대피) / < 임계 → 빠른복귀.
#         신중복귀 출구(B-2, 새 숫자 없음): 버블<1.30 또는 '버블이 대피 때보다 낮아짐+S&P회복'.
# ============================================================
BUBBLE_FAST_THRESHOLD = 2.0                 # split 기본 임계값 (닷컴급 2.0 권장)
SPLIT_THRESHOLDS = [1.5, 2.0, 2.5, 99.0]    # 비교 스윕 (99=사실상 '항상 신중')


# ★ 복귀 부스터: 빠른복귀(버블<1.30, NDX/S&P 중 먼저 200일선 회복) 진입 순간의 비중.
#   평상시 W_A와 별개로 자유 조절. 재원은 금에서 뺌(TQQQ↑, gold↓).
#   환원: method A=S&P 200일선 확정 시 / method B=연례 리밸런싱 시 → 평상시 W_A로 복귀.
RECOVER_BOOST = {'TQQQ': 0.60, 'gold': 0.40}

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
       통과분만 path에 저장. 성공 시 시리즈 반환, 전 소스 실패 시 None(기존 파일 안 건드림).
       → get_data가 '파일 없음/검증실패/오래됨'일 때 자동 호출한다."""
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

    # 실제 BOXX 스플라이스 (상장일 2022-12-28 이후는 실데이터 사용, 그 전은 IRX 합성 유지)
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
                   bubble_fast_threshold=BUBBLE_FAST_THRESHOLD,
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
    exit_bubble = None   # split: 대피 시점의 버블(복귀 방식 분기용)
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
                cash -= min(tax_bill, cash)
                tax_bill = 0
                executed = True

        if pending and not executed and not is_last:
            if pending == 'go_cash': astr = '대피(USD대기)'
            elif pending == 'go_boxx': astr = '대피(BOXX전환)'
            elif pending.startswith('go_invest'):
                astr = '복귀(부스터60:40)' if (is_boosted and pending_aw is not None) else '복귀'
            else: astr = pending

            logs.append({'실행일': cd.strftime('%Y-%m-%d'), '액션': astr, '종류': trig.get('note', ''),
                         '버블': round(trig.get('bubble', 0), 4), 'GSPC': round(trig.get('gspc', 0), 2)})

            if pending == 'go_cash':
                _sell_all('TQQQ', p)
                state = 'CASH_USD'
            elif pending == 'go_boxx':
                _buy_amt('BOXX', cash, p) # 🟢 버그 수정: 금을 건드리지 않고 달러(cash)만 BOXX로 전액 매수
                state = 'CASH_BOXX'
            elif pending == 'go_invest_from_usd':
                note = trig.get('note', '')
                if pending_aw is not None:                     # 부스터B: NDX 단독복귀 시 부스터 비중(60:40)으로 재진입
                    _rebalance(pending_aw, p); pending_aw = None
                elif note.startswith('fast_recover'):
                    _rebalance(base_w, p)
                else:
                    _buy_amt('TQQQ', cash, p)
                state = 'INVESTED'
            elif pending == 'go_invest_from_boxx':
                note = trig.get('note', '')
                if pending_aw is not None:                     # 부스터B: NDX 단독복귀 시 부스터 비중(60:40)으로 재진입
                    _rebalance(pending_aw, p); pending_aw = None
                elif note.startswith('fast_recover'):
                    _rebalance(base_w, p)
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
                aw = base_w.copy()
                aw['TQQQ'] = 0
                aw['BOXX'] = 0
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

            elif method == 'split_recover':
                # 대피는 fast_recover와 동일. 복귀만 '대피 시점 버블'로 분기.
                # [의도] 높은 거품에서 대피했으면 신중복귀(거품 빠질 때까지 기다림),
                #        낮은 거품에서 대피했으면 그냥 빠른복귀.
                if state == 'INVESTED':
                    if bub >= BUBBLE_LIMIT and gspc < gsma:
                        pending = 'go_cash'; trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'exit'}
                        exit_bubble = bub   # ★ 대피 시점 버블 기록

                elif state in ['CASH_USD', 'CASH_BOXX'] and is_month_end:
                    # 대피 버블이 임계 미만 = 저버블 대피 → 빠른복귀 / 임계 이상 = 고버블 대피 → 신중복귀
                    use_fast = (exit_bubble is None or exit_bubble < bubble_fast_threshold)
                    spx_ok = gspc > gsma
                    if use_fast:
                        # ── 저버블 대피 → 기존 빠른복귀와 100% 동일 ──
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
                    else:
                        # ── 고버블 대피 → 신중복귀 ──
                        # 출구(B-2, 새 숫자 없음): 둘 중 하나면 복귀.
                        #   ① 버블<1.30 (거품 완전히 빠짐) + S&P/NDX 200일선 회복
                        #   ② 버블이 대피 시점보다 낮아짐(거품 줄어듦) + S&P 200일선 회복
                        #      → ②가 흡수상태(1.30 안 와도 영원히 갇힘)를 막는 탈출구.
                        if bub < BUBBLE_LIMIT:
                            ndx_ok = ndx > nsma
                            if spx_ok or ndx_ok:
                                who = 'S&P+NDX' if (spx_ok and ndx_ok) else ('S&P' if spx_ok else 'NDX')
                                pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                                trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'ndx': ndx, 'ndx_sma200': nsma, 'note': f'slow_recover_{who}'}
                        elif (exit_bubble is not None and bub < exit_bubble and spx_ok):
                            pending = 'go_invest_from_usd' if state == 'CASH_USD' else 'go_invest_from_boxx'
                            trig = {'gspc': gspc, 'sma200': gsma, 'bubble': bub, 'note': 'slow_recover_degear'}
                        # else: 복귀 안 함 (거품이 대피 때보다 줄지도, 1.30 아래로도 안 옴 → 계속 대기)

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

# ============================================================
# [5. 실행]
# ============================================================
if __name__ == "__main__":
    df = get_data()

    for nm, w in [("A(gold)", W_A), ("B(BOXX)", W_B)]:
        s = sum(w.values())
        if abs(s - 1.0) > 1e-6:
            print(f"  [경고] 포트 {nm} 비중 합 = {s:.2f} (1.00 아님 → 나머지는 미투자 현금)")

    configs = [
        ("FAST + gold(비과세)",  'fast_recover', W_A),
        ("FAST + BOXX(양도세)",  'fast_recover', W_B),
    ]

    results = {}
    for name, m, w in configs:
        print(f"\n▷ {name} 시뮬레이션...")
        nav, log = run_simulation(df, INITIAL_CAPITAL, w, name, method=m)
        results[name] = (nav, log)

    nav_spy = run_bh_aftertax(df, INITIAL_CAPITAL, 'SPY')
    nav_qqq = run_bh_aftertax(df, INITIAL_CAPITAL, 'QQQ')
    nav_qld = run_bh_aftertax(df, INITIAL_CAPITAL, 'QLD')   # ★ QLD(2x) 벤치마크 추가

    def stats_line(nav, log):
        c, m, s = calc_stats(nav, INITIAL_CAPITAL)
        n_daepi = int((log['액션'] == '대피(USD대기)').sum()) if not log.empty else 0
        n_trade = len(log)
        return nav.iloc[-1], c, m, s, n_daepi, n_trade

    first_nav = list(results.values())[0][0]
    yrs = round((first_nav.index[-1] - first_nav.index[0]).days / 365.25, 1)
    sd = first_nav.index[0].strftime('%Y-%m-%d')
    ed = first_nav.index[-1].strftime('%Y-%m-%d')

    print("\n" + "=" * 104)
    print(f"  📊 스마트 대기 + FAST — A(gold) vs B(BOXX) ({sd} ~ {ed}, {yrs}년)")
    print(f"  자산: gold=KRX금현물(비과세), BOXX=박스스프레드(양도세, 단기채복제) / SPY·QQQ·QLD 세후")
    print("=" * 104)
    print(f"{'방식':^24} | {'최종자산($)':^16} | {'CAGR':^8} | {'MDD':^8} | {'샤프':^6} | {'대피수':^6} | {'총매매':^6}")
    print("-" * 104)
    for name, _, _ in configs:
        nav, log = results[name]
        fin, c, m, s, nd, nt = stats_line(nav, log)
        print(f"{name:^24} | {fin:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {nd:>6} | {nt:>6}")

    for bname, bnav in [("SPY(세후, 참고)", nav_spy), ("QQQ(세후, 참고)", nav_qqq), ("QLD(세후, 참고)", nav_qld)]:
        c, m, s = calc_stats(bnav, INITIAL_CAPITAL)
        print(f"{bname:^24} | {bnav.iloc[-1]:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {'-':>6} | {'-':>6}")
    print("=" * 104)

    a_fin = results["FAST + gold(비과세)"][0].iloc[-1]
    b_fin = results["FAST + BOXX(양도세)"][0].iloc[-1]
    diff = a_fin - b_fin
    ratio = (a_fin / b_fin - 1) * 100 if b_fin > 0 else 0
    print(f"\n  ▶ A(gold) − B(BOXX) = {diff:>+,.0f}  ({ratio:+.1f}%)")
    print(f"    {'A(gold) 우세' if diff > 0 else 'B(BOXX) 우세'}")

    # ============================================================
    # [5b. 복귀규칙 비교] 대피 시점 버블에 따라 빠른복귀 vs 신중복귀(버블<1.30) 분기
    #   A(gold) 기준으로, 현재(빠른복귀) vs split(여러 임계값)을 나란히 비교.
    #   split: 대피버블 ≥ 임계값 → 기존 빠른복귀 / 미만 → 버블<1.30에서만 복귀
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [복귀규칙 비교] A(gold) 기준 — '대피 시점 버블'로 복귀 방식 분기 효과")
    print("     split: 대피버블 ≥ 임계값이면 기존 빠른복귀, 미만이면 버블<1.30 아래로 와야만 복귀")
    print("=" * 104)
    print(f"{'복귀규칙':^30} | {'최종자산($)':^16} | {'CAGR':^8} | {'MDD':^8} | {'샤프':^6} | {'대피수':^6} | {'총매매':^6}")
    print("-" * 104)
    _bnav, _blog = results["FAST + gold(비과세)"]
    _bc, _bm, _bs = calc_stats(_bnav, INITIAL_CAPITAL)
    _bnd = int((_blog['액션'] == '대피(USD대기)').sum()) if not _blog.empty else 0
    print(f"{'현재(빠른복귀, 기준)':^30} | {_bnav.iloc[-1]:>16,.0f} | {_bc*100:>7.2f}% | {_bm*100:>7.2f}% | {_bs:>6.2f} | {_bnd:>6} | {len(_blog):>6}")
    for _thr in SPLIT_THRESHOLDS:
        _nav, _log = run_simulation(df, INITIAL_CAPITAL, W_A, f"split_{_thr}",
                                    method='split_recover', bubble_fast_threshold=_thr)
        _c, _m, _s = calc_stats(_nav, INITIAL_CAPITAL)
        _nd = int((_log['액션'] == '대피(USD대기)').sum()) if not _log.empty else 0
        _tag = (f"split 임계={_thr:g} (항상신중)" if _thr >= 90 else f"split 임계={_thr:g}")
        print(f"{_tag:^30} | {_nav.iloc[-1]:>16,.0f} | {_c*100:>7.2f}% | {_m*100:>7.2f}% | {_s:>6.2f} | {_nd:>6} | {len(_log):>6}")
    print("=" * 104)
    print("  · '항상신중'은 모든 대피를 버블<1.30 복귀로 처리 → 박사님 원안(복귀를 버블1.30 이하로만)에 해당")

    # ============================================================
    # [5f. 복귀 부스터] 빠른복귀(NDX 단독, S&P 아직 200일선 아래) 진입 시 TQQQ 더 싣기
    #   A=S&P 200일선 회복 시 환원 / B=연례 리밸런싱 시 환원. 재원은 금에서.
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [복귀 부스터B] A(gold) 기준 — NDX 단독 빠른복귀 진입 순간 TQQQ↑(금↓)로 부스터")
    print(f"     평상시 {int(W_A['TQQQ']*100)}:{int(W_A['gold']*100)} → 부스터 {int(RECOVER_BOOST['TQQQ']*100)}:{int(RECOVER_BOOST['gold']*100)} "
          f"(NDX 단독복귀 시만). 환원: 연 1회 리밸런싱(12/31). ★채택")
    print("=" * 104)
    print(f"{'방식':^26} | {'최종자산($)':^16} | {'CAGR':^8} | {'MDD':^8} | {'샤프':^6} | {'대피수':^6} | {'총매매':^6}")
    print("-" * 104)
    print(f"{'현재(부스터 없음, 기준)':^26} | {_bnav.iloc[-1]:>16,.0f} | {_bc*100:>7.2f}% | {_bm*100:>7.2f}% | {_bs:>6.2f} | {_bnd:>6} | {len(_blog):>6}")
    _nav, _log = run_simulation(df, INITIAL_CAPITAL, W_A, '부스터B(연례환원)', method='boost_until_annual')
    _c, _m, _s = calc_stats(_nav, INITIAL_CAPITAL)
    _nd = int((_log['액션'] == '대피(USD대기)').sum()) if not _log.empty else 0
    _nboost = int(_log['액션'].astype(str).str.contains('부스터60:40').sum()) if not _log.empty else 0
    print(f"{'부스터B(연례환원)':^26} | {_nav.iloc[-1]:>16,.0f} | {_c*100:>7.2f}% | {_m*100:>7.2f}% | {_s:>6.2f} | {_nd:>6} | {len(_log):>6}")
    print(f"   └ 부스터 발동 횟수: {_nboost}회 (NDX 단독복귀 시점)")
    print("=" * 104)
    print(f"  · RECOVER_BOOST = {RECOVER_BOOST} 로 부스터 비율 자유 조절. 발동 0회면 그 기간에 NDX 단독복귀가 없었다는 뜻.")
    print(f"  · 부스터B 효과: CAGR {(_c-_bc)*100:+.2f}%p / 최종 {(_nav.iloc[-1]/_bnav.iloc[-1]-1)*100:+.1f}% (MDD·샤프 불변=순상방)")

    # ============================================================
    # [5g. 다중 윈도우 강건성] 여러 시작점에서 각 전략을 돌려 '기간 의존성' 점검
    #   한 창에서만 좋은 전략(시작점 편향/과최적화)을 걸러낸다.
    #   각 셀: 해당 전략 CAGR − 현재(fast_recover) CAGR  (양수=현재보다 우월)
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [다중 윈도우 강건성] 시작점별 'CAGR 우위(전략 − 현재)' — 모든 창에서 +라야 진짜")
    print("     양수(+)=그 기간에 현재보다 우월 / 음수(−)=현재보다 열위. 한 칸이라도 크게 −면 기간 의존.")
    print("=" * 104)

    _df_full = get_data('FULL')
    _windows = ['1986-08-01', '1995-01-01', '2000-01-01', '2005-01-01', '2010-01-01']

    # 평가할 전략: (라벨, method, 추가 kwargs)
    _strats = [
        ("split 임계1.5",   'split_recover',     {'bubble_fast_threshold': 1.5}),
        ("split 임계2.0",   'split_recover',     {'bubble_fast_threshold': 2.0}),
        ("부스터B 연례",    'boost_until_annual',{}),
    ]

    # 헤더
    _hdr = f"{'전략 \\ 시작점':^18} |"
    for w in _windows:
        _hdr += f" {w[:4]:^8} |"
    print(_hdr)
    print("-" * 104)

    # 각 윈도우의 현재(fast_recover) CAGR을 먼저 계산(기준선)
    _base_cagr = {}
    _base_label = f"{'현재 CAGR(기준)':^18} |"
    for w in _windows:
        _d = _df_full.loc[w:]
        if len(_d) < 250:
            _base_cagr[w] = None; _base_label += f" {'N/A':^8} |"; continue
        _nav, _ = run_simulation(_d, INITIAL_CAPITAL, W_A, method='fast_recover')
        _c, _, _ = calc_stats(_nav, INITIAL_CAPITAL)
        _base_cagr[w] = _c
        _base_label += f" {_c*100:>6.1f}% |"
    print(_base_label)
    print("-" * 104)

    # 각 전략의 윈도우별 (전략 CAGR − 현재 CAGR)
    for _lbl, _m, _kw in _strats:
        _row = f"{_lbl:^18} |"
        for w in _windows:
            if _base_cagr[w] is None:
                _row += f" {'N/A':^8} |"; continue
            _d = _df_full.loc[w:]
            _nav, _ = run_simulation(_d, INITIAL_CAPITAL, W_A, method=_m, **_kw)
            _c, _, _ = calc_stats(_nav, INITIAL_CAPITAL)
            _delta = (_c - _base_cagr[w]) * 100
            _mark = '+' if _delta >= 0 else ''
            _row += f" {_mark}{_delta:>5.2f}%p|"
        print(_row)
    print("=" * 104)
    print("  · 모든 칸이 + → 기간에 강건(진짜 우위). 칸마다 부호가 갈리면 → 시작점 편향(그 창에만 맞음).")
    print("  · 부스터는 NDX 단독복귀가 있는 창에서만 효과(없는 창은 0에 가까움).")

    # ============================================================
    # [5h. 고버블 구간 절단 검증] '고버블에서 진짜 효과 있나'를 직접 본다.
    #   다중윈도우는 시작점부터 '끝까지'라 고버블 효과가 후속 기간에 희석됨.
    #   여기서는 역사적 고버블 폭락 구간만 잘라(시작~바닥), 그 구간 안에서
    #   현재 vs 동적C vs split vs 게이트의 '낙폭(MDD)·구간수익'을 비교한다.
    #   → 고버블 방어 전략이면 그 구간에서 MDD가 작아야(덜 맞아야) 한다.
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [고버블 구간 절단] 역사적 폭락 구간만 떼서 — '그 구간에서 덜 맞았나' 직접 검증")
    print("     핵심 = 구간 MDD(낙폭, 작을수록 방어 우수). 구간수익도 참고.")
    print("=" * 104)

    # (라벨, 시작, 끝) — 고버블 진입~바닥. 끝은 바닥 근처로 잡아 '폭락 구간'만 절단.
    _crash_windows = [
        ("2000 닷컴붕괴",  "2000-03-01", "2003-03-31"),
        ("2007 금융위기",  "2007-10-01", "2009-03-31"),
        ("2022 긴축폭락",  "2021-11-01", "2022-12-31"),
    ]
    # 비교 전략: (라벨, method, kwargs) — 보험용 split만 현재와 비교
    _crash_strats = [
        ("현재(빠른복귀)",  'fast_recover',      {}),
        ("split 임계1.5",   'split_recover',     {'bubble_fast_threshold': 1.5}),
        ("split 임계2.0",   'split_recover',     {'bubble_fast_threshold': 2.0}),
    ]

    for _wlabel, _wstart, _wend in _crash_windows:
        _seg = df.loc[_wstart:_wend]
        if len(_seg) < 30:
            print(f"\n  [{_wlabel}] 데이터 부족 — 건너뜀")
            continue
        _b0 = _seg['Bubble_Value'].iloc[0]
        _bmin = _seg['Bubble_Value'].min()
        _bmax = _seg['Bubble_Value'].max()
        print(f"\n  ── [{_wlabel}] {_wstart} ~ {_wend} "
              f"(구간 버블 {_bmin:.2f}~{_bmax:.2f}, 시작 {_b0:.2f}) ──")
        print(f"  {'전략':^18} | {'구간수익':^10} | {'구간MDD':^10} | {'최종/초기':^10}")
        print("  " + "-" * 56)
        for _slabel, _sm, _skw in _crash_strats:
            _nav, _ = run_simulation(_seg, INITIAL_CAPITAL, W_A, _slabel, method=_sm, **_skw)
            _ret = (_nav.iloc[-1] / _nav.iloc[0] - 1) * 100
            _mdd = (_nav / _nav.cummax() - 1).min() * 100
            print(f"  {_slabel:^18} | {_ret:>+8.1f}% | {_mdd:>8.1f}% | {_nav.iloc[-1]/_nav.iloc[0]:>8.3f}")
    print("\n" + "=" * 104)
    print("  · 해석: 고버블 방어가 목적이면 그 구간 MDD가 '현재'보다 작아야(덜 맞아야) 효과 있는 것.")
    print("  · 구간수익이 현재보다 높으면서 MDD도 작으면 = 그 구간에선 확실히 우수.")
    print("  · 단, 이건 '구간을 미리 안다'는 가정. 실전은 '언제 그 구간인지 모름'이 핵심 난점.")

    for name, _, _ in configs:
        log = results[name][1]
        if not log.empty:
            print(f"\n[{name} 매매로그]\n" + log.to_string(index=False))
    # ============================================================
    # [6. 차트] NAV(로그) + Drawdown  ← 이 블록을 기존 코드 맨 끝에 붙여넣기
    #   (if __name__ == "__main__": 안, 매매로그 출력 다음 / 들여쓰기 4칸)
    # ============================================================
    import matplotlib.gridspec as gridspec

    A_name = "FAST + gold(비과세)"
    B_name = "FAST + BOXX(양도세)"
    nav_a = results[A_name][0]
    nav_b = results[B_name][0]

    def _dd(nav):
        return (nav / nav.cummax() - 1.0) * 100.0

    ca, ma, sa = calc_stats(nav_a, INITIAL_CAPITAL)
    cb, mb, sb = calc_stats(nav_b, INITIAL_CAPITAL)

    fig = plt.figure(figsize=(15, 9))
    gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.18)

    # ── 상단: NAV (로그 스케일) ──
    ax1 = fig.add_subplot(gs[0])
    ax1.plot(nav_a.index, nav_a.values, color='crimson', lw=1.8,
             label=f'A: FAST+gold (CAGR {ca*100:.1f}%, MDD {ma*100:.1f}%)')
    ax1.plot(nav_b.index, nav_b.values, color='steelblue', lw=1.5, ls='--',
             label=f'B: FAST+BOXX (CAGR {cb*100:.1f}%, MDD {mb*100:.1f}%)')
    ax1.plot(nav_spy.index, nav_spy.values, color='gray', lw=1.0, ls=':', label='SPY (세후)')
    ax1.plot(nav_qqq.index, nav_qqq.values, color='purple', lw=1.0, ls=':', label='QQQ (세후)')
    ax1.plot(nav_qld.index, nav_qld.values, color='green', lw=1.0, ls=':', label='QLD (세후)')   # ★ QLD 추가
    ax1.set_yscale('log')
    ax1.set_ylabel('NAV (USD, Log)')
    ax1.set_title(f'{yrs}년 백테스트 ({sd} ~ {ed}) — A:FAST+gold(비과세) vs B:FAST+BOXX(양도세)')
    ax1.legend(loc='upper left')
    ax1.grid(True, which='both', alpha=0.3)

    # ── 하단: Drawdown (%) ──
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    dd_a = _dd(nav_a)
    dd_b = _dd(nav_b)
    ax2.fill_between(dd_a.index, dd_a.values, 0, color='crimson', alpha=0.20, label='A MDD')
    ax2.plot(dd_b.index, dd_b.values, color='steelblue', lw=1.0, ls='--', label='B MDD')
    ax2.set_ylabel('DD (%)')
    ax2.set_title('Drawdown')
    ax2.legend(loc='lower left')
    ax2.grid(True, alpha=0.3)

    try:
        plt.savefig('backtest_chart.png', dpi=120, bbox_inches='tight')
        print("\n차트 저장: backtest_chart.png")
    except Exception:
        pass
    plt.show()
