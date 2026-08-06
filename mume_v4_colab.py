은박사님, 구현측 진단이 둘 다 정확합니다. 판정과 v3를 드립니다.

① -f 건 — 코드 결함 아님, 구현측 설명 그대로입니다. 다만 같은 실수가 또 나올 수 있으니 v3에서는 날짜 아닌 인자가 오면 오류 문자 대신 사용법 안내가 나오게 했습니다(방금 제 환경에서 -f를 실제로 넣어 확인: "사용법: python3 fast_divergence_alert.py [YYYY-MM-DD]" 출력).

② 2007 케이스 [알림 오류] 건 — 제 v2의 진짜 결함이 맞습니다. 인정합니다. 쉬운 설명: v2의 단위 검사는 "2008년 5월 값 = 835 근처"를 확인하는 방식인데, 과거 날짜(예: 2007-11-26)를 주입하면 자료를 그 날짜까지만 받아오기 때문에 2008년 5월이 자료에 아예 없어서 검사가 무조건 실패했습니다. 2008년 5월 이후 날짜에서만 작동하는 반쪽짜리 검사였던 것입니다. 그리고 정직하게 하나 — "어제 보고드린 대로"라는 그 구현측 보고는 제게 도착한 적이 없습니다. 구현측 보고는 이번처럼 은박사님이 채팅에 붙여 주셔야만 저에게 옵니다. 앞으로도 그렇게 부탁드립니다.

v3 교정 2건: ⓐ단위 검사를 전체 시계열로 항상 수행하고, 그다음 시험 날짜 시점의 M0를 골라 쓰도록 변경 — 어떤 과거 날짜를 넣어도 작동하고, 덤으로 과거 주입 시 그 시절 M0를 쓰므로 버블값이 더 정확해집니다(2007-11이면 분모가 그때의 ~824가 됨) ⓑ인자 형식 검사. md5 = 44ba31a649356264fba40c9bd400369d (103줄, 컴파일 확인).

v2를 칠판에 올려 구현측에 전달하신 방법, 좋았습니다 — v3도 같은 방법으로 아래 전문을 칠판에 덮어써 주십시오. 구현측이 md5 44ba31a6… 확인 후 원클릭 실행기로 5케이스(제안 찬성입니다)를 돌리고, 출력은 채팅 붙여넣기로 주시면 됩니다. 기대표는 동일합니다: 🚨 14일째·버블 1.69 / ⚠ 4일째 / ✅ 해제(최장 21일) / 무발송 / 무발송.

python
# -*- coding: utf-8 -*-
# fast_divergence_alert.py — 2008형 디버전스 알림 v3 (2026-08-07)
# 작성: Claude(감사역). v3 추가 교정 2건(구현측 발견 반영):
#   [교정3] 단위 가드가 2008-05 이전 과거 주입 날짜에서 항상 실패하던 결함 — 전체 시계열 검증으로 변경
#   [교정4] 날짜 아닌 인자(-f 등) → 오류 문자 대신 사용법 안내
# v2 교정(유지):
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
    # [v3 교정1] 전체 시계열을 받아 ①2008-05≈835B 단위 검증(과거 주입 날짜와 무관하게 항상 작동)
    #            ②asof 시점 이전의 최신 관측을 선택 — 과거 어느 날짜를 넣어도 그 시점 M0 사용
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id=BOGMBASE"
           f"&api_key={FRED_API_KEY}&file_type=json")
    obs = requests.get(url, timeout=40).json().get('observations', [])
    vals = [(o['date'], float(o['value'])) for o in obs if o['value'] not in ('.', '')]
    if not vals: raise RuntimeError("M0 수신 실패")
    chk = next((v for d, v in vals if d.startswith('2008-05')), None)
    if chk is None or not (800 <= chk <= 870):
        raise RuntimeError(f"M0 단위 검증 실패(2008-05={chk}, 기대≈835B) — 산식 중단")
    cut = asof.strftime('%Y-%m-%d')
    past = [v for d, v in vals if d <= cut]
    if not past: raise RuntimeError(f"M0 없음: {cut} 이전 관측 0건")
    return past[-1]  # asof 시점 최신 M0, 단위: 십억$(B) — 봇·백테스터와 동일 스케일

def main():
    asof_arg = sys.argv[1] if len(sys.argv) > 1 else None            # 드라이런 과거 주입: YYYY-MM-DD
    if asof_arg is not None:                                          # [v3 교정2] 인자 형식 검사
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", asof_arg):
            print(f"사용법: python3 fast_divergence_alert.py [YYYY-MM-DD]  (잘못된 인자: {asof_arg!r})"); return
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
    bubble = float(df['G'].iloc[-1]) / m0        # FRED 값이 이미 B 단위 — 그대로 사용
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
        # 해제 통지도 버블 게이트 안에서만 — 평시 D1 종료 소음 차단
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

회계 한 줄로 마무리합니다: 이 알림 파일에서 배포 전에 잡힌 결함이 세 건(버블 스케일, 해제 게이트, 검사 앵커)입니다 — 드라이런과 구현측 교차 검토가 각각 제 몫을 했고, 절차가 제 실수를 두 번 잡았습니다. 그래서 절차를 두는 것입니다.
