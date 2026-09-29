--- vr_auto_runner_toss_orig.py	2026-09-29 21:14:51.907602071 +0900
+++ vr_auto_runner_toss.py	2026-09-29 21:24:01.900125569 +0900
@@ -1,7 +1,26 @@
 # -*- coding: utf-8 -*-
 """
-vr_auto_runner_toss.py — vr_signal_bot <-> vr_toss_adapter 글루 [토스 전용]  rev.5
+vr_auto_runner_toss.py — vr_signal_bot <-> vr_toss_adapter 글루 [토스 전용]  rev.6
 ════════════════════════════════════════════════════════════════════════
+★ rev.6 (2026-09-29, ACCT-1 · 사양서 v0.5 "계좌 변동 감지·확인형 반영" 1단계) — 승인 전 초안.
+  · 정규 실행(22:30 KST)에서 체결 동기화 직후 실계좌(보유주수·현금)와 원장(shares·Pool)을 대조해
+    차이를 '건(#번호)'으로 만들어 리포트에서 묻고, 은박사님이 <code>/예 N</code>으로 답하면 다음 정규
+    실행이 재감지 후 반영한다. 반영은 전부 봇 명령(/setpos·/lumpsum)을 그대로 호출해 수행 —
+    러너에 새 원장 산식을 두지 않는다(= 손으로 치던 명령을 봇이 대신 침).
+  · 1단계 범위: 매매 없는 처리(원장 맞춤·Pool만·처음 등록) + 현금만 변동·|N|≥2는 기존 목돈
+    경로(/lumpsum v 자동집행) 재사용(ACCT_LUMP_V). 주식+현금 복합 변동의 비례 매매(신규 주문
+    코드)는 2단계 — 1단계에서는 원장 맞춤만 제안하고 필요한 매매 주수를 안내한다.
+  · 현금 필드: 토스 buying-power 응답엔 총예수금이 없어(cashBuyingPower뿐) C_a = 주문가능금액
+    + Σ(대기 매수주문 잔량×지정가×(1+수수료율))로 역산. 종전 '미체결 있으면 감지 건너뜀'(K-E)
+    제약이 사라지고, 종전 '미신고 입출금 감지'(CASH_GAP_ALERT) 블록은 이 감지로 대체(환경변수
+    CASH_GAP_ALERT는 더 이상 읽지 않음).
+  · 답 형식 /예 N·/아니오 N(건번호 필수): 봇 process_commands가 "/"로 시작하지 않는 메시지를
+    건너뛰므로(봇 불가침) 명령형으로 받는다. 건번호 필수 = "본 건과 다른 건은 절대 집행 안 함".
+  · 불일치 안내 정합: 건이 열려 있을 때 probe·reconcile의 🚨 /setpos 처방 문구를 "건 #N에 답하세요"로
+    치환(reconcile은 프레임워크 불가침 → auto._notify 래핑으로 문구만 치환, 판정·중단 동작 무수정).
+  · 봇·어댑터·프레임워크 무수정. 환경변수: ACCT_CHANGE_MIN / ACCT_FIX_MAX_N / ACCT_CASE_DAYS /
+    ACCT_FEE / ACCT_KRW_MIN / ACCT_LUMP_V (아래 표).
+
 ★ rev.5 (2026-07-26, 은박사 승인): 문서만 갱신 — 코드 로직 무변경.
   · [T1] 요지를 어댑터 rev.4 정정과 정합화(사각 2종: 앱 수동매매 + 응답 유실 접수).
   · 호출량 표기 교정(아래 rev.4 ※ 항목에 인라인) — 166콜은 코드 구조상 산정(정확),
@@ -82,6 +101,13 @@
   CAP_RATIO=0.05 / CAP_FLOOR=50   동적 주수 상한(보유×0.05, min 50주). 정상 lot의 1.34배.
   SYNC_SINCE=       YYYY-MM-DD (journal 모드는 저널 미종결분만 조회 — 창 축소 이득이 키움보다 작다)
   SYMBOL=TQQQ
+  ★ACCT-1(rev.6) 계좌 변동 감지·확인형 반영 (사양서 v0.5 §8 파라미터 표)
+  ACCT_CHANGE_MIN=5     잔돈 문턱(USD). 주수 차이 0 이고 현금 차이가 이 미만이면 변동 없음으로 본다.
+  ACCT_FIX_MAX_N=1      허용 오차(주). 통일 규칙 N의 |N|≤이 값이면 매매 없이 원장 맞춤.
+  ACCT_CASE_DAYS=7      질문 유효기간(일). 지나면 같은 내용을 새 건번호로 다시 묻는다.
+  ACCT_FEE=0.001        수수료율(N 계산·대기주문 증거금 역산). 토스 미국주식 0.1%(2026-09-29 실측 $4.35/$4,353.66).
+  ACCT_KRW_MIN=500000   원화 예수금이 이 이상이면 환전 안내 한 줄.
+  ACCT_LUMP_V=on        현금만 변동·|N|≥2 → 기존 목돈 경로(/lumpsum ±금액 v, 장중 자동집행) 제안. off면 Pool만 맞춤 제안.
   + TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
 ════════════════════════════════════════════════════════════════════════
 """
@@ -102,10 +128,19 @@
 # KIWOOM_MOCK 대응 없음 [T3] — 토스 모의서버 부재. L1은 DRY_RUN/LIVE_ARM 2축으로만 판정.
 FILLS_MODE   = os.environ.get("FILLS_MODE", "journal").strip().lower()   # [T1]
 SYNC_SINCE   = os.environ.get("SYNC_SINCE", "").strip()
-# ★미신고 입출금 감지(2026-07-23): 증권사 예수금과 원장 Pool 차이가 이 값(USD) 이상이면 알림만.
-#   sync_fills 직후 비교하므로 남는 차이는 외부 입출금뿐(배당·수수료는 임계 아래).
-#   기본 3500 ≈ 500만원(환율 1400). 자동 처리는 하지 않는다 — 의도(v/pool)를 사람이 정해야 하므로.
-CASH_GAP_ALERT = float(os.environ.get("CASH_GAP_ALERT", "3500"))
+# ★ACCT-1(rev.6, 2026-09-29): 종전 '미신고 입출금 감지'(CASH_GAP_ALERT, 알림만)를 계좌 변동 감지·확인형
+#   반영으로 대체. 파라미터는 사양서 v0.5 §8 표. CASH_GAP_ALERT 환경변수는 더 이상 읽지 않는다.
+ACCT_CHANGE_MIN = float(os.environ.get("ACCT_CHANGE_MIN", "5"))     # 잔돈 문턱(USD)
+ACCT_FIX_MAX_N  = int(os.environ.get("ACCT_FIX_MAX_N", "1"))        # 허용 오차(주)
+ACCT_CASE_DAYS  = int(os.environ.get("ACCT_CASE_DAYS", "7"))        # 질문 유효기간(일)
+ACCT_FEE        = float(os.environ.get("ACCT_FEE", "0.001"))        # 수수료율(추정) — 토스 미국주식 0.1%
+ACCT_KRW_MIN    = float(os.environ.get("ACCT_KRW_MIN", "500000"))   # 원화 환전 안내 문턱(KRW)
+ACCT_LUMP_V     = ON(os.environ.get("ACCT_LUMP_V", "on"))           # 현금만 변동·|N|≥2 → 기존 목돈 경로 재사용
+ACCT_SMALL_USD  = 3000.0                                            # 처음 시작 소액 안내(총액 미만이면 안내)
+ACCT_RECO_USD   = 5000.0                                            # 처음 시작 권장 총액(안내 문구용)
+_ACCT_YES = ("/예", "/네", "/응", "/yes", "/y")
+_ACCT_NO  = ("/아니오", "/아니요", "/no", "/n")
+_CTX = {}   # run()이 채운다: 이번 실행의 감지 스냅샷("detect") — 답 처리기가 '본 건 = 이번 감지' 확인에 사용
 SYMBOL       = os.environ.get("SYMBOL", "TQQQ")
 # EXCD 대응 없음 — 토스 주문·조회 바디에 거래소구분 필드가 존재하지 않음.
 
@@ -461,6 +496,9 @@
 def _guarded_apply(pos, text, price_hint, Veff_target=None):
     t = (text or "").strip().split()
     cmd = t[0].lower().split("@", 1)[0] if t else ""
+    # ★ACCT-1: 계좌 변동 건 답(/예 N · /아니오 N)은 봇에 넘기지 않고 러너가 처리한다(봇 불가침).
+    if cmd in _ACCT_YES or cmd in _ACCT_NO:
+        return _acct_answer(pos, text, price_hint)
     if AUTO_MODE and cmd in BLOCKED_IN_AUTO:
         _alt = ("\n   입출금은 <code>/lumpsum ±금액 v</code>(목돈공식·자동집행) 또는 "
                 "<code>/lumpsum ±금액 pool</code>(Pool만)을 쓰세요."
@@ -472,6 +510,274 @@
 bot.apply_command = _guarded_apply
 
 
+# ══ [ACCT-1] 계좌 변동 감지·확인형 반영 (사양서 v0.5, 1단계 · rev.6) ═══════════════
+#   흐름(정규 실행): 체결동기화 → _acct_detect(조회·분류·질문 또는 승인건 집행) → process_commands
+#   (/예 N → _acct_answer → 이번 실행 감지와 같은 건일 때만 집행) → probe → 목돈 → 롤오버 → daily_run.
+#   원장 변경은 전부 봇 명령 문자열(/setpos·/lumpsum)을 _orig_apply로 호출한다 — 러너 자체 산식 없음.
+#   저장되는 키: pos["acct_case"](열린 건) · pos["acct_seq"](건번호 카운터) · pos["acct_declined"](아니오 한 건)
+#   · pos["acct_last"](마지막 반영 기록). 봇 /setpos는 이 키들을 건드리지 않는다(다음 감지가 자연 해소).
+
+def _acct_now():
+    return bot.pd.Timestamp.now(tz="Asia/Seoul")
+
+def _acct_snapshot(broker):
+    """실계좌 스냅샷(조회만·주문 없음). C_a = 주문가능금액 + Σ대기 매수주문 잔량×지정가×(1+수수료율).
+       토스 buying-power 응답엔 총예수금 필드가 없어(cashBuyingPower뿐) 대기 매수 증거금을 역산해 더한다.
+       매도 대기주문은 증거금이 없어 더하지 않는다. 오차 = 수수료 예치 반올림(9/29 실측 36건 $0.2 안쪽)."""
+    held  = broker.get_holdings(SYMBOL)
+    opens = broker.list_open_orders(SYMBOL) or []
+    cash_bp = float(broker.get_cash_usd())
+    reserve = 0.0
+    for o in opens:
+        if str(o.get("side", "")).lower() == "buy":
+            try:
+                reserve += float(o.get("qty") or 0) * float(o.get("price") or 0) * (1.0 + ACCT_FEE)
+            except Exception:
+                pass
+    px = float(broker._cached_price(SYMBOL)) if hasattr(broker, "_cached_price") else float(broker.get_price(SYMBOL))
+    return {"S_a": float(held.shares), "C_a": round(cash_bp + reserve, 2), "cash_bp": round(cash_bp, 2),
+            "reserve": round(reserve, 2), "n_open": len(opens), "px": px}
+
+def _acct_krw(broker):
+    """원화 예수금(주문가능) — 환전 안내용. 실패해도 감지를 막지 않는다(None)."""
+    try:
+        d = broker._req("GET", broker.EP["buypower"], None, "원화예수금조회", params={"currency": "KRW"})
+        res = d.get("result") or {}
+        return float(broker._num(res.get("cashBuyingPower"))) if "cashBuyingPower" in res else None
+    except Exception:
+        return None
+
+def _acct_classify(pos, snap, price_hint):
+    """감지 결과를 '건'으로 분류 — 순수 계산(API·원장 무접촉). None = 반영할 변동 없음.
+       [사양 §3 통일 규칙] r = P_l÷S_l, N = (C_a − r×S_a) ÷ (r + P×(1+f)) 반올림.
+         |N| ≤ 허용 오차 → 매매 없이 원장 맞춤(현금만이면 /lumpsum pool!, 주수 변동이면 /setpos, V' = V×S_a÷S_l)
+         |N| ≥ 2, 현금만 변동 → 기존 목돈 경로(/lumpsum v: 비중대로 매수·매도 + V×(1+ΔC/총자산)) — 책 207쪽과 동치
+         |N| ≥ 2, 주수+현금 복합 → [1단계] 원장 맞춤만 제안 + 비례 매매 주수 안내(자동 매매는 2단계)
+       [사양 §4] 원장 없음 → 처음 시작(보유 있으면 /setpos 등록, 현금뿐이면 안내). [§2-6] CASH 중 → Pool만."""
+    S_l = float(pos.get("shares", 0.0) or 0.0); P_l = float(pos.get("pool", 0.0) or 0.0)
+    V = float(pos.get("V", 0.0) or 0.0); state = str(pos.get("state", "INVESTED"))
+    S_a = float(snap["S_a"]); C_a = float(snap["C_a"]); px = float(snap.get("px") or 0.0)
+    dS = S_a - S_l; dC = round(C_a - P_l, 2)
+    today = _acct_now().strftime("%Y-%m-%d")
+    lcs = str(pos.get("last_cycle_start") or today)
+    base = {"dS": dS, "dC": dC, "S_a": S_a, "C_a": C_a, "S_l": S_l, "P_l": P_l, "V": V, "px": px,
+            "state": state, "price_hint": float(price_hint or 0.0), "N": 0, "V_new": V, "cmd": None}
+    if S_l == 0 and P_l == 0:                                   # (c) 원장 없음 → 처음 시작
+        if S_a > 0:
+            base.update(kind="first_hold", cmd=f"/setpos {S_a:g} {C_a:.2f} 0 {today} INVESTED",
+                        V_new=S_a * float(price_hint or 0.0))
+            return base
+        if C_a >= ACCT_CHANGE_MIN:
+            base.update(kind="first_cash", N=(int(C_a * 0.9 / px) if px > 0 else 0))
+            return base
+        return None
+    if abs(dS) < 0.5 and abs(dC) < ACCT_CHANGE_MIN:            # 잔돈 문턱 이내 → 변동 없음
+        return None
+    if state == "CASH":                                         # (d) 대피 중 → Pool만
+        base.update(kind="cash_pool", cmd=(f"/lumpsum {dC:+.2f} pool!" if abs(dC) >= ACCT_CHANGE_MIN else None))
+        return base
+    if S_l <= 0 or px <= 0:                                     # 비정상(INVESTED인데 0주·가격 없음) → 원장 맞춤(V 유지)
+        base.update(kind="fix_pos", cmd=f"/setpos {S_a:g} {C_a:.2f} {V:.2f} {lcs} {state}")
+        return base
+    r = P_l / S_l
+    N = int(round((C_a - r * S_a) / (r + px * (1.0 + ACCT_FEE))))
+    base["N"] = N
+    if abs(N) <= ACCT_FIX_MAX_N:                                # (a) 매매 없이 원장 맞춤
+        if abs(dS) < 0.5:
+            base.update(kind="fix_pool", cmd=f"/lumpsum {dC:+.2f} pool!")
+        else:
+            V_new = V * S_a / S_l
+            base.update(kind="fix_pos", cmd=f"/setpos {S_a:g} {C_a:.2f} {V_new:.2f} {lcs} {state}", V_new=V_new)
+        return base
+    if abs(dS) < 0.5:                                           # 현금만 변동·|N|≥2
+        total = S_l * float(price_hint or px) + P_l
+        if ACCT_LUMP_V and total > 0:
+            w = S_l * float(price_hint or px) / total
+            base.update(kind="lump_v", cmd=f"/lumpsum {dC:+.2f} v", V_new=V * (1.0 + dC / total),
+                        q_est=int(abs(dC) * w / px) if px > 0 else 0, w=w)
+        else:
+            base.update(kind="fix_pool", cmd=f"/lumpsum {dC:+.2f} pool!")
+        return base
+    V_new = V * S_a / S_l                                       # 복합 변동·|N|≥2 → [1단계] 원장 맞춤만
+    base.update(kind="mixed", cmd=f"/setpos {S_a:g} {C_a:.2f} {V_new:.2f} {lcs} {state}", V_new=V_new,
+                V_trade=V * (S_a + N) / S_l)
+    return base
+
+def _acct_same(a, b):
+    """같은 변동인가(재감지 기준: 주수 차이 동일, 현금 차이 ±$1 이내)."""
+    try:
+        return abs(float(a["dS"]) - float(b["dS"])) < 0.5 and abs(float(a["dC"]) - float(b["dC"])) <= 1.0
+    except Exception:
+        return False
+
+def _acct_message(case, cid, opened, asked, snap=None, dry=False):
+    """질문 문구(사양 §5): 금액 병기·유효기간·복사용 답 줄. HTML(봇 _tg 파서)."""
+    k = case["kind"]; dS = case["dS"]; dC = case["dC"]; px = case.get("px") or 0.0
+    try:
+        exp = (bot.pd.Timestamp(opened) + bot.pd.Timedelta(days=ACCT_CASE_DAYS)).strftime("%m-%d")
+    except Exception:
+        exp = "?"
+    L = [("[DRY] " if dry else "") + f"🧾 <b>계좌 변동 감지 [건 #{cid}]</b>" + (f" (재질문 {asked}회차)" if asked > 1 else "")]
+    if k in ("first_hold", "first_cash"):
+        L.append(f"   원장이 비어 있고 실계좌에 주식 {case['S_a']:g}주 · 현금 {case['C_a']:,.2f} USD가 있습니다.")
+    else:
+        _ds = f"주식 {dS:+g}주" if abs(dS) >= 0.5 else "주식 변동 없음"
+        _dc = f"현금 {dC:+,.2f} USD" if abs(dC) >= ACCT_CHANGE_MIN else "현금 변동 없음"
+        L.append(f"   {_ds} · {_dc}  (원장 {case['S_l']:g}주·Pool {case['P_l']:,.2f} → 실계좌 {case['S_a']:g}주·현금 {case['C_a']:,.2f})")
+    if snap and snap.get("reserve", 0) > 0:
+        L.append(f"   (실계좌 현금 = 주문가능 {snap['cash_bp']:,.2f} + 대기 매수주문 {snap['n_open']}건 증거금 {snap['reserve']:,.2f} 역산)")
+    side = "매수" if case.get("N", 0) > 0 else "매도"
+    if k == "fix_pool":
+        L.append(f"   처리안: 매매 없이 Pool만 맞춤 — Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} ({dC:+,.2f}) · V·주식 그대로")
+    elif k == "fix_pos":
+        L.append(f"   처리안: 매매 없이 원장 맞춤 — 주식 {case['S_l']:g} → {case['S_a']:g} · Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} · "
+                 f"V {case['V']:,.0f} → {case['V_new']:,.0f} (주수 비례)")
+    elif k == "lump_v":
+        L.append(f"   처리안: 책 목돈 공식 — 현재 비중(주식 {case.get('w',0):.0%})대로 {side} 약 {case.get('q_est',0)}주 ≈ ${case.get('q_est',0)*px:,.0f} "
+                 f"(집행가에 따라 주수 변동, 나머지는 Pool) · V {case['V']:,.0f} → {case['V_new']:,.0f} · 장중 지정가(±10%) 자동 집행")
+        if dC < 0:
+            L.append("   ※ 매도가 실현되면 해외주식 양도소득세 대상입니다(연 250만 원 기본공제 초과분 22%).")
+    elif k == "mixed":
+        L.append(f"   처리안 ① 예 → 매매 없이 원장 맞춤: 주식 → {case['S_a']:g} · Pool → {case['C_a']:,.2f} · V {case['V']:,.0f} → {case['V_new']:,.0f}")
+        L.append(f"   ② 책 비율(Pool÷주식 유지) 복원에는 {side} 약 {abs(case['N'])}주 ≈ ${abs(case['N'])*px:,.0f} 필요 — "
+                 f"1단계에서는 자동 매매가 없습니다. 앱에서 직접 {side}하시면 다음 실행이 새 건으로 감지해 원장을 맞춥니다(그때 V ≈ {case.get('V_trade',0):,.0f}).")
+        if case["N"] < 0:
+            L.append("   ※ 매도가 실현되면 해외주식 양도소득세 대상입니다(연 250만 원 기본공제 초과분 22%).")
+    elif k == "cash_pool":
+        L.append(f"   처리안: 대피(CASH) 중 — Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} · V 그대로 · 매매 없음")
+        if case["S_a"] > 0:
+            L.append(f"   ⚠️ 대피 중인데 실계좌에 주식 {case['S_a']:g}주가 있습니다 — 앱에서 확인하세요(자동 반영 없음).")
+    elif k == "first_hold":
+        tot = case["S_a"] * px + case["C_a"]
+        ratio = (case["C_a"] / tot) if tot > 0 else 0.0
+        L.append(f"   처리안: 처음 등록(매매 없음) — 주식 {case['S_a']:g}주 · Pool {case['C_a']:,.2f} · "
+                 f"V = {case['S_a']:g}×전일종가 {case['price_hint']:,.2f} = {case['V_new']:,.0f} · 사이클 시작 = 오늘 · 매수한도 = Pool×50%")
+        if ratio < 0.10:
+            L.append(f"   ⚠️ Pool 비중 {ratio:.0%} — 책 권장(10~20%)보다 낮아 사다리 매수 여력이 부족합니다.")
+        if tot < ACCT_SMALL_USD:
+            L.append(f"   ℹ️ 총액 ${tot:,.0f} — $3,000 미만이면 사다리가 1~2칸뿐입니다. ${ACCT_RECO_USD:,.0f} 이상을 권장합니다(막지는 않음).")
+    elif k == "first_cash":
+        n = case.get("N", 0); tot = case["C_a"]
+        L.append(f"   처리안: 처음 시작(현금뿐) — 책 방식은 주식 ⌊현금×0.9÷가격⌋ = {n}주 ≈ ${n*px:,.0f} 매수, Pool ≈ {tot - n*px:,.0f}(10%).")
+        L.append("   1단계에서는 자동 매수가 없습니다 — 앱에서 위 주수를 사시면 다음 실행이 '처음 등록' 건으로 묻습니다.")
+        if tot < ACCT_SMALL_USD:
+            L.append(f"   ℹ️ 총액 ${tot:,.0f} — $3,000 미만이면 사다리가 1~2칸뿐입니다. ${ACCT_RECO_USD:,.0f} 이상을 권장합니다(막지는 않음).")
+    if k not in ("first_hold", "first_cash") and dC < -ACCT_CHANGE_MIN:
+        L.append("   ⚠️ 실제 현금이 원장 Pool보다 적습니다 — 반영 전까지 사다리 매수 주문이 거절될 수 있습니다. "
+                 "TQQQ가 아닌 종목을 사셨으면 <code>/아니오</code>로 답하세요.")
+    if case.get("cmd"):
+        L.append(f"   원장 명령(예 시 봇이 실행): <code>{case['cmd']}</code>")
+        if not dry:
+            L.append(f"   → 반영 <code>/예 {cid}</code>   ·   보류 <code>/아니오 {cid}</code>   (유효 {exp}까지, 답 없으면 매 리포트 반복)")
+    return "\n".join(L)
+
+def _acct_execute(pos, cur, price_hint):
+    """승인된 건 집행 = 봇 명령 호출. 성공 → 건 종료·기록. 실패(봇 거부) → approved 유지, 다음 실행 재시도."""
+    cmd = cur.get("cmd")
+    pos2, res = _orig_apply(pos, cmd, price_hint)
+    ok = bool(res) and not str(res).lstrip().startswith(("⚠️", "❓", "⛔", "🚨"))
+    if ok:
+        pos2.pop("acct_case", None); pos2.pop("acct_declined", None)
+        pos2["acct_last"] = {"id": cur["id"], "kind": cur["kind"], "cmd": cmd, "at": _acct_now().strftime("%Y-%m-%d %H:%M")}
+        return pos2, f"✅ <b>계좌 변동 건 #{cur['id']} 반영</b> — 원장 명령 <code>{cmd}</code>\n{res}"
+    cur["approved"] = True; pos2["acct_case"] = cur
+    return pos2, f"🚨 계좌 변동 건 #{cur['id']} 집행 실패 — 유효기간 내 다음 실행에서 재감지 후 자동 재시도합니다.\n{res}"
+
+def _acct_answer(pos, text, price_hint):
+    """/예 N · /아니오 N 처리. 건번호 필수(본 건과 다른 건 집행 금지). 집행은 '이번 실행 감지 = 그 건'일 때만."""
+    t = (text or "").strip().split()
+    cmd = t[0].lower().split("@", 1)[0] if t else ""
+    yes = cmd in _ACCT_YES
+    cur = pos.get("acct_case")
+    if not cur:
+        return pos, "ℹ️ 열린 계좌 변동 건이 없습니다(이미 해소됐거나 아직 감지 전)."
+    try:
+        n = int(t[1]) if len(t) > 1 else None
+    except Exception:
+        n = None
+    if n is None:
+        return pos, f"⚠️ 건번호를 붙여 주세요 — 현재 열린 건은 #{cur['id']}: <code>/예 {cur['id']}</code> 또는 <code>/아니오 {cur['id']}</code>"
+    if n != int(cur["id"]):
+        return pos, (f"⚠️ 건번호 불일치 — 보내신 #{n}, 현재 열린 건은 #{cur['id']}(내용이 바뀌어 새 번호). "
+                     f"현재 건을 확인한 뒤 <code>/예 {cur['id']}</code> 또는 <code>/아니오 {cur['id']}</code>.")
+    if not yes:
+        pos["acct_declined"] = {k: cur.get(k) for k in ("id", "kind", "dS", "dC", "S_a", "C_a")}
+        pos.pop("acct_case", None)
+        _after = ("다음 실행에서 차이가 남아 있으면 매매 없이 원장만 맞추는 안을 새 건으로 제안합니다."
+                  if cur.get("kind") == "lump_v" else "변동 내용이 바뀔 때까지 다시 묻지 않습니다(리포트에 보류 한 줄만).")
+        return pos, f"⏸️ 계좌 변동 건 #{cur['id']} 보류(아니오). {_after}"
+    if not cur.get("cmd"):
+        return pos, f"ℹ️ 건 #{cur['id']}는 안내 전용(자동 반영 항목 없음)입니다."
+    if DRY_RUN:
+        return pos, f"[DRY] 건 #{cur['id']} 승인 접수 — DRY_RUN이라 원장을 바꾸지 않습니다(LIVE 실행에서 집행)."
+    det = _CTX.get("detect") or {}
+    if not det.get("case") or not _acct_same(det["case"], cur):
+        cur["approved"] = True; pos["acct_case"] = cur
+        return pos, (f"⏸️ 건 #{cur['id']} 승인 접수 — 이번 실행 재감지가 건 내용과 맞지 않거나 조회에 실패해 집행을 보류합니다. "
+                     f"다음 실행에서 재감지 후 같은 내용이면 자동 집행합니다.")
+    return _acct_execute(pos, cur, price_hint)
+
+def _acct_detect(broker, pos, notifier, price_hint):
+    """[ACCT-1] 정규 실행마다: 실계좌 조회 → 분류 → (승인건이면 집행 / 아니면 질문). DRY는 미리보기만(저장 없음)."""
+    _CTX["detect"] = None
+    if pos.get("pending_lump") or pos.get("lump_in_flight") or pos.get("evac_pending") \
+       or pos.get("recover_pending") or pos.get("recover_retry"):
+        notifier("⏸️ 계좌 변동 감지 보류 — 목돈·대피·복귀 집행이 진행 중입니다(확정 후 다음 실행에서 감지).")
+        return pos
+    try:
+        snap = _acct_snapshot(broker)
+    except Exception as e:
+        notifier(f"⚠️ 계좌 변동 감지 생략(조회 실패): {e}")
+        return pos
+    case = _acct_classify(pos, snap, price_hint)
+    _CTX["detect"] = {"snap": snap, "case": case}
+    krw = _acct_krw(broker)
+    if krw is not None and krw >= ACCT_KRW_MIN:
+        notifier(f"💱 원화 예수금 ₩{krw:,.0f} — 달러로 환전하시면 다음 실행이 입금으로 감지합니다.")
+    now = _acct_now(); today = now.strftime("%Y-%m-%d")
+    if DRY_RUN:
+        if case is None:
+            notifier("[DRY] 계좌 변동 없음 — 실계좌와 원장 일치(잔돈 문턱 이내). ※DRY는 체결 미동기화 상태의 미리보기")
+        else:
+            notifier(_acct_message(case, "미리보기", today, 1, snap, dry=True) + "\n   ※DRY: 건 저장·답 처리 없음(체결 미동기화 미리보기)")
+        return pos
+    cur = pos.get("acct_case")
+    if case is None:
+        changed = False
+        if cur:
+            notifier(f"✅ 계좌 변동 건 #{cur['id']} 해소 — 실계좌와 원장이 일치합니다(별도 조치 없음)."); pos.pop("acct_case", None); changed = True
+        if pos.get("acct_declined"):
+            pos.pop("acct_declined", None); changed = True
+        if changed: bot.save_position(pos)
+        return pos
+    if cur and _acct_same(cur, case):
+        if cur.get("approved"):                                 # 승인됐으나 집행 못 한 건 → 자동 재시도
+            pos, msg = _acct_execute(pos, cur, price_hint); bot.save_position(pos); notifier(msg); return pos
+        try:
+            expired = (now.tz_localize(None) - bot.pd.Timestamp(cur["opened"])).days >= ACCT_CASE_DAYS
+        except Exception:
+            expired = True
+        if expired:
+            cid = int(pos.get("acct_seq", 0)) + 1; pos["acct_seq"] = cid
+            cur = dict(case, id=cid, opened=today, asked=1)
+        else:
+            cur["asked"] = int(cur.get("asked", 1)) + 1
+    else:
+        dec = pos.get("acct_declined")
+        if dec and _acct_same(dec, case):
+            if dec.get("kind") == "lump_v" and case["kind"] == "lump_v":   # 예비 경로: 매매 없이 Pool만
+                case = dict(case, kind="fix_pool", cmd=f"/lumpsum {case['dC']:+.2f} pool!")
+            else:
+                notifier(f"⏸️ 계좌 변동 건 #{dec.get('id')} 보류 중(아니오) — 주식 {case['dS']:+g}주 · 현금 {case['dC']:+,.2f}. 변동이 바뀌면 다시 묻습니다.")
+                return pos
+        cid = int(pos.get("acct_seq", 0)) + 1; pos["acct_seq"] = cid
+        cur = dict(case, id=cid, opened=today, asked=1)
+    pos["acct_case"] = cur
+    bot.save_position(pos)
+    notifier(_acct_message(cur, cur["id"], cur["opened"], cur.get("asked", 1), snap))
+    return pos
+
+
 # ══ [G6] 목돈 자동 집행 ═══════════════════════════════════════════
 def _us_market_open():
     """미국 정규장 개장 중인가(XNYS). 판정 불가하면 False — 보수적으로 집행을 미룬다."""
@@ -704,6 +1010,12 @@
         L.append(f"   예수금 조회 생략: {e}")
 
     notify("\n".join(L))
+    if not ok and pos.get("acct_case"):
+        # ★ACCT-1: 건이 열려 있으면 /setpos 처방 대신 건 답변으로 유도(수동 명령과 자동 반영의 이중계상 방지).
+        _cid = pos["acct_case"].get("id")
+        notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주. 계좌 변동 건 #{_cid}로 처리 중 — "
+               f"리포트의 <code>/예 {_cid}</code>·<code>/아니오 {_cid}</code>로 답하세요(수동 <code>/setpos</code> 불필요).")
+        return ok
     if not ok:
         # ★R7(2026-07-25 승인): 불일치 경보를 2분기로. 종전 단일 문구("수동 확인 필요")는
         #   '체결 반영 대기' 상황(어댑터 [A4]: 종결 주문만 원장 반영 → 장중 재실행 시 일시 괴리)에서
@@ -763,8 +1075,8 @@
         banner += ("\n⚠️ AUTO_MODE=on · 자동복귀=off — 복귀신호 시 /enter가 거부되어 CASH 고착 위험. "
                    "토스 LIVE는 자동복귀=on 권장(탈출구는 /setpos뿐).")
     if AUTO_MODE:   # 입출금 안내 — ★2026-07-23 목돈 자동집행 도입으로 절차 자체가 바뀌었다.
-        banner += ("\nℹ️ 입출금: <code>/lumpsum ±금액 v</code>(목돈공식·장중 자동집행) 또는 "
-                   "<code>/lumpsum ±금액 pool</code>(Pool만·즉시). 크론 정지·SYNC_SINCE 조작 불필요.")
+        banner += ("\nℹ️ 입출금·입고·배당은 봇이 감지해 리포트에서 묻습니다(<code>/예 N</code>·<code>/아니오 N</code>). "
+                   "수동 <code>/lumpsum ±금액 v|pool</code>도 그대로 됩니다. 크론 정지·SYNC_SINCE 조작 불필요.")   # ★ACCT-1
     print(banner)
 
     df  = bot.build_data()
@@ -791,6 +1103,33 @@
         return _orig_rotate(pos, *a, **kw)
     auto.rotate_cycle = _gated_rotate
 
+    # ★ACCT-1: 건이 열려 있는 동안 프레임워크 reconcile의 🚨 /setpos 처방 문구를 "건 #N에 답하세요"로 치환.
+    #   (문구만 치환 — 판정·사다리 중단 동작은 프레임워크 원문 그대로. 두 가지 V 숫자가 동시에 나가
+    #    한쪽을 손으로 따라 치는 사고 방지.)
+    _orig_recon = auto.reconcile
+    def _acct_recon(pos, quiet=False):
+        _case = pos.get("acct_case")
+        if not _case:
+            return _orig_recon(pos, quiet)
+        _saved = auto._notify
+        def _swap(m):
+            if str(m).lstrip().startswith("🚨 포지션 불일치"):
+                _saved(f"🚨 포지션 불일치(실보유≠원장) — 계좌 변동 건 #{_case.get('id')}로 처리 중입니다. "
+                       f"리포트의 <code>/예 {_case.get('id')}</code>·<code>/아니오 {_case.get('id')}</code>로 답하세요"
+                       f"(수동 <code>/setpos</code> 불필요). 해소 전까지 사다리 배치는 중단됩니다.")
+            else:
+                _saved(m)
+        auto._notify = _swap
+        try:
+            return _orig_recon(pos, quiet)
+        finally:
+            auto._notify = _saved
+    auto.reconcile = _acct_recon
+
+    px_col = ("TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
+                              not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ")
+    price_hint = float(df[px_col].iloc[-1])   # ★ACCT-1: 감지(처음 등록 V·목돈 비중)에 필요해 앞으로 이동(값 동일)
+
     since = rolling_since(5)
     if SYNC_SINCE and SYNC_SINCE > since:
         since = SYNC_SINCE
@@ -828,25 +1167,11 @@
         except Exception:
             pass
 
-        # ★미신고 입출금 감지 — 체결 반영 직후라 남는 차이는 외부 입출금뿐. 알림만(자동처리 안 함).
-        try:
-            _openq = broker.list_open_orders(SYMBOL)      # K-E: 미체결이 있으면 증거금 차감으로 오탐 → 스킵
-            if not _openq:
-                _cash = float(broker.get_cash_usd())
-                _gap  = _cash - float(pos.get("pool", 0.0))
-                if abs(_gap) >= CASH_GAP_ALERT and not pos.get("pending_lump"):
-                    _a = "입금" if _gap > 0 else "출금"
-                    notifier(f"💡 <b>{_a} 감지 {abs(_gap):,.0f} USD</b> — 예수금 {_cash:,.0f} vs 원장 Pool {pos.get('pool',0):,.0f}\n"
-                             f"   원인별 처리(자동 처리하지 않습니다 — 의도를 직접 정하셔야 합니다):\n"
-                             f"   · 배당·이자·정산차이(이미 계좌 반영분) → <code>/lumpsum {_gap:+.0f} pool</code>  ※총자산 2% 초과는 pool! 재확인\n"
-                             f"   · 새 자금 입금/인출(목돈) → <code>/lumpsum {_gap:+.0f} v</code>  (비중대로 자동 배분·V 조정)\n"
-                             f"   · 원인 불명 → 아무것도 보내지 마세요(미체결 증거금·정산 지연이면 자연 해소됩니다)")
-        except Exception:
-            pass
-
-    px_col = ("TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
-                              not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ")
-    price_hint = float(df[px_col].iloc[-1])
+    # ★ACCT-1(rev.6): 계좌 변동 감지·질문(체결 반영 직후 → 남는 차이 = 외부 입출금·입고·배당·수동매매).
+    #   종전 '미신고 입출금 감지'(알림만·미체결 있으면 스킵) 블록을 대체. DRY는 미리보기만.
+    #   정규 실행에서만(사다리 전용·KS 전용 실행은 체결 동기화가 daily_run 안에 있어 여기서 감지하면 오탐).
+    if not (KS_ONLY or LADDER_ONLY):
+        pos = _acct_detect(broker, pos, notifier, price_hint)
 
     pos = bot.ensure_V(pos, price_hint)
