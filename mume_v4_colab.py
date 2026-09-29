# -*- coding: utf-8 -*-
"""acct1_preview.py — ACCT-1 배포 전 실계좌 미리보기 (조회만 · 주문 없음 · 원장 파일 미변경 · 텔레그램 미발송)
   ~/toss 에서  $ python3 acct1_preview.py  한 줄로 실행. 같은 폴더의 .env(KEY=VALUE)를 읽어 API 키를 쓴다(값은 출력하지 않음).
   출력: 실보유·주문가능금액·대기 매수 증거금 역산·원장 대조·건 분류·리포트에 나갈 질문 문구(그대로)."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
# .env 로드(러너 크론과 동일 변수). 값은 절대 출력하지 않는다.
for _envf in (".env", "toss.env"):
    if os.path.exists(_envf):
        for _ln in open(_envf, encoding="utf-8"):
            _ln = _ln.strip()
            if not _ln or _ln.startswith("#") or "=" not in _ln: continue
            _k, _v = _ln.split("=", 1); _k = _k.strip().replace("export ", ""); _v = _v.strip().strip('"').strip("'")
            os.environ.setdefault(_k, _v)
        break
os.environ["DRY_RUN"] = "on"          # 미리보기: 러너 모듈이 DRY로 로드되게(주문 경로 원천 차단)
os.environ["TELEGRAM_TOKEN"] = ""     # 텔레그램 미발송(봇 _tg는 토큰 없으면 print)
import vr_signal_bot as bot
import vr_auto_runner_toss as R

pos = bot.load_position()
print("[원장] shares=%s pool=%s V=%s state=%s cycle=%s" % (pos.get("shares"), pos.get("pool"), pos.get("V"), pos.get("state"), pos.get("last_cycle_start")))
print("[열린 건]", json.dumps(pos.get("acct_case"), ensure_ascii=False) if pos.get("acct_case") else "없음")
broker = R.make_broker()
snap = R._acct_snapshot(broker)
print("[실계좌] 보유 %g주 · 주문가능 $%.2f · 대기주문 %d건 · 대기 매수 증거금 역산 $%.2f · 현금(C_a) $%.2f · 현재가 %.2f"
      % (snap["S_a"], snap["cash_bp"], snap["n_open"], snap["reserve"], snap["C_a"], snap["px"]))
krw = R._acct_krw(broker)
print("[원화 예수금]", ("₩%s" % format(int(krw), ",")) if krw is not None else "조회 실패/없음")
# 전일 완성 종가(price_hint)는 데이터 빌드가 필요 — 미리보기에서는 현재가로 대체(처음 등록 V·목돈 비중 표시에만 영향)
case = R._acct_classify(pos, snap, snap["px"])
print("[분류]", json.dumps({k: v for k, v in (case or {}).items()}, ensure_ascii=False, default=str) if case else "변동 없음(잔돈 문턱 이내)")
if case:
    today = R._acct_now().strftime("%Y-%m-%d")
    print("\n[리포트에 나갈 질문 문구 — 미리보기(건번호는 실제 실행에서 부여)]")
    print(R._acct_message(case, "N", today, 1, snap))
print("\n※ 조회만 했습니다. 원장 파일·주문·텔레그램 모두 건드리지 않았습니다.")
