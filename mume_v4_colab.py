# -*- coding: utf-8 -*-
"""
라오어 VR 신호 알림 봇 (거치식 + 목돈 추가/인출) — 계산·알림만, 주문은 수동
════════════════════════════════════════════════════════════════════════
★ laoer_vr_compare.py 백테스터와 '동일한 파라미터'로 '오늘의 신호'만 계산해 텔레그램 발송.
  실제 매매는 신호 확인 후 은박사님이 직접 수동 주문.

■ [2026-07-19 책 정합 개정] 체결 모델을 책 본체(라오어 VR)대로 통일:
   · 매매의 본 경로 = '사이클 시작일에 2주치 예약매수/매도 지정가 사다리를 걸고
     장중 밴드 터치 즉시 체결'. (기존 '종가 밴드이탈→다음날 LOC 일괄'은 제거)
   · 킬스위치(대피/복귀)만 종가 판정 유지 — 이건 오버레이라 책 범위 밖.
   · 반영된 책 로직: ①사다리 본 매매화(LOC 매매신호·min_trade 제거) ②매수한도 '근처'
     칸까지(off-by-one 제거) ④사다리↔신호 경로 일치 ⑤묶음(lot)은 그룹 마지막 칸 배치
     ⑦롤오버 순서(체결보고→V갱신) ⑧전 계산을 완성 종가 뷰로 통일.
   · 유지(책 외 안전장치): sell_reach(+50%)·HARD=60·V괴리 거부·낡은명령 차단·신선도 경고.

   ※ 트레이드오프: 이 개정으로 봇은 '책'과 일치하되 백테스터(종가 체결 모형)와는
     장중 저점 터치 후 종가 복귀 케이스에서 미세하게 달라진다(책·봇=체결, 백테=무체결).
     검증된 파라미터(V공식·G·밴드·한도·킬스위치·B1)는 동일. 백테스터까지 재정합하려면
     laoer_vr_compare.py를 사다리 체결로 맞추는 별도 작업 필요.

■ 매일 계산·발송하는 신호(전체):
   1) 킬스위치 상태 : INVESTED / CASH, 오늘 대피 조건 충족 여부, (월말) 복귀 조건 충족 여부
   2) VR 사다리    : 사이클 시작일에 2주치 예약매수/매도 지정가 목록(본 매매) + 밴드 위치 상태
   3) VOLTGT       : 현재 실현변동성·목표노출(scale)·V_effective (VOLTGT_ON="on"일 때만)
   4) 목돈 추가/인출: PENDING이 있으면 P/V 고정 방식으로 반영 안내

■ 현재 포지션(은박사님이 직접 입력):
   실전은 '지금 보유 상태'에서 시작하므로 아래 4개를 정확히 넣어야 밴드가 맞음.
     POS_SHARES / POS_POOL / POS_V / LAST_CYCLE_START

■ 데이터: yfinance 실시간(^GSPC/^NDX/^IRX/TQQQ), FRED BOGMBASE(M0). 실패 시 캐시 폴백.
════════════════════════════════════════════════════════════════════════
"""
import os, time, warnings, json, html
import numpy as np
import pandas as pd
import requests
warnings.filterwarnings("ignore", category=FutureWarning)

# ══════════════ [1. 설정] ══════════════
# ── 초기 포지션 시드 (파일이 없을 때 1회만 사용. 이후엔 vr_position.json이 진실) ──
SEED_ON           = "on"          # "on"이면 파일 없을 때 아래 시드로 파일 생성
POS_SHARES        = 0.0           # 현재 TQQQ 보유 주수
POS_POOL          = 0.0           # 현재 Pool(현금, USD)
POS_V             = 0.0           # 현재 V값. 0이면 자동=보유평가금
LAST_CYCLE_START  = "2026-01-02"  # 마지막 사이클 시작일(격주 기준점)
STATE             = "INVESTED"    # "INVESTED"(주식보유) / "CASH"(대피중)

POSITION_FILE     = "vr_position.json"
UPDATE_OFFSET_FILE= "vr_update_offset.txt"   # 처리한 텔레그램 update_id 저장(중복처리 방지)
STALE_CMD_HOURS   = 30       # ★수정(2026-07): 23→30. 실행주기 24h인데 임계 23h면 실행 직후~1h 명령이 폐기(무한 폐기루프). offset이 중복 1차방어라 30h 안전.

# ── VR 파라미터 (거치식 = 백테스터·책과 동일) ──
G                 = 10
BUY_LIMIT         = 0.50
BAND_LOW, BAND_HIGH = 0.85, 1.15
BUBBLE_LIMIT      = 1.30

# ── 킬스위치/B1/빠른복귀/VOLTGT 스위치 (백테스터와 동일) ──
KILLSWITCH        = "on"
B1_ON             = "on"
B1_PCTL           = 0.75          # ★확정 2026-07-14 (0.80은 단일점 아티팩트). 절벽에서 두 칸 이격.
B1_WIN_Y          = 10
FAST_RECOVER      = "on"
VOLTGT_ON         = "off"         # ★기각 확정 2026-07-16 (롤링 표본 3종 모두 CAGR 음수). B1이 낙폭 유지.
VOLTGT_TARGET     = 0.60
VOLTGT_LOOKBACK   = 20

# ── 텔레그램 / 헬스체크 / FRED ──
TG_TOKEN          = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID", "")
HEALTHCHECK_URL   = os.environ.get("HEALTHCHECK_URL", "")
FRED_API_KEY      = os.environ.get("FRED_API_KEY", "")
PRICE_CACHE_DIR   = os.environ.get("PRICE_CACHE_DIR", ".")
# ★안내문구 분기용(2026-07-23): 러너가 AUTO_MODE=on이면 체결이 API로 자동 동기화되고
#   /buy·/sell·/exit·/enter 등은 러너 가드가 거부한다(이중반영 방지). 리포트가 그 명령을
#   보내라고 안내하면 모순이므로 문구만 바꾼다. 계산·판정 로직에는 일절 관여하지 않음.
#   봇 단독 실행 시엔 미설정 → "off" → 기존 수동 안내 그대로.
AUTO_MODE_HINT    = str(os.environ.get("AUTO_MODE", "off")).strip().lower() == "on"

FETCH_START = "1985-10-01"

def ON(x): return str(x).strip().lower() == "on"

def _wall_today():
    """사이클 달력 기준 '오늘'(KST 고정). GitHub Actions(UTC)·로컬 어디서 돌려도 한국 날짜.
       [8번] 가격·판정은 완성 종가를 쓰지만 '사이클 경계'는 달력 행위(책: 월요일에 주문을
       건다)라 봉 완성과 무관하게 오늘 날짜로 판정 — 완성종가 뷰로 옮겨도 롤오버·사다리가
       하루 밀리지 않도록."""
    return pd.Timestamp.now(tz="Asia/Seoul").normalize().tz_localize(None)

# ══════════════ [2. 데이터] ══════════════
def _tg(msg):
    """텔레그램 발송. 줄바꿈 경계 분할 + HTML 파싱 실패(400) 시 평문 폴백 재전송."""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[경고] TG_TOKEN/CHAT_ID 없음 — 콘솔 출력만"); print(msg); return False
    chunks=[]; cur=""
    for line in msg.split("\n"):
        if len(cur)+len(line)+1>3900:
            if cur: chunks.append(cur); cur=""
            while len(line)>3900:
                chunks.append(line[:3900]); line=line[3900:]
        cur = (cur+"\n"+line) if cur else line
    if cur: chunks.append(cur)
    def _send(text, use_html):
        data={"chat_id":TG_CHAT_ID,"text":text}
        if use_html: data["parse_mode"]="HTML"
        r=requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=data, timeout=30)
        return r.status_code
    ok=True
    for chunk in chunks:
        try:
            sc=_send(chunk, True)
            if sc!=200:
                print(f"[텔레그램 HTML 실패 status={sc}] 평문 재전송")
                sc2=_send(chunk, False)
                ok = ok and sc2==200
        except Exception as e:
            print(f"[텔레그램 실패] {e}"); ok=False
    return ok

def _emergency_tg(err):
    safe_err=html.escape(str(err)[:500])
    try: _tg(f"🚨 <b>VR봇 크래시</b>\n{safe_err}")
    except Exception: pass

def _cache_path(name): return os.path.join(PRICE_CACHE_DIR, f"vrbot_cache_{name}.csv")

def _yf(ticker, start=FETCH_START):
    import yfinance as yf
    try:
        cache_dir=os.path.join(PRICE_CACHE_DIR, ".yf_cache")
        os.makedirs(cache_dir, exist_ok=True)
        yf.set_tz_cache_location(cache_dir)
    except Exception:
        pass
    raw=yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if raw is None or len(raw)==0:
        raise RuntimeError(f"yfinance 빈 결과: {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        d = close.iloc[:,0] if close.ndim>1 else close
    else:
        d = raw["Close"]
    d = pd.Series(np.asarray(d).ravel(), index=pd.to_datetime(raw.index))
    d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
    return d.dropna()

def _load_m0():
    """FRED BOGMBASE(M0). 실패 시 캐시."""
    UA={"User-Agent":"Mozilla/5.0"}
    def _norm(s):
        s=pd.to_numeric(s,errors="coerce").dropna().sort_index(); s.index=pd.to_datetime(s.index)
        s=s[~s.index.duplicated(keep="last")]
        if len(s) and s.max()>100000: s=s/1000.0
        return s
    try:
        url=(f"https://api.stlouisfed.org/fred/series/observations?series_id=BOGMBASE"
             f"&api_key={FRED_API_KEY}&file_type=json&observation_start=1985-01-01")
        r=requests.get(url,headers=UA,timeout=40); r.raise_for_status()
        obs=r.json().get("observations",[])
        if obs:
            df=pd.DataFrame(obs); s=_norm(pd.Series(df["value"].values,index=pd.to_datetime(df["date"])))
            s.to_csv(_cache_path("m0"))
            _load_m0.from_cache=False; _load_m0.cache_age_days=0
            return s.resample("B").ffill()
    except Exception as e:
        print(f"[M0 FRED 실패] {e} → 캐시")
    p=_cache_path("m0")
    if os.path.exists(p):
        df=pd.read_csv(p); s=_norm(pd.Series(df[df.columns[-1]].values,index=df[df.columns[0]].values))
        try:
            _age=int((pd.Timestamp.today().normalize()-pd.Timestamp(s.index[-1])).days)
            _load_m0.cache_age_days=_age
            _load_m0.from_cache=True
            print(f"[M0 캐시 사용] 최신 {s.index[-1].date()} ({_age}일 전)")
        except Exception:
            _load_m0.cache_age_days=None; _load_m0.from_cache=True
        return s.resample("B").ffill()
    raise RuntimeError("M0 확보 실패")

def build_data():
    """백테스터 build_data와 동일한 합성 스플라이싱 + 지표. 오늘까지.
       [원자성] 티커별 개별 다운로드·저장 → 하나가 실패해도 성공 티커 캐시는 갱신.
       [신선도] 티커별 실제 마지막 날짜·폴백여부 수집 → 리포트가 차등 신선도 검사."""
    _fresh={}
    def _rd(nm):
        p=_cache_path(nm); d=pd.read_csv(p,index_col=0); d.index=pd.to_datetime(d.index)
        return pd.to_numeric(d[d.columns[-1]],errors="coerce").dropna()
    def _get(nm, ticker, start=FETCH_START):
        try:
            s=_yf(ticker, start); s.to_csv(_cache_path(nm))
            _fresh[nm]={"last":s.index[-1], "fallback":False}
            return s
        except Exception as e:
            print(f"[{ticker} 실패] {e} → 캐시 폴백")
            s=_rd(nm)
            _fresh[nm]={"last":(s.index[-1] if len(s) else None), "fallback":True}
            return s
    ndx=_get("ndx","^NDX"); irx=_get("irx","^IRX"); gspc=_get("gspc","^GSPC")
    tqqq_real=_get("tqqq","TQQQ","2010-02-11"); qqq_real=_get("qqq","QQQ","1999-03-10")
    m0=_load_m0()
    idx=pd.date_range(ndx.index[0],ndx.index[-1],freq="B")
    ndx=ndx.reindex(idx).ffill(); gspc=gspc.reindex(idx).ffill()
    irx=irx.reindex(idx).ffill().bfill(); m0=m0.reindex(idx).ffill().bfill()
    def splice(syn,real):
        real=real.reindex(idx).ffill(); rf=real.first_valid_index()
        if rf is None or pd.isna(syn.loc[rf]): return syn
        sc=syn.loc[rf]/real.loc[rf]; out=syn.copy(); mk=idx>=rf
        out[mk]=(real*sc).reindex(idx[mk]).ffill(); return out
    qqq=splice((1+ndx.pct_change().fillna(0).clip(-.5,.5)).cumprod()*100, qqq_real)
    drag=(irx/100)*2.0+0.0095+0.015
    tqqq=splice((1+(qqq.pct_change().fillna(0).clip(-.5,.5)*3-drag/252)).cumprod()*100, tqqq_real)
    out=pd.DataFrame({"TQQQ":tqqq,"QQQ":qqq,"GSPC":gspc,"NDX":ndx,"IRX":irx,
        "GSMA":gspc.rolling(200).mean(),"NSMA":ndx.rolling(200).mean(),"BUB":gspc/m0}).dropna()
    out["TQQQ_REAL"]=tqqq_real.reindex(out.index).ffill()
    w=int(252*B1_WIN_Y)
    out["BUB_PCTL"]=out["BUB"].rolling(w,min_periods=int(252*3)).apply(lambda x:(x[-1]>=x).mean(),raw=True)
    out["RV"]=out["TQQQ_REAL"].pct_change().rolling(VOLTGT_LOOKBACK).std()*np.sqrt(252)
    out.attrs["fresh"]=_fresh
    return out

# ══════════════ [3. 사이클 계산] ══════════════
def current_cycle(last_start):
    """마지막 사이클 시작일 기준 격주(14일) 사이클 — 실제 달력(KST) 기준.
       [8번] 가격·판정은 완성 종가를 쓰지만 사이클 경계는 달력 행위라 오늘 날짜로 판정.
       last_start가 미래면 그 날짜가 곧 이번 사이클 시작."""
    anchor=pd.Timestamp(last_start).normalize()
    today=_wall_today()
    if anchor>today:
        return anchor.date(), (anchor+pd.Timedelta(days=14)).date()
    k=(today-anchor).days//14
    return (anchor+pd.Timedelta(days=14*k)).date(), (anchor+pd.Timedelta(days=14*(k+1))).date()

# ══════════════ [3b. 포지션 파일 & 텔레그램 명령] ══════════════
def load_position():
    """포지션 파일 로드. 없으면 시드(SEED_ON)로 생성.
       손상 시: 0값 시드로 덮어쓰기 전에 .bak 보존 + 긴급알림."""
    if os.path.exists(POSITION_FILE):
        try:
            with open(POSITION_FILE) as f: return json.load(f)
        except Exception as e:
            print(f"[포지션 로드 실패] {e}")
            try:
                import shutil
                bak=f"{POSITION_FILE}.corrupt.{int(time.time())}.bak"
                shutil.copy2(POSITION_FILE, bak)
                _emergency_tg(f"포지션 파일 손상 감지 → {bak} 보존. 시드로 재시작될 수 있으니 /setpos 로 재설정 필요.")
            except Exception: pass
    pos={"shares":POS_SHARES,"pool":POS_POOL,"V":POS_V,
         "last_cycle_start":LAST_CYCLE_START,"state":STATE,"pending_deposit":0.0,
         "last_recover_check":LAST_CYCLE_START}
    if ON(SEED_ON): save_position(pos)
    return pos

def save_position(pos):
    try:
        tmp=POSITION_FILE+".tmp"
        with open(tmp,"w") as f: json.dump(pos,f,ensure_ascii=False,indent=2)
        os.replace(tmp,POSITION_FILE)
    except Exception as e: print(f"[포지션 저장 실패] {e}")

def ensure_V(pos, price):
    """V가 0/미설정이면 1회 확정·저장.
       INVESTED: V=보유평가금(shares×실제가). CASH: V=투자금(pool, 복귀 목표)."""
    if pos.get("V",0) <= 0:
        if pos.get("state")=="INVESTED" and pos.get("shares",0)>0:
            pos["V"]=pos["shares"]*price; save_position(pos)
        elif pos.get("state")=="CASH" and pos.get("pool",0)>0:
            pos["V"]=pos["pool"]; save_position(pos)
    return pos

def _get_updates(pos=None):
    """텔레그램 미처리 명령 수신(getUpdates). 처리한 offset 이후만.
       ★exactly-once(2026-07-24): offset을 별도 파일이 아니라 vr_position.json 안에 둔다.
         원장과 offset이 '한 번의 원자 저장'으로 함께 확정되므로 중간 사망 시
         (원장 저장·offset 미확정) 같은 어긋난 상태가 원천적으로 생기지 않는다.
         구버전 vr_update_offset.txt는 최초 1회만 읽어 승계한다(마이그레이션)."""
    if not TG_TOKEN: return []
    off=0
    if pos is not None and pos.get("tg_offset") is not None:
        try: off=int(pos["tg_offset"])+1
        except Exception: off=0
    elif os.path.exists(UPDATE_OFFSET_FILE):          # 구버전 승계(1회)
        try: off=int(open(UPDATE_OFFSET_FILE).read().strip())+1
        except Exception: off=0
    try:
        r=requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                       params={"offset":off,"timeout":5}, timeout=20)
        return r.json().get("result",[]) if r.status_code==200 else []
    except Exception as e:
        print(f"[getUpdates 실패] {e}"); return []

def _save_offset(uid):
    """(사어) exactly-once 전환(2026-07-24)으로 미사용. offset은 pos["tg_offset"]에 저장된다.
       구버전 상태파일 승계 후엔 vr_update_offset.txt를 읽지도 쓰지도 않는다."""
    try:
        tmp=UPDATE_OFFSET_FILE+".tmp"
        with open(tmp,"w") as f: f.write(str(uid))
        os.replace(tmp,UPDATE_OFFSET_FILE)
    except Exception: pass

def apply_command(pos, text, price_hint, Veff_target=None):
    """명령 하나를 포지션에 반영. 반환: (갱신pos, 처리결과문자열)."""
    t=text.strip().split()
    if not t: return pos,None
    cmd=t[0].lower()
    if "@" in cmd: cmd=cmd.split("@",1)[0]
    def _px(default):
        for tok in t:
            if tok.startswith("@"):
                try: return float(tok[1:].replace(",",""))
                except Exception:
                    raise ValueError(f"가격 '{tok}' 파싱 실패 — 숫자를 확인하세요 (예: @75.5). 조용한 종가 대체를 막기 위해 거부")
        return default
    try:
        if cmd=="/buy":
            # ★F3(2026-07-23): 대피 중 밴드 매수는 논리상 불가. 수용하면 'CASH인데 주식 보유' 모순 원장이
            #   되고, 이후 복귀신호의 min(V,Pool) 재매수와 겹쳐 이중 보유가 된다.
            if pos.get("state")=="CASH":
                return pos,"⚠️ 매수 거부: 대피(CASH) 중입니다. 복귀는 <code>/enter</code>, 현금 조정은 <code>/lumpsum ±금액 pool</code>."
            sh=float(t[1]); px=_px(price_hint); cost=sh*px
            if sh<=0: return pos,"⚠️ 매수 거부: 주수는 양수여야 합니다. (음수는 원장을 오염시킵니다. 매도는 /sell, 인출은 /lumpsum -금액)"
            if cost > pos["pool"] + 1.0:
                return pos,(f"⚠️ 매수 거부: {cost:,.0f} 필요한데 현금은 {pos['pool']:,.0f}뿐입니다.\n"
                            f"   주수를 줄이거나 /deposit 으로 현금을 넣으세요.")
            pos["shares"]+=sh; pos["pool"]-=cost
            if abs(pos["pool"])<1e-6: pos["pool"]=0.0
            pos["cyc_used"]=float(pos.get("cyc_used",0.0))+cost
            return pos,f"매수 {sh}주 @{px:,.2f} (−{cost:,.0f})"
        if cmd=="/sell":
            sh=float(t[1]); px=_px(price_hint)
            if sh<=0: return pos,"⚠️ 매도 거부: 주수는 양수여야 합니다. (음수는 원장을 오염시킵니다. 인출은 /lumpsum -금액)"
            held=pos["shares"]
            if sh > held + 1e-6:
                if sh <= held + 0.01:
                    sh=held
                else:
                    return pos,(f"⚠️ 매도 거부: {sh}주 매도인데 보유는 {held:.4f}주뿐입니다.\n"
                                f"   전량 매도하려면 <code>/exit @{px:,.2f}</code> 를 쓰세요.")
            proc=sh*px
            pos["shares"]-=sh; pos["pool"]+=proc
            if abs(pos["shares"])<1e-4: pos["shares"]=0.0
            if pos["shares"]==0.0 and pos.get("state")=="INVESTED":
                return pos,(f"매도 {sh}주 @{px:,.2f} (+{proc:,.0f})\n"
                            f"[주의] 보유0주+INVESTED - 대피면 /exit @{px:,.2f}.")
            return pos,f"매도 {sh}주 @{px:,.2f} (+{proc:,.0f})"
        if cmd=="/exit":
            # ★F2(2026-07-23): 이미 대피 완료 상태에서 /exit가 또 오면 last_recover_check가 오늘로
            #   리셋돼 그 사이 월말들이 소급판정 창에서 빠진다(복귀 최대 1개월 지연).
            #   대피 리포트의 복사 명령이 /exit라 옛 메시지 재복사로 충분히 발생한다.
            if pos.get("state")=="CASH" and pos.get("shares",0.0)<=1e-9:
                return pos,"ℹ️ 이미 대피(CASH) 상태 — 재발송 무시(복귀 기준일 보호). 복귀는 <code>/enter</code>."
            px=_px(price_hint); proc=pos["shares"]*px
            pos["pool"]+=proc; pos["shares"]=0.0; pos["state"]="CASH"
            _esd = pos.pop("evac_sig_date", None)   # ★수정(2026-07): 꺼내 쓰고 즉시 제거 → 묵은 신호일 재사용 차단(Gemini 지적: 옛 날짜 재사용 시 즉시 재매수 오신호)
            _wt = _wall_today()
            _fresh = False
            if _esd:
                try: _fresh = 0 <= (_wt - pd.Timestamp(_esd)).days <= 7   # 7일 이내만 사용 → 묵은 값 첫 사용도 차단
                except Exception: _fresh = False
            pos["last_recover_check"] = _esd if _fresh else _wt.strftime('%Y-%m-%d')
            return pos,(f"전량대피 @{px:,.2f} (+{proc:,.0f}) → CASH\n"
                        f"⚠️ 걸어둔 예약매수·매도 지정가도 <b>전량 취소</b>하세요.")
        if cmd=="/enter":
            # ★F3(2026-07-23): 이미 INVESTED면 복귀 매수가 성립하지 않는다. 수용하면 밴드 논리 밖 매수 +
            #   cyc_budget 무단 리셋으로 매수한도가 초기화된다.
            if pos.get("state")=="INVESTED":
                return pos,"⚠️ 이미 INVESTED 상태입니다 — 밴드 매수는 <code>/buy</code>, 자금 추가는 <code>/lumpsum ±금액 v|pool</code>."
            _vt=pos.get("V",0.0); _base=_vt if _vt>0 else (Veff_target if (Veff_target and Veff_target>0) else 0.0)
            _default = min(_base, pos["pool"]) if _base>0 else pos["pool"]   # 살아있는 V 우선(배치 내 stale 방지)
            amt=float(t[1]) if len(t)>1 and not t[1].startswith("@") else _default
            if amt<=0:
                return pos,("⚠️ 매수 금액이 0입니다. 복귀 목표금액을 확인하세요.\n"
                            "   (V가 0으로 설정됐을 수 있음 → /setpos로 V를 다시 넣으세요)")
            avail=pos["pool"]
            if amt > avail + 1e-6:
                if amt <= avail + 1.0:
                    amt=avail
                else:
                    return pos,(f"⚠️ 매수 거부: {amt:,.0f} 매수인데 현금은 {avail:,.0f}뿐입니다.\n"
                                f"   전액 매수하려면 금액 없이 <code>/enter @{_px(price_hint):,.2f}</code> 를 쓰세요.")
            px=_px(price_hint); sh=amt/px
            pos["shares"]+=sh; pos["pool"]-=amt
            if abs(pos["pool"])<1e-6: pos["pool"]=0.0
            pos["state"]="INVESTED"
            pos["cyc_budget"]=max(0.0,pos["pool"])*BUY_LIMIT   # 복귀 후 잔여 Pool 기준 매수한도 재설정(N1)
            pos["cyc_used"]=0.0
            pos.pop("ladder_placed_for",None)                  # 복귀 직후 새 사다리 자동 재게시(N1)
            return pos,(f"복귀매수 {amt:,.0f} @{px:,.2f} ({sh:.4f}주) → INVESTED\n"
                        f"   ↻ 잔여 Pool 기준 매수한도 재설정 · 아래에 새 사다리 즉시 게시.")
        if cmd=="/deposit":
            amt=float(t[1])
            # ★F4(2026-07-23): 음수·0 거부. 음수가 pending에 잠복하면 이후 양수 예약과 몰래 상쇄된다
            #   (예: -500 후 +700 → 실제 200). 확정단은 pend≤0을 막지만 예약단이 뚫려 있었다.
            if amt<=0:
                return pos,"⚠️ 추가납입은 양수만 가능합니다. 인출은 <code>/lumpsum -금액 v|pool</code>을 쓰세요."
            pos["pending_deposit"]=pos.get("pending_deposit",0.0)+amt
            return pos,f"추가납입 예약 {amt:,.0f} (안내대로 매수 후 /deposit_done 으로 확정)"
        if cmd=="/deposit_done":
            if pos.get("state")=="CASH":
                return pos,("⚠️ 대피(CASH) 중엔 추가납입 확정 불가. 먼저 복귀(/enter) 후 진행하세요.")
            pend=pos.get("pending_deposit",0.0)
            if pend<=0:
                return pos,"⚠️ 예약된 추가납입이 없습니다. 먼저 /deposit 금액 으로 예약하세요."
            sh=float(t[1]); px=_px(price_hint); cost=sh*px
            if sh<0:
                return pos,"[거부] 추가납입 확정 주수는 0 이상(매수 주수)."
            if cost > pend + 1.0:
                return pos,(f"⚠️ 매수비용 {cost:,.0f}이 예약액 {pend:,.0f}보다 큽니다.\n"
                            f"   주수를 확인하세요(예약금 내에서 매수해야 함).")
            V=pos.get("V",0.0); pool=pos.get("pool",0.0)
            prev_total = pool + pos.get("shares",0.0)*px
            pos["shares"]=pos.get("shares",0.0)+sh
            rest = pend - cost
            pos["pool"]=pool + rest
            if prev_total>1e-9:
                pos["V"] = V*(1.0 + pend/prev_total)
            else:
                pos["V"] = V + pend
            pos["pending_deposit"]=0.0
            pos["cyc_budget"]=max(0.0,pos["pool"])*BUY_LIMIT; pos["cyc_used"]=0.0   # 매수한도 재설정(lumpsum과 통일)
            if abs(pos["pool"])<1e-6: pos["pool"]=0.0
            pos.pop("ladder_placed_for",None)   # V 변경 → 옛 사다리 무효, 이번 실행에서 자동 재게시
            return pos,(f"✅ 추가납입 확정: {sh:.4f}주 매수(@{px:,.2f}) + Pool {rest:,.0f} 추가\n"
                        f"   새 V = {pos['V']:,.0f} · 예약 소진 완료\n"
                        f"   ↻ 옛 사다리 무효 → 새 밴드로 재게시됩니다.")
        if cmd=="/setpos":
            if len(t)<6:
                return pos,("⚠️ 형식: <code>/setpos 주수 현금 V 사이클시작일 상태</code>\n"
                            "   예) <code>/setpos 86 1661.69 0 2026-07-05 INVESTED</code>")
            st_in=t[5].upper()
            if st_in not in ("INVESTED","CASH"):
                return pos,(f"⚠️ 상태는 <b>INVESTED</b> 또는 <b>CASH</b>만 됩니다 (입력: {html.escape(t[5])})")
            try:
                _d=pd.Timestamp(t[4])
                if pd.isna(_d): raise ValueError
                # ★F2(2026-07-23): 과거 날짜를 그대로 넣으면 _cycle_rollover가 k=(오늘-시작)//14 만큼
                #   즉시 롤오버해 V가 Pool/G×k 이중계상된다(/setpos의 V는 '현재값'이므로).
                #   격주 위상(14일 그리드)을 유지한 채 '오늘 이전의 가장 최근 사이클 시작'으로 당겨 k=0으로 만든다.
                _norm=_d; _shift=0
                _tdy=_wall_today().normalize()
                if _d.normalize()<_tdy:
                    _shift=(_tdy-_d.normalize()).days//14
                    if _shift>0: _norm=_d.normalize()+pd.Timedelta(days=14*_shift)
                dstr=_norm.strftime("%Y-%m-%d")
            except Exception:
                return pos,(f"⚠️ 날짜 형식 오류: {html.escape(t[4])}\n"
                            "   YYYY-MM-DD로 넣으세요. 예) 2026-07-05")
            try:
                pos["shares"]=float(t[1]); pos["pool"]=float(t[2]); pos["V"]=float(t[3])
            except Exception:
                return pos,"⚠️ 주수·현금·V는 숫자로 넣으세요. 예) /setpos 86 1661.69 0 2026-07-05 INVESTED"
            pos["last_cycle_start"]=dstr; pos["state"]=st_in
            pos["last_recover_check"]=dstr
            pos["pending_deposit"]=0.0; pos["pending_lump"]=0.0
            for _k in ("pending_lump_mode","evac_sig_date","ladder_placed_for","pending_echo",
                       "evac_pending","recover_pending","recover_retry","evac_recancel","rsv_ladder_for"):
                # ★F4-② + 어댑터 플래그(2026-07-24): 원장 재설정이므로 옛 상태 승계 금지.
                #   특히 evac_pending이 남으면 daily_run이 "신호 무관 전량매도 재시도"를 새 원장에 발화한다(실측).
                #   ※ fills_seen은 절대 지우지 않는다 — 지우면 5일 조회창의 기체결이 재적용돼 이중반영.
                pos.pop(_k,None)
            if pos["V"]<=0:
                if pos["state"]=="INVESTED" and pos["shares"]>0: pos["V"]=pos["shares"]*price_hint
                elif pos["state"]=="CASH" and pos["pool"]>0: pos["V"]=pos["pool"]
            pos["cyc_scale"]=None if ON(VOLTGT_ON) else 1.0
            pos["cyc_budget"]=max(0.0,pos["pool"])*BUY_LIMIT; pos["cyc_used"]=0.0
            pos.pop("ladder_placed_for",None)
            _warn=""
            if pos["state"]=="INVESTED" and pos["shares"]>0 and price_hint and price_hint>0:
                _evlu = pos["shares"]*price_hint
                if pos["V"]>0 and _evlu>0:
                    _diff = abs(pos["V"]-_evlu)/_evlu
                    if _diff >= 0.25:
                        _warn=(f"\n\n⚠️ <b>V 확인 필요</b> — 입력한 V={pos['V']:,.0f} 인데 "
                               f"현재 평가금은 {_evlu:,.0f}({pos['shares']:.0f}주×{price_hint:,.2f}) 입니다.\n"
                               f"   {_diff*100:.0f}% 차이 — 의도한 값이 맞나요?\n"
                               f"   보통 V는 '보유주수×현재가'≈{_evlu:,.0f} 로 넣습니다.\n"
                               f"   (V가 크게 어긋나면 사다리 지정가가 튀어 오주문 위험)")
            return pos,(f"포지션 세팅: {html.escape(t[1])}주 Pool{html.escape(t[2])} "
                        f"V{pos['V']:,.0f} {dstr} {st_in} (예약 초기화){_warn}")
        if cmd=="/setcycle":
            if len(t)<2:
                return pos,("⚠️ 형식: <code>/setcycle YYYY-MM-DD</code>\n"
                            "   예) 오늘부터 사이클 다시 시작 → <code>/setcycle 2026-07-20</code>\n"
                            "   (사다리 지정가 목록이 이 날짜에 다시 나옵니다)")
            try:
                _d=pd.Timestamp(t[1])
                if pd.isna(_d): raise ValueError
                # ★F1(2026-07-23): /setpos와 동일 정규화. 과거일을 그대로 저장하면 직후
                #   _cycle_rollover가 k=(오늘-시작)//14 회 롤오버해 V가 Pool/G×k 부풀려진다.
                #   장기 중단 후 밀린 롤오버는 last_cycle_start가 파일에 남아 자동 처리되므로
                #   /setcycle에 소급 롤오버를 남길 이유가 없다. 14일 위상은 보존.
                _tdy=_wall_today().normalize()
                if _d.normalize()<_tdy:
                    _sf=(_tdy-_d.normalize()).days//14
                    if _sf>0: _d=_d.normalize()+pd.Timedelta(days=14*_sf)
                dstr=_d.strftime("%Y-%m-%d")
            except Exception:
                return pos,(f"⚠️ 날짜 형식 오류: {html.escape(t[1])}\n"
                            "   YYYY-MM-DD로 넣으세요. 예) 2026-07-20")
            pos["last_cycle_start"]=dstr
            pos["cyc_budget"]=max(0.0,pos.get("pool",0.0))*BUY_LIMIT; pos["cyc_used"]=0.0
            pos.pop("ladder_placed_for",None)
            return pos,(f"✅ 사이클 시작일 재설정: <b>{dstr}</b>\n"
                        f"   이 날짜부터 격주(14일) 사이클. 사다리 지정가 목록이 이날 다시 나옵니다.\n"
                        f"   (포지션·V·Pool은 그대로 유지)")
        if cmd=="/ladder":
            sh=pos.get("shares",0.0); V=pos.get("V",0.0); pl=pos.get("pool",0.0)
            st=pos.get("state","INVESTED")
            if st!="INVESTED":
                return pos,"ℹ️ 대피(CASH) 상태에선 사다리가 없습니다. 복귀 후 확인하세요."
            if sh<=0 or V<=0:
                return pos,"⚠️ 보유 주수·V가 있어야 사다리를 계산합니다. /setpos 또는 /setv 확인."
            Veff = V * (float(pos.get("cyc_scale") or 1.0) if ON(VOLTGT_ON) else 1.0)
            _bud=None
            if pos.get("cyc_budget") is not None:
                _bud=max(0.0, float(pos["cyc_budget"])-float(pos.get("cyc_used",0.0)))
            buy,sell,blot,slot=compute_ladder(sh, Veff, pl, budget_override=_bud, cur_px=_px(price_hint))
            lot=blot
            if lot==-1:
                return pos,(f"⚠️ 사다리 생성 거부 — V={V:,.0f}가 현재 평가금과 크게 어긋납니다.\n"
                            f"   (V÷보유 {V/max(sh,1):,.1f} vs 현재가 {_px(price_hint):,.2f} — 2.5배↑ 괴리)\n"
                            f"   → /setpos 로 V를 '보유주수×현재가'({sh*_px(price_hint):,.0f})에 맞게 재설정하세요.")
            if lot==-2:
                return pos,(f"⚠️ 사다리 생성 거부 — 매수한도가 V를 초과합니다 (Pool 과대).\n"
                            f"   (한도 {(_bud if pos.get('cyc_budget') is not None else pl*BUY_LIMIT):,.0f} > V {V:,.0f} — 현금 자릿수 오타 의심)\n"
                            f"   → /setpos 로 Pool(현금)을 다시 확인하세요.")
            _bu = "1주씩" if blot==1 else f"{blot}주씩(묶음)"
            _su = "1주씩" if slot==1 else f"{slot}주씩(묶음)"
            L=[f"📋 <b>사다리 지정가 목록</b> (책 방식)",
               f"  V={V:,.0f}"+(f" · Veff={Veff:,.0f}(노출{pos.get('cyc_scale',1.0):.0%})" if abs(Veff-V)>1 else "")
               +f" · 밴드 {Veff*BAND_LOW:,.0f}~{Veff*BAND_HIGH:,.0f} · 보유 {sh:.0f}주 · Pool {pl:,.0f}"]
            if blot>1 or slot>1:
                L.append(f"  ⚙️ 묶음 매매: 매수 <b>{blot}주씩</b> · 매도 <b>{slot}주씩</b> (책 136p: 큰 금액이면 여러 주씩)")
            if buy:
                L.append(f"  🟩 <b>예약매수</b> (저가 닿으면 {_bu}, 매수한도 내):")
                for pt,s2,p2 in buy: L.append(f"     @ {pt:,.2f} → 체결 후 {s2}주 보유")
            else:
                L.append("  🟩 예약매수: 없음 (매수한도 소진/Pool 부족)")
            if sell:
                L.append(f"  🟥 <b>예약매도</b> (고가 닿으면 {_su}, 무제한):")
                for pt,s2,p2 in sell: L.append(f"     @ {pt:,.2f} → 체결 후 {s2}주 보유")
            L.append("  ※ 참고용. 체결은 자동 동기화됩니다(보고 불필요)." if AUTO_MODE_HINT
                     else "  ※ 참고용. 체결되면 실제 주수·가격으로 /buy·/sell 보내세요.")
            return pos,"\n".join(L)
        if cmd=="/setv":
            px=_px(None)
            if px is None or px<=0:
                return pos,("⚠️ 가격을 넣어주세요: <code>/setv @종가</code>\n"
                            "   예) 종가 75.27이면 <code>/setv @75.27</code>")
            sh=pos.get("shares",0.0)
            if sh<=0:
                return pos,"⚠️ 보유 주수가 0이라 V를 계산할 수 없습니다. 먼저 /setpos 로 보유를 입력하세요."
            pos["V"]=sh*px
            pos.pop("ladder_placed_for",None)   # V 변경 → 옛 사다리 무효, 이번 실행에서 자동 재게시
            return pos,(f"✅ V 갱신: {sh:.4f}주 × {px:,.2f} = <b>V {pos['V']:,.2f}</b>\n"
                        f"   밴드: 하한 {pos['V']*BAND_LOW:,.0f} ~ 상한 {pos['V']*BAND_HIGH:,.0f}\n"
                        f"   ↻ 옛 사다리 무효 → 새 밴드로 재게시됩니다.")
        if cmd=="/lumpsum":
            if len(t)<2:
                return pos,("⚠️ 형식: <code>/lumpsum +금액 v</code> 또는 <code>/lumpsum +금액 pool</code>\n"
                            "   · <b>v</b> = 목돈 공식 (V 재설정 + 비율대로 즉시 매수)\n"
                            "   · <b>pool</b> = Pool만 보충 (V 그대로, 다음 사이클부터 V+Pool/G로 반영)\n"
                            "   예) <code>/lumpsum +10000 v</code> · <code>/lumpsum -5000 pool</code>")
            try: amt=float(t[1].replace(",",""))
            except Exception:
                return pos,"⚠️ 금액을 숫자로 넣으세요. 예) <code>/lumpsum +10000 v</code>"
            if amt==0: return pos,"⚠️ 금액이 0입니다."
            _mode=(t[2].lower() if len(t)>2 else ""); _prev_lump=float(pos.get("pending_lump",0.0) or 0.0)
            if _mode not in ("v","pool"):
                return pos,(f"❓ <b>{amt:+,.0f} USD</b> — 처리 방식을 지정하세요.\n"
                            f"   ① <code>/lumpsum {amt:+.0f} v</code> — <b>목돈 공식</b>\n"
                            f"      V를 재설정하고 현재 비중대로 즉시 매수/매도합니다(자산 규모 자체가 바뀜).\n"
                            f"   ② <code>/lumpsum {amt:+.0f} pool</code> — <b>Pool 보충</b>\n"
                            f"      Pool만 조절하고 V는 그대로. 다음 사이클부터 V+Pool/G로 천천히 반영됩니다.")
            pr=price_hint
            ev=pos.get("shares",0.0)*pr; pool=pos.get("pool",0.0); total=ev+pool
            w=0.0 if pos.get("state")=="CASH" else (ev/total if total>0 else 1.0)   # ★수정(2026-07): CASH(대피)는 주식비중0=전액Pool. 총자산0서 w=1.0(전액TQQQ) 되던 모순 방지
            # ★B안(2026-07-23): pool 모드는 주문이 없으므로 예약·확정 2단계를 없애고 즉시 확정.
            #   (구조상 /lumpsum_done을 거치지 않으므로 "pool인데 V가 바뀌는" 버그가 원천 차단됨)
            if _mode=="pool":
                _newpool=pool+amt
                if _newpool<0:
                    return pos,(f"⚠️ Pool 부족 — 현재 Pool {pool:,.0f}에서 {abs(amt):,.0f} 인출 불가.\n"
                                f"   주식을 함께 줄이려면 <code>/lumpsum {amt:+.0f} v</code>(목돈 공식)를 쓰세요.")
                _act = "추가" if amt>0 else "인출"
                pos["pool"]=0.0 if abs(_newpool)<1e-9 else _newpool
                _drop=""
                if _prev_lump:   # ★A3(2026-07-23): pool 즉시확정이 기존 v 예약을 무경고 삭제하던 것 → 고지
                    _drop=f"   ⚠️ 대기 중이던 목돈 예약 {_prev_lump:+,.0f}(v)는 <b>취소</b>되었습니다.\n"
                pos.pop("pending_lump",None); pos.pop("pending_lump_mode",None)
                if amt<0 and pos.get("cyc_budget") is not None:   # 인출 시 남은 매수한도만 새 Pool×50%로 클램프
                    _rem=max(0.0,float(pos["cyc_budget"])-float(pos.get("cyc_used",0.0)))
                    _cap=max(0.0,pos["pool"])*BUY_LIMIT
                    if _rem>_cap:
                        pos["cyc_budget"]=float(pos.get("cyc_used",0.0))+_cap
                        pos.pop("ladder_placed_for",None)          # 매수단 축소 → 사다리 재게시
                # ★②(2026-07-24): 중간 저장 제거 → 배치말 일괄 저장으로 통일.
                #   여기서 저장하면 offset 확정 전에 프로세스가 죽을 때 같은 update가 재수신돼
                #   pool 조정이 두 번 반영된다(이중반영 창). 배치말 저장이면 유실로 축소된다.
                return pos,(_drop+f"✅ <b>Pool {_act} {abs(amt):,.0f} USD 반영</b> (V 변경 없음)\n"
                            f"   Pool {pool:,.0f} → <b>{pos['pool']:,.0f}</b>\n"
                            f"   · V={pos.get('V',0):,.0f} 그대로. 다음 사이클부터 V+Pool/G로 반영됩니다.\n"
                            f"   · 확정 완료 — 별도 명령 불필요합니다.")
            # ── v 모드(목돈 공식): 주문이 필요하므로 예약 → 러너 자동집행 또는 /lumpsum_done ──
            if amt<0 and total>0 and (-amt)>=total:                # ★F3: 총자산 이상 인출은 예약 단계에서 거부
                return pos,(f"⚠️ 인출 {abs(amt):,.0f} ≥ 총자산 {total:,.0f} — 불가합니다.\n"
                            f"   전액 청산이 목적이면 <code>/exit @가격</code>을 쓰세요.")
            pos["pending_lump"]=amt; pos["pending_lump_mode"]=_mode
            _prev_note=""
            if _prev_lump:   # ★F4-⑤: 무경고 덮어쓰기 방지 — 대체 사실을 명시(deposit은 누적이라 비대칭이었음)
                _prev_note=f"   ⚠️ 이전 예약 {_prev_lump:+,.0f}는 <b>대체</b>되었습니다(누적 아님).\n"
            if amt>0:
                d_tqqq=amt*w; d_pool=amt*(1-w); _sh=round(d_tqqq/pr)
                return pos,(_prev_note+f"💵 <b>목돈 추가 {amt:,.0f} USD 예약</b> (현재 비중 주식{w:.0%}:현금{1-w:.0%})\n"
                            f"   ① TQQQ에 <b>약 {d_tqqq:,.0f} USD어치</b> 매수 (실제 체결가로 주수 결정)\n"
                            f"      · 참고: 어제 종가 {pr:,.2f} 기준 ≈ {_sh}주\n"
                            f"   ② 나머지(약 {d_pool:,.0f})는 Pool로\n"
                            f"   ③ V 재설정: {pos.get('V',0):,.0f} → <b>약 {pos.get('V',0)*(1+amt/total) if total>0 else 0:,.0f}</b>\n"
                            + ("   → 러너가 다음 실행(장중)에 자동 집행합니다."
                               if AUTO_MODE_HINT else
                               "   실제 매수 후 → <code>/lumpsum_done 실제주수 @실제체결가</code>"))
            else:
                need=abs(amt); s_tqqq=need*w; s_pool=need*(1-w); _sh=round(s_tqqq/pr)
                return pos,(_prev_note+f"💸 <b>목돈 인출 {need:,.0f} USD 예약</b> (현재 비중 주식{w:.0%}:현금{1-w:.0%})\n"
                            f"   ① TQQQ <b>약 {s_tqqq:,.0f} USD어치</b> 매도 (실제 체결가로 주수 결정)\n"
                            f"      · 참고: 어제 종가 {pr:,.2f} 기준 ≈ {_sh}주\n"
                            f"   ② Pool에서 약 {s_pool:,.0f} 인출\n"
                            f"   ③ V 재설정: {pos.get('V',0):,.0f} → <b>약 {pos.get('V',0)*(1+amt/total) if total>0 else 0:,.0f}</b>\n"
                            + ("   → 러너가 다음 실행(장중)에 자동 집행합니다."
                               if AUTO_MODE_HINT else
                               "   실제 매도 후 → <code>/lumpsum_done -실제주수 @실제체결가</code> (인출은 −)"))
        if cmd=="/lumpsum_done":
            lump=pos.get("pending_lump",0.0)
            if lump==0:
                return pos,"⚠️ 예약된 목돈이 없습니다. 먼저 <code>/lumpsum +금액</code> 또는 <code>-금액</code>으로 예약하세요."
            try: sh=float(t[1])
            except Exception:
                return pos,"⚠️ 주수를 넣으세요. 추가=양수, 인출=음수. 예) <code>/lumpsum_done 112 @80</code>"
            px=_px(price_hint)
            # ★B안 방어(2026-07-23): pool 모드는 /lumpsum 단계에서 즉시 확정된다. 구버전 상태파일에
            #   pool 예약이 남아 여기 오면 V가 바뀌는 사고(F1)가 나므로 차단하고 그 자리서 안전 처리.
            if str(pos.get("pending_lump_mode","v")).lower()=="pool":
                _np=pos.get("pool",0.0)+lump
                if _np<0:
                    return pos,f"⚠️ Pool 부족({_np:,.0f}) — 금액을 확인하세요."
                pos["pool"]=0.0 if abs(_np)<1e-9 else _np
                pos["pending_lump"]=0.0; pos.pop("pending_lump_mode",None)
                # ★②(2026-07-24): 중간 저장 제거 — 배치말 일괄 저장으로 통일(이중반영 창 차단)
                return pos,(f"✅ Pool {'추가' if lump>0 else '인출'} 확정 {abs(lump):,.0f} → Pool {pos['pool']:,.0f}\n"
                            f"   V={pos.get('V',0):,.0f} 그대로 (pool 모드는 주식 매매·V 변경 없음)")
            V=pos.get("V",0.0); pool=pos.get("pool",0.0); shares=pos.get("shares",0.0)
            if pos.get("state")=="CASH" and abs(sh)>1e-9:   # ★수정(2026-07): CASH(대피)는 전액Pool 조정 → 주식매매 불가(모순 방지)
                return pos,"⚠️ CASH(대피) 상태에선 주식 매매 없이 Pool만 조정됩니다. <code>/lumpsum_done 0</code> 으로 확정하세요."
            if lump>0 and sh<0:
                return pos,(f"⚠️ 목돈 <b>추가</b> 예약인데 매도(음수 {sh})가 들어왔습니다.\n"
                            f"   추가 확정은 양수 주수로: <code>/lumpsum_done {abs(sh):.2f} @{px:,.2f}</code>")
            if lump<0 and sh>0:
                return pos,(f"⚠️ 목돈 <b>인출</b> 예약인데 매수(양수 {sh})가 들어왔습니다.\n"
                            f"   인출 확정은 음수 주수로: <code>/lumpsum_done -{sh:.2f} @{px:,.2f}</code>")
            if sh<0 and abs(sh) > shares + 1e-6:
                return pos,(f"⚠️ 매도 {abs(sh):.4f}주인데 보유는 {shares:.4f}주뿐입니다.\n"
                            f"   보유 내에서 매도하세요.")
            ev_before=shares*px
            # ★F5(2026-07-23): 확정단 재검사. 예약단 F3 가드는 '예약 시점' 가격 기준이라
            #   확정까지의 하락을 못 막는다(가격 반토막 → 총자산=|인출| → V=0, 미세 음수 창).
            if lump<0 and (ev_before+pool)>1e-9 and (-lump)>=(ev_before+pool):
                return pos,(f"⚠️ 인출 {abs(lump):,.0f} ≥ 확정시점 총자산 {ev_before+pool:,.0f} — 거부합니다.\n"
                            f"   예약 이후 하락한 것으로 보입니다. 전액 청산은 <code>/exit @가격</code>을 쓰세요.")
            traded=sh*px
            new_pool=pool + (lump - traded)
            if new_pool < -1.0:
                return pos,(f"⚠️ 처리 결과 Pool이 {new_pool:,.0f}로 음수가 됩니다.\n"
                            f"   목돈액({lump:+,.0f})과 매매주수({sh:+.2f}주 @{px:,.2f})를 확인하세요.")
            pos["shares"]=shares+sh
            pos["pool"]=new_pool
            if abs(pos["pool"])<1e-6: pos["pool"]=0.0
            prev_total = ev_before + pool
            if prev_total>1e-9:
                pos["V"]=V*(1.0 + lump/prev_total)
                v_basis="V*(1+목돈/직전총자산)"
            else:
                pos["V"]=pos["shares"]*px
                v_basis="현재 평가금(총자산0 새출발)"
            pos["pending_lump"]=0.0; pos.pop("pending_lump_mode",None)
            pos["cyc_budget"]=max(0.0,pos["pool"])*BUY_LIMIT; pos["cyc_used"]=0.0
            pos.pop("ladder_placed_for",None)   # V 변경 → 옛 사다리 무효, 이번 실행에서 자동 재게시
            w=ev_before/(ev_before+pool) if (ev_before+pool)>0 else 1.0
            target_trade=lump*w
            diff=target_trade-traded
            hint=""
            if abs(diff)>max(px, (ev_before+pool)*0.01):
                extra_sh=diff/px
                if extra_sh>0:
                    hint=f"\n   ℹ️ 목표 대비 {abs(extra_sh):.2f}주 <b>더 매수</b>하면 비례배분에 근접(생략 가능)"
                else:
                    hint=f"\n   ℹ️ 목표 대비 {abs(extra_sh):.2f}주 <b>더 매도</b>하면 비례배분에 근접(생략 가능)"
            act="추가" if lump>0 else "인출"
            return pos,(f"✅ 목돈 {act} 확정: 주식 {sh:+.4f}주 @{px:,.2f}, Pool {pos['pool']:,.0f}\n"
                        f"   새 V = {pos['V']:,.0f} ({v_basis})\n"
                        f"   밴드: 하한 {pos['V']*BAND_LOW:,.0f} ~ 상한 {pos['V']*BAND_HIGH:,.0f}{hint}\n"
                        f"   ↻ 옛 사다리 무효 → 새 밴드로 재게시됩니다.")
        if cmd=="/reset":
            if len(t)>1 and t[1].lower()=="yes":
                pos["shares"]=0.0; pos["pool"]=0.0; pos["V"]=0.0
                pos["pending_deposit"]=0.0; pos["state"]="INVESTED"
                pos["pending_lump"]=0.0; pos.pop("pending_lump_mode",None)
                pos["cyc_scale"]=1.0; pos["cyc_budget"]=0.0; pos["cyc_used"]=0.0
                pos["last_cycle_start"] = _wall_today().strftime('%Y-%m-%d')
                for _k in ("ladder_placed_for","evac_sig_date","evac_reason","lump_in_flight","pending_echo",
                           "evac_pending","recover_pending","recover_retry","evac_recancel","rsv_ladder_for"):
                    # ★F6 + 어댑터 플래그(2026-07-24). fills_seen은 보존(이중반영 방지).
                    pos.pop(_k,None)
                pos["last_recover_check"]=pos["last_cycle_start"]
                return pos,("🔄 <b>전체 초기화 완료</b> — 보유·현금·V·기록 모두 삭제.\n"
                            "   새로 시작하려면 /setpos 로 현재 보유를 다시 입력하세요.")
            else:
                return pos,("⚠️ <b>/reset은 모든 기록을 지웁니다.</b>\n"
                            "   정말 초기화하려면 <code>/reset yes</code> 라고 보내세요.\n"
                            "   (실수 방지를 위해 'yes' 확인이 필요합니다)")
        if cmd=="/status":
            st=pos.get("state","INVESTED"); sh=pos.get("shares",0.0)
            pl=pos.get("pool",0.0); vv=pos.get("V",0.0)
            lcs=pos.get("last_cycle_start","-"); pend=pos.get("pending_deposit",0.0)
            msg=(f"📋 <b>현재 포지션</b>\n"
                 f"   상태: {st}\n"
                 f"   보유: {sh:.4f}주\n"
                 f"   현금(Pool): {pl:,.2f} USD\n"
                 f"   V값: {vv:,.2f}\n"
                 f"   사이클 시작: {lcs}")
            if pend>0: msg+=f"\n   예약 추가납입: {pend:,.2f} USD"
            plump=pos.get("pending_lump",0.0)
            if plump!=0:
                _act="추가" if plump>0 else "인출"
                _pm=str(pos.get("pending_lump_mode","v")).lower()   # ★F4-④: 모드까지 표시(v=목돈공식 / pool=Pool만)
                msg+=f"\n   예약 목돈({_act}, 모드 {_pm}): {abs(plump):,.2f} USD"
            return pos,msg
        if cmd=="/help":
            return pos,(
                "📖 <b>명령어 목록</b>\n"
                "━━━━━━━━━━━━━━\n"
                "<b>[상태]</b>\n"
                "/status — 현재 포지션 확인\n"
                "/help — 이 목록 보기\n\n"
                "<b>[밴드 매매]</b>\n"
                "/buy 주수 @가격 — 매수 반영\n"
                "/sell 주수 @가격 — 매도 반영\n\n"
                "<b>[대피/복귀]</b>\n"
                "/exit @가격 — 전량 대피(→CASH)\n"
                "/enter 금액 @가격 — 복귀 재매수(→INVESTED)\n\n"
                "<b>[추가납입]</b>\n"
                "/deposit 금액 — 추가납입 예약\n"
                "/deposit_done 주수 @가격 — 매수 후 확정\n\n"
                "<b>[목돈 추가/인출]</b>\n"
                "/lumpsum +금액 v — 목돈 추가(V 재설정+비율매수)\n"
                "/lumpsum +금액 pool — Pool만 보충(V 불변, 즉시 확정)\n"
                "/lumpsum -금액 v|pool — 인출(같은 방식)\n"
                "/lumpsum_done 주수 @가격 — v 모드 확정(인출은 -주수)\n\n"
                "<b>[사다리 지정가 — 책 방식(본 매매)]</b>\n"
                "/ladder — 지금 지정가 사다리 목록 확인\n"
                "/setcycle YYYY-MM-DD — 사이클 시작일 재설정(사다리 다시 시작)\n\n"
                "<b>[설정]</b>\n"
                "/setpos 주수 현금 V 시작일 상태 — 포지션 등록\n"
                "/setv @종가 — V를 종가 기준으로 보정\n"
                "/reset → /reset yes — 전체 초기화\n"
                "━━━━━━━━━━━━━━\n"
                "※ @가격 생략 시 그날 종가로 자동 처리")
    except Exception as e:
        return pos,f"⚠️ 명령 오류: {html.escape(text)} ({html.escape(str(e))})"
    if cmd.startswith("/"):
        return pos,(f"❓ 알 수 없는 명령: <code>{html.escape(cmd)}</code>\n"
                    "전체 명령은 <code>/help</code> 로 확인하세요.")
    return pos,None

def process_commands(pos, price_hint, Veff_target=None):
    """쌓인 텔레그램 명령을 순서대로 처리. 본인(TG_CHAT_ID)이 보낸 것만.
       ★exactly-once(2026-07-24): offset을 pos["tg_offset"]에 담아 원장과 함께 1회 원자 저장.
         · 저장 전에 죽으면 → 원장·offset 둘 다 미확정 → 다음 실행이 그대로 재처리(정확히 1회)
         · 저장에 성공하면 → 둘 다 확정 → 재수신돼도 아래 '이미 처리한 id' 가드가 스킵
         종전의 (원장파일 + offset파일) 2파일 구조는 어느 순서로 저장해도
         '이중반영' 또는 '유실' 창이 남았다. 단일 파일이면 그 창 자체가 사라진다."""
    ups=_get_updates(pos); results=[]; last_uid=None
    owner=str(TG_CHAT_ID).strip()
    _seen=pos.get("tg_offset")
    try: _seen=int(_seen) if _seen is not None else None
    except Exception: _seen=None
    for u in ups:
        uid=u.get("update_id")
        if _seen is not None and uid is not None and uid<=_seen:
            continue                                   # 이미 처리된 update(서버 재전달) → 스킵
        last_uid=uid
        msg=u.get("message") or u.get("channel_post")
        if not msg: continue
        sender=str((msg.get("chat") or {}).get("id",""))
        if owner and sender!=owner:
            print(f"[보안] 미인가 발신자 무시: chat_id={sender}")
            continue
        text=msg.get("text","")
        if not text.startswith("/"): continue
        _mt=int(msg.get("date",0) or 0)
        if _mt and (time.time()-_mt) > STALE_CMD_HOURS*3600:
            _age_h=(time.time()-_mt)/3600
            print(f"[낡은 명령 무시] {text[:30]} ({_age_h:.1f}시간 전)")
            results.append(f"⏱️ <b>낡은 명령 폐기</b>: <code>{html.escape(text[:40])}</code> "
                           f"({_age_h:.1f}시간 전 발송, 임계 {STALE_CMD_HOURS}h 초과)\n"
                           f"      → 미반영. 필요하면 <b>지금 다시 보내세요</b>.")
            continue
        pos,res=apply_command(pos, text, price_hint, Veff_target)
        if res: results.append(res)
    if last_uid is not None:
        pos["tg_offset"]=last_uid          # 원장과 함께 저장 → 원자적으로 동시 확정
        # ★pending_echo(2026-07-24): 원자 저장 성공 후 '발송 전' 사망 시 유실되는 통지를 보존한다.
        #   원장은 exactly-once로 이미 안전하고, 이건 통지만 다음 리포트에 재전송하기 위한 것.
        #   저장은 아래 1회뿐 — tg_offset과 반드시 동시 확정되어야 하므로 별도 save 금지.
        _echo=pos.get("pending_echo") or []
        _cut=_wall_today()-pd.Timedelta(days=7)
        _kept=[]
        for _e in _echo:                    # ① 프루닝: 7일 초과·파싱불가 폐기
            try:
                if pd.Timestamp(str(_e.get("ts",""))[:10]) >= _cut: _kept.append(_e)
            except Exception:
                pass
        _echo=_kept[-10:]                   #    최신 10개까지만 유지
        if results:                         # ② append (프루닝 뒤)
            _echo.append({"ts": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
                          "lines": list(results)})
        pos["pending_echo"]=_echo
        save_position(pos)                 # save_position은 tmp+os.replace(원자)
    return pos, results

def compute_ladder(shares, V, pool, max_rows=None, sell_reach=1.50, budget_override=None, cur_px=None):
    """책(라오어 VR) 예약매수/매도 사다리 — 책 로직 그대로.
       [책 그리드] 1주 칸: 매수점(n→n+1)=최소밴드/n, 매도점(n→n−1)=최대밴드/n.
       [2번 — 매수한도 '근처'] 누적비용이 한도(BUY_LIMIT×Pool)에 '가장 가까워지는' 칸까지 시도.
         한도를 한 칸 넘겨도 그쪽이 더 가까우면 포함. 책 5개 예시 전수 재현
         (127p·129p·131p·133p·137p).
       [5번 — 묶음(책 136p)] 1주 그리드를 유지한 채 lot칸씩 묶어 그 그룹의 '마지막 칸' 가격에
         lot주 배치(체결 후 보유수가 1주 사다리와 동일 지점에서 일치. '첫 칸 배치'의 조기체결
         편향 교정). 기본 lot=1(책 예시 동일). 칸수가 HARD를 넘는 큰 계좌만 자동 묶음.
       [안전장치(책 외, 유지 확정)] HARD=60 · sell_reach(+50% 실효상한) · V괴리 거부(lot=-1).
       반환: (buy[(지정가,체결후보유,남은Pool)], sell[...], lot)."""
    if shares<=0 or V<=0:
        return [], [], 1, 1
    bmin=V*BAND_LOW; bmax=V*BAND_HIGH
    budget = budget_override if budget_override is not None else max(0.0,pool)*BUY_LIMIT
    budget = max(0.0, budget)
    start_px=V/shares

    HARD=60
    if cur_px and cur_px > 0:
        ratio = start_px / cur_px
        if ratio > 2.5 or ratio < 0.4:
            return [], [], -1, -1
    if budget > V:                     # 매수한도가 V 초과 = Pool 과대(현금 자릿수 오타 등) → lot 폭주 방지
        return [], [], -2, -2

    # [5번] lot: 기본 1주(책 예시). 필요 칸수가 HARD를 넘을 때만 묶음(책 136p '큰 금액이면 여러 개씩').
    #   ★교정(2026-07-24): 매수·매도 lot을 분리. 종전엔 공용 lot=max(buy,sell)이라 매도가 굵으면
    #   매수까지 굵어졌다(1301주: 매수 필요 lot 2인데 매도 때문에 6 → 11칸으로 뭉침).
    #   책의 이상은 1주 그리드이고 묶음은 '손으로 걸기 힘들 때'의 편의책인데, 봇은 그 제약이 없다.
    #   → 각 방향이 HARD 안에 들어가는 최소 lot을 쓰면 책 그리드에 가장 근접한다.
    #   ※ 종전 주석의 "책 5개 예시 전수 재현"은 사실이 아니었다. 공용 lot은 258주부터 켜져
    #     137p(300주)·141p(315주)·143p 등 거치식 예시를 재현하지 못했다. 분리 후에도
    #     보유가 커지면 묶음은 불가피하며(책 136p가 허용), 재현되는 건 lot=1 구간뿐이다.
    est_sell_rungs = shares * max(0.0, 1.0 - BAND_HIGH/sell_reach)
    # est_buy: 조화합 closed form. 매수점=bmin/s(s에 반비례)를 적분한 정확한 rung수.
    #   (시작가 선형추정 budget/start_px는 깊은 rung 저가 미반영 → 대량현금 구간 최심부 누락)
    est_buy_rungs  = shares*(np.exp(min(budget/(V*BAND_LOW), 20.0))-1.0)
    buy_lot  = max(1, int(np.ceil(est_buy_rungs /HARD)))
    sell_lot = max(1, int(np.ceil(est_sell_rungs/HARD)))
    # ★①(2026-07-24) 절단 방지: est_buy_rungs는 1주 사다리 기준 연속근사인데, 묶음은 그룹비용이
    #   '마지막 칸 가격×lot'이라 1주 합보다 싸서 같은 예산으로 더 깊이 내려간다. 여기에 nearest가
    #   마지막 1그룹을 더하면 그룹수가 HARD를 1 넘겨 최심부(가장 싼) 매수가 조용히 잘린다.
    #   실측: Pool/V≈1.99에서 61그룹이 정답인데 60그룹만 게시(@26.03 누락). est를 믿지 말고 실제로 센다.
    def _count_buy(lot):
        s=shares; used=0.0; n=0
        while n <= HARD:                      # HARD+1까지만 세면 초과 여부 판정에 충분
            pt=bmin/(s+lot-1); cost=pt*lot; room=budget-used
            if pool < cost - 1e-9: break
            if cost <= room + 1e-9: used+=cost; s+=lot; n+=1
            else:
                if (cost-room) <= room: n+=1
                break
        return n
    for _ in range(8):                        # 안전 한계(무한루프 방지)
        _n=_count_buy(buy_lot)
        if _n <= HARD: break
        # ★비례 점프(2026-07-24): +1씩 올리면 대형 계좌(lot 수백)에서 8회로 안 줄어든다.
        #   필요 배율만큼 한 번에 올려 규모와 무관하게 2회 내 수렴시킨다.
        buy_lot = max(buy_lot+1, int(np.ceil(buy_lot*_n/HARD)))

    cap_buy = max_rows if max_rows else HARD
    cap_sell= max_rows if max_rows else HARD

    # ── 매수: 그룹 '마지막 칸' 가격 · 한도 '근처'까지(책) ──
    buy=[]; s=shares; p=pool; used=0.0
    for _ in range(cap_buy):
        buypt = bmin/(s + buy_lot - 1)
        cost  = buypt*buy_lot
        if p < cost - 1e-9: break
        room  = budget - used
        if cost <= room + 1e-9:
            s+=buy_lot; p-=cost; used+=cost; buy.append((buypt,int(s),p))
        else:
            if (cost - room) <= room:
                s+=buy_lot; p-=cost; used+=cost; buy.append((buypt,int(s),p))
            break
    # ── 매도: 그룹 '마지막 칸' 가격 · 무제한(실효상한 sell_reach — 유지 확정) ──
    sell=[]; s=shares; p=pool
    sell_limit=start_px*sell_reach
    for _ in range(cap_sell):
        if s < sell_lot: break
        sellpt = bmax/(s - sell_lot + 1)
        if max_rows is None and sellpt > sell_limit: break
        p+=sellpt*sell_lot; s-=sell_lot; sell.append((sellpt,int(s),p))
    return buy, sell, buy_lot, sell_lot

def _drop_live_bar(df):
    """판정용: '완성된 전일 종가'만 쓰도록 미완성 당일봉을 제거.
       실행 시각이 미국 장중이면 df.iloc[-1]이 오늘 미완성봉이라 SMA200/버블/백분위/밴드/평가금이
       그 장중가로 오염됨(23:40 KST 실행 = 10:40 ET 장중). 마지막 봉이 '오늘(ET) 거래일'이고
       종가(16:00 ET) 전이면 제거 → 마지막이 완성된 직전 거래일 종가.
       ※ [8번 수정] main에서 전 계산(킬스위치·밴드·평가금·가격힌트·사다리)에 일괄 적용."""
    try:
        if len(df) < 2:
            return df
        last = df.index[-1]
        now_et = pd.Timestamp.now(tz="America/New_York")
        if last.date() != now_et.date():
            return df
        try:
            import pandas_market_calendars as mcal
            sched = mcal.get_calendar("XNYS").schedule(
                start_date=now_et.date().isoformat(), end_date=now_et.date().isoformat())
            if sched.empty:
                return df
            close_et = pd.Timestamp(sched.iloc[0]["market_close"]).tz_convert("America/New_York")
        except Exception:
            close_et = now_et.normalize() + pd.Timedelta(hours=16)
        if now_et < close_et:
            return df.iloc[:-1]
        return df
    except Exception as e:
        print(f"[live bar drop 스킵] {e}")
        return df

def compute_signal(df, pos):
    # [8번] df는 main에서 _drop_live_bar 적용된 '완성 종가' 단일 뷰.
    #   킬스위치·밴드·평가금·사다리 전부 동일 기준(책: 직전 거래일 종가로 V·밴드 확정).
    #   사이클 경계만 wall clock(_wall_today).
    today=df.index[-1]; row=df.iloc[-1]
    g=float(row["GSPC"]); gs=float(row["GSMA"])
    ndx=float(row["NDX"]); nsm=float(row["NSMA"]); bub=float(row["BUB"])
    pc=row["BUB_PCTL"]
    p=float(row["TQQQ"]); rv=row["RV"]
    pr=float(row["TQQQ_REAL"]) if ("TQQQ_REAL" in df.columns and not pd.isna(row["TQQQ_REAL"])) else p

    state=pos.get("state","INVESTED")
    shares=pos.get("shares",0.0); pool=pos.get("pool",0.0)
    ev=shares*pr
    total=ev+pool
    posV=pos.get("V",0.0)
    V = posV if posV>0 else ev
    pending_dep=pos.get("pending_deposit",0.0)

    # 사이클(달력 KST 기준)
    wall_today=_wall_today()
    cyc_start, cyc_next = current_cycle(pos.get("last_cycle_start",LAST_CYCLE_START))

    # 월말 판정: 판정일(today=마지막 완성 종가일) 기준 NYSE 실제 거래일
    try:
        import pandas_market_calendars as mcal
        _nyse=mcal.get_calendar("XNYS")
        _vd=_nyse.valid_days(today.strftime("%Y-%m-%d"),
                             (today+pd.Timedelta(days=10)).strftime("%Y-%m-%d"))
        _future=[d.tz_localize(None) for d in _vd if d.tz_localize(None)>today]
        nb=_future[0] if _future else today+pd.tseries.offsets.BDay(1)
        _this_month_left=[today]+[d for d in _future if d.month==today.month]
        near_month_end=(len(_this_month_left)<=3)
    except Exception:
        nb=today+pd.tseries.offsets.BDay(1)
        near_month_end=False
    is_month_end=(nb.month!=today.month)
    next_trading_day=nb.date()

    # ── 복귀 소급 판정(월말 누락 방지) — 완성 종가 뷰(df) 기준 ──
    me_row=None; me_date=None
    def _recover_ok_at(rrow):
        _g=float(rrow["GSPC"]); _gs=float(rrow["GSMA"]); _b=float(rrow["BUB"])
        _nx=float(rrow["NDX"]); _ns=float(rrow["NSMA"]); _spx=_g>_gs
        allow_fast = ON(FAST_RECOVER)   # ★복귀정책 B(2026-07): B1대피 시에도 NDX 빠른복귀 허용. 백테스트 실데이터 5구간 전부 CAGR +3.5~7%p·MDD동일. (구: and evac_reason!="b1" = B1대피 시 NDX차단)
        return (_spx or (allow_fast and _nx>_ns)) if _b<BUBBLE_LIMIT else _spx
    if state=="CASH":
        try:
            _mems=df.index.to_series().groupby([df.index.year, df.index.month]).max()
            months=[pd.Timestamp(d) for d in _mems.values]
            last_checked=pos.get("last_recover_check","") or pos.get("last_cycle_start","")
            past_me=[d for d in months
                     if d<today and (d.year,d.month)!=(today.year,today.month)
                     and str(d.date())>str(last_checked)]
            if is_month_end and str(today.date())>str(last_checked):
                past_me.append(today)
            past_me=sorted(set(past_me))
            if past_me:
                me_date=past_me[-1]
                for d in past_me:
                    if _recover_ok_at(df.loc[d]):
                        me_date=d; break
                me_row=df.loc[me_date]
        except Exception as _e:
            print(f"[복귀 소급판정 스킵] {_e}")
            me_row=None; me_date=None

    # VOLTGT 노출 (off 확정 상태 — 로직은 백테스터 정합 위해 보존)
    if ON(VOLTGT_ON) and "cyc_scale" in pos and pos.get("cyc_scale") is not None:
        scale=float(pos["cyc_scale"]); Veff=V*scale
    elif ON(VOLTGT_ON) and not pd.isna(rv) and rv>0:
        scale=min(1.0, VOLTGT_TARGET/float(rv)); Veff=V*scale
    else:
        scale=1.0; Veff=V

    # ── 킬스위치 (대피=매일 종가판정→다음날, 복귀=월말 종가→다음 거래일) ──
    ks_msg=[]; action_ks=None
    below=g<gs
    hi_pctl = (float(pc)>=B1_PCTL) if not pd.isna(pc) else False
    if ON(KILLSWITCH):
        if state=="INVESTED":
            exit_now=False; why=""
            if below:
                if bub>=BUBBLE_LIMIT: exit_now=True; why="버블≥1.30 AND S&P 200일선 하회"; pos["evac_reason"]="bubble"
                elif ON(B1_ON) and hi_pctl: exit_now=True; why=f"버블백분위≥{B1_PCTL:.0%} AND S&P 200일선 하회"; pos["evac_reason"]="b1"
            if exit_now:
                action_ks="🔴 대피"
                pos["evac_sig_date"]=str(today.date())   # ★소급복귀용(2026-07): 대피 판정일 저장 → /exit가 '보고일' 아닌 이 날짜로 last_recover_check 스탬프
                ks_msg.append(f"🔴 <b>대피 신호</b> ({why})")
                ks_msg.append(f"   → <b>{today.date()} 종가로 확정</b>. <b>다음 거래일({next_trading_day}) 개장가(MOO)로 TQQQ 전량 매도</b>")
                ks_msg.append(f"   ⚠️ <b>걸어둔 예약매수·매도 지정가를 먼저 전량 취소</b>하세요 (남아 있으면 대피 중 재체결).")
            else:
                ks_msg.append(f"🟢 보유 유지 (대피 조건 미충족)")
        else:
            if me_row is not None:
                mg=float(me_row["GSPC"]); mgs=float(me_row["GSMA"])
                mbub=float(me_row["BUB"]); mndx=float(me_row["NDX"]); mnsm=float(me_row["NSMA"])
                spx_ok=mg>mgs
                is_retro=(me_date is not None and me_date.date()!=today.date())
                retro_tag=f" ⟨{me_date.date()} 월말 소급판정⟩" if is_retro else ""
                if mbub<BUBBLE_LIMIT:
                    ok = spx_ok or (ON(FAST_RECOVER) and mndx>mnsm)   # ★복귀정책 B: evac_reason 차단 제거(위 795와 동일 근거)
                    if ok:
                        who="S&P" if spx_ok else "NDX(빠른복귀)"
                        action_ks="🔵 복귀"
                        ks_msg.append(f"🔵 <b>복귀 신호</b> ({who} 200일선 상향, 월말 종가 판정){retro_tag}")
                        ks_msg.append(f"   → <b>다음 거래일({next_trading_day}) TQQQ 재매수</b> (목표 {min(Veff,pool):,.0f} USD)")
                    else:
                        ks_msg.append(f"⚪ 대피 유지 (월말 판정: 복귀 조건 미충족){retro_tag}")
                else:
                    if spx_ok:
                        action_ks="🔵 복귀"
                        ks_msg.append(f"🔵 <b>복귀 신호</b> (S&P 200일선 상향, 버블≥1.30, 월말 종가 판정){retro_tag}")
                        ks_msg.append(f"   → <b>다음 거래일({next_trading_day}) TQQQ 재매수</b> (목표 {min(Veff,pool):,.0f} USD)")
                    else:
                        ks_msg.append(f"⚪ 대피 유지 (월말 판정: 복귀 조건 미충족){retro_tag}")
            else:
                ks_msg.append("⚪ 대피 중 (복귀 판정은 매월 말일 종가 기준 → 다음 거래일 복귀)")

    # ── [1번·4번] VR 밴드 = '상태 표시 + 정합 점검'만. 종가 LOC 매매신호·min_trade 제거.
    #    책의 매매는 사이클 시작에 걸어둔 사다리 지정가가 전담(밴드 터치 즉시 1주부터 체결). ──
    band_msg=[]
    if state=="INVESTED" and action_ks is None:
        bmin,bmax=Veff*BAND_LOW,Veff*BAND_HIGH
        band_msg.append(f"밴드: 하한 {bmin:,.0f} ~ 상한 {bmax:,.0f}  (V={V:,.0f}"
                        + (f", Veff={Veff:,.0f}·노출{scale:.0%}" if ON(VOLTGT_ON) else "")+")")
        band_msg.append(f"TQQQ 평가금(전일 종가): {ev:,.0f} USD  ({pr:,.2f} × {shares:.4f}주)")
        if ev < bmin - 1e-6:
            band_msg.append("🟩 평가금이 하한 아래 — 정상이면 사다리 매수가 이미 체결됐을 구간입니다.")
            band_msg.append("   → 체결됐으면 /buy 로 보고, 사다리를 안 걸었으면 /ladder 로 받아 걸어두세요.")
        elif ev > bmax + 1e-6:
            band_msg.append("🟥 평가금이 상한 위 — 정상이면 사다리 매도가 이미 체결됐을 구간입니다.")
            band_msg.append("   → 체결됐으면 /sell 로 보고, 사다리를 안 걸었으면 /ladder 로 받아 걸어두세요.")
        else:
            band_msg.append("⬜ 밴드 안")

    # ── 목돈/추가납입 안내 (변경 없음 — 목돈성 확정) ──
    dep_msg=[]
    # ★F4-①(2026-07-23): 미확정 목돈 리마인드. 예약만 하고 확정을 잊으면 원장이 계속 어긋난다.
    _plump=float(pos.get("pending_lump",0.0) or 0.0)
    if _plump:
        _pm=str(pos.get("pending_lump_mode","v")).lower()
        dep_msg.append(f"⏳ <b>미확정 목돈 {_plump:+,.0f} USD</b> (모드: {_pm})")
        dep_msg.append("   · 러너가 장중 실행에 자동 집행합니다(AUTO_MODE)."
                       if AUTO_MODE_HINT else
                       "   · 매매 후 <code>/lumpsum_done 주수 @체결가</code>로 확정하세요.")
        dep_msg.append("")
    if pending_dep>0 and AUTO_MODE_HINT:
        # ★③(2026-07-24): AUTO_MODE에선 /deposit·/deposit_done이 러너 가드에 막힌다.
        #   묵은 예약이 남아 있으면 "매수 후 /deposit_done" 안내가 거부되는 명령을 시키는 모순이 된다.
        dep_msg.append(f"⚠️ <b>묵은 추가납입 예약 {pending_dep:,.0f} USD</b> — AUTO_MODE에선 확정 불가")
        dep_msg.append("   · 같은 효과는 <code>/lumpsum +금액 v</code>(동일 P/V 고정 공식, 자동 집행)로 처리하세요.")
        dep_msg.append("   · 예약 자체를 지우려면 <code>/setpos</code>로 원장을 다시 등록하면 초기화됩니다.")
        dep_msg.append("")
    elif pending_dep>0 and state=="INVESTED":
        if total>0 and V>0:
            w=ev/total
            d_tqqq=pending_dep*w; d_pool=pending_dep*(1-w)
            _sh=round(d_tqqq/pr)
            dep_msg.append(f"💰 <b>추가납입 {pending_dep:,.0f} USD 예약됨</b> (P/V 고정)")
            dep_msg.append(f"   ① TQQQ에 <b>약 {d_tqqq:,.0f} USD어치</b> 매수 (실제 체결가로 주수 결정)")
            dep_msg.append(f"      · 참고: 어제 종가 {pr:,.2f} 기준 ≈ {_sh}주")
            dep_msg.append(f"   ② 나머지(약 {d_pool:,.0f})는 자동으로 Pool에 들어감")
            dep_msg.append(f"   매수 후 → <code>/deposit_done 실제주수 @실제체결가</code> 로 확정")
        else:
            _sh=round(pending_dep/pr)
            dep_msg.append(f"💰 <b>추가납입 {pending_dep:,.0f} USD 예약됨</b>")
            dep_msg.append(f"   TQQQ에 <b>약 {pending_dep:,.0f} USD어치</b> 매수 (실제 체결가로 주수 결정)")
            dep_msg.append(f"      · 참고: 어제 종가 {pr:,.2f} 기준 ≈ {_sh}주")
            dep_msg.append(f"   매수 후 → <code>/deposit_done 실제주수 @실제체결가</code> 로 확정")
    elif pending_dep>0 and state=="CASH":
        dep_msg.append(f"💰 <b>추가납입 {pending_dep:,.0f} USD 예약됨</b> (대피 중)")
        dep_msg.append(f"   → 지금은 CASH 상태라 대기. 복귀 매수 후 /deposit_done 으로 반영하세요.")

    # ── 복사용 명령: [1번] 킬스위치 대피/복귀만 유지 (밴드 LOC 복사명령 제거) ──
    copy_cmd=None; cmd_hint=None
    _pi=f"{pr:,.2f}".replace(",","")
    if action_ks=="🔴 대피":
        copy_cmd=f"/exit @{_pi}"
        cmd_hint="전량 매도하셨으면 아래를 복사해 보내세요(가격은 실제 체결가로):"
    elif action_ks=="🔵 복귀":
        buyamt=int(min(Veff,pool))
        copy_cmd=f"/enter {buyamt} @{_pi}"
        cmd_hint="다시 매수하셨으면 아래를 복사해 보내세요(금액·가격은 실제로):"

    # ── 사다리(본 매매 경로): 사이클 시작일에 2주치 게시, 사이클당 1회 ──
    buy_ladder=sell_ladder=[]; ladder_lot=1; ladder_slot=1
    _placed = pos.get("ladder_placed_for")
    is_cycle_start = (wall_today.date() >= cyc_start) and (_placed != str(cyc_start))
    if state=="INVESTED" and action_ks is None and is_cycle_start:
        _bud=None
        if pos.get("cyc_budget") is not None:
            _bud=max(0.0, float(pos["cyc_budget"])-float(pos.get("cyc_used",0.0)))
        buy_ladder, sell_ladder, ladder_lot, ladder_slot = compute_ladder(shares, Veff, pool, budget_override=_bud, cur_px=pr)

    return dict(today=today,dec_date=str(today.date()),p=p,pr=pr,bub=bub,pc=pc,g=g,gs=gs,ndx=ndx,nsm=nsm,rv=rv,scale=scale,
                V=V,Veff=Veff,veff=Veff,ev=ev,pool=pool,shares=shares,total=total,state=state,
                cyc_start=cyc_start,cyc_next=cyc_next,is_month_end=is_month_end,near_month_end=near_month_end,
                is_cycle_start=is_cycle_start,ladder_posted=bool((buy_ladder or sell_ladder) and ladder_lot not in (-1,-2)),
                recover_check_date=(str(me_date.date()) if (me_date is not None and state=="CASH") else None),
                ks_msg=ks_msg,band_msg=band_msg,dep_msg=dep_msg,action_ks=action_ks,
                ks_evac=(action_ks=="🔴 대피"), ks_recover=(action_ks=="🔵 복귀"),
                copy_cmd=copy_cmd,cmd_hint=cmd_hint,
                buy_ladder=buy_ladder,sell_ladder=sell_ladder,ladder_lot=ladder_lot,ladder_slot=ladder_slot)

# ══════════════ [5. 리포트] ══════════════
def build_report(s, df):
    L=[]
    L.append(f"📊 <b>라오어 VR 신호</b> (거치식) — {s['today'].date()}")
    L.append("━"*22)
    ny_today=pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    lag=np.busday_count(s['today'].date(), ny_today.date())
    if lag>=3: L.append(f"⚠️ 데이터 {lag}영업일 지연 — 확인 필요")
    # [실행시각 가드] 미국 정규장 중 실행이면 '다음 거래일 개장가' 지시가 하루 밀림 → 경고.
    try:
        _net=pd.Timestamp.now(tz="America/New_York")
        import pandas_market_calendars as _mc
        _sc=_mc.get_calendar("XNYS").schedule(start_date=_net.date().isoformat(), end_date=_net.date().isoformat())
        if not _sc.empty:
            _op=pd.Timestamp(_sc.iloc[0]["market_open"]).tz_convert("America/New_York")
            _cl=pd.Timestamp(_sc.iloc[0]["market_close"]).tz_convert("America/New_York")
            if _op <= _net < _cl:
                L.append("ℹ️ 미국 장중 실행 — 실시간 지정가 방식에선 <b>정상</b>입니다(장중이어야 접수·체결).")
    except Exception:
        pass
    try:
        _fresh=df.attrs.get("fresh") or {}
        _TOL={"tqqq":2,"gspc":2,"ndx":2,"qqq":2,"irx":5}
        _warn=[]
        for _nm,_info in _fresh.items():
            _last=_info.get("last")
            if _last is None:
                _warn.append(f"{_nm.upper()}: 데이터 없음"); continue
            _d=int(np.busday_count(pd.Timestamp(_last).date(), ny_today.date()))
            _fb="캐시폴백" if _info.get("fallback") else ""
            if _d > _TOL.get(_nm,3) or _info.get("fallback"):
                _warn.append(f"{_nm.upper()} {_d}영업일 지연{(' ('+_fb+')') if _fb else ''}")
        if _warn:
            L.append("⚠️ <b>티커별 신선도 경고</b>: " + " · ".join(_warn))
            L.append("   → 낡은 값이 ffill로 오늘까지 끌려와 킬스위치·밴드가 오판할 수 있습니다.")
        if getattr(_load_m0, "from_cache", False):
            _ma = getattr(_load_m0, "cache_age_days", None)
            if _ma is None or _ma > 45:
                L.append(f"🔴 <b>M0 캐시 폴백</b>: FRED 실패 → 캐시 사용"
                         f"{f' ({_ma}일 전)' if _ma is not None else ''}. "
                         f"버블·B1 판정이 낡았을 수 있습니다 — FRED_API_KEY 확인 필요.")
            else:
                L.append(f"⚠️ M0 캐시 사용({_ma}일 전) — 단기 장애는 무해하나 FRED 상태 확인 권장.")
    except Exception as _e:
        print(f"[신선도 검사 스킵] {_e}")
    # [8번] 완성종가 뷰에선 미국 장중 실행 시 lag=1이 정상 → 월말 경고 임계 1→2.
    if lag>=2 and s.get('near_month_end', False):
        L.append(f"⚠️ <b>월말 주의</b>: 데이터가 {lag}영업일 지연 상태이고 지금은 월말 근처입니다.")
        L.append(f"   당일 종가가 늦게 반영되면 월말 복귀 판정을 놓칠 수 있으니,")
        L.append(f"   실제 날짜·종가를 확인하시고 필요하면 봇을 다시 실행(Run workflow)하세요.")
    L.append(f"\n<b>[시장]</b>")
    L.append(f"TQQQ(실제가) {s['pr']:,.2f} | 버블 {s['bub']:.2f}"
             + (f" (백분위 {float(s['pc']):.0%})" if not pd.isna(s['pc']) else ""))
    L.append(f"S&P {s['g']:,.0f} / 200일선 {s['gs']:,.0f} → {'아래' if s['g']<s['gs'] else '위'}")
    if ON(VOLTGT_ON) and not pd.isna(s['rv']):
        L.append(f"실현변동성 {float(s['rv']):.0%} → 목표노출 {s['scale']:.0%}")
    memo = "  ·오늘=월말 종가판정일(복귀여부 확인)" if s['is_month_end'] else ""
    L.append(f"\n<b>[킬스위치]</b> 상태: {s['state']}{memo}")
    L += s['ks_msg']
    if s['band_msg']:
        L.append(f"\n<b>[VR 밴드]</b>")
        L += s['band_msg']
    # ── 책 예약매수/매도 사다리 (본 매매) ──
    if s['state']=="INVESTED" and s.get('action_ks') is None:
        if s.get('ladder_lot')==-1:
            L.append(f"\n⚠️ <b>사다리 생성 거부 — V 재설정 필요</b>")
            L.append(f"   V={s['V']:,.0f} ÷ 보유{s['shares']:.0f}주 = {s['V']/max(s['shares'],1):,.1f} 인데")
            L.append(f"   현재가는 {s['pr']:,.2f} 입니다 (2.5배 이상 괴리).")
            L.append(f"   → <code>/setv @{s['pr']:,.2f}</code> (현재가) 또는 /setpos 로 V를")
            L.append(f"      재설정하세요. V가 '보유주수×현재가'({s['shares']*s['pr']:,.0f})로 맞춰집니다.")
            L.append(f"   (⚠️ /setv 인자는 '주가'입니다. V값({s['shares']*s['pr']:,.0f})을 넣으면")
            L.append(f"      V={s['shares']:.0f}주×{s['shares']*s['pr']:,.0f}로 {s['shares']:,.0f}배 폭발 → 대량 오주문)")
        elif s.get('ladder_lot')==-2:
            L.append(f"\n⚠️ <b>사다리 생성 거부 — 매수한도가 V 초과 (Pool 과대)</b>")
            L.append(f"   V={s['V']:,.0f} 인데 매수한도(Pool×{BUY_LIMIT:.0%})가 이를 넘습니다.")
            L.append(f"   현금 자릿수 오타 의심 → <code>/setpos</code> 로 Pool(현금)을 다시 확인하세요.")
        elif s.get('buy_ladder') or s.get('sell_ladder'):
            _lot=s.get('ladder_lot',1); _slot=s.get('ladder_slot',_lot)
            _bu="1주씩" if _lot==1 else f"{_lot}주씩(묶음)"
            _su="1주씩" if _slot==1 else f"{_slot}주씩(묶음)"
            L.append(f"\n<b>[사다리 지정가 — 책 방식 · 본 매매] ★사이클 시작일</b>")
            L.append(f"  ⚠️ 먼저 <b>이전 사이클의 미체결 지정가를 전량 취소</b>하고 아래를 새로 거세요(중복 방지).")
            L.append(f"  오늘 사이클 시작 → 아래 2주치 지정가를 한 번 걸어두세요(장중 체결).")
            if _lot>1 or _slot>1:
                L.append(f"  ⚙️ 묶음 매매: 매수 <b>{_lot}주씩</b> · 매도 <b>{_slot}주씩</b> (책 136p: 큰 금액이면 여러 주씩)")
            if s.get('buy_ladder'):
                L.append(f"  🟩 <b>예약매수</b> (저가가 닿으면 {_bu}, 매수한도 내):")
                for pt,sh,pl in s['buy_ladder']:
                    L.append(f"     @ {pt:,.2f} → {sh}주 보유")
            if s.get('sell_ladder'):
                L.append(f"  🟥 <b>예약매도</b> (고가가 닿으면 {_su}, 무제한):")
                for pt,sh,pl in s['sell_ladder']:
                    L.append(f"     @ {pt:,.2f} → {sh}주 보유")
            L.append("  ※ 이 지정가를 2주간 유지. 체결은 증권사 API로 자동 동기화됩니다(보고 불필요)." if AUTO_MODE_HINT
                     else "  ※ 이 지정가를 2주간 유지. 체결되면 실제 주수·가격으로 /buy·/sell 보내세요.")
        else:
            L.append(f"\n<b>[사다리 지정가 — 책 방식 · 본 매매]</b>")
            L.append(f"  오늘은 사이클 중간 → 사이클 시작일({s['cyc_start']})에 건 지정가를 그대로 유지하세요.")
            L.append(f"  (다음 사이클 시작일 {s['cyc_next']}에 새 지정가 목록이 나옵니다)")
    if s['dep_msg']:
        L.append("")
        L += s['dep_msg']
    # ── 복사용 명령 (킬스위치 대피/복귀 시에만) ──
    if s.get('copy_cmd'):
        L.append("\n" + "─"*22)
        if AUTO_MODE_HINT:
            # 자동매매: 러너가 API로 직접 집행하고 체결도 자동 동기화. /exit·/enter는 러너가 거부.
            L.append(f"⏰ <b>실행 (자동)</b>")
            L.append(f"   이 신호는 <b>{s['dec_date']} 종가({s['pr']:,.2f})로 판정</b>한 것입니다.")
            L.append(f"   → 러너가 <b>다음 거래일 개장 직후 자동 집행</b>합니다.")
            L.append(f"   ※ 체결은 증권사 API로 자동 동기화 — <b>별도 보고 불필요</b>합니다.")
            L.append(f"     (AUTO_MODE에선 <code>/exit</code>·<code>/enter</code>가 거부됩니다 — 이중반영 방지)")
        else:
            L.append(f"⏰ <b>실행 방법 (시초가)</b>")
            L.append(f"   이 신호는 <b>{s['dec_date']} 종가({s['pr']:,.2f})로 판정</b>한 것입니다.")
            L.append(f"   → <b>다음 거래일 개장가(MOO, 장 시작) 주문</b>으로 체결하세요.")
            L.append(f"   ※ 실제 체결가는 <b>다음날 시초가(개장가)</b>라 판정 종가와 다를 수 있습니다.")
            L.append(f"     (그래서 아래 @가격에 실제 체결가를 넣는 게 중요합니다)")
            L.append("")
            L.append(f"📋 <b>매매 후 아래 한 줄을 복사해서 보내세요</b>")
            L.append(f"<code>{s['copy_cmd']}</code>")
            L.append("   ↑ 이 줄을 꾹 눌러 복사 → 붙여넣기 → 전송")
            L.append("")
            L.append(f"💡 <b>@뒤의 숫자 = 실제 체결가격</b>")
            L.append(f"   증권사 앱에 뜬 '체결가'(다음날 시초가)로 바꿔주세요.")
            L.append(f"   (봇이 이 가격으로 내 현금을 정확히 계산합니다)")
            L.append(f"   · 가격 확인이 번거로우면 @부분을 <b>지우고</b> 보내도 됩니다")
            L.append(f"     → 그날 종가로 자동 처리 (예: <code>{s['copy_cmd'].split(' @')[0]}</code>)")
        L.append("─"*22)
    L.append(f"\n<b>[사이클]</b> 현재 시작 {s['cyc_start']} · 다음 {s['cyc_next']}")
    L.append(f"보유 {s['shares']:.4f}주 · Pool {s['pool']:,.0f} · 총 {s['total']:,.0f} USD")
    L.append("━"*22)
    L.append("※ 자동매매 모드 — 주문·체결 동기화는 러너가 수행합니다. 체결 보고 명령은 불필요(거부됨)." if AUTO_MODE_HINT
             else "※ 봇은 계산·알림만. 실제 주문은 직접. 매매 후 위 명령을 보내면 다음 신호에 반영됩니다.")
    return "\n".join(L)

# ══════════════ [6. 메인] ══════════════
def _ping():
    if HEALTHCHECK_URL:
        try: requests.get(HEALTHCHECK_URL,timeout=10)
        except Exception: pass

def _cycle_rollover(pos, df):
    """사이클 경계를 넘었으면 V=V+Pool/G 갱신(거치식) + 시작일 전진. CASH 중엔 V 동결.
       [7번] main에서 '체결보고(process_commands) → 롤오버' 순서로 호출됨.
       책·백테스터의 V갱신은 '사이클 종료 시점(체결 반영 후) Pool' 기준 — 경계 넘어 늦게
       보고된 구사이클 체결도 Pool에 먼저 반영한 뒤 V 계산.
       k≥2(장기 중단): 중간 Pool은 알 수 없어 현재 Pool을 k회 사용(중단 중 체결 없으면 정확)."""
    today=_wall_today()
    anchor=pd.Timestamp(pos.get("last_cycle_start",LAST_CYCLE_START)).normalize()
    k=(today-anchor).days//14
    if pos.get("shares",0)==0 and pos.get("pool",0)==0:
        return pos, None, False
    if k>=1:
        msg=None
        if pos.get("state")=="INVESTED":
            V=pos.get("V",0.0)
            if not V:
                px_col = "TQQQ_REAL" if ("TQQQ_REAL" in df.columns and not pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ"
                V=pos.get("shares",0.0)*float(df[px_col].iloc[-1])
            pool=pos.get("pool",0.0)
            for _ in range(k):
                V = V + pool/G
            pos["V"]=V
            msg = f"사이클 {k}회 경과 → V 갱신 {V:,.0f}"
        else:
            msg = f"사이클 {k}회 경과 → (대피 중으로 V 동결)"
        pos["last_cycle_start"]=str((anchor+pd.Timedelta(days=14*k)).date())
        rv0=float(df["RV"].iloc[-1]) if not pd.isna(df["RV"].iloc[-1]) else float("nan")
        pos["cyc_scale"]=min(1.0,VOLTGT_TARGET/rv0) if (ON(VOLTGT_ON) and not pd.isna(rv0) and rv0>0) else 1.0
        pos["cyc_budget"]=max(0.0,pos.get("pool",0.0))*BUY_LIMIT
        pos["cyc_used"]=0.0
        return pos, msg, True
    return pos, None, False

def main():
    df=build_data()
    # [8번] 전 계산을 '완성된 전일 종가' 뷰로 통일(책: 직전 거래일 종가로 V·밴드 확정).
    #   attrs(티커별 신선도)는 슬라이스에서 유실될 수 있어 명시적으로 이관.
    _df2=_drop_live_bar(df)
    if _df2 is not df: _df2.attrs=df.attrs
    df=_df2
    pos=load_position()
    price_hint=float(df["TQQQ_REAL"].iloc[-1]) if ("TQQQ_REAL" in df.columns and not pd.isna(df["TQQQ_REAL"].iloc[-1])) else float(df["TQQQ"].iloc[-1])
    # 0) V=0/미설정이면 먼저 확정
    pos = ensure_V(pos, price_hint)
    # [7번] /enter 기본값(Veff_target)은 CASH에서만 쓰이고 CASH는 롤오버가 V를 동결하므로
    #   롤오버 전에 계산해도 동일.
    V_tmp=pos.get("V",0.0) or (pos.get("shares",0.0)*price_hint)
    if ON(VOLTGT_ON) and "cyc_scale" in pos and pos.get("cyc_scale") is not None:
        scale_tmp=float(pos["cyc_scale"])
    else:
        rv_tmp=float(df["RV"].iloc[-1]) if not pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale_tmp=min(1.0,VOLTGT_TARGET/rv_tmp) if (ON(VOLTGT_ON) and not pd.isna(rv_tmp) and rv_tmp>0) else 1.0
    Veff_target=V_tmp*scale_tmp
    # 1) [7번 순서 교정] 체결보고 먼저 반영 → 사이클말 Pool 완성
    pos, cmd_results = process_commands(pos, price_hint, Veff_target)
    # 2) 롤오버: 체결 반영된 Pool로 V=V+Pool/G (책·백테스터 기준)
    pos, roll_msg, cycle_changed = _cycle_rollover(pos, df)
    if cycle_changed: save_position(pos)

    empty = (pos.get("shares",0)==0 and pos.get("pool",0)==0)
    if empty and not cmd_results:
        p=price_hint
        # ★F2(2026-07-23): 예시 날짜를 동적 생성. 하드코딩 과거 날짜를 그대로 복사하면
        #   _cycle_rollover가 즉시 k회 롤오버해 V가 이중계상된다(/setpos가 정규화하지만 안내도 안전하게).
        _eg_date=(_wall_today().normalize()-pd.Timedelta(days=_wall_today().weekday())).strftime("%Y-%m-%d")
        guide=[
            "⚠️ <b>먼저 현재 보유 상태를 알려주세요</b>",
            "━"*22,
            "봇이 아직 은박사님 보유 현황을 몰라서 신호를 못 냅니다.",
            "아래 형식으로 <b>현재 실제 보유</b>를 한 줄 보내주세요:",
            "",
            "<b>[투자 중이면]</b>",
            "<code>/setpos 보유주수 현금 0 사이클시작일 INVESTED</code>",
            f"   예) 50주 보유, 현금 10000, {_eg_date} 시작:",
            f"<code>/setpos 50 10000 0 {_eg_date} INVESTED</code>",
            "",
            "<b>[아직 현금만 있으면(대피/시작전)]</b>",
            f"<code>/setpos 0 투자금 0 {_eg_date} CASH</code>",
            f"   예) 현금 100000:",
            f"<code>/setpos 0 100000 0 {_eg_date} CASH</code>",
            "",
            "💡 V값은 <b>0</b>을 넣으면 현재 평가금으로 자동 설정됩니다.",
            f"💡 오늘 TQQQ 종가: {p:,.2f} USD (참고용)",
            "━"*22,
            "이 줄을 꾹 눌러 복사 → 숫자만 실제로 고쳐서 → 전송",
        ]
        msg="\n".join(guide)
        if _tg(msg): _ping()
        else: print(msg)
        return

    # 3) 신호 계산
    s=compute_signal(df, pos)
    report=build_report(s, df)
    if s.get('action_ks')=="🔴 대피": save_position(pos)   # ★대피 시 저장: evac_sig_date(소급복귀 스탬프용, /exit가 사용) + evac_reason(대피사유 로그용). 복귀정책 B 이후 evac_reason은 판정에 미사용.
    head=[]
    # ★pending_echo 렌더링: cmd_results가 있으면 echo의 '마지막 원소'가 이번 실행분이므로
    #   그 앞 원소들만 ⏮(지난 실행 처리분)으로 붙인다. cmd_results가 비면 전부 ⏮.
    _echo = pos.get("pending_echo") or []
    _past = _echo[:-1] if cmd_results else _echo
    for _e in _past:
        head.append(f"⏮ <b>지난 실행 처리분(통지 재전송)</b> — {_e.get('ts','?')} 처리")
        head += [f"   • {l}" for l in (_e.get("lines") or [])]
        head.append("   ※ 이미 원장에 반영된 내역의 재통지입니다(새 체결 아님).")
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg: head.append(f"🔄 {roll_msg}")
    if head: report="\n".join(head)+"\n\n"+report
    sent_ok=_tg(report)
    if sent_ok:
        _ping()
        if pos.get("pending_echo"):        # ★S4: 발송 성공 시에만 소거. 실패면 잔존 → 다음 실행 ⏮
            pos["pending_echo"]=[]; save_position(pos)
        if s.get('ladder_posted'):
            pos["ladder_placed_for"]=str(s['cyc_start']); save_position(pos)
        rcd=s.get('recover_check_date')
        recovering=bool(s.get('ks_recover')) or (s.get('action_ks')=="🔵 복귀")
        if rcd and not recovering and rcd!=pos.get("last_recover_check",""):
            pos["last_recover_check"]=rcd; save_position(pos)
    else:
        print("[경고] 텔레그램 전송 실패 — ping 생략"); print(report)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _emergency_tg(e)
        print(f"[크래시] {e}")
        raise
