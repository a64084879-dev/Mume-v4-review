# -*- coding: utf-8 -*-
"""ACCT-1 자체 검증 하니스 — 실제 vr_signal_bot(76d3b6a4)·vr_broker_adapter(33d0ec59)·vr_toss_adapter(aad1d7c3)를
   그대로 임포트하고, 브로커만 가짜(FakeBroker)로 바꿔 감지→질문→답→집행을 돌린다. 주문·네트워크 없음.
   사양서 v0.5 §9 T1~T13 중 1단계 해당분(T1·T2·T3·T4·T4b·T4c·T5·T6·T7·T8·T10·T11·T13)."""
import os, sys, json, tempfile, importlib, math
os.environ.update({"DRY_RUN": "off", "LIVE_ARM": "on", "AUTO_MODE": "on", "AUTO_RECOVER": "on",
                   "TELEGRAM_TOKEN": "", "TELEGRAM_CHAT_ID": "", "HEALTHCHECK_URL": "",
                   "TOSS_CLIENT_ID": "x", "TOSS_CLIENT_SECRET": "y", "TOSS_ACCOUNT": "1"})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(); os.chdir(TMP)
import vr_signal_bot as bot
from vr_broker_adapter import Position
from vr_toss_adapter import TossAdapter
R = importlib.import_module("vr_auto_runner_toss")
bot.POSITION_FILE = os.path.join(TMP, "vr_position.json")

class FakeBroker:
    EP = TossAdapter.EP
    _num = staticmethod(TossAdapter._num)
    def __init__(self, shares, cash_bp, px, opens=None, krw=0.0):
        self.shares, self.cash_bp, self.px, self.opens, self.krw = shares, cash_bp, px, (opens or []), krw
    def get_holdings(self, symbol): return Position(symbol, float(self.shares), 0.0)
    def list_open_orders(self, symbol): return list(self.opens)
    def get_cash_usd(self): return float(self.cash_bp)
    def get_price(self, symbol): return float(self.px)
    def _req(self, method, path, payload, err, with_account=True, params=None):
        return {"result": {"currency": "KRW", "cashBuyingPower": str(self.krw)}}

class Log:
    def __init__(self): self.msgs = []
    def __call__(self, m): self.msgs.append(m)
    def text(self): return "\n".join(self.msgs)
    def clear(self): self.msgs = []

PASS = []; FAIL = []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))

def ledger(shares, pool, V, state="INVESTED", lcs="2026-09-20", **kw):
    p = {"shares": float(shares), "pool": float(pool), "V": float(V), "state": state,
         "last_cycle_start": lcs, "last_recover_check": lcs, "pending_deposit": 0.0}
    p.update(kw); return p

def buy_orders(n, qty, price):
    return [{"order_id": f"o{i}", "side": "buy", "price": f"{price:.2f}", "qty": qty} for i in range(n)]

# ───────────────────────────── T3: 배당 +68.16 → 원장 맞춤(Pool만) ─────────────────────────────
pos = ledger(652, 11651, 52170); log = Log()
brk = FakeBroker(652, 11651 + 68.16, 76.69)
pos = R._acct_detect(brk, pos, log, 76.69)
c = pos.get("acct_case")
check("T3a 감지→건 생성(fix_pool)", c and c["kind"] == "fix_pool" and c["id"] == 1 and c["cmd"] == "/lumpsum +68.16 pool!", str(c))
check("T3a N=1(0.71 반올림)·허용오차 내", c and c["N"] == 1, str(c and c["N"]))
check("T3a 질문 문구에 금액·답 줄", "Pool 11,651.00 → 11,719.16" in log.text() and "/예 1" in log.text(), log.text())
pos2, msg = bot.apply_command(pos, "/예 1", 76.69)          # 러너 가드 경유(= 텔레그램 명령 경로)
check("T3a /예 1 → 집행(Pool 11,719.16·V 불변·주식 불변)",
      abs(pos2["pool"] - 11719.16) < 0.005 and pos2["V"] == 52170 and pos2["shares"] == 652 and "acct_case" not in pos2, f"{pos2.get('pool')} {msg}")
check("T3a 반영 메시지에 원장 명령 표기", "/lumpsum +68.16 pool!" in msg and msg.startswith("✅"), msg)
# 다음 실행: 차이 없음 → 조용
log.clear(); brk = FakeBroker(652, 11719.16, 76.69)
pos3 = R._acct_detect(brk, pos2, log, 76.69)
check("T3a 다음 실행 변동 없음(질문 없음·건 없음)", "acct_case" not in pos3 and log.text() == "", log.text())

# T3b: 입금 +1,000 → 목돈 경로(lump_v)
pos = ledger(652, 11651, 52170); log = Log()
brk = FakeBroker(652, 12651.0, 76.69)
pos = R._acct_detect(brk, pos, log, 76.69); c = pos["acct_case"]
N_exp = int(round(1000 / (11651/652 + 76.69*1.001)))
check("T3b 감지→lump_v, N=11", c["kind"] == "lump_v" and c["N"] == N_exp == 11 and c["cmd"] == "/lumpsum +1000.00 v", str(c))
w = 652*76.69/(652*76.69+11651)
check("T3b V' = V×(1+ΔC/총자산)", abs(c["V_new"] - 52170*(1+1000/(652*76.69+11651))) < 0.01, str(c["V_new"]))
check("T3b 예상 주수 = int(1000×w/px) = 10 (목돈 경로는 내림)", c["q_est"] == int(1000*w/76.69) == 10, str(c["q_est"]))
pos2, msg = bot.apply_command(pos, "/예 1", 76.69)
check("T3b /예 → 목돈 예약 등록(pending_lump 1000 v)·건 종료",
      pos2.get("pending_lump") == 1000.0 and pos2.get("pending_lump_mode") == "v" and "acct_case" not in pos2, f"{pos2.get('pending_lump')} {msg[:80]}")
# 목돈 진행 중이면 감지 보류
log.clear(); pos3 = R._acct_detect(FakeBroker(652, 12651.0, 76.69), pos2, log, 76.69)
check("T3b 목돈 대기 중 감지 보류", "보류" in log.text() and "acct_case" not in pos3, log.text())

# ───────────────────────────── T4: 9/29 입고 재현(81주 입고 + 현금 차이, 대기 매수 36건) ─────────────────────────────
pos = ledger(514, 9191, 41128); log = Log()
opens = buy_orders(36, 2, 4583.00/72)          # 36건×2주, 주문금액 합 4,583.00
brk = FakeBroker(595, 11421.10, 76.38, opens=opens)
pos = R._acct_detect(brk, pos, log, 76.38); c = pos["acct_case"]
snap = R._CTX["detect"]["snap"]
_principal = sum(o["qty"] * float(o["price"]) for o in opens)                  # 36×2×63.65 = 4,582.80(2자리 지정가)
check("T4 현금 역산: 주문가능 11,421.10 + 대기매수 4,582.80×1.001 = 16,008.48 (실측 총예수금 16,008.52와 $0.04 차)",
      abs(snap["C_a"] - round(11421.10 + _principal * 1.001, 2)) < 0.005 and abs(snap["C_a"] - 16008.52) < 0.25, str(snap))
r = 9191/514
N_exp = int(round((snap["C_a"] - r*595) / (r + 76.38*1.001)))
check("T4 N = 57(제안 57주)", c["N"] == N_exp == 57, f"{c['N']} vs {N_exp}")
check("T4 복합 변동 → mixed(1단계: 원장 맞춤 제안 + 매수 57주 안내)", c["kind"] == "mixed" and "매수 약 57주" in log.text(), log.text())
check("T4 V_trade = 41,128×652÷514 = 52,170", abs(c["V_trade"] - 41128*652/514) < 0.01 and abs(c["V_trade"] - 52170) < 1, str(c["V_trade"]))
check("T4 P=78 → 56주", int(round((snap["C_a"] - r*595) / (r + 78*1.001))) == 56)
check("T4 질문에 증거금 역산 표기", "대기 매수주문 36건 증거금" in log.text(), log.text())
# T4-after: 앱에서 57주 @76.38 매수 후 다음 실행 → 새 건(fix_pos) → /예 → 수동 /setpos 652 11651 52170 과 동일 원장
log.clear(); brk = FakeBroker(652, 11650.51, 76.69)
pos = R._acct_detect(brk, pos, log, 76.69); c = pos["acct_case"]
check("T4-after 변동 바뀜 → 새 건 #2, fix_pos, N=0", c["id"] == 2 and c["kind"] == "fix_pos" and c["N"] == 0, str(c))
pos2, msg = bot.apply_command(pos, "/예 1", 76.69)
check("T8 옛 건번호 /예 1 거부(현재 #2)", "건번호 불일치" in msg and pos2.get("acct_case") and pos2["shares"] == 514, msg)
pos2, msg = bot.apply_command(pos, "/예", 76.69)
check("T8 번호 없는 /예 거부", "건번호를 붙여" in msg and pos2["shares"] == 514, msg)
pos2, msg = bot.apply_command(pos, "/예 2", 76.69)
check("T4-after /예 2 → 원장 652·11,650.51·V 52,169.6(=41,128×652÷514) — 수동 /setpos 652 11651 52170 과 동치",
      pos2["shares"] == 652 and abs(pos2["pool"] - 11650.51) < 0.005 and abs(pos2["V"] - 41128*652/514) < 0.01 and pos2["last_cycle_start"] == "2026-09-20", f"{pos2['shares']} {pos2['pool']} {pos2['V']} {pos2['last_cycle_start']}")
check("T4-after 매수한도 = Pool×50%(=/setpos 동일)·cyc_used 0", abs(pos2["cyc_budget"] - 11650.51*0.5) < 0.01 and pos2["cyc_used"] == 0)

# ───────────────────────────── T4c: 아니오 → 예비 경로 ─────────────────────────────
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 12651.0, 76.69), pos, log, 76.69)
pos, msg = bot.apply_command(pos, "/아니오 1", 76.69)
check("T4c /아니오 → 건 종료·declined 기록", "acct_case" not in pos and pos["acct_declined"]["kind"] == "lump_v", msg)
log.clear(); pos = R._acct_detect(FakeBroker(652, 12651.0, 76.69), pos, log, 76.69); c = pos["acct_case"]
check("T4c 다음 실행 → 예비 경로(Pool만) 새 건 #2", c["id"] == 2 and c["kind"] == "fix_pool" and c["cmd"] == "/lumpsum +1000.00 pool!", str(c))
pos, msg = bot.apply_command(pos, "/아니오 2", 76.69)
log.clear(); pos = R._acct_detect(FakeBroker(652, 12651.0, 76.69), pos, log, 76.69)
check("T4c 그것도 아니오 → 보류 한 줄만·건 없음", "보류 중" in log.text() and "acct_case" not in pos and log.text().count("\n") == 0, log.text())
log.clear(); pos = R._acct_detect(FakeBroker(652, 12651.0 + 500, 76.69), pos, log, 76.69)
check("T4c 변동이 바뀌면 다시 묻는다(새 건 #3)", pos.get("acct_case") and pos["acct_case"]["id"] == 3, log.text()[:120])

# ───────────────────────────── T5: 인출 −3,000 ─────────────────────────────
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 8651.0, 76.69), pos, log, 76.69); c = pos["acct_case"]
check("T5 인출 → lump_v(매도), N<0, 양도세 문구, 현금부족 경고", c["kind"] == "lump_v" and c["N"] < 0 and c["cmd"] == "/lumpsum -3000.00 v"
      and "양도소득세" in log.text() and "실제 현금이 원장 Pool보다 적습니다" in log.text(), log.text())
pos2, msg = bot.apply_command(pos, "/예 1", 76.69)
check("T5 /예 → 목돈 인출 예약(-3000 v)", pos2.get("pending_lump") == -3000.0 and pos2.get("pending_lump_mode") == "v", msg[:100])

# ───────────────────────────── T6/T7: 처음 시작 ─────────────────────────────
pos = {"shares": 0.0, "pool": 0.0, "V": 0.0, "state": "INVESTED", "last_cycle_start": "2026-01-02", "last_recover_check": "2026-01-02", "pending_deposit": 0.0}
log = Log(); pos = R._acct_detect(FakeBroker(236, 2000.0, 76.0), pos, log, 76.0); c = pos["acct_case"]
today = R._acct_now().strftime("%Y-%m-%d")
check("T6 처음 등록(보유 있음) 건", c["kind"] == "first_hold" and c["cmd"] == f"/setpos 236 2000.00 0 {today} INVESTED", str(c))
pos2, msg = bot.apply_command(pos, "/예 1", 76.0)
check("T6 /예 → 등록: 236주·Pool 2,000·V=236×76=17,936·사이클 시작 오늘·한도 1,000",
      pos2["shares"] == 236 and pos2["pool"] == 2000 and abs(pos2["V"] - 236*76) < 0.01 and pos2["last_cycle_start"] == today and abs(pos2["cyc_budget"] - 1000) < 0.01, f"{pos2}")
pos = {"shares": 0.0, "pool": 0.0, "V": 0.0, "state": "INVESTED", "last_cycle_start": "2026-01-02", "last_recover_check": "2026-01-02", "pending_deposit": 0.0}
log = Log(); pos = R._acct_detect(FakeBroker(0, 20000.0, 76.0), pos, log, 76.0); c = pos["acct_case"]
check("T7 처음 시작(현금뿐) 안내: ⌊20,000×0.9÷76⌋=236주", c["kind"] == "first_cash" and c["N"] == 236 and c["cmd"] is None and "236주" in log.text(), log.text())
pos2, msg = bot.apply_command(pos, "/예 1", 76.0)
check("T7 /예 → 안내 전용(원장 무변경)", "안내 전용" in msg and pos2["shares"] == 0, msg)
log = Log(); pos = R._acct_detect(FakeBroker(0, 500.0, 76.0), {"shares": 0.0, "pool": 0.0, "V": 0.0, "state": "INVESTED"}, log, 76.0)
check("T12 소액($500) 처음 시작 안내($3,000 미만 문구)", "$3,000 미만" in log.text(), log.text())

# ───────────────────────────── T10: CASH 중 → Pool만 ─────────────────────────────
pos = ledger(0, 20000, 18000, state="CASH"); log = Log()
pos = R._acct_detect(FakeBroker(0, 20500.0, 76.0), pos, log, 76.0); c = pos["acct_case"]
check("T10 CASH 중 입금 → cash_pool", c["kind"] == "cash_pool" and c["cmd"] == "/lumpsum +500.00 pool!", str(c))
pos2, msg = bot.apply_command(pos, "/예 1", 76.0)
check("T10 /예 → Pool 20,500·V 18,000 유지·매매 없음", pos2["pool"] == 20500 and pos2["V"] == 18000 and pos2["shares"] == 0 and pos2["state"] == "CASH", msg)

# ───────────────────────────── T13: 책 예시 재현 ─────────────────────────────
# ② 208쪽: 평가금 18,000(300주×60)·Pool 2,000·V 20,000 + 10,000 → 매수 9,000·Pool 3,000·V 30,000
pos = ledger(300, 2000, 20000); log = Log()
pos = R._acct_detect(FakeBroker(300, 12000.0, 60.0), pos, log, 60.0); c = pos["acct_case"]
check("T13② +10,000 → lump_v: 매수 150주=$9,000·V 30,000", c["kind"] == "lump_v" and c["q_est"] == 150 and abs(c["V_new"] - 30000) < 0.01, str(c))
# ③ 209쪽: 주식 9,000 매도 + 10,000 인출(앱에서 실행 후 계좌: 150주·현금 1,000) → 매매 0·Pool 1,000·V 10,000
pos = ledger(300, 2000, 20000); log = Log()
pos = R._acct_detect(FakeBroker(150, 1000.0, 60.0), pos, log, 60.0); c = pos["acct_case"]
pos2, msg = bot.apply_command(pos, "/예 1", 60.0)
check("T13③ 매도+인출 후 → fix_pos: 150주·Pool 1,000·V 10,000", c["kind"] == "fix_pos" and c["N"] == 0 and pos2["shares"] == 150 and pos2["pool"] == 1000 and abs(pos2["V"] - 10000) < 0.01, f"{c} {pos2}")
# ③' 현금만 −1,000 → 매도 900·Pool 1,900·V 19,000
pos = ledger(300, 2000, 20000); log = Log()
pos = R._acct_detect(FakeBroker(300, 1000.0, 60.0), pos, log, 60.0); c = pos["acct_case"]
check("T13③' −1,000 → lump_v: 매도 15주=$900·V 19,000", c["kind"] == "lump_v" and c["q_est"] == 15 and abs(c["V_new"] - 19000) < 0.01, str(c))

# ───────────────────────────── T8: 승인·재감지 안전 / 유효기간 / 자동 재시도 ─────────────────────────────
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos, log, 76.69)
R._CTX["detect"] = {"snap": {}, "case": dict(pos["acct_case"], dC=99.0)}      # 이번 실행 재감지가 다르다고 가정
pos2, msg = bot.apply_command(pos, "/예 1", 76.69)
check("T8 재감지 불일치 → 집행 보류·approved 기록", pos2["acct_case"].get("approved") and pos2["pool"] == 11651 and "보류" in msg, msg)
log.clear(); pos3 = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos2, log, 76.69)
check("T8 다음 실행 같은 내용 → 자동 집행(Pool 11,719.16)", abs(pos3["pool"] - 11719.16) < 0.005 and "acct_case" not in pos3 and "반영" in log.text(), log.text()[:150])
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos, log, 76.69)
pos["acct_case"]["opened"] = "2026-09-01"                                     # 8일 이상 지난 건
log.clear(); pos = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos, log, 76.69)
check("T8 유효기간 7일 경과 → 새 건번호 #2로 계속 질문", pos["acct_case"]["id"] == 2 and pos["acct_case"]["asked"] == 1 and "[건 #2]" in log.text(), log.text()[:120])
log.clear(); pos = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos, log, 76.69)
check("T8 답 없으면 같은 건 반복(재질문 2회차)", pos["acct_case"]["id"] == 2 and pos["acct_case"]["asked"] == 2 and "재질문 2회차" in log.text(), log.text()[:120])

# ───────────────────────────── T11: 잔돈 문턱·경고 ─────────────────────────────
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 11651 + 4.99, 76.69), pos, log, 76.69)
check("T11 현금 차이 $4.99(<$5) → 변동 없음", "acct_case" not in pos and log.text() == "", log.text())
log = Log(); pos = R._acct_detect(FakeBroker(652, 11651.0, 76.69, krw=750000), ledger(652, 11651, 52170), log, 76.69)
check("T11 원화 75만 원 → 환전 안내", "환전" in log.text(), log.text())

# ───────────────────────────── DRY: 미리보기만 ─────────────────────────────
R.DRY_RUN = True
pos = ledger(652, 11651, 52170); log = Log()
pos = R._acct_detect(FakeBroker(652, 11719.16, 76.69), pos, log, 76.69)
check("DRY 감지 미리보기·건 저장 없음", "[DRY]" in log.text() and "acct_case" not in pos and "/예 " not in log.text(), log.text())
R.DRY_RUN = False

# ───────────────────────────── T2 구조: 감지 위치 = 체결동기화 뒤·명령 처리 앞 ─────────────────────────────
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vr_auto_runner_toss.py"), encoding="utf-8").read()
i_sync = src.index("pos = auto.sync_fills(pos, since)"); i_det = src.index("pos = _acct_detect(broker, pos, notifier, price_hint)")
i_cmd = src.index("pos, cmd_results = bot.process_commands(pos, price_hint, V_tmp * scale)")
check("T2 순서: sync_fills → _acct_detect → process_commands", i_sync < i_det < i_cmd)
check("T1 현금 필드: cashBuyingPower + 대기 매수 증거금 역산(코드 확인)", "cash_bp + reserve" in src)

print(f"\n합계: PASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL: print("FAIL 목록:", FAIL)
