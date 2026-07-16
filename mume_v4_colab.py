# ============================================================================
#  라오어 VR — [진단 I] VOLTGT 2010 이전 검증  · Colab 단일 셀
# ============================================================================
#  질문: VOLTGT가 2000 닷컴 · 2008 금융위기 같은 고변동기에 노출을 줄였나?
#
#  ★★핵심 한계 (B1과 다름):
#     B1     = GSPC/M0 신호 → 1986~ 실데이터 → 신호 시점 신뢰 O
#     VOLTGT = TQQQ RV 신호 → 2010 이전 합성 → 신호 자체가 합성
#     → VOLTGT는 '언제 축소하는지'조차 합성 변동성에 의존
#
#  그래서 이 진단은 두 부분으로 나눈다:
#   [A] 시점 포착 — VOLTGT가 언제 scale<1 (노출축소) 했나
#        합성 TQQQ RV ≈ NDX RV × 3, NDX는 실데이터 → '시점'은 참고 가능
#   [B] 성과 기여 — 롤링 dMDD/dCAGR
#        ❌ scale 크기가 합성이라 성과는 신뢰 불가. 부호도 B1처럼 못 믿음.
#        → 참고로만 출력, 결론 근거로 쓰지 말 것
#
#  실행: 이 셀 전체 Colab 붙여넣기 → Shift+Enter.  필요: m0_full.csv (Drive 루트)
# ============================================================================
!pip -q install yfinance 2>/dev/null
import os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

# ═══════════ [설정] — canonical과 동일 ═══════════
FETCH_START = "1985-10-01"
END_DATE    = "2026-07-10"
SIGNAL_LAG  = 1
B1_PCTL, B1_WIN_Y = 0.75, 10
BUBBLE_LIMIT, FAST_RECOVER = 1.30, "on"
VOLTGT_TARGET, VOLTGT_LOOKBACK = 0.60, 20
HOLD_CAP, HOLD_POOL, HOLD_G, HOLD_LIMIT = 100000.0, 0.10, 10, 0.50
BAND_LOW, BAND_HIGH = 0.85, 1.15
TAX_RATE, TAX_DEDUCTION = 0.22, 250.0
TQQQ_REAL_START, QQQ_REAL_START = "2010-02-11", "1999-03-10"
def ON(x): return str(x).strip().lower() == "on"

# 위기 구간 (시점 포착 확인용)
CRISES = [("2000 닷컴",     "2000-03-01", "2002-10-01"),
          ("2008 금융위기", "2007-10-01", "2009-03-01"),
          ("2020 코로나",   "2020-02-01", "2020-05-01"),
          ("2022 약세장",   "2022-01-01", "2022-12-31")]

# ═══════════ [데이터] — canonical build_data 그대로 ═══════════
def _drive_base():
    if 'google.colab' in sys.modules:
        try:
            from google.colab import drive; drive.mount('/content/drive')
            return '/content/drive/MyDrive/'
        except Exception: return ''
    return ''
def _first(*c): return next((x for x in c if x and os.path.exists(x)), None)
def _flat(path, col):
    df = pd.read_csv(path); df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df = df.set_index(df.columns[0]).sort_index()
    if col in df.columns: return df[col].dropna()
    tail = col.split("|")[-1]
    for c in df.columns:
        if str(c).endswith("|"+tail) or str(c).lower().startswith(tail.lower()):
            return df[c].dropna()
    return None

def build_data(db=""):
    ndx=irx=gspc=qqq_real=tqqq_real=m0=None
    try:
        import yfinance as yf
        def _c(t,s):
            d=yf.download(t,start=s,end=END_DATE,auto_adjust=True,progress=False)["Close"]
            d=d.squeeze() if hasattr(d,"squeeze") else d
            d.index=pd.to_datetime(d.index).tz_localize(None); return d.dropna()
        ndx=_c("^NDX",FETCH_START); irx=_c("^IRX",FETCH_START); gspc=_c("^GSPC",FETCH_START)
        qqq_real=_c("QQQ",QQQ_REAL_START); tqqq_real=_c("TQQQ",TQQQ_REAL_START)
        print("  · 지수: yfinance 실시간")
    except Exception as e:
        print(f"  · yfinance 불가({str(e)[:36]}) → 캐시")
    if ndx is None or gspc is None:
        bp=_first("base_indices.csv",db+"price_cache_base_indices.csv")
        if bp:
            ndx=ndx if ndx is not None else _flat(bp,"Close|^NDX")
            irx=irx if irx is not None else _flat(bp,"Close|^IRX")
            gspc=gspc if gspc is not None else _flat(bp,"Close|^GSPC")
    if qqq_real is None:
        qp=_first("qqq_drive.csv",db+"price_cache_tk_QQQ.csv")
        if qp: qqq_real=_flat(qp,"Close|QQQ")
    if tqqq_real is None:
        tp=_first("tqqq_drive.csv",db+"price_cache_tk_TQQQ.csv")
        if tp: tqqq_real=_flat(tp,"Close|TQQQ")
    mp=_first("m0_full.csv",db+"m0_full.csv")
    if mp:
        md=pd.read_csv(mp); md.index=pd.to_datetime(md[md.columns[0]])
        m0=pd.to_numeric(md[md.columns[-1]],errors="coerce").dropna()
    if ndx is None or gspc is None or m0 is None:
        raise RuntimeError("^NDX/^GSPC/M0 확보 실패 — m0_full.csv 필요.")

    idx=pd.date_range(ndx.index[0],ndx.index[-1],freq="B")
    ndx=ndx.reindex(idx).ffill(); gspc=gspc.reindex(idx).ffill()
    irx=(irx.reindex(idx).ffill().bfill() if irx is not None else pd.Series(2.5,index=idx))
    m0=m0.reindex(idx).ffill().bfill()
    def splice(syn,real,name):
        if real is None or real.empty: return syn
        real=real.reindex(idx).ffill(); rf=real.first_valid_index()
        if rf is None or pd.isna(syn.loc[rf]): return syn
        sc=syn.loc[rf]/real.loc[rf]; out=syn.copy(); mk=idx>=rf
        out[mk]=(real*sc).reindex(idx[mk]).ffill()
        print(f"  · {name} 스플라이스 @ {rf.date()} (scale {sc:.3f})"); return out
    qqq=splice((1+ndx.pct_change().fillna(0).clip(-.5,.5)).cumprod()*100,qqq_real,"QQQ")
    # canonical NEW 합성: -33% 이하 -99% 고정
    r_ndx=qqq.pct_change().fillna(0)
    daily_lev=np.where(r_ndx<=-0.3333,-0.99,r_ndx*3)
    daily_cost=(irx/100+0.0084)/252
    tqqq_syn=(1+(pd.Series(daily_lev,index=qqq.index)-daily_cost)).cumprod()*100
    tqqq=splice(tqqq_syn,tqqq_real,"TQQQ")
    out=pd.DataFrame({"TQQQ":tqqq,"QQQ":qqq,"GSPC":gspc,"NDX":ndx,"IRX":irx,
                      "GSMA":gspc.rolling(200).mean(),"NSMA":ndx.rolling(200).mean(),
                      "BUB":gspc/m0}).dropna()
    w=int(252*B1_WIN_Y)
    out["BUB_PCTL"]=out["BUB"].rolling(w,min_periods=int(252*3)).apply(
        lambda x:(x[-1]>=x).mean(),raw=True)
    tq_al=tqqq_real.reindex(out.index).ffill() if tqqq_real is not None else None
    ret_syn=out["TQQQ"].pct_change()
    ret_rv=(tq_al.pct_change().where(tq_al.pct_change().notna(),ret_syn)
            if tq_al is not None else ret_syn)
    out["RV"]=ret_rv.rolling(VOLTGT_LOOKBACK).std()*np.sqrt(252)
    # ★NDX 자체 RV도 계산 (합성 오염 없는 참조용)
    out["RV_NDX"]=out["NDX"].pct_change().rolling(VOLTGT_LOOKBACK).std()*np.sqrt(252)
    return out

# ═══════════ [엔진] — canonical 축약 ═══════════
def split_cycles(index):
    first=index[0]; dss=(first.weekday()-5)%7
    anchor=(first-pd.Timedelta(days=dss)).normalize()
    cyc,ck,cur=[],None,[]
    for ts in index:
        k=(ts.normalize()-anchor).days//14
        if k!=ck:
            if cur: cyc.append(cur)
            cur,ck=[],k
        cur.append(ts)
    if cur: cyc.append(cur)
    return cyc
def _signals(d):
    lag=int(SIGNAL_LAG); sh=(lambda s:s.shift(lag)) if lag>0 else (lambda s:s)
    dts=list(d.index)
    me=pd.Series([(i<len(dts)-1 and dts[i+1].month!=dts[i].month) for i in range(len(dts))],index=d.index)
    return {"G":sh(d["GSPC"]),"GS":sh(d["GSMA"]),"NX":sh(d["NDX"]),"NS":sh(d["NSMA"]),
            "BU":sh(d["BUB"]),"PCTL":sh(d["BUB_PCTL"]),"RV":sh(d["RV"]),
            "ME":sh(me.astype(float)).fillna(0.0).astype(bool)}
def _vscale(sig,day,voltgt_on):
    if not ON(voltgt_on): return 1.0
    rv=sig["RV"].get(day,np.nan)
    if pd.isna(rv) or rv<=0: return 1.0
    return min(1.0,VOLTGT_TARGET/float(rv))
def _exit_sig(sig,dd,b1_on):
    g=sig["G"].get(dd,np.nan); gs=sig["GS"].get(dd,np.nan)
    if pd.isna(g) or pd.isna(gs) or g>=gs: return False
    bub=sig["BU"].get(dd,np.nan)
    if not pd.isna(bub) and bub>=BUBBLE_LIMIT: return True
    if ON(b1_on):
        pc=sig["PCTL"].get(dd,np.nan)
        if not pd.isna(pc) and pc>=B1_PCTL: return True
    return False
def _recover_sig(sig,dd):
    if not bool(sig["ME"].get(dd,False)): return False
    g=sig["G"].get(dd,np.nan); gs=sig["GS"].get(dd,np.nan)
    if pd.isna(g) or pd.isna(gs): return False
    spx_ok=g>gs; bub=sig["BU"].get(dd,np.nan)
    if not pd.isna(bub) and bub<BUBBLE_LIMIT:
        nx=sig["NX"].get(dd,np.nan); ns=sig["NS"].get(dd,np.nan)
        ndx_ok=(not pd.isna(nx) and not pd.isna(ns) and nx>ns)
        return spx_ok or (ON(FAST_RECOVER) and ndx_ok)
    return spx_ok
def run_vr(d,voltgt_on,b1_on,killswitch,init=HOLD_CAP):
    px=d["TQQQ"]; sig=_signals(d)
    stock=init*(1-HOLD_POOL); pool=init*HOLD_POOL
    shares=stock/float(px.iloc[0]); V=shares*float(px.iloc[0])
    n_exit=0; daily=[]; state="INVESTED"
    for cd in split_cycles(px.index):
        Veff=V*_vscale(sig,cd[0],voltgt_on); bmin,bmax=Veff*BAND_LOW,Veff*BAND_HIGH
        budget=max(0,pool)*HOLD_LIMIT; used=0.0
        for dd in cd:
            p=float(px.loc[dd])
            if killswitch:
                if state=="INVESTED" and _exit_sig(sig,dd,b1_on):
                    pool+=shares*p; shares=0.0; state="CASH"; n_exit+=1
                    daily.append((dd,pool)); continue
                if state=="CASH" and _recover_sig(sig,dd):
                    buy=min(Veff,pool); shares=buy/p; pool-=buy; state="INVESTED"
            if state=="INVESTED":
                ev=shares*p
                if ev<bmin:
                    b=min(bmin-ev,pool,max(0,budget-used))
                    if b>1e-9: shares+=b/p; pool-=b; used+=b
                elif ev>bmax:
                    s=ev-bmax
                    if s>1e-9: shares-=s/p; pool+=s
            daily.append((dd,shares*p+pool))
        if state=="INVESTED":
            V=V+pool/HOLD_G
    dd_=pd.DataFrame(daily,columns=["d","t"]).set_index("d")
    mdd=float((dd_.t/dd_.t.cummax()-1).min()); nav=float(dd_.t.iloc[-1])
    yrs=(dd_.index[-1]-dd_.index[0]).days/365.25
    tax=max(0,nav-init-TAX_DEDUCTION)*TAX_RATE; at=nav-tax
    cagr=(at/init)**(1/yrs)-1 if at>0 else float('nan')
    return dict(aftertax=at,mdd=mdd,cagr=cagr,n_exit=n_exit)

# ═══════════ [실행] ═══════════
if __name__=="__main__":
    print("="*88); print("  라오어 VR — 진단 I · VOLTGT 2010 이전 검증"); print("="*88)
    db=_drive_base(); df=build_data(db)
    print(f"  · {df.index[0].date()}~{df.index[-1].date()} ({len(df)}행)\n")

    # ── [A] 시점 포착 — VOLTGT가 위기에 노출 축소했나 ──
    print("="*88)
    print("  [A] 시점 포착 — VOLTGT scale<1 (노출축소) 발동 (★NDX 기반이라 참고 가능)")
    print("="*88)
    sig=_signals(df)
    print(f"{'위기':<16}{'구간일수':>8}{'scale<1 일수':>13}{'축소율':>8}{'최저scale':>10}{'평균축소%':>10}")
    print("-"*70)
    for name,cs,ce in CRISES:
        seg=df[(df.index>=cs)&(df.index<=ce)]
        if len(seg)==0: continue
        scales=[_vscale(sig,dd,"on") for dd in seg.index]
        scales=[s for s in scales if not pd.isna(s)]
        n=len(scales); below=sum(1 for s in scales if s<0.999)
        min_s=min(scales) if scales else 1.0
        avg_cut=(1-np.mean([s for s in scales if s<0.999]))*100 if below>0 else 0
        era="(합성)" if pd.Timestamp(cs)<pd.Timestamp("2010-02-11") else "(실측)"
        print(f"{name+era:<16}{n:>8}{below:>13}{below/n*100:>7.0f}%{min_s:>10.3f}{avg_cut:>9.1f}%")
    print("-"*70)
    print("  → 닷컴·금융위기(합성)에 scale<1 발동하면 '고변동 시점 포착'은 됨(NDX 기반)")
    print("    단 축소 '크기'는 합성 RV라 신뢰 불가")

    # ── [B] VOLTGT 순기여 롤링 — 10/7/5년으로 겹침 영향 확인 ──
    def voltgt_rolling(HOLD_Y, step):
        last=df.index[-1]-pd.DateOffset(years=HOLD_Y)
        starts=pd.date_range(df.index[0],last,freq=step)
        rows=[]
        for sd in starts:
            sub=df[(df.index>=sd)&(df.index<=sd+pd.DateOffset(years=HOLD_Y))]
            if len(sub)<int(252*HOLD_Y*0.9): continue
            r_off=run_vr(sub,"off","on",True); r_on=run_vr(sub,"on","on",True)
            c_off,m_off=r_off["cagr"],r_off["mdd"]; c_on,m_on=r_on["cagr"],r_on["mdd"]
            if not (np.isfinite(c_off) and np.isfinite(c_on) and m_off<0 and m_on<0): continue
            era="실측" if sd>=pd.Timestamp("2010-02-11") else "합성"
            rows.append(dict(era=era,dmdd=(m_on-m_off)*100,dcagr=(c_on-c_off)*100,
                             nav_ratio=r_on["aftertax"]/r_off["aftertax"]))
        R=pd.DataFrame(rows); RM=R[R.era=="실측"]
        print("\n"+"="*88)
        print(f"  [B] VOLTGT 순기여 — {HOLD_Y}년 보유·{step} 간격")
        print("="*88)
        if len(RM)>0:
            n=len(RM); cw=(RM.dcagr>0).sum(); mw=(RM.dmdd>0).sum(); nw=(RM.nav_ratio>1).sum()
            print(f"  실측 {n}개 | CAGR개선 {cw}/{n} ({cw/n*100:.0f}%) · 낙폭방어 {mw}/{n} ({mw/n*100:.0f}%) · 자산우세 {nw}/{n}")
            print(f"  dCAGR: P10 {RM.dcagr.quantile(.10):+.2f} / 중앙 {RM.dcagr.median():+.2f} / P90 {RM.dcagr.quantile(.90):+.2f} %p")
            print(f"  dMDD 중앙 {RM.dmdd.median():+.1f}%p · 자산비 {RM.nav_ratio.median():.3f}")
            comp=(1+RM.dcagr.median()/100)**HOLD_Y
            print(f"  → 중앙 dCAGR {HOLD_Y}년 복리: {(comp-1)*100:+.1f}%")
        return RM

    r10=voltgt_rolling(10,"3MS")
    r7 =voltgt_rolling(7,"2MS")
    r5 =voltgt_rolling(5,"1MS")
    print("\n"+"="*88)
    print("  [종합] 겹침 줄여도 CAGR 비용 유지되나")
    print("="*88)
    for lab,R in [("10년",r10),("7년",r7),("5년",r5)]:
        if len(R)>0:
            cw=(R.dcagr>0).sum(); n=len(R)
            print(f"  {lab}: 실측 {n}개 · CAGR개선 {cw}/{n} ({cw/n*100:.0f}%) · 중앙 dCAGR {R.dcagr.median():+.2f}%p · dMDD {R.dmdd.median():+.1f}%p · 자산비 {R.nav_ratio.median():.3f}")
    print("\n  판독: 5년(겹침 최소)에서도 CAGR개선 낮고 중앙 음수면 → 비용 확정, 끄는 게 맞다.")
    print("        5년에서 CAGR개선이 크게 늘면 → 10년은 겹침 착시. 재검토.")========================================================================================
  라오어 VR — 진단 I · VOLTGT 2010 이전 검증
========================================================================================
Mounted at /content/drive
  · 지수: yfinance 실시간
  · QQQ 스플라이스 @ 1999-03-10 (scale 42.248)
  · TQQQ 스플라이스 @ 2010-02-11 (scale 1435.351)
  · 1986-07-07~2026-07-09 (10439행)

========================================================================================
  [A] 시점 포착 — VOLTGT scale<1 (노출축소) 발동 (★NDX 기반이라 참고 가능)
========================================================================================
위기                  구간일수   scale<1 일수     축소율   최저scale     평균축소%
----------------------------------------------------------------------
2000 닷컴(합성)          675          675    100%     0.203     55.7%
2008 금융위기(합성)        370          315     85%     0.238     33.0%
2020 코로나(실측)          65           49     75%     0.225     59.9%
2022 약세장(실측)         260          258     99%     0.440     32.9%
----------------------------------------------------------------------
  → 닷컴·금융위기(합성)에 scale<1 발동하면 '고변동 시점 포착'은 됨(NDX 기반)
    단 축소 '크기'는 합성 RV라 신뢰 불가

========================================================================================
  [B] VOLTGT 순기여 — 10년 보유·3MS 간격
========================================================================================
  실측 25개 | CAGR개선 0/25 (0%) · 낙폭방어 25/25 (100%) · 자산우세 0/25
  dCAGR: P10 -2.25 / 중앙 -1.03 / P90 -0.52 %p
  dMDD 중앙 +4.1%p · 자산비 0.926
  → 중앙 dCAGR 10년 복리: -9.8%

========================================================================================
  [B] VOLTGT 순기여 — 7년 보유·2MS 간격
========================================================================================
  실측 56개 | CAGR개선 7/56 (12%) · 낙폭방어 50/56 (89%) · 자산우세 7/56
  dCAGR: P10 -3.21 / 중앙 -1.15 / P90 +0.28 %p
  dMDD 중앙 +0.8%p · 자산비 0.944
  → 중앙 dCAGR 7년 복리: -7.8%

========================================================================================
  [B] VOLTGT 순기여 — 5년 보유·1MS 간격
========================================================================================
  실측 137개 | CAGR개선 32/137 (23%) · 낙폭방어 99/137 (72%) · 자산우세 32/137
  dCAGR: P10 -4.50 / 중앙 -0.76 / P90 +0.85 %p
  dMDD 중앙 +1.3%p · 자산비 0.973
  → 중앙 dCAGR 5년 복리: -3.8%

========================================================================================
  [종합] 겹침 줄여도 CAGR 비용 유지되나
========================================================================================
  10년: 실측 25개 · CAGR개선 0/25 (0%) · 중앙 dCAGR -1.03%p · dMDD +4.1%p · 자산비 0.926
  7년: 실측 56개 · CAGR개선 7/56 (12%) · 중앙 dCAGR -1.15%p · dMDD +0.8%p · 자산비 0.944
  5년: 실측 137개 · CAGR개선 32/137 (23%) · 중앙 dCAGR -0.76%p · dMDD +1.3%p · 자산비 0.973

  판독: 5년(겹침 최소)에서도 CAGR개선 낮고 중앙 음수면 → 비용 확정, 끄는 게 맞다.
        5년에서 CAGR개선이 크게 늘면 → 10년은 겹침 착시. 재검토.
