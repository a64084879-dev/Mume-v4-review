# -*- coding: utf-8 -*-
"""
vr_auto_runner_kis.py — vr_signal_bot <-> vr_kis_adapter 글루 [KIS 전용]  rev.3
════════════════════════════════════════════════════════════════════════
★ 불가침 (한 글자도 수정하지 않는다) ★
    vr_signal_bot.py      공통 신호 계층   완성·검증
    vr_broker_adapter.py  공통 프레임워크  완성·검증
    vr_kis_adapter.py     한투 어댑터      완성·검증
    vr_toss_adapter.py    토스 어댑터      완성·검증
    vr_kiwoom_adapter.py  키움 어댑터      완성·검증
  이 러너는 '새 파일'이며, 위 다섯을 import·상속만 한다.

★ 트랙 정리 (2026-07-12 확정) ★
  · 자동화 트랙 = 사다리 단일화. 어댑터 체인 전체(DAY 매일 fresh 재배치,
    budget_override, cancel-first, 예약주문)가 사다리 전제로 설계·검증됨.
  · LOC는 별개 트랙(수동 신호)의 결정이었고, 자동화로 그 이유가 소멸.
    백테스트 <0.33%는 'LOC 우위'가 아니라 '사다리 기준 LOC 동등성' 검증.
  · 어댑터의 ORD_DVSN 34(LOC) 매핑은 데드코드가 아니라 대피·복귀용 예약분.
  · OrderReq.order_kind로 주문종류가 이미 어댑터 계층에 분리돼 있음.
  → 주문 종류에 대해 이 러너는 아무것도 바꾸지 않는다.

★ KIS 전용 ★ GuardedKIS의 스키마 가드가 KIS 응답 필드명에 묶여 있다.
  한투 = 모의 검증 전용. 실전은 토스·키움.
  토스/키움 러너는 make_broker() + GuardedXXX만 교체(핵심 로직은 증권사 무관).
  단 스키마 가드는 해당 증권사 필드가 '실측 확정'된 뒤에만 작성 가능.

━━ 러너가 봉합하는 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 [G1] 스키마 가드 — 어댑터가 실제로 .get() 하는 필드를 '전부' 검사.
      어댑터의 예외전파는 rt_cd≠0만 막는다. '200 OK인데 필드명이 다른 경우'는
      조용히 0/[]로 떨어진다. 그 필드들이 지금 [부분확인]이다.
        · ovrs_cblc_qty 오인 → get_holdings=0주 → killswitch "실보유 0 확인 —
          CASH 확정" → 주식 그대로인데 대피 완료 기록 (무음실패)
        · nccs_qty 오인 → list_open_orders=[] → cancel-first 통과 → 이중 사다리
        · ord_dt 오인 → sync_fills dedup 키 붕괴. KIS ODNO는 '일자별 채번'이라
          filled_at="" 이면 다른 날 같은 번호끼리 충돌 → 체결 유실
      ※ rev.1 자기감사에서 '식별자(pdno)만 검사' 버전이 위 두 실패를 그대로
        통과시키는 것을 시뮬레이션으로 실증 → 수량 필드까지 확장.

 [G2] AUTO_MODE — 체결보고성 명령 거부.
      apply_command '/buy'와 sync_fills가 둘 다 shares/pool/cyc_used를 건드린다.
      자동 켠 채 /buy 보내면 같은 체결이 2번 반영.

 [G3] 실행순서 — sync_fills를 rollover보다 먼저.
      'rollover → sync' 순이면 사이클 마지막 세션에 체결이 난 날:
        ① 체결 반영 전 pool로 V=V+pool/G → V 왜곡
        ② 같은 stale pool로 cyc_budget 스냅샷 + cyc_used=0 리셋
        ③ 직후 sync가 구사이클 체결 cost를 새 cyc_used에 적재 → 매수한도 선소진
      sync_fills는 fills_seen 멱등 → 먼저 1회 호출해도 daily_run 내부 2차 sync는 no-op.

 [G4] 프로브 — DRY에서도 조회를 실제로 태운다.
      dry_run이면 sync_fills/reconcile/rotate_cycle이 전부 `if dry_run: return`
      → get_holdings·list_open_orders·get_fills가 한 번도 호출되지 않는다
      → 스키마 가드가 발동할 기회가 없다 → DRY가 KIS를 아무것도 검증 못 한다.

━━ rev.3 수정 (rev.2 자기감사) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 [R1] 🔴 STRICT_CCNL 오탐. rev.2는 ccnl '모든 행'을 세어 중복을 판정했는데,
      어댑터는 모의에서 CCLD_NCCS_DVSN="00"(전체)로 조회한다 → 미체결 행이 섞여
      온다. 같은 주문이 미체결행+체결행으로 나뉘면 (일자,ODNO) 키가 겹쳐
      '주문당 다행'으로 오판 → 첫 체결이 나는 날 봇이 정지한다.
      → 어댑터가 '실제로 채택하는 행'(해당 심볼 + 체결수량>0)만 대상으로 좁힘.
 [R2] 🟠 텔레그램 4096자. rev.2는 프로브+버퍼+명령결과+리포트를 한 메시지로
      합쳤다 → 체결 많은 날 전송 실패 → 그 안의 체결 알림이 통째로 소실.
      → 버퍼는 '별도 메시지'로 분리 전송. 리포트가 죽어도 체결 기록은 산다.
 [R3] 🟢 프로브의 주수 대조 결과(recon_ok)가 죽은 변수였다 → 불일치면 경보.

━━ 운영 전제 (코드로 막을 수 없음) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ★ 기존 vr_signal_bot.py 크론(07:37)을 반드시 삭제/비활성화할 것. ★
   AUTO_MODE 가드는 이 러너 안에서만 산다. 옛 봇이 자기 워크플로로 계속 돌면
   패치 안 된 apply_command가 /buy를 그대로 먹고(이중반영), 두 프로세스가
   vr_position.json·offset 파일을 동시에 쓴다. 러너가 신호+리포트+명령을 모두
   포함하므로 옛 크론은 중복이다.

━━ 모의 1단계 설계 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · use_reserve=False (정규주문). 모의는 예약주문 '조회'(TTTT3039R) 미지원 →
    걸린 예약을 API로 확인 불가. 검증 단계에서 검증 불가능한 경로는 쓰지 않는다.
  · 크론 23:40 KST (미국 개장 직후). 정규주문은 미국장 중에만 접수된다.
    신호 기준일(마지막 미국 종가=D-1)은 07:37이든 23:40이든 동일 → 단일 크론 통합.

━━ 환경변수 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  KIS_APPKEY / KIS_APPSECRET / KIS_CANO      (필수)
  KIS_ACNT_PRDT_CD=01  KIS_MOCK=on  USE_RESERVE=off  KIS_SYMBOL=TQQQ
  DRY_RUN=on        기본 ON. 주문 안 나감. 프로브는 실행(가드 검증됨).
  AUTO_MODE=off     ON이면 체결보고 명령 거부(자동 sync가 진실원)
  AUTO_RECOVER=off  복귀는 기본 수동(/enter). 대피만 자동 — 비대칭이 안전 방향.
  STRICT_CCNL=on    ccnl 주문당 다행 감지 시 중단
  SYNC_SINCE=       YYYY-MM-DD. 체결조회 시작일 하한(프리플라이트 테스트 체결 차단).
                    rolling_since(5)가 5영업일 뒤 이 값을 넘어서면 저절로 무력화됨.
  + TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, traceback

import vr_signal_bot as bot                    # main()은 __main__ 가드 안이라 import 안전
from vr_broker_adapter import LadderAutomator, daily_run, rolling_since
from vr_kis_adapter import KISAdapter, KISError

ON = bot.ON
DRY_RUN      = ON(os.environ.get("DRY_RUN", "on"))
AUTO_MODE    = ON(os.environ.get("AUTO_MODE", "off"))
AUTO_RECOVER = ON(os.environ.get("AUTO_RECOVER", "off"))
USE_RESERVE  = ON(os.environ.get("USE_RESERVE", "off"))
KIS_MOCK     = ON(os.environ.get("KIS_MOCK", "on"))
STRICT_CCNL  = ON(os.environ.get("STRICT_CCNL", "on"))
SYNC_SINCE   = os.environ.get("SYNC_SINCE", "").strip()
SYMBOL       = os.environ.get("KIS_SYMBOL", "TQQQ")

TG_LIMIT = 3800   # 텔레그램 단일 메시지 상한 4096 — 여유 두고 자름

# 체결을 '보고'하는 명령 = sync_fills와 진실원이 겹침 → AUTO_MODE에서 거부.
# /setpos·/setv·/setcycle·/reset 은 의도적 '수리' 명령이라 허용(틀리면 reconcile이 잡음).
BLOCKED_IN_AUTO = {"/buy", "/sell", "/exit", "/enter", "/deposit_done", "/lumpsum_done"}


# ══ [R2] 알림 — 경보는 즉시, 나머지는 별도 메시지로 묶어 전송 ═══════
class Notifier:
    URGENT = ("🚨", "🔴", "⚠", "⛔")
    def __init__(self, sink):
        self.sink = sink; self.buf = []
    def __call__(self, m):
        head = m.lstrip()[:3]
        if any(u in head for u in self.URGENT):
            self.sink(m)                     # 경보는 즉시 — 크래시해도 남는다
        else:
            self.buf.append(m)
    def flush(self):
        """[R2] 리포트에 합치지 않는다. 합치면 4096자 초과 시 체결 알림까지 소실."""
        if not self.buf:
            return
        chunk = []
        for m in self.buf:
            if sum(len(x) + 1 for x in chunk) + len(m) > TG_LIMIT and chunk:
                self.sink("\n".join(chunk)); chunk = []
            chunk.append(m)
        if chunk:
            self.sink("\n".join(chunk))
        self.buf = []


# ══ [G1] 스키마 가드 ═══════════════════════════════════════════════
class GuardedKIS(KISAdapter):
    """어댑터 무수정 — 상속만 한다. 필드 계약 검증만 덧씌운다.

       ★ 어댑터가 실제로 .get() 하는 필드를 '전부' 검사해야 한다.
         식별자(pdno)만 검사하면 수량 필드가 틀렸을 때 조용히 0/[]로 떨어져,
         가드가 막겠다고 선언한 무음실패가 그대로 재현된다(rev.1 실증)."""
    _EXPECT = {
        "balance":  ["ovrs_pdno", "ovrs_cblc_qty"],
        "open_ord": ["pdno", "odno", "nccs_qty"],
        "fills":    ["pdno", "odno", "ft_ccld_qty", "ft_ccld_unpr3", "ord_dt"],
    }
    # sll_buy_dvsn_cd는 어댑터가 이미 fail-fast(KISError) → 중복 검사 불필요.

    def _get_paged(self, path, tr_key, params, err, list_key="output", max_pages=10):
        rows = super()._get_paged(path, tr_key, params, err, list_key, max_pages)
        need = self._EXPECT.get(tr_key, [])
        if rows and need:
            miss = [k for k in need if not any(k in r for r in rows)]
            if miss:
                raise KISError(
                    f"🔴 스키마 불일치[{tr_key}]: 누락 {miss}. "
                    f"조용한 0/[] 반환 = 킬스위치 무음실패·이중사다리 경로 → 중단. "
                    f"실제 키={list(rows[0].keys())}")
        if STRICT_CCNL and tr_key == "fills" and rows:
            self._check_fill_rows(rows)
        return rows

    def _check_fill_rows(self, rows):
        """sync_fills는 '(ord_dt:ODNO)당 누계 1행'을 전제한다.
           체결건당 다행이면 delta<=0 → continue → 체결 유실 → shares 과소.

           [R1] 어댑터는 모의에서 CCLD_NCCS_DVSN="00"(전체)로 조회한다 →
           미체결 행이 섞여 온다. 전체 행을 세면 같은 주문의 미체결행+체결행이
           키 충돌을 일으켜 '다행'으로 오판 → 첫 체결일에 봇 정지.
           → 어댑터가 '실제로 채택하는 행'만 대상으로 좁힌다(get_fills와 동일 필터)."""
        adopted = [r for r in rows
                   if r.get("pdno") == SYMBOL
                   and float(r.get("ft_ccld_qty", 0) or 0) > 0]
        seen = {}
        for r in adopted:
            k = f"{r.get('ord_dt','')}:{r.get('odno','')}"
            seen[k] = seen.get(k, 0) + 1
        dup = {k: v for k, v in seen.items() if v > 1}
        if dup:
            raise KISError(
                f"🔴 ccnl 주문당 다행 감지 {dup} — sync_fills의 delta dedup 전제 위반. "
                f"체결 유실 위험 → 중단. (STRICT_CCNL=off 로 무시 가능하나 비권장)")


# ══ [G2] AUTO_MODE 가드 ════════════════════════════════════════════
_orig_apply = bot.apply_command

def _guarded_apply(pos, text, price_hint, Veff_target=None):
    t = (text or "").strip().split()
    cmd = t[0].lower().split("@", 1)[0] if t else ""
    if AUTO_MODE and cmd in BLOCKED_IN_AUTO:
        return pos, (f"⛔ AUTO_MODE — <code>{cmd}</code> 거부.\n"
                     f"   체결은 증권사 API로 자동 동기화됩니다(이중반영 방지).\n"
                     f"   수동 개입이 필요하면 AUTO_MODE=off 후 실행.")
    return _orig_apply(pos, text, price_hint, Veff_target)

bot.apply_command = _guarded_apply


# ══ [G4] 조회 전용 프로브 — DRY에서도 항상 실행 ════════════════════
def probe(broker, pos, since, notify):
    """DRY에서는 sync/reconcile/rotate가 전부 스킵되어 KIS 조회가 한 번도
       일어나지 않는다 = 스키마 가드가 발동할 기회가 없다.
       → 주문은 내지 않고 조회 4종만 실제로 태워 가드를 발동시킨다."""
    L = ["🔍 <b>조회 프로브</b> (주문 없음)"]
    L.append(f"   현재가 ${broker.get_price(SYMBOL):,.2f}")

    held = broker.get_holdings(SYMBOL)                   # ← balance 스키마 가드
    bs = float(pos.get("shares", 0.0))
    ok = abs(held.shares - bs) <= 0.5
    L.append(f"   실보유 {held.shares:g}주 vs 봇 {bs:g}주  {'✅' if ok else '불일치'}")

    opens = broker.list_open_orders(SYMBOL)              # ← nccs 스키마 가드
    L.append(f"   미체결 {len(opens)}건")

    fills = broker.get_fills(SYMBOL, since)              # ← ccnl 스키마 + 행구조 가드
    L.append(f"   체결({since}~) {len(fills)}건")

    try:
        L.append(f"   주문가능 ${broker.get_cash_usd():,.0f} "
                 f"(Pool ${float(pos.get('pool',0)):,.0f} · 증거금 차감분이라 참고용)")
    except Exception as e:
        L.append(f"   주문가능 조회 생략: {e}")

    notify("\n".join(L))
    # [R3] 주수 불일치는 죽은 변수로 두지 않는다 — 경보로 올린다.
    if not ok:
        notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주. "
               f"reconcile이 사다리를 중단시킨다. 수동 확인 필요.")
    return ok


# ══ 러너 ═══════════════════════════════════════════════════════════
def make_broker():
    ak, sk, cano = (os.environ.get("KIS_APPKEY"), os.environ.get("KIS_APPSECRET"),
                    os.environ.get("KIS_CANO"))
    if not (ak and sk and cano):
        raise SystemExit("환경변수 필요: KIS_APPKEY / KIS_APPSECRET / KIS_CANO")
    return GuardedKIS(ak, sk, cano,
                      acnt_prdt_cd=os.environ.get("KIS_ACNT_PRDT_CD", "01"),
                      mock=KIS_MOCK, use_reserve=USE_RESERVE)


def run():
    mode = ("DRY" if DRY_RUN else "LIVE") + ("/모의" if KIS_MOCK else "/실전")
    banner = (f"⚙️ 자동매매 {mode} · AUTO_MODE={'on' if AUTO_MODE else 'off'} · "
              f"자동복귀={'on' if AUTO_RECOVER else 'off'} · "
              f"예약주문={'on' if USE_RESERVE else 'off'}")
    print(banner)

    df  = bot.build_data()
    pos = bot.load_position()

    broker   = make_broker()
    notifier = Notifier(bot._tg)
    auto     = LadderAutomator(broker, SYMBOL, dry_run=DRY_RUN, notify=notifier)

    # 체결조회 창 하한 — 프리플라이트 테스트 체결이 빨려들어오는 것 차단
    since = rolling_since(5)
    if SYNC_SINCE and SYNC_SINCE > since:
        since = SYNC_SINCE
        notifier(f"ℹ️ SYNC_SINCE={SYNC_SINCE} 적용 (5영업일 뒤 자동 해제)")

    # ① [G4] 프로브 — DRY 포함 항상. 스키마 가드가 여기서 발동한다.
    probe(broker, pos, since, notifier)

    # ② [G3] sync_fills 먼저 (구사이클 pool 확정).
    #    DRY면 어차피 no-op → 스킵(중복 알림 방지).
    if not DRY_RUN:
        try:
            pos = auto.sync_fills(pos, since)
            bot.save_position(pos)
        except Exception as e:
            bot._tg(f"🚨 체결동기화 실패 — 이후 단계 중단(안전): {e}")
            notifier.flush()
            raise

    px_col = "TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
                             not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ"
    price_hint = float(df[px_col].iloc[-1])

    # ③ ensure_V → rollover (체결 반영된 pool로 V·cyc_budget 스냅샷)
    pos = bot.ensure_V(pos, price_hint)
    pos, roll_msg, cycle_changed = bot._cycle_rollover(pos, df)
    if cycle_changed:
        bot.save_position(pos)

    # ④ 명령 처리 (AUTO_MODE면 체결보고 명령 거부)
    V_tmp = pos.get("V", 0.0) or (pos.get("shares", 0.0) * price_hint)
    if ON(bot.VOLTGT_ON) and pos.get("cyc_scale") is not None:
        scale = float(pos["cyc_scale"])
    else:
        rv = float(df["RV"].iloc[-1]) if not bot.pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale = (min(1.0, bot.VOLTGT_TARGET / rv)
                 if (ON(bot.VOLTGT_ON) and rv == rv and rv > 0) else 1.0)
    pos, cmd_results = bot.process_commands(pos, price_hint, V_tmp * scale)

    if pos.get("shares", 0) == 0 and pos.get("pool", 0) == 0 and not cmd_results:
        notifier.flush()
        bot._tg("⚠️ 포지션 미등록 — <code>/setpos</code> 먼저. 자동매매 스킵.")
        return

    # ⑤ daily_run — 내부 sync는 멱등 no-op. compute_ladder 필수(DAY-only 브로커).
    pos = daily_run(auto, pos, bot.compute_signal, df, since, bot.save_position,
                    auto_recover=AUTO_RECOVER, compute_ladder=bot.compute_ladder)

    # ⑥ [R2] 버퍼 알림 먼저 별도 전송 — 리포트가 길어 죽어도 체결 기록은 산다.
    notifier.flush()

    # ⑦ 리포트 (daily_run이 중간 return해도 항상 발송)
    s = bot.compute_signal(df, pos)
    head = [banner]
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg:
        head.append(f"🔄 {roll_msg}")
    report = "\n".join(head) + "\n\n" + bot.build_report(s, df)

    if bot._tg(report):
        bot._save_last(str(s["today"].date()))
        bot._ping()
        if s.get("is_cycle_start"):
            pos["ladder_placed_for"] = str(s["cyc_start"]); bot.save_position(pos)
        rcd = s.get("recover_check_date")
        recovering = bool(s.get("ks_recover")) or (s.get("action_ks") == "🔵 복귀")
        if rcd and not recovering and rcd != pos.get("last_recover_check", ""):
            pos["last_recover_check"] = rcd; bot.save_position(pos)
    else:
        print("[경고] 텔레그램 전송 실패"); print(report)


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        bot._emergency_tg(e)
        print(f"[크래시] {e}"); traceback.print_exc()
        raise     



# -*- coding: utf-8 -*-
"""
kis_mock_preflight.py — KIS 모의투자 '필드 실측기'
════════════════════════════════════════════════════════════════════════
목적: 자동매매 배선 전에 vr_kis_adapter.py가 [부분확인]/[실측확정 대기]로
      남겨둔 필드명·행구조를 raw 응답으로 확정한다.

⚠️ 설계 원칙: 어댑터를 import하지 않는다.
   어댑터의 가정(ovrs_pdno, ft_ccld_qty …)이 '검증 대상'이므로,
   어댑터를 통해 조회하면 틀린 가정이 그대로 0/[]로 은폐된다.
   → 여기서는 tr_id·params만 어댑터와 동일하게 쓰고, 응답은 생짜로 본다.

확정 대상 6종:
  ① balance  output1 : ovrs_pdno / ovrs_cblc_qty / pchs_avg_pric
  ② nccs             : pdno / odno / nccs_qty / sll_buy_dvsn_cd / ft_ord_unpr3
  ③ ccnl             : pdno / odno / ft_ccld_qty / ft_ccld_unpr3 / sll_buy_dvsn_cd
                       + ★행구조(주문당 1행 누계 vs 체결건당 다행) ← 최대 리스크
  ④ psbl             : ord_psbl_frcr_amt
  ⑤ SLL_TYPE="00"    : 매도 수용 여부
  ⑥ 수수료 실제 필드 : frcr_ccld_amt2가 수수료인가 체결금액인가

실행:
  export KIS_APPKEY=...  KIS_APPSECRET=...  KIS_CANO=8자리
  python kis_mock_preflight.py              # 조회만 (주문 없음, 아무때나 실행 가능)
  python kis_mock_preflight.py --order      # 1주 실주문 사이클 (★미국장 중에만★)

--order 시나리오 (모두 1주, 모의계좌):
  P6  매수 1주 @ 현재가-20%  → 미체결 유도 → ODNO 확보
  P7  nccs 재조회            → ② 필드 확정 + 방금 주문이 보이는가
  P8  취소 (ORGN_ODNO, ORD_QTY=1)
  P9  nccs 재조회            → 0건 확인 (cancel-first 신뢰성)
  P10 매수 1주 @ 현재가+3%   → 체결 유도
  P11 ccnl 원문              → ③ 필드·행구조·수수료 확정  ★핵심
  P12 balance 재조회         → ① 필드 확정 (1주 반영되는가)
  P13 매도 1주 SLL_TYPE="00" → ⑤ 수용 여부
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, sys, json, time, datetime, requests

MOCK = "https://openapivts.koreainvestment.com:29443"
AK   = os.environ.get("KIS_APPKEY", "")
SK   = os.environ.get("KIS_APPSECRET", "")
CANO = os.environ.get("KIS_CANO", "")
ACNT = os.environ.get("KIS_ACNT_PRDT_CD", "01")
SYMB = os.environ.get("KIS_SYMBOL", "TQQQ")
EXCD_ORD = "NASD"   # 주문·잔고
EXCD_PRC = "NAS"    # 시세

DO_ORDER = "--order" in sys.argv

TR = {  # 어댑터와 동일 (모의)
    "buy": "VTTT1002U", "sell": "VTTT1001U", "cancel": "VTTT1004U",
    "balance": "VTTS3012R", "nccs": "VTTS3018R", "ccnl": "VTTS3035R",
    "psbl": "VTTS3007R", "price": "HHDFS00000300",
}

# 어댑터가 '가정'하고 있는 필드명 — 이게 맞는지 보는 게 이 스크립트의 전부
ASSUMED = {
    "balance.output1": ["ovrs_pdno", "ovrs_cblc_qty", "pchs_avg_pric"],
    "nccs.output":     ["pdno", "odno", "nccs_qty", "sll_buy_dvsn_cd", "ft_ord_unpr3"],
    "ccnl.output":     ["pdno", "odno", "ft_ccld_qty", "ft_ccld_unpr3", "sll_buy_dvsn_cd",
                       "ord_dt"],   # ★ord_dt = sync_fills dedup 키. ODNO는 일자별 채번이라 필수.
    "psbl.output":     ["ord_psbl_frcr_amt"],
}

S = requests.Session()
_tok = {"v": None, "exp": 0}
VERDICT = []   # (항목, 상태, 메모)


def log(*a): print(*a, flush=True)
def hr(t=""): log("\n" + "━" * 68); log(t) if t else None


def auth():
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    r = S.post(f"{MOCK}/oauth2/tokenP",
               headers={"content-type": "application/json"},
               data=json.dumps({"grant_type": "client_credentials",
                                "appkey": AK, "appsecret": SK}), timeout=10)
    r.raise_for_status(); d = r.json()
    if "access_token" not in d:
        raise SystemExit(f"❌ 인증 실패: {d}")
    _tok["v"] = d["access_token"]
    _tok["exp"] = time.time() + int(d.get("expires_in", 86400))
    return _tok["v"]


def H(tr_id, hashkey=None):
    h = {"content-type": "application/json", "authorization": f"Bearer {auth()}",
         "appkey": AK, "appsecret": SK, "tr_id": tr_id, "custtype": "P"}
    if hashkey: h["hashkey"] = hashkey
    return h


def hashkey(body):
    r = S.post(f"{MOCK}/uapi/hashkey",
               headers={"content-type": "application/json", "appkey": AK, "appsecret": SK},
               data=json.dumps(body), timeout=10)
    r.raise_for_status(); return r.json()["HASH"]


def GET(path, tr, params, label):
    r = S.get(f"{MOCK}{path}", headers=H(TR[tr]), params=params, timeout=10)
    r.raise_for_status(); d = r.json()
    time.sleep(0.6)   # 모의 초당 2건
    ok = str(d.get("rt_cd")) == "0"
    log(f"  rt_cd={d.get('rt_cd')} msg_cd={d.get('msg_cd')} msg1={(d.get('msg1') or '').strip()}")
    if not ok:
        VERDICT.append((label, "❌ 호출실패", d.get("msg1")))
    return d, ok


def POST(path, tr, body, label):
    hk = hashkey(body)
    r = S.post(f"{MOCK}{path}", headers=H(TR[tr], hk), data=json.dumps(body), timeout=10)
    r.raise_for_status(); d = r.json()
    time.sleep(1.0)
    ok = str(d.get("rt_cd")) == "0"
    log(f"  rt_cd={d.get('rt_cd')} msg_cd={d.get('msg_cd')} msg1={(d.get('msg1') or '').strip()}")
    return d, ok


def audit(key, rows):
    """어댑터 가정 필드 vs 실제 키 대조."""
    want = ASSUMED[key]
    if not rows:
        log(f"  ⚪ {key}: 행 0개 — 필드 확정 불가(보유/주문 생긴 뒤 재실행)")
        VERDICT.append((key, "⚪ 미확정", "행 0개"))
        return
    actual = list(rows[0].keys())
    miss = [f for f in want if f not in actual]
    log(f"  실제 키({len(actual)}): {actual}")
    if miss:
        log(f"  🔴 어댑터 가정 필드 없음: {miss}")
        # 비슷한 후보 제안
        for m in miss:
            cand = [a for a in actual if any(t in a for t in m.split("_") if len(t) > 2)]
            log(f"      '{m}' 후보 → {cand or '없음'}")
        VERDICT.append((key, "🔴 필드불일치", f"없음: {miss}"))
    else:
        log(f"  ✅ 어댑터 가정 필드 전부 존재: {want}")
        VERDICT.append((key, "✅ 확정", "가정 일치"))
    log(f"  샘플 행: {json.dumps(rows[0], ensure_ascii=False)[:400]}")


# ══════════════════════════════════════════════════════════════
def main():
    if not (AK and SK and CANO):
        raise SystemExit("환경변수 필요: KIS_APPKEY / KIS_APPSECRET / KIS_CANO")

    hr("P0  인증")
    auth(); log("  ✅ 토큰 발급")

    hr("P1  현재가  (HHDFS00000300, EXCD=NAS)")
    d, ok = GET("/uapi/overseas-price/v1/quotations/price", "price",
                {"AUTH": "", "EXCD": EXCD_PRC, "SYMB": SYMB}, "price")
    px = float((d.get("output") or {}).get("last", 0) or 0)
    log(f"  {SYMB} last = ${px}")
    if px <= 0:
        raise SystemExit("❌ 현재가 0 — 지연시세/휴장/심볼 확인 필요. 중단.")
    VERDICT.append(("price", "✅ 확정", f"${px}"))

    hr("P2  잔고 원문  ① ovrs_pdno / ovrs_cblc_qty")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-balance", "balance",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "balance")
    if ok: audit("balance.output1", d.get("output1") or [])

    hr("P3  매수가능금액  ④ ord_psbl_frcr_amt")
    # 어댑터 get_cash_usd()는 OVRS_ORD_UNPR="0"으로 호출한다 → 그 파라미터를 그대로 시험.
    _d0, _ok0 = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "psbl",
                    {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                     "OVRS_ORD_UNPR": "0", "ITEM_CD": SYMB}, "psbl(어댑터 파라미터 unpr=0)")
    if not _ok0:
        log("  🟠 어댑터의 OVRS_ORD_UNPR='0'이 거부됨 → get_cash_usd() 상시 예외.")
        log("     (reconcile은 정보성 로그라 무해하나, 어댑터 수정 권장)")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "psbl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "OVRS_ORD_UNPR": f"{px:.2f}", "ITEM_CD": SYMB}, "psbl")
    if ok:
        o = d.get("output") or {}
        audit("psbl.output", [o] if o else [])
        _amt = float((o or {}).get("ord_psbl_frcr_amt", 0) or 0)
        log(f"  주문가능 USD = {_amt:,.2f}")
        if _amt <= 0:
            log("  🔴 외화 주문가능금액 0 — 모의계좌에 USD 예수금이 없다.")
            log("     → P6~P13(실주문) 전부 실패한다. KIS 모의투자 해외주식 신청/환전 확인 후 재실행.")
            VERDICT.append(("USD 예수금", "🔴 없음", "실주문 시험 불가"))

    hr("P4  미체결 원문  ② pdno / odno / nccs_qty / sll_buy_dvsn_cd")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    if ok: audit("nccs.output", d.get("output") or [])

    hr("P5  체결 원문  ③ ft_ccld_qty / 행구조 / 수수료")
    since = (datetime.date.today() - datetime.timedelta(days=14)).strftime("%Y%m%d")
    today = datetime.date.today().strftime("%Y%m%d")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-ccnl", "ccnl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT,
                 "ORD_STRT_DT": since, "ORD_END_DT": today,
                 "SORT_SQN": "DS", "OVRS_EXCG_CD": "",
                 "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00",
                 "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "ccnl")
    if ok:
        rows = d.get("output") or []
        audit("ccnl.output", rows)
        _row_structure(rows)

    if not DO_ORDER:
        _summary()
        log("\n💡 실주문 검증(P6~P13)은  --order  플래그 + ★미국장 시간★에.")
        return

    # ── 실주문 사이클 ──────────────────────────────────────────
    hr("P6  매수 1주 @ 현재가-20% (미체결 유도)")
    lo = round(px * 0.80, 2)
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
            "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{lo:.2f}",
            "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": ""}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "buy", body, "buy")
    if not ok:
        VERDICT.append(("정규매수", "❌ 실패", d.get("msg1")))
        _summary(); raise SystemExit("❌ 매수 접수 실패 — 이후 단계 중단")
    odno = (d.get("output") or {}).get("ODNO", "")
    log(f"  ODNO = {odno!r}")
    VERDICT.append(("정규매수", "✅ 접수", f"@{lo} ODNO={odno}"))

    hr("P7  nccs 재조회 — 방금 주문이 보이는가?")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    rows = d.get("output") or []
    audit("nccs.output", rows)
    hit = [r for r in rows if str(r.get("odno", "")).lstrip("0") == str(odno).lstrip("0")]
    if hit:
        log(f"  ✅ 방금 ODNO 발견 — list_open_orders 신뢰 가능")
        log(f"     sll_buy_dvsn_cd = {hit[0].get('sll_buy_dvsn_cd')!r}  (매수인데 이 값 → 02가 매수)")
        VERDICT.append(("nccs 추적", "✅ 확정", f"매수 코드={hit[0].get('sll_buy_dvsn_cd')!r}"))
    else:
        log("  🔴 방금 ODNO를 nccs에서 못 찾음 → cancel-first 무력 → 이중 사다리 위험!")
        VERDICT.append(("nccs 추적", "🔴 실패", "접수한 주문이 미체결조회에 없음"))

    hr("P8  취소 (ORGN_ODNO, ORD_QTY=1)")
    cb = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD, "PDNO": SYMB,
          "ORGN_ODNO": odno, "RVSE_CNCL_DVSN_CD": "02", "ORD_QTY": "1", "OVRS_ORD_UNPR": "0"}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order-rvsecncl", "cancel", cb, "cancel")
    VERDICT.append(("정규취소", "✅ 성공" if ok else "🔴 실패", d.get("msg1")))

    hr("P9  nccs 재조회 — 0건 확인")
    d, _ = GET("/uapi/overseas-stock/v1/trading/inquire-nccs", "nccs",
               {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                "SORT_SQN": "DS", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "nccs")
    rows = d.get("output") or []
    left = [r for r in rows if str(r.get("odno", "")).lstrip("0") == str(odno).lstrip("0")]
    log("  ✅ 취소 반영됨" if not left else f"  🔴 취소했는데 잔존: {left}")

    hr("P10 매수 1주 @ 현재가+3% (체결 유도)")
    hi = round(px * 1.03, 2)
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
            "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{hi:.2f}",
            "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": ""}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "buy", body, "buy2")
    odno2 = (d.get("output") or {}).get("ODNO", "")
    log(f"  ODNO = {odno2!r} @ {hi}")
    log("  ⏳ 체결 대기 20초…"); time.sleep(20)

    hr("P11 ccnl 원문  ★핵심: 행구조 + 수수료")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-ccnl", "ccnl",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT,
                 "ORD_STRT_DT": today, "ORD_END_DT": today,
                 "SORT_SQN": "DS", "OVRS_EXCG_CD": "",
                 "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00",
                 "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "ccnl")
    rows = d.get("output") or []
    audit("ccnl.output", rows)
    _row_structure(rows)
    _fee_check(rows)

    hr("P12 잔고 재조회  ① 1주 반영 확인")
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-balance", "balance",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}, "balance")
    r1 = d.get("output1") or []
    audit("balance.output1", r1)
    mine = [h for h in r1 if h.get("ovrs_pdno") == SYMB]
    if mine:
        log(f"  ✅ get_holdings 경로 정상: {mine[0].get('ovrs_cblc_qty')}주")
        VERDICT.append(("get_holdings", "✅ 확정", f"{mine[0].get('ovrs_cblc_qty')}주"))
    else:
        log(f"  🔴🔴 ovrs_pdno=={SYMB} 매치 실패 → get_holdings가 0주 반환 →")
        log(f"       killswitch가 '실보유 0 확인 — CASH 확정' 로 무음실패한다!")
        VERDICT.append(("get_holdings", "🔴🔴 치명", "심볼 매치 실패 = 킬스위치 무음실패"))

    hr("P13 매도 1주  ⑤ SLL_TYPE='00' 수용?")
    # ★[F7] P10이 미체결이면 보유 0 → 매도는 '잔고부족'으로 거부된다.
    #   그걸 'SLL_TYPE 거부'로 읽으면 오판정 → 실제로 멀쩡한 경로를 🔴로 낙인.
    _hq = float((mine[0].get("ovrs_cblc_qty", 0) or 0)) if mine else 0.0
    if _hq < 1:
        log("  ⚪ 보유 0주 (P10 미체결) — 매도 시험 스킵.")
        log("     보유 없이 매도하면 '잔고부족' 거부가 SLL_TYPE 거부로 오판된다.")
        VERDICT.append(("매도 SLL_TYPE=00", "⚪ 미확정", "P10 미체결 → 시험 불가"))
        _summary(); return
    sb = {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
          "PDNO": SYMB, "ORD_QTY": "1", "OVRS_ORD_UNPR": f"{round(px*0.90,2):.2f}",
          "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00", "SLL_TYPE": "00"}
    d, ok = POST("/uapi/overseas-stock/v1/trading/order", "sell", sb, "sell")
    VERDICT.append(("매도 SLL_TYPE=00", "✅ 수용" if ok else "🔴 거부", d.get("msg1")))
    if ok:
        log("  ✅ 킬스위치 매도 경로 유효")
    else:
        log("  🔴 매도 거부 → 사다리 매도 + 킬스위치 매도 전부 불가. SLL_TYPE 재확인 필요.")

    _summary()


def _row_structure(rows):
    """★ sync_fills의 delta dedup 전제 검증: 주문당 1행인가, 체결건당 다행인가."""
    if not rows:
        log("  ⚪ 체결 0건 — 행구조 판정 불가")
        return
    from collections import Counter
    # ★[F3] KIS ODNO는 '일자별 채번' → 다른 날 같은 번호가 존재한다.
    #   ODNO 단독으로 세면 14일 창에서 가짜 '주문당 다행'이 뜬다(오탐).
    #   반드시 (ord_dt, odno) 복합키. 이건 sync_fills의 dedup 키와도 동일해야 한다.
    if not any("ord_dt" in r for r in rows):
        log("  🔴 ord_dt 필드 없음 — sync_fills의 filled_at이 빈 문자열이 된다.")
        log("     → dedup 키가 ':ODNO:side'로 붕괴 → 다른 날 같은 ODNO끼리 충돌 → 체결 유실.")
        log("     → 실제 날짜 필드명을 찾아 어댑터 get_fills의 o.get('ord_dt') 교체 필요.")
        VERDICT.append(("ccnl ord_dt", "🔴🔴 치명", "dedup 키 붕괴"))
    c = Counter((str(r.get("ord_dt", "")), str(r.get("odno", ""))) for r in rows)
    dup = {f"{d}:{o}": v for (d, o), v in c.items() if v > 1}
    log(f"  행 {len(rows)}개 / 고유 (일자,ODNO) {len(c)}개")
    if dup:
        log(f"  🔴🔴 같은 ODNO 다행 발견: {dup}")
        log("       → sync_fills 전제('주문당 1행 누계') 위반!")
        log("         delta=f.qty-done 에서 2번째 행이 delta<=0 → continue → 체결 유실")
        log("         → shares 과소 → reconcile 불일치 → 매일 봇 정지")
        log("       → 수정 필요: seen[key] 를 '행별 누계 합산'으로 (key에 체결일련번호 추가)")
        VERDICT.append(("ccnl 행구조", "🔴🔴 치명", f"주문당 다행: {dup}"))
    else:
        log("  ✅ ODNO당 1행 — sync_fills의 delta dedup 전제 성립")
        VERDICT.append(("ccnl 행구조", "✅ 확정", "주문당 1행 누계"))


def _fee_check(rows):
    """⑥ frcr_ccld_amt2가 수수료인가 체결금액인가."""
    if not rows: return
    r = rows[0]
    q = float(r.get("ft_ccld_qty", 0) or 0)
    p = float(r.get("ft_ccld_unpr3", 0) or 0)
    if q <= 0 or p <= 0:
        log("  ⚪ 수량/단가 0 — 수수료 판정 불가"); return
    gross = q * p
    log(f"  체결금액(계산) = {q} × {p} = {gross:.2f}")
    for f in ("frcr_ccld_amt2", "cmsn", "frcr_ccld_amt1", "ovrs_excg_fee"):
        if f in r:
            try:
                v = float(r[f] or 0)
            except Exception:
                continue
            if v == 0:
                kind = "0"
            elif abs(v - gross) / gross < 0.02:
                kind = "🔴 체결금액! (수수료 아님 — Pool 이중차감 위험)"
            elif 0 < v <= gross * 0.01:
                kind = f"✅ 수수료 후보 (요율 {v/gross:.4%})"
            else:
                kind = "❓ 정체불명"
            log(f"  {f} = {v}  → {kind}")
    log(f"  ※ 어댑터 현재 추정요율 FEE_RATE=0.0035 → 예상 {gross*0.0035:.4f}")
    VERDICT.append(("수수료 필드", "🟡 수동판정", "위 출력 확인"))


def _summary():
    hr("판정 요약")
    w = max(len(a) for a, _, _ in VERDICT) if VERDICT else 10
    for item, st, memo in VERDICT:
        log(f"  {item.ljust(w)}  {st}   {str(memo or '')[:60]}")
    bad = [v for v in VERDICT if "🔴" in v[1]]
    log("\n" + ("🔴 치명 항목 있음 — 자동매매 배선 금지" if bad else
                "✅ 치명 항목 없음 — 다음 게이트 진행 가능"))


if __name__ == "__main__":
    main()






이것까지확인하고   


import os, getpass
os.environ["KIS_APPKEY"]    = getpass.getpass("모의 APPKEY: ")
os.environ["KIS_APPSECRET"] = getpass.getpass("모의 APPSECRET: ")
os.environ["KIS_CANO"]      = input("계좌번호 앞 8자리: ").strip()
print("입력 완료")


import json, requests

MOCK = "https://openapivts.koreainvestment.com:29443"
AK   = os.environ["KIS_APPKEY"]
SK   = os.environ["KIS_APPSECRET"]

r = requests.post(f"{MOCK}/oauth2/tokenP",
                  headers={"content-type": "application/json"},
                  data=json.dumps({"grant_type": "client_credentials",
                                   "appkey": AK, "appsecret": SK}),
                  timeout=10)
print("HTTP", r.status_code)
d = r.json()

if "access_token" in d:
    TOKEN = d["access_token"]
    os.environ["KIS_TOKEN"] = TOKEN
    print("✅ P0 인증 성공")
    print("   토큰 앞 20자:", TOKEN[:20], "...")
    print("   만료(초):", d.get("expires_in"))
else:
    print("❌ P0 인증 실패")
    print(json.dumps(d, ensure_ascii=False, indent=2))



import time

CANO = os.environ["KIS_CANO"]
ACNT = "01"
SYMB = "TQQQ"
EXCD_ORD = "NASD"   # 주문·잔고
EXCD_PRC = "NAS"    # 시세
S = requests.Session()

def H(tr_id):
    return {"content-type": "application/json",
            "authorization": f"Bearer {os.environ['KIS_TOKEN']}",
            "appkey": AK, "appsecret": SK,
            "tr_id": tr_id, "custtype": "P"}

def GET(path, tr_id, params, label):
    r = S.get(f"{MOCK}{path}", headers=H(tr_id), params=params, timeout=10)
    d = r.json()
    time.sleep(0.6)
    print(f"[{label}] HTTP {r.status_code} | rt_cd={d.get('rt_cd')} "
          f"msg_cd={d.get('msg_cd')} msg1={(d.get('msg1') or '').strip()}")
    return d, str(d.get("rt_cd")) == "0"

def show_keys(rows, name):
    if not rows:
        print(f"  ⚪ {name}: 행 0개 — 필드 확정 불가")
        return
    print(f"  실제 키 ({len(rows[0])}개): {list(rows[0].keys())}")
    print(f"  샘플 행: {json.dumps(rows[0], ensure_ascii=False)[:500]}")

print("헬퍼 준비 완료")


d, ok = GET("/uapi/overseas-price/v1/quotations/price", "HHDFS00000300",
            {"AUTH": "", "EXCD": EXCD_PRC, "SYMB": SYMB}, "P1 현재가")
px = float((d.get("output") or {}).get("last", 0) or 0)
print(f"  TQQQ last = ${px}")



d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-balance", "VTTS3012R",
            {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
             "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""},
            "P2 잔고")
rows = d.get("output1") or []
print(f"  보유 종목 {len(rows)}건")
show_keys(rows, "balance.output1")
print("\n  output2(요약):", json.dumps(d.get("output2") or {}, ensure_ascii=False)[:400])



for unpr in ("0", f"{px:.2f}"):
    d, ok = GET("/uapi/overseas-stock/v1/trading/inquire-psamount", "VTTS3007R",
                {"CANO": CANO, "ACNT_PRDT_CD": ACNT, "OVRS_EXCG_CD": EXCD_ORD,
                 "OVRS_ORD_UNPR": unpr, "ITEM_CD": SYMB},
                f"P3 매수가능(unpr={unpr})")
    if ok:
        o = d.get("output") or {}
        show_keys([o], "psbl.output")



이것까지인증하고   


[P2 잔고] HTTP 200 | rt_cd=0 msg_cd=70070000 msg1=모의투자 조회할 내역(자료)이 없습니다.
  보유 종목 0건
  ⚪ balance.output1: 행 0개 — 필드 확정 불가
  output2(요약): {"frcr_pchs_amt1": "0.00000", "ovrs_rlzt_pfls_amt": "0.00000", "ovrs_tot_pfls": "0.00000", "rlzt_erng_rt": "0.00000000", "tot_evlu_pfls_amt": "0.00000000", "tot_pftrt": "0.00000000", "frcr_buy_amt_smtl1": "0.000000", "ovrs_rlzt_pfls_amt2": "0.00000", "frcr_buy_amt_smtl2": "0.000000"} 5번맞나?




P3 매수가능(unpr=0)] HTTP 200 | rt_cd=0 msg_cd=20310000 msg1=모의투자 조회가 완료되었습니다.
  실제 키 (11개): ['tr_crcy_cd', 'ord_psbl_frcr_amt', 'sll_ruse_psbl_amt', 'ovrs_ord_psbl_amt', 'max_ord_psbl_qty', 'echm_af_ord_psbl_amt', 'echm_af_ord_psbl_qty', 'ord_psbl_qty', 'exrt', 'frcr_ord_psbl_amt1', 'ovrs_max_ord_psbl_qty']
  샘플 행: {"tr_crcy_cd": "USD", "ord_psbl_frcr_amt": "100000.00", "sll_ruse_psbl_amt": "0.00", "ovrs_ord_psbl_amt": "100000.00", "max_ord_psbl_qty": "0", "echm_af_ord_psbl_amt": "100000.00", "echm_af_ord_psbl_qty": "0", "ord_psbl_qty": "0", "exrt": "1504.2000000000", "frcr_ord_psbl_amt1": "99000.000000", "ovrs_max_ord_psbl_qty": "0"}
[P3 매수가능(unpr=77.03)] HTTP 200 | rt_cd=0 msg_cd=20310000 msg1=모의투자 조회가 완료되었습니다.
  실제 키 (11개): ['tr_crcy_cd', 'ord_psbl_frcr_amt', 'sll_ruse_psbl_amt', 'ovrs_ord_psbl_amt', 'max_ord_psbl_qty', 'echm_af_ord_psbl_amt', 'echm_af_ord_psbl_qty', 'ord_psbl_qty', 'exrt', 'frcr_ord_psbl_amt1', 'ovrs_max_ord_psbl_qty']
  샘플 행: {"tr_crcy_cd": "USD", "ord_psbl_frcr_amt": "100000.00", "sll_ruse_psbl_amt": "0.00", "ovrs_ord_psbl_amt": "100000.00", "max_ord_psbl_qty": "1285", "echm_af_ord_psbl_amt": "100000.00", "echm_af_ord_psbl_qty": "1285", "ord_psbl_qty": "1285", "exrt": "1504.2000000000", "frcr_ord_psbl_amt1": "99000.000000", "ovrs_max_ord_psbl_qty": "1285"}


이것까지하고 G1 만들던 단계다 이어서 진행해줘
