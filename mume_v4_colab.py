# -*- coding: utf-8 -*-
"""
vr_auto_runner_kiwoom.py — vr_signal_bot <-> vr_kiwoom_adapter 글루 [키움 전용]  rev.1
════════════════════════════════════════════════════════════════════════
★ 불가침 (한 글자도 수정하지 않는다)
    vr_signal_bot.py · vr_broker_adapter.py · vr_kiwoom_adapter.py
  이 파일만 고친다. 어댑터 보강은 전부 '상속·래핑'으로 한다.

★ KIS 실측(2026-07-12~13)에서 얻은 경화를 전부 이식했다
  [N1] 키 공백 → strip (앱키 앞 스페이스 1칸이 반나절을 날렸다)
  [N2] 레이트리밋 → _PacedSession이 최소 호출간격 강제 + HTTP 429 백오프
       키움 공식: TR별 1 req/s (버스트 2). 초과 시 429.
  [N3] 토큰 무효 → 1회 재인증(쿨다운 존중). 토큰 파일 캐시 공유로 재발급 최소화.
  [G1] 스키마 가드 — 어댑터가 .get() 하는 필드를 '전부' 검사. 조용한 0/[] 금지.
  [G2] AUTO_MODE — 체결보고 명령 거부 (sync_fills와 이중반영 방지)
  [G4] 조회 프로브 — DRY에서도 항상.
  [F3] verify_placed — 접수한 주문이 조회에 실제로 보이는가
  [Q1] 프로브를 '명령 처리 뒤'에 (허위 불일치 경보 방지)

★ 키움 고유 주의 (공식 명세서 실측)
  [K1] 체결조회(ust21150)는 '하루 단위'다 → 어댑터가 날짜 루프를 돈다.
       조회창이 길면 콜 수가 늘어난다(1일=1콜×1.1초). SYNC_SINCE로 창을 좁혀라.
  [K2] 응답에 '수수료 필드가 없다' → FEE_RATE 추정(0.1%). [실측필요]
       첫 체결 후 실제 수수료를 확인해 FEE_RATE를 보정할 것.
  [K3] 체결 side가 한글명(slby_tp_nm)뿐 → 판정불가면 어댑터가 중단(sell 낙착 금지).
  [K5] 미체결 판정은 ord_remnq(주문잔량)>0.

★★ 실계좌 안전장치 ★★
  [L1] KIWOOM_MOCK=off(실전)이면 LIVE_ARM=on 없이는 실주문 거부
  [L2] 동적 주수 상한 max(CAP_FLOOR, ⌈보유수×CAP_RATIO⌉) — 넘으면 중단. 금액상한 불요(주수 막으면 자동).
  [L3] 배선 순서: 모의(mockapi)로 완주 → 실전 DRY 프로브 → 1주 실측 → LIVE_ARM

━━ 환경변수 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  KIWOOM_APPKEY / KIWOOM_SECRETKEY         (필수)
  KIWOOM_ACCOUNT                           (선택. 명세상 body 불요 — 로그용)
  KIWOOM_MOCK=on    on=mockapi.kiwoom.com / off=api.kiwoom.com(실전)
  KIWOOM_EXCD=ND    거래소구분. TQQQ=나스닥 → ND (NY:NYSE, NA:AMEX)
  DRY_RUN=on        주문 안 냄(프로브만)
  LIVE_ARM=off      ★실전(MOCK=off)에서 실주문하려면 on 필요
  AUTO_MODE=off     on이면 체결보고 명령 거부(실주문 시 필수)
  AUTO_RECOVER=off
  CAP_RATIO=0.05 / CAP_FLOOR=50   동적 주수 상한(보유×0.05, min 50주). 정상 lot의 1.34배.
  SYNC_SINCE=       YYYY-MM-DD (키움은 날짜루프라 창을 좁힐수록 빠르다)
  SYMBOL=TQQQ
  + TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, time, traceback, math

import vr_signal_bot as bot
from vr_broker_adapter import LadderAutomator, daily_run, rolling_since, Fill, OrderReq
from vr_kiwoom_adapter import KiwoomAdapter, KiwoomError

ON = bot.ON
DRY_RUN      = ON(os.environ.get("DRY_RUN", "on"))
LIVE_ARM     = ON(os.environ.get("LIVE_ARM", "off"))
AUTO_MODE    = ON(os.environ.get("AUTO_MODE", "off"))
AUTO_RECOVER = ON(os.environ.get("AUTO_RECOVER", "off"))
KIWOOM_MOCK  = ON(os.environ.get("KIWOOM_MOCK", "on"))
SYNC_SINCE   = os.environ.get("SYNC_SINCE", "").strip()
# ★미신고 입출금 감지(2026-07-23): 증권사 예수금과 원장 Pool 차이가 이 값(USD) 이상이면 알림만.
#   sync_fills 직후 비교하므로 남는 차이는 외부 입출금뿐(배당·수수료는 임계 아래).
#   기본 3500 ≈ 500만원(환율 1400). 자동 처리는 하지 않는다 — 의도(v/pool)를 사람이 정해야 하므로.
CASH_GAP_ALERT = float(os.environ.get("CASH_GAP_ALERT", "3500"))
SYMBOL       = os.environ.get("SYMBOL", "TQQQ")
EXCD         = os.environ.get("KIWOOM_EXCD", "ND").strip().upper()

# [L2] 동적 주수 상한: max(CAP_FLOOR, ceil(보유수×CAP_RATIO)).
#   CAP_RATIO=0.05 = 정상 lot(보유수×0.0374, 봇 budget>V 방어로 보장되는 절대상한)의 1.34배.
#   여유 1.34배 근거 = ceil 올림 + est 근사오차 + budget=V 경계안전.
#   (전수검증: pool/V 0.01~2.0 × 계좌 10주~10만주 2587건 오탐 0, 최소여유 12주. 봇우회 오주문 정상×1.5부터 차단.)
#   계좌 성장에 자동 대응(보유수 연동) → 상한 수동조정 불요. 금액 상한은 불요(금액=주수×주가, 주수 막으면 자동 제한).
CAP_RATIO = float(os.environ.get("CAP_RATIO", "0.05"))
CAP_FLOOR = int(os.environ.get("CAP_FLOOR", "50"))

TG_LIMIT = 3800
# ★R4 교정(2026-07-23): /deposit 추가. /deposit_done이 차단인데 러너에 deposit 자동집행이 없어
#   예약이 영구 잔존 → 매일 "확정하세요" ↔ "⛔ 거부" 모순 루프. /lumpsum v가 같은 공식(P/V 고정)으로
#   기능을 완전 대체하고 자동 집행되므로 입구에서 막고 안내한다.
BLOCKED_IN_AUTO = {"/buy", "/sell", "/exit", "/enter", "/deposit", "/deposit_done", "/lumpsum_done"}


# ══ 알림 ═══════════════════════════════════════════════════════════
class Notifier:
    URGENT = ("🚨", "🔴", "⚠", "⛔")
    def __init__(self, sink):
        self.sink = sink; self.buf = []
    def __call__(self, m):
        if any(u in m.lstrip()[:3] for u in self.URGENT):
            self.sink(m)
        else:
            self.buf.append(m)
    def flush(self):
        if not self.buf: return
        chunk = []
        for m in self.buf:
            if sum(len(x) + 1 for x in chunk) + len(m) > TG_LIMIT and chunk:
                self.sink("\n".join(chunk)); chunk = []
            chunk.append(m)
        if chunk: self.sink("\n".join(chunk))
        self.buf = []


# ══ [N2][N3] 네트워크 경화 세션 래퍼 ═══════════════════════════════
class _PacedSession:
    """어댑터의 requests.Session을 감싸 (a)최소 호출간격 (b)429 백오프
       (c)토큰 무효 1회 재인증. 키움 공식 한도: TR별 1req/s(버스트 2)."""
    AUTH_RC = ("3", "8", "40")     # [확인필요] 인증계열 return_code 후보 — 첫 실측 시 확정

    def __init__(self, real, owner, min_gap=1.1):
        self._real, self._owner, self._gap = real, owner, min_gap
        self._last = 0.0

    def _pace(self):
        wait = self._gap - (time.time() - self._last)
        if wait > 0: time.sleep(wait)
        self._last = time.time()

    def post(self, url, **kw):
        r = None
        for attempt in range(4):
            self._pace()
            r = self._real.post(url, **kw)
            if r.status_code == 429:                       # 유량초과 → 적응형 백오프
                self._gap = min(self._gap * 1.5, 3.0)
                print(f"[레이트리밋] 간격 {self._gap:.1f}s 상향 후 재시도")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (401, 403) and attempt == 0 and "/oauth2/" not in url:
                if self._owner._reauth():
                    h = dict(kw.get("headers") or {})
                    h["authorization"] = f"Bearer {self._owner._token}"
                    kw["headers"] = h
                    continue
            return r
        return r

    def get(self, url, **kw):
        self._pace()
        return self._real.get(url, **kw)


# ══ [G1] 스키마 가드 ═══════════════════════════════════════════════
class GuardedKiwoom(KiwoomAdapter):
    """어댑터 무수정 — 상속만. 필드 계약 검증 + 실계좌 주문 상한."""

    # 어댑터가 실제로 .get() 하는 필드를 전부 검사.
    # ★교정(2026-07-23, 모의 실측): 종목코드 = stk_cd. rev.3의 stk_code는 오류였고 어댑터는 이미
    #   stk_cd로 교정됐는데 이 가드만 낡아 정상 응답을 불일치 판정 → 전면 중단시켰다.
    #   ust21070 실측 응답 키에 stk_cd 확인. us_unfilled/us_filled는 아직 0행이라 미실측 —
    #   어댑터가 읽는 이름(stk_cd)에 맞춰두고, 행이 생겨 다르면 가드가 걸러낸다(설계대로).
    _EXPECT = {
        "us_balance":  ["stk_cd", "poss_qty"],                   # + frgn_stk_book_uv
        "us_unfilled": ["ord_no", "stk_cd", "ord_remnq"],
        "us_filled":   ["ord_no", "stk_cd", "cntr_qty", "cntr_uv"],
        "us_rsv_list": ["rsrv_ord_no", "stk_cd"],                # 예약 미지원(uses_reservation=False)이라 사실상 사문
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._placed = []
        self._sess = _PacedSession(self._sess, self, 1.1)
        self._last_auth = 0.0
        self._multifill_alerted = False   # [치명3] 다행 감지 알림 — 실행당 1회(get_fills가 실행당 3~4회 호출됨)
        self._cap_shares = None           # [L2] 동적 상한용 보유수 캐시(실행당 1회 조회, 사다리 여러 칸 재조회 방지)
        self._ladder_rsv_n = 0            # [치명A] 이번 실행 실제 예약 배치 건수 → 래치를 '실배치'에 결속(배치0건이면 래치 안 함)

    def _reauth(self):
        if time.time() - self._last_auth < 65:
            print("[재인증 보류] 쿨다운 — 원래 오류를 그대로 올린다")
            return False
        self._last_auth = time.time()
        self._token = None; self._exp = 0
        try: os.remove(f".kiwoom_token_{'mock' if self.mock else 'live'}.json")
        except Exception: pass
        try:
            self.authenticate()
            print("[재인증] 새 토큰 발급 — 재시도")
            return True
        except Exception as e:
            print(f"[재인증 실패] {e}")
            return False

    def _audit(self, api_id, rows):
        key = next((k for k, v in self.API.items() if v == api_id), None)
        need = self._EXPECT.get(key, [])
        if not (rows and need): return
        miss = [k for k in need if not any(k in r for r in rows)]
        if miss:
            raise KiwoomError(
                f"🔴 스키마 불일치[{key}/{api_id}]: 누락 {miss}. 조용한 0/[] 반환 = "
                f"킬스위치 무음실패·이중사다리 경로 → 중단. 실제 키={list(rows[0].keys())}")

    def _post(self, path, api_id, body, err, paged=False):
        d = super()._post(path, api_id, body, err, paged=paged)
        self._audit(api_id, self._rows(d))
        return d

    # ── [L2] 동적 주수 상한 ──────────────────────────────────
    def _cap_qty(self, symbol):
        """상한 = max(CAP_FLOOR, ceil(보유수×CAP_RATIO)) = 정상 lot의 1.34배.
           보유수는 실행당 1회 조회 후 캐시. 조회 실패 시 예외 전파(무음실패 금지)."""
        if self._cap_shares is None:
            self._cap_shares = float(self.get_holdings(symbol).shares)
        return max(CAP_FLOOR, math.ceil(self._cap_shares * CAP_RATIO))

    # ── [L2] 실계좌 주문 상한 ──────────────────────────────────
    def place_order(self, req):
        qty = int(req.qty)
        # [치명2] tag 분기 — 킬스위치·복귀는 계좌 규모와 무관하게 전량 집행돼야 한다.
        #   killswitch: 매도 수량=실보유(killswitch_evacuate가 get_holdings로 산정) → 상한 예외 안전.
        #   recover   : 매수 notional≤pool(recover_enter의 min(veff,pool)) → 상한 예외 안전.
        #   그 외(ladder 등)만 동적 주수 상한 유지. 지정가 괴리 검사는 tag 무관 유지.
        #   금액 상한 불요: 금액=주수×주가라 주수를 막으면 금액도 자동 제한(주가 상승은 정상이라 안 막음).
        _tag = (getattr(req, "tag", "") or "").lower()
        # ★R1 교정(2026-07-23): lumpsum 면제 추가. 목돈 주수는 사용자가 지정한 금액에서 유도되고
        #   (qty×price ≤ |lump| 구조 보장) 예수금이 최종 방어다. 상한에 걸리면 집행 불가 →
        #   pending 잔존 → 매일 재시도·알림 루프. AUTO에선 /lumpsum_done도 차단이라 해소 경로마저 없음.
        _exempt = _tag in ("killswitch", "recover", "lumpsum")
        if not _exempt:
            cap = self._cap_qty(req.symbol)
            if qty > cap:
                raise KiwoomError(f"⛔ 주문 상한 초과: {qty}주 > 동적상한 {cap}주(보유×{CAP_RATIO}). "
                                  f"사다리 오계산·V 오입력 의심 → 중단(계좌 보호).")
        # ★[2026-07-17] 지정가 괴리 방어 — V 오설정 대량 오주문 실증 후 추가.
        #   개별 주문 크기(qty·notional)는 상한 안 넘어도, '지정가가 현재가에서 튀면'
        #   V가 잘못된 것(예: V=200,000/1269주 → 매도 지정가 236, 현재가 71의 3배).
        #   지정가가 현재가의 2.5배↑ 또는 0.4배↓면 비정상 → 거부(계좌 보호).
        #   (정상 사다리는 밴드 ±15% × lot 누적이라 현재가의 0.6~1.6배 안에 든다.)
        lim = float(req.limit_price or 0)
        if lim > 0:
            try:
                mkt = self.get_price(req.symbol)
            except Exception:
                mkt = 0.0
            if mkt > 0:
                r = lim / mkt
                if r > 2.5 or r < 0.4:   # ★2026-07-17 임계 완화(1.8→2.5). 정상 오탐 방지.
                    raise KiwoomError(
                        f"⛔ 지정가 괴리 — {req.side} {qty}주 @ {lim:.2f} vs 현재가 {mkt:.2f} "
                        f"({r:.1f}배). V 오설정 의심 → 중단(계좌 보호). "
                        f"V를 '보유×현재가'에 맞게 재설정하세요.")
        oid = super().place_order(req)
        if oid:
            self._placed.append((str(oid), req.side, qty))
        return oid

    # ── [L2+] 사다리 예약 상한 (rev.4 예약경로) ─────────────────────
    #   place_ladder_reserve도 place_order와 동일 상한: 칸 qty·notional·지정가 괴리.
    #   사다리라 tag 면제 없음(대피/복귀=sell_at_open/buy_at_open은 부모 그대로 = 면제).
    def place_ladder_reserve(self, side, symbol, qty, limit, strt_dt, end_dt):
        q = int(qty); px = float(limit or 0)
        cap = self._cap_qty(symbol)   # 동적: 정상 lot의 1.34배. 금액상한 불요(주수 막으면 자동 제한).
        if q > cap:
            raise KiwoomError(f"⛔ 예약 상한 초과: {q}주 > 동적상한 {cap}주(보유×{CAP_RATIO}). "
                              f"사다리 오계산·V 오입력 의심 → 중단(계좌 보호).")
        if px > 0:   # 지정가 괴리(정상 사다리는 현재가의 0.6~1.6배)
            try: mkt = self.get_price(symbol)
            except Exception: mkt = 0.0
            if mkt > 0 and (px > mkt*2.5 or px < mkt*0.4):
                raise KiwoomError(f"⛔ 예약 지정가 괴리 — {side} {q}주 @ {px:.2f} vs 현재가 {mkt:.2f}. "
                                  f"V 오설정 의심 → 중단(계좌 보호).")
        oid = super().place_ladder_reserve(side, symbol, q, px, strt_dt, end_dt)
        if oid:
            self._placed.append((str(oid), side, q))
            self._ladder_rsv_n += 1   # [치명A] 실제 배치 성공 카운트(래치 트리거)
        return oid

    def get_fills(self, symbol, since):
        """[치명3 보험] ust21150 부분체결 다행 대비 — (filled_at,order_id,side)로 집계.
           어댑터 원본이 '주문당 누적 1행'이면 항등(무해). 행별(부분체결마다 별도 행) 응답이면
           같은 주문의 여러 행이 dedup 키 충돌로 소실되던 것을 방지.
           병합: 수량 합 · 가중평균 체결가 · 수수료 합. 원본 등장 순서 보존."""
        raw = super().get_fills(symbol, since)
        agg = {}; order = []
        for f in raw:
            k = (f.filled_at, f.order_id, f.side)
            if k in agg:
                a = agg[k]; tot = a.qty + f.qty
                aprice = (a.price * a.qty + f.price * f.qty) / tot if tot else f.price
                agg[k] = Fill(f.symbol, f.side, int(tot), aprice, a.fee + f.fee, f.order_id, f.filled_at)
            else:
                agg[k] = f; order.append(k)
        merged = [agg[k] for k in order]
        # [치명3 다행 감지] 병합이 실제로 일어났으면(원시 행수 > 주문 수) 알림. 실행당 1회.
        #   부분체결은 인위 재현이 어려워 자연 발생을 기다려야 형태(증분 b / 누적 c) 확정 가능.
        #   이 알림이 그 트리거 — 당일 즉시 인지(없으면 익일 reconcile 중단이 첫 징후).
        #   날짜가 바뀌면 재발 허용(5영업일 창 리마인더, 창 지나면 자연 소멸).
        if len(raw) > len(merged) and not self._multifill_alerted:
            self._multifill_alerted = True
            from collections import Counter
            cnt = Counter((f.order_id, f.side) for f in raw)
            parts = [f"{m.order_id}({m.side}) {cnt[(m.order_id, m.side)]}행→{m.qty}주"
                     for m in merged if cnt.get((m.order_id, m.side), 1) > 1]
            try:
                bot._tg("ℹ️ 부분체결 다행 감지 — 원시 " + str(len(raw)) + "행 → " + str(len(merged)) +
                        "주문 병합.\n   " + "; ".join(parts) +
                        "\n   ⚠️ 원시 행별 값이 '증분'이면 현행 합산 정확, '누적'이면 과계상. "
                        "원시 응답 형태 실측 확정 필요(다음 reconcile이 불일치 시 자동중단).")
            except Exception:
                pass
        return merged

    # ── [F3] 접수 주문 가시성 ──────────────────────────────────
    def verify_placed(self, symbol, since):
        if not self._placed: return None
        norm = lambda x: str(x or "").strip().lstrip("0")     # 0패딩 정규화
        try:
            opens = {norm(o.get("order_id")) for o in self.list_open_orders(symbol)}
            fills = {norm(f.order_id) for f in self.get_fills(symbol, since)}
        except KiwoomError as e:
            return f"🚨 접수주문 가시성 확인 실패: {e}"
        # [중C] 예약경로: 예약번호는 개장 전이라 미체결·체결에 안 뜸 → 예약목록(rsrv_ord_no)도 대조 대상에 포함.
        rsvs = set()
        if getattr(self, "uses_reservation", False):
            try:
                rsvs = {norm(r["rsrv_ord_no"]) for r in self.list_reservations(symbol) if r.get("rsrv_ord_no")}
            except Exception:
                rsvs = set()
        ghost = [o for o, _s, _q in self._placed if norm(o) not in opens and norm(o) not in fills and norm(o) not in rsvs]
        # [중C 폴백] 접수 응답 id가 ord_no인지 rsrv_ord_no인지는 G1 실측. 개별 대조가 id 필드 불일치로 실패해도
        #   실제 예약 건수 ≥ 접수 건수면 ghost 아님(건수 대조 — 이중사다리 오경보 방지).
        if ghost and getattr(self, "uses_reservation", False) and len(rsvs) >= len(self._placed):
            ghost = []
        if ghost:
            return (f"🚨🚨 접수한 주문 {ghost} 이 미체결·체결·예약 어디에도 없음 — "
                    f"조회가 주문을 못 본다는 뜻. cancel-first 무력 → 이중 사다리 위험.")
        return None


# ══ [G2] AUTO_MODE 명령 가드 ═══════════════════════════════════════
_orig_apply = getattr(bot.apply_command, "_vr_orig", bot.apply_command)   # ★멱등: reload/이중임포트 시 패치 중첩(무한재귀) 방지
def _guarded_apply(pos, text, price_hint, Veff_target=None):
    t = (text or "").strip().split()
    cmd = t[0].lower().split("@", 1)[0] if t else ""
    if AUTO_MODE and cmd in BLOCKED_IN_AUTO:
        _alt = ("\n   입출금은 <code>/lumpsum ±금액 v</code>(목돈공식·자동집행) 또는 "
                "<code>/lumpsum ±금액 pool</code>(Pool만)을 쓰세요."
                if cmd in ("/deposit", "/deposit_done", "/lumpsum_done") else "")
        return pos, (f"⛔ AUTO_MODE — <code>{cmd}</code> 거부.\n"
                     f"   체결은 증권사 API로 자동 동기화됩니다(이중반영 방지).{_alt}")
    return _orig_apply(pos, text, price_hint, Veff_target)
_guarded_apply._vr_orig = _orig_apply
bot.apply_command = _guarded_apply


# ══ [G6] 목돈 자동 집행 ═══════════════════════════════════════════
def _us_market_open():
    """미국 정규장 개장 중인가(XNYS). 판정 불가하면 False — 보수적으로 집행을 미룬다."""
    try:
        import pandas_market_calendars as mcal
        now = bot.pd.Timestamp.now(tz="America/New_York")
        d = now.strftime("%Y-%m-%d")
        sch = mcal.get_calendar("XNYS").schedule(start_date=d, end_date=d)
        if sch.empty:
            return False
        return bool(sch.iloc[0]["market_open"] <= now <= sch.iloc[0]["market_close"])
    except Exception:
        return False


def V_pre_check(pos, lump, total):
    """집행 후 V가 양수로 남는지 사전 계산(R3 가드용). total>0 전제."""
    try:
        return float(pos.get("V", 0.0)) * (1.0 + lump / total)
    except Exception:
        return 0.0


def apply_pending_lump(broker, pos, price, notify):
    """목돈(/lumpsum ±금액 v|pool) 자동 집행 — AUTO_MODE 전용.
       · pool 모드: Pool만 증감. 주문 없음 → 장 시간 무관.
       · v 모드   : 책 공식. Pool 증감 + V 재설정(P/V 고정, V×(1+M/총자산)) +
                   현재 비중대로 즉시 매수/매도(marketable limit). 체결은 다음 실행 sync_fills가 반영.
                   장 마감이면 집행하지 않고 대기 — 사다리 '전량취소'에 휩쓸리는 사고를 원천 차단.
       · DRY_RUN : 계산만 알리고 원장·주문 모두 손대지 않는다."""
    lump = float(pos.get("pending_lump", 0.0) or 0.0)
    mode = str(pos.get("pending_lump_mode", "") or "").lower()
    if not lump or mode not in ("v", "pool"):
        return pos
    # ★㉡(2026-07-23): 직전 목돈이 체결 대기 중이면 중첩 집행 금지.
    #   두 건이 겹치면 V가 두 번 재설정되고 사다리 게이트도 꼬인다. 확정 후 다음 실행에 처리.
    if pos.get("lump_in_flight"):
        notify(f"⏸️ 목돈 {lump:+,.0f} 대기 — 이전 목돈이 체결 대기 중입니다. 확정 후 집행합니다.")
        return pos
    if pos.get("lump_in_flight"):   # ★㉡: 이전 목돈이 체결 대기 중이면 중첩 집행 금지
        notify("⏸️ 이전 목돈이 체결 대기 중 — 확정된 뒤 집행합니다(예약 유지).")
        return pos

    ev    = float(pos.get("shares", 0.0)) * price
    pool  = float(pos.get("pool", 0.0))
    total = ev + pool
    w     = 0.0 if pos.get("state") == "CASH" else (ev / total if total > 0 else 1.0)
    act   = "추가" if lump > 0 else "인출"

    # ── Pool 보충/인출 (V 불변, 주문 없음) ──
    # ★B안(2026-07-23) 이후 pool 모드는 봇 /lumpsum 단계에서 즉시 확정된다.
    #   여기 도달하는 건 구버전 상태파일에 남은 예약뿐 → 폴백으로 안전 처리.
    if mode == "pool":
        newpool = pool + lump
        if newpool < 0:
            pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
            bot.save_position(pos)
            notify(f"⚠️ 목돈 취소 — Pool {pool:,.0f}에서 {abs(lump):,.0f} 인출 불가. "
                   f"주식까지 줄이려면 <code>/lumpsum {lump:+.0f} v</code>.")
            return pos
        if DRY_RUN:
            notify(f"[DRY] Pool {act} {abs(lump):,.0f} → {pool:,.0f}→{newpool:,.0f} (원장 미변경)")
            return pos
        pos["pool"] = newpool
        pos["cyc_budget"] = max(0.0, newpool) * bot.BUY_LIMIT; pos["cyc_used"] = 0.0
        pos.pop("ladder_placed_for", None)          # 한도 바뀜 → 사다리 재게시
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
        bot.save_position(pos)
        notify(f"💰 <b>Pool {act} {abs(lump):,.0f} 반영</b> — Pool {pool:,.0f} → {newpool:,.0f} (V 불변)")
        return pos

    # ── 목돈 공식 (V 재설정 + 비율대로 즉시 매매) ──
    if total <= 0:
        notify("⚠️ 목돈(v) 보류 — 총자산 0이라 비중 계산 불가. <code>/setpos</code>로 원장을 먼저 맞추세요.")
        return pos
    # ★R3(2026-07-23): 집행 직전 재검증. 봇 F3는 '예약 시점' 가격 기준이라, 예약↔집행 사이 급락
    #   (장 마감이면 며칠 이월 가능)이나 레거시 예약이면 관통한다. Pool 음수·V 음수 사고 차단.
    if lump < 0 and (-lump) >= total:
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None); bot.save_position(pos)
        notify(f"🚨 목돈 인출 취소 — 요청 {abs(lump):,.0f} ≥ 현재 총자산 {total:,.0f}. "
               f"예약 시점 이후 하락한 것으로 보입니다. 금액을 줄여 다시 예약하세요.")
        return pos
    # ※ 여기서 'pool+lump<0'을 막으면 안 된다(2026-07-23 회귀 교정). 러너는 비동기 회계 —
    #   Pool이 인출액 전액을 먼저 흡수하고 매도대금은 다음 실행 sync_fills로 들어온다.
    #   따라서 인출 직후 Pool이 일시 음수인 것이 정상 경로다(책 예시2: 2,000−10,000 → 매도 9,000 유입 → 1,000).
    #   총자산 초과는 위 1차 가드가 이미 차단하고, V_new≤0도 그와 수학적으로 동치라 별도 검사 불필요.
    # ★R5(2026-07-23): limit·qty를 실시간 현재가로 산출. price_hint(전일 완성 종가)로 잡으면
    #   +10% 이상 갭업 시 매수 limit이 시장 아래 → 미체결인데 pending은 소거돼 재시도가 없다.
    px_live = price
    try:
        _p = float(broker.get_price(SYMBOL))
        if _p > 0: px_live = _p
    except Exception:
        pass
    side  = "buy" if lump > 0 else "sell"
    qty   = int(abs(lump * w) / px_live) if px_live > 0 else 0     # 정수 주수(내림), 나머지는 Pool
    if side == "sell":
        qty = min(qty, int(float(pos.get("shares", 0.0))))
    V_old = float(pos.get("V", 0.0)); V_new = V_old * (1.0 + lump / total)
    limit = round(px_live * (1.10 if side == "buy" else 0.90), 2)  # marketable limit(킬스위치와 동일 방식)
    # 매도대금까지 포함한 '최종' Pool로 검사(qty 내림 잔차가 커서 음수가 되는 극단 케이스만 차단).
    if lump < 0 and (pool + lump + qty * px_live) < -1.0:
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None); bot.save_position(pos)
        notify(f"🚨 목돈 취소 — 매도대금 포함 최종 Pool({pool+lump+qty*px_live:,.0f})이 음수입니다. 재예약 필요.")
        return pos

    if DRY_RUN:
        notify(f"[DRY] 목돈 {lump:+,.0f}({act}) — {side} {qty}주 @{limit} · "
               f"Pool {pool:,.0f}→{pool+lump:,.0f} · V {V_old:,.0f}→{V_new:,.0f} (원장·주문 미실행)")
        return pos
    if not _us_market_open():
        notify(f"⏸️ 목돈 {lump:+,.0f} 대기 — 미국장 마감. 다음 장중 실행에 집행합니다.")
        return pos

    _oid = None
    if qty > 0:
        try:
            _oid = broker.place_order(OrderReq(SYMBOL, side, qty, limit, "DAY", "LIMIT", "lumpsum"))
        except Exception as e:
            notify(f"🚨 목돈 주문 실패 — 원장 미변경, 다음 실행에 재시도: {e}")
            return pos

    pos["pool"] = pool + lump
    pos["V"]    = V_new
    # ★R2+K-D 교정(2026-07-23): 여기서 ladder_placed_for/cyc_budget을 건드리지 않는다.
    #   · ladder_placed_for pop → 같은 실행에서 새 V로 사다리 재게시 → shares는 체결 전(구주수)이라
    #     매수단 전체가 현재가 위에 깔려 즉시 폭주 체결(실측). day_only 재배치라 cancel-first가
    #     목돈 주문까지 삼킨다. → 체결 확정될 때까지 사다리를 아예 보류(lump_in_flight 게이트).
    #   · budget 리셋도 체결 후로 미룬다. sync_fills가 목돈 매수를 cyc_used에 가산하므로(K-D)
    #     지금 리셋하면 예산이 목돈에 전소돼 사이클 내내 사다리 매수 불능이 된다.
    if _oid:
        pos["lump_in_flight"] = str(_oid)
    pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
    bot.save_position(pos)
    notify(f"💵 <b>목돈 {lump:+,.0f} 집행({act})</b> — {side} {qty}주 접수 @{limit}(marketable) · "
           f"Pool {pool:,.0f}→{pos['pool']:,.0f} · V {V_old:,.0f}→{V_new:,.0f}\n"
           f"   체결 확정까지 사다리는 보류됩니다(즉시체결 방지).")
    return pos


# ══ [G4] 조회 프로브 ═══════════════════════════════════════════════
def probe(broker, pos, since, notify):
    acct = "모의" if KIWOOM_MOCK else "<b>실계좌</b>"
    L = [f"🔍 <b>조회 프로브</b> (주문 없음) — 키움 {acct}"]
    L.append(f"   현재가 ${broker.get_price(SYMBOL):,.2f}")

    held = broker.get_holdings(SYMBOL)
    bs = float(pos.get("shares", 0.0))
    ok = abs(held.shares - bs) <= 0.5
    L.append(f"   실보유 {held.shares:g}주 vs 봇 {bs:g}주  {'✅' if ok else '불일치'}")

    opens = broker.list_open_orders(SYMBOL)
    L.append(f"   미체결 {len(opens)}건")

    fills = broker.get_fills(SYMBOL, since)     # [K1] 날짜 루프 — 창이 길면 느리다
    L.append(f"   체결({since}~) {len(fills)}건")

    try:
        L.append(f"   예수금 ${broker.get_cash_usd():,.0f} "
                 f"(Pool ${float(pos.get('pool',0)):,.0f})")
    except Exception as e:
        L.append(f"   예수금 조회 생략: {e}")

    notify("\n".join(L))
    if not ok:
        notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주. "
               f"reconcile이 사다리를 중단시킨다. 수동 확인 필요.")
    return ok


# ══ 러너 ═══════════════════════════════════════════════════════════
def make_broker():
    # [N1] 공백/개행 방어
    ak = os.environ.get("KIWOOM_APPKEY", "").strip()
    sk = os.environ.get("KIWOOM_SECRETKEY", "").strip()
    acc = os.environ.get("KIWOOM_ACCOUNT", "").strip()
    if not (ak and sk):
        raise SystemExit("환경변수 필요: KIWOOM_APPKEY / KIWOOM_SECRETKEY")
    return GuardedKiwoom(ak, sk, acc, mock=KIWOOM_MOCK, excd=EXCD)


def run():
    # [L1] 실전(MOCK=off)에서 실주문하려면 LIVE_ARM 필요
    if (not DRY_RUN) and (not KIWOOM_MOCK) and (not LIVE_ARM):
        msg = ("⛔ 기동 거부 — 키움 <b>실계좌</b>에 실주문을 내려 합니다.\n"
               "   LIVE_ARM=on 을 함께 켜야 합니다(이중 잠금).\n"
               "   먼저 모의(KIWOOM_MOCK=on)로 완주하세요.")
        try: bot._tg(msg)
        except Exception: pass
        raise SystemExit(msg)

    if (not DRY_RUN) and (not AUTO_MODE):
        msg = ("⛔ 기동 거부 — DRY_RUN=off 인데 AUTO_MODE=off.\n"
               "   체결이 자동동기화 + 수동 /buy 로 두 번 반영됩니다.")
        try: bot._tg(msg)
        except Exception: pass
        raise SystemExit(msg)

    mode = ("DRY" if DRY_RUN else "LIVE") + ("/모의" if KIWOOM_MOCK else "/실전")
    banner = (f"⚙️ 키움 {mode} · AUTO_MODE={'on' if AUTO_MODE else 'off'} · "
              f"자동복귀={'on' if AUTO_RECOVER else 'off'} · 거래소={EXCD} · "
              f"상한 보유×{CAP_RATIO}(min {CAP_FLOOR}주, 동적)")
    if AUTO_MODE and not AUTO_RECOVER:   # [중4] 복귀 교착 위험 조합
        banner += ("\n⚠️ AUTO_MODE=on · 자동복귀=off — 복귀신호 시 /enter가 거부되어 CASH 고착 위험. "
                   "키움 LIVE는 자동복귀=on 권장(탈출구는 /setpos뿐).")
    if AUTO_MODE:   # 입출금 안내 — ★2026-07-23 목돈 자동집행 도입으로 절차 자체가 바뀌었다.
        banner += ("\nℹ️ 입출금: <code>/lumpsum ±금액 v</code>(목돈공식·장중 자동집행) 또는 "
                   "<code>/lumpsum ±금액 pool</code>(Pool만·즉시). 크론 정지·SYNC_SINCE 조작 불필요.")
    print(banner)

    df  = bot.build_data()
    # [치명1/봇 8번 이식] 봇 main과 동일하게 '완성된 전일 종가' 단일 뷰로 통일.
    #   장중 크론(예: 23:40 KST=10:40 ET)에서 미완성 당일봉으로 킬스위치·월말·price_hint를
    #   판정하는 드리프트 차단. attrs(티커별 신선도)는 슬라이스에서 유실될 수 있어 명시 이관.
    _df2 = bot._drop_live_bar(df)
    if _df2 is not df: _df2.attrs = df.attrs
    df = _df2
    pos = bot.load_position()

    broker   = make_broker()
    notifier = Notifier(bot._tg)
    auto     = LadderAutomator(broker, SYMBOL, dry_run=DRY_RUN, notify=notifier)

    # ★R2 게이트(2026-07-23): 목돈 주문이 체결 대기 중이면 사다리를 배치하지 않는다.
    #   day_only 재배치라 cancel-first가 목돈 주문까지 취소하고, shares는 체결 전(구주수)인데
    #   V만 신규라 매수단 전체가 시장가 위에 깔려 즉시 폭주 체결된다(실측).
    _orig_rotate = auto.rotate_cycle
    def _gated_rotate(pos, *a, **kw):
        if pos.get("lump_in_flight"):
            notifier("⏸️ 목돈 체결 대기 — 오늘 사다리 배치 보류(동기화 후 재개)")
            return []
        return _orig_rotate(pos, *a, **kw)
    auto.rotate_cycle = _gated_rotate

    since = rolling_since(5)
    if SYNC_SINCE and SYNC_SINCE > since:
        since = SYNC_SINCE
        notifier(f"ℹ️ SYNC_SINCE={SYNC_SINCE} 적용")

    if not DRY_RUN:
        try:
            pos = auto.sync_fills(pos, since)
            bot.save_position(pos)
        except Exception as e:
            bot._tg(f"🚨 체결동기화 실패 — 이후 단계 중단(안전): {e}")
            notifier.flush()
            raise

        # ★R2 사후처리: 목돈 주문의 체결 확정 여부 판정 → 예산·사다리 재정렬(수동 /lumpsum_done과 동일 의미)
        _oid = pos.get("lump_in_flight")
        if _oid:
            _filled = any(str(k).split(":")[1:2] == [str(_oid)] for k in (pos.get("fills_seen") or {}))
            if _filled:
                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
                pos["cyc_used"]   = 0.0          # K-D: 목돈 체결분이 사다리 예산을 먹지 않도록 여기서 리셋
                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
                bot.save_position(pos)
                notifier("✅ 목돈 체결 확정 — 매수한도 재설정·사다리 재개")
            else:
                try: _open = broker.list_open_orders(SYMBOL)
                except Exception: _open = [{"_unknown": True}]
                if not _open:                    # DAY 만료·취소로 소멸 → 매매 없이 V만 바뀐 상태
                    pos.pop("lump_in_flight", None); bot.save_position(pos)
                    notifier("🚨 목돈 주문 미체결 소멸 — 매매 없이 V만 변경된 상태입니다. "
                             "<code>/status</code>로 확인 후 재예약하거나 <code>/setv</code>로 되돌리세요.")

        # ★K-B 교정: 어댑터가 last_recover_check를 '집행/확정일'(UTC today)로 찍는다.
        #   봇 /exit와 동일하게 '판정일'(evac_sig_date, 7일 이내)로 교정 — 그 사이 월말이
        #   소급복귀 후보에서 빠져 복귀가 최대 한 달 지연되는 것을 막는다.
        try:
            _esd = pos.get("evac_sig_date")
            if pos.get("state") == "CASH" and _esd:
                _fresh = 0 <= (bot._wall_today() - bot.pd.Timestamp(_esd)).days <= 7
                if _fresh and pos.get("last_recover_check") != _esd:
                    pos["last_recover_check"] = _esd
                    pos.pop("evac_sig_date", None)
                    bot.save_position(pos)
                    notifier(f"ℹ️ 소급복귀 기준일 교정 → {_esd}(대피 판정일)")
        except Exception:
            pass

        # ★미신고 입출금 감지 — 체결 반영 직후라 남는 차이는 외부 입출금뿐. 알림만(자동처리 안 함).
        try:
            _openq = broker.list_open_orders(SYMBOL)      # K-E: 미체결이 있으면 증거금 차감으로 오탐 → 스킵
            if not _openq:
                _cash = float(broker.get_cash_usd())
                _gap  = _cash - float(pos.get("pool", 0.0))
                if abs(_gap) >= CASH_GAP_ALERT and not pos.get("pending_lump"):
                    _a = "입금" if _gap > 0 else "출금"
                    notifier(f"💡 <b>{_a} 감지 {abs(_gap):,.0f} USD</b> — 예수금 {_cash:,.0f} vs 원장 Pool {pos.get('pool',0):,.0f}\n"
                             f"   목돈이면 <code>/lumpsum {_gap:+.0f} v</code>, Pool 조절이면 <code>/lumpsum {_gap:+.0f} pool</code>을 보내세요.\n"
                             f"   (자동 처리하지 않습니다 — 의도를 직접 정하셔야 합니다)")
        except Exception:
            pass

    px_col = ("TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
                              not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ")
    price_hint = float(df[px_col].iloc[-1])

    pos = bot.ensure_V(pos, price_hint)

    V_tmp = pos.get("V", 0.0) or (pos.get("shares", 0.0) * price_hint)
    if ON(bot.VOLTGT_ON) and pos.get("cyc_scale") is not None:
        scale = float(pos["cyc_scale"])
    else:
        rv = float(df["RV"].iloc[-1]) if not bot.pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale = (min(1.0, bot.VOLTGT_TARGET / rv)
                 if (ON(bot.VOLTGT_ON) and rv == rv and rv > 0) else 1.0)
    pos, cmd_results = bot.process_commands(pos, price_hint, V_tmp * scale)

    # ★목돈 자동 집행 — 명령 처리 직후·롤오버 전.
    #   AUTO_MODE에서만 자동. 수동 모드는 기존 /lumpsum_done 경로 유지(이중처리 방지).
    if AUTO_MODE or DRY_RUN:
        pos = apply_pending_lump(broker, pos, price_hint, notifier)

    # ★R6 교정(2026-07-23): 롤오버를 명령·목돈 뒤로. 봇 순서(commands→rollover)와 정렬.
    #   책 방식과도 일치 — 목돈을 먼저 반영하고 '새 Pool' 기준으로 V+Pool/G를 계산해야 한다.
    #   (기존 순서면 pool 즉시확정이 경계일과 겹칠 때 lump/G(=10%)만큼 미반영)
    pos, roll_msg, cycle_changed = bot._cycle_rollover(pos, df)
    if cycle_changed:
        bot.save_position(pos)

    # [Q1] 프로브는 명령 처리 뒤
    probe(broker, pos, since, notifier)

    if pos.get("shares", 0) == 0 and pos.get("pool", 0) == 0 and not cmd_results:
        notifier.flush()
        bot._tg("⚠️ 포지션 미등록 — <code>/setpos</code> 먼저. 자동매매 스킵.")
        return

    # [중6] 복귀확정(sync)으로 cyc_budget이 pop된 상태면 봇 규칙(pool*BUY_LIMIT)으로 재설정.
    #   pop만 두면 다음 롤오버까지 매일 '현재 pool×50%'로 재계산되어 누적매수가 발산(부동예산).
    #   여기서 동결하면 봇 /enter(N1)의 "복귀일 Pool의 50% 총한도 동결" 의미를 정확히 미러.
    #   BUY_LIMIT은 bot 참조(봇 단일 진실). daily_run '전'에 실행 → 이번 회차부터 동결 적용.
    if pos.get("state") == "INVESTED" and pos.get("cyc_budget") is None:
        pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
        pos["cyc_used"] = 0.0
        bot.save_position(pos)

    # [강화안] 대피 예약취소 3회 실패로 남은 예약 재취소(대피조건 무관·최우선). 성공 시 플래그 해제.
    #   재매수 후 다음 실행에 대피조건이 해소(반등)됐어도 잔존 매수예약을 청소 → 폭락 재매수/킬스위치 무력화 방지.
    #   daily_run 전에 실행 → 이번 회차 사다리 재배치와 안 섞임.
    if pos.get("evac_recancel") and getattr(broker, "uses_reservation", False) and not DRY_RUN:
        try:
            c = broker.cancel_all_reservations(SYMBOL)
            bot._tg(f"🧹 대피 잔존 예약 {c}건 재취소 완료(취소실패 후속 청소)")
            pos.pop("evac_recancel", None); bot.save_position(pos)
        except Exception as e:
            bot._tg(f"⚠️ 대피 잔존 예약 재취소 실패 — 다음 실행 재시도: {e}")

    pos = daily_run(auto, pos, bot.compute_signal, df, since, bot.save_position,
                    auto_recover=AUTO_RECOVER, compute_ladder=bot.compute_ladder)

    try:
        ghost = broker.verify_placed(SYMBOL, since)
        if ghost: bot._tg(ghost)
    except Exception as e:
        bot._tg(f"🚨 접수주문 가시성 확인 중 오류: {e}")

    notifier.flush()

    s = bot.compute_signal(df, pos)
    head = [banner]
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg:
        head.append(f"🔄 {roll_msg}")
    report = "\n".join(head) + "\n\n" + bot.build_report(s, df)

    if bot._tg(report):
        bot._ping()
        # [치명A + DRY제외] 실제 예약이 '전량' 배치됐을 때만 래치. DRY는 place_ladder_reserve를 안 타
        #   카운터가 0 → 래치 안 함(DRY를 며칠 돌려도 사이클 안 잠김). DRY→LIVE 전환 시 그날 바로 실제 사다리 배치.
        #   부작용: DRY 리포트에 사다리 매일 재표시(=DRY 로그로 사다리 내용 확인 이점). 부분실패도 익일 자가치유.
        _need = len(s.get("buy_ladder", [])) + len(s.get("sell_ladder", []))
        if s.get("ladder_posted") and broker._ladder_rsv_n >= _need:
            pos["ladder_placed_for"] = str(s["cyc_start"]); bot.save_position(pos)
        rcd = s.get("recover_check_date")
        recovering = bool(s.get("ks_recover")) or (s.get("action_ks") == "🔵 복귀")
        if rcd and not recovering and rcd != pos.get("last_recover_check", ""):
            pos["last_recover_check"] = rcd; bot.save_position(pos)
    else:
        print("[경고] 텔레그램 전송 실패"); print(report)


if __name__ == "__main__":
    # ★[2026-07-17] 무인(야간) 재시도 래퍼 — 두 원칙 엄수:
    #   원칙1(절대): 전체가 절대 GitHub 한계(yml timeout)를 넘지 않는다. run()은 시작하면
    #     못 멈추므로, '다음 run을 시작하면 한계를 넘을지'를 매번 실측 기반으로 판정해 막는다.
    #   원칙2(적당): 한계 안에서 과하지 않게, 5분 간격으로 여러 번 시도(서버 회복 시간 확보).
    #   중간 실패는 조용히(알림 X). 최종 실패에만 알림 1번(도배 방지). 놓쳐도 다음날 소급복구.
    #   fail-fast: 비일시 오류(V괴리·토큰 등)는 재시도 없이 즉시 크래시.
    import time as _time
    _TRANSIENT = ("MCI", "전송 오류", "후처리", "timeout", "timed out",
                  "Connection", "Read timed", "temporarily", "일시", "잠시",
                  "Max retries", "Remote end", "Bad Gateway", "502", "503", "504")
    def _is_transient(e):
        s = str(e)
        return any(k.lower() in s.lower() for k in _TRANSIENT)

    _BUDGET     = 17 * 60      # 재시도 총예산 17분. yml timeout(아래 19분)보다 2분 여유=알림시간.
    _RETRY_GAP  = 5 * 60       # 재시도 간격 5분(서버 회복 시간).
    _ALERT_BUF  = 40           # 크래시 후 알림 전송 여유(초).
    _t0         = _time.time()
    _attempt    = 0
    _last_err   = None
    _last_run_s = 6 * 60       # 다음 run 소요 예측 초기값(첫 실측 전엔 6분 가정).
    while True:
        _elapsed = _time.time() - _t0
        # ★원칙1 핵심: 다음 run이 '실측된 소요시간'만큼 걸린다고 보고, 그게 예산을 넘으면 시작 안 함.
        #   (첫 run은 _attempt==0이라 무조건 1회는 실행 — 단 yml timeout이 최후 방어선.)
        if _attempt > 0 and (_elapsed + _last_run_s + _ALERT_BUF) >= _BUDGET:
            bot._emergency_tg(
                f"🚨 야간 재시도 {_attempt}회 실패(경과 {_elapsed/60:.1f}분) — 서버 장애 추정. "
                f"오늘 매매 스킵(다음 실행이 5영업일 소급으로 자동복구). 마지막: {_last_err}")
            print(f"[재시도 종료-예산] {_last_err}")
            raise SystemExit(1)
        _attempt += 1
        _rs = _time.time()
        try:
            run()
            break                              # 성공 → 종료
        except Exception as e:
            _last_run_s = _time.time() - _rs   # ★이번 run이 실제로 걸린 시간 → 다음 예측에 사용
            _last_err = e
            _elapsed = _time.time() - _t0
            if not _is_transient(e):            # 비일시 → 즉시 크래시
                bot._emergency_tg(e)
                print(f"[크래시-비일시] {e}"); traceback.print_exc()
                raise
            # 5분 대기 전에도 검사: 대기 후 다음 run이 예산 넘으면 대기 생략 → 즉시 판정.
            if (_elapsed + _RETRY_GAP + _last_run_s + _ALERT_BUF) >= _BUDGET:
                print(f"[대기 생략 — 남은시간 부족, 경과 {_elapsed/60:.1f}분]")
                continue
            print(f"[야간 재시도 {_attempt}회 경과 {_elapsed/60:.1f}분, "
                  f"직전 run {_last_run_s/60:.1f}분] {e} → 5분 후 재시도(조용히)")
            _time.sleep(_RETRY_GAP)
