# -*- coding: utf-8 -*-
# ============================================================================
# fs_scorecard.py — 거짓 탈출·복귀 판정 채점표 v1 (2026-08-22, Gemini 역할 구현)
#   명세: 칠판 「거짓 탈출·복귀 판정 명세서 v1」(64줄, md5 0931ca7e) §1~§3 그대로.
#   지위: 관찰용 채점표 — 킬스위치 판정 규칙 무변경, 각 신호일에 점수만 부기.
#   임계값은 명세로 사전 고정(사후 조정 금지). 매매 편입 여부는 성적표 후 은박사님 별도 재가.
#   실행: Colab %run fs_scorecard.py  (드라이브 자동 연결·FRED 캐시 로컬+드라이브·한글 그래프)
# ============================================================================
import os, io, hashlib, subprocess, sys
import numpy as np
import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yfinance"], check=False)
    import yfinance as yf

# ── [임계값 — 명세 §2 사전 고정] ─────────────────────────────────────────────
BUBBLE_LIMIT   = 1.30      # 무장: 버블지수(S&P500 ÷ M0십억$) ≥ 1.30
SAHM_HI        = 0.50      # S1 +1
SAHM_LO        = 0.10      # S1 −1
CR_JUMP        = 1.00      # S2 +1: c − min126 ≥ 1.00%p AND Δ20 > 0
CR_CALM        = 0.50      # S2 −1: c − min126 ≤ 0.50%p
R1_DROP        = 0.90      # R1 +1: c ≤ 0.90×peak AND Δ20 < 0
R1_STICK       = 0.98      # R1 −1: c ≥ 0.98×peak
MIN126, D20    = 126, 20
LBL_TRUE_DD    = 0.20      # 탈출 진짜: 추가 하락 ≥20% 또는 USREC 포함
LBL_FALSE_DD   = 0.10      # 탈출 거짓: 추가 하락 <10% (10~20% 회색)
RET_WIN        = 126       # 복귀 진짜: 126거래일 내 재탈출 없음 AND 최저 −10% 이내
RET_WIN2       = 252       # 병기 전용(채점 기준은 126 고정)
RET_DD         = 0.10
FETCH_START    = "1985-10-01"
# ── 신용 c(t) 3원 접합(추록1 §2, 2026-08-22 재가): 임계·판정식 무변경 ──
MIRROR_URL     = "https://raw.githubusercontent.com/csaladenes/eco-archive/master/BAMLH0A0HYM2.csv"
MIRROR_MD5     = "ec8668ebf7bd9e5a7cf68e15c993482c"   # 고정 — 불일치 시 실행 중단(추록1 §3a)
HY_CUT         = "1996-12-31"     # 이전 = 폴백(기존)
MIRROR_END     = "2021-03-19"     # 미러 구간 끝
GAP_END        = "2023-08-21"     # 공백(폴백) 구간 끝 — 이후 = 현행 FRED
FRESH_DAYS     = 14               # 추록1 §3c: 현행 구간 마지막 관측 최신성
# ── FAST-B1 게이트(추록2 개정판): 백테스터 K2 블록 자구 — 당일 포함 롤링 백분위 ──
B1_PCTL        = 0.75             # 출처: 백테스터(TQQQ50금50 v3tax) GATE_MODE="B1" 정의부
B1_WIN         = int(252 * 10)    # 10년 롤링 창(자구: _b1_w)
B1_MINP        = int(252 * 3)     # 자구 min_periods=756 — 초기 ~3년 NaN(추록 §1 서술 정합;
                                  #   §2의 '252' 표기 대신 원문 자구를 따름 — 납품 보고 명기)
EXIT_INDEX     = "NDX"     # 명세 §3-1: 사건 수 대조는 동일 설정 실행분과만
FRED_CSV       = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1985-10-01"   # ★수정1: 기본 3년창 방지
M0_PATHS       = ["m0_full.csv", "/content/drive/MyDrive/m0_full.csv"]

def _md5s(s): return hashlib.md5(s.encode() if isinstance(s, str) else s).hexdigest()[:8]
def _md5_file(p): return hashlib.md5(open(p, 'rb').read()).hexdigest()[:8]

def _ensure_drive():
    base = "/content/drive/MyDrive"
    if os.path.isdir(base): return base
    try:
        from google.colab import drive
        drive.mount('/content/drive', force_remount=False)
        if os.path.isdir(base): return base
    except Exception:
        pass
    return None

def fetch_fred(sid, min_rows=100, max_start=None):
    """FRED 시리즈 수신 — 캐시 로컬+드라이브 동시 저장(Colab 표준), 재실행 시 캐시 우선.
       ★수정2(감사역): max_start 가드 — 시리즈 시작일이 이보다 늦으면 절단 수신으로 간주.
       절단된 기존 캐시는 자동 무시하고 재수신하며, 재수신도 늦으면 실행 중단·보고."""
    fn = f"fred_{sid}.csv"
    db = _ensure_drive()
    for p in [fn] + ([f"{db}/{fn}"] if db else []):
        if os.path.exists(p):
            try:
                s = pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0].dropna()
                if len(s) >= min_rows:
                    if max_start is not None and s.index[0] > pd.Timestamp(max_start):
                        print(f"  · {sid} 캐시 절단 감지({p}: {s.index[0].date()} 시작) — 무시하고 재수신")
                        continue
                    print(f"  · {sid} 캐시 사용: {p} ({len(s)}행, md5={_md5_file(p)})")
                    return s
            except Exception:
                pass
    r = requests.get(FRED_CSV.format(sid=sid), timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ['DATE', sid]
    df['DATE'] = pd.to_datetime(df['DATE'])
    s = pd.to_numeric(df.set_index('DATE')[sid], errors='coerce').dropna()
    s.to_csv(fn)
    if db:
        try: s.to_csv(f"{db}/{fn}")
        except Exception: pass
    print(f"  · {sid} 수신: {len(s)}행 ({s.index[0].date()}~{s.index[-1].date()}) — 캐시 로컬{'+드라이브' if db else ''} 저장")
    if max_start is not None and s.index[0] > pd.Timestamp(max_start):
        raise SystemExit(f"★중단: {sid} 시작일 {s.index[0].date()} > 허용 {max_start} — 절단 수신. "
                         f"신용 채점 무효 방지를 위해 실행을 멈춥니다(감사역 수정 2).")
    return s

def fetch_mirror():
    """추록1 §2: GitHub 미러(1996-12-31~2021-03-19). 캐시 로컬+드라이브 — 사용 전마다 md5 재검증,
       다운로드본도 md5 불일치면 즉시 중단(행수가 아니라 md5로 가드)."""
    fn = "hy_mirror_BAMLH0A0HYM2.csv"
    db = _ensure_drive()
    raw = None
    for p_ in [fn] + ([f"{db}/{fn}"] if db else []):
        if os.path.exists(p_):
            b = open(p_, 'rb').read()
            if hashlib.md5(b).hexdigest() == MIRROR_MD5:
                print(f"  · 미러 캐시 사용: {p_} (md5 일치 {MIRROR_MD5[:8]})")
                raw = b; break
            print(f"  · 미러 캐시 md5 불일치({p_}) — 무시하고 재수신")
    if raw is None:
        r = requests.get(MIRROR_URL, timeout=60); r.raise_for_status()
        raw = r.content
        got = hashlib.md5(raw).hexdigest()
        if got != MIRROR_MD5:
            raise SystemExit(f"★중단: 미러 md5 {got[:8]} ≠ 고정 {MIRROR_MD5[:8]} — 무결성 실패(추록1 §3a).")
        open(fn, 'wb').write(raw)
        if db:
            try: open(f"{db}/{fn}", 'wb').write(raw)
            except Exception: pass
        print(f"  · 미러 수신: md5 일치 {MIRROR_MD5[:8]} — 캐시 로컬{'+드라이브' if db else ''} 저장")
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = ['DATE', 'V']
    s = pd.to_numeric(df.set_index(pd.to_datetime(df['DATE']))['V'], errors='coerce').dropna()
    print(f"  · 미러 유효 관측 {len(s)}개 ({s.index[0].date()}~{s.index[-1].date()}) — 결측 자동 제거")
    return s

def fetch_m0():
    """M0(BOGMBASE, 십억$) — 백테스터 정본 캐시(m0_full.csv) 우선 재사용(명세 §1)."""
    db = _ensure_drive()
    paths = [M0_PATHS[0]] + ([f"{db}/m0_full.csv"] if db else [])
    for p in paths:
        if os.path.exists(p):
            s = pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0].dropna()
            print(f"  · M0 정본 캐시 사용: {p} ({len(s)}개월, md5={_md5_file(p)})")
            return s
    s = fetch_fred("BOGMBASE")
    return s / 1000.0 if s.median() > 10000 else s   # 백만$ 단위면 십억$로

def _fetch_close(tk, start):
    df = yf.download(tk, start=start, progress=False, auto_adjust=False)
    if df is None or len(df) == 0: raise RuntimeError(f"{tk} 수신 실패")
    s = df['Close']
    if isinstance(s, pd.DataFrame): s = s.iloc[:, 0]
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.dropna()

def build_events(gate_mode="ABS"):
    """명세 §3-1: 전 기간 1회 실행으로 무장 상태 탈출·복귀 사건 전건 추출.
       신호 로직 = 통합 엔진 run_r4 ④블록 자구(무장 AND NDX<SMA200 탈출 일일 / 복귀 월말 핫·냉 게이트).
       gate_mode(추록2 개정판): "ABS"=버블≥1.30(기존 무변경) / "B1"=버블의 10년 롤링 백분위(당일 포함,
       K2 자구) ≥ 0.75 — 게이트 함수는 무장 판정과 복귀 핫/콜드 분기 양쪽에 공용, NaN이면 닫힘."""
    ndx = _fetch_close('^NDX', FETCH_START)
    gspc = _fetch_close('^GSPC', FETCH_START)
    idx = ndx.index
    gspc = gspc.reindex(idx).ffill()
    nsma = ndx.rolling(200).mean()
    gsma = gspc.rolling(200).mean()
    m0 = fetch_m0()
    m0d = m0.reindex(idx.union(m0.index)).ffill().reindex(idx)
    bub = gspc / m0d
    pctl = bub.rolling(B1_WIN, min_periods=B1_MINP).apply(
        lambda x: float((x[-1] >= x).mean()), raw=True) if gate_mode == "B1" else None   # K2 자구
    exits, rets = [], []
    state = 'IN'
    ep_exit_date = None
    dates = list(idx)
    for i, cd in enumerate(dates):
        if pd.isna(nsma.iloc[i]) or pd.isna(gsma.iloc[i]) or pd.isna(bub.iloc[i]): continue
        is_me = (i < len(dates) - 1 and dates[i + 1].month != cd.month)
        if gate_mode == "B1":
            _pv = pctl.iloc[i]
            gate_hot = (not pd.isna(_pv)) and _pv >= B1_PCTL      # NaN → 게이트 닫힘
        else:
            gate_hot = bub.iloc[i] >= BUBBLE_LIMIT
        exit_px, exit_sma = (ndx.iloc[i], nsma.iloc[i]) if EXIT_INDEX == "NDX" else (gspc.iloc[i], gsma.iloc[i])
        if state == 'IN':
            if gate_hot and exit_px < exit_sma:
                state = 'OUT'; ep_exit_date = cd
                exits.append(dict(date=cd, bub=float(bub.iloc[i]), px=float(exit_px),
                                  pctl=(float(pctl.iloc[i]) if gate_mode == "B1" else float('nan'))))
        else:
            if is_me:
                spx_ok = gspc.iloc[i] > gsma.iloc[i]
                rec = spx_ok if gate_hot else (spx_ok or ndx.iloc[i] > nsma.iloc[i])
                if rec:
                    rets.append(dict(date=cd, exit_date=ep_exit_date, bub=float(bub.iloc[i]),
                                     px=float(gspc.iloc[i]), hot=bool(gate_hot),
                                     pctl=(float(pctl.iloc[i]) if gate_mode == "B1" else float('nan'))))
                    state = 'IN'; ep_exit_date = None
    print(f"  · 사건 추출(게이트={gate_mode}, EXIT_INDEX=\"{EXIT_INDEX}\"): 탈출 {len(exits)}건 · "
          f"복귀 {len(rets)}건 ({idx[0].date()}~{idx[-1].date()})")
    return ndx, gspc, exits, rets

def build_macro():
    """실업(Sahm, 발표지연: 월 M 값은 M+1월 10일부터) · 신용 c(t)(하이일드, 1996-12-31 이전 폴백 Baa−10Y)."""
    un = fetch_fred("UNRATE")
    sahm_rt = fetch_fred("SAHMREALTIME", min_rows=50)
    ma3 = un.rolling(3).mean()
    sahm = ma3 - ma3.rolling(12).min()                      # 명세 §0 정의(자체 계산)
    avail = sahm.copy()
    avail.index = (sahm.index + pd.offsets.MonthBegin(1)) + pd.Timedelta(days=9)   # M+1월 10일
    hy_new = fetch_fred("BAMLH0A0HYM2")                        # 현행 3년 롤링 창(추록1 §2)
    if (pd.Timestamp.now().normalize() - hy_new.index[-1]).days > FRESH_DAYS:
        raise SystemExit(f"★중단: 현행 FRED 마지막 관측 {hy_new.index[-1].date()}가 "
                         f"실행일 기준 {FRESH_DAYS}일 초과(추록1 §3c).")
    mir = fetch_mirror()
    baa = fetch_fred("DBAA"); g10 = fetch_fred("DGS10")
    fb = (baa - g10.reindex(baa.index).ffill()).dropna()
    cut, me, ge = pd.Timestamp(HY_CUT), pd.Timestamp(MIRROR_END), pd.Timestamp(GAP_END)
    c = pd.concat([fb[fb.index < cut],                          # ~1996-12-30 폴백(기존)
                   mir[(mir.index >= cut) & (mir.index <= me)], # 미러
                   fb[(fb.index > me) & (fb.index <= ge)],      # 공백 폴백(사건 0건 — 추록1 §2)
                   hy_new[hy_new.index > ge]]).sort_index()     # 현행
    c = c[~c.index.duplicated()]
    if c.index[0] > pd.Timestamp("1997-01-10"):
        raise SystemExit(f"★중단: 접합 후 c(t) 시작일 {c.index[0].date()} > 1997-01-10(추록1 §3b).")
    ov1 = pd.concat([fb, mir], axis=1, keys=['fb', 'x']).dropna()
    ov2 = pd.concat([fb, hy_new], axis=1, keys=['fb', 'x']).dropna()
    print(f"  · 겹침 보고 ①폴백↔미러(1996-12-31~{MIRROR_END}): 상관 {ov1['fb'].corr(ov1['x']):.3f} · "
          f"수준차(미러−폴백) {float((ov1['x']-ov1['fb']).mean()):+.2f}%p ({len(ov1)}일)")
    print(f"  · 겹침 보고 ②폴백↔현행(2023-08-22~): 상관 {ov2['fb'].corr(ov2['x']):.3f} · "
          f"수준차(현행−폴백) {float((ov2['x']-ov2['fb']).mean()):+.2f}%p ({len(ov2)}일)")
    print("  · 미러↔현행 직접 겹침 없음(공백 2021-03-20~2023-08-21 존재 — 폴백으로 접합, 추록1 §4)")
    usrec = fetch_fred("USREC", min_rows=50)
    return sahm, sahm_rt, avail, c, usrec

def _sahm_at(avail, t):
    s = avail[avail.index <= t]
    return float(s.iloc[-1]) if len(s) else np.nan

def _cr_at(c, t):
    """전일 기준: t 이전(미포함) 마지막 관측으로 c·min126·Δ20."""
    s = c[c.index < t]
    if len(s) < MIN126 + D20: return np.nan, np.nan, np.nan
    cv = float(s.iloc[-1])
    return cv, float(cv - s.iloc[-MIN126:].min()), float(cv - s.iloc[-1 - D20])

def _src_of(c, t):
    """채점에 쓰인 c(t)의 소스(추록1 §4): 전일 마지막 관측일 기준."""
    s = c[c.index < t]
    if not len(s): return "결측"
    d = s.index[-1]
    if d < pd.Timestamp(HY_CUT): return "폴백"
    if d <= pd.Timestamp(MIRROR_END): return "미러"
    if d <= pd.Timestamp(GAP_END): return "폴백"
    return "현행"

def _run_scorecard(tag, sfx, ndx, gspc, exits, rets, sahm, avail, c, usrec, self_md5, show_pctl):
    """채점~표~행렬~기준선~CSV~차트 — v3 main 본문 자구 이동(로직 무변경). tag/sfx/show_pctl만 인자화."""
    dates = list(ndx.index)
    pos = {d: k for k, d in enumerate(dates)}
    exit_dates = [e['date'] for e in exits]

    # ── 탈출 채점 ──
    ex_rows = []
    for e in exits:
        t = e['date']
        nxt = min([r['date'] for r in rets if r['date'] > t], default=dates[-1])
        seg = ndx[(ndx.index >= t) & (ndx.index <= nxt)]
        dd = float(1.0 - seg.min() / e['px']) if len(seg) else np.nan
        rec_in = usrec[(usrec.index >= t.replace(day=1)) & (usrec.index <= nxt)]
        has_rec = bool((rec_in > 0).any())
        truth = "진짜" if (dd >= LBL_TRUE_DD or has_rec) else ("거짓" if dd < LBL_FALSE_DD else "회색")
        sv = _sahm_at(avail, t - pd.Timedelta(days=1))
        s1 = 0 if np.isnan(sv) else (1 if sv >= SAHM_HI else (-1 if sv <= SAHM_LO else 0))
        cv, over, d20 = _cr_at(c, t)
        s2 = 0 if np.isnan(cv) else (1 if (over >= CR_JUMP and d20 > 0) else (-1 if over <= CR_CALM else 0))
        E = s1 + s2
        if truth == "회색": hit = "회색"
        elif truth == "진짜": hit = "적중" if E >= 1 else ("미탐" if E <= -1 else "중립")
        else: hit = "적중" if E <= -1 else ("오탐" if E >= 1 else "중립")
        ex_rows.append(dict(종류="탈출", 날짜=str(t.date()), 버블=round(e['bub'], 3),
                            Sahm=(round(sv, 2) if sv == sv else "결측"), S1=s1,
                            스프레드=(round(cv, 2) if cv == cv else "결측"),
                            초과min126=(round(over, 2) if over == over else ""), Δ20=(round(d20, 2) if d20 == d20 else ""),
                            S2=s2, 점수=E, 추가하락pct=round(dd * 100, 1), USREC=int(has_rec),
                            소스=_src_of(c, t), 정답=truth, 판정=hit,
                            **({"백분위": round(e['pctl'], 3)} if show_pctl else {})))

    # ── 복귀 채점 ──
    rt_rows = []
    for r in rets:
        t = r['date']; ed = r['exit_date']
        seg = c[(c.index >= ed) & (c.index < t)]
        peak = float(seg.max()) if len(seg) else np.nan
        cv, over, d20 = _cr_at(c, t)
        if np.isnan(cv) or np.isnan(peak) or peak <= 0:
            R = 0
        else:
            R = 1 if (cv <= R1_DROP * peak and d20 < 0) else (-1 if cv >= R1_STICK * peak else 0)
        i0 = pos[t]
        w126 = dates[i0 + 1: i0 + 1 + RET_WIN]
        re_ex = next((d for d in exit_dates if d > t and (not w126 or d <= w126[-1])), None)
        seg_g = gspc[(gspc.index > t)][:RET_WIN]
        low_ok = bool(len(seg_g) and seg_g.min() / r['px'] >= 1.0 - RET_DD)
        truth = "진짜" if (re_ex is None and low_ok) else "거짓"
        if len(seg_g) < RET_WIN and re_ex is None:               # 추록2: 창 미충족 → 잠정 표기
            truth = truth + "(잠정)"
        w252 = dates[i0 + 1: i0 + 1 + RET_WIN2]
        re252 = next((d for d in exit_dates if d > t and (not w252 or d <= w252[-1])), None)
        seg2 = gspc[(gspc.index > t)][:RET_WIN2]
        t252 = "진짜" if (re252 is None and len(seg2) and seg2.min() / r['px'] >= 1.0 - RET_DD) else "거짓"
        _tb = truth.replace("(잠정)", "")
        if _tb == "진짜": hit = "적중" if R >= 1 else ("미탐" if R <= -1 else "중립")
        else: hit = "적중" if R <= -1 else ("오탐" if R >= 1 else "중립")
        rt_rows.append(dict(종류="복귀", 날짜=str(t.date()), 탈출일=str(ed.date()) if ed is not None else "",
                            버블=round(r['bub'], 3), 스프레드=(round(cv, 2) if cv == cv else "결측"),
                            peak=(round(peak, 2) if peak == peak else ""), Δ20=(round(d20, 2) if d20 == d20 else ""),
                            점수=R, 소스=_src_of(c, t), 정답=truth, 정답252=t252, 판정=hit,
                            **({"백분위": round(r['pctl'], 3)} if show_pctl else {})))

    T = pd.DataFrame(ex_rows + rt_rows)
    T.to_csv(f"fs_scorecard{sfx}.csv", index=False, encoding="utf-8-sig")

    # ── 채점표 인쇄 ──
    print("\n" + "-" * 110)
    print(f"  [{tag} 채점표 — 탈출]  (지표는 전일 기준 · Sahm은 발표지연 반영 가용 최신월)")
    _pc_h = f"|{'백분위':>7}" if show_pctl else ""
    print(f"   {'날짜':^12}|{'버블':>6}{_pc_h}|{'Sahm':>6}|{'S1':>3}|{'스프레드':>8}|{'초과':>6}|{'Δ20':>6}|{'S2':>3}|"
          f"{'E':>3}|{'추가하락':>8}|{'REC':>4}|{'소스':^4}|{'정답':^4}|{'판정':^4}")
    for r in ex_rows:
        _pc_v = f"|{r.get('백분위', ''):>7}" if show_pctl else ""
        print(f"   {r['날짜']:^12}|{r['버블']:>6}{_pc_v}|{str(r['Sahm']):>6}|{r['S1']:>3}|{str(r['스프레드']):>8}|"
              f"{str(r['초과min126']):>6}|{str(r['Δ20']):>6}|{r['S2']:>3}|{r['점수']:>3}|"
              f"{r['추가하락pct']:>7.1f}%|{r['USREC']:>4}|{r['소스']:^4}|{r['정답']:^4}|{r['판정']:^4}")
    print(f"\n  [{tag} 채점표 — 복귀]  (peak = 대피 에피소드 내 스프레드 최고)")
    print(f"   {'날짜':^12}|{'탈출일':^12}|{'스프레드':>8}|{'peak':>7}|{'Δ20':>6}|{'R':>3}|{'소스':^4}|{'정답':^4}|{'252일':^5}|{'판정':^4}")
    for r in rt_rows:
        print(f"   {r['날짜']:^12}|{r['탈출일']:^12}|{str(r['스프레드']):>8}|{str(r['peak']):>7}|"
              f"{str(r['Δ20']):>6}|{r['점수']:>3}|{r['소스']:^4}|{r['정답']:^4}|{r['정답252']:^5}|{r['판정']:^4}")

    # ── 혼동행렬(신호별·합산) ──
    def _mat(rows, key, name):
        cnt = {}
        for r in rows:
            if r['정답'] == "회색": continue
            if "(잠정)" in str(r.get('정답', '')): continue        # 잠정은 행렬 제외(표기만)
            v = r[key]
            sgn = "+1" if v >= 1 else ("-1" if v <= -1 else "0")
            cnt[(r['정답'], sgn)] = cnt.get((r['정답'], sgn), 0) + 1
        print(f"    {name:<10} | " + " | ".join(f"{k[0]}/{k[1]}:{v}" for k, v in sorted(cnt.items())))
    print("\n  [혼동행렬] (회색 제외)")
    _mat(ex_rows, 'S1', "탈출 S1"); _mat(ex_rows, 'S2', "탈출 S2"); _mat(ex_rows, '점수', "탈출 E")
    _mat(rt_rows, '점수', "복귀 R")
    ok_e = sum(1 for r in ex_rows if r['판정'] == "적중"); tot_e = sum(1 for r in ex_rows if r['정답'] != "회색")
    ok_r = sum(1 for r in rt_rows if r['판정'] == "적중")
    maj_e = max(sum(1 for r in ex_rows if r['정답'] == "진짜"), sum(1 for r in ex_rows if r['정답'] == "거짓"))
    maj_r = max(sum(1 for r in rt_rows if r['정답'] == "진짜"), sum(1 for r in rt_rows if r['정답'] == "거짓"))
    print(f"\n  [기준선 대조] 탈출: 적중 {ok_e}/{tot_e}(중립 제외 아님·회색 제외) vs 무정보 다수클래스 {maj_e}/{tot_e}"
          f" | 복귀: 적중 {ok_r}/{len(rt_rows)} vs 무정보 {maj_r}/{len(rt_rows)}")
    print("  · 판정(명세 §3-5)은 감사역 몫 — 본 스크립트는 측정·표만 산출. 목표 오답 2건(2002-03형·2007-12형)의")
    print("    포착 여부는 복귀 채점표에서 해당 날짜 행을 직접 확인.")

    print(f"\n  [V5] 산출물: fs_scorecard{sfx}.csv = {_md5_file(f'fs_scorecard{sfx}.csv')} ({len(T)}행) | script = {self_md5}")

    # ── 타임라인 차트 2단(명세 §3-4) ──
    try:
        import matplotlib
        try:
            from IPython import get_ipython
            in_nb = (get_ipython() is not None) or ('google.colab' in sys.modules)
        except Exception:
            in_nb = False
        if not in_nb: matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        try:
            import matplotlib.font_manager as fm
            for f in ["NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "AppleGothic"]:
                if any(f.lower() in x.name.lower() for x in fm.fontManager.ttflist):
                    plt.rcParams['font.family'] = f; break
            else:
                subprocess.run(["apt-get", "-qq", "install", "-y", "fonts-nanum"], check=False, capture_output=True)
                fm.fontManager.addfont("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
                plt.rcParams['font.family'] = "NanumGothic"
            plt.rcParams['axes.unicode_minus'] = False
        except Exception:
            pass
        col = {"적중": "green", "오탐": "red", "미탐": "red", "중립": "gray", "회색": "lightgray"}
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 2]}, sharex=True)
        a1.set_title(f"[{tag}] 거짓 탈출·복귀 채점 타임라인 — ▼탈출 ▲복귀 (초록=적중, 빨강=오답, 회색=중립)")
        a1.plot(ndx.index, ndx, lw=0.9, color="#444", label="NDX")
        for r in ex_rows:
            d = pd.Timestamp(r['날짜'])
            a1.scatter([d], [float(ndx.asof(d))], marker="v", s=70, color=col.get(r['판정'], "gray"), zorder=5)
        for r in rt_rows:
            d = pd.Timestamp(r['날짜'])
            a1.scatter([d], [float(ndx.asof(d))], marker="^", s=70, color=col.get(r['판정'], "gray"), zorder=5)
        a1.set_yscale("log"); a1.set_ylabel("NDX (Log)"); a1.grid(alpha=0.3); a1.legend(fontsize=9)
        a2.plot(c.index, c, lw=0.9, color="crimson", label="신용스프레드 c(t) %p")
        a2b = a2.twinx()
        a2b.plot(sahm.index, sahm, lw=1.1, color="#1f77b4", label="Sahm")
        a2b.axhline(SAHM_HI, color="#1f77b4", ls=":", lw=1)
        a2.set_ylabel("스프레드 (%p)", color="crimson"); a2b.set_ylabel("Sahm", color="#1f77b4")
        a2.grid(alpha=0.3)
        h1, l1 = a2.get_legend_handles_labels(); h2, l2 = a2b.get_legend_handles_labels()
        a2.legend(h1 + h2, l1 + l2, fontsize=9, loc="upper left")
        plt.tight_layout(); plt.savefig(f"fs_timeline{sfx}.png", dpi=100, bbox_inches="tight")
        print(f"  · 차트 저장: fs_timeline{sfx}.png")
        if in_nb:
            try: plt.show()
            except Exception: pass
        plt.close()
    except Exception as e:
        print(f"  · 차트 생략({str(e)[:70]})")
    print("=" * 110)


def main():
    print("=" * 110)
    print("  [거짓 탈출·복귀 채점표] 명세 v1(md5 0931ca7e) — 관찰 전용 · 킬스위치 판정 무변경 · 임계 사전 고정")
    print("=" * 110)
    try:
        self_md5 = hashlib.md5(open(__file__, 'rb').read()).hexdigest()
    except Exception:
        self_md5 = "(셀 실행 — 칠판 raw로 대조)"
    print(f"  · 스크립트 md5: {self_md5}")
    print(f"  · 라벨 규칙(사후 정답): 탈출 진짜=추가하락 ≥{LBL_TRUE_DD*100:.0f}%(판정지수 NDX, 탈출일 종가 대비"
          f" 다음 복귀까지 최저) 또는 USREC 포함 / 거짓=<{LBL_FALSE_DD*100:.0f}% / 사이=회색.")
    print(f"    복귀 진짜=복귀 후 {RET_WIN}거래일 내 재탈출 없음 AND 최저 −{RET_DD*100:.0f}% 이내(판정지수 GSPC —"
          f" 복귀 판정 지수와 동일 해석, 주석 명기). {RET_WIN2}일 창은 병기만(채점은 {RET_WIN} 고정).")

    ndx, gspc, exits, rets = build_events()
    sahm, sahm_rt, avail, c, usrec = build_macro()

    # ── SAHMREALTIME 대조표 1회(명세 §3-3) ──
    rt_al = sahm_rt.copy()                                   # ★선택(감사역 §4): 실시간 시리즈는 한 달 뒤
    rt_al.index = rt_al.index - pd.offsets.MonthBegin(1)     #   시점 기준 — 한 달 당겨 정렬 후 비교
    both = pd.concat([sahm.rename('자체'), rt_al.rename('FRED')], axis=1).dropna()
    diff = (both['자체'] - both['FRED']).abs()
    print(f"\n  [대조] 자체 Sahm vs SAHMREALTIME(한 달 시프트 정렬): 겹침 {len(both)}개월 · "
          f"최대차 {diff.max():.3f} · 불일치(>0.05) {int((diff > 0.05).sum())}건"
          + (" — 보고 요망" if (diff > 0.05).any() else " ✓"))

    _run_scorecard("FAST-ABS", "", ndx, gspc, exits, rets, sahm, avail, c, usrec, self_md5, show_pctl=False)

    # ── FAST-B1 절(추록2 개정판): 게이트만 백분위(≥0.75)로 교체 — 그 외 전부 동일 ──
    print("\n" + "=" * 110)
    print("  [FAST-B1 확장] 게이트 = 버블 10년 롤링 백분위(당일 포함, K2 자구) ≥ "
          f"{B1_PCTL} · min_periods={B1_MINP}(원문 252×3 — 초기 ~3년 NaN=닫힘)")
    print(f"  · B1_PCTL={B1_PCTL:.2f}(출처: 백테스터 TQQQ50금50 v3tax GATE_MODE=\"B1\" 정의부 — K2 이식 블록)")
    print("  · 탈출지수 NDX 고정·복귀 GSPC 월말(비대칭)·콜드 시 NDX 빠른복귀·E/R 판정식·임계·라벨 전부 무변경.")
    print("  · 기존 FAST-ABS 표와 모집단이 다르므로 별도 절 — 혼합 금지(추록2 개정판 §2).")
    ndx2, gspc2, exits2, rets2 = build_events(gate_mode="B1")
    _run_scorecard("FAST-B1", "_b1", ndx2, gspc2, exits2, rets2, sahm, avail, c, usrec, self_md5, show_pctl=True)

if __name__ == "__main__":
    main()
