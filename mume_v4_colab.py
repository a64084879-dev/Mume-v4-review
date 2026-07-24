# -*- coding: utf-8 -*-
"""
vr_broker_adapter.py — VR 사다리 자동매매 '증권사 어댑터' (fable5 9개 항목 반영)
════════════════════════════════════════════════════════════════════════
목적: vr_signal_bot.py의 사다리 계산을 증권사 API로 '자동 실행'.
설계: 어댑터 패턴 — 봇 공통 로직은 증권사 무관, API 호출만 Adapter에 격리.

⚠️⚠️ 미확인 경고 (fable5 #4) ⚠️⚠️
   아래 토스 API 엔드포인트·헤더·필드명·레이트리밋·"SINGLE 개수제한 없음" 전부
   검색 기반 추정이며 공식 OpenAPI JSON으로 교차검증 안 됨.
   승인 후 developers.tossinvest.com OpenAPI JSON과 전수 대조 전까지 [미확인],
   실거래 금지. 특히 '조건주문' 발동 시 시장가/지정가 여부는 필수 확인.

fable5 9개 반영:
  ① sync_fills 멱등성 — order_id 파일 누적, 재실행 시 스킵.
  ② 자기주문 이중차감 방지 — 포지션 변경 단일 진실원 = sync_fills.
  ③ AUTO_MODE 시 수동 명령 거부(봇 쪽, 여기선 플래그 제공).
  ④ 수수료 반영 + 계좌 USD 잔고와 Pool 리컨실.
  ⑤ 대피 = marketable limit(현재가×0.90, 시가 근처). 헤더 옛 "익일 LOC"는 낡음-실제 275행.
  ⑥ rotate_cycle CASH 가드.
  ⑦ 주문 건별 try/except + 실패 텔레그램 보고, 진입은 cancel-first.
  ⑧ 유효기간 enum(DAY/1WEEK/1MONTH/GTC)이면 '14일' 불가 → 1MONTH+cancel_all.
  ⑨ 모든 배치·취소·체결·오류를 _tg()로 알림.
권고 일일순서: 러너는 rollover(봇 main)->daily_run 순. daily_run 내부는
  sync_fills->reconcile(2b/2c 선행)->킬스위치->복귀->rotate_cycle->리포트.
  헤더 옛 "sync->rollover"는 봇 확정순서와 상충-이 서술이 정정본.
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable
import os, time, datetime   # [fable5] json·FILLS_SEEN_PATH 데드코드 제거(fills_seen은 pos 내장)


def _kst_today():
    """★KST 기준 오늘(2026-07-24). 종전 datetime.date.today()는 서버 로컬(=UTC)이라
       KST보다 하루 이르게 찍혔다(07:30 KST 크론 = 22:30 UTC 전일). 그러면
       last_recover_check 소급창이 1일 넓어져 대피 확정 당일 월말이 복귀 후보로 재포함되는 등
       봇(KST)·백테스터와 어긋난다. 어댑터의 모든 날짜 스탬프를 이 함수로 통일한다."""
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=9)).date().isoformat()


@dataclass
class OrderReq:
    symbol: str
    side: str                   # "buy"|"sell"
    qty: int
    limit_price: float
    validity: str = "1MONTH"    # ⑧ DAY/1WEEK/1MONTH/GTC [미확인]
    order_kind: str = "LIMIT"   # LIMIT|LOC|MARKET
    tag: str = ""

@dataclass
class Fill:
    symbol: str; side: str; qty: int; price: float
    fee: float; order_id: str; filled_at: str

@dataclass
class Position:
    symbol: str; shares: float; avg_price: float = 0.0

class BrokerAdapter(ABC):
    name = "abstract"
    max_validity = "1MONTH"    # 유효기간 상한(추상 기본). KIS=DAY, 토스=DAY(조건주문 확정 전).
                               #   DAY-only면 daily_run이 매일 cancel_all+재배치.
                               #   [fable5] 토스도 현재 DAY 확정 → 1MONTH 마커 문제 자동해소.
    @abstractmethod
    def authenticate(self) -> None: ...
    @abstractmethod
    def get_holdings(self, symbol: str) -> Position: ...
    @abstractmethod
    def get_cash_usd(self) -> float: ...
    @abstractmethod
    def get_price(self, symbol: str) -> float: ...
    @abstractmethod
    def place_order(self, req: OrderReq) -> str: ...
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str = "", qty=None) -> bool: ...
    @abstractmethod
    def list_open_orders(self, symbol: str) -> list: ...
    @abstractmethod
    def get_fills(self, symbol: str, since: str) -> list: ...

    def cancel_all(self, symbol: str) -> int:
        # [주요2 수정] 건별 예외를 삼키지 않고, 실패가 하나라도 있으면 예외 전파.
        #   호출측(rotate)이 '취소 완료'로 오인해 이중 사다리 얹는 것 방지.
        #   [🔴 fable5] qty 전달: KIS 정규취소는 실수량 필수(None이면 KISError). o["qty"] 넘김.
        #   계단식 폴백: (id,symbol,qty) -> (id,symbol) -> (id). 서드파티/구시그니처 어댑터 호환.
        #   [fable5] 현재 KIS·토스·키움 모두 3인자 → 폴백은 외부 어댑터 대비용(인용례 정정).
        n=0; fails=[]
        for o in self.list_open_orders(symbol):   # list 실패 시 여기서 예외 전파됨
            oid=o["order_id"]; q=o.get("qty")
            try:
                res=self._cancel_one(oid, symbol, q)
                if res: n+=1
            except Exception as e:
                fails.append((oid, str(e)))
        if fails:
            raise RuntimeError(f"취소 {len(fails)}건 실패: {fails[:3]}")
        return n

    def _cancel_one(self, oid, symbol, qty):
        # 계단식 시그니처 폴백(TypeError만 흡수, 실제 취소 오류는 전파).
        try:
            return self.cancel_order(oid, symbol, qty)
        except TypeError:
            pass
        try:
            return self.cancel_order(oid, symbol)
        except TypeError:
            pass
        return self.cancel_order(oid)


# TossAdapter는 vr_toss_adapter.py로 분리(KIS와 대칭). 아래는 미구현 스텁.
class KiwoomAdapter(BrokerAdapter):
    name="kiwoom"; BASE="https://openapi.kiwoom.com"   # [미확인]
    def __init__(self, app_key, app_secret, account_no):
        self.ak=app_key; self.asec=app_secret; self.account=account_no
    def authenticate(self): raise NotImplementedError("키움 미구현 — 우대 만료 후")
    def get_holdings(self,s): raise NotImplementedError
    def get_cash_usd(self): raise NotImplementedError
    def get_price(self,s): raise NotImplementedError
    def place_order(self,r): raise NotImplementedError
    def cancel_order(self,i,symbol=""): raise NotImplementedError
    def list_open_orders(self,s): raise NotImplementedError
    def get_fills(self,s,since): raise NotImplementedError


class LadderAutomator:
    """사다리 자동화. fable5 치명1·2 + 주요1~5 반영.
       핵심 원칙: '실패했는데 성공한 척' 절대 금지(무음실패 차단)."""
    def __init__(self, broker, symbol="TQQQ", dry_run=True, notify=None):
        self.broker=broker; self.symbol=symbol; self.dry_run=dry_run
        self._notify=notify or (lambda m: print(f"[TG] {m}"))
    def _tg(self, msg):
        try: self._notify(msg)
        except Exception: print(f"[TG-FAIL] {msg}")

    # ── ①③ 멱등 체결동기화: seen을 pos["fills_seen"]에 통합(주요3 원자저장) ──
    #    키=날짜:ODNO, 값=반영수량(부분체결 델타 대비, 주요보완). 포지션 변경 단일 진실원(②).
    def sync_fills(self, pos, since):
        if self.dry_run:
            self._tg("[DRY] 체결동기화 스킵"); return pos
        fills=self.broker.get_fills(self.symbol,since)   # 실패 시 예외 전파(무음실패 차단)
        seen=pos.setdefault("fills_seen",{})             # {날짜:ODNO -> 반영수량}
        applied=0; buy_applied=False   # [fable5] '이번 sync에 반영된' 매수 추적(만료해제 판정용)
        for f in fills:
            # [fable5] dedup 키에 side 포함 — 같은 (filled_at:order_id)로 매수·매도가 오면
            #   키 충돌로 한쪽이 덮여 delta 오염. side 분리로 방지.
            key=f"{f.filled_at}:{f.order_id}:{f.side}"
            # [fable5 하위호환] 구키(날짜:ID)로 이미 반영된 체결이 5일 조회창에 남은 채 이 버전으로
            #   갈아타면 신키에서 prev=0 → delta 전량 재적용(shares 이중반영·허위 INVESTED 실증).
            #   구키를 기반영으로 인정해 이 마이그레이션 사고 클래스 소멸.
            done=seen.get(key, seen.get(f"{f.filled_at}:{f.order_id}",0))
            delta=f.qty-done                              # 부분체결 누적 대비 델타만 반영
            if delta<=0: continue
            cost=delta*f.price
            # 수수료는 델타 비율로 안분
            fee=f.fee*(delta/f.qty) if f.qty else 0.0
            if f.side=="buy":
                pos["shares"]=pos.get("shares",0.0)+delta
                pos["pool"]=pos.get("pool",0.0)-cost-fee
                pos["cyc_used"]=pos.get("cyc_used",0.0)+cost
                buy_applied=True
            elif f.side=="sell":
                pos["shares"]=pos.get("shares",0.0)-delta
                pos["pool"]=pos.get("pool",0.0)+cost-fee
            seen[key]=f.qty; applied+=1
            self._tg(f"✅ 체결반영: {f.side} {delta}주 @ {f.price:.2f} (수수료 {fee:.2f})")
        # 프루닝: since 이전(오래된) 키 제거로 무한증가 방지(보완)
        cutoff=since.replace("-","")
        for k in list(seen.keys()):
            kd=k.split(":")[0].replace("-","")
            if kd and kd<cutoff: del seen[k]
        # [🔴1 pending 소비] 킬스위치 매도 체결로 shares≈0 확인되면 CASH 확정.
        if pos.get("evac_pending") and pos.get("shares",0.0)<=0.5:
            pos["state"]="CASH"; pos.pop("evac_pending",None)
            # [🔴 휩소방지] 자동대피 CASH확정 시 복귀 소급판정 기준일을 오늘로 → 대피 이전
            #   멀쩡했던 월말들을 복귀조건으로 오판해 당일 재매수하는 휩소 차단(봇 /exit와 동일).
            # ★K-B 정합(2026-07-24): 봇 /exit처럼 '대피 판정일'(evac_sig_date)을 우선 사용한다.
            #   집행·확정일로 찍으면 판정~확정 사이 월말이 소급창에서 빠져 복귀가 최대 한 달 지연된다.
            #   7일 신선도 가드 + pop(재사용 차단)도 봇과 동일.
            _esd = pos.pop("evac_sig_date", None); _stamp = _kst_today()
            if _esd:
                try:
                    _d0 = datetime.date.fromisoformat(str(_esd))
                    _d1 = datetime.date.fromisoformat(_stamp)
                    if 0 <= (_d1 - _d0).days <= 7: _stamp = str(_esd)
                except Exception: pass
            pos["last_recover_check"]=_stamp
            self._tg("🔵 매도 전량체결 확인 — CASH 확정")
        # 복귀 매수 체결로 shares>0 되면 INVESTED 확정.
        if pos.get("recover_pending") and pos.get("shares",0.0)>0.5:
            pos["state"]="INVESTED"; pos.pop("recover_pending",None)
            pos.pop("recover_retry",None)   # [🔴 fable5] 복귀 완료 → retry 잔존 제거(대피 재매수 씨앗 차단)
            pos.pop("cyc_budget",None); pos.pop("cyc_used",None); pos.pop("ladder_placed_for",None)   # [봇 N1 미러] 복귀 직후 매수한도 리셋 + 래치 해제 → 다음 사다리는 봇 compute_ladder가 pool*BUY_LIMIT 자체계산(봇 /enter와 동일값). 같은사이클 대피/복귀 후 무주문 방지(치명B)
            self._tg("🟢 복귀 매수체결 확인 — INVESTED 확정")
        # [🟠 만료해소] 접수 성공했으나 미체결로 DAY 만료 시 pending 영구고착 방지.
        #   판정: pending이 '전일 이전 날짜' 또는 불리언(구형식 stale)이고 이번 sync에서 매수 미체결.
        #   DAY 유효기간상 전일 주문은 확실히 소멸 → 해제하면 신호 재발화·2c가 자연 재시도.
        #   당일 세팅분은 절대 해제 안 함(10:10 접수→23:30 체결→익일 sync 정상경로).
        rp=pos.get("recover_pending")
        if rp and pos.get("shares",0.0)<=0.5:   # 아직 CASH(매수 미체결)
            today=_kst_today()
            # [fable5] 조회창(5일) 전체가 아니라 '이번 sync 반영' 매수만 — 옛 매수체결이 창에
            #   남아있으면 해제가 최대 5일 지연되던 것 정밀화.
            buy_filled=buy_applied
            stale = (rp is True) or (isinstance(rp,str) and rp<today)
            if stale and not buy_filled:
                pos.pop("recover_pending",None)
                self._tg("⚠️ 복귀주문 미체결 만료(DAY 소멸) — pending 해제, 신호 재발화 시 재시도")
        return pos   # 저장은 호출측(daily_run)에서 pos 통째로(원자적)

    # ── ② 리컨실: 주수 대조(본선) + 현금은 정보성(주요: ord_psbl 개념오류) ──
    def reconcile(self, pos):
        if self.dry_run: return True
        real=self.broker.get_holdings(self.symbol).shares  # 실패 시 예외 전파
        if abs(real-pos.get("shares",0.0))>0.5:
            self._tg(f"🚨 포지션 불일치! 봇 {pos.get('shares',0)}주 vs 실보유 {real}주 — 자동매매 중단")
            return False
        # 현금: ord_psbl_frcr_amt는 증거금 차감분이라 Pool과 직접 비교 불가 → 정보성 로그만
        try:
            time.sleep(0.3)   # 조회 레이트리밋 대비(보완)
            rc=self.broker.get_cash_usd()
            self._tg(f"ℹ️ 주문가능액 {rc:.0f} (Pool {pos.get('pool',0):.0f}, 미체결 증거금 차감분이라 참고용)")
        except Exception as e:
            self._tg(f"ℹ️ 주문가능액 조회 생략: {e}")
        return True

    # ── ⑦ 사다리 배치(건별 try + 실패보고) ──
    def _place_ladder(self, buy_l, sell_l, lot, validity, strt_dt=None, end_dt=None, sell_lot=None):
        # ★lot 분리(2026-07-24): 봇이 매수/매도 lot을 따로 산출한다(매도가 굵어도 매수는 촘촘히).
        #   sell_lot 미전달이면 종전처럼 lot 공용(하위호환).
        _sl = int(sell_lot) if sell_lot else int(lot)
        ids,fails=[],[]
        use_rsv = getattr(self.broker, "uses_reservation", False)   # 키움=True(예약), KIS/토스=False(정규)
        def one(side,pt):
            _q = _sl if side=="sell" else int(lot)
            if self.dry_run:
                _m = f"예약 {strt_dt}~{end_dt}" if use_rsv else f"{validity}"
                self._tg(f"[DRY] {side} {_q}주 @ {round(pt,2)} ({_m})"); return None
            if use_rsv:
                # ★예약경로: 사다리 각 칸 = 기간예약 잔량주문(지정가). 기간=사이클 cyc_start~cyc_next.
                #   책 예시(매수점=최소밴드/n, 매도점=최대밴드/n)를 2주 지정가 예약으로 게시.
                return self.broker.place_ladder_reserve(side, self.symbol, _q, round(pt,2), strt_dt, end_dt)
            req=OrderReq(self.symbol,side,_q,round(pt,2),validity,"LIMIT",f"ladder_{side}")
            return self.broker.place_order(req)
        for pt,*_ in buy_l:
            try:
                oid=one("buy",pt)
                if oid: ids.append(oid)
            except Exception as e: fails.append(("buy",pt,str(e)))
        for pt,*_ in sell_l:
            try:
                oid=one("sell",pt)
                if oid: ids.append(oid)
            except Exception as e: fails.append(("sell",pt,str(e)))
        if fails:
            # ★[2026-07-18] 실패 '이유'를 첫 건에 한해 표시 — 진단용.
            #   기존엔 side@price만 찍혀 8005인지 장시간·권한·파라미터인지 구분 불가.
            _why = fails[0][2] if fails and len(fails[0]) > 2 else ""
            self._tg(f"🚨 사다리 배치 {len(fails)}건 실패: "
                     + ", ".join(f"{s}@{p:.2f}" for s,p,_ in fails[:5])
                     + (f"\n   └ 사유(첫건): {_why[:180]}" if _why else ""))
        return ids,fails

    # ── ⑥⑦ 사이클 갱신: CASH가드 + cancel-first + 취소후 0건 재확인(주요2) ──
    def rotate_cycle(self, pos, buy_l, sell_l, lot, validity=None, strt_dt=None, end_dt=None, sell_lot=None):
        if pos.get("state")=="CASH":
            self._tg("ℹ️ CASH 상태 — 사다리 배치 스킵"); return []
        use_rsv = getattr(self.broker, "uses_reservation", False)
        validity = validity or getattr(self.broker,"max_validity","1MONTH")
        if self.dry_run:
            self._tg("[DRY] 기존주문 전량취소")
        else:
            # ★cancel-first: 새 예약 걸기 전 옛 예약을 먼저 전량 취소(개장 시 이중 매수·예수금 이중잠금 방지).
            try:
                if use_rsv:
                    c=self.broker.cancel_all_reservations(self.symbol); self._tg(f"🔄 기존 예약 {c}건 취소")
                else:
                    c=self.broker.cancel_all(self.symbol); self._tg(f"🔄 기존 {c}건 취소")
            except Exception as e:
                self._tg(f"🚨 취소 실패 — 배치 중단(이중사다리 방지): {e}"); return []
            # [주요2] 취소 후 0건 재확인. 잔존 시 배치 중단(예약은 예약목록, 정규는 미체결목록으로 확인).
            try:
                rem = self.broker.list_reservations(self.symbol) if use_rsv else self.broker.list_open_orders(self.symbol)
                if rem:
                    self._tg(f"🚨 취소 후에도 {len(rem)}건 잔존 — 배치 중단(이중사다리 방지)"); return []
            except Exception as e:
                self._tg(f"🚨 잔존확인 실패 — 배치 중단: {e}"); return []
        ids,fails=self._place_ladder(buy_l,sell_l,lot,validity,strt_dt,end_dt,sell_lot=sell_lot)
        # ★[예약 공백 방지] 취소는 성공했는데 재게시가 '전부' 실패하면 이번 사이클 무주문 공백 →
        #   봇 원칙(실패했는데 성공한 척 금지)에 따라 긴급 알림. cyc_next 폴백도 못 쓰는 상황(옛 예약 이미 취소됨).
        if use_rsv and not self.dry_run and fails and not ids:
            _why = fails[0][2] if fails and len(fails[0])>2 else ""
            self._tg(f"🚨🚨 예약 취소는 됐으나 재게시 전량 실패 — 이번 사이클 무주문 공백! 즉시 수동확인 필요."
                     + (f"\n   └ 사유(첫건): {_why[:180]}" if _why else ""))
        n=(len(buy_l)+len(sell_l)) if self.dry_run else len(ids)
        self._tg(f"🪜 사다리 {n}건 배치"+(f" (실패 {len(fails)})" if fails else ""))
        return ids

    # ═══ 킬스위치 집행 기준 (은박사 확정 · 봇 신호와 정합) ═══════════════════════════
    #   대피: 매일 종가 기준 판정 → 다음 영업일 '개장가(MOO=시초가, 시장가)'로 전량 매도.
    #   복귀: 매월 마지막 영업일 종가 기준 판정 → 익월 첫 영업일 '개장가(시초가, 시장가)'로 복귀 매수.
    #   → 둘 다 '시초가 집행'. 봇도 "다음 거래일 개장가(MOO)로 매도/재매수"를 지시한다(vr_signal_bot.py).
    #     따라서 07:30 예약 전환 시 sell_at_open/buy_at_open = 예약주문(ust21200) frgn_trde_tp="03"(시장가).
    #     (지정가 아님 — 대피/복귀는 '확실한 시초가 체결'이 목적이라 시장가 예약이 맞다.)
    #   ⚠️ 대피 시: 걸어둔 2주 예약 사다리(매수·매도)를 '먼저 전량 취소'한 뒤 대피 예약(재체결 방지).
    #   [현재 구현 주의] 아래는 place_order(장중 지정가, 현재가−10%) — 장중(23:40) 크론용 근사다.
    #     봇의 본래 지시는 MOO(개장가)이므로, 07:30 예약 집행 개조 시 이 블록을 예약 시장가로 교체할 것.
    # ── ⑤ 킬스위치: state=CASH는 매도접수 성공 후에만(치명1). evac_pending로 이중주문 방지 ──
    def killswitch_evacuate(self, pos):
        _today=_kst_today()
        # ★R4(2026-07-24): 대피 스탬프도 sync 경로와 동일하게 '판정일'(evac_sig_date, ≤7일) 우선.
        #   확정/집행일로 찍으면 판정~확정 사이 월말이 소급창에서 빠져 복귀가 최대 한 달 지연된다.
        #   pop은 하지 않는다 — 이 함수는 접수 단계이고, 소비·소거는 sync의 CASH 확정이 담당한다.
        _esd0 = pos.get("evac_sig_date"); _today_stamp = _today
        if _esd0:
            try:
                _a = datetime.date.fromisoformat(str(_esd0)); _b = datetime.date.fromisoformat(_today)
                if 0 <= (_b - _a).days <= 7: _today_stamp = str(_esd0)
            except Exception: pass
        if self.dry_run:
            # ★K-C 교정(2026-07-23): DRY는 알림만. 원장 변경 금지 —
            #   DRY 검증 중 대피신호가 한 번 뜨면 state=CASH가 파일에 굳어 수동봇·LIVE 전환 시 오동작.
            #   ★㉠: recover_* 플래그 소거도 DRY에선 하지 않는다(원장 무접촉 원칙).
            self._tg("[DRY] 킬스위치: 전량취소+전량매도 (원장 미변경)")
            return pos
        # [🔴 fable5] 대피 진입 시 복귀 잔존플래그 전소거. 안 하면 대피 확정된 그 실행에서
        #   2c(recover_retry)/4b가 신호 없이 재매수 접수 → 킬스위치 무력화(시뮬 실증).
        pos.pop("recover_retry",None); pos.pop("recover_pending",None)
        # 1) 기존 주문 취소(실패해도 매도는 시도 — 청산 우선). 예약경로는 예약 취소 + 최대 3회 재시도.
        if getattr(self.broker,"uses_reservation",False):
            # ★취소 실패 시 잔존 매수예약이 폭락 중 재매수될 위험 → 인-런 재시도로 성공률↑(1req/s 페이싱, 수초 비용).
            #   매도는 개장가 예약(MOO)이라 이 수초 지연은 무해. 3회 실패해도 청산은 진행(폴백) + 다음 실행 재취소 표시.
            for _try in range(3):
                try:
                    c=self.broker.cancel_all_reservations(self.symbol)
                    self._tg(f"🔴 킬스위치: 예약 {c}건 취소" + (f" (재시도 {_try+1})" if _try else ""))
                    break
                except Exception as e:
                    if _try < 2:
                        self._tg(f"⚠️ 킬스위치 예약취소 실패 {_try+1}/3 — 재시도: {e}"); time.sleep(1.0)
                    else:
                        # 3회 실패 → 청산 우선(매도 진행) + 잔존 예약 재취소를 다음 실행 최우선으로 표시(evac_recancel).
                        self._tg(f"🚨 킬스위치 예약취소 3회 실패 — 매도는 진행(청산우선), 잔존 예약 재취소 예약: {e}")
                        pos["evac_recancel"]=True
        else:
            try:
                c=self.broker.cancel_all(self.symbol); self._tg(f"🔴 킬스위치: {c}건 취소")
            except Exception as e:
                self._tg(f"⚠️ 킬스위치 취소 일부 실패(매도는 계속): {e}")
        # 2) 실보유 조회 — 실패 시 '조용한 0' 금지, 중단+긴급알림(치명1)
        try:
            held=int(self.broker.get_holdings(self.symbol).shares)
        except Exception as e:
            self._tg(f"🚨🚨 킬스위치 보유조회 실패 — 대피 미완료! INVESTED 유지, 다음 실행 재시도: {e}")
            pos["evac_pending"]=True   # 다음 실행에서 재시도 표시
            return pos                  # state 그대로(INVESTED) — 성공한 척 금지
        # 3) 매도 주문 접수 — 성공(rt_cd=0) 후에만 CASH 표시 안 하고, 실제 CASH는 sync가 확정
        if held>0:
            try:
                if getattr(self.broker,"uses_reservation",False):
                    # ★예약경로: 다음 영업일 개장가(MOO)로 전량 매도 = 시장가 예약(_reserve rsrv_ord_tp="1").
                    #   07:30(장마감)엔 현재가 조회·지정가 근사가 불가 → 시장가로 개장가 확실 체결.
                    #   봇 지시("다음 거래일 개장가로 전량 매도")와 정합.
                    self.broker.sell_at_open(self.symbol, held, "killswitch")
                    pos["evac_pending"]=True
                    pos["last_recover_check"]=_today_stamp
                    self._tg(f"🔴 전량매도 예약 {held}주 (다음 개장가 시장가, MOO) — 체결 후 CASH 확정(sync)")
                else:
                    # 정규경로(KIS/토스): 장중 현재가−10% marketable limit(확실 체결).
                    #   [주요1] 버퍼 10%: 갭다운 날 −3%로는 미체결 위험. 낮게 걸어도 실제론 시장가에 체결.
                    px=self.broker.get_price(self.symbol)
                    limit=round(px*0.90,2)
                    req=OrderReq(self.symbol,"sell",held,limit,"DAY","LIMIT","killswitch")
                    self.broker.place_order(req)   # 실패 시 예외
                    pos["evac_pending"]=True
                    pos["last_recover_check"]=_today_stamp
                    self._tg(f"🔴 전량매도 접수 {held}주 @ {limit}(현재가−10%, marketable) — 체결 후 CASH 확정(sync)")
            except Exception as e:
                self._tg(f"🚨🚨 킬스위치 매도접수 실패 — 대피 미완료! INVESTED 유지, 재시도 예정: {e}")
                pos["evac_pending"]=True
                return pos   # state 그대로 — 성공한 척 금지(치명1 핵심)
        else:
            # 실보유 0 확인됨 → 이미 청산 상태 → CASH 확정 안전
            pos["state"]="CASH"; pos.pop("evac_pending",None)
            pos["last_recover_check"]=_today_stamp   # [🔴 휩소방지]
            self._tg("🔵 실보유 0 확인 — CASH 확정")
        return pos

    # ── 🔵 복귀: 자동 복귀매수 min(Veff,pool). (정책: 자동. 수동원하면 daily_run에서 끄기) ──
    #   ★기준(은박사 확정): 매월 마지막 영업일 종가로 판정 → 익월 첫 영업일 '개장가(시초가) 시장가' 매수.
    #     07:30 예약 전환 시 buy_at_open = 예약주문(ust21200) frgn_trde_tp="03"(시장가). 아래 place_order
    #     (장중 지정가 현재가+3%)는 장중(23:40) 크론용 근사 — 개조 시 예약 시장가로 교체.
    def recover_enter(self, pos, veff):
        if self.dry_run:
            self._tg("[DRY] 복귀 매수 (원장 미변경)")   # ★K-C: DRY는 알림만, state·플래그 손대지 않음
            return pos
        pool=pos.get("pool",0.0)
        budget=min(veff, pool)
        if budget<=0:
            self._tg("⚠️ 복귀 예산 부족 — 수동 확인"); pos["recover_retry"]=True; return pos
        try:
            px=self.broker.get_price(self.symbol)   # 예약경로도 07:30에 usa20100 base_close_pric(전일종가) 폴백 반환
            if getattr(self.broker,"uses_reservation",False):
                # ★예약경로: 익월 첫 영업일 개장가로 매수 = 시장가 예약(_reserve rsrv_ord_tp="1").
                #   수량=예산//전일종가. 시장가라 개장가로 체결(갭업 시 예산 소폭 초과 가능하나 체결 우선).
                #   봇 지시("익월 첫 영업일 개장가로 재매수")와 정합.
                qty=int((budget*0.97)//px)   # [haircut] 개장 갭업 대비 3% 여유 → 증거금 거부로 인한 복귀 지연 예방
                if qty>0:
                    self.broker.buy_at_open(self.symbol, qty)
                    self._tg(f"🔵 복귀매수 예약 {qty}주 (다음 개장가 시장가, 전일종가 {px:.2f} 기준) — 체결 후 INVESTED 확정(sync)")
                    pos["recover_pending"]=_kst_today(); pos.pop("recover_retry",None)
                else:
                    self._tg("⚠️ 복귀 수량 0(예산<전일종가) — 수동 확인"); pos["recover_retry"]=True
            else:
                # 정규경로(KIS/토스): 장중 현재가+3% 지정가(매수 체결 유도).
                limit=round(px*1.03,2)
                # [🔴 fable5 실증] 수량은 '주문가(limit)' 기준. px 기준이면 주문금액이 예산 최대 3% 초과 → 증거금 거부.
                qty=int(budget//limit)
                if qty>0:
                    self.broker.place_order(OrderReq(self.symbol,"buy",qty,limit,"DAY","LIMIT","recover"))
                    self._tg(f"🔵 복귀매수 접수 {qty}주 @ {limit} — 체결 후 INVESTED 확정(sync)")
                    pos["recover_pending"]=_kst_today(); pos.pop("recover_retry",None)
                else:
                    self._tg("⚠️ 복귀 수량 0(예산<현재가) — 수동 확인"); pos["recover_retry"]=True
        except Exception as e:
            # [🟠 복귀 재시도] 접수 실패 시 플래그 → daily_run이 신호 무관 재시도(대피 2b와 대칭).
            #   봇 복귀판정이 소급 1회성이라, 접수 실패 한 번이면 다음 월말까지 CASH 고착 방지.
            self._tg(f"🚨 복귀매수 실패 — 다음 실행 재시도: {e}"); pos["recover_retry"]=True
        return pos


def rolling_since(days_back=5):
    """[주요3] since 규약: 오늘−N영업일(기본5). 지연 조회된 전일 체결도 포착,
       프루닝과 자동 정합. daily_run(since=rolling_since())로 호출."""
    import datetime as _dt
    d=_dt.date.today(); n=0
    while n<days_back:
        d-=_dt.timedelta(days=1)
        if d.weekday()<5: n+=1   # 평일만 카운트
    return d.strftime("%Y-%m-%d")


def daily_run(auto, pos, compute_signal, df, since, save_pos, veff=None,
              auto_recover=False, compute_ladder=None):
    """일일 오케스트레이션. fable5 순서 강제.
       [주요5] compute_signal을 콜백으로 받아 sync 직후 계산(낡은 포지션 신호 방지).
       [🔴2] DAY-only 브로커는 매일 fresh compute_ladder로 재배치(signal dict 아님).
         compute_ladder(shares, Veff, pool, budget_override) → (buy, sell, buy_lot, sell_lot) 4-튜플 반환.
         KIS 주문은 당일만 유효하므로 2~14일차도 매일 새 사다리를 걸어야 책의 '2주 유지'와 동치."""
    # 1) 체결 동기화(항상 먼저) — 실패 시 예외 전파(무음실패 차단)
    try:
        pos=auto.sync_fills(pos,since); save_pos(pos)   # 원자적 저장(seen이 pos 안에)
    except Exception as e:
        auto._tg(f"🚨 체결동기화 실패 — 이후 단계 중단(안전): {e}"); return pos

    # ★evac_recancel 소비(2026-07-24): 킬스위치 예약취소 3회 실패 시 "다음 실행 최우선 재취소"로
    #   기록만 하고 읽는 곳이 없었다(기록 1곳·소비 0곳). 잔존 매수예약이 CASH 중에 체결되면
    #   shares>0 + state=CASH 모순이 sync로 조용히 정합화되어 리컨실도 못 잡는다.
    if pos.get("evac_recancel") and not auto.dry_run:   # ★R3: DRY는 실API 호출 금지(원장·계좌 무접촉)
        try:
            if hasattr(auto.broker, "cancel_all_reservations"):
                auto.broker.cancel_all_reservations(auto.symbol)
            else:
                for _o in (auto.broker.list_open_orders(auto.symbol) or []):
                    auto.broker.cancel_order(_o.get("order_id"), auto.symbol)
            pos.pop("evac_recancel", None); save_pos(pos)
            auto._tg("✅ 잔존 예약 재취소 완료 — 대피 중 재체결 위험 해소")
        except Exception as _e:
            auto._tg(f"🚨 잔존 예약 재취소 실패 — 대피 중 재체결 위험 지속. 수동 취소 필요: {_e}")

    # 2) [주요5] signal은 sync 이후에 계산 (콜백)
    signal=compute_signal(df, pos)

    # 2a') [🔴 신규1 봉합] 신호 계약: 불리언 우선(ks_evac/ks_recover), 없으면 관용 부분일치.
    #   기존 '=="🔴 대피"' 정확일치는 봇 문구가 한 글자만 바뀌어도 무음 불발 → 부분일치 방어.
    #   봇이 불리언 키를 제공하면 그쪽 우선(권고: compute_signal에 ks_evac/ks_recover 추가).
    _aks=str(signal.get("action_ks") or "")
    evac_sig  = bool(signal.get("ks_evac"))    or ("대피" in _aks)
    recov_sig = bool(signal.get("ks_recover")) or ("복귀" in _aks)

    # 3→앞당김) 리컨실 — 복귀 게이트용으로 2b/2c보다 먼저 산출.
    #   [🟠 fable5] 복귀는 봇 pool 기반 '매수'라 괴리 중 실행되면 오버바이 → recon_ok로 차단.
    #   대피는 실보유 기준 '매도'라 recon 무관 허용(기존 원칙 유지).
    recon_ok=True
    try:
        recon_ok=auto.reconcile(pos)
    except Exception as e:
        auto._tg(f"⚠️ 리컨실 오류: {e}"); recon_ok=False

    # 2b) [주요2] evac_pending 익일 완결: sync가 소비했는데도 여전히 pending이면(접수실패/미체결)
    #   대피는 신호 발생 시점에 확정된 행동 → 신호 사라져도 재실행. INVESTED일 때만(CASH면 완료됨).
    if pos.get("evac_pending") and pos.get("state")=="INVESTED":
        auto._tg("🔴 대피 미완결(evac_pending) — 신호 무관 재시도")
        pos=auto.killswitch_evacuate(pos); save_pos(pos); return pos

    # 2c) [🟠 복귀 재시도] 접수 실패로 recover_retry 남았고 여전히 CASH면 신호 무관 재시도(2b와 대칭).
    #   auto_recover일 때만(수동 정책이면 사용자가 /enter). 봇 복귀판정이 소급 1회성이라
    #   접수 실패 한 번에 다음 월말까지 CASH 고착되는 것 방지.
    if auto_recover and recon_ok and pos.get("recover_retry") and pos.get("state")=="CASH" \
       and not pos.get("recover_pending"):   # [fable5] pending 있으면 당일 중복접수 방지
        auto._tg("🔵 복귀 미완결(recover_retry) — 신호 무관 재시도")
        pos=auto.recover_enter(pos, veff or signal.get("veff",0.0)); save_pos(pos); return pos

    # 4) 킬스위치(대피) — 리컨실 실패해도 실행 허용(실보유 기준 매도라 안전)
    if evac_sig:
        pos=auto.killswitch_evacuate(pos); save_pos(pos); return pos

    # 4b) 복귀 — CASH인데 복귀신호. 자동복귀 옵션 켜졌을 때만(기본 수동)
    #   [fable5] recover_pending 있으면 당일 중복접수 방지. 만료 시 sync가 풀어 익일 재발화 유지.
    if recov_sig and pos.get("state")=="CASH" and not pos.get("recover_pending"):
        if auto_recover and not recon_ok:
            auto._tg("⚠️ 리컨실 불일치 — 자동복귀 보류(수동 확인 필요)"); return pos
        if auto_recover:
            pos=auto.recover_enter(pos, veff or signal.get("veff",0.0)); save_pos(pos)
        else:
            auto._tg("🔵 복귀 신호 — 수동 복귀 정책(/enter로 실행). 자동원하면 auto_recover=True")
        return pos

    # 5) 리컨실 실패면 사다리 중단(주요1)
    if not recon_ok:
        auto._tg("⚠️ 리컨실 불일치로 사다리 배치 중단 — 수동 확인 필요"); return pos

    # 6) 사다리 배치. [🔴2] DAY-only는 매일 fresh 계산, 아니면 사이클 시작일만.
    day_only = getattr(auto.broker,"max_validity","1MONTH")=="DAY"
    # ★예약경로 래치(2026-07-24): 봇 main이 리포트 발송 후 ladder_placed_for를 마킹하므로,
    #   (봇 main → daily_run) 순서면 여기 오는 signal의 is_cycle_start가 이미 False가 되어
    #   키움 예약 사다리가 사이클 통째로 스킵된다. 어댑터가 자체 래치로 판정한다.
    #   (DAY-only(KIS)는 매일 재배치라 is_cycle_start와 무관 — 영향 없음)
    _cs_key = str(signal.get("cyc_start") or "")
    _rsv_due = (not day_only) and pos.get("rsv_ladder_for") != _cs_key
    if pos.get("state")=="INVESTED" and (day_only or _rsv_due):
        # [🟠2 가드] DAY-only인데 compute_ladder 콜백 미전달이면 signal 사다리(2~14일차 빈 리스트)로
        #   떨어져 🔴2가 조용히 재발 → 배치 중단+경고. [🟡 state 체크 뒤로: CASH에선 조용].
        if day_only and compute_ladder is None and not signal.get("is_cycle_start"):
            auto._tg("🚨 DAY-only인데 compute_ladder 콜백 없음 — 사다리 배치 중단(2~14일차 빈배치 방지). "
                     "daily_run(compute_ladder=...) 전달 필요."); return pos
        # ★R1 교정(2026-07-24): 예약경로도 콜백으로 신선 계산한다.
        #   래치(_rsv_due)만 고치고 데이터는 signal에 묶어두면, 봇 main이 먼저 돌아
        #   ladder_placed_for를 마킹한 날 signal의 사다리가 '빈 리스트'로 와서
        #   rotate가 옛 예약을 전량 취소하고 0건 배치 후 래치까지 찍는다(원래 결함보다 나쁨).
        if compute_ladder is not None:
            _veff = veff or signal.get("veff") or pos.get("V",0.0)
            _bud=None
            if pos.get("cyc_budget") is not None:
                _bud=max(0.0, float(pos["cyc_budget"])-float(pos.get("cyc_used",0.0)))
            # ★4-튜플(2026-07-24): 봇 compute_ladder가 매수/매도 lot을 분리 반환한다.
            #   3-unpack이면 ValueError로 배치 전 크래시(무주문 공백) → 반드시 4개로 받는다.
            buy,sell,blot,slot=compute_ladder(pos.get("shares",0.0), _veff, pos.get("pool",0.0),
                                              budget_override=_bud, cur_px=signal.get("pr"))
        else:
            # 콜백 미전달(예약경로 구설정): 사이클 시작일 signal의 사다리 사용
            buy=signal.get("buy_ladder",[]); sell=signal.get("sell_ladder",[])
            blot=signal.get("ladder_lot",1); slot=signal.get("ladder_slot",blot)
        if blot in (-1, -2):   # [봇 거부철학 미러] V괴리(-1)·한도>V(-2)면 쓰레기 사다리 → 기존주문 유지(취소 안 함)+긴급알림, 배치 스킵
            _rsn = "V괴리 — V 오입력 의심(/setv·/setpos 확인)" if blot==-1 else "매수한도>V — Pool 과대(현금 자릿수 확인)"
            auto._tg(f"🚨 사다리 배치 거부 — {_rsn}. 기존 주문 유지, 수동 확인 필요.")
            save_pos(pos); return pos
        # ★R1 방어선: 센티널이 아닌데 매수·매도가 모두 비었다 = 계산 실패/데이터 공백.
        #   이 상태로 rotate에 들어가면 cancel-first가 옛 주문만 지우고 0건을 건다 → 무주문 잠금.
        if not buy and not sell:
            auto._tg("🚨 사다리 계산 결과가 비었습니다 — 기존 주문 유지(취소 안 함), 배치 스킵. "
                     "보유·V·Pool과 compute_ladder 전달 여부를 확인하세요.")
            save_pos(pos); return pos
        # ★예약경로: 봇 사이클 기간(cyc_start~cyc_next)을 예약 시작/종료일로 전달(YYYYMMDD).
        #   정규경로는 strt_dt/end_dt를 무시하므로 KIS/토스에 무영향.
        _cs=signal.get("cyc_start"); _cn=signal.get("cyc_next")
        _cs_s=_cs.strftime("%Y%m%d") if hasattr(_cs,"strftime") else (str(_cs).replace("-","") if _cs else None)
        _cn_s=_cn.strftime("%Y%m%d") if hasattr(_cn,"strftime") else (str(_cn).replace("-","") if _cn else None)
        _ids = auto.rotate_cycle(pos, buy, sell, blot, sell_lot=slot, strt_dt=_cs_s, end_dt=_cn_s)
        # ★R2 교정: 실제 접수분이 있을 때만 래치. 취소 실패·전량 실패면 []라 무래치 → 익일 재시도.
        #   DRY도 무래치(원장 무접촉 원칙) — DRY 검증 후 같은 사이클 LIVE 전환 시 배치가 스킵되면 안 된다.
        if (not auto.dry_run) and (not day_only) and _cs_key and _ids:
            pos["rsv_ladder_for"]=_cs_key   # ★예약 래치: 이 사이클 배치 완료 표시(중복 배치 방지)
        save_pos(pos)
    return pos


def _example():
    # [fable5] TossAdapter는 vr_toss_adapter.py로 분리 → 함수내 지연임포트(순환참조 회피).
    from vr_toss_adapter import TossAdapter
    broker=TossAdapter(os.environ.get("TOSS_CLIENT_ID","TODO"),
                       os.environ.get("TOSS_CLIENT_SECRET","TODO"),
                       os.environ.get("TOSS_ACCOUNT","TODO"))
    auto=LadderAutomator(broker,"TQQQ",dry_run=True)
    def fake_signal(df,pos):
        return {"action_ks":None,"is_cycle_start":True,
                "buy_ladder":[(64.96,3018,0)],"sell_ladder":[(87.88,2982,0)],"ladder_lot":18}
    pos={"shares":3000,"pool":76420,"cyc_used":0,"state":"INVESTED"}
    daily_run(auto,pos,fake_signal,df=None,since="2026-07-06",save_pos=lambda p: None)

if __name__=="__main__":
    _example()
