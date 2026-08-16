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
#   F7(2026-08-01 은박사 확정): 미실현 잠재세 일별 차감 폐지 → VR v3 방식으로 통일.
#       일별 NAV = 자산 − '확정' 세부채만. 잠재세는 팔아야 생기는 조건부 청구권이며
#       완충폭이 내재이익 크기에 따라 불규칙(±0.5~6%p)해 MDD 비교축을 깨뜨렸음.
#       최종 세후액은 종전과 동일(실현 기준 정산 불변) — MDD·샤프 표시만 정직해짐.
#       벤치마크(SPY/QQQ/QLD)도 동일 방식(경로=세전, 최종값=만기 청산 세후)으로 통일.
#       MDD·변동성은 '만기 청산 전 경로'로 계산(마지막 날 세금 절벽이 MDD 오염 방지, VR v3 정의와 동일).
#   F8(2026-08-01 은박사 확정): 수수료 토스 실측 정합 — COMMISSION 0.07%→0.10%,
#       슬리피지 0.2%→0(지정가 체결 가정, VR v3와 동일). 결과: 미국주식 편도 0.27%→0.10%,
#       gold 0.5%→0.3%(KRX 금현물 온라인 수수료 실측 범위 — 토스 미국주식 요율 비적용 자산),
#       BOXX 0.12%→0.15%(스프레드 0.05% + 수수료 0.10%).
#   F9(2026-08-01 은박사 확정): 양도세 기본공제 환율을 VR v3와 통일 — 연 250만원 ÷ ₩1,400
#       = $1,785.71 (종전 $1,724 = 환율 약 1,450 환산분). 원화 정의 + 명시 환산 구조로 교체.
#       공제는 연 1회·이월 없음·손실해 소멸(현행 세법). 세금이 소폭 줄어 결과는 미미하게 상향.
#   F10(2026-08-01 은박사 확정): gold 매매비용 0.30%→0. 종전 0.30%는 Claude가 근거 없이
#       넣은 추정치였음("KRX 실측 범위"로 표기했으나 실제 측정치 아님 — 은박사 지시로 0 확정).
#   F11(2026-08-01 은박사 지시): 연구용 섹션 출력 스위치 SHOW_LAB(기본 False) 신설.
#       [5f]복귀 부스터B · [5g]다중 윈도우 강건성 · [5h]고버블 구간 절단 — 세 섹션을
#       SHOW_LAB=True일 때만 출력. 계산 로직·메인 표·[5a]·매매로그·차트는 무변경.
#   F12(2026-08-01 은박사 지시): TQQQ 단독 보유(세후) 비교 추가 — 메인 벤치 표 첫 행,
#       [5a] 시작일별 표(각 시작일 A/B 아래 1행, 대피 열 '-'), 차트 점선. 산식은 기존
#       run_bh_aftertax('TQQQ') 그대로(F7 방식: 경로 세전, 최종만 만기 청산 세후).
#   F13(2026-08-01 은박사 지시): QLD 단독 보유(세후)도 [5a] 시작일별 표에 추가(TQQQ단독 아래).
#       메인 벤치 표·차트에는 종전부터 존재 — [5a]만 신규. 산식 동일(run_bh_aftertax('QLD')).
#   F14(2026-08-01 은박사 지시): QQQ·SPY 단독 보유(세후)도 [5a]에 추가 — 벤치 전 종목 수록.
#       행 순서 = A / B / TQQQ / QLD / QQQ / SPY (레버리지 내림차순). 산식 동일.
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
END_DATE = "2026-07-10"   # 데이터 다운로드 상한
# ★종료일 스윗(2026-08-08 은박사님 지시) — VR 스윗판과 동일 리스트:
END_DATES = ["2018-12-31", "2020-12-31", "2021-12-31", "2022-12-30", "2024-12-31", "2026-07-10"]

# ★ 메인 A vs B 성과표를 여러 시작일 각각으로 돌려 비교 (전체기간 표 아래에 추가 출력).
#   빈 리스트 []면 이 비교표 생략(전체기간만).
START_DATES = ["1986-08-11", "1994-01-02", "1998-01-02", "2000-01-02", "2010-02-11",
               "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]

INITIAL_CAPITAL = 100_000.0

W_A = {'TQQQ': 0.60, 'gold': 0.40}   # A: FAST + gold(비과세)
W_B = {'TQQQ': 0.50, 'gold': 0.50}   # B: FAST + (양도세)

BUBBLE_LIMIT = 1.30
TAX_RATE_EQUITY = 0.22
# ★F9(2026-08-01 은박사 확정): 공제 환율을 VR v3와 1,400으로 통일.
#   공제는 원화(연 250만원 인별 기본공제)이고 이 백테스트는 전액 USD이므로 환산을 명시한다.
#   종전 1,724는 환율 약 1,450 환산분 — 두 백테스터 비교 시 축이 어긋나 통일.
#   · 이 계좌가 매년 전액 사용 가정. 연 1회, 미사용분 이월 없음, 손실해 소멸.
#   · 환율↑ → 공제USD↓ → 세금↑ 방향이라 1,400은 보수 쪽(1,450 대비 공제가 커져 세금은 소폭 감소).
#   · 연도별 실환율·환차손익은 모델 밖(USD 백테스트의 구조적 한계).
TAX_DEDUCTION_KRW = 2_500_000.0
FX_KRWUSD = 1_400.0
TAX_EXEMPTION = TAX_DEDUCTION_KRW / FX_KRWUSD   # ≈ $1,785.71 (종전 1,724.0)
NORMAL_SLIPPAGE = 0.0     # ★F8: 지정가 체결 가정(VR v3 정합). 종전 0.002
COMMISSION = 0.001        # ★F8: 토스 실측 편도 0.1%. 종전 0.0007
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

# ★F11: 연구용 섹션([5f] 부스터B / [5g] 다중 윈도우 강건성 / [5h] 고버블 구간 절단) 출력 여부.
#   False(기본) = 세 섹션 출력 생략(계산도 건너뜀 — 실행시간 단축). True = 종전대로 전부 출력.
SHOW_LAB = False

# ★K1(2026-08-06 사양서 K1~K7): 탈출지수 실험 파라미터 — 측정 장치이며 실전 규칙 변경 아님.
#   EXIT_INDEX: 탈출(대피) '추세 판정' 지수 선택. 버블 정의(GSPC/M0)는 불변 — 게이트와 무관.
#   GATE_MODE : "ABS"=버블≥BUBBLE_LIMIT(현행과 수학적 동치) | "B1"=버블 10년 롤링 백분위≥B1_PCTL | "NONE"=상시 개방.
#   EXIT_LAB  : True일 때만 [5e] 3축(게이트)×2지수 실험 섹션 실행(F11 SHOW_LAB과 같은 패턴).
#   ※ 기본값(GSPC/ABS/False)이면 신호가 현행과 동치 → K7 회귀 기준.
EXIT_INDEX = "NDX"    # "GSPC" | "NDX" — 탈출 추세 판정 지수 ★2026-08-06 은박사님 확정: NDX
GATE_MODE  = "ABS"    # "ABS" | "B1" | "NONE"
B1_PCTL    = 0.75
EXIT_LAB   = False

# ★K8(2026-08-06 사양서 K8~K12): 복귀지수 실험 파라미터 — 측정 장치이며 실전 규칙 변경 아님.
#   REC_HOT_INDEX: 핫게이트(게이트 열림) 재진입 '회복 판정' 지수. "GSPC"=현행 recover_spx_only와 동치.
#   REC_LAB      : True일 때만 [5i] 복귀지수 실험 섹션 실행(EXIT_LAB과 같은 패턴).
#   ※ 냉게이트(게이트 닫힘) 빠른복귀(S&P/NDX 병용)·부스터 로직은 대상 아님(무변경 — 사양 K8 범위 제한).
#   ※ 기본값(GSPC/False)이면 신호·로그가 K판(bc9d8f3a)과 바이트 동일 → K12 회귀 기준.
REC_HOT_INDEX = "GSPC"   # "GSPC"=현행 recover_spx_only | "NDX"=고버블 재진입도 NDX 회복 기준
REC_LAB = False          # True일 때만 [5i] 복귀지수 실험 섹션 실행

# ★K13(2026-08-07 사양서 K13): 위험계기판(VaR/cVaR) 파라미터 — 측정 전용, 매매 로직·신호·비중·세제 무접촉.
#   VaR(Value at Risk)=하루 손실의 하위 분위수, cVaR=그 초과일들의 평균 손실. 실측 분포 기반(정규 가정 없음).
VAR_LAB          = True        # True일 때만 [5v] 섹션 실행
VAR_LEVELS       = (0.95, 0.99) # 신뢰수준
VAR_ACCOUNT_USD  = 200000.0     # 원화 환산 문장용 계좌 규모(측정 표시 전용)
VAR_FX           = 1400.0       # 환산 환율(백테스터 세금 공제 환산과 동일 값)
VAR_RECENT_YEARS = 1            # 최근 구간 표의 길이(연말 점검용)

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
    # ★K2(2026-08-06): 버블 10년 롤링 백분위 — VR B1 블록 로직 불변 이식(사양서 K2).
    #   원형(칠판 리포 mume_v4_colab.py 2026-07-31 판, 07-24 판까지 동일 확인):
    #     "# B1: 버블의 롤링 백분위 (당일 포함 = 그 시점까지의 정보만. 미래 없음)"
    #     w = int(252 * B1_WIN_Y);  out["BUB_PCTL"] = out["BUB"].rolling(w,
    #         min_periods=int(252 * 3)).apply(lambda x: (x[-1] >= x).mean(), raw=True)
    #   윈도우 int(252*10)=2520일·min_periods int(252*3)=756일·정의 (x[-1] >= x).mean() 원형 그대로.
    #   변수명만 어댑트: BUB→Bubble_Value, BUB_PCTL→Bubble_Pctl, B1_WIN_Y(=10) 인라인.
    #   _need에 미포함(사양 K2 — 초기구간 잘림 방지). min_periods 미달 초기 ~3년은 NaN → B1게이트 미발동.
    _b1_w = int(252 * 10)
    df_usd['Bubble_Pctl'] = df_usd['Bubble_Value'].rolling(_b1_w, min_periods=int(252 * 3)).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)

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

def _calc_tax(hold, eq_p, row):
    """★F7 이후 미사용(잠재세 일별 차감 폐지 — VR v3 방식). 참고·롤백용으로만 보존."""
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

def run_bh_aftertax(df, ic, t):
    """★F7: VR v3 방식 — 경로는 세전(도중 매도 없음 = 확정부채 0), 최종값만 만기 청산 세후.
       종전(잠재세 일별 차감 경로)은 폐지. 최종 수치는 종전과 동일(같은 청산 산식)."""
    px = df[t]
    units = ic / px.iloc[0]
    nav = units * px
    fin_tax = max(0.0, (nav.iloc[-1] - ic) - TAX_EXEMPTION) * TAX_RATE_EQUITY
    nav.iloc[-1] = max(0.0, nav.iloc[-1] - fin_tax)
    return nav

def calc_stats(nav, ic):
    days = (nav.index[-1] - nav.index[0]).days
    cagr = (nav.iloc[-1] / ic) ** (365 / days) - 1        # 최종값 = 만기 청산 세후 → 세후 CAGR
    path = nav.iloc[:-1] if len(nav) > 2 else nav         # ★F7: MDD·변동성은 '청산 전 경로'
    mdd = (path / path.cummax() - 1).min()                #  (마지막 날 세금 절벽의 MDD 오염 방지, VR v3 정의)
    vol = path.pct_change().dropna().std() * np.sqrt(252)
    sharpe = (cagr - RISK_FREE_RATE) / vol if vol > 0 else 0
    return cagr, mdd, sharpe

# ── ★K13(2026-08-07): 위험계기판 헬퍼 — 측정 전용, 시뮬 로직 무접촉 ──
def _var_returns(nav):
    """일별 단순수익률 + 오염 제거 2종(사양 K13-2). 반환 (r, n_dropped).
       (a) 마지막 날 제외 — 최종 청산 세금 반영일(calc_stats '청산 전 경로' 원칙 준용)
       (b) 각 연도 6월 첫 거래일 제외 — 세금 납부일(is_may_end 다음 거래일). 비교 공정성 위해 전 대상 동일 적용."""
    r = nav.pct_change().dropna()
    n0 = len(r)
    if len(r) and r.index[-1] == nav.index[-1]:
        r = r.iloc[:-1]                                   # (a) 청산일
    _drop = []
    for _y in sorted(set(r.index.year)):
        _sel = r.index[(r.index.year == _y) & (r.index.month == 6)]
        if len(_sel):
            _drop.append(_sel[0])                          # (b) 6월 첫 거래일
    if _drop:
        r = r.drop(_drop)
    return r, n0 - len(r)

def _var_core(r, level):
    """분위수 기반 VaR/cVaR 핵심식(사양 K13-2). 반환 (var, cvar, n_used, n_exceed, cover_ratio)."""
    q = r.quantile(1 - level)
    var = -q
    tail = r[r <= q]
    cvar = -tail.mean()
    n_exceed = int((r <= q).sum())
    _exp = len(r) * (1 - level)
    cover = (n_exceed / _exp) if _exp > 0 else float('nan')
    return var, cvar, len(r), n_exceed, cover

def _var_cvar(nav, level, label=""):
    """사양 K13-2 지정 헬퍼. 반환 (var, cvar, n_used, n_dropped, n_exceed, cover_ratio).
       label은 예약 인자(현재 미사용)."""
    r, n_dropped = _var_returns(nav)
    var, cvar, n_used, n_exceed, cover = _var_core(r, level)
    return var, cvar, n_used, n_dropped, n_exceed, cover

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

# ── ★K4(2026-08-06): 대피→복귀 이벤트 표 — 시뮬 로직 무접촉, 매매로그 후처리 전용 ──
def print_event_table(log, df):
    """'대피(USD대기)' 실행일과 다음 '복귀*' 실행일을 짝지어 1행씩 출력(사양 K4).
       가격 = TQQQ 실행일 시가(시뮬 _exec_px와 동일하게 시가 결측 시 종가 폴백).
       구간등락 = 복귀가÷대피가−1. 양수=헛대피 비용(더 비싸게 재진입) / 음수=회피 성공 크기.
       기간 끝까지 미복귀면 종료일 종가로 '미복귀(미실현)' 표기. 말미에 합계·헛대피 횟수."""
    def _px(d, use_open=True):
        if d not in df.index: return np.nan
        r = df.loc[d]
        if use_open:
            v = r['TQQQ_OPEN'] if 'TQQQ_OPEN' in r.index else np.nan
            if not pd.isna(v) and v > 0: return v
        v = r['TQQQ'] if 'TQQQ' in r.index else np.nan
        return v if (not pd.isna(v) and v > 0) else np.nan
    if log is None or log.empty:
        print("    (매매로그 없음 — 대피/복귀 이벤트 없음)")
        return
    print(f"    {_pad('대피일',12)} | {_pad('대피시가',10)} | {_pad('복귀일',14)} | {_pad('복귀시가',10)} | {_pad('구간등락',9)}")
    print("    " + "-" * 68)
    esc = None
    total = 0.0; n_bad = 0; n_evt = 0
    for _, r in log.iterrows():
        a = str(r['액션'])
        if a == '대피(USD대기)':
            esc = pd.to_datetime(r['실행일'])
        elif a.startswith('복귀') and esc is not None:
            rec = pd.to_datetime(r['실행일'])
            pe, pr = _px(esc), _px(rec)
            if pd.isna(pe) or pd.isna(pr):
                print(f"    {_pad(esc.strftime('%Y-%m-%d'),12)} | {_pad('결측',10)} | {_pad(rec.strftime('%Y-%m-%d'),14)} | {_pad('결측',10)} | {_pad('N/A',9)}")
            else:
                chg = pr / pe - 1.0
                total += chg; n_evt += 1
                if chg > 0: n_bad += 1
                print(f"    {_pad(esc.strftime('%Y-%m-%d'),12)} | {pe:>10,.2f} | {_pad(rec.strftime('%Y-%m-%d'),14)} | {pr:>10,.2f} | {chg*100:>+8.2f}%")
            esc = None
    if esc is not None:                                  # 기간 끝까지 미복귀 → 종료일 종가(미실현)
        pe = _px(esc)
        pl = _px(df.index[-1], use_open=False)
        if not (pd.isna(pe) or pd.isna(pl)):
            chg = pl / pe - 1.0
            total += chg; n_evt += 1
            if chg > 0: n_bad += 1
            print(f"    {_pad(esc.strftime('%Y-%m-%d'),12)} | {pe:>10,.2f} | {_pad('미복귀(미실현)',14)} | {pl:>10,.2f} | {chg*100:>+8.2f}%")
    print("    " + "-" * 68)
    print(f"    합계(구간등락 단순합) {total*100:+.2f}%p · 헛대피 {n_bad}회 / 이벤트 {n_evt}회 "
          f"(양수=헛대피 비용, 음수=회피 성공)")


# ============================================================
# [5. 실행]
# ============================================================
if __name__ == "__main__":
    # ★ F6: FULL 1회만 다운로드 → 전체기간 df 및 모든 다중윈도우가 공유(중복 다운로드 제거)
    df_full = get_data('FULL')
    df = df_full.loc[START_DATE:]
    df = df[df.index <= END_DATE]

    def _port_label(tag, w):
        """라벨 자동 생성: 포트 구성(W_A·W_B)에서 자산명·비중을 읽는다 — gold→BOXX 등 자산을 바꾸면 표기가 저절로 따라온다."""
        tq = int(round(w.get('TQQQ', 0) * 100))
        hedge = next((k for k in w if k != 'TQQQ'), None)
        return f"{tag}(TQQQ{tq})" if hedge is None else f"{tag}(TQQQ{tq}:{hedge}{int(round(w[hedge] * 100))})"
    A_NAME = _port_label("A", W_A)   # 예: A(TQQQ60:gold40)
    B_NAME = _port_label("B", W_B)   # 예: B(TQQQ50:gold50)

    for nm, w in [(A_NAME, W_A), (B_NAME, W_B)]:
        s = sum(w.values())
        if abs(s - 1.0) > 1e-6:
            print(f"  [경고] 포트 {nm} 비중 합 = {s:.2f} (1.00 아님 → 나머지는 미투자 현금)")

    configs = [
        (A_NAME,  'fast_recover', W_A),
        (B_NAME,  'fast_recover', W_B),
    ]

    results = {}
    for name, m, w in configs:
        print(f"\n▷ {name} 시뮬레이션...")
        nav, log = run_simulation(df, INITIAL_CAPITAL, w, name, method=m)
        results[name] = (nav, log)

    nav_spy = run_bh_aftertax(df, INITIAL_CAPITAL, 'SPY')
    nav_qqq = run_bh_aftertax(df, INITIAL_CAPITAL, 'QQQ')
    nav_qld = run_bh_aftertax(df, INITIAL_CAPITAL, 'QLD')   # ★ QLD(2x) 벤치마크
    nav_tqqq = run_bh_aftertax(df, INITIAL_CAPITAL, 'TQQQ')  # ★F12: TQQQ 단독 보유(세후)

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
    print(f"  📊 스마트 대기 + FAST — {A_NAME} vs {B_NAME} ({sd} ~ {ed}, {yrs}년)")
    print(f"  자산: gold=KRX금현물(비과세), BOXX=박스스프레드(양도세, 단기채복제) / SPY·QQQ·QLD 세후")
    print(f"  · ★F7/F8/F9: NAV=자산−확정세부채(잠재세 폐지, VR v3 정합) · 수수료 편도: 미국주식 "
          f"{(NORMAL_SLIPPAGE+COMMISSION)*100:.2f}%(토스 실측) · gold {_get_slip_comm('gold')*100:.2f}% · BOXX {_get_slip_comm('BOXX')*100:.2f}% · MDD=청산 전 경로")
    print(f"  · 세금: 양도세 {TAX_RATE_EQUITY:.0%} · 공제 연 ₩{TAX_DEDUCTION_KRW:,.0f}"
          f"(≈${TAX_EXEMPTION:,.0f} @₩{FX_KRWUSD:,.0f}/$, 이 계좌 전액사용 가정·이월 없음) — VR v3와 동일 기준")
    print(f"  · FAST_RECOVER_KEEPS_GOLD = {FAST_RECOVER_KEEPS_GOLD} "
          f"({'현금→TQQQ만(gold 무접촉)' if FAST_RECOVER_KEEPS_GOLD else '전체 50:50 재조정(기존)'})")
    print("=" * 104)
    print(f"{_pad('방식',24)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피수',6)} | {_pad('총매매',6)}")
    print("-" * 104)
    for name, _, _ in configs:
        nav, log = results[name]
        fin, c, m, s, nd, nt = stats_line(nav, log)
        print(f"{_pad(name,24)} | {fin:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {nd:>6} | {nt:>6}")

    for bname, bnav in [("TQQQ단독(세후)", nav_tqqq), ("SPY(세후, 참고)", nav_spy), ("QQQ(세후, 참고)", nav_qqq), ("QLD(세후, 참고)", nav_qld)]:
        c, m, s = calc_stats(bnav, INITIAL_CAPITAL)
        print(f"{_pad(bname,24)} | {bnav.iloc[-1]:>16,.0f} | {c*100:>7.2f}% | {m*100:>7.2f}% | {s:>6.2f} | {'-':>6} | {'-':>6}")
    print("=" * 104)

    a_fin = results[A_NAME][0].iloc[-1]
    b_fin = results[B_NAME][0].iloc[-1]
    diff = a_fin - b_fin
    ratio = (a_fin / b_fin - 1) * 100 if b_fin > 0 else 0
    print(f"\n  ▶ {A_NAME} − {B_NAME} = {diff:>+,.0f}  ({ratio:+.1f}%)")
    print(f"    {A_NAME + ' 우세' if diff > 0 else B_NAME + ' 우세'}")

    # ============================================================
    # [5a-v2. 시작일 바깥 · 종료일 안쪽] ★ 2026-08-08 은박사님 지시 순서
    # ============================================================
    if START_DATES:
      _nm_ed = {"2018-12-31": "금겨울 끝", "2020-12-31": "코로나 회복 후", "2021-12-31": "직전 고점",
                "2022-12-30": "하락 바닥권", "2024-12-31": "금급등 중", "2026-07-10": "현재(기준 재현)"}
      for _sd_i in START_DATES:
        print("\n" + "=" * 108)
        print(f"  📊 ★시작일 {_sd_i} — 종료일별 A vs B (부스터B 기준)")
        print("=" * 108)
        print(f"{_pad('종료일',12)} | {_pad('자산',18)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피',5)}"
              )
        print("-" * 108)
        for _ED in END_DATES:
            if _ED <= _sd_i:
                continue
            globals()["END_DATE"] = _ED
            _sub = df_full.loc[_sd_i:]
            _sub = _sub[_sub.index <= _ED]
            if len(_sub) < 250:
                print(f"{_pad(_ED,12)} | 기간 부족 — 건너뜀")
                continue
            for _lbl, _w in [(A_NAME, W_A), (B_NAME, W_B)]:
                _nav_i, _log_i = run_simulation(_sub, INITIAL_CAPITAL, _w, _lbl,
                                                method='boost_until_annual',
                                                recover_boost=_boost_for(_w))
                _c_i, _m_i, _s_i = calc_stats(_nav_i, INITIAL_CAPITAL)
                _nd_i = int((_log_i['액션'] == '대피(USD대기)').sum()) if not _log_i.empty else 0
                print(f"{_pad(_ED,12)} | {_pad(_lbl,18)} | {_nav_i.iloc[-1]:>16,.0f} | "
                      f"{_c_i*100:>7.2f}% | {_m_i*100:>7.2f}% | {_s_i:>6.2f} | {_nd_i:>5}")
            _nav_t = run_bh_aftertax(_sub, INITIAL_CAPITAL, 'TQQQ')
            _c_t, _m_t, _s_t = calc_stats(_nav_t, INITIAL_CAPITAL)
            print(f"{_pad(_ED,12)} | {_pad('TQQQ단독(세후)',18)} | {_nav_t.iloc[-1]:>16,.0f} | "
                  f"{_c_t*100:>7.2f}% | {_m_t*100:>7.2f}% | {_s_t:>6.2f} | {'-':>5}")
            _nav_q = run_bh_aftertax(_sub, INITIAL_CAPITAL, 'QLD')            # ★벤치 복원(2026-08-09)
            _c_q, _m_q, _s_q = calc_stats(_nav_q, INITIAL_CAPITAL)
            print(f"{_pad(_ED,12)} | {_pad('QLD단독(세후)',18)} | {_nav_q.iloc[-1]:>16,.0f} | "
                  f"{_c_q*100:>7.2f}% | {_m_q*100:>7.2f}% | {_s_q:>6.2f} | {'-':>5}")
            _nav_n = run_bh_aftertax(_sub, INITIAL_CAPITAL, 'QQQ')
            _c_n, _m_n, _s_n = calc_stats(_nav_n, INITIAL_CAPITAL)
            print(f"{_pad(_ED,12)} | {_pad('QQQ단독(세후)',18)} | {_nav_n.iloc[-1]:>16,.0f} | "
                  f"{_c_n*100:>7.2f}% | {_m_n*100:>7.2f}% | {_s_n:>6.2f} | {'-':>5}")
            _nav_s = run_bh_aftertax(_sub, INITIAL_CAPITAL, 'SPY')            # ★벤치 복원(2026-08-09)
            _c_s, _m_s, _s_s = calc_stats(_nav_s, INITIAL_CAPITAL)
            print(f"{_pad(_ED,12)} | {_pad('SPY단독(세후)',18)} | {_nav_s.iloc[-1]:>16,.0f} | "
                  f"{_c_s*100:>7.2f}% | {_m_s*100:>7.2f}% | {_s_s:>6.2f} | {'-':>5}")
            print("-" * 108)
        print("=" * 108)
      print("  · 마지막 행(2026-07-10)이 기존 표의 같은 시작일 행과 일치하면 회귀 검증 통과.")
      print("  · ⚠️ 시작일·종료일 조합들은 독립 표본이 아님(같은 폭락 공유).")
      globals()["END_DATE"] = "2026-07-10"

    # ============================================================
    # [5e. 탈출지수 실험] ★K5(2026-08-06) — EXIT_LAB=True일 때만 실행(F11 SHOW_LAB 패턴)
    #   GATE 3종(ABS/B1/NONE) × EXIT 2종(GSPC/NDX) = 6조합. A 포트(W_A)·fast_recover만(부스터 제외).
    #   복귀 규칙은 전 조합 동일(S&P/NDX 200일선 — EXIT_INDEX 미참조) → 탈출 축만 분리 측정.
    #   실행 권장: END_DATE="2026-08-01"(2026 상반기 왕복 포함) — 실행 파라미터이며 코드 수정 아님.
    #   K7 회귀는 END_DATE="2026-01-01" 기본 스위치로 수행.
    # ============================================================
    if EXIT_LAB:
        print("\n" + "=" * 104)
        print("  🔬 [5e. 탈출지수 실험] GATE 3종 × EXIT 2종 = 6조합 — A 포트(fast_recover, 부스터 제외)")
        print(f"     게이트: ABS=버블≥{BUBBLE_LIMIT:.2f} | B1=버블 10년 롤링 백분위≥{B1_PCTL:.2f} | NONE=상시 개방")
        print("     탈출 = 게이트 AND (EXIT지수 < 자기 200일선). 복귀 규칙은 전 조합 동일(EXIT_INDEX 미참조).")
        print("=" * 104)
        for _gm in ["ABS", "B1", "NONE"]:
            for _ei in ["GSPC", "NDX"]:
                _tag = f"GATE={_gm} · EXIT={_ei}"
                print("\n" + "-" * 104)
                print(f"  ▷ [{_tag}] 전체기간 {sd} ~ {ed}")
                _nav_e, _log_e = run_simulation(df, INITIAL_CAPITAL, W_A, _tag, method='fast_recover',
                                                exit_index=_ei, gate_mode=_gm)
                _c_e, _m_e, _s_e = calc_stats(_nav_e, INITIAL_CAPITAL)
                _nd_e = int((_log_e['액션'] == '대피(USD대기)').sum()) if not _log_e.empty else 0
                print(f"    최종자산 {_nav_e.iloc[-1]:>16,.0f} | CAGR {_c_e*100:>7.2f}% | MDD {_m_e*100:>7.2f}% | "
                      f"샤프 {_s_e:>5.2f} | 대피 {_nd_e}회")
                print_event_table(_log_e, df)
                if START_DATES:
                    print(f"    [{_tag}] 시작일별 요약 (~{END_DATE})")
                    print(f"    {_pad('시작일',12)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피',5)}")
                    print("    " + "-" * 66)
                    for _sd_e in START_DATES:
                        _sub_e = df_full.loc[_sd_e:]
                        if END_DATE:
                            _sub_e = _sub_e[_sub_e.index <= END_DATE]
                        if len(_sub_e) < 250:
                            print(f"    {_pad(_sd_e,12)} | 데이터 부족 — 건너뜀")
                            continue
                        _nav_w, _log_w = run_simulation(_sub_e, INITIAL_CAPITAL, W_A, _tag, method='fast_recover',
                                                        exit_index=_ei, gate_mode=_gm)
                        _c_w, _m_w, _s_w = calc_stats(_nav_w, INITIAL_CAPITAL)
                        _nd_w = int((_log_w['액션'] == '대피(USD대기)').sum()) if not _log_w.empty else 0
                        print(f"    {_pad(_sd_e,12)} | {_nav_w.iloc[-1]:>16,.0f} | {_c_w*100:>7.2f}% | "
                              f"{_m_w*100:>7.2f}% | {_s_w:>6.2f} | {_nd_w:>5}")
        print("\n" + "=" * 104)
        print("  · 판정 기준(사전 등록): 동률 폭 CAGR ±0.3%p·MDD ±0.5%p — NDX 채택은 ①회피손익 합계 비열위 "
              "②헛대피 증가 상쇄 ③10창 CAGR 전건 비열위·MDD 비악화 ④장기창(1986·1994·1998·2000) 우세/동률, 전부 충족 시에만.")
        print("=" * 104)

    # ============================================================
    # [5i. 복귀지수 실험] ★K10(2026-08-06) — REC_LAB=True일 때만 실행([5e] 패턴 복제)
    #   EXIT=NDX 고정(2026-08-06 탈출지수 NDX 채택 확정) — 복귀축만 분리 측정.
    #   GATE 3종(ABS/B1/NONE) × REC_HOT 2종(GSPC/NDX) = 6조합. A 포트(W_A)·fast_recover만(부스터 제외).
    #   냉게이트 빠른복귀(S&P/NDX 병용)·부스터 로직은 대상 아님(사양 K8 범위 제한 — 전 조합 동일).
    #   실행 권장: END_DATE="2026-08-01" — 실행 파라미터이며 코드 기본값 불변([5e]와 동일 방식).
    # ============================================================
    if REC_LAB:
        print("\n" + "=" * 104)
        print("  🔬 [5i. 복귀지수 실험] GATE 3종 × REC_HOT 2종 = 6조합 — EXIT=NDX 고정(2026-08-06 확정), 복귀축만 분리 측정")
        print(f"     게이트: ABS=버블≥{BUBBLE_LIMIT:.2f} | B1=버블 10년 롤링 백분위≥{B1_PCTL:.2f} | NONE=상시 개방")
        print("     핫게이트 복귀 = REC_HOT 지수 > 자기 200일선(월말). 냉게이트 복귀·부스터는 전 조합 동일(무변경).")
        print("     A 포트(W_A)·fast_recover만(부스터 제외).")
        print("=" * 104)
        for _gm2 in ["ABS", "B1", "NONE"]:
            for _rh in ["GSPC", "NDX"]:
                _tag2 = f"GATE={_gm2} · REC={_rh}"
                print("\n" + "-" * 104)
                print(f"  ▷ [{_tag2} · EXIT=NDX] 전체기간 {sd} ~ {ed}")
                _nav_r, _log_r = run_simulation(df, INITIAL_CAPITAL, W_A, _tag2, method='fast_recover',
                                                exit_index="NDX", gate_mode=_gm2, rec_hot_index=_rh)
                _c_r, _m_r, _s_r = calc_stats(_nav_r, INITIAL_CAPITAL)
                _nd_r = int((_log_r['액션'] == '대피(USD대기)').sum()) if not _log_r.empty else 0
                print(f"    최종자산 {_nav_r.iloc[-1]:>16,.0f} | CAGR {_c_r*100:>7.2f}% | MDD {_m_r*100:>7.2f}% | "
                      f"샤프 {_s_r:>5.2f} | 대피 {_nd_r}회")
                print_event_table(_log_r, df)
                if START_DATES:
                    print(f"    [{_tag2} · EXIT=NDX] 시작일별 요약 (~{END_DATE})")
                    print(f"    {_pad('시작일',12)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피',5)}")
                    print("    " + "-" * 66)
                    for _sd_r in START_DATES:
                        _sub_r = df_full.loc[_sd_r:]
                        if END_DATE:
                            _sub_r = _sub_r[_sub_r.index <= END_DATE]
                        if len(_sub_r) < 250:
                            print(f"    {_pad(_sd_r,12)} | 데이터 부족 — 건너뜀")
                            continue
                        _nav_rw, _log_rw = run_simulation(_sub_r, INITIAL_CAPITAL, W_A, _tag2, method='fast_recover',
                                                          exit_index="NDX", gate_mode=_gm2, rec_hot_index=_rh)
                        _c_rw, _m_rw, _s_rw = calc_stats(_nav_rw, INITIAL_CAPITAL)
                        _nd_rw = int((_log_rw['액션'] == '대피(USD대기)').sum()) if not _log_rw.empty else 0
                        print(f"    {_pad(_sd_r,12)} | {_nav_rw.iloc[-1]:>16,.0f} | {_c_rw*100:>7.2f}% | "
                              f"{_m_rw*100:>7.2f}% | {_s_rw:>6.2f} | {_nd_rw:>5}")
        print("\n" + "=" * 104)
        print("  · 판정 기준(사전 등록): 주 판정축 = GATE=B1 · 2010 이후 6창(2010/2013/2016/2019/2022/2024) · EXIT=NDX 고정.")
        print("  · REC=NDX 채택 조건(전부 충족 시에만): ①6창 CAGR 전건 비열위(±0.3%p) ②6창 MDD 전건 비악화(±0.5%p) "
              "③이벤트표(B1·ABS 두 축) 헛대피 비용 합계 비열위 ④ABS 전체기간 CAGR 악화 −0.5%p 이내(장기 안전판).")
        print("  · 하나라도 미충족 또는 전반 동률 → 현행(복귀=S&P) 유지. 동률이면 바꾸지 않는다(변경 최소 원칙).")
        print("=" * 104)

    # ============================================================
    # [5v. 위험계기판(VaR/cVaR)] ★K13(2026-08-07) — VAR_LAB=True일 때만 실행. 측정 전용.
    #   대상 6종 = 기존 산출물 재사용(신규 시뮬레이션 금지): A/B 포트 + TQQQ/QLD/QQQ/SPY 단독(세후).
    #   표1 전기간 · 표2 최근 VAR_RECENT_YEARS년 · 표3 A 포트 상태 분해(투자중/대피중).
    # ============================================================
    if VAR_LAB:
        _var_targets = [(A_NAME, results[A_NAME][0]), (B_NAME, results[B_NAME][0]),
                        ('TQQQ단독', nav_tqqq), ('QLD단독', nav_qld),
                        ('QQQ단독', nav_qqq), ('SPY단독', nav_spy)]
        def _var_table(_title, _navs):
            print("\n" + "-" * 104)
            print(f"  ▷ {_title}")
            _nd_note = []
            for _lv in VAR_LEVELS:
                print(f"    [신뢰수준 {int(round(_lv*100))}%]")
                print(f"    {_pad('대상',18,'<')} | {_pad('1일 VaR',9)} | {_pad('1일 cVaR',9)} | {_pad('초과일(실제/기대)',20)} | {_pad('사용일수',8)}")
                print("    " + "-" * 76)
                for _t, _nv in _navs:
                    _v, _c, _nu, _ndp, _ne, _cv = _var_cvar(_nv, _lv, _t)
                    _exp = _nu * (1 - _lv)
                    print(f"    {_pad(_t,18,'<')} | {_v*100:>8.2f}% | {_c*100:>8.2f}% | "
                          f"{_pad(f'{_ne}/{_exp:.1f} ({_cv:.2f}배)',20)} | {_nu:>8,}")
                    if _lv == VAR_LEVELS[0]:
                        _nd_note.append(f"{_t} {_ndp}일")
            print(f"    · 제외일수(청산 1 + 연도별 6월 세금납부일): " + ", ".join(_nd_note))
        # 표 1 — 전기간
        print("\n" + "=" * 104)
        print(f"  🔬 [5v. 위험계기판(VaR/cVaR)] 실측 분포 기반 — {sd} ~ {ed}")
        print("=" * 104)
        _var_table("표1 전기간", _var_targets)
        # 표 2 — 최근 구간(연말 점검용)
        _var_recent = []
        for _t, _nv in _var_targets:
            _cut = _nv.index[-1] - pd.DateOffset(years=VAR_RECENT_YEARS)
            _var_recent.append((_t, _nv.loc[_nv.index >= _cut]))
        _var_table(f"표2 최근 {VAR_RECENT_YEARS}년", _var_recent)
        # 원화 환산 문장 — 표2의 A 포트 95% 기준(사양 K13-3)
        _nav_a_rc = dict(_var_recent)[A_NAME]
        _v95, _c95, _nu95, _nd95, _ne95, _cv95 = _var_cvar(_nav_a_rc, 0.95, A_NAME)
        print(f"    계좌 USD {VAR_ACCOUNT_USD:,.0f} 기준: 한 달에 하루쯤 약 ₩{VAR_ACCOUNT_USD*_v95*VAR_FX:,.0f} 이상 하락, "
              f"그런 날 평균 ₩{VAR_ACCOUNT_USD*_c95*VAR_FX:,.0f}")
        # 표 3 — A 포트 상태 분해(전기간): 매매로그로 '대피(USD대기)~복귀' 구간을 CASH로 마킹
        #   구간 규칙: 대피 실행일 포함 ~ 복귀 실행일 제외(실행이 시가라 대피일=대체로 현금·복귀일=대체로 투자).
        _nav_a, _log_a = results[A_NAME]
        _r_a, _nd_a = _var_returns(_nav_a)
        _cash = pd.Series(False, index=_r_a.index)
        _st = None
        if not _log_a.empty:
            for _, _row in _log_a.iterrows():
                _act = str(_row['액션'])
                _d = pd.to_datetime(_row['실행일'])
                if _act == '대피(USD대기)' and _st is None:
                    _st = _d
                elif _act.startswith('복귀') and _st is not None:
                    _cash[(_cash.index >= _st) & (_cash.index < _d)] = True
                    _st = None
        if _st is not None:
            _cash[_cash.index >= _st] = True
        print("\n" + "-" * 104)
        print(f"  ▷ 표3 A 포트 상태 분해(전기간) — 투자중 {int((~_cash).sum()):,}일 / 대피중 {int(_cash.sum()):,}일 "
              f"(킬스위치의 꼬리 절단 분리 측정)")
        for _lv in VAR_LEVELS:
            print(f"    [신뢰수준 {int(round(_lv*100))}%]")
            print(f"    {_pad('상태',18,'<')} | {_pad('1일 VaR',9)} | {_pad('1일 cVaR',9)} | {_pad('초과일(실제/기대)',20)} | {_pad('사용일수',8)}")
            print("    " + "-" * 76)
            for _t, _rr in [('투자중', _r_a[~_cash]), ('대피중', _r_a[_cash])]:
                if len(_rr) < 30:
                    print(f"    {_pad(_t,18,'<')} | 표본 {len(_rr)}일 — 산출 생략")
                    continue
                _v, _c, _nu, _ne, _cv = _var_core(_rr, _lv)
                _exp = _nu * (1 - _lv)
                print(f"    {_pad(_t,18,'<')} | {_v*100:>8.2f}% | {_c*100:>8.2f}% | "
                      f"{_pad(f'{_ne}/{_exp:.1f} ({_cv:.2f}배)',20)} | {_nu:>8,}")
        # 각주(사양 K13-3 필수 3줄)
        print("\n" + "=" * 104)
        print("  · 각주 (a) 실측 분포 기반이며 정규분포 가정을 쓰지 않음.")
        print(f"  · 각주 (b) 제외일 = 최종 청산일 1일 + 각 연도 6월 첫 거래일(세금 납부일) — A 포트 기준 {_nd_a}일, 전 대상 동일 규칙.")
        print("  · 각주 (c) 이 값은 매매 신호가 아니라 관찰용 계기판.")
        print("=" * 104)

    # ★F11: 아래 세 섹션([5f][5g][5h])은 SHOW_LAB=True일 때만 실행·출력
    if SHOW_LAB:
        # ============================================================
        # [5f. 복귀 부스터] 빠른복귀(NDX 단독) 진입 시 TQQQ 더 싣기 — A 포트 기준
        # ============================================================
        print("\n" + "=" * 104)
        print(f"  🔬 [복귀 부스터B] {A_NAME} 기준 — NDX 단독 빠른복귀 진입 순간 TQQQ↑(헤지↓)로 부스터")
        _hA = next((k for k in W_A if k != 'TQQQ'), '')
        _hR = next((k for k in RECOVER_BOOST if k != 'TQQQ'), '')
        print(f"     평상시 TQQQ{int(W_A['TQQQ']*100)}:{_hA}{int(W_A.get(_hA,0)*100)} → 부스터 TQQQ{int(RECOVER_BOOST['TQQQ']*100)}:{_hR}{int(RECOVER_BOOST.get(_hR,0)*100)} "
              f"(NDX 단독복귀 시만). 환원: 연 1회 리밸런싱(12/31). ★채택")
        print("=" * 104)
        print(f"{_pad('방식',26)} | {_pad('최종자산($)',16)} | {_pad('CAGR',8)} | {_pad('MDD',8)} | {_pad('샤프',6)} | {_pad('대피수',6)} | {_pad('총매매',6)}")
        print("-" * 104)
        _bnav, _blog = results[A_NAME]
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
                _path = _nav.iloc[:-1] if len(_nav) > 2 else _nav   # ★F7: 구간 끝 청산 세금 절벽 제외
                _mdd = (_path / _path.cummax() - 1).min() * 100
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

    A_name = A_NAME
    B_name = B_NAME
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
             label=f'{A_NAME} (CAGR {ca*100:.1f}%, MDD {ma*100:.1f}%)')
    ax1.plot(nav_b.index, nav_b.values, color='steelblue', lw=1.5, ls='--',
             label=f'{B_NAME} (CAGR {cb*100:.1f}%, MDD {mb*100:.1f}%)')
    ax1.plot(nav_spy.index, nav_spy.values, color='gray', lw=1.0, ls=':', label='SPY (세후)')
    ax1.plot(nav_qqq.index, nav_qqq.values, color='purple', lw=1.0, ls=':', label='QQQ (세후)')
    ax1.plot(nav_qld.index, nav_qld.values, color='green', lw=1.0, ls=':', label='QLD (세후)')
    ax1.plot(nav_tqqq.index, nav_tqqq.values, color='darkorange', lw=1.0, ls=':', label='TQQQ단독 (세후)')  # ★F12
    ax1.set_yscale('log')
    ax1.set_ylabel('NAV (USD, Log)')
    ax1.set_title(f'{yrs}년 백테스트 ({sd} ~ {ed}) — {A_NAME} vs {B_NAME}')
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
