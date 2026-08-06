# -*- coding: utf-8 -*-
# fast_divergence_alert.py — 2008형 디버전스 알림 v2 (2026-08-07)
# 작성: Claude(감사역). 드라이런 1차에서 잡힌 결함 2건 교정:
#   [교정1] 버블 스케일 1,000배 오류 — FRED BOGMBASE 실측 반환값은 이미 십억$(B) 단위
#           → /1000 제거 + 2008-05≈835B 단위 검증 가드 추가(봇·백테스터와 동일 철학)
#   [교정2] 해제(✅) 통지에 버블 게이트 부재 → 평시 소음 차단 위해 게이트 추가
#   [정리]  utcnow 폐지 경고 제거
import os, sys, datetime as dt
import requests
import pandas as pd

DRY_RUN = True                 # 드라이런 통과 후 False
HOLDING = True                 # 실제 대피 시 수동으로 False — False면 침묵
BUBBLE_LIMIT = 1.30
HIST_FAKE_MAX = 11             # 2026-08-06 프로브 실측 고정 상수 — 재계산 금지
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
TG_TOKEN = os.environ.get("FAST_TG_TOKEN", "")
TG_CHAT  = os.environ.get("FAST_TG_CHAT", "")

def send(msg):
    if DRY_RUN:
        print("[DRY_RUN]\n" + msg); return
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  data={"chat_id": TG_CHAT, "text": msg}, timeout=30).raise_for_status()

def get_close(tk, start):
    import yfinance as yf
    s = yf.download(tk, start=start, progress=False, auto_adjust=True)['Close'].squeeze()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.resample('B').ffill()

def get_m0(asof):
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=BOGMBASE"
           f"&api_key={FRED_API_KEY}&file_type=json&observation_end={asof:%Y-%m-%d}")
    obs = requests.get(url, timeout=40).json().get('observations', [])
    vals = [(o['date'], float(o['value'])) for o in obs if o['value'] not in ('.', '')]
    if not vals: raise RuntimeError("M0 수신 실패")
    chk = next((v for d, v in vals if d.startswith('2008-05')), None)
    if chk is None or not (800 <= chk <= 870):
        raise RuntimeError(f"M0 단위 검증 실패(2008-05={chk}, 기대≈835B) — 산식 중단")
    return vals[-1][1]  # 단위: 십억$(B) — 봇·백테스터와 동일 스케일

def main():
    asof_arg = sys.argv[1] if len(sys.argv) > 1 else None            # 드라이런 과거 주입: YYYY-MM-DD
    today_et = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(hours=4)
    asof = pd.Timestamp(asof_arg) if asof_arg else pd.Timestamp(today_et.date())
    start = (asof - pd.Timedelta(days=600)).strftime('%Y-%m-%d')
    g = get_close('^GSPC', start); n = get_close('^NDX', start)
    df = pd.DataFrame({'G': g, 'N': n}).dropna()
    df['SG'] = df['G'].rolling(200).mean(); df['SN'] = df['N'].rolling(200).mean()
    df = df.dropna(); df = df[df.index <= asof]
    if len(df) < 5: raise RuntimeError("데이터 부족")
    last = df.index[-1]
    if asof_arg is None and last.date() != asof.date():
        print(f"무발송: 데이터 최신일 {last.date()} ≠ 오늘 {asof.date()} (휴장/지연)"); return
    d1 = (df['G'] < df['SG']) & (df['N'] >= df['SN'])
    m0 = get_m0(last)
    bubble = float(df['G'].iloc[-1]) / m0        # [교정1] FRED 값이 이미 B 단위 — 그대로 사용
    if not HOLDING:
        print("HOLDING=False — 침묵"); return
    gpct = (df['G'].iloc[-1] / df['SG'].iloc[-1] - 1) * 100
    npct = (df['N'].iloc[-1] / df['SN'].iloc[-1] - 1) * 100
    if d1.iloc[-1] and bubble >= BUBBLE_LIMIT:
        N = 0
        for v in d1.values[::-1]:
            if v: N += 1
            else: break
        if N <= HIST_FAKE_MAX:
            send(f"⚠ [2008형 감시] S&P만 200일선 아래 — 오늘 {N}일째 (나스닥은 위)\n"
                 f"버블 {bubble:.2f} | S&P 선 대비 {gpct:+.1f}% | 나스닥 {npct:+.1f}%\n"
                 f"참고: 지난 40년 가짜 경보는 전부 {HIST_FAKE_MAX}일 안에 끝났습니다. 관찰 계속.")
        else:
            send(f"🚨 [대피 권고] S&P만 이탈 {N}일째 — 역대 가짜가 도달한 적 없는 구간.\n"
                 f"이 선을 넘긴 것은 2007년(진짜, 21일 지속) 한 번뿐입니다. 대피 검토 시점.\n"
                 f"버블 {bubble:.2f} | S&P {gpct:+.1f}% | 나스닥 {npct:+.1f}%")
    elif len(d1) >= 2 and d1.iloc[-2] and not d1.iloc[-1] and bubble >= BUBBLE_LIMIT:
        # [교정2] 해제 통지도 버블 게이트 안에서만 — 평시 D1 종료 소음 차단
        N = 0
        for v in d1.values[:-1][::-1]:
            if v: N += 1
            else: break
        send(f"✅ 해제 — 조건 종료(최장 {N}일). 관찰 종료.")
    else:
        print("조건 미충족 — 무발송")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try: send(f"[알림 오류] fast_divergence_alert: {e}")
        except Exception: print(f"[알림 오류·발송 실패] {e}")
