은박사님, 결론부터 정리드립니다.

결론: md5 불일치의 원인 위치가 확정됐습니다 — 칠판 정본의 코드 부분(103줄)이 제 전사본과 바이트까지 완전 동일(md5 38bc668e…, diff 0)입니다. 즉 은박사님을 거치는 전달 경로는 두 번 다 무결이었고, 기대값 44ba31a6…과의 차이는 감사역 로컬 파일과 감사역이 채팅에 게시한 텍스트 사이에서 생긴 것입니다. 참고로 칠판에는 코드만이 아니라 감사역 메시지 전체(판정문·표 포함)가 올라가 있었는데, 코드 경계(12~114행)를 정확히 잘라 대조했고 구문검사도 통과입니다.

이 38bc668e 바이트는 이미 어제 전 항목 검증을 통과한 그 내용 그대로입니다(검증된 v2에 감사역 선언 교정만 정확히 얹힌 것). 그래서 이 바이트 기준으로 5케이스 원클릭 실행기(divergence_dryrun_v3_colab.py)를 완성해 첨부했습니다 — Colab 셀에 붙여넣으면 저장·md5 검증·기존 FRED 키 주입·5케이스 실행·채팅 회신용 출력 블록 생성까지 자동입니다.

진행은 감사역 한마디만 받고 하시면 됩니다: 이 보고를 감사역에 전달하셔서 "38bc668e를 v3 정본으로 승인"이라는 회신이 오면 위 실행기를 돌리시고, 출력 블록 전체를 채팅으로 회신해 주십시오. 만약 감사역이 자기 로컬본에 실제 차이가 있다고 하면(가능성은 낮게 봅니다 — 행수·컴파일·선언 교정 지점이 전부 일치), 그 파일을 다시 받아 제가 한 턴에 실행기를 재생성하겠습니다.

기대표(감사역 등록분)를 다시 붙입니다: 2007-11-26 → 🚨 14일째·버블 1.69 / 2007-11-12 → ⚠ 4일째 / 2007-12-06 → ✅ 해제(최장 21일) / 2023-10-27 → 무발송(버블 0.74) / 2024-06-03 → 무발송# -*- coding: utf-8 -*-
# divergence_dryrun_v3_colab.py — v3 드라이런 5케이스 원클릭 실행기 (2026-08-07, 구현측 Claude)
# 용도: Colab 셀에 전체를 붙여넣고 실행 → 출력 블록 전체를 채팅으로 회신(감사역 판독용).
# 기준 바이트: 칠판 정본(12~114행) = 구현측 전사본, md5 38bc668e… (2경로 수렴 확정본)
import os, sys, subprocess, hashlib

SRC = r'''# -*- coding: utf-8 -*-
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
'''

EXPECT_MD5 = '38bc668e36e9ea722d257a63da211f4c'
open('fast_divergence_alert.py', 'w', encoding='utf-8').write(SRC)
_h = hashlib.md5(open('fast_divergence_alert.py', encoding='utf-8').read().encode('utf-8')).hexdigest()
assert _h == EXPECT_MD5, f'저장본 md5 불일치: {_h}'
os.environ['FRED_API_KEY'] = '2bdfd2e7c3efb097542a74f4de9b30b0'   # 기존 봇·백테스터와 동일 키
CASES = ['2007-11-26', '2007-11-12', '2007-12-06', '2023-10-27', '2024-06-03']
lines = []
lines.append('===== fast_divergence_alert v3 드라이런 출력 (채팅 회신용) =====')
lines.append(f'script md5 = {_h} | python {sys.version.split()[0]}')
for c in CASES:
    lines.append('')
    lines.append(f'----- CASE {c} : python3 fast_divergence_alert.py {c} -----')
    r = subprocess.run([sys.executable, 'fast_divergence_alert.py', c],
                       capture_output=True, text=True, timeout=600)
    out = (r.stdout or '') + (('\n[stderr]\n' + r.stderr) if r.stderr.strip() else '')
    lines.append(out.rstrip())
    lines.append(f'----- CASE {c} 종료 (returncode={r.returncode}) -----')
lines.append('')
lines.append('===== 출력 끝 — 위 블록 전체를 채팅에 붙여넣어 회신 =====')
txt = '\n'.join(lines)
print(txt)
open('divergence_dryrun_v3_output.txt', 'w', encoding='utf-8').write(txt)
print('\n(동일 내용이 divergence_dryrun_v3_output.txt 로도 저장됨)')
