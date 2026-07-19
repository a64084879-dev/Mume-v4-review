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
# ═══════════════════════════════════════════════════════════════════════════
#  [TQQQ 실측보정 합성 — 자동생성 블록]  ★ 이 블록을 원본 상단(import 아래)에 붙여넣으세요.
#  · 첫 실행: 2010+ 실제 TQQQ가 비용(m,b)을 결정 → 1985-10~2010-03 합성 → tqqq_full.csv 저장.
#  · 이후 실행: 파일 로드만(빠름). m0_full.csv 자동빌드와 동일 철학.
#  · 정지는 '구조 붕괴'(m<1.5 or m>3.0 or b<0 or 데이터 실패)뿐. 미세 드리프트는 성적표 기록만.
#  · 합성은 참고용(pre-2010). 2010+ 실데이터는 각 엔진 splice가 덮으므로 이 블록과 무관.
# ═══════════════════════════════════════════════════════════════════════════
def _tqf_effr(fred_key, start="1985-01-01"):
    """일별 실효연방기금금리(연율 소수). FRED DFF → DBnomics → ^IRX 폴백."""
    import pandas as _pd, numpy as _np, requests as _rq
    UA = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=DFF"
               f"&api_key={fred_key}&file_type=json&observation_start={start}")
        r = _rq.get(url, headers=UA, timeout=40); r.raise_for_status()
        obs = r.json().get('observations', [])
        if obs:
            df = _pd.DataFrame(obs)
            s = _pd.Series(_pd.to_numeric(df['value'], errors='coerce').values,
                           index=_pd.to_datetime(df['date'])).dropna() / 100.0
            if len(s) > 1000: return s.resample('B').ffill()
    except Exception: pass
    try:
        r = _rq.get("https://api.db.nomics.world/v22/series/FRED/DFF?observations=1",
                    headers=UA, timeout=40); r.raise_for_status()
        d = r.json()['series']['docs'][0]
        s = _pd.Series(_pd.to_numeric(_pd.Series(d['value']).replace('NA', _np.nan),
                       errors='coerce').values, index=_pd.to_datetime(d['period'])).dropna() / 100.0
        s = s[s.index >= start]
        if len(s) > 1000: return s.resample('B').ffill()
    except Exception: pass
    try:
        import yfinance as _yf
        d = _yf.download('^IRX', start=start, auto_adjust=True, progress=False)['Close']
        d = d.squeeze() if hasattr(d, 'squeeze') else d
        d.index = _pd.to_datetime(d.index)
        if getattr(d.index, 'tz', None) is not None: d.index = d.index.tz_localize(None)
        d = (d / 100.0).dropna()
        if len(d) > 1000:
            print("  · [경고] 금리 ^IRX 폴백(EFFR 근사)")
            return d.resample('B').ffill()
    except Exception: pass
    return None

def _tqf_yf_co(ticker, start="1985-09-20"):
    """yfinance close+open (auto_adjust). 실패 시 None."""
    import pandas as _pd
    try:
        import yfinance as _yf
        df = _yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df is None or df.empty: return None, None
        if isinstance(df.columns, _pd.MultiIndex):
            close = df['Close'].squeeze()
            open_ = df['Open'].squeeze() if 'Open' in df.columns.get_level_values(0) else close
        else:
            close = df['Close']; open_ = df.get('Open', close)
        ci = _pd.to_datetime(close.index)
        if getattr(ci, 'tz', None) is not None: ci = ci.tz_localize(None)
        close.index = ci; open_.index = ci
        close = close[close > 0].dropna(); open_ = open_.reindex(close.index)
        open_ = open_.where(open_ > 0, close)
        return close, open_
    except Exception:
        return None, None

def ensure_tqqq_full(db="", fred_key="2bdfd2e7c3efb097542a74f4de9b30b0"):
    """tqqq_full.csv 있으면 로드, 없으면 자동 생성. 반환 (close, open) Series.
       구조 붕괴만 정지(RuntimeError). 미세 드리프트는 tqqq_full_report.txt 기록."""
    import os as _os, numpy as _np, pandas as _pd
    # 1) 로드 경로
    path = None
    for c in ["tqqq_full.csv", db + "tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]:
        if c and _os.path.exists(c): path = c; break
    if path is not None:
        df = _pd.read_csv(path); d = _pd.to_datetime(df[df.columns[0]])
        c = _pd.to_numeric(df["TQQQ"], errors="coerce"); o = _pd.to_numeric(df["TQQQ_OPEN"], errors="coerce")
        if (d.is_monotonic_increasing and c.notna().all() and (c > 0).all()
                and o.notna().all() and (o > 0).all()
                and (d == _pd.Timestamp("2010-02-11")).any()
                and d.iloc[0] <= _pd.Timestamp("1985-10-05")):
            print(f"  · tqqq_full.csv 로드 ({len(df)}행)")
            return _pd.Series(c.values, index=d), _pd.Series(o.values, index=d)
        print("  · [경고] tqqq_full.csv 손상 → 재생성")
    # 2) 빌드
    print("  · tqqq_full.csv 없음 → 자동 생성 (2010+ 실측이 m·b 결정)")
    qc, _ = _tqf_yf_co('QQQ', "1999-03-10")
    tc, _ = _tqf_yf_co('TQQQ', "2010-02-11")
    nc, no = _tqf_yf_co('^NDX', "1985-09-20")
    rate = _tqf_effr(fred_key)
    if qc is None or tc is None or nc is None or rate is None:
        raise RuntimeError("★구조 붕괴: TQQQ/QQQ/^NDX/금리 로드 실패 — 세션 재시작 후 재실행.")
    # 보정 (2창 정확해)
    r_q = qc.resample('B').ffill().pct_change().dropna()
    r_t = tc.resample('B').ffill().pct_change().dropna()
    ra = rate.resample('B').ffill()
    idx = r_q.index.intersection(r_t.index).intersection(ra.index)
    cost = 3 * r_q.reindex(idx) - r_t.reindex(idx); rr = ra.reindex(idx)
    hi_end = str(idx[-1].date())
    cz = cost.loc['2010-03-01':'2021-12-31']; rz = rr.loc['2010-03-01':'2021-12-31']
    ch = cost.loc['2022-06-01':hi_end];        rh = rr.loc['2022-06-01':hi_end]
    if len(cz) < 500 or len(ch) < 250:
        raise RuntimeError(f"★구조 붕괴: 보정 창 부족(ZIRP {len(cz)}·HI {len(ch)}행).")
    mc_z, mr_z = 252 * cz.mean(), rz.mean(); mc_h, mr_h = 252 * ch.mean(), rh.mean()
    m = (mc_h - mc_z) / (mr_h - mr_z); b = mc_z - m * mr_z
    # ★ 구조 붕괴 정지 (딱 이것만) — ×1급/부호/이상치
    if m < 1.5 or m > 3.0 or b < 0:
        raise RuntimeError(f"★구조 붕괴: m={m:.2f}(정상 2 부근)·b={b*100:.2f}% — "
                           f"×1급/부호 오류. 데이터·정렬 확인 후 재실행.")
    # 미세 드리프트 = 기록만 (정지 안 함)
    r_model = 3 * r_q.reindex(idx) - (m * rr + b) / 252
    corr = float(_np.corrcoef(r_model.values, r_t.reindex(idx).values)[0, 1])
    def _ann(cum, yrs): return (1 + cum) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    ez = ((1 + r_model.loc['2010-03-01':'2021-12-31']).prod()
          / (1 + r_t.reindex(idx).loc['2010-03-01':'2021-12-31']).prod() - 1)
    print(f"  · [기록] 실측 m={m:.3f}·b={b*100:.2f}%·일간상관 {corr:.4f} "
          f"(구조 하한 통과 → 파일 생성. 미세 드리프트는 참고용)")
    # 합성 생성 (NDX→QQQ 총수익 스플라이스, −33.3%→−99% 플로어)
    syn_idx = _pd.bdate_range('1985-10-01', '2010-03-31')
    ndx = nc.resample('B').ffill().reindex(_pd.bdate_range('1985-09-20', '2010-03-31')).ffill()
    ndx_o = (no.resample('B').ffill().reindex(ndx.index) if no is not None else ndx)
    ndx_o = ndx_o.where(ndx_o > 0, ndx)
    r_und = ndx.pct_change(); gap = (ndx_o / ndx.shift(1) - 1.0)
    qcl = qc.resample('B').ffill(); r_qq = qcl.pct_change()
    both = r_und.index.intersection(r_qq.dropna().index)
    r_und.loc[both] = r_qq.reindex(r_und.index).loc[both]
    r_und = r_und.reindex(syn_idx).fillna(0.0); gap = gap.reindex(syn_idx).fillna(0.0)
    ra_syn = rate.reindex(syn_idx).ffill().bfill()
    lev = _np.where(r_und.values <= -1.0/3.0, -0.99, 3.0 * r_und.values)
    close = _pd.Series((1.0 + lev - (m * ra_syn.values + b) / 252.0).cumprod() * 100.0, index=syn_idx)
    g3 = _np.clip(3.0 * gap.values, -0.99, None)
    openp = close.shift(1) * (1.0 + g3); openp.iloc[0] = close.iloc[0]
    openp = openp.where(openp > 0, close)
    n_floor = int((r_und.values <= -1.0/3.0).sum())
    out = _pd.DataFrame({'TQQQ': close.round(6), 'TQQQ_OPEN': openp.round(6)})
    out.index.name = 'DATE'
    save = (db + "tqqq_full.csv") if db else "tqqq_full.csv"
    _saved_ok = False
    try:
        out.to_csv(save)
        _saved_ok = True
        print(f"  · tqqq_full.csv 저장 ({len(out)}행, 플로어 {n_floor}일)")
        with open((db + "tqqq_full_report.txt") if db else "tqqq_full_report.txt", 'w') as f:
            f.write(f"tqqq_full.csv 자동생성 성적표 ({_pd.Timestamp.today().date()})\n")
            f.write("=" * 56 + "\n")
            f.write("[채택 근거] 연율 드리프트 일관성 + 연도별 잔차(σ게이트 아님)\n")
            f.write(f"실측 재원조달 승수 m = {m:.4f} (정상 2 부근, 구조 하한 통과)\n")
            f.write(f"실측 고정비      b = {b*100:.4f}%\n")
            f.write(f"일간상관 {corr:.5f} · ZIRP 배수오차 {ez*100:+.2f}%\n")
            f.write(f"합성: {close.index[0].date()}~{close.index[-1].date()}, 플로어 {n_floor}일\n")
            f.write("[σ게이트] 구조 건전성 하한으로 강등(품질 판정 아님). 미세 드리프트는\n")
            f.write("  실제 TQQQ의 물리적 복제 성질(~0.5%/년)이라 정상. 1986 표는 참고용.\n")
    except Exception as e:
        print(f"  · [경고] 저장 실패: {e}")
    # 1회차도 저장본을 재로드 → 이후 로드 경로와 완전 동일(round·정렬 일치)
    if _saved_ok:
        _df = _pd.read_csv(save); _d = _pd.to_datetime(_df[_df.columns[0]])
        return (_pd.Series(_pd.to_numeric(_df["TQQQ"], errors="coerce").values, index=_d),
                _pd.Series(_pd.to_numeric(_df["TQQQ_OPEN"], errors="coerce").values, index=_d))
    return close, openp
# ═══════════════════════════════════════════════════════════════════════════


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
    # ★ TQQQ 합성: tqqq_full.csv(실측보정, 자동생성) 로드로 대체. splice는 유지.
    _tqf_c, _tqf_o = ensure_tqqq_full('/content/drive/MyDrive/')
    close_usd['TQQQ'] = _tqf_c.reindex(close_usd.index).ffill()
    open_usd['TQQQ']  = _tqf_o.reindex(open_usd.index).ffill()
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
if __name__ == "__main__":
    # ★ F6: FULL 1회만 다운로드 → 전체기간 df 및 모든 다중윈도우가 공유(중복 다운로드 제거)
    df_full = get_data('FULL')
    df = df_full.loc[START_DATE:]
    df = df[df.index <= END_DATE]

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
    nav_qld = run_bh_aftertax(df, INITIAL_CAPITAL, 'QLD')   # ★ QLD(2x) 벤치마크

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
    print(f"  · FAST_RECOVER_KEEPS_GOLD = {FAST_RECOVER_KEEPS_GOLD} "
          f"({'현금→TQQQ만(gold 무접촉)' if FAST_RECOVER_KEEPS_GOLD else '전체 50:50 재조정(기존)'})")
    print("=" * 104)
    print(f"{_pad('방식',24)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피수',6)} | {_pad('총매매',6)}")
    print("-" * 104)
    for name, _, _ in configs:
        nav, log = results[name]
        fin, c, m, s, nd, nt = stats_line(nav, log)
        print(f"{_pad(name,24)} | {fin:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {nd:>6} | {nt:>6}")

    for bname, bnav in [("SPY(세후, 참고)", nav_spy), ("QQQ(세후, 참고)", nav_qqq), ("QLD(세후, 참고)", nav_qld)]:
        c, m, s = calc_stats(bnav, INITIAL_CAPITAL)
        print(f"{_pad(bname,24)} | {bnav.iloc[-1]:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {'-':>6} | {'-':>6}")
    print("=" * 104)

    a_fin = results["FAST + gold(비과세)"][0].iloc[-1]
    b_fin = results["FAST + BOXX(양도세)"][0].iloc[-1]
    diff = a_fin - b_fin
    ratio = (a_fin / b_fin - 1) * 100 if b_fin > 0 else 0
    print(f"\n  ▶ A(gold) − B(BOXX) = {diff:>+,.0f}  ({ratio:+.1f}%)")
    print(f"    {'A(gold) 우세' if diff > 0 else 'B(BOXX) 우세'}")

    # ============================================================
    # [5a. 시작일별 A vs B 비교] — 부스터B로 각 시작일에서 실행
    #   ★ F1: B(BOXX)에는 gold 키가 든 기본 RECOVER_BOOST가 들어가면 안 됨 →
    #         _boost_for(w)로 포트에 맞춘 부스터(B는 BOXX 40%)를 recover_boost로 전달.
    # ============================================================
    if START_DATES:
        print("\n" + "=" * 104)
        print(f"  📊 [시작일별 A vs B] 부스터B 기준 — 시작일 {len(START_DATES)}개 각각 (~{END_DATE})")
        print("=" * 104)
        print(f"{_pad('시작일',12)} | {_pad('자산',14)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피',5)}")
        print("-" * 104)
        for _sd_i in START_DATES:
            _sub = df_full.loc[_sd_i:]
            if END_DATE:
                _sub = _sub[_sub.index <= END_DATE]
            if len(_sub) < 250:
                print(f"{_pad(_sd_i,12)} | 데이터 부족 — 건너뜀")
                continue
            for _lbl, _w in [("A(gold)", W_A), ("B(BOXX)", W_B)]:
                _nav_i, _log_i = run_simulation(_sub, INITIAL_CAPITAL, _w, _lbl,
                                                method='boost_until_annual',
                                                recover_boost=_boost_for(_w))  # ★F1
                _c_i, _m_i, _s_i = calc_stats(_nav_i, INITIAL_CAPITAL)
                _nd_i = int((_log_i['액션'] == '대피(USD대기)').sum()) if not _log_i.empty else 0
                print(f"{_pad(_sd_i,12)} | {_pad(_lbl,14)} | {_nav_i.iloc[-1]:>16,.0f} | "
                      f"{_c_i*100:>7.2f}% | {_m_i*100:>7.2f}% | {_s_i:>6.2f} | {_nd_i:>5}")
            print("-" * 104)
        print("=" * 104)
        print("  · 부스터B(NDX 단독복귀 시 60:40) 기준. A=gold(비과세) / B=BOXX(양도세, 부스터도 BOXX).")
        print("  · ⚠️ 시작일들은 독립 표본이 아님(같은 폭락 공유) — 겹치는 구간은 함께 움직임.")

    # ============================================================
    # [5f. 복귀 부스터] 빠른복귀(NDX 단독) 진입 시 TQQQ 더 싣기 — A(gold) 기준
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [복귀 부스터B] A(gold) 기준 — NDX 단독 빠른복귀 진입 순간 TQQQ↑(금↓)로 부스터")
    print(f"     평상시 {int(W_A['TQQQ']*100)}:{int(W_A['gold']*100)} → 부스터 {int(RECOVER_BOOST['TQQQ']*100)}:{int(RECOVER_BOOST['gold']*100)} "
          f"(NDX 단독복귀 시만). 환원: 연 1회 리밸런싱(12/31). ★채택")
    print("=" * 104)
    print(f"{_pad('방식',26)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피수',6)} | {_pad('총매매',6)}")
    print("-" * 104)
    _bnav, _blog = results["FAST + gold(비과세)"]
    _bc, _bm, _bs = calc_stats(_bnav, INITIAL_CAPITAL)
    _bnd = int((_blog['액션'] == '대피(USD대기)').sum()) if not _blog.empty else 0
    print(f"{_pad('현재(부스터 없음, 기준)',26)} | {_bnav.iloc[-1]:>16,.0f} | {_bc*100:>7.2f}% | {_bm*100:>7.2f}% | {_bs:>6.2f} | {_bnd:>6} | {len(_blog):>6}")
    _nav, _log = run_simulation(df, INITIAL_CAPITAL, W_A, '부스터B(연례환원)', method='boost_until_annual')
    _c, _m, _s = calc_stats(_nav, INITIAL_CAPITAL)
    _nd = int((_log['액션'] == '대피(USD대기)').sum()) if not _log.empty else 0
    _nboost = int(_log['액션'].astype(str).str.contains('부스터').sum()) if not _log.empty else 0   # ★F5
    print(f"{_pad('부스터B(연례환원)',26)} | {_nav.iloc[-1]:>16,.0f} | {_c*100:>7.2f}% | {_m*100:>7.2f}% | {_s:>6.2f} | {_nd:>6} | {len(_log):>6}")
    print(f"   └ 부스터 발동 횟수: {_nboost}회 (NDX 단독복귀 시점)")
    print("=" * 104)
    print(f"  · RECOVER_BOOST = {RECOVER_BOOST} 로 부스터 비율 자유 조절. 발동 0회면 그 기간에 NDX 단독복귀가 없었다는 뜻.")
    print(f"  · 부스터B 효과: CAGR {(_c-_bc)*100:+.2f}%p / 최종 {(_nav.iloc[-1]/_bnav.iloc[-1]-1)*100:+.1f}% (MDD·샤프 불변=순상방)")

    # ============================================================
    # [5g. 다중 윈도우 강건성] 시작점별 'CAGR 우위(전략 − 현재)'
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [다중 윈도우 강건성] 시작점별 'CAGR 우위(전략 − 현재)' — 모든 창에서 +라야 진짜")
    print("     양수(+)=그 기간에 현재보다 우월 / 음수(−)=현재보다 열위. 한 칸이라도 크게 −면 기간 의존.")
    print("=" * 104)

    _windows = ['2010-02-11', '2013-01-02', '2016-01-02', '2018-01-02',
                '2020-01-02', '2021-01-02', '2022-01-02', '2024-01-02']
    _strats = [
        ("부스터B 연례",    'boost_until_annual', {}),
    ]

    _hdr = f"{_pad('전략 \\ 시작점',18)} |"
    for w in _windows:
        _hdr += f" {w[:4]:^8} |"
    print(_hdr)
    print("-" * 104)

    _base_cagr = {}
    _base_label = f"{_pad('현재 CAGR(기준)',18)} |"
    for w in _windows:
        _d = df_full.loc[w:]
        if len(_d) < 250:
            _base_cagr[w] = None; _base_label += f" {'N/A':^8} |"; continue
        _nav, _ = run_simulation(_d, INITIAL_CAPITAL, W_A, method='fast_recover')
        _c, _, _ = calc_stats(_nav, INITIAL_CAPITAL)
        _base_cagr[w] = _c
        _base_label += f" {_c*100:>6.1f}% |"
    print(_base_label)
    print("-" * 104)

    for _lbl, _m, _kw in _strats:
        _row = f"{_pad(_lbl,18)} |"
        for w in _windows:
            if _base_cagr[w] is None:
                _row += f" {'N/A':^8} |"; continue
            _d = df_full.loc[w:]
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
    # [5h. 고버블 구간 절단 검증]
    # ============================================================
    print("\n" + "=" * 104)
    print("  🔬 [고버블 구간 절단] 역사적 폭락 구간만 떼서 — '그 구간에서 덜 맞았나' 직접 검증")
    print("     핵심 = 구간 MDD(낙폭, 작을수록 방어 우수). 구간수익도 참고.")
    print("=" * 104)

    _crash_windows = [
        ("2000 닷컴붕괴",  "2000-03-01", "2003-03-31"),
        ("2007 금융위기",  "2007-10-01", "2009-03-31"),
        ("2022 긴축폭락",  "2021-11-01", "2022-12-31"),
    ]
    _crash_strats = [
        ("현재(빠른복귀)",  'fast_recover',      {}),
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
        print(f"  {_pad('전략',18)} | {_pad('구간수익',10)} | {_pad('구간MDD',10)} | {_pad('최종/초기',10)}")
        print("  " + "-" * 56)
        for _slabel, _sm, _skw in _crash_strats:
            _nav, _ = run_simulation(_seg, INITIAL_CAPITAL, W_A, _slabel, method=_sm, **_skw)
            _ret = (_nav.iloc[-1] / _nav.iloc[0] - 1) * 100
            _mdd = (_nav / _nav.cummax() - 1).min() * 100
            print(f"  {_pad(_slabel,18)} | {_ret:>+8.1f}% | {_mdd:>8.1f}% | {_nav.iloc[-1]/_nav.iloc[0]:>8.3f}")
    print("\n" + "=" * 104)
    print("  · 해석: 고버블 방어가 목적이면 그 구간 MDD가 '현재'보다 작아야(덜 맞아야) 효과 있는 것.")
    print("  · 구간수익이 현재보다 높으면서 MDD도 작으면 = 그 구간에선 확실히 우수.")
    print("  · 단, 이건 '구간을 미리 안다'는 가정. 실전은 '언제 그 구간인지 모름'이 핵심 난점.")

    for name, _, _ in configs:
        log = results[name][1]
        if not log.empty:
            print(f"\n[{name} 매매로그]\n" + log.to_string(index=False))

    # ============================================================
    # [6. 차트] NAV(로그) + Drawdown
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

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(nav_a.index, nav_a.values, color='crimson', lw=1.8,
             label=f'A: FAST+gold (CAGR {ca*100:.1f}%, MDD {ma*100:.1f}%)')
    ax1.plot(nav_b.index, nav_b.values, color='steelblue', lw=1.5, ls='--',
             label=f'B: FAST+BOXX (CAGR {cb*100:.1f}%, MDD {mb*100:.1f}%)')
    ax1.plot(nav_spy.index, nav_spy.values, color='gray', lw=1.0, ls=':', label='SPY (세후)')
    ax1.plot(nav_qqq.index, nav_qqq.values, color='purple', lw=1.0, ls=':', label='QQQ (세후)')
    ax1.plot(nav_qld.index, nav_qld.values, color='green', lw=1.0, ls=':', label='QLD (세후)')
    ax1.set_yscale('log')
    ax1.set_ylabel('NAV (USD, Log)')
    ax1.set_title(f'{yrs}년 백테스트 ({sd} ~ {ed}) — A:FAST+gold(비과세) vs B:FAST+BOXX(양도세)')
    ax1.legend(loc='upper left')
    ax1.grid(True, which='both', alpha=0.3)

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

# -*- coding: utf-8 -*-
"""
라오어 밸류 리밸런싱 백테스터 v2 — 거치식·적립식·인출식 (+킬스위치/B1/VOLTGT)  1986~오늘
════════════════════════════════════════════════════════════════════════
★ v2 핵심 교정 (2026-07-14): 신호일과 집행일을 분리했다.

  ■ 무엇이 문제였나 (v1)
    · 대피/복귀: 당일 종가로 판정하고 → '그 당일 종가'로 청산/재매수했다.
    · VOLTGT  : 사이클 첫날 RV(그날 종가 포함)로 노출을 정하고 → '그날부터' 적용했다.
    종가를 알아야 계산되는 신호로 그 종가에 체결하는 것은 실전에서 불가능하다
    (미래를 보는 건 아니지만 same-bar execution — 백테스트를 유리하게 만든다).
    3배 레버리지에서 하루 차이는 크다. 특히 폭락 첫날.

  ■ 우리 봇은 어떻게 하나 (검증 완료)
    · 오늘 종가로 판정 → "다음 거래일 LOC"로 집행 (vr_signal_bot.py 764·825·842행)
    · VOLTGT scale = 마지막 완료 종가의 RV → 그 이후 밴드에 적용
    → 봇은 look-ahead 없음. 백테스터만 하루 유리했다.

  ■ v2가 하는 일
    SIGNAL_LAG=1 (기본) → 대피·복귀·VOLTGT 신호를 '전 거래일 종가' 기준으로 읽고
    '오늘 종가'에 집행한다. 봇의 (판정 t → LOC t+1)과 정확히 같은 구조.
    SIGNAL_LAG=0 으로 두면 v1(구버전) 재현 → 얼마나 부풀려졌는지 직접 비교 가능.

  ■ 밴드 매매(사다리)는 지연 없음 — 의도적이다
    사다리는 사이클 시작에 지정가를 '미리 걸어두고' 장중에 체결된다.
    따라서 당일 종가 기준 밴드 이탈 → 당일 체결은 정당한 근사다(실전 재현 가능).
    (LOC vs 사다리 등가성은 별도 검증: 8.5년 +0.051pp/년 → 무시 가능)

════════════════════════════════════════════════════════════════════════
■ 공통 V 공식 :  V_next = V + pool/G + (적립금 − 인출금)
      · 거치식 : G=10 · 초기Pool 10% · 매수한도 50%
      · 적립식 : G=10 · 초기Pool  0% · 매수한도 75%
      · 인출식 : G=20 · 초기Pool 20% · 매수한도 25%
  공통: 밴드 ±15% · 매도 무제한 · 격주(14일) 사이클 · 첫 V = 보유주수 × 시작가
  (김개미 검증: 거치 18,300→18,500 / 적립 4,999.5→5,249.55 / 인출 39,500→39,750→39,866.78)

■ 킬스위치: 버블(GSPC/M0)≥1.30 AND GSPC<SMA200 → 전량매도 → 현금, VR 동결.
  복귀(월말 판정): 버블<1.30 → GSPC/NDX 중 먼저 SMA200 돌파 / 버블≥1.30 → GSPC 단독.
  ★V 리셋 안 함.  B1: 위 조건 OR (버블 롤링백분위 ≥ B1_PCTL AND GSPC<SMA200)
■ 데이터: 합성 스플라이싱(^NDX→QQQ→TQQQ×3, 2010~ 실데이터)
■ 세금: 양도세 22% · 공제 250만(만기 1회)
════════════════════════════════════════════════════════════════════════
"""
import os, sys, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")        # FutureWarning 스팸 제거 (계산엔 영향 없음)

# ══════════════ [1. 파라미터] ══════════════
FETCH_START = "1985-10-01"
START_DATES = ["1986-08-11", "1994-01-02", "1998-01-02", "2000-01-02", "2010-02-11",
               "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]
END_DATE    = "2026-07-10"           # None=데이터끝. 책재현="2020-12-31"

# ★★ v2 핵심 스위치 ★★
#   1 = 봇 정합 (전일 종가 신호 → 당일 종가 집행)   ← 기본·실전 재현
#   0 = v1 재현 (당일 신호 → 당일 집행)             ← 구버전 비교용
SIGNAL_LAG = 1

RUN_HOLD, RUN_DCA, RUN_WD = "on", "on", "on"
KILLSWITCH = "on"
CHART_ON   = "on"
CHART_MODE = "hold"                  # "hold"/"dca"/"wd"
CHART_START = "2010-02-11"

def ON(x): return str(x).strip().lower() == "on"

# 거치식 / 적립식 / 인출식
HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT = 100000.0, 0.10, 10, 0.50
DCA_INIT, DCA_MONTHLY, DCA_POOL, DCA_G, DCA_LIMIT = 500.0, 50.0, 0.00, 10, 0.75
WD_CAP, WD_MONTHLY, WD_POOL, WD_G, WD_LIMIT = 100000.0, 300.0, 0.20, 20, 0.25

LUMP_EVENTS = {}                     # {"2020-03-23": 50000, "2022-06-01": -20000}

BAND_LOW, BAND_HIGH = 0.85, 1.15
TAX_RATE, TAX_DEDUCTION = 0.22, 250.0
BUBBLE_LIMIT = 1.30
FAST_RECOVER = "on"
SKILL_ON     = "off"                 # 실력공식: 기각(2026-07) — 미탑재 유지

# ── B1 (QE 이후 사각지대 보완) ──
#   ★확정 2026-07-14: PCTL 0.80→0.75. "0.80 수익우위 +23%"는 실 FRED M0 특정
#     아티팩트(폴백선 +5.6%로 증발)+단일점. 절벽(0.85 붕괴)에서 두 칸 이격. MDD방어는
#     0.70~0.80 평탄. 롤링(1986~) 검증: B1은 QE 이후 전담(실측 방어 100%), QE 이전엔
#     원조건이 전담·B1 무해(합성 방어 5%). = 세대교체 상호보완, 둘 다 유지.
B1_ON    = "on"
B1_PCTL  = 0.75
B1_WIN_Y = 10

# ── VOLTGT (변동성 타겟팅) ── ★기각 확정 2026-07-16 (on → off)
#   [번복 근거] 6개 시작일 "유지"는 2022 폭락직후 편향. 롤링(시작점 다양화)에서 뒤집힘:
#     10년25개 CAGR개선 0/25·중앙 -1.03%p / 7년56개 12%·-1.15%p / 5년137개(겹침최소) 23%·-0.76%p.
#     세 표본 CAGR 음수 일관 = 겹침 착시 아님. 낙폭방어도 대부분 +1%p대(10년만 +4.1%p 예외).
#     연 ~1%p CAGR 상시 비용 vs 낙폭 1~4%p 방어 = 가성비 나쁨. 낙폭 핵심 25%p는 B1이 유지.
#     "폭락직후 이득"은 첫 타격 이미 맞은 뒤라 무의미(현실엔 없는 시나리오). → 무매·VR 통일 기각.
VOLTGT_ON       = "off"
VOLTGT_TARGET   = 0.60
VOLTGT_LOOKBACK = 20

TQQQ_DRAG_MULT, TQQQ_DRAG_ADD = 2.0, 0.0095 + 0.015   # (구 합성용, 2026-07-16 NEW 공식으로 대체 — 미사용)
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


# ══════════════ [2. 데이터] ══════════════
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


# ═══════════════════════════════════════════════════════════════════════════
#  [TQQQ 실측보정 합성 — 자동생성 블록]  ★ 이 블록을 원본 상단(import 아래)에 붙여넣으세요.
#  · 첫 실행: 2010+ 실제 TQQQ가 비용(m,b)을 결정 → 1985-10~2010-03 합성 → tqqq_full.csv 저장.
#  · 이후 실행: 파일 로드만(빠름). m0_full.csv 자동빌드와 동일 철학.
#  · 정지는 '구조 붕괴'(m<1.5 or m>3.0 or b<0 or 데이터 실패)뿐. 미세 드리프트는 성적표 기록만.
#  · 합성은 참고용(pre-2010). 2010+ 실데이터는 각 엔진 splice가 덮으므로 이 블록과 무관.
# ═══════════════════════════════════════════════════════════════════════════
def _tqf_effr(fred_key, start="1985-01-01"):
    """일별 실효연방기금금리(연율 소수). FRED DFF → DBnomics → ^IRX 폴백."""
    import pandas as _pd, numpy as _np, requests as _rq
    UA = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=DFF"
               f"&api_key={fred_key}&file_type=json&observation_start={start}")
        r = _rq.get(url, headers=UA, timeout=40); r.raise_for_status()
        obs = r.json().get('observations', [])
        if obs:
            df = _pd.DataFrame(obs)
            s = _pd.Series(_pd.to_numeric(df['value'], errors='coerce').values,
                           index=_pd.to_datetime(df['date'])).dropna() / 100.0
            if len(s) > 1000: return s.resample('B').ffill()
    except Exception: pass
    try:
        r = _rq.get("https://api.db.nomics.world/v22/series/FRED/DFF?observations=1",
                    headers=UA, timeout=40); r.raise_for_status()
        d = r.json()['series']['docs'][0]
        s = _pd.Series(_pd.to_numeric(_pd.Series(d['value']).replace('NA', _np.nan),
                       errors='coerce').values, index=_pd.to_datetime(d['period'])).dropna() / 100.0
        s = s[s.index >= start]
        if len(s) > 1000: return s.resample('B').ffill()
    except Exception: pass
    try:
        import yfinance as _yf
        d = _yf.download('^IRX', start=start, auto_adjust=True, progress=False)['Close']
        d = d.squeeze() if hasattr(d, 'squeeze') else d
        d.index = _pd.to_datetime(d.index)
        if getattr(d.index, 'tz', None) is not None: d.index = d.index.tz_localize(None)
        d = (d / 100.0).dropna()
        if len(d) > 1000:
            print("  · [경고] 금리 ^IRX 폴백(EFFR 근사)")
            return d.resample('B').ffill()
    except Exception: pass
    return None

def _tqf_yf_co(ticker, start="1985-09-20"):
    """yfinance close+open (auto_adjust). 실패 시 None."""
    import pandas as _pd
    try:
        import yfinance as _yf
        df = _yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df is None or df.empty: return None, None
        if isinstance(df.columns, _pd.MultiIndex):
            close = df['Close'].squeeze()
            open_ = df['Open'].squeeze() if 'Open' in df.columns.get_level_values(0) else close
        else:
            close = df['Close']; open_ = df.get('Open', close)
        ci = _pd.to_datetime(close.index)
        if getattr(ci, 'tz', None) is not None: ci = ci.tz_localize(None)
        close.index = ci; open_.index = ci
        close = close[close > 0].dropna(); open_ = open_.reindex(close.index)
        open_ = open_.where(open_ > 0, close)
        return close, open_
    except Exception:
        return None, None

def ensure_tqqq_full(db="", fred_key="2bdfd2e7c3efb097542a74f4de9b30b0"):
    """tqqq_full.csv 있으면 로드, 없으면 자동 생성. 반환 (close, open) Series.
       구조 붕괴만 정지(RuntimeError). 미세 드리프트는 tqqq_full_report.txt 기록."""
    import os as _os, numpy as _np, pandas as _pd
    # 1) 로드 경로
    path = None
    for c in ["tqqq_full.csv", db + "tqqq_full.csv", "/content/drive/MyDrive/tqqq_full.csv"]:
        if c and _os.path.exists(c): path = c; break
    if path is not None:
        df = _pd.read_csv(path); d = _pd.to_datetime(df[df.columns[0]])
        c = _pd.to_numeric(df["TQQQ"], errors="coerce"); o = _pd.to_numeric(df["TQQQ_OPEN"], errors="coerce")
        if (d.is_monotonic_increasing and c.notna().all() and (c > 0).all()
                and o.notna().all() and (o > 0).all()
                and (d == _pd.Timestamp("2010-02-11")).any()
                and d.iloc[0] <= _pd.Timestamp("1985-10-05")):
            print(f"  · tqqq_full.csv 로드 ({len(df)}행)")
            return _pd.Series(c.values, index=d), _pd.Series(o.values, index=d)
        print("  · [경고] tqqq_full.csv 손상 → 재생성")
    # 2) 빌드
    print("  · tqqq_full.csv 없음 → 자동 생성 (2010+ 실측이 m·b 결정)")
    qc, _ = _tqf_yf_co('QQQ', "1999-03-10")
    tc, _ = _tqf_yf_co('TQQQ', "2010-02-11")
    nc, no = _tqf_yf_co('^NDX', "1985-09-20")
    rate = _tqf_effr(fred_key)
    if qc is None or tc is None or nc is None or rate is None:
        raise RuntimeError("★구조 붕괴: TQQQ/QQQ/^NDX/금리 로드 실패 — 세션 재시작 후 재실행.")
    # 보정 (2창 정확해)
    r_q = qc.resample('B').ffill().pct_change().dropna()
    r_t = tc.resample('B').ffill().pct_change().dropna()
    ra = rate.resample('B').ffill()
    idx = r_q.index.intersection(r_t.index).intersection(ra.index)
    cost = 3 * r_q.reindex(idx) - r_t.reindex(idx); rr = ra.reindex(idx)
    hi_end = str(idx[-1].date())
    cz = cost.loc['2010-03-01':'2021-12-31']; rz = rr.loc['2010-03-01':'2021-12-31']
    ch = cost.loc['2022-06-01':hi_end];        rh = rr.loc['2022-06-01':hi_end]
    if len(cz) < 500 or len(ch) < 250:
        raise RuntimeError(f"★구조 붕괴: 보정 창 부족(ZIRP {len(cz)}·HI {len(ch)}행).")
    mc_z, mr_z = 252 * cz.mean(), rz.mean(); mc_h, mr_h = 252 * ch.mean(), rh.mean()
    m = (mc_h - mc_z) / (mr_h - mr_z); b = mc_z - m * mr_z
    # ★ 구조 붕괴 정지 (딱 이것만) — ×1급/부호/이상치
    if m < 1.5 or m > 3.0 or b < 0:
        raise RuntimeError(f"★구조 붕괴: m={m:.2f}(정상 2 부근)·b={b*100:.2f}% — "
                           f"×1급/부호 오류. 데이터·정렬 확인 후 재실행.")
    # 미세 드리프트 = 기록만 (정지 안 함)
    r_model = 3 * r_q.reindex(idx) - (m * rr + b) / 252
    corr = float(_np.corrcoef(r_model.values, r_t.reindex(idx).values)[0, 1])
    def _ann(cum, yrs): return (1 + cum) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    ez = ((1 + r_model.loc['2010-03-01':'2021-12-31']).prod()
          / (1 + r_t.reindex(idx).loc['2010-03-01':'2021-12-31']).prod() - 1)
    print(f"  · [기록] 실측 m={m:.3f}·b={b*100:.2f}%·일간상관 {corr:.4f} "
          f"(구조 하한 통과 → 파일 생성. 미세 드리프트는 참고용)")
    # 합성 생성 (NDX→QQQ 총수익 스플라이스, −33.3%→−99% 플로어)
    syn_idx = _pd.bdate_range('1985-10-01', '2010-03-31')
    ndx = nc.resample('B').ffill().reindex(_pd.bdate_range('1985-09-20', '2010-03-31')).ffill()
    ndx_o = (no.resample('B').ffill().reindex(ndx.index) if no is not None else ndx)
    ndx_o = ndx_o.where(ndx_o > 0, ndx)
    r_und = ndx.pct_change(); gap = (ndx_o / ndx.shift(1) - 1.0)
    qcl = qc.resample('B').ffill(); r_qq = qcl.pct_change()
    both = r_und.index.intersection(r_qq.dropna().index)
    r_und.loc[both] = r_qq.reindex(r_und.index).loc[both]
    r_und = r_und.reindex(syn_idx).fillna(0.0); gap = gap.reindex(syn_idx).fillna(0.0)
    ra_syn = rate.reindex(syn_idx).ffill().bfill()
    lev = _np.where(r_und.values <= -1.0/3.0, -0.99, 3.0 * r_und.values)
    close = _pd.Series((1.0 + lev - (m * ra_syn.values + b) / 252.0).cumprod() * 100.0, index=syn_idx)
    g3 = _np.clip(3.0 * gap.values, -0.99, None)
    openp = close.shift(1) * (1.0 + g3); openp.iloc[0] = close.iloc[0]
    openp = openp.where(openp > 0, close)
    n_floor = int((r_und.values <= -1.0/3.0).sum())
    out = _pd.DataFrame({'TQQQ': close.round(6), 'TQQQ_OPEN': openp.round(6)})
    out.index.name = 'DATE'
    save = (db + "tqqq_full.csv") if db else "tqqq_full.csv"
    _saved_ok = False
    try:
        out.to_csv(save)
        _saved_ok = True
        print(f"  · tqqq_full.csv 저장 ({len(out)}행, 플로어 {n_floor}일)")
        with open((db + "tqqq_full_report.txt") if db else "tqqq_full_report.txt", 'w') as f:
            f.write(f"tqqq_full.csv 자동생성 성적표 ({_pd.Timestamp.today().date()})\n")
            f.write("=" * 56 + "\n")
            f.write("[채택 근거] 연율 드리프트 일관성 + 연도별 잔차(σ게이트 아님)\n")
            f.write(f"실측 재원조달 승수 m = {m:.4f} (정상 2 부근, 구조 하한 통과)\n")
            f.write(f"실측 고정비      b = {b*100:.4f}%\n")
            f.write(f"일간상관 {corr:.5f} · ZIRP 배수오차 {ez*100:+.2f}%\n")
            f.write(f"합성: {close.index[0].date()}~{close.index[-1].date()}, 플로어 {n_floor}일\n")
            f.write("[σ게이트] 구조 건전성 하한으로 강등(품질 판정 아님). 미세 드리프트는\n")
            f.write("  실제 TQQQ의 물리적 복제 성질(~0.5%/년)이라 정상. 1986 표는 참고용.\n")
    except Exception as e:
        print(f"  · [경고] 저장 실패: {e}")
    # 1회차도 저장본을 재로드 → 이후 로드 경로와 완전 동일(round·정렬 일치)
    if _saved_ok:
        _df = _pd.read_csv(save); _d = _pd.to_datetime(_df[_df.columns[0]])
        return (_pd.Series(_pd.to_numeric(_df["TQQQ"], errors="coerce").values, index=_d),
                _pd.Series(_pd.to_numeric(_df["TQQQ_OPEN"], errors="coerce").values, index=_d))
    return close, openp
# ═══════════════════════════════════════════════════════════════════════════


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
    # ★2026-07-16 합성 교정: 기존 clip(-.5,.5)*3은 폭락일 -150% → 자산 음수 폭발
    #   ("500~700배 유령"의 원인). 실측(2010~) 채점: 기존 배수오차 -41.7% → 교정 -2.0%,
    #   일간상관 0.9986 동일. 레버리지 ETF 표준: NDX*3, 원지수 -33.3% 이하는 -99% 고정
    #   (3배 ETF 전액소멸 특성), 비용 = 금리 + TQQQ 총보수 0.84%.
    #   → 이제 2010년 이전 합성 구간도 폭발 없이 신뢰 가능(성과는 여전히 참고용).
    # ★ TQQQ 합성: tqqq_full.csv(실측보정 m≈2, 자동생성) 로드로 대체. splice는 유지.
    _tqf_c, _tqf_o = ensure_tqqq_full(db)
    tqqq_syn = _tqf_c.reindex(idx).ffill()
    tqqq = splice(tqqq_syn, tqqq_real, "TQQQ")

    out = pd.DataFrame({"TQQQ": tqqq, "QQQ": qqq, "GSPC": gspc, "NDX": ndx, "IRX": irx,
                        "GSMA": gspc.rolling(200).mean(), "NSMA": ndx.rolling(200).mean(),
                        "BUB": gspc / m0}).dropna()

    # B1: 버블의 롤링 백분위 (당일 포함 = 그 시점까지의 정보만. 미래 없음)
    w = int(252 * B1_WIN_Y)
    out["BUB_PCTL"] = out["BUB"].rolling(w, min_periods=int(252 * 3)).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)

    # RV: 실제 TQQQ 우선(2010~), 없으면 합성가. 봇과 동일 기준.
    tqqq_real_al = tqqq_real.reindex(out.index).ffill() if tqqq_real is not None else None
    ret_syn = out["TQQQ"].pct_change()
    if tqqq_real_al is not None:
        ret_real = tqqq_real_al.pct_change()
        ret_for_rv = ret_real.where(ret_real.notna(), ret_syn)
    else:
        ret_for_rv = ret_syn
    out["RV"] = ret_for_rv.rolling(VOLTGT_LOOKBACK).std() * np.sqrt(252)
    return out


# ══════════════ [3. 주기 분할] ══════════════
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


# ══════════════ [3b. ★신호 지연 — v2 핵심] ══════════════
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
        "G":    sh(d["GSPC"]),
        "GS":   sh(d["GSMA"]),
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


def _exit_sig(sig, dd):
    """대피 신호 (전일 종가 기준). 기존(버블≥1.30) OR B1(롤링백분위≥임계). 둘 다 SMA200 하회 전제."""
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
    """복귀 신호 (전일=월말 종가 기준). 버블<1.30이면 S&P/NDX 중 먼저 돌파, 아니면 S&P 단독."""
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


# ══════════════ [4. VR 엔진] ══════════════
def run_vr(d, init_capital, pool_ratio, G, buy_limit, dep=0.0, wd=0.0, killswitch=True):
    """flow = dep − wd (사이클당 순현금). V_next = V + pool/G + flow.
       ★v2: 대피·복귀·VOLTGT는 '전일 신호 → 당일 종가 집행' (봇과 동일 구조)."""
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

        # ── 목돈 추가/인출 (P/V 고정) ──
        while li < len(lumps) and lumps[li][0] <= cd[0] and state == "INVESTED":
            amt = lumps[li][1]; ev0 = shares * p0; total = ev0 + pool
            if total > 0 and V > 0:
                if amt < 0 and -amt >= total:          # 총자산보다 큰 인출 → 파산
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

        # 인출 고갈 → 파산 정지
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
            if pool < 0:                               # 인출로 현금 부족 → 주식 매도
                need = -pool; sell_sh = min(need / p0, shares)
                shares -= sell_sh; pool += sell_sh * p0
                if pool < 0: pool = 0.0

        # ★VOLTGT: 사이클 첫날에 '직전 거래일 RV'로 노출 확정 (봇의 cyc_scale 스냅샷)
        Veff = V * _vscale(sig, cd[0])
        bmin, bmax = Veff * BAND_LOW, Veff * BAND_HIGH
        budget = max(0, pool) * buy_limit; used = 0.0

        for dd in cd:
            p = float(px.loc[dd])

            if killswitch:
                # ★대피: 전일 신호 → 오늘 종가 집행 (봇의 '익일 LOC'와 동일 구조)
                if state == "INVESTED" and _exit_sig(sig, dd):
                    pool += shares * p; shares = 0.0
                    state = "CASH"; n_exit += 1
                    daily.append((dd, pool)); continue
                # ★복귀: 전일(=월말) 신호 → 오늘 종가 집행
                if state == "CASH" and _recover_sig(sig, dd):
                    buy = min(Veff, pool)
                    shares = buy / p; pool -= buy
                    state = "INVESTED"; n_rec += 1

            # 밴드 매매(사다리) — 지연 없음(지정가 사전 게시 → 장중 체결)
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

    # 샤프: 현금흐름 제거한 순수 시장수익률 기준
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
    """단순보유(세후). 적립분 매수/인출분 매도 반영. 성과 = 최종NAV + 인출누계."""
    shares = init_capital / float(px.iloc[0]); cum_in = cum_out = 0.0
    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]])
        if dep > 0: shares += dep / p0; cum_in += dep
        if wd > 0:  shares -= min(wd / p0, shares); cum_out += wd
    nav = shares * float(px.iloc[-1])
    cum = init_capital + cum_in; result = nav + cum_out
    tax = max(0, result - cum - TAX_DEDUCTION) * TAX_RATE
    return result - tax


# ══════════════ [5. 출력] ══════════════
import unicodedata
def _w(s):
    return sum(2 if unicodedata.east_asian_width(str(c)) in "WF" else 1 for c in str(s))
def _cell(s, width, align=">"):
    pad = width - _w(s)
    if pad <= 0: return str(s)
    if align == ">": return " " * pad + str(s)
    if align == "<": return str(s) + " " * pad
    return " " * (pad // 2) + str(s) + " " * (pad - pad // 2)


def _table(df, title, init, pool_ratio, G, buy_limit, dep, wd):
    end_dt = (df[df.index <= END_DATE].index[-1] if END_DATE else df.index[-1]).date()
    print("\n" + "=" * 128); print(f"  {title}")
    print(f"  ▸ 종료일: {end_dt} · SIGNAL_LAG={SIGNAL_LAG} "
          f"({'봇 정합(전일신호→당일집행)' if SIGNAL_LAG else 'v1 재현(당일신호→당일집행)'})")
    print("=" * 128)
    cols = [("시작일", 12, "<"), ("년수", 6, ">"), ("원금", 11, ">"), ("VR+KS세후", 15, ">"),
            ("VR단독세후", 15, ">"), ("TQQQ보유", 14, ">"), ("QQQ보유", 13, ">"),
            ("CAGR", 8, ">"), ("KS MDD", 9, ">"), ("샤프", 7, ">"), ("대피/복귀", 11, ">")]
    print("".join(_cell(h, w, a) for h, w, a in cols))
    print("-" * 128)
    for sd in START_DATES:
        sub = df[df.index >= sd]
        if END_DATE: sub = sub[sub.index <= END_DATE]
        if len(sub) < 300:
            print(_cell(sd, 12, "<") + "  (데이터 부족)"); continue
        rk = run_vr(sub, init, pool_ratio, G, buy_limit, dep, wd, killswitch=ON(KILLSWITCH))
        rn = run_vr(sub, init, pool_ratio, G, buy_limit, dep, wd, killswitch=False)
        ht = run_hold_bench(sub["TQQQ"], init, dep, wd)
        hq = run_hold_bench(sub["QQQ"], init, dep, wd)
        vals = [(sd, 12, "<"), (f"{rk['yrs']:.1f}", 6, ">"), (f"{rk['cum']:,.0f}", 11, ">"),
                (f"{rk['aftertax']:,.0f}", 15, ">"), (f"{rn['aftertax']:,.0f}", 15, ">"),
                (f"{ht:,.0f}", 14, ">"), (f"{hq:,.0f}", 13, ">"),
                (f"{rk['cagr']*100:.1f}%", 8, ">"), (f"{rk['mdd']*100:.1f}%", 9, ">"),
                (f"{rk['sharpe']:.2f}", 7, ">"), (f"{rk['n_exit']}/{rk['n_rec']}", 11, ">")]
        print("".join(_cell(v, w, a) for v, w, a in vals))


def _nav_series_vr(d, init, pool_ratio, G, buy_limit, killswitch, dep=0.0, wd=0.0):
    """차트용 NAV 시계열. run_vr와 동일 로직(신호지연 포함)."""
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


def make_chart(df, start, mode="hold", init=None, save="on"):
    import matplotlib
    try:
        from IPython import get_ipython
        in_nb = (get_ipython() is not None and "IPKernelApp" in str(get_ipython().config)) \
                or ('google.colab' in sys.modules)
    except Exception:
        in_nb = ('google.colab' in sys.modules)
    if not in_nb: matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _setup_korean_font()

    cfg = {"hold": ("거치식", HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, 0.0, 0.0),
           "dca":  ("적립식", DCA_INIT, DCA_POOL, DCA_G, DCA_LIMIT, DCA_MONTHLY / 2, 0.0),
           "wd":   ("인출식", WD_CAP, WD_POOL, WD_G, WD_LIMIT, 0.0, WD_MONTHLY / 2)}[mode]
    label0, cap, pool_r, G, lim, dep, wd = cfg
    init = init if init else cap
    sub = df[df.index >= start]
    if END_DATE: sub = sub[sub.index <= END_DATE]

    ks = _nav_series_vr(sub, init, pool_r, G, lim, ON(KILLSWITCH), dep, wd)
    so = _nav_series_vr(sub, init, pool_r, G, lim, False, dep, wd)
    tq = init / float(sub["TQQQ"].iloc[0]) * sub["TQQQ"]
    qq = init / float(sub["QQQ"].iloc[0]) * sub["QQQ"]
    dd = lambda s: (s / s.cummax() - 1) * 100
    cg = lambda s: ((s.iloc[-1] / s.iloc[0]) ** (365.25 / ((s.index[-1] - s.index[0]).days)) - 1
                    if s.iloc[-1] > 0 else float('nan'))

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 8),
                                 gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    a1.set_title(f"VR {label0} {init:,.0f} ({start} ~ {sub.index[-1].date()}) "
                 f"[KS={KILLSWITCH}, B1={B1_ON}, VOLTGT={VOLTGT_ON}, LAG={SIGNAL_LAG}]", fontsize=12)
    a1.plot(ks.index, ks, lw=2.2, color="crimson",
            label=f"VR+KS (CAGR {cg(ks)*100:.1f}%, MDD {dd(ks).min():.1f}%)")
    a1.plot(so.index, so, lw=1.3, color="darkorange", ls="--",
            label=f"VR단독 (CAGR {cg(so)*100:.1f}%, MDD {dd(so).min():.1f}%)")
    a1.plot(tq.index, tq, lw=1.0, color="steelblue", ls=":",
            label=f"TQQQ보유 (CAGR {cg(tq)*100:.1f}%, MDD {dd(tq).min():.1f}%)")
    a1.plot(qq.index, qq, lw=1.0, color="purple", ls=":",
            label=f"QQQ보유 (CAGR {cg(qq)*100:.1f}%, MDD {dd(qq).min():.1f}%)")
    a1.set_yscale("log"); a1.set_ylabel("NAV (USD, Log)")
    a1.legend(fontsize=9, loc="upper left"); a1.grid(alpha=0.3)
    a2.fill_between(dd(ks).index, dd(ks), 0, color="crimson", alpha=0.25, label="VR+KS DD")
    a2.plot(dd(so).index, dd(so), color="darkorange", lw=0.9, ls="--", label="VR단독 DD")
    a2.set_ylabel("DD (%)"); a2.legend(fontsize=8, loc="lower left"); a2.grid(alpha=0.3)
    plt.tight_layout()
    out = f"vr_chart_{mode}.png"
    if ON(save):
        plt.savefig(out, dpi=100, bbox_inches="tight")
        print(f"  · 차트 저장: {out}")
    if in_nb:
        try: plt.show()
        except Exception: pass
    plt.close()
    return out


# ══════════════ [5b. 결론 요약 — 실데이터 구간만] ══════════════
REAL_STARTS = ["2010-02-11", "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02"]

def summary(df):
    """★TQQQ 실데이터(2010-02-11 상장~)만. 그 이전은 NDX×3 합성 시계열이라
       '킬스위치가 -99% 두 번을 피했다' 같은 유령 배수가 나온다 — 결론 근거로 쓰지 않는다."""
    print("\n" + "█" * 92)
    print("  ★ 결론 요약 — TQQQ 실데이터 구간(2010~)만.  거치식 10만 · 세후")
    print("     (1986~2000 시작은 합성 데이터 → 참고용. 아래 상세표 참조)")
    print("█" * 92)
    print(f"{'시작일':<13}{'년수':>6}{'VR+KS':>14}{'VR단독':>14}{'TQQQ보유':>14}"
          f"{'CAGR':>8}{'MDD':>9}{'샤프':>7}{'KS효과':>9}")
    print("-" * 92)
    for sd in REAL_STARTS:
        sub = df[df.index >= sd]
        if END_DATE: sub = sub[sub.index <= END_DATE]
        if len(sub) < 300: continue
        rk = run_vr(sub, HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, killswitch=ON(KILLSWITCH))
        rn = run_vr(sub, HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, killswitch=False)
        ht = run_hold_bench(sub["TQQQ"], HOLD_CAP)
        eff = rk["aftertax"] / rn["aftertax"] if rn["aftertax"] > 0 else float("nan")
        print(f"{sd:<13}{rk['yrs']:>5.1f}년{rk['aftertax']:>14,.0f}{rn['aftertax']:>14,.0f}"
              f"{ht:>14,.0f}{rk['cagr']*100:>7.1f}%{rk['mdd']*100:>8.1f}%"
              f"{rk['sharpe']:>7.2f}{eff:>8.2f}배")
    print("-" * 92)
    print("  · KS효과 = VR+킬스위치 ÷ VR단독.  실데이터에선 1.3~1.5배 수준(합성구간의 500배는 유령).")
    print("  · VR단독 = 킬스위치 off.  TQQQ보유 = 단순 매수후보유(세후).")
    print(f"  · 오버레이: B1={B1_ON} · VOLTGT={VOLTGT_ON}(목표{VOLTGT_TARGET:.0%}) "
          f"· 빠른복귀={FAST_RECOVER} · SIGNAL_LAG={SIGNAL_LAG}(봇 정합)")
    print("█" * 92)


# ══════════════ [6. LAG 영향 진단 — v1 대비 얼마나 부풀려졌나] ══════════════
def lag_diagnostic(df, init=None, pool_ratio=None, G=None, buy_limit=None):
    """SIGNAL_LAG 0(v1) vs 1(봇정합) 을 같은 조건으로 돌려 차이를 보여준다.
       → 'B1·VOLTGT 효과가 same-bar 집행 덕분이었나'를 직접 확인."""
    global SIGNAL_LAG
    init = init or HOLD_CAP; pool_ratio = HOLD_POOL if pool_ratio is None else pool_ratio
    G = G or HOLD_G; buy_limit = buy_limit or HOLD_LIMIT

    print("\n" + "=" * 100)
    print("  🔬 [신호지연 진단] v1(당일신호·당일집행) vs v2(전일신호·당일집행=봇 정합)")
    print("     ΔCAGR/ΔMDD = v2 − v1.  v1이 유리하게 나왔다면 그만큼이 '실전 불가능 이득'.")
    print("=" * 100)
    print(f"{'시작일':<13}{'v1 CAGR':>10}{'v2 CAGR':>10}{'ΔCAGR':>9}"
          f"{'v1 MDD':>10}{'v2 MDD':>10}{'ΔMDD':>9}{'v1 대피':>8}{'v2 대피':>8}")
    print("-" * 100)
    saved = SIGNAL_LAG
    for sd in START_DATES:
        sub = df[df.index >= sd]
        if END_DATE: sub = sub[sub.index <= END_DATE]
        if len(sub) < 300: continue
        SIGNAL_LAG = 0
        r0 = run_vr(sub, init, pool_ratio, G, buy_limit, killswitch=ON(KILLSWITCH))
        SIGNAL_LAG = 1
        r1 = run_vr(sub, init, pool_ratio, G, buy_limit, killswitch=ON(KILLSWITCH))
        print(f"{sd:<13}{r0['cagr']*100:>9.2f}%{r1['cagr']*100:>9.2f}%"
              f"{(r1['cagr']-r0['cagr'])*100:>+8.2f}%"
              f"{r0['mdd']*100:>9.2f}%{r1['mdd']*100:>9.2f}%"
              f"{(r1['mdd']-r0['mdd'])*100:>+8.2f}%"
              f"{r0['n_exit']:>8}{r1['n_exit']:>8}")
    SIGNAL_LAG = saved
    print("=" * 100)
    print("  · ΔMDD 음수 = v2에서 낙폭이 더 깊다 → v1이 하루 먼저 빠져나가 유리했던 것.")
    print("  · ΔCAGR 음수 = v2에서 수익이 낮다 → 같은 이유.")
    print("  · 차이가 작으면 B1·VOLTGT 결론은 그대로 유효. 크면 재검토 필요.")


# ══════════════ [7. 실행] ══════════════
if __name__ == "__main__":
    db = _drive_base()
    print("=" * 122)
    print("  라오어 VR v2 — 거치식·적립식·인출식 (+킬스위치/B1/VOLTGT) · 신호·집행 분리")
    print("=" * 122)
    df = build_data(db)
    print(f"  · 시계열: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}행) "
          f"| 버블 최신 {df['BUB'].iloc[-1]:.2f}")
    print(f"  · SIGNAL_LAG={SIGNAL_LAG} "
          f"({'봇 정합 — 전일 종가 신호 → 당일 종가 집행' if SIGNAL_LAG else 'v1 재현 — 당일 신호·당일 집행'})")

    # ★★ 결론부터 — 실데이터(2010~)만 ★★
    summary(df)

    if ON(RUN_HOLD):
        _table(df, f"거치식VR {HOLD_CAP:,.0f} (Pool{HOLD_POOL*100:.0f}%, G={HOLD_G}, "
                   f"한도{HOLD_LIMIT*100:.0f}%, 세후)",
               HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, 0.0, 0.0)
    if ON(RUN_DCA):
        _table(df, f"적립식VR (초기{DCA_INIT:.0f}, 격주적립{DCA_MONTHLY/2:.0f}, "
                   f"Pool{DCA_POOL*100:.0f}%, G={DCA_G}, 한도{DCA_LIMIT*100:.0f}%, 세후)",
               DCA_INIT, DCA_POOL, DCA_G, DCA_LIMIT, DCA_MONTHLY / 2, 0.0)
    if ON(RUN_WD):
        _table(df, f"인출식VR {WD_CAP:,.0f} (격주인출{WD_MONTHLY/2:.0f}, Pool{WD_POOL*100:.0f}%, "
                   f"G={WD_G}, 한도{WD_LIMIT*100:.0f}%, 세후·성과=NAV+인출누계)",
               WD_CAP, WD_POOL, WD_G, WD_LIMIT, 0.0, WD_MONTHLY / 2)

    print("\n" + "=" * 122)
    print("  · VR단독 = 킬스위치 OFF. 대피 0회면 VR+KS = VR단독. CAGR = VR+KS 세후.")
    print("  · V_next = V + pool/G + (적립−인출). 거치 G10/P10%/한도50 · 적립 G10/P0%/한도75 "
          "· 인출 G20/P20%/한도25")
    print("  · ★신호·집행 분리: 대피·복귀·VOLTGT는 전일 종가 신호로 당일 종가에 집행(봇=익일 LOC).")
    print("    밴드 매매(사다리)는 지정가 사전게시 → 당일 체결이 정당(지연 없음).")
    print("=" * 122)

    # LAG 진단 (v1이 얼마나 유리했나)
    try:
        lag_diagnostic(df)
    except Exception as e:
        print(f"  · LAG 진단 생략({str(e)[:60]})")

    if ON(CHART_ON):
        try:
            make_chart(df, CHART_START, mode=CHART_MODE)
        except Exception as e:
            print(f"  · 차트 생략({str(e)[:70]})")
