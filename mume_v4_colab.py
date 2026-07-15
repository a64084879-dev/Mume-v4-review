B1을 2010년 부터만 측정을했는데,1986년 부터 2009년12월 까지다시확인하는것이 어떨까? 순수 합성으로만 하면  그때도 별로 오차없이 B1에관한것은 측정해낼수있을것 같은데?

날카로운 생각입니다. 논리는 맞습니다 — B1의 신호는 지수(GSPC/M0)로만 만들어지고 TQQQ 가격을 안 쓰므로, 합성 구간에서도 대피 시점 자체는 정확히 계산됩니다. 실제 S&P·M0는 1986년부터 진짜 데이터니까요.
다만 한 가지가 걸립니다. 그걸 코드로 먼저 짚어보겠습니다.Analyzing what can and cannot be measured with B1 in the synthetic 1986-2009 periodAnalyzing what can and cannot be measured with B1 in the synthetic 1986-2009 period부분적으로 맞습니다 — 신호는 되지만 성과는 안 됩니다
핵심을 나눠야 합니다.
측정 가능한 것 (신호만 쓰는 것): B1의 대피/복귀 시점은 1986~2009도 정확합니다. GSPC·M0·SMA200·버블 백분위가 전부 그 시절 진짜 데이터니까요. 은박사 말씀이 맞습니다.
측정 불가한 것 (합성가에 오염): 대피가 "얼마를 지켰나" — MDD 개선폭, 자산비, CAGR은 전부 합성 TQQQ 가격에 의존합니다. 우리가 이미 이 구간에서 킬스위치 500~700배 유령을 목격했고, 그래서 배제하기로 한 겁니다. −80% MDD가 진짜인지 ±50% 클리핑 산물인지 구분이 안 됩니다.
그러니 목적을 좁히면 가치가 있습니다. "B1을 다시 측정한다"가 성과 재측정이면 무의미하지만, "신호 행동 측정"이면 값어치가 있습니다.
오히려 더 중요한 걸 얻을 수 있습니다
이 구간에서 정말 확인할 가치가 있는 건 원조건(버블≥1.30)입니다.
2010년 이후 원조건은 0회 발동했고(QE로 M0 팽창), 그래서 "죽은 신호, 보험으로만 유지"로 판정했습니다. 그런데 2000년 닷컴 버블과 2008년 금융위기 때는 어땠을까요? 그때 버블이 1.30을 넘었다면:

**"킬스위치 원조건은 QE 이전엔 살아 있었다"**가 확인됩니다
원조건을 보험으로 켜두는 근거가 강해집니다 (죽은 게 아니라 잠자는 것)
그리고 QE가 끝나거나 통화 환경이 바뀌면 다시 살아날 수 있다는 뜻이 됩니다

이건 성과와 무관하게 순수 신호 계산이라 합성 오염을 안 받습니다.
그리고 B1의 성격을 2회 더 볼 수 있습니다
B1이 닷컴(2000)과 금융위기(2008)를 잡았는지도 신호만으로 확인됩니다. 잡았다면 B1의 "고평가+하락 필터" 성격이 2회 더 확인되는 셈입니다. 지금 B1의 방어 근거가 2022 한 건(n=1)에 몰려 있는데, **닷컴·금융위기에서도 제때 대피 신호를 냈다면 "신호 자체는 여러 위기에서 작동한다"**는 게 됩니다.
다만 냉정하게: 이것도 독립 표본 +2이지 통계적 확증은 아닙니다. 그리고 "대피 시점이 맞았다"와 "대피가 돈을 지켰다"는 다른 문제라, 후자는 여전히 합성 오염으로 측정 불가입니다.
제안
진단을 이렇게 좁혀서 만들면 가치 있습니다:

1986~2009 구간에서 원조건(1.30) 발동일 목록 — 2000·2008에 걸렸나
B1 대피 신호 발동일 목록 — 어떤 하락장을 언제 잡았나
각 대피일의 버블값·백분위 실측 — 임계가 그 시절엔 어디였나

성과 수치(MDD·자산비·CAGR)는 아예 출력하지 않습니다. 합성 오염된 숫자를 보여주면 또 유령에 휘둘리니까요. 오직 **"신호가 언제, 왜 발동했나"**만 봅니다.
이렇게 목적을 명확히 하면 만들 가치가 있습니다. 만들까요? 아니면 원조건 발동 여부만 빠르게 확인하는 미니 버전으로 할까요?

986~2009 구간에서 원조건(1.30) 발동일 목록 — 2000·2008에 걸렸나  이것은 걸렸다.. 벌써해봤다  그랴도 포함해서 다한번 만들어봐라
좋습니다. 원조건이 2000·2008에 걸렸다는 걸 이미 확인하셨으니, 그걸 포함해서 신호 행동 전체를 보는 진단을 만들겠습니다. 성과 수치(MDD·자산비·CAGR)는 합성 오염이라 아예 출력하지 않고, 오직 신호가 언제·왜 발동했는가만 봅니다.파일 생성됨, 파일 읽음파일 생성됨, 파일 읽음Colab 단일 셀로 만들었습니다. 붙여넣고 Shift+Enter만 하면 됩니다.
핵심 설계 — 성과는 아예 계산하지 않습니다
이게 이 진단의 원칙입니다. MDD·자산비·CAGR을 출력하지 않습니다. 그 숫자들은 합성 TQQQ 가격에 오염돼 있고(500~700배 유령을 이미 겪었으니), 보여주면 또 휘둘립니다. 오직 신호 — GSPC·M0·SMA200·백분위로만 만들어지는, 1986년부터 진짜인 것 — 만 봅니다.
나오는 것 4가지
[1] 원조건(1.30) 발동 구간 — 이미 확인하신 2000·2008이 시대(QE 이전/이후) 라벨과 함께 나옵니다. QE 이후 0구간으로 확정되면 "원조건은 QE 시대에 죽었다"가 자동 판정됩니다.
[2] B1 대피 구간 전체 — 1986~2026 각 대피가 시작·종료·일수·평균 백분위·최대 버블과 함께. 닷컴·금융위기를 B1이 언제 잡았는지 나옵니다.
[3] 위기별 대조표 — 7개 위기(블랙먼데이·닷컴·금융위기·2018Q4·코로나·2022·2025)마다 원조건과 B1 중 누가 먼저 잡았나. 이게 흥미로울 겁니다 — 닷컴·금융위기에서는 원조건이 먼저 잡고, 2018 이후로는 B1만 잡는 패턴이 나올 가능성이 높습니다. 그게 나오면 "QE가 원조건을 죽였고 B1이 그 자리를 물려받았다"는 서사가 신호로 확인됩니다.
[4] 요약 + 차트 — 버블 궤적에 원조건(빨강)·B1(파랑) 발동 구간을 음영으로 겹치고, 2010 QE 경계선을 그어 한눈에 보이게 했습니다.
이걸로 얻는 것 (그리고 못 얻는 것)
얻는 것: B1의 "고평가+하락 필터" 성격이 닷컴·금융위기에서도 작동했다는 신호 확인. 지금 B1 방어 근거가 2022 한 건(n=1)에 몰려 있는데, 신호 차원에서는 여러 위기에서 제때 발동했다는 게 보이면 근거가 넓어집니다. 그리고 원조건을 보험으로 켜두는 정당성(QE 이전엔 살아 있었다).
못 얻는 것: "대피가 돈을 지켰나"는 여전히 측정 불가입니다. 신호가 제때 발동한 것과 그 대피가 수익을 방어한 것은 다른 문제이고, 후자는 합성 TQQQ라 신뢰할 수 없습니다. 그래서 "신호 작동 ✓, 성과 방어 ✗(측정불가)"를 요약에 명시해뒀습니다.
돌려서 결과 주시면 교차검산하겠습니다 — 특히 [3] 위기별 대조에서 원조건→B1 세대교체 패턴이 나오는지 보겠습니다.
# ============================================================================
#  라오어 VR — [진단 G] 대피 신호 행동 분석  (1986~2026 전 구간)  · Colab 단일 셀
# ============================================================================
#  ★이 진단은 '성과'를 측정하지 않는다. '신호'만 본다.
#
#  이유: B1·킬스위치 신호는 GSPC/M0/SMA200로만 만들어진다 (전부 1986~ 실제 데이터).
#        → 대피/복귀 '시점'은 합성 구간에서도 정확하다.
#        반면 그 시점에 매매되는 TQQQ는 1986~2009가 합성(±50% 클리핑)이라
#        → MDD·자산비·CAGR은 오염된다. 그래서 아예 계산하지 않는다.
#
#  측정하는 것 (전부 신호 = 오염 없음):
#    ① 원조건(버블≥1.30) 발동 구간 — 2000 닷컴 / 2008 금융위기에 걸렸나
#    ② B1(백분위≥0.75) 대피 구간 — 어떤 하락장을 언제 잡았나
#    ③ 각 위기별로 누가 먼저 걸렸나 (원조건 vs B1)
#    ④ QE 전후 원조건의 생사 (2010 경계)
#
#  실행: 이 셀 전체를 Colab에 붙여넣고 Shift+Enter.
#  필요: m0_full.csv (Drive 루트)
# ============================================================================
!pip -q install yfinance 2>/dev/null

import os, sys, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

# ═══════════ [설정] ═══════════
END_DATE     = "2026-07-10"
FETCH_START  = "1985-10-01"
B1_PCTL      = 0.75
B1_WIN_Y     = 10
BUBBLE_LIMIT = 1.30
QE_BOUNDARY  = "2010-01-01"     # 이 이후가 QE 팽창 구간

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
    if col in df.columns: return df[col].dropna()
    tail = col.split("|")[-1]
    for c in df.columns:
        if str(c).endswith("|" + tail) or str(c).lower().startswith(tail.lower()):
            return df[c].dropna()
    return None

# ═══════════ [데이터 — 신호에 필요한 것만] ═══════════
def build_signal_data(db=""):
    gspc = m0 = None
    try:
        import yfinance as yf
        g = yf.download("^GSPC", start=FETCH_START, end=END_DATE,
                        auto_adjust=True, progress=False)["Close"]
        g = g.squeeze() if hasattr(g, "squeeze") else g
        g.index = pd.to_datetime(g.index).tz_localize(None)
        gspc = g.dropna()
        print("  · GSPC: yfinance 실시간")
    except Exception as e:
        print(f"  · yfinance 불가({str(e)[:40]}) → 캐시")
    if gspc is None:
        bp = _first("base_indices.csv", db + "price_cache_base_indices.csv")
        if bp: gspc = _flat(bp, "Close|^GSPC")

    mp = _first("m0_full.csv", db + "m0_full.csv")
    if mp:
        md = pd.read_csv(mp)
        md.index = pd.to_datetime(md[md.columns[0]])
        m0 = pd.to_numeric(md[md.columns[-1]], errors="coerce").dropna()
    if gspc is None or m0 is None:
        raise RuntimeError("GSPC/M0 확보 실패 — m0_full.csv를 Drive 루트에 두세요.")

    idx = pd.date_range(gspc.index[0], gspc.index[-1], freq="B")
    gspc = gspc.reindex(idx).ffill()
    m0 = m0.reindex(idx).ffill().bfill()

    out = pd.DataFrame({"GSPC": gspc, "SMA200": gspc.rolling(200).mean(),
                        "BUB": gspc / m0})
    w = int(252 * B1_WIN_Y)
    out["PCTL"] = out["BUB"].rolling(w, min_periods=int(252 * 3)).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)
    out["below"] = out["GSPC"] < out["SMA200"]
    # 대피 트리거 (신호만 — SIGNAL_LAG 무관, 시점 파악이 목적)
    out["ks_orig"] = out["below"] & (out["BUB"] >= BUBBLE_LIMIT)
    out["b1"]      = out["below"] & (out["PCTL"] >= B1_PCTL)
    out["evac"]    = out["ks_orig"] | out["b1"]
    return out.dropna(subset=["SMA200"])

# ═══════════ [구간 추출] ═══════════
def _segments(mask):
    """연속 True 구간을 (시작일, 종료일, 일수) 리스트로."""
    segs = []
    in_seg = False; s = None; prev = None
    for dt, v in mask.items():
        if v and not in_seg:
            in_seg = True; s = dt
        elif not v and in_seg:
            in_seg = False; segs.append((s, prev))
        prev = dt
    if in_seg: segs.append((s, prev))
    return [(a, b, (mask.index.get_loc(b) - mask.index.get_loc(a) + 1)) for a, b in segs]

def _era(dt):
    return "QE이전" if dt < pd.Timestamp(QE_BOUNDARY) else "QE이후"

# ═══════════ [실행] ═══════════
if __name__ == "__main__":
    print("=" * 92)
    print("  라오어 VR — 진단 G · 대피 신호 행동 (1986~2026)")
    print("  ※ 성과(MDD·자산·CAGR) 없음. 신호 시점만 — 합성 오염 없는 것만.")
    print("=" * 92)
    db = _drive_base()
    d = build_signal_data(db)
    print(f"  · 신호 시계열: {d.index[0].date()} ~ {d.index[-1].date()} ({len(d)}행)\n")

    # ── ① 원조건(버블≥1.30) 발동 구간 ──
    print("=" * 92)
    print("  [1] 원조건 킬스위치 (버블 ≥ 1.30 AND SMA200 이탈) — 발동 구간")
    print("=" * 92)
    ks = _segments(d["ks_orig"])
    if ks:
        print(f"{'':3}{'시작':<13}{'종료':<13}{'일수':>6}{'시대':>10}{'최대버블':>10}")
        print("-" * 60)
        for a, b, n in ks:
            mb = d.loc[a:b, "BUB"].max()
            print(f"{'':3}{str(a.date()):<13}{str(b.date()):<13}{n:>6}{_era(a):>10}{mb:>10.2f}")
        qe_pre = sum(1 for a, _, _ in ks if a < pd.Timestamp(QE_BOUNDARY))
        qe_post = len(ks) - qe_pre
        print("-" * 60)
        print(f"  → QE이전 {qe_pre}구간 / QE이후 {qe_post}구간")
        print(f"  ★ 원조건은 {'QE이전에만 발동 → QE가 버블비율을 억제했음 확인' if qe_post==0 else 'QE이후에도 발동'}")
    else:
        print("  발동 없음")

    # ── ② B1 대피 구간 ──
    print("\n" + "=" * 92)
    print("  [2] B1 대피 (버블 백분위 ≥ 0.75 AND SMA200 이탈) — 발동 구간")
    print("=" * 92)
    b1 = _segments(d["b1"])
    print(f"  총 {len(b1)}개 구간")
    print(f"{'':3}{'시작':<13}{'종료':<13}{'일수':>6}{'시대':>9}{'평균백분위':>11}{'최대버블':>9}")
    print("-" * 66)
    for a, b, n in b1:
        pc = d.loc[a:b, "PCTL"].mean(); mb = d.loc[a:b, "BUB"].max()
        print(f"{'':3}{str(a.date()):<13}{str(b.date()):<13}{n:>6}{_era(a):>9}{pc:>11.3f}{mb:>9.2f}")

    # ── ③ 주요 위기별 — 누가 언제 걸렸나 ──
    print("\n" + "=" * 92)
    print("  [3] 주요 위기별 대피 신호 (원조건 vs B1 — 누가 먼저 잡았나)")
    print("=" * 92)
    crises = [("1987 블랙먼데이", "1987-08-01", "1988-06-01"),
              ("2000 닷컴버블",   "2000-03-01", "2003-06-01"),
              ("2008 금융위기",   "2007-10-01", "2009-09-01"),
              ("2018 Q4 급락",    "2018-09-01", "2019-02-01"),
              ("2020 코로나",     "2020-02-01", "2020-06-01"),
              ("2022 약세장",     "2022-01-01", "2023-02-01"),
              ("2025 관세",       "2025-01-01", "2025-07-01")]
    print(f"{'위기':<18}{'원조건 첫발동':>15}{'B1 첫발동':>14}{'먼저 잡은 쪽':>14}")
    print("-" * 62)
    for name, cs, ce in crises:
        seg = d.loc[cs:ce]
        ks_days = seg.index[seg["ks_orig"]]
        b1_days = seg.index[seg["b1"]]
        ks_first = ks_days[0].date() if len(ks_days) else None
        b1_first = b1_days[0].date() if len(b1_days) else None
        if ks_first and b1_first:
            winner = "원조건" if ks_first <= b1_first else "B1"
        elif b1_first:
            winner = "B1만"
        elif ks_first:
            winner = "원조건만"
        else:
            winner = "미발동"
        print(f"{name:<18}{str(ks_first) if ks_first else '—':>15}"
              f"{str(b1_first) if b1_first else '—':>14}{winner:>14}")

    # ── ④ 요약 ──
    print("\n" + "=" * 92)
    print("  [4] 요약")
    print("=" * 92)
    n_ks = int(d["ks_orig"].sum()); n_b1 = int(d["b1"].sum())
    ks_post = int(d.loc[QE_BOUNDARY:, "ks_orig"].sum())
    b1_pre = int(d.loc[:QE_BOUNDARY, "b1"].sum())
    b1_post = int(d.loc[QE_BOUNDARY:, "b1"].sum())
    print(f"  원조건 발동일: 총 {n_ks}일  (QE이후 {ks_post}일)")
    print(f"  B1 발동일:     총 {n_b1}일  (QE이전 {b1_pre}일 / QE이후 {b1_post}일)")
    print()
    print("  판독:")
    print("   · 원조건 QE이후 0일 → '킬스위치 원조건은 QE 시대에 죽었다' 확정")
    print("   · 원조건 QE이전 >0 → '2000·2008엔 살아있었다 = 보험으로 켜둘 근거'")
    print("   · B1이 닷컴·금융위기·코로나·2022 전부 잡았으면 → 신호는 여러 위기에서 작동")
    print("     (단 '신호 작동'이지 '성과 방어'가 아님 — 후자는 합성 오염으로 측정불가)")
    print("=" * 92)

    # ── 시각화 ──
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(14, 7), sharex=True,
                               gridspec_kw={"height_ratios": [2, 1]})
        ax[0].plot(d.index, d["BUB"], color="black", lw=0.7, label="Bubble (S&P/M0)")
        ax[0].axhline(1.30, color="red", ls="--", lw=1, label="원조건 1.30")
        ax[0].axvline(pd.Timestamp(QE_BOUNDARY), color="green", ls=":", lw=1.2, label="QE 경계 2010")
        ax[0].fill_between(d.index, 0, d["BUB"].max(), where=d["ks_orig"],
                           color="red", alpha=0.25, label="원조건 발동")
        ax[0].fill_between(d.index, 0, d["BUB"].max(), where=d["b1"],
                           color="steelblue", alpha=0.20, label="B1 발동")
        ax[0].set_ylabel("Bubble"); ax[0].legend(loc="upper left", fontsize=8)
        ax[0].set_title("Bubble & 대피 신호 (1986~2026)")

        ax[1].plot(d.index, d["PCTL"], color="purple", lw=0.7, label="버블 10년 백분위")
        ax[1].axhline(0.75, color="steelblue", ls="--", lw=1, label="B1 임계 0.75")
        ax[1].axvline(pd.Timestamp(QE_BOUNDARY), color="green", ls=":", lw=1.2)
        ax[1].set_ylabel("Percentile"); ax[1].legend(loc="lower left", fontsize=8)
        plt.tight_layout(); plt.show()
    except Exception as e:
        print(f"  · 차트 생략({str(e)[:60]})")
