# -*- coding: utf-8 -*-
"""
무한매수법 V4.0 계산·제안형 텔레그램 봇 (mume_v4_bot.py) — 완전 독립 실행
════════════════════════════════════════════════════════════════════════
⚠ 개인 실행 전용(라오어 방법론 재가공·외부 배포 금지). private 리포 유지.
자동 주문 없음 — 주문표를 '제안'만 하고, 실제 주문은 사용자가 수동으로 넣는다.

■ 하루 흐름 (GitHub Actions 크론, 미국장 마감 후 KST 아침):
  ① state.json 로드 → ② 텔레그램 명령 수거(/set 등) → ③ OHLC 수집(yfinance)
  ④ 어제 제안 주문 vs 실제 종가/고가로 체결 '추정' → update_state 반영
  ⑤ 오늘의 주문표 계산(suggest_orders) → ⑥ 텔레그램 발송 → ⑦ state 저장(커밋)

■ 체결 추정 규칙(방법론 그대로):
  매수 LOC P: 종가 ≤ P → 종가에 체결 / 매도 LOC P: 종가 ≥ P → 종가에 체결
  지정가 매도 P: 고가 ≥ P → P에 체결 / MOC: 무조건 종가 체결
  ※ 추정과 실제가 다르면 /set 으로 정정 (T 최종 판단은 사용자 — 라오어 원칙)

■ 텔레그램 명령:
  /status                      현재 상태
  /set t 5.5                   T값 정정 (avg·shares·balance·seed 동일)
  /restart 20000               사이클 종료 후 새 시드로 재시작 (복리/단리는 금액으로 표현)
  /pause  /resume              제안 일시중지/재개
════════════════════════════════════════════════════════════════════════
환경변수: MUME_TG_TOKEN, MUME_TG_CHAT (필수) | MUME_TICKER, MUME_SPLIT, MUME_SEED(초기 1회)
"""
import os, sys, json, datetime, hashlib
from typing import List, Optional
import requests

from mume_v4_core import State, Order, suggest_orders, star_price, star_pct, unit_amount, is_first_half, _round2
from mume_v4_state import Fill, update_state, start_new_cycle
try:
    from mume_v4_broker import load_adapter, reconcile, submit_orders, loc_submit_allowed
except Exception:
    load_adapter = None   # 어댑터 파일 없으면 종가 추정 모드로만 동작

# ══════════════ 설정 ══════════════
TICKER   = os.environ.get("MUME_TICKER", "TQQQ")          # TQQQ / SOXL
SPLIT    = int(os.environ.get("MUME_SPLIT", "40"))        # 20 / 40
SEED0    = float(os.environ.get("MUME_SEED", "20000"))    # 최초 부트스트랩 시드
STATE_FILE = os.environ.get("MUME_STATE", "mume_state.json")
TG_TOKEN = os.environ.get("MUME_TG_TOKEN", "")
TG_CHAT  = os.environ.get("MUME_TG_CHAT", "")
DRY_RUN  = os.environ.get("MUME_DRY", "0") == "1"          # 1=발송 대신 stdout
# VOLTGT A (백테스트로 8개 시작일 전부 MDD·샤프 개선 확인 → 채택)
VOLTGT_ON     = os.environ.get("MUME_VOLTGT", "1") == "1"   # 1=켬(기본)
VOLTGT_TARGET = float(os.environ.get("MUME_VOLTGT_TARGET", "0.60"))
VOLTGT_LOOKBACK = int(os.environ.get("MUME_VOLTGT_LOOKBACK", "20"))
KST = datetime.timezone(datetime.timedelta(hours=9))

# ══════════════ 상태 저장/복원 ══════════════
def _default_state() -> dict:
    return {"ticker": TICKER, "split": SPLIT, "seed": SEED0, "balance": SEED0,
            "shares": 0, "avg": 0.0, "T": 0.0, "mode": "normal", "rev_first": False,
            "closes": [], "last_date": None, "pending_orders": [],
            "tg_offset": 0, "paused": False, "await_restart": False,
            "approved_date": None, "submitted": {}}

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return _default_state()

def save_state(d: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def to_State(d: dict) -> State:
    return State(d["ticker"], d["split"], d["seed"], d["balance"], d["shares"],
                 d["avg"], d["T"], mode=d["mode"], rev_first=d["rev_first"],
                 prev_close=(d["closes"][-1] if d["closes"] else None),
                 close5_avg=(_round2(sum(d["closes"][-5:]) / 5) if len(d["closes"]) >= 5 else None),
                 closes=list(d["closes"]))

def from_State(st: State, d: dict):
    d.update({"seed": st.seed, "balance": st.balance, "shares": st.shares,
              "avg": st.avg, "T": st.T, "mode": st.mode, "rev_first": st.rev_first,
              "closes": list(st.closes or [])[-30:]})

def _ohash(orders_json: list) -> str:
    """주문표 스냅샷 해시 — /ok 승인 시점과 제출 시점의 주문표 동일성 보장."""
    return hashlib.md5(json.dumps(orders_json, sort_keys=True).encode()).hexdigest()[:12]

def voltgt_scale(closes: list) -> float:
    """VOLTGT A: RV = 최근 LOOKBACK일 수익률 std × √252 (실 TQQQ 가격 기준).
    scale = min(1, TARGET/RV). 변동성 높을 때 1회매수금 축소. 데이터 부족 시 1.0."""
    if not VOLTGT_ON or len(closes) < VOLTGT_LOOKBACK + 1:
        return 1.0
    import math
    px = closes[-(VOLTGT_LOOKBACK + 1):]
    rets = [(px[i] / px[i - 1] - 1.0) for i in range(1, len(px))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    rv = math.sqrt(var) * math.sqrt(252)
    if rv <= 0:
        return 1.0
    return min(1.0, VOLTGT_TARGET / rv)

def orders_to_json(orders: List[Order]) -> list:
    return [{"side": o.side, "kind": o.kind, "price": o.price, "qty": o.qty,
             "tag": o.tag, "role": o.role} for o in orders]

# ══════════════ 시세 ══════════════
def fetch_ohlc(ticker: str):
    """최근 15거래일 OHLC. 반환: list of (date_str, open, high, low, close)."""
    import yfinance as yf
    df = yf.download(ticker, period="3mo", auto_adjust=True, progress=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    out = []
    for idx, row in df.tail(35).iterrows():
        out.append((idx.strftime("%Y-%m-%d"), float(row["Open"]), float(row["High"]),
                    float(row["Low"]), float(row["Close"])))
    return out

# ══════════════ 체결 추정 ══════════════
def infer_fills(pending: list, high: float, close: float) -> List[Fill]:
    fills: List[Fill] = []
    for o in pending:
        role, side, kind, price, qty = o["role"], o["side"], o["kind"], o["price"], o["qty"]
        if qty <= 0:
            continue
        if kind == "MOC":
            fills.append(Fill(role, close, qty))
        elif side == "buy":                        # LOC 매수: 종가 ≤ 지정가 → 종가 체결
            if price is not None and close <= price:
                fills.append(Fill(role, close, qty))
        elif kind == "LOC":                        # LOC 매도: 종가 ≥ 지정가 → 종가 체결
            if price is not None and close >= price:
                fills.append(Fill(role, close, qty))
        else:                                      # 지정가 매도: 고가 ≥ 지정가 → 지정가 체결
            if price is not None and high >= price:
                fills.append(Fill(role, price, qty))
    return fills

# ══════════════ 텔레그램 ══════════════
def tg_send(text: str):
    if DRY_RUN or not TG_TOKEN:
        print("─" * 46 + "\n[텔레그램 발송(DRY)]\n" + text + "\n" + "─" * 46)
        return
    # 텔레그램 한도 4096자 — 줄 단위 분할 발송 + 실패 체크
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur); cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    chunks.append(cur)
    for i, ch in enumerate(chunks):
        try:
            r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                              json={"chat_id": TG_CHAT,
                                    "text": ch if len(chunks) == 1 else f"({i+1}/{len(chunks)})\n{ch}"},
                              timeout=20)
            if r.status_code != 200:
                print(f"[tg_send 실패 {r.status_code}] {r.text[:120]}")
        except Exception as e:
            print(f"[tg_send 예외] {e}")

def tg_poll(offset: int):
    """미처리 명령 수거. 반환: (texts, new_offset)."""
    if DRY_RUN or not TG_TOKEN:
        return [], offset
    try:
        r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                         params={"offset": offset + 1, "timeout": 0}, timeout=20).json()
        texts, new_off = [], offset
        for u in r.get("result", []):
            new_off = max(new_off, u["update_id"])
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id", "")) == str(TG_CHAT) and msg.get("text"):
                texts.append(msg["text"].strip())
        return texts, new_off
    except Exception:
        return [], offset

def apply_commands(d: dict, texts: List[str]) -> List[str]:
    notes = []
    for t in texts:
        low = t.lower()
        try:
            if low.startswith("/set"):
                _, key, val = t.split(None, 2)
                key = key.lower()
                m = {"t": "T", "avg": "avg", "shares": "shares",
                     "balance": "balance", "seed": "seed"}
                if key in m:
                    d[m[key]] = int(float(val)) if key == "shares" else float(val)
                    notes.append(f"✏ /set {key} = {val} 적용")
            elif low.startswith("/restart"):
                seed = float(t.split()[1])
                st = to_State(d); start_new_cycle(st, seed); from_State(st, d)
                d["await_restart"] = False; d["pending_orders"] = []
                notes.append(f"🔄 새 사이클 시작 (시드 ${seed:,.2f})")
            elif low.startswith("/ok"):
                d["approved_date"] = datetime.datetime.now(KST).strftime("%Y-%m-%d")
                d["approved_hash"] = d.get("pending_hash")
                notes.append("✅ 주문표 승인 — 다음 실행에서 제출")
            elif low.startswith("/no"):
                d["approved_date"] = None; d["pending_orders"] = []
                notes.append("🚫 주문표 반려 — 오늘 미제출")
            elif low.startswith("/pause"):
                d["paused"] = True; notes.append("⏸ 일시중지")
            elif low.startswith("/resume"):
                d["paused"] = False; notes.append("▶ 재개")
            elif low.startswith("/status"):
                notes.append("ℹ 상태는 아래 참조")
        except Exception as e:
            notes.append(f"⚠ 명령 해석 실패: {t} ({e})")
    return notes

# ══════════════ 메시지 ══════════════
def fmt_orders(orders: List[Order]) -> str:
    buys = [o for o in orders if o.side == "buy"]
    sells = [o for o in orders if o.side == "sell"]
    L = []
    if buys:
        L.append(" [매수]")
        L += [f"  {o.kind} ${o.price:.2f} × {o.qty}주 ({o.tag})" if o.price is not None
              else f"  MOC × {o.qty}주 ({o.tag})" for o in buys]
    if sells:
        L.append(" [매도]")
        L += [f"  {o.kind} ${o.price:.2f} × {o.qty}주 ({o.tag})" if o.price is not None
              else f"  MOC × {o.qty}주 ({o.tag})" for o in sells]
    return "\n".join(L) if L else " (제안 주문 없음)"

def fmt_state(st: State) -> str:
    if st.mode == "reverse":
        phase = "리버스" + ("(첫날)" if st.rev_first else "")
    else:
        phase = "일반·" + ("전반전" if is_first_half(st) else "후반전")
    sp = f"별% {star_pct(st)*100:+.2f}% 별지점 ${star_price(st):.2f}" if st.shares > 0 else ""
    return (f" 모드 {phase} | T {st.T:.3f} | 평단 ${st.avg:.2f} | 보유 {st.shares}주\n"
            f" 잔금 ${st.balance:,.2f} / 시드 ${st.seed:,.2f}  {sp}")

# ══════════════ 메인 ══════════════
def run_daily(mock_ohlc=None):
    d = load_state()
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d(%a)")
    header = f"📊 무매 V4 [{d['ticker']}·{d['split']}분할] {today}"
    lines = [header]

    # ① 텔레그램 명령 반영
    texts, d["tg_offset"] = tg_poll(d.get("tg_offset", 0))
    notes = apply_commands(d, texts)
    if notes:
        lines += ["── 명령 처리"] + [" " + n for n in notes]

    # ② 시세
    try:
        ohlc = mock_ohlc if mock_ohlc is not None else fetch_ohlc(d["ticker"])
    except Exception as e:
        tg_send(header + f"\n⚠ 시세 수집 실패: {str(e)[:80]}\n상태 변경 없음."); save_state(d); return

    # ③ 새 거래일 체결 추정 → 상태 갱신
    new_days = [r for r in ohlc if d["last_date"] is None or r[0] > d["last_date"]]
    if d["last_date"] is None and new_days:
        # 최초 부트스트랩: 종가 이력만 적재(체결 추정 없음)
        for r in new_days:
            d["closes"] = (d["closes"] + [r[4]])[-30:]
        d["last_date"] = new_days[-1][0]
        lines.append(f"── 부트스트랩: 종가 이력 {len(new_days)}일 적재 (최근 ${new_days[-1][4]:.2f})")
    elif new_days:
        st = to_State(d)
        adapter = load_adapter() if load_adapter else None
        first = True
        for (date, _o, high, _l, close) in new_days:
            fills = []
            if first:
                if adapter is not None:
                    try:
                        fills, pos, cash, blogs = reconcile(
                            adapter, d["ticker"], d.get("pending_orders", []),
                            d.get("submitted", {}), date)
                        lines.append(f"── {date} 실체결 정산 [{adapter.name}]")
                        lines += blogs if blogs else ["  · 체결 없음"]
                    except Exception as e:
                        lines.append(f"── {date} ⚠ 브로커 조회 실패({str(e)[:60]}) → 종가 추정 폴백")
                        fills = infer_fills(d.get("pending_orders", []), high, close)
                        adapter = None
                else:
                    fills = infer_fills(d.get("pending_orders", []), high, close)
            res = update_state(st, fills, close)
            if first:
                if adapter is not None:
                    lines.append(f"  · T {res.t_before:.3f} → {res.t_after:.3f} (종가 ${close:.2f})")
                else:
                    lines.append(f"── {date} 체결 추정 (종가 ${close:.2f} / 고가 ${high:.2f})")
                    if fills:
                        for f in fills:
                            lines.append(f"  · {f.role} → {f.qty}주 @ ${f.price:.2f}")
                        lines.append(f"  · T {res.t_before:.3f} → {res.t_after:.3f}")
                    else:
                        lines.append("  · 체결 없음(추정)")
                    lines.append("  ※ 실제와 다르면 /set 으로 정정")
            for ev in res.events:
                lines.append(f"  🔔 {ev}")
                if "사이클종료" in ev:
                    d["await_restart"] = True
            first = False
        if len(new_days) > 1:
            lines.append(f"  ⚠ 누락 거래일 {len(new_days)-1}일 — 종가만 반영. 상태 확인 요망.")
        # 증권사 실측 보정: 평단·수량은 증권사가 정답(수수료 포함 실평단)
        if adapter is not None:
            try:
                diff = []
                if pos.shares and abs(pos.shares - st.shares) > 0:
                    diff.append(f"수량 {st.shares}→{int(pos.shares)}")
                    st.shares = int(pos.shares)
                if pos.avg_price and abs(pos.avg_price - st.avg) > 0.005:
                    diff.append(f"평단 ${st.avg:.2f}→${pos.avg_price:.2f}")
                    st.avg = float(pos.avg_price)
                if diff:
                    lines.append("  ✏ 증권사 실측 보정: " + ", ".join(diff))
            except Exception:
                pass
        from_State(st, d)
        d["last_date"] = new_days[-1][0]
        d["pending_orders"] = []
        if d.get("approved_date") and not d.get("submitted"):
            lines.append("ℹ 직전 승인(/ok)은 제출되지 않은 채 만료됨 — 오늘 주문표 확인 후 다시 /ok")
        d["approved_date"] = None; d["submitted"] = {}   # 새 거래일 → 승인·제출 기록 리셋

    # ④ 오늘의 주문 제안
    st = to_State(d)
    lines += ["── 현재 상태", fmt_state(st)]
    if d.get("paused"):
        lines.append("⏸ 일시중지 상태 — /resume 으로 재개")
    elif d.get("await_restart"):
        lines.append("🔔 사이클 종료 상태 — /restart <새시드> 로 재시작 (복리=잔금 전액, 단리=기존 시드)")
    else:
        # VOLTGT A: 변동성 높으면 1회매수금 축소(balance 임시 축소로 unit↓). 백테스터 A와 동일.
        scale = voltgt_scale(st.closes or [])
        vtag = ""
        if VOLTGT_ON:
            n_cl = len(st.closes or [])
            if n_cl < VOLTGT_LOOKBACK + 1:
                vtag = f" · VOLTGT 대기(이력 {n_cl}/{VOLTGT_LOOKBACK + 1})"
            elif scale < 1.0:
                vtag = f" · VOLTGT scale {scale:.2f}(RV↑ 매수축소)"
        if scale < 1.0:
            real_bal = st.balance
            st.balance = _round2(real_bal * scale)
            orders = suggest_orders(st)
            st.balance = real_bal
        else:
            orders = suggest_orders(st)
        oj = orders_to_json(orders)
        d["pending_orders"] = oj
        d["pending_hash"] = _ohash(oj)
        lines += ["── 오늘의 주문 제안 (LOC 예약 / 지정가는 프리장부터)" + vtag, fmt_orders(orders)]
        if st.mode == "reverse" and not st.rev_first and st.close5_avg is None:
            lines.append("⚠ 5일 종가 이력 부족 — 리버스 별지점 산출 불가(주문 없음). 다음 거래일 자동 해소.")
        today_kst = datetime.datetime.now(KST).strftime("%Y-%m-%d")
        adapter2 = load_adapter() if load_adapter else None
        if adapter2 is None:
            lines.append("· 브로커 미연결 — 위 주문표를 수동 입력")
        elif d.get("approved_date") == today_kst and d.get("approved_hash") != d.get("pending_hash"):
            d["approved_date"] = None
            lines.append("⛔ 승인 이후 주문표가 변경됨(/set 등) — 새 주문표 확인 후 다시 /ok")
        elif d.get("approved_date") == today_kst:
            sub, slogs = submit_orders(adapter2, d["ticker"], orders, st.balance,
                                       d.get("submitted", {}))
            d["submitted"] = sub
            lines += ["── 주문 제출 결과"] + [" " + s for s in slogs]
        else:
            ok, why = loc_submit_allowed(adapter2)
            lines.append(f"· 제출 대기 — 확인 후 /ok 로 승인 (KST 23:35 제출 전까지) ({'제출가능: ' if ok else '⛔ '}{why})")

    tg_send("\n".join(lines))
    save_state(d)

# ══════════════ 셀프테스트 (mock 3일 시나리오, 네트워크 불필요) ══════════════
def selftest():
    global STATE_FILE, DRY_RUN
    STATE_FILE = "/tmp/mume_state_test.json"
    DRY_RUN = True
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    base = [("2026-07-01", 45, 46, 44, 45.5), ("2026-07-02", 45, 46.5, 44.5, 45.93)]
    print("\n### Day0: 부트스트랩")
    run_daily(mock_ohlc=base)
    print("\n### Day1: 처음매수 체결 (종가 45.00)")
    run_daily(mock_ohlc=base + [("2026-07-03", 46, 46.2, 44.8, 45.00)])
    print("\n### Day2: 전반전 매수 체결 (종가 43.00)")
    run_daily(mock_ohlc=base + [("2026-07-03", 46, 46.2, 44.8, 45.00),
                                ("2026-07-06", 44, 44.5, 42.8, 43.00)])
    print("\n### Day3: 반등 — 별지점 0.5회 체결 예상 (종가 47.9, 쿼터매도 49.94 미달)")
    run_daily(mock_ohlc=base + [("2026-07-03", 46, 46.2, 44.8, 45.00),
                                ("2026-07-06", 44, 44.5, 42.8, 43.00),
                                ("2026-07-07", 44, 48.5, 43.9, 47.90)])
    d = json.load(open(STATE_FILE))
    print(f"\n### 최종 상태: T={d['T']:.3f} 평단=${d['avg']:.2f} 보유={d['shares']} 잔금=${d['balance']:.2f}")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run_daily()
