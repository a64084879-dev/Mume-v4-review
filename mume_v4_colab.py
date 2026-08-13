--- vr_auto_runner_toss.py	2026-08-13 02:58:20.240464320 +0000
+++ vr_auto_runner_toss_LR.py	2026-08-13 03:08:37.716501798 +0000
@@ -627,6 +627,60 @@
 
 
 # ══ [G4] 조회 프로브 ═══════════════════════════════════════════════
+def _resolve_lump(broker, pos, notifier):
+    """★LUMP-RESOLVE(2026-08-12 은박사님 승인 v2): 목돈 체결확정 해소기 — 정규 실행 750블록의
+       ★R2 사후처리(구 760~807행)를 로직 무변경으로 추출(3분기·문구·판정식 전부 원문 그대로).
+       원 위치와 868행 집행 직후(체결 확인 시에만)의 2곳에서 호출된다. pos 반환."""
+    _oid = pos.get("lump_in_flight")
+    if _oid:
+        # ★R-B(2026-07-24): 앞에서 세면(=[1:2]) filled_at에 시각(콜론)이 들어갈 때 어긋나
+        #   체결을 '미체결 소멸'로 오판 → 허위 알림 + /setv 되돌리기 유도(V 오염) + 예산 리셋 누락.
+        #   신키 f"{filled_at}:{order_id}:{side}" → [-2], 구키 f"{filled_at}:{order_id}" → [-1].
+        #   뒤에서 세면 filled_at 형식과 무관하게 안전하다.
+        # ★B(2026-07-24): 0-패딩 정규화. 접수응답 ord_no와 ust21150 ord_no의 패딩이
+        #   다르면 체결을 '미체결 소멸'로 오분류한다. 원장 조치는 같지만 알림이 거짓이 되고,
+        #   그 문구가 되돌리기를 유도해 V 오염 위험이 있다. verify_placed와 동일 norm으로 양변 통일.
+        #   "PENDING" 센티널은 lstrip("0")에 불변이고 어떤 키와도 불일치라 무해하다.
+        _norm = lambda x: str(x or "").strip().lstrip("0")
+        def _oid_of(k):
+            _p = str(k).split(":")
+            return {_norm(_p[-2]) if len(_p) >= 3 else None,
+                    _norm(_p[-1]) if len(_p) >= 2 else None}
+        _filled = any(_norm(_oid) in _oid_of(k) for k in (pos.get("fills_seen") or {}))
+        if _filled:
+            pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
+            pos["cyc_used"]   = 0.0          # K-D: 목돈 체결분이 사다리 예산을 먹지 않도록 여기서 리셋
+            pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
+            bot.save_position(pos)
+            notifier("✅ 목돈 체결 확정 — 매수한도 재설정·사다리 재개")
+        else:
+            try: _open = broker.list_open_orders(SYMBOL)
+            except Exception: _open = [{"_unknown": True}]
+            if _oid == "PENDING" and not _open:
+                # ★2단계 커밋의 잔존(2026-07-24): 주문번호를 남기기 전에 죽은 경우.
+                #   미체결 주문이 없으므로 (a)접수 자체가 안 됐거나 (b)이미 체결됐다.
+                #   두 경우 모두 Pool은 정합(목돈 반영 완료)이므로 예산 재설정이 정답이다.
+                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
+                pos["cyc_used"]   = 0.0
+                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
+                bot.save_position(pos)
+                notifier("ℹ️ 목돈 주문 상태 불명(접수 직전 중단) — Pool·V는 반영됨. "
+                         "미체결 없음을 확인해 사다리를 재개합니다. <code>/status</code>로 보유 확인 권장.")
+            elif not _open:                    # DAY 만료·취소로 소멸 → 매매 없이 Pool·V만 바뀐 상태
+                # ★교정(2026-07-24): 종전 문구가 "재예약하거나 /setv로 되돌리세요"였는데,
+                #   이 시점엔 Pool·V가 이미 커밋돼 있어 재예약하면 pool 2회 가산 + V 2회 스케일이 된다
+                #   (바로 위 접수실패 분기는 정확히 그 반대로 경고하고 있었다 — 비대칭 해소).
+                #   원장 상태가 PENDING 분기와 동일하므로 예산 리셋도 동일하게 한다.
+                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
+                pos["cyc_used"]   = 0.0
+                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
+                bot.save_position(pos)
+                notifier("🚨 목돈 주문 미체결 소멸 — 매매 없이 <b>Pool·V는 이미 반영</b>된 상태입니다.\n"
+                         "   ⚠️ <code>/lumpsum</code> 재예약 금지(Pool 2회 가산·V 2회 조정됩니다).\n"
+                         "   · 그대로 두면 남은 현금을 사다리가 소화합니다(권장).\n"
+                         "   · 되돌리려면 <code>/setv @현재가</code> + <code>/lumpsum ∓금액 pool</code>.")
+    return pos
+
 def probe(broker, pos, since, notify):
     acct = "<b>실계좌</b>"   # [T3] 토스는 실계좌뿐
     L = [f"🔍 <b>조회 프로브</b> (주문 없음) — 토스 {acct}"]
@@ -757,54 +811,7 @@
             raise
 
         # ★R2 사후처리: 목돈 주문의 체결 확정 여부 판정 → 예산·사다리 재정렬(수동 /lumpsum_done과 동일 의미)
-        _oid = pos.get("lump_in_flight")
-        if _oid:
-            # ★R-B(2026-07-24): 앞에서 세면(=[1:2]) filled_at에 시각(콜론)이 들어갈 때 어긋나
-            #   체결을 '미체결 소멸'로 오판 → 허위 알림 + /setv 되돌리기 유도(V 오염) + 예산 리셋 누락.
-            #   신키 f"{filled_at}:{order_id}:{side}" → [-2], 구키 f"{filled_at}:{order_id}" → [-1].
-            #   뒤에서 세면 filled_at 형식과 무관하게 안전하다.
-            # ★B(2026-07-24): 0-패딩 정규화. 접수응답 ord_no와 ust21150 ord_no의 패딩이
-            #   다르면 체결을 '미체결 소멸'로 오분류한다. 원장 조치는 같지만 알림이 거짓이 되고,
-            #   그 문구가 되돌리기를 유도해 V 오염 위험이 있다. verify_placed와 동일 norm으로 양변 통일.
-            #   "PENDING" 센티널은 lstrip("0")에 불변이고 어떤 키와도 불일치라 무해하다.
-            _norm = lambda x: str(x or "").strip().lstrip("0")
-            def _oid_of(k):
-                _p = str(k).split(":")
-                return {_norm(_p[-2]) if len(_p) >= 3 else None,
-                        _norm(_p[-1]) if len(_p) >= 2 else None}
-            _filled = any(_norm(_oid) in _oid_of(k) for k in (pos.get("fills_seen") or {}))
-            if _filled:
-                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
-                pos["cyc_used"]   = 0.0          # K-D: 목돈 체결분이 사다리 예산을 먹지 않도록 여기서 리셋
-                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
-                bot.save_position(pos)
-                notifier("✅ 목돈 체결 확정 — 매수한도 재설정·사다리 재개")
-            else:
-                try: _open = broker.list_open_orders(SYMBOL)
-                except Exception: _open = [{"_unknown": True}]
-                if _oid == "PENDING" and not _open:
-                    # ★2단계 커밋의 잔존(2026-07-24): 주문번호를 남기기 전에 죽은 경우.
-                    #   미체결 주문이 없으므로 (a)접수 자체가 안 됐거나 (b)이미 체결됐다.
-                    #   두 경우 모두 Pool은 정합(목돈 반영 완료)이므로 예산 재설정이 정답이다.
-                    pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
-                    pos["cyc_used"]   = 0.0
-                    pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
-                    bot.save_position(pos)
-                    notifier("ℹ️ 목돈 주문 상태 불명(접수 직전 중단) — Pool·V는 반영됨. "
-                             "미체결 없음을 확인해 사다리를 재개합니다. <code>/status</code>로 보유 확인 권장.")
-                elif not _open:                    # DAY 만료·취소로 소멸 → 매매 없이 Pool·V만 바뀐 상태
-                    # ★교정(2026-07-24): 종전 문구가 "재예약하거나 /setv로 되돌리세요"였는데,
-                    #   이 시점엔 Pool·V가 이미 커밋돼 있어 재예약하면 pool 2회 가산 + V 2회 스케일이 된다
-                    #   (바로 위 접수실패 분기는 정확히 그 반대로 경고하고 있었다 — 비대칭 해소).
-                    #   원장 상태가 PENDING 분기와 동일하므로 예산 리셋도 동일하게 한다.
-                    pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
-                    pos["cyc_used"]   = 0.0
-                    pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
-                    bot.save_position(pos)
-                    notifier("🚨 목돈 주문 미체결 소멸 — 매매 없이 <b>Pool·V는 이미 반영</b>된 상태입니다.\n"
-                             "   ⚠️ <code>/lumpsum</code> 재예약 금지(Pool 2회 가산·V 2회 조정됩니다).\n"
-                             "   · 그대로 두면 남은 현금을 사다리가 소화합니다(권장).\n"
-                             "   · 되돌리려면 <code>/setv @현재가</code> + <code>/lumpsum ∓금액 pool</code>.")
+        pos = _resolve_lump(broker, pos, notifier)   # ★LUMP-RESOLVE: 원 블록을 추출 함수 호출로 대체(동작 동일)
 
         # ★K-B 교정: 어댑터가 last_recover_check를 '집행/확정일'(UTC today)로 찍는다.
         #   봇 /exit와 동일하게 '판정일'(evac_sig_date, 7일 이내)로 교정 — 그 사이 월말이
@@ -866,6 +873,28 @@
     #   AUTO_MODE에서만 자동. 수동 모드는 기존 /lumpsum_done 경로 유지(이중처리 방지).
     if (AUTO_MODE or DRY_RUN) and not (KS_ONLY or LADDER_ONLY):   # ★KS-OPEN·LADDER-ONLY: 목돈 집행도 정규 실행 몫
         pos = apply_pending_lump(broker, pos, price_hint, notifier)
+        # ★LUMP-RESOLVE(2026-08-12 은박사님 승인 v2): 같은 실행 내 목돈 해소 — 사다리 공백 교정.
+        #   ①게이트 잔존 시에만 ②sync 1회(fills_seen 키 기반 멱등 — 750블록·daily_run ①sync가 이미
+        #   공존하는 기존 구조와 동일 전제) ③'이 주문' 체결이 fills_seen에서 확인될 때만 _resolve_lump
+        #   호출 → 정상 체결(✅) 분기만 도달. 미확인 시 무동작(추가 알림 0) — PENDING·미체결소멸 분기는
+        #   여기서 절대 타지 않는다(허위 '미체결 소멸' 원천 차단). 판정식은 해소기 원문(★R-B 뒤에서
+        #   세는 키 파싱·★B 0패딩 정규화)과 동일 코드 재사용.
+        _lr_oid = pos.get("lump_in_flight")
+        if _lr_oid and (not DRY_RUN):
+            try:
+                pos = auto.sync_fills(pos, since)
+                bot.save_position(pos)
+            except Exception as _lr_e:
+                bot._tg(f"⚠️ 목돈 즉시해소용 체결동기화 실패 — 보류 유지(다음 정규 실행이 처리): {_lr_e}")
+            else:
+                _lr_norm = lambda x: str(x or "").strip().lstrip("0")
+                def _lr_oid_of(k):
+                    _p = str(k).split(":")
+                    return {_lr_norm(_p[-2]) if len(_p) >= 3 else None,
+                            _lr_norm(_p[-1]) if len(_p) >= 2 else None}
+                if any(_lr_norm(_lr_oid) in _lr_oid_of(k) for k in (pos.get("fills_seen") or {})):
+                    pos = _resolve_lump(broker, pos, notifier)   # 체결 확인됨 → ✅ 분기만 도달
+
 
     # ★R6 교정(2026-07-23): 롤오버를 명령·목돈 뒤로. 봇 순서(commands→rollover)와 정렬.
     #   책 방식과도 일치 — 목돈을 먼저 반영하고 '새 Pool' 기준으로 V+Pool/G를 계산해야 한다.
