"""
===========================================================================
  [실전 모니터링 봇] 전술적 자산배분 — TQQQ/금 시스템 (FAST + 스마트 BOXX 대기)

  구조: 매일 1989년부터 전체 데이터를 다시 받아 상태머신을 처음부터 끝까지
        재계산한다. → 상태 영속화(파일 저장)가 불필요하다. 봇이 며칠 죽었다
        살아나도, 데이터만 있으면 현재 상태가 항상 정확히 복원된다.

  ★ 상태(3개) — 스마트 BOXX 대기:
    INVESTED   : 정상투자 (TQQQ + 금)
    CASH_USD   : 대피 직후. TQQQ 매도 → '달러(USD) 현금' 대기 (아직 BOXX 아님). 금 유지.
    CASH_BOXX  : 첫 월말에도 복귀 미충족 → 대기 달러를 BOXX로 전환한 장기 방어. 금 유지.

  ★ 신호 (FAST + 빠른복귀):
    - 대피(매일):      버블 ≥ 1.30 & 나스닥100 < 자기 200일선 (★2026-08-06 NDX 확정)
                       → TQQQ 전량 매도 → 달러 대기 (BOXX 즉시매수 안 함! 금 유지)
    - BOXX 전환(월말): 대피 후 '첫 월말'에 복귀 조건 미충족(진짜 하락장)
                       → 대기 달러 전액 → BOXX 매수 (금 유지)
    - 복귀(월말):      · 버블 ≥ 1.30 → S&P > 200일선 (기존 baseline)
                       · 버블 < 1.30 → S&P OR 나스닥100 중 먼저 200일선 돌파 (빠른복귀)
                       → 대기달러(또는 BOXX 매도)로 TQQQ 매수. 복귀 후 항상 S&P 기준.
                         빠른복귀(버블<1.30)면 TQQQ/금 평상시 비중(60:40) 전체 복원.
    - ★ 복귀 부스터B:  빠른복귀(버블<1.30, S&P/NDX 중 누가 먼저 넘었든) 진입 시
                       평상시 대신 부스터 비중으로 진입 권장(★60:40 확정 후 부스터=평상시라 사실상 무효).
                       (봇은 신호만 — 실제 비율 조절은 사람이. RECOVER_BOOST로 조정)
                       환원: 연말 리밸런싱 때 평상시 비중으로.
    - 연말 리밸런싱:   · INVESTED  → TQQQ:금 60:40 복원 (부스터 중이었으면 평상시로 환원)
                       · CASH_BOXX → 금:BOXX 40:60 복원 (방어 상태 정비)

  ★ M0 무결성 (백테스트와 동일):
    버블의 분모 M0(BOGMBASE)는 검증 가드(2008-05 ≈ 835B)를 통과한 소스만 채택한다.
    우선순위: ① 완전판 m0_full.csv → ② FRED → ③ 봇 캐시(전날값).
    FRED를 못 받으면 '보간'하지 않고 '전날 캐시 M0'를 그대로 쓰고, 보고서에
    "FRED 미수신 → 전날 캐시 M0 사용" 경고를 띄운다(M0는 월간 데이터라 안전).
    캐시조차 전혀 없는 극단적 경우(사실상 최초 실행에 FRED까지 죽음)에만
    신호 판정을 보류하고 경고를 보낸다. (가짜 M0로 잘못된 신호를 내지 않기 위함.)

  ★ 스마트 BOXX 대기의 핵심:
    대피해도 곧장 BOXX로 안 바꾸고 '달러'로 대기 → 첫 월말에 바로 복귀하면(휩소)
    달러로 TQQQ 재매수하여 BOXX 왕복 수수료를 통째로 절약. 진짜 하락장으로 확인되면
    (첫 월말 미복귀) 그때 BOXX로 전환해 이자를 수취. 금은 어느 경우에도 안 건드림.

  주의: 봇은 '신호만' 보낸다. 실제 매매는 사람이 다음 거래일 시가에 수동으로.
  설치: pip install yfinance pandas numpy requests pytz pandas_market_calendars
  환경변수: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, FRED_API_KEY (하드코딩 금지),
            HEALTHCHECK_URL(선택), BOT_CACHE_DIR(선택),
            M0_FULL_PATH(선택 — 백테스트가 만든 검증된 m0_full.csv 경로)
===========================================================================
"""

import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf
from pandas.tseries.offsets import CustomBusinessDay
from pandas.tseries.holiday import USFederalHolidayCalendar

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)


class M0Error(Exception):
    """M0(BOGMBASE) 확보·검증 실패 — 버블 계산 불가. main()에서 경고 후 신호 보류."""
    pass


# ==========================================
# [1. 설정]
# ==========================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
FRED_API_KEY = os.environ.get('FRED_API_KEY')   # 하드코딩 금지 — 환경변수/Secrets로만 주입
HEALTHCHECK_URL = os.environ.get('HEALTHCHECK_URL')   # healthchecks.io ping URL (선택)

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise EnvironmentError("환경변수 누락: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID")
if not FRED_API_KEY:
    # FRED 키가 없어도 m0_full.csv 또는 검증된 캐시가 있으면 동작.
    # 단, 셋 다 없으면 보간하지 않고 신호 판정을 보류한다(아래 load_m0_with_cache 참조).
    print("[경고] FRED_API_KEY 미설정 → m0_full.csv 또는 검증된 캐시가 있어야 M0 확보 가능")

BUBBLE_LIMIT = 1.30
TARGET_W = {'TQQQ': 0.60, 'GLD': 0.40}   # ★2026-08-02 은박사님 확정: TQQQ60:금40
# ★ 복귀 부스터B: NDX 단독 빠른복귀(S&P 아직 200일선 아래, 버블<1.30) 시 권장 비중.
#   봇은 '신호만' 보냄 — 실제 조절은 사람이. 이 숫자는 신호 텍스트에 표시될 안내값.
#   환원은 연말 리밸런싱 때 평상시(TARGET_W)로. 비율 바꾸려면 여기 한 곳만 수정.
RECOVER_BOOST = {'TQQQ': 0.60, 'GLD': 0.40}
FETCH_START = "1989-01-01"      # 백테스트와 동일 시작 (200일선·휩소 정확)
CACHE_DIR = os.environ.get('BOT_CACHE_DIR', '.')   # 캐시 CSV 저장 폴더
# 백테스트가 만든 검증된 완전판 M0. 있으면 최우선 사용(데이터 소스 일원화).
M0_FULL_PATH = os.environ.get('M0_FULL_PATH', os.path.join(CACHE_DIR, 'm0_full.csv'))

# ==========================================
# [2. 데이터 — CSV 캐시로 누락 방어]
# ==========================================
def _cache_path(name):
    return os.path.join(CACHE_DIR, f"cache_{name}.csv")

def _load_cache(name):
    """캐시 CSV 로드 → pd.Series(close, index=date). 없으면 None."""
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=['date'])
        s = df.set_index('date')['close'].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s[~s.index.duplicated(keep='last')].sort_index()
    except Exception as e:
        print(f"[캐시 로드 실패: {name}] {e}")
        return None

def _save_cache(name, series):
    """Series를 캐시 CSV로 저장 (원자적 쓰기)."""
    path = _cache_path(name)
    tmp = path + ".tmp"
    out = series.dropna().rename('close')
    out.index.name = 'date'
    out.to_csv(tmp)
    os.replace(tmp, path)

def _merge_series(cache, fresh, name):
    """캐시와 신규 데이터를 병합. 신규 우선, 신규에 없는 과거는 캐시가 채움.
       → yfinance가 과거를 누락해도 캐시가 메워 누락 방어.
       정합성 검증: 신규가 비정상이면 캐시만 사용."""
    if fresh is None or len(fresh) == 0:
        if cache is not None:
            print(f"[{name}] 신규 데이터 없음 → 캐시 사용")
            return cache
        raise RuntimeError(f"[{name}] 신규·캐시 모두 없음 — 진행 불가")

    fresh = fresh[~fresh.index.duplicated(keep='last')].sort_index()

    if cache is None:
        return fresh   # 최초 실행

    # 정합성 검증: 신규의 최근값이 비정상(0/음수/NaN)이면 캐시 우선
    last_val = fresh.iloc[-1]
    if pd.isna(last_val) or last_val <= 0:
        print(f"[{name}] 신규 최근값 비정상({last_val}) → 캐시 사용")
        return cache

    # 겹치는 구간에서 신규가 캐시와 크게 다르면(>50%) 데이터 오염 의심 → 캐시 우선
    overlap = fresh.index.intersection(cache.index)
    if len(overlap) >= 5:
        ratio = (fresh.loc[overlap] / cache.loc[overlap]).replace([np.inf, -np.inf], np.nan).dropna()
        if len(ratio) > 0:
            med = ratio.median()
            if med < 0.5 or med > 2.0:   # 중앙값이 2배 이상 차이 = 오염 의심
                print(f"[{name}] 신규-캐시 괴리 큼(중앙비 {med:.2f}) → 캐시 사용")
                return cache

    # 정상: 신규 우선 병합 (신규에 없는 과거 날짜는 캐시가 채움)
    merged = fresh.combine_first(cache).sort_index()
    return merged

def load_index_with_cache(ticker, name):
    """지수(^GSPC)를 캐시와 함께 로드. 신규는 야후에서, 과거는 캐시로 보강."""
    cache = _load_cache(name)
    fresh = None
    try:
        # 캐시가 있으면 최근 2년만, 없으면 1989부터 전체
        if cache is not None and len(cache) > 250:
            raw = yf.Ticker(ticker).history(period="2y")
        else:
            raw = yf.Ticker(ticker).history(start=FETCH_START)
        if raw is not None and len(raw) > 0:
            fresh = raw['Close'].copy()
            fresh.index = pd.to_datetime(fresh.index).tz_localize(None).normalize()
            fresh = fresh.dropna()
    except Exception as e:
        print(f"[{name}] 야후 다운로드 실패: {e} → 캐시 시도")

    merged = _merge_series(cache, fresh, name)
    _save_cache(name, merged)
    return merged


# ── M0 무결성 가드 (백테스트 load_m0_full과 동일 기준) ──
def _validate_m0(s):
    """2008-05 본원통화가 700~950B 범위여야 통과. 보간/오염/절단 데이터 차단.
       (실측 2008-05 ≈ 835B. 옛 보간 폴백은 ~1340B로 이 범위를 벗어나 걸러짐.)"""
    if s is None or len(s) == 0:
        return False
    t = pd.to_numeric(pd.Series(s.values, index=pd.to_datetime(s.index)), errors='coerce').dropna()
    if len(t) == 0:
        return False
    if t.max() > 100000:           # 백만달러 단위면 10억달러로 환산해 검사
        t = t / 1000.0
    seg = t[(t.index >= '2008-04-01') & (t.index <= '2008-06-30')]
    return len(seg) > 0 and 700 <= seg.mean() <= 950

def fetch_fred(series_id):
    """FRED에서 시리즈 수집 (API 키 사용)."""
    end = datetime.today().strftime('%Y-%m-%d')
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
           f"&observation_start={FETCH_START}&observation_end={end}")
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    data = r.json().get('observations', [])
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    return df.set_index('date')['value'].dropna()

def load_m0_with_cache():
    """M0(BOGMBASE)를 '검증과 함께' 로드. 보간 폴백 영구 제거.
       우선순위: ① 완전판 m0_full.csv → ② FRED(+캐시 병합) → ③ 봇 캐시(전날값).
       각 소스는 2008-05 ≈ 835B 검증을 통과해야 채택.
       ★ FRED 확보 실패 시 → '전날 캐시 M0'를 그대로 사용(M0는 월간 데이터라 안전).
         캐시조차 없을 때만 None 반환 → main()이 경고 후 신호 판정 보류.
       반환: (m0_series 또는 None, 날짜문자열, source)
             source ∈ {'file', 'fred', 'cache'(전날값 폴백), 'none'}"""
    # ① 완전판(백테스트와 동일 파일) — 있으면 최우선
    if os.path.exists(M0_FULL_PATH):
        try:
            dff = pd.read_csv(M0_FULL_PATH)
            s = pd.to_numeric(dff[dff.columns[-1]], errors='coerce')
            s.index = pd.to_datetime(dff[dff.columns[0]], errors='coerce')
            s = s.dropna().sort_index()
            s = s[~s.index.duplicated(keep='last')]
            if _validate_m0(s):
                return s, f"{s.index[-1].strftime('%Y-%m-%d')} (m0_full.csv)", 'file'
            print("[M0] m0_full.csv 검증 실패 → 다음 소스 시도")
        except Exception as e:
            print(f"[M0] m0_full.csv 로드 실패: {e} → 다음 소스 시도")

    cache = _load_cache('m0')

    # ② FRED 시도
    fresh = None
    if FRED_API_KEY:
        try:
            m0 = fetch_fred('BOGMBASE')
            if m0 is not None and len(m0) > 0:
                m0.index = pd.to_datetime(m0.index).tz_localize(None).normalize()
                fresh = m0
            else:
                print("[M0] FRED 응답 비어있음 → 전날 캐시 시도")
        except Exception as e:
            print(f"[M0] FRED 실패: {e} → 전날 캐시 시도")
    else:
        print("[M0] FRED_API_KEY 없음 → 전날 캐시 시도")

    # FRED 성공: 캐시와 병합 후 검증 → 최신값 사용
    if fresh is not None:
        try:
            merged = _merge_series(cache, fresh, 'm0')
        except RuntimeError:
            merged = None
        if merged is not None and _validate_m0(merged):
            _save_cache('m0', merged)
            return merged, merged.index[-1].strftime('%Y-%m-%d'), 'fred'
        print("[M0] FRED 병합본 검증 실패 → 전날 캐시 폴백 시도")

    # ③ FRED 실패/검증실패 → '전날 캐시 M0' 사용 (월간 데이터라 안전)
    if cache is not None and _validate_m0(cache):
        print("[M0] FRED 미확보 → 전날 캐시 M0 사용")
        return cache, cache.index[-1].strftime('%Y-%m-%d'), 'cache'

    # ④ 캐시조차 없음 → None (main에서 경고·보류)
    print("[M0] FRED·캐시 모두 없음 → 신호 판정 보류")
    return None, "M0 확보·검증 실패", 'none'

def get_data():
    """S&P500, 나스닥100, M0를 캐시 기반으로 받아 지표 데이터프레임 생성.
       캐시가 과거를 보존하므로 yfinance가 과거를 누락해도 안전.
       M0 확보·검증 실패 시 M0Error를 던진다(보간하지 않음)."""
    gspc_close = load_index_with_cache('^GSPC', 'gspc')
    ndx_close = load_index_with_cache('^NDX', 'ndx')

    m0_series, m0_date_str, m0_source = load_m0_with_cache()
    if m0_series is None:
        raise M0Error("M0(BOGMBASE) 확보·검증 실패 — m0_full.csv·FRED·캐시 모두 불가/오염")

    df = pd.DataFrame(index=gspc_close.index)
    df['GSPC_RAW'] = gspc_close
    df['SPY_SMA200'] = df['GSPC_RAW'].rolling(200).mean()
    df['NDX_RAW'] = ndx_close.reindex(df.index).ffill()
    df['NDX_SMA200'] = df['NDX_RAW'].rolling(200).mean()

    m0_b = m0_series.resample('B').ffill()
    if m0_b.max() > 100000:
        m0_b = m0_b / 1000.0
    df['M0'] = m0_b.reindex(df.index).ffill().bfill()
    df['Bubble_Value'] = df['GSPC_RAW'] / df['M0']

    df = df.dropna(subset=['GSPC_RAW', 'SPY_SMA200', 'NDX_RAW', 'NDX_SMA200', 'Bubble_Value'])
    return df, m0_date_str, m0_source

# ==========================================
# [3. 상태머신 — FAST + 스마트 BOXX (3상태) + 모든 전이 기록]
# ==========================================
# NYSE 거래소 캘린더 (Good Friday 등 거래소 단독 휴장일 반영)
try:
    import pandas_market_calendars as mcal
    _NYSE = mcal.get_calendar('NYSE')
    _HAS_MCAL = True
except Exception:
    _NYSE = None
    _HAS_MCAL = False
    print("[경고] pandas_market_calendars 미설치 → 연방휴일 근사 사용. "
          "정확도를 위해 'pip install pandas_market_calendars' 권장.")

def _next_trading_day(d):
    """d 다음의 첫 거래일 (NYSE 휴장일 반영). 마지막 날의 월말/연말 판정용."""
    d = pd.Timestamp(d).normalize()
    if _HAS_MCAL:
        sched = _NYSE.schedule(start_date=(d + pd.Timedelta(days=1)).date(),
                               end_date=(d + pd.Timedelta(days=15)).date())
        if len(sched) > 0:
            return pd.Timestamp(sched.index[0]).normalize()
    # 폴백: 연방휴일 기준
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return (d + us_bd).normalize()

def run_state_machine(df):
    """1989부터 끝까지 FAST+스마트BOXX 상태머신을 돌리며 '모든 전이'를 날짜와 함께 기록.
       반환: dict(현재 state, signals=[(날짜,액션,상세)...], ...)
       → main()에서 '마지막 보고일 이후' 신호만 골라 보고 (하루 걸러도 안 놓침).

       ★ 3상태 (INVESTED / CASH_USD / CASH_BOXX):
         - 대피(매일):      버블 ≥ 1.30 & 나스닥100 < 자기 200일선 → CASH_USD (★NDX 확정, 금 유지)
         - 복귀(월말):      버블≥1.30 → S&P>200일선 / 버블<1.30 → S&P OR NDX 먼저 돌파
                            → INVESTED (대기달러/BOXX로 TQQQ 매수)
         - BOXX전환(월말):  CASH_USD에서 첫 월말 복귀 미충족 → CASH_BOXX (달러→BOXX)
         - 연말 리밸런싱:   INVESTED → TQQQ:금 60:40 / CASH_BOXX → 금:BOXX 40:60

       대피 다음날 실행이 아니라 '판정일' 기준으로 상태를 전이한다(신호=다음 거래일
       시가 실행 지시). 매일 전체 재계산이므로 CASH_USD/CASH_BOXX가 정확히 복원된다."""
    dates = df.index
    state = 'INVESTED'

    last_i = len(dates) - 1
    signals = []   # [(date, action, detail), ...] — 모든 전이 기록

    for i in range(len(dates)):
        cd = dates[i]
        p = df.iloc[i]
        is_last = (i == last_i)

        # 다음 거래일 (월말·연말 판정). 마지막 날은 NYSE 캘린더로 계산.
        if not is_last:
            nd = dates[i+1]
        else:
            nd = _next_trading_day(cd)
        is_month_end = (cd.month != nd.month)
        is_year_end = (cd.year != nd.year)

        gspc = p['GSPC_RAW']; gsma = p['SPY_SMA200']
        ndx = p['NDX_RAW']; nsma = p['NDX_SMA200']
        bub = p['Bubble_Value']

        if state == 'INVESTED':
            # 대피(매일): 버블 ≥ 1.30 AND 나스닥100 < 자기 200일선 → 달러 대기(CASH_USD)
            #   ★2026-08-06 은박사님 확정: 탈출 추세지수 GSPC→NDX (버블 정의·복귀 규칙 불변)
            if bub >= BUBBLE_LIMIT and ndx < nsma:
                state = 'CASH_USD'
                signals.append((cd, 'go_cash', {'gspc': gspc, 'gsma': gsma,
                                'ndx': ndx, 'nsma': nsma, 'bub': bub}))

        elif state in ('CASH_USD', 'CASH_BOXX') and is_month_end:
            # ★ 복귀(월말) — 빠른복귀(fast_recover):
            #   · 버블 ≥ 1.30 → S&P 단독 200일선 돌파 (기존 baseline)
            #   · 버블 < 1.30 → S&P OR NDX 중 먼저 200일선 돌파 (빠른 복귀)
            spx_ok = gspc > gsma
            recovered = False
            who = None
            note = None
            if bub < BUBBLE_LIMIT:
                ndx_ok = ndx > nsma
                if spx_ok or ndx_ok:
                    who = 'S&P+NDX' if (spx_ok and ndx_ok) else ('S&P' if spx_ok else 'NDX')
                    recovered = True
                    note = 'fast_recover'
            else:
                if spx_ok:
                    who = 'S&P'
                    recovered = True
                    note = 'recover_spx_only'

            if recovered:
                frm = state
                state = 'INVESTED'
                signals.append((cd, 'go_invest', {'gspc': gspc, 'gsma': gsma, 'ndx': ndx,
                                'nsma': nsma, 'bub': bub, 'from': frm, 'who': who, 'note': note}))
            elif state == 'CASH_USD':
                # ★ 첫 월말에도 복귀 미충족 = 진짜 하락장 → 달러를 BOXX로 전환
                state = 'CASH_BOXX'
                signals.append((cd, 'go_boxx', {'gspc': gspc, 'gsma': gsma, 'bub': bub}))

        # 연말 리밸런싱. 대피 등과 독립적으로 기록.
        #   INVESTED → TQQQ:금 60:40 / CASH_BOXX → 금:BOXX 40:60 (방어 정비)
        #   단, 같은 날 fast_recover 복귀가 이미 평상시 비중 전체 복원을 했으면 중복 → 생략.
        if is_year_end and state in ('INVESTED', 'CASH_BOXX'):
            _just_fast = (signals and signals[-1][0] == cd and signals[-1][1] == 'go_invest'
                          and signals[-1][2].get('note') == 'fast_recover')
            if not _just_fast:
                signals.append((cd, 'rebalance', {'state': state}))

    return {
        'state': state,
        'signals': signals,
        'is_month_end': is_month_end, 'is_year_end': is_year_end,
        'last_row': df.iloc[-1], 'last_date': dates[-1],
    }

# ==========================================
# [4. 리포트]
# ==========================================
STATE_KR = {
    'INVESTED': '정상투자 (INVESTED)',
    'CASH_USD': '대피·달러대기 (CASH_USD — TQQQ 매도→달러, 금 유지)',
    'CASH_BOXX': 'BOXX 방어 (CASH_BOXX — 달러→BOXX 전환됨, 금 유지)',
}

def _signal_text(action, det):
    """단일 신호(action, detail)를 사람이 읽을 텍스트로."""
    if action == 'go_cash':
        return ("🔴 <b>대피 신호</b>\n"
                "👉 시가에 <b>TQQQ 전량 매도 → 달러(USD) 현금 대기</b> (금은 그대로 유지)\n"
                "   <i>※ 아직 BOXX로 바꾸지 마세요. 다음 '월말'에 복귀/BOXX전환을 판정합니다.</i>\n"
                f"   (버블 {det['bub']:.3f} ≥1.30, 나스닥100 {det.get('ndx', 0):.2f} &lt; 200일선 {det.get('nsma', 0):.2f} · "
                f"참고 S&amp;P {det['gspc']:.2f} / 200일선 {det['gsma']:.2f})")
    if action == 'go_boxx':
        return ("🟠 <b>BOXX 전환 신호</b> (진짜 하락장 확인)\n"
                "👉 시가에 <b>대기 중인 달러 전액 → BOXX 매수</b> (금은 그대로 유지)\n"
                "   <i>※ 대피 후 첫 월말에도 복귀 조건 미충족 → 장기 방어 태세로 전환.</i>\n"
                f"   (버블 {det['bub']:.3f}, S&amp;P {det['gspc']:.2f} / 200일선 {det['gsma']:.2f})")
    if action == 'go_invest':
        frm = det.get('from', 'CASH_USD')
        who = det.get('who', 'S&P')
        note = det.get('note', '')
        src_line = ("👉 시가에 <b>대기 달러로 TQQQ 매수</b>" if frm == 'CASH_USD'
                    else "👉 시가에 <b>BOXX 매도 → TQQQ 매수</b>")
        if note == 'fast_recover':
            # ★ 모든 빠른복귀(버블<1.30)에 부스터: S&P/NDX 중 누가 먼저 넘었든 부스터.
            #   거품 빠진 바닥에서의 복귀는 강하다 → 평상시보다 TQQQ를 더 싣고 진입.
            _bt = int(RECOVER_BOOST['TQQQ'] * 100)
            _bg = int(RECOVER_BOOST['GLD'] * 100)
            _nt = int(TARGET_W['TQQQ'] * 100)
            _ng = int(TARGET_W['GLD'] * 100)
            if RECOVER_BOOST == TARGET_W:
                # ★2026-08-06: 평상시=60:40 확정 → 부스터=평상시(무효). 안내만 평상시로.
                tail = f" → <b>평상시 비중(TQQQ {_nt}:금 {_ng})으로 복원</b>"
            else:
                tail = (f" → 🚀 <b>부스터 복귀</b>: TQQQ {_nt}:금 {_ng} → "
                        f"<b>TQQQ {_bt}:금 {_bg}</b> (부스터 비율로 진입)")
            if who == 'NDX':
                _lead = "나스닥100이 S&amp;P보다 먼저 200일선 돌파"
            elif who == 'S&P':
                _lead = "S&amp;P가 나스닥100보다 먼저 200일선 돌파"
            else:  # S&P+NDX
                _lead = "S&amp;P·나스닥100 동시 200일선 돌파"
            _hint = ("   👉 평상시 비중 대신 <b>TQQQ를 더 싣고</b>(금에서 재원) 진입하세요. "
                     "환원은 연말 리밸런싱 때 평상시 비중으로.\n"
                     if RECOVER_BOOST != TARGET_W else
                     "   👉 <b>평상시 비중 그대로</b> 진입하세요(60:40 확정으로 부스터=평상시).\n")
            cond = ("   🚀 <b>빠른복귀</b>: 버블 진정 국면(&lt;1.30), "
                    + _lead + "\n"
                    + _hint +
                    f"   (S&amp;P {det['gspc']:.2f} / 200일선 {det['gsma']:.2f}, "
                    f"NDX {det.get('ndx', 0):.2f} / 200일선 {det.get('nsma', 0):.2f}, "
                    f"버블 {det.get('bub', 0):.3f}&lt;1.30)")
        else:
            tail = " (금은 그대로 유지)"
            cond = (f"   (S&amp;P {det['gspc']:.2f} &gt; 200일선 {det['gsma']:.2f}, "
                    f"버블 {det.get('bub', 0):.3f} ≥1.30)")
        return ("🟢 <b>복귀 신호</b>\n" + src_line + tail + "\n" + cond)
    if action == 'rebalance':
        if det.get('state') == 'CASH_BOXX':
            return ("🟡 <b>연말 정기 리밸런싱 (방어 상태)</b>\n"
                    f"👉 시가에 <b>금:BOXX = {int(TARGET_W['GLD']*100)}:{int(TARGET_W['TQQQ']*100)} 비중 복원</b>\n"
                    "   (현금대피 중 — TQQQ 없이 금/BOXX만 재조정)")
        return ("🟡 <b>연말 정기 리밸런싱</b>\n"
                f"👉 시가에 <b>TQQQ:금 = {int(TARGET_W['TQQQ']*100)}:{int(TARGET_W['GLD']*100)} 비중 복원</b>\n"
                "   (보유 상태 유지, 비중만 재조정)\n"
                "   <i>※ 만약 부스터 복귀로 비중을 바꿔둔 상태라면, "
                f"지금 평상시 TQQQ {int(TARGET_W['TQQQ']*100)}:금 {int(TARGET_W['GLD']*100)}으로 환원하세요.</i>")
    return ""

def build_report(res, m0_date_str, m0_source, new_signals):
    """new_signals: 마지막 보고일 이후 발생한 미보고 신호 [(date, action, detail)...].
       여러 개면 모두 표시 (하루 걸러도 안 놓침).
       m0_source: 'file'/'fred'/'cache'(전날값 폴백) — cache면 보고서에 경고 표시."""
    p = res['last_row']
    d = res['last_date']
    state = res['state']

    r = "📊 <b>[전술적 자산배분 봇] 일일 보고서</b>\n"
    r += f"📅 기준일: {d.strftime('%Y-%m-%d')}\n"
    r += "-"*30 + "\n"
    r += f"🛡️ 현재 상태: <b>{STATE_KR.get(state, state)}</b>\n"
    if m0_source == 'cache':
        r += ("⚠️ <b>M0 주의</b>: FRED 미수신 → <b>전날 캐시 M0 사용</b>\n"
              "   (M0는 월간 발표라 버블 영향은 거의 없음. FRED 복구되면 자동 정상화)\n")
    r += "-"*30 + "\n\n"

    r += "📈 <b>지표</b>\n"
    r += (f"• S&amp;P500: {p['GSPC_RAW']:.2f} (200일선 {p['SPY_SMA200']:.2f}, "
          f"{(p['GSPC_RAW']/p['SPY_SMA200']-1)*100:+.1f}%)\n")
    r += (f"• 나스닥100: {p['NDX_RAW']:.2f} (200일선 {p['NDX_SMA200']:.2f}, "
          f"{(p['NDX_RAW']/p['NDX_SMA200']-1)*100:+.1f}%) ← 탈출 판정 지수\n")
    r += f"• 버블(GSPC/M0): {p['Bubble_Value']:.4f} (기준 {BUBBLE_LIMIT:.2f})\n"
    _m0_tag = m0_date_str + (" — 전날 캐시(FRED 미수신)" if m0_source == 'cache' else "")
    r += f"  <i>※ M0 소스: {_m0_tag}</i>\n\n"

    r += "📆 <b>[행동 판독]</b>\n"
    if new_signals:
        if len(new_signals) > 1:
            r += f"⚠️ <b>미보고 신호 {len(new_signals)}건</b> (봇 미실행 기간 발생분 일괄 보고)\n\n"
        for sd, act, det in new_signals:
            r += f"📌 <b>{sd.strftime('%Y-%m-%d')}</b>\n"
            r += _signal_text(act, det) + "\n\n"
        r += "⚠️ <i>실행 안 한 신호가 있으면 지금이라도 해당 비중으로 조정하세요.</i>\n"
    else:
        if state == 'CASH_USD':
            r += "ℹ️ 대피·달러 대기 중. 다음 '월말'에 복귀 또는 BOXX전환을 판정 → 지금은 달러 유지.\n"
        elif state == 'CASH_BOXX':
            r += "ℹ️ BOXX 방어 중. 복귀는 '월말'에만 심사 → 포지션 유지.\n"
            r += "   (버블&lt;1.30이면 나스닥100 선행 돌파 시 빠른복귀 가능)\n"
        else:
            r += "✅ 신호 없음. 현재 포지션 유지.\n"

    return r

# ==========================================
# [5. 텔레그램 / 메인]
# ==========================================
def send_telegram(text):
    """4096자 제한 방어: 줄 단위로 분할 전송.
       줄 경계로 자르므로 <b>...</b> 등 HTML 태그가 줄 안에서 닫혀 안전.
       (봇이 장기간 멈췄다 살아나 미보고 신호가 많이 쌓여도 전송 실패 안 함)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    MAX = 4000   # 4096 한계에 여유
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > MAX and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    for c in chunks:
        r = requests.post(url, data={'chat_id': CHAT_ID, 'text': c,
                                     'parse_mode': 'HTML'}, timeout=20)
        r.raise_for_status()

# 마지막으로 '신호를 보고한 날짜'만 기록 (상태는 영속화 안 함, 이 한 줄만).
REPORT_MARK = os.path.join(CACHE_DIR, "last_report_date.txt")

def _load_last_report_date():
    if not os.path.exists(REPORT_MARK):
        return None
    try:
        with open(REPORT_MARK) as f:
            return pd.Timestamp(f.read().strip()).normalize()
    except Exception:
        return None

def _save_last_report_date(d):
    tmp = REPORT_MARK + ".tmp"
    with open(tmp, "w") as f:
        f.write(pd.Timestamp(d).strftime("%Y-%m-%d"))
    os.replace(tmp, REPORT_MARK)

def main():
    # 장중 실행 차단 (뉴욕시간 9:30~16:30). raise 대신 조용히 종료 → cron 로그 깔끔.
    # 16:30까지 버퍼: Yahoo 종가 봉이 16:15~16:20경 확정되므로 그 이후에만 판정.
    ny = datetime.now(pytz.timezone('America/New_York'))
    ny_float = ny.hour + ny.minute / 60.0
    if 9.5 <= ny_float < 16.5:
        print("미국 정규장/마감직후 → 종료 (종가 확정 후 실행).")
        return

    print("▷ 데이터 수집 및 상태 재계산 중...")
    # ★ M0: FRED 실패 시 전날 캐시 사용(보고서에 경고). 캐시조차 없을 때만 보류.
    try:
        df, m0_date_str, m0_source = get_data()
    except M0Error as e:
        warn = ("🆘 <b>M0 확보 완전 실패</b> (FRED·전날 캐시 모두 없음)\n"
                f"<code>{e}</code>\n"
                "→ 쓸 수 있는 M0가 전혀 없어 버블 계산 불가. <b>오늘 신호 판정을 보류</b>합니다 "
                "(킬스위치 감시 일시 중단).\n"
                "점검: FRED_API_KEY / 네트워크 (보통 캐시가 있어 여기까지 오지 않음).\n"
                "<i>※ 가짜 M0로 잘못된 대피·복귀 신호를 내는 것을 막기 위한 의도된 보류입니다.</i>")
        print(warn.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                  .replace('<code>', '').replace('</code>', ''))
        try:
            send_telegram(warn)
        except Exception as se:
            print(f"[M0 경고 전송 실패] {se}")
            _emergency_telegram(warn)
        return

    res = run_state_machine(df)

    # ── 미보고 신호 수집 (★ 봇이 하루 걸러도 안 놓침) ──
    # 마지막 보고일 이후 발생한 모든 전이를 모은다. 최초 실행이면 '마지막 날'만.
    last_rep = _load_last_report_date()
    all_signals = res['signals']
    if last_rep is None:
        # 최초: 마지막 거래일에 발생한 신호만 (과거 신호 소급 폭탄 방지)
        new_signals = [(d, a, det) for (d, a, det) in all_signals
                       if pd.Timestamp(d).normalize() == res['last_date'].normalize()]
    else:
        # 마지막 보고일 '이후' 발생분 전부
        new_signals = [(d, a, det) for (d, a, det) in all_signals
                       if pd.Timestamp(d).normalize() > last_rep]

    report = build_report(res, m0_date_str, m0_source, new_signals)

    # ── 데이터 신선도 점검 (yfinance가 신규 실패→캐시만 쓰면 기준일이 굳음) ──
    # 마지막 데이터 날짜가 오늘 기준 거래일 3일 이상 뒤처지면 경고를 머리에 붙임.
    try:
        ny_today = datetime.now(pytz.timezone('America/New_York')).date()
        stale = int(np.busday_count(res['last_date'].date(), ny_today))
        if stale >= 3:
            report = (f"⚠️ <b>데이터 지연 경고</b>\n"
                      f"마지막 데이터: {res['last_date'].strftime('%Y-%m-%d')} "
                      f"(오늘 기준 거래일 {stale}일 뒤처짐)\n"
                      f"→ yfinance/FRED 수급 점검 필요. 아래 보고서는 옛 데이터일 수 있음.\n"
                      + "-"*30 + "\n\n") + report
    except Exception:
        pass   # 신선도 점검 실패가 본 보고를 막지 않도록

    print(report.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                .replace('&lt;', '<').replace('&gt;', '>'))
    # ★ 전송 성공 시에만 보고일 갱신 → 실패하면 다음 실행에서 같은 신호 재시도.
    #   (전송 실패해도 무조건 저장하면 그 신호를 '이미 보고함'으로 건너뛰어 영구 누락.
    #    특히 대피(go_cash)·BOXX전환(go_boxx) 신호가 사라지면 위기 대응을 통째로 놓침.)
    #   부분 전송(청크1 성공, 청크2 실패) 시엔 다음 실행에서 청크1이 중복될 수 있으나,
    #   매일 재계산·재전송 구조라 중복은 무해. 누락을 막는 안전한 트레이드오프.
    sent_ok = False
    try:
        send_telegram(report)
        sent_ok = True
        print("\n✅ 텔레그램 전송 성공")
    except Exception as e:
        print(f"\n❌ 텔레그램 전송 실패: {e}")

    if sent_ok:
        _save_last_report_date(res['last_date'])
        _ping_healthcheck()   # 정상 완주 신호. 24h 무소식이면 healthchecks.io가 직접 알림.
    else:
        print("⚠️ 전송 실패 → 보고일 미갱신. 다음 실행에서 동일 신호를 재시도합니다.")
        # ping 안 보냄: 전송 실패는 '미완수'로 취급 → 계속 실패하면 healthcheck가 잡아줌

def _ping_healthcheck():
    """healthchecks.io 등에 정상 완주 ping. 24시간 ping이 없으면 외부 서비스가
       박사님께 알림 → cron 자체가 안 돌거나 머신이 죽는 경우까지 잡는 진짜
       dead-man's switch. URL 미설정이거나 ping 실패해도 본 로직엔 영향 없음."""
    if not HEALTHCHECK_URL:
        return
    try:
        requests.get(HEALTHCHECK_URL, timeout=10)
    except Exception as e:
        print(f"[healthcheck ping 실패] {e}")

def _emergency_telegram(text):
    """크래시 시 최소 의존성으로 알림. send_telegram이 못 쓸 상황(import 등) 대비.
       토큰/챗ID가 없거나 전송 실패해도 조용히 무시(이중 크래시 방지)."""
    try:
        tok = os.environ.get('TELEGRAM_TOKEN')
        cid = os.environ.get('TELEGRAM_CHAT_ID')
        if not tok or not cid:
            return
        import requests as _rq
        _rq.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                 data={'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}, timeout=20)
    except Exception:
        pass

if __name__ == "__main__":
    # ── 침묵 실패 방어 ──
    # 이 봇에서 '침묵'은 "신호 없음(정상)"과 "봇이 죽음"이 구분 안 됨 → 가장 위험.
    # main()이 어디서 터지든 텔레그램으로 비명을 질러, 죽은 걸 알 수 있게 함.
    # 단, cron 자체가 안 돌거나 머신이 죽으면 이 코드도 실행 안 됨 → 외부 감시
    # (healthchecks.io ping, cron MAILTO 등)를 병행하는 것이 진짜 dead-man's switch.
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _emergency_telegram(f"🆘 <b>봇 실행 실패</b>\n<code>{type(e).__name__}: {e}</code>\n"
                            f"→ 로그 점검 필요. 킬스위치 감시가 중단됐을 수 있음.")
        raise
