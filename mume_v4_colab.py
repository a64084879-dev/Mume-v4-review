
# -*- coding: utf-8 -*-
"""
라오어 밸류 리밸런싱 백테스터 v3 — 거치식·적립식·인출식 (+킬스위치/B1/VOLTGT)  1986~오늘
════════════════════════════════════════════════════════════════════════
★ v3 핵심 추가 (2026-08-01, 은박사 승인 계획서): 한국 현행 세제·수수료 엔진.

  ■ 무엇이 문제였나 (v2)
    · 세금: 만기 일괄과세(전 기간 1회 실현 가정) — VR은 격주로 이익을 실현하는데
      B&H의 이연 혜택을 VR에도 부여했다(VR에 일방적으로 유리한 낙관 편향).
    · 킬스위치 대피 전량매도의 과세 충격(다음해 5월 Pool 유출)이 없었다.
    · 수수료 0. 공제 250은 USD/원 단위 불일치.

  ■ v3가 하는 일 (TAX_MODE="annual", 기본)
    · 모든 매도(밴드·대피·인출·목돈·납부부족·만기)의 실현손익을 원장에 기록
      (취득원가 = 이동평균, 매수수수료 포함 = 세법상 필요경비 자동공제).
    · 12/31 정산: 세액 = max(0, 연중 실현손익 − 공제) × 22% → 미납부채(당일 NAV부터 차감).
      손실해 세액 0, 이월결손 차단(연내 통산만). ★공제 = 연 250만원(인별 기본공제)을
      고정환율(FX_KRWUSD)로 USD 환산해 매년 1회 적용 — 이 계좌가 전액 사용 가정,
      공제 이월 없음, 마지막 해는 만기 청산익과 합산해 1회만(이중공제 차단).
      v2의 '250.0 USD' 단위 불일치를 원화 정의 + 명시 환산으로 교정(2026-08-01 지시).
    · 다음해 6월 첫 거래일 납부: ★라오어 부록A 목돈인출 방식 — TQQQ:Pool 비례
      인출 + V_new = V×(1−세액/총자산). 라이브 봇 /lumpsum과 동일 메커니즘.
    · 수수료 편도 0.1%(토스 실측): 매수 (1+f) 가산, 매도 (1−f) 차감.
    · 표의 세후액 = 만기 전량매도 → 마지막해 정산 → 실수령액. 벤치마크(TQQQ/QQQ
      보유·적립·인출)도 전부 동일 엔진 — B&H의 "도중 세금 0"은 특별취급이 아니라
      같은 엔진의 자연 귀결(도중 매도가 없으므로).
    · MDD·샤프 = (평가액+Pool−미납부채) 경로. 5월 납부는 NAV 중립(부채 소멸=현금
      유출), 12/31 정산일에 부채만큼 NAV 하락이 정직하게 찍힌다.
  ■ 회귀 앵커: TAX_MODE="maturity" + TAX_DEDUCTION=250.0 + FEE_RATE=0.0
    + SHARPE_RF="irx" + SHARPE_NUM="arith"  (5개 전부 함께 바꿔야 v2 재현)
    → v2(md5 bd3dd7c8) 결과 재현. 신규 로직 전부 스위치 원칙(SIGNAL_LAG 전례).

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

■ 킬스위치(★2026-08-08 비대칭 확정 — 탈출=NDX·복귀=GSPC, 4변형 비교 전 창 1위): 버블(GSPC/M0)≥1.30 AND ★NDX<SMA200 → 전량매도 → 현금, VR 동결.
  복귀(월말 판정): 버블<1.30 → GSPC/NDX 중 먼저 SMA200 돌파 / 버블≥1.30 → GSPC 단독.
  ★V 리셋 안 함.  B1: 위 조건 OR (버블 롤링백분위 ≥ B1_PCTL AND GSPC<SMA200)
■ 데이터: 합성 스플라이싱(^NDX→QQQ→TQQQ×3, 2010~ 실데이터)
■ 세금: 양도세 22% · 공제 250만(만기 1회)
════════════════════════════════════════════════════════════════════════
"""
import os, sys, warnings
try:
    import yfinance as _yf_chk   # 코랩 복붙 자립: 없으면 자동 설치
except ImportError:
    import subprocess as _sp; _sp.run([sys.executable, "-m", "pip", "-q", "install", "yfinance"])
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
# ── ★v3 세금·수수료 엔진 (2026-08-01 은박사 승인) ──
#   "annual"  = 연차 실현과세: 매도 실현익 연말 정산 → 다음해 6월 첫 거래일 부록A 방식 납부.
#   "maturity"= v2 만기 일괄과세 재현(회귀 앵커). ★v2 완전재현: maturity + 공제 250.0 + FEE 0.0
TAX_MODE = "annual"
TAX_RATE = 0.22
# ★공제 부활(2026-08-01 은박사 지시): 해외주식 양도소득 기본공제 연 250만원(인별)을
#   '이 계좌가 매년 전액 사용' 가정으로 적용. 백테스터는 전액 USD이므로 고정환율로 환산한다.
#   · 공제는 연 단위 실현이익 양수분에서 1회 차감 — 손실해엔 소멸, 다음 해 이월 없음(현행 세법).
#   · 마지막 해는 연중 실현 + 만기 청산익을 합산해 공제 1회만 적용(이중공제 없음).
#   · 인별 공제는 전 계좌 합산 연 1회 — 타 계좌에서 일부라도 쓰는 해엔 실제 세금이 이 모델보다 커진다.
#   · 환율↑ → 공제USD↓ → 세금↑ 방향이라 1,400은 보수 쪽. 연도별 실환율·환차손익은 모델 밖(한계 명시).
TAX_DEDUCTION_KRW = 2_500_000.0            # 연 250만원 기본공제
FX_KRWUSD = 1_400.0                        # 공제 환산 전용 고정환율(₩/$)
TAX_DEDUCTION = TAX_DEDUCTION_KRW / FX_KRWUSD   # ≈ $1,785.71 · ★v2 재현 시 250.0으로 직접 덮어쓰기
FEE_RATE = 0.001                      # 편도 수수료(토스 0.1% 실측). 매수 (1+f)·매도 (1−f)
SLIP     = 0.0                        # 슬리피지 — 지정가/LOC 구조상 0 기본, 필요 시 가산
# ★샤프 무위험수익률 정합 (2026-08-01 은박사 지적 → 교정)
#   이 엔진의 Pool(현금)은 이자를 받지 않는다(0%). 그런데 샤프에서 무위험 4.5%를 빼면
#   '현금을 든 전략'만 이중으로 벌점을 먹는다 — 대피일은 실제수익 0%인데 매일 −rf가 차감됨.
#   그러면 샤프의 정의적 성질인 '무위험자산과의 혼합에 불변'(레버리지 불변성)이 깨져서
#   현금 비중이 다른 전략끼리 같은 자로 잴 수 없게 된다.
#     실측: 같은 전략을 비중 w로만 줄였을 때 — rf=4.5%면 샤프 0.346→-0.034로 붕괴,
#           rf=0%면 0.441 불변. 전략 실력은 그대로인데 자가 변하는 것이 현행의 결함.
#   → 무위험은 Pool 수익률과 같은 값을 쓴다(현행 Pool 0% → rf 0%).
#   ※ 나중에 Pool에 이자를 주는 모델로 바꾸면 반드시 "irx"로 되돌려야 정합이 유지된다.
#   ※ v2 완전재현 시에도 "irx"(v2는 IRX 평균을 뺐음). 분자는 SHARPE_NUM="arith".
SHARPE_RF = "pool"                    # "pool"(정합, 기본) | "irx"(v2 재현·Pool 이자 지급 시)
# ★샤프 분자 정의 (2026-08-01 은박사 확정): FAST 백테스터와 통일.
#   "cagr"(기본) = (세후CAGR − rf) / 연율변동성 — FAST의 calc_stats와 동일 산식.
#     · 두 백테스터를 같은 자로 재야 비교가 성립한다. v2의 산술평균 분자는 변동성이 클수록
#       부풀어(대략 +σ²/2) 표의 CAGR 열과 다른 수치가 되고, 표 간 비교도 불가능해진다.
#     · 부수효과: 세후액 ≤ 0(파산)이면 CAGR=nan → 샤프도 nan. 종전에는 파산 행에 양수 샤프가
#       찍혔는데(NAV 음수 구간에서 일수익 부호가 역전) 그 허위값이 자동으로 사라진다.
#   "arith" = v2 원식(일수익 산술평균 − rf/252). v2 완전재현에만 사용.
SHARPE_NUM = "cagr"                   # "cagr"(정합, 기본) | "arith"(v2 재현)
BUBBLE_LIMIT = 1.30
FAST_RECOVER = "on"
RECOVER_B1_BLOCK = "off"              # ★확정(2026-07): 복귀정책 B — B1대피 시에도 NDX 빠른복귀 허용(봇 정합). 실데이터 5구간 전부 CAGR +3.5~7%p·MDD동일로 B 우세 검증. (on=옛 A방식, B1대피 시 NDX차단, 기각됨)
SKILL_ON     = "off"                 # (구) 하위호환 — 아래 SKILL_MODE로 대체됨
# ── 실력공식 조건부 적용 (2026-07 재검토) ──
#   기본공식 V=V+Pool/G, 실력공식 V=V+Pool/G+(E-V)/(2√G). E=사이클종료 평가금.
#   상시켜면 상승장서 매도밴드 낮아져 CAGR 깎임 → B1 사각지대에서만 조건부로 켜서 Pool 보존.
#   진동 무해(스위치가 매매 직접 유발 안 함, V증분만 조정) → 자기해소(임계밑 내려가면 자동 off).
SKILL_MODE       = "off"      # ★기각 확정(2026-07): 조건부까지 스윕 검증 결과 3후보 전부 미채택(A괴리=전구간 CAGR손실, B낙폭=효과 노이즈수준, 상시=CAGR깎임). off 유지. [옵션값: always/gap/drawdown]
SKILL_GAP_THRESH = 0.15       # 후보A: 평가금이 최소밴드(V×0.85) 대비 이 비율 이상 아래로 벌어지면 실력공식 켬
SKILL_DD_THRESH  = 0.40       # 후보B: TQQQ 고점대비 낙폭 이 이상 AND B1미발현(백분위<B1_PCTL)이면 켬

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
    if m0 is None:
        # ★M0 자동수신: m0_full.csv 없으면 FRED BOGMBASE 직접(_tqf_effr와 동일 키·방식, 단위 정규화=봇 동일)
        try:
            import requests as _rq
            _u = ("https://api.stlouisfed.org/fred/series/observations?series_id=BOGMBASE"
                  "&api_key=2bdfd2e7c3efb097542a74f4de9b30b0&file_type=json&observation_start=1980-01-01")
            _r = _rq.get(_u, headers={'User-Agent': 'Mozilla/5.0'}, timeout=40); _r.raise_for_status()
            _obs = _r.json().get('observations', [])
            if _obs:
                _md = pd.DataFrame(_obs)
                m0 = pd.Series(pd.to_numeric(_md['value'], errors='coerce').values,
                               index=pd.to_datetime(_md['date'])).dropna().sort_index()
                if len(m0) and m0.max() > 100000: m0 = m0 / 1000.0
                try:
                    m0.rename("BOGMBASE").to_csv("m0_full.csv")
                    if db: m0.rename("BOGMBASE").to_csv(db + "m0_full.csv")
                    print(f"  · M0: FRED BOGMBASE 자동수신({len(m0)}행) → m0_full.csv 저장(로컬+드라이브)")
                except Exception:
                    print(f"  · M0: FRED BOGMBASE 자동수신({len(m0)}행, 캐시 저장 생략)")
        except Exception as _e:
            print(f"  · M0 FRED 자동수신 실패({str(_e)[:40]}) — m0_full.csv를 올려주세요")
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


# ══════════════ [4. VR 엔진] ══════════════
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


def run_hold_bench(px, init_capital, dep=0.0, wd=0.0, full=False):
    """단순보유(세후). 적립분 매수/인출분 매도 반영. 성과 = 최종NAV + 인출누계.
       ★full=False(기본): 세후액 스칼라 반환 — 기존 호출부·회귀 앵커와 완전 동일.
       ★full=True: dict(aftertax, cagr, mdd, yrs, nav_series) — 표의 벤치마크 위험지표용.
       ★v3(annual): VR과 동일 세금·수수료 엔진(사이클 단위 근사, ±14일).
         · 도중 매도(인출)만 당해 실현 → 연초 정산 → 그해 6월 이후 첫 사이클에 매도 납부
         · 순수 보유(dep=wd=0)는 도중 실현 0 → 만기 매도 1회 과세(같은 엔진의 자연 귀결)
       ★maturity: v2 산식 그대로 보존(회귀 앵커)."""
    if str(TAX_MODE).strip().lower() != "annual":
        # ── v2 원본 경로(만기 일괄) — 산술 바이트 동일. full일 때만 일별 NAV 수집(계산 무영향) ──
        shares = init_capital / float(px.iloc[0]); cum_in = cum_out = 0.0
        daily = []
        for cd in split_cycles(px.index):
            p0 = float(px.loc[cd[0]])
            if dep > 0: shares += dep / p0; cum_in += dep
            if wd > 0:  shares -= min(wd / p0, shares); cum_out += wd
            if full:
                for dd in cd: daily.append((dd, shares * float(px.loc[dd])))
        nav = shares * float(px.iloc[-1])
        cum = init_capital + cum_in; result = nav + cum_out
        tax = max(0, result - cum - TAX_DEDUCTION) * TAX_RATE
        if not full: return result - tax
        return _bench_pack(result - tax, cum, daily, px)
    # ── ★v3 연차 실현과세 경로 ──
    led = TaxLedger()
    shares = led.buy_cash(init_capital, float(px.iloc[0])); cum_in = cum_out = 0.0
    prev_year = px.index[0].year; paid_years = set(); daily = []
    for cd in split_cycles(px.index):
        p0 = float(px.loc[cd[0]]); y = cd[0].year
        if y != prev_year:
            led.year_end(); prev_year = y                     # 전년 실현분 정산(사이클 경계 근사)
        if led.liab > 1e-9 and cd[0].month >= 6 and y not in paid_years:
            T = led.liab
            _q = led.qty_for_cash(T, p0, shares)              # B&H는 Pool 없음 → 전액 주식 매도로 납부
            got = led.sell_qty(_q, p0, shares); shares -= _q
            pay = min(T, got)
            led.liab -= pay; led.tax_paid += pay; led.n_pay += 1
            paid_years.add(y)
        if dep > 0: shares += led.buy_cash(dep, p0); cum_in += dep
        if wd > 0:
            _q = led.qty_for_cash(wd, p0, shares)
            got = led.sell_qty(_q, p0, shares); shares -= _q
            cum_out += min(wd, got)                           # 잔고 초과 인출 불가(현실 정합)
        if full:
            for dd in cd: daily.append((dd, shares * float(px.loc[dd]) - led.liab))
    cash_end = led.sell_qty(shares, float(px.iloc[-1]), shares)
    tax = led.liab + led.final_tax()
    after = cash_end - tax + cum_out
    if not full: return after
    return _bench_pack(after, init_capital + cum_in, daily, px)


def _bench_pack(after, cum, daily, px):
    """벤치마크 상세(세후액·CAGR·MDD·NAV경로). CAGR·MDD 정의는 run_vr과 동일 기준:
       CAGR = (세후액/원금)^(1/년) − 1,  MDD = 일별 NAV(세부채 차감) 경로의 최대 낙폭."""
    ser = pd.DataFrame(daily, columns=["d", "t"]).set_index("d")["t"]
    yrs = (px.index[-1] - px.index[0]).days / 365.25
    cagr = (after / cum) ** (1 / yrs) - 1 if (after > 0 and cum > 0 and yrs > 0) else float("nan")
    mdd = float((ser / ser.cummax() - 1).min()) if len(ser) else float("nan")
    return dict(aftertax=after, cagr=cagr, mdd=mdd, yrs=yrs, nav_series=ser)


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

def _money(x):
    """★(b) 표기(2026-08-01 은박사 결정): 세후액 < 0 = 자산 전멸 후 세금부채 잔존 → '파산(빚 X)'.
       음수 원인: VR은 이익만 실현(연차 과세)하고 손실은 미실현 — 붕괴 후에도 확정 세부채는
       이월·환급 없이 잔존(현행 세법). 코드 결함 아님, 세제 구조의 정직한 노출."""
    return f"{x:,.0f}" if x >= 0 else f"파산(빚 {-x:,.0f})"


def _table(df, title, init, pool_ratio, G, buy_limit, dep, wd):
    # ★열 정의(표시폭 기준) — 구분선 폭은 sum()으로 자동 산출. 한글 전각은 _cell이 보정.
    cols = [("시작일", 11, "<"), ("년수", 5, ">"), ("원금", 10, ">"),
            ("VR+KS세후", 16, ">"), ("CAGR", 7, ">"), ("MDD", 8, ">"), ("샤프", 6, ">"),
            ("VR단독세후", 18, ">"), ("CAGR", 7, ">"), ("MDD", 8, ">"), ("샤프", 6, ">"),
            ("TQQQ보유", 14, ">"), ("CAGR", 7, ">"), ("MDD", 8, ">"),
            ("QQQ보유", 13, ">"), ("대피/복귀", 10, ">")]
    LN = sum(w for _, w, _ in cols)
    end_dt = (df[df.index <= END_DATE].index[-1] if END_DATE else df.index[-1]).date()
    print("\n" + "=" * LN); print(f"  {title}")
    print(f"  ▸ 종료일: {end_dt} · ★킬스위치=비대칭 확정형(탈출NDX·복귀S&P, 2026-08-08) · SIGNAL_LAG={SIGNAL_LAG} "
          f"({'봇 정합(전일신호→당일집행)' if SIGNAL_LAG else 'v1 재현(당일신호→당일집행)'})")
    print(f"  ▸ ★v3 세금엔진: TAX_MODE={TAX_MODE} · 세율 {TAX_RATE:.0%} "
          f"· 공제 연 ₩{TAX_DEDUCTION_KRW:,.0f}(≈${TAX_DEDUCTION:,.0f} @₩{FX_KRWUSD:,.0f}/$, 이 계좌 전액사용 가정) "
          f"· 수수료 편도 {(FEE_RATE+SLIP)*100:.2f}% — 세후액 = 만기 전량매도·양도세 차감 후 실수령액"
          if str(TAX_MODE).strip().lower() == "annual" else
          f"  ▸ 세금엔진: maturity(v2 만기일괄 재현) · 세율 {TAX_RATE:.0%} · 공제 {TAX_DEDUCTION:g} "
          f"· 수수료 편도 {(FEE_RATE+SLIP)*100:.2f}%")
    print("  ▸ CAGR·MDD는 각 열 자기 기준(세후액 기준 CAGR · 일별 NAV 경로 MDD). 샤프는 VR+KS·VR단독 표기"
          f" (=(세후CAGR−{'IRX' if str(SHARPE_RF).strip().lower()=='irx' else '0%'})/연율변동성 · FAST 백테스터와 동일 정의).")
    print("=" * LN)
    print("".join(_cell(h, w, a) for h, w, a in cols))
    print("-" * LN)
    _pc = lambda x: f"{x*100:.1f}%" if x == x else "  —"     # nan(파산·음수 세후) 안전표기
    _sh = lambda x: f"{x:.2f}" if x == x else "  —"          # 샤프 nan(파산) 안전표기
    for sd in START_DATES:
        sub = df[df.index >= sd]
        if END_DATE: sub = sub[sub.index <= END_DATE]
        if len(sub) < 300:
            print(_cell(sd, cols[0][1], "<") + "  (데이터 부족)"); continue
        rk = run_vr(sub, init, pool_ratio, G, buy_limit, dep, wd, killswitch=ON(KILLSWITCH))
        rn = run_vr(sub, init, pool_ratio, G, buy_limit, dep, wd, killswitch=False)
        ht = run_hold_bench(sub["TQQQ"], init, dep, wd, full=True)
        hq = run_hold_bench(sub["QQQ"], init, dep, wd)
        row = [sd, f"{rk['yrs']:.1f}", f"{rk['cum']:,.0f}",
               _money(rk['aftertax']), _pc(rk['cagr']), _pc(rk['mdd']), _sh(rk['sharpe']),
               _money(rn['aftertax']), _pc(rn['cagr']), _pc(rn['mdd']), _sh(rn['sharpe']),
               _money(ht['aftertax']), _pc(ht['cagr']), _pc(ht['mdd']),
               _money(hq), f"{rk['n_exit']}/{rk['n_rec']}"]
        print("".join(_cell(v, w, a) for v, (_, w, a) in zip(row, cols)))
    print("-" * LN)
    print("  · 파산(빚 X) = 만기 전량청산 후에도 남는 미납 세금부채 X — 자산 전멸 후 확정세 잔존"
          "(이월·환급 없음). CAGR '—' = 세후액 ≤ 0(복리수익률 정의 불가).")


def _nav_series_vr(d, init, pool_ratio, G, buy_limit, killswitch, dep=0.0, wd=0.0):
    """차트용 NAV 시계열 — ★v3: 엔진 이원화 제거. run_vr의 일별 NAV(세부채 차감 경로)를
       그대로 사용한다. v2에선 이 함수가 run_vr 사본이었고 목돈이벤트·세금이 빠져 있었다."""
    return run_vr(d, init, pool_ratio, G, buy_limit, dep, wd, killswitch=killswitch)["nav_series"]


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
    # ★열 폭은 '표시폭'(한글 전각=2칸) 기준. 파이썬 :<13 은 문자수라 한글 헤더에서 어긋난다 → _cell 사용.
    _W = [13, 9, 14, 14, 14, 9, 10, 8, 10]
    _AL = ["<", ">", ">", ">", ">", ">", ">", ">", ">"]
    _LN = sum(_W)
    _HD = ["시작일", "년수", "VR+KS", "VR단독", "TQQQ보유", "CAGR", "MDD", "샤프", "KS효과"]
    print("\n" + "█" * _LN)
    print("  ★ 결론 요약 — TQQQ 실데이터 구간(2010~)만.  거치식 10만 · 세후")
    print("     (1986~2000 시작은 합성 데이터 → 참고용. 아래 상세표 참조)")
    print("█" * _LN)
    print("".join(_cell(h, w, a) for h, w, a in zip(_HD, _W, _AL)))
    print("-" * _LN)
    for sd in REAL_STARTS:
        sub = df[df.index >= sd]
        if END_DATE: sub = sub[sub.index <= END_DATE]
        if len(sub) < 300: continue
        rk = run_vr(sub, HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, killswitch=ON(KILLSWITCH))
        rn = run_vr(sub, HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT, killswitch=False)
        ht = run_hold_bench(sub["TQQQ"], HOLD_CAP)
        eff = rk["aftertax"] / rn["aftertax"] if rn["aftertax"] > 0 else float("nan")
        _row = [sd, f"{rk['yrs']:.1f}년", _money(rk['aftertax']), _money(rn['aftertax']),
                _money(ht), f"{rk['cagr']*100:.1f}%", f"{rk['mdd']*100:.1f}%",
                f"{rk['sharpe']:.2f}", f"{eff:.2f}배"]
        print("".join(_cell(v, w, a) for v, w, a in zip(_row, _W, _AL)))
    print("-" * _LN)
    print("  · KS효과 = VR+킬스위치 ÷ VR단독(세후 기준 — ★v3 핵심 검증 질문: 대피 과세 충격 후에도 ≥1인가).")
    print("  · VR단독 = 킬스위치 off.  TQQQ보유 = 단순 매수후보유(세후).")
    print(f"  · ★v3 세금엔진: TAX_MODE={TAX_MODE} · 세율 {TAX_RATE:.0%} "
          f"· 공제 연 ₩{TAX_DEDUCTION_KRW:,.0f}(≈${TAX_DEDUCTION:,.0f} @₩{FX_KRWUSD:,.0f}/$) "
          f"· 수수료 편도 {(FEE_RATE+SLIP)*100:.2f}% · 전 열 동일 엔진 · 세후액=만기 전량매도 후 실수령")
    print(f"  · 오버레이: B1={B1_ON} · VOLTGT={VOLTGT_ON}(목표{VOLTGT_TARGET:.0%}) "
          f"· 빠른복귀={FAST_RECOVER} · SIGNAL_LAG={SIGNAL_LAG}(봇 정합)")
    print("█" * _LN)


# ══════════════ [7. 실행] ══════════════
if __name__ == "__main__":
    db = _drive_base()
    print("=" * 122)
    print("  라오어 VR v3 — 거치식·적립식·인출식 (+킬스위치/B1/VOLTGT) · 신호·집행 분리 · ★연차 실현과세")
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
    print("  · ★v3 세금: 매도 실현익 → 12/31 정산(부채 계상) → 다음해 6월 첫 거래일 부록A 방식 납부.")
    print(f"    공제 연 ₩{TAX_DEDUCTION_KRW:,.0f}(≈${TAX_DEDUCTION:,.0f} @₩{FX_KRWUSD:,.0f}/$, "
          f"이 계좌 전액사용·이월 없음·마지막해 1회) · 이월결손 차단 · 수수료 편도 {(FEE_RATE+SLIP)*100:.2f}%.")
    print("    v2 재현 = TAX_MODE='maturity' + TAX_DEDUCTION=250.0 + FEE_RATE=0.0"
          " + SHARPE_RF='irx' + SHARPE_NUM='arith'  (5개 동시)")
    print("=" * 122)

    if ON(CHART_ON):
        try:
            make_chart(df, CHART_START, mode=CHART_MODE)
        except Exception as e:
            print(f"  · 차트 생략({str(e)[:70]})")
