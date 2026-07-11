# -*- coding: utf-8 -*-
"""
무한매수법 V4.0 브로커 층 (mume_v4_broker.py) — VR 어댑터 재활용
════════════════════════════════════════════════════════════════════════
계좌 분담(경우 C): 봇 인스턴스마다 MUME_BROKER 하나 고정. 개인 실행 전용.

■ 브로커별 현재 상태 (2026-07 기준, 어댑터 헤더 근거):
  KIS   : 실전=진짜 LOC(34)·MOC(33)·예약주문(공식확인) ✅ / 모의=LOC 미지원(marketable 폴백)
  토스  : 전체 [승인후확정] — API 스펙 미검증 + place_order가 LOC를 marketable로 변환 ⚠
  키움  : 해외 API 2026-07-02 개시 직후, api-id 미확정(fail-fast 스텁)

■ ★ LOC 무결성 가드 (V4 생명선):
  V4 주문은 LOC(종가 체결)가 핵심. LOC를 marketable limit으로 변환하는 어댑터에
  제출하면 별지점 매수가 '즉시 체결'되는 재앙 → LOC 확정 지원 브로커에만 제출 허용.
    LOC_LIVE_OK = {"kis"(live)}          ← 현재 유일
    토스: LOC 지원 OpenAPI 확정 후 화이트리스트 추가
    키움: 해외 TR api-id 확정 후 추가
  연습: MUME_ALLOW_MOCK_LOC=1 이면 KIS 모의의 marketable 폴백을 '연습용'으로 허용(경고 표시).

■ 자동 정산(reconcile): 아침에 get_fills(전일)+get_holdings 조회 →
  실체결을 role로 매칭(update_state 입력) + 증권사 실평단·수량으로 상태 보정.
  role 매칭: ①자동제출분은 order_id 맵으로 확정 ②수동주문분은 side·수량·지정가로 추정,
  모호하면 '?'로 표시하고 사용자 /set 확인 요청.
════════════════════════════════════════════════════════════════════════
환경변수:
  MUME_BROKER = kis | toss | kiwoom
  KIS : MUME_KIS_APPKEY / MUME_KIS_SECRET / MUME_KIS_CANO / MUME_KIS_MOCK(1|0) / MUME_KIS_RESERVE(1|0)
  토스: MUME_TOSS_ID / MUME_TOSS_SECRET / MUME_TOSS_ACCOUNT
  키움: MUME_KW_APPKEY / MUME_KW_SECRET / MUME_KW_ACCOUNT
"""
from __future__ import annotations
import os, datetime
from typing import List, Tuple, Optional

from vr_broker_adapter import BrokerAdapter, OrderReq, Position
from mume_v4_core import Order
from mume_v4_state import Fill as MFill

KST = datetime.timezone(datetime.timedelta(hours=9))

# ══════════════ 어댑터 로더 ══════════════
def load_adapter() -> Optional[BrokerAdapter]:
    name = os.environ.get("MUME_BROKER", "").strip().lower()
    if not name:
        return None                                   # 브로커 미설정 → 종가 추정 모드
    if name == "kis":
        from vr_kis_adapter import KISAdapter
        return KISAdapter(os.environ["MUME_KIS_APPKEY"], os.environ["MUME_KIS_SECRET"],
                          os.environ["MUME_KIS_CANO"],
                          mock=os.environ.get("MUME_KIS_MOCK", "1") == "1",
                          use_reserve=os.environ.get("MUME_KIS_RESERVE", "0") == "1")
    if name == "toss":
        from vr_toss_adapter import TossAdapter
        return TossAdapter(os.environ["MUME_TOSS_ID"], os.environ["MUME_TOSS_SECRET"],
                           os.environ["MUME_TOSS_ACCOUNT"])
    if name == "kiwoom":
        from vr_kiwoom_adapter import KiwoomAdapter
        return KiwoomAdapter(os.environ["MUME_KW_APPKEY"], os.environ["MUME_KW_SECRET"],
                             os.environ["MUME_KW_ACCOUNT"])
    raise RuntimeError(f"알 수 없는 MUME_BROKER: {name}")

# ══════════════ ★ LOC 무결성 가드 ══════════════
def loc_submit_allowed(adapter: BrokerAdapter) -> Tuple[bool, str]:
    """이 어댑터에 LOC 주문 제출이 안전한가. (허용여부, 사유)."""
    n = adapter.name
    if n == "kis":
        mock = bool(getattr(adapter, "mock", True))
        if not mock:
            return True, "KIS 실전 — 진짜 LOC(34)/MOC(33) 지원 ✅"
        if os.environ.get("MUME_ALLOW_MOCK_LOC", "0") == "1":
            return True, "⚠ KIS 모의 — LOC가 marketable limit으로 폴백됨(연습 전용, 실전 금지)"
        return False, "KIS 모의는 LOC 미지원(marketable 폴백) — 연습 허용은 MUME_ALLOW_MOCK_LOC=1"
    if n == "toss":
        return False, "토스 API [승인후확정] + LOC→marketable 변환 위험 — LOC 지원 확정 전 제출 금지"
    if n == "kiwoom":
        return False, "키움 해외 api-id 미확정 — 연동 완료 후 허용"
    return False, f"미지원 브로커: {n}"

# ══════════════ 주문 변환 ══════════════
_KIND = {"LOC": "LOC", "지정가": "LIMIT", "MOC": "MOC"}

def to_order_req(symbol: str, o: Order) -> OrderReq:
    return OrderReq(symbol=symbol, side=o.side, qty=int(o.qty),
                    limit_price=float(o.price or 0.0),
                    validity="DAY", order_kind=_KIND.get(o.kind, "LIMIT"),
                    tag=o.role)

# ══════════════ /ok 게이트 제출 (멱등 + sanity + 건별 실패 보고) ══════════════
def submit_orders(adapter: BrokerAdapter, symbol: str, orders: List[Order],
                  balance: float, already: dict) -> Tuple[dict, List[str]]:
    """승인된 주문표 제출. already={order_key: order_id}(멱등). 반환 (갱신된 already, 로그)."""
    logs: List[str] = []
    ok, why = loc_submit_allowed(adapter)
    if not ok:
        return already, [f"⛔ 제출 차단: {why}"]
    logs.append(f"제출 경로: {adapter.name} — {why}")
    # sanity: 매수 총액 ≤ 잔금×1.02 (수수료 여유)
    buy_total = sum((o.price or 0) * o.qty for o in orders if o.side == "buy")
    if buy_total > balance * 1.02:
        return already, [f"⛔ sanity 실패: 매수총액 ${buy_total:,.2f} > 잔금 ${balance:,.2f} — 전체 미제출"]
    adapter.authenticate()
    for o in orders:
        key = f"{o.role}|{o.side}|{o.price}|{o.qty}"
        if key in already:
            logs.append(f"  ↷ 스킵(기제출): {o.tag}")
            continue
        if o.qty <= 0:
            continue
        try:
            oid = adapter.place_order(to_order_req(symbol, o))
            already[key] = {"order_id": oid, "role": o.role}
            logs.append(f"  ✅ {o.side}/{o.kind} ${o.price} × {o.qty} ({o.tag}) → #{oid}")
        except Exception as e:
            logs.append(f"  ❌ 실패: {o.tag} — {str(e)[:90]} (수동 처리 필요)")
    return already, logs

# ══════════════ 자동 정산 (조회 → role 매칭 → 상태 보정) ══════════════
def _match_role(f, pending: list, id_map: dict) -> str:
    """체결 1건의 role 판정. ①order_id 맵 ②지정가매도 price 일치 ③side·qty·지정가 조건 ④'?'"""
    for rec in id_map.values():
        if isinstance(rec, dict) and rec.get("order_id") == f.order_id:
            return rec["role"]
    cands = [p for p in pending if p["side"] == f.side and p.get("qty") == f.qty]
    if f.side == "sell":
        for p in pending:
            if p["role"] == "tp_sell" and p.get("price") and abs(f.price - p["price"]) < 0.011:
                return "tp_sell"                       # 지정가매도: 체결가=지정가
        if len(cands) == 1:
            return cands[0]["role"]
        # LOC매도(쿼터/리버스): 체결가(종가) ≥ 지정가 조건
        c2 = [p for p in cands if p.get("price") and f.price >= p["price"] - 0.011]
        return c2[0]["role"] if len(c2) == 1 else "?"
    # 매수: LOC 조건 = 체결가(종가) ≤ 지정가
    c2 = [p for p in pending if p["side"] == "buy" and p.get("price")
          and f.price <= p["price"] + 0.011]
    exact = [p for p in c2 if p.get("qty") == f.qty]
    if len(exact) == 1:
        return exact[0]["role"]
    if f.qty == 1 and any(p["role"] == "extra_buy" for p in c2):
        return "extra_buy"                             # 1주 체결은 사다리일 확률 높음
    return c2[0]["role"] if len(c2) == 1 else "?"

def reconcile(adapter: BrokerAdapter, symbol: str, pending: list,
              id_map: dict, since: str) -> Tuple[List[MFill], Position, float, List[str]]:
    """전일 실체결 조회→role 매칭 + 잔고 조회. 반환 (mume체결, 증권사포지션, 예수금, 로그)."""
    logs: List[str] = []
    adapter.authenticate()
    raw = adapter.get_fills(symbol, since)
    fills: List[MFill] = []
    for f in raw:
        role = _match_role(f, pending, id_map)
        if role == "?":
            logs.append(f"  ⚠ role 모호: {f.side} {f.qty}주 @${f.price:.2f} — 반영 보류, /set 확인 요망")
            continue
        fills.append(MFill(role, f.price, int(f.qty)))
        logs.append(f"  · {role}: {f.qty}주 @${f.price:.2f} (수수료 ${f.fee:.2f})")
    pos = adapter.get_holdings(symbol)
    cash = adapter.get_cash_usd()
    return fills, pos, cash, logs
