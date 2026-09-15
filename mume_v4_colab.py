--- orig.py	2026-09-15 07:16:12.452316127 +0000
+++ base_rate.py	2026-09-15 07:16:40.488925706 +0000
@@ -35,13 +35,16 @@
 #    · VR% · 방석% = 전체 자금에서 차지하는 %. FAST% = 100 − VR% − 방석%(자동 계산)
 #    · 최대 6팔. 합계는 자동 검산.
 #    · 이번 설정 목적(2026-08-16 은박사님 지시): 본체를 FAST 50:50으로 바꾸는 결정 하에서,
-#      VR을 서비스로 얹을 때 5·10·15% 세 눈금의 실측. 판정 기준 = 은박사님 감내선 −50%
-#      (최신 세계 낙폭이 이 선 안에 남는 최대 VR%가 답). C 60:40은 기준선 참고용.
-#      측정 전용 — 확정은 은박사님 재가로만.
-ARMS = [("E 70:10:20",  0.60, 10, 20),
-        ("50:50+VR35",  0.50, 35,  0),
-        ("60:40",       0.60,  0,  0),
-        ("50:50",       0.50,  0,  0)]
+#    · 이번 설정 목적(금리 액셀 골자 §1, 2026-09-15 재가): FAST 내부 비중 액셀(A)의 단독 효과 실측.
+#      실행 2회 — RATE_ACCEL="off" → "on". 측정 전용 · 채택/기각 판정 기준은 골자 §6 사전 등록.
+ARMS = [("FAST70+VR30", 0.50, 30, 0),
+        ("50:50 단독",  0.50,  0, 0)]
+# ── [금리 액셀 A — 골자 §2·§3·§4] 실험 스위치(측정 장치 — 실전 규칙 변경 아님) ──
+RATE_ACCEL  = "off"     # "off" | "on" — 실행 2회(off 먼저: G-회귀 대조)
+RATE_SRC    = "irx"     # "irx"(기본, ^IRX 컬럼) | "fedfunds"(FRED — 옵션)
+RATE_STEP   = 0.10      # 상승기: TQQQ 비중 = 기본 − 0.10 (50:50 → 40:60). 한 단계만.
+RATE_THRESH = 0.25      # 방향 문턱 ±0.25%p (연준 1회 폭 — 튜닝 금지)
+RATE_WIN    = 60        # 60거래일 평균 vs 12개월(252거래일) 전 같은 평균
 # ============================================================
 # [1. 파라미터]
 # ============================================================
@@ -1214,6 +1217,49 @@
         lambda x: float((x[-1] >= x).mean()), raw=True)
     return D
 
+# ── [금리 액셀 A 판정 유틸 — 골자 §2. RATE_ACCEL="on"일 때만 호출됨] ──
+_RATE_MA = {}
+def _rate_ma(D):
+    """판정 소스의 60거래일 이동평균(1회 계산 캐시). SRC="irx"=^IRX 컬럼 / "fedfunds"=FRED 수신."""
+    k = id(D)
+    if k in _RATE_MA: return _RATE_MA[k]
+    if RATE_SRC == "irx":
+        s = D['IRX']
+    else:
+        import requests as _rq
+        r = _rq.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS", timeout=30)
+        r.raise_for_status()
+        import io as _io
+        df = pd.read_csv(_io.StringIO(r.text)); df.columns = ['DATE', 'V']
+        s = pd.to_numeric(df.set_index(pd.to_datetime(df['DATE']))['V'], errors='coerce').dropna()
+        s = s.reindex(D.index.union(s.index)).ffill().reindex(D.index)
+        if s.isna().all(): raise SystemExit("★중단: FEDFUNDS 수신 실패(RATE_SRC 옵션).")
+    m = s.rolling(RATE_WIN).mean()
+    _RATE_MA[k] = m
+    return m
+
+def _rate_dir(D, dd):
+    """연말 신호일 dd 기준 방향: +1 상승 / −1 하락 / 0 보합. 60일 평균(당일까지) vs 252거래일 전 값."""
+    m = _rate_ma(D)
+    i = D.index.get_loc(dd); j = i - 252
+    if j < RATE_WIN - 1: return 0
+    a = m.iloc[i]; b = m.iloc[j]
+    if pd.isna(a) or pd.isna(b): return 0
+    d = float(a - b)
+    return 1 if d > RATE_THRESH else (-1 if d < -RATE_THRESH else 0)
+
+def _rate_eff(D, dates, i, base, cnt):
+    """pending 실행일 i의 직전 거래일(=연말 신호일) 판정으로 다음 해 가중 결정(골자 §3).
+       상승기: TQQQ = 기본 − RATE_STEP(하한 0), 감소분은 금으로. 하락·보합: 기본 복귀. 한 단계만."""
+    dd = dates[i - 1] if i >= 1 else dates[0]
+    rd = _rate_dir(D, dd)
+    if rd == 1:
+        cnt['up'] += 1
+        tq0 = float(base.get('TQQQ', 0.0)); tq = max(0.0, tq0 - RATE_STEP)
+        eff = dict(base); eff['TQQQ'] = tq; eff['gold'] = float(base.get('gold', 0.0)) + (tq0 - tq)
+        return eff, rd
+    return base, rd
+
 # ═══ [부품: R5 판(9d1770a8) run_arm — 바이트 이식(원형 불변). R8의 F·C 팔 계산에 사용] ═══
 def run_arm(D, win, weights, cush_w, init=R5_INIT):
     """R5 한 팔 주행. weights=FAST 가중(W_A 또는 W_B), cush_w=방석 비중(0이면 FAST 단독).
@@ -1224,6 +1270,7 @@
     f_cap = init * (1.0 - cush_w); c_cap = init * cush_w
     f_cash = float(f_cap); f_hold = {}; f_state = 'INVESTED'
     f_pending = None; f_annual_pending = False; f_trig = {}
+    _rate_cnt = {'up': 0, 'dn': 0}                           # ★RATE-A: 상승 판정/하향 적용 연수
     n_exit = 0; evac_days = 0; tax_total = 0.0; tax_log = []
     cu_bx_u = 0.0; cu_bx_cost = 0.0; cu_g_u = 0.0
     if f_cap > 0:
@@ -1350,13 +1397,18 @@
         # ③ FAST 연 리밸(정본: 12/31 표시 → 익영업일 집행)
         if f_annual_pending and not f_executed and not is_last:
             f_annual_pending = False
+            _wR = weights                                    # ★RATE-A 접점(골자 §4): off면 기존과 동일 객체
+            if RATE_ACCEL == "on":
+                _wR, _rd = _rate_eff(D, dates, i, weights, _rate_cnt)
+                if _rd == 1 and f_state == 'INVESTED':
+                    _rate_cnt['dn'] += 1                     # 하향 '적용'은 투자 중 리밸에만 계수
             if f_state == 'INVESTED':
-                f_rebalance(weights, p)
+                f_rebalance(_wR, p)
             elif f_state == 'CASH_BOXX':
-                aw = weights.copy(); aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0); aw['TQQQ'] = 0
+                aw = _wR.copy(); aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0); aw['TQQQ'] = 0
                 f_rebalance(aw, p)
             elif f_state == 'CASH_USD':
-                aw = weights.copy(); aw['TQQQ'] = 0
+                aw = _wR.copy(); aw['TQQQ'] = 0
                 f_rebalance(aw, p)
             f_executed = True
         # ④ FAST 신호(정본: GATE=ABS·EXIT=NDX·복귀 GSPC 월말+fast_recover)
@@ -1434,7 +1486,8 @@
             tax_total += final_tax + uni['liab']
             nav_path[i] = max(after, 0.0)
     return dict(nav=pd.Series(nav_path, index=dates), cf=pd.Series(cf_day, index=dates),
-                n_exit=n_exit, evac_days=evac_days, tax_total=tax_total, tax_log=tax_log)
+                n_exit=n_exit, evac_days=evac_days, tax_total=tax_total, tax_log=tax_log,
+                rate_up=_rate_cnt['up'], rate_dn=_rate_cnt['dn'])
 
 # ═══ [메인: 창 열거·게이트·산출물 — 사양 R5-3~R5-5] ═══
 
@@ -1456,6 +1509,7 @@
     # ── FAST 슬리브(정본 run_simulation 이식) ──
     f_cash = float(fast_init); f_hold = {}; f_state = 'INVESTED'
     f_pending = None; f_annual_pending = False; f_trig = {}
+    _rate_cnt = {'up': 0, 'dn': 0}                           # ★RATE-A: 상승 판정/하향 적용 연수
     n_exit = 0; evac_days = 0
     if fast_init > 0:
         p0 = sub.iloc[0]
@@ -1635,13 +1689,18 @@
         # ③ FAST 연 리밸(정본: 12/31 표시 → 익영업일 집행)
         if f_annual_pending and not f_executed and not is_last and fast_init > 0:
             f_annual_pending = False
+            _wR = w                                          # ★RATE-A 접점(골자 §4): off면 기존과 동일 객체
+            if RATE_ACCEL == "on":
+                _wR, _rd = _rate_eff(D, dates, i, w, _rate_cnt)
+                if _rd == 1 and f_state == 'INVESTED':
+                    _rate_cnt['dn'] += 1
             if f_state == 'INVESTED':
-                f_rebalance(w, p)
+                f_rebalance(_wR, p)
             elif f_state == 'CASH_BOXX':
-                aw = w.copy(); aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0); aw['TQQQ'] = 0
+                aw = _wR.copy(); aw['BOXX'] = aw.get('BOXX', 0) + aw.get('TQQQ', 0); aw['TQQQ'] = 0
                 f_rebalance(aw, p)
             elif f_state == 'CASH_USD':
-                aw = w.copy(); aw['TQQQ'] = 0
+                aw = _wR.copy(); aw['TQQQ'] = 0
                 f_rebalance(aw, p)
             f_executed = True
 
@@ -1837,7 +1896,8 @@
     return dict(nav=pd.Series(nav_path, index=dates), cf=pd.Series(cf_day, index=dates),
                 n_exit=n_exit, evac_days=evac_days, v_nexit=v_nexit, stage2=stage2_date,
                 scale_path=scale_path, tax_total=tax_total, narr=narr, tax_log=tax_log,
-                stop_date=stop_date, alloc_log=alloc_log, vr_last=vr_last, tot_last=tot_last)
+                stop_date=stop_date, alloc_log=alloc_log, vr_last=vr_last, tot_last=tot_last,
+                rate_up=_rate_cnt['up'], rate_dn=_rate_cnt['dn'])
 
 # ═══ [메인: 창 열거·게이트·산출물 — 사양 v1.1 ⑥⑦⑧] ═══
 def _win_list(idx):
@@ -1893,6 +1953,13 @@
             if len(wv) < 60: continue
             if (wv[-1] - wv[0]).days / 365.25 < R9_MIN_YEARS: continue
             wins.append((f"{s_ts:%Y}→{e_ts:%Y}", f"{sd}~{ed}", wv))
+    print(f"  · [RATE-A] RATE_ACCEL={RATE_ACCEL} · SRC={RATE_SRC} · STEP={RATE_STEP:.2f} · "
+          f"문턱 ±{RATE_THRESH}%p · 창 {RATE_WIN}거래일(vs 252일 전) · 판정 연 1회(연말 신호일)")
+    _ye = [d for k, d in enumerate(D.index) if k < len(D.index) - 1 and D.index[k + 1].year != d.year]
+    _ups = [d.year for d in _ye if _rate_dir(D, d) == 1]
+    _dns = [d.year for d in _ye if _rate_dir(D, d) == -1]
+    print(f"  · 금리 방향 판정(전 기간, 연말 기준): 상승기 {_ups}")
+    print(f"    하락기 {_dns} — 그 외 보합. (G-작동 대조: 1994·1999~2000·2004~06·2015~18·2022)")
     print(f"\n  · 창 격자: 시작 {len(R9_START_DATES)} × 종료 {len(R9_END_DATES)} "
           f"→ 유효 {len(wins)}창 × {len(plans)}팔 = {len(wins)*len(plans)}회")
 
@@ -1910,7 +1977,7 @@
         print("\n" + "=" * 112)
         print(f"  📊 ★시작일 {win[0].date()} [{world} 세계] — 종료일 {win[-1].date()} ({yrs:.2f}년)")
         print("=" * 112)
-        print(f"   {'자산':^14}|{'눈금':>6}|{'최종자산($)':>15} |{'CAGR':>9} |{'MDD':>9} |{'세금($)':>12} |{'대피':>6}")
+        print(f"   {'자산':^14}|{'눈금':>6}|{'최종자산($)':>15} |{'CAGR':>9} |{'MDD':>9} |{'세금($)':>12} |{'대피':>6}|{'상승':>4}|{'하향':>4}")
         print("-" * 112)
         for nm, w, fp, vrp, cup, dial, route in plans:
             if route == "run_arm":
@@ -1930,14 +1997,16 @@
                          "CAGR%": round(c * 100, 3) if c == c else "", "MDD%": round(mdd, 2),
                          "최종$": round(after, 0), "세금총액$": round(res['tax_total'], 0),
                          "위기일최악%": round(worst, 3) if worst == worst else "",
-                         "KS발동": res['n_exit'], "대피일수": res['evac_days']})
+                         "KS발동": res['n_exit'], "대피일수": res['evac_days'],
+                         "상승판정연수": res.get('rate_up', 0), "하향적용연수": res.get('rate_dn', 0)})
             cg = f"{c*100:>8.2f}%" if c == c else "       —"
-            print(f"   {nm:^14}|{dial:>6.2f}|{after:>15,.0f} |{cg} |{mdd:>8.2f}% |{res['tax_total']:>12,.0f} |{res['evac_days']:>6}")
+            print(f"   {nm:^14}|{dial:>6.2f}|{after:>15,.0f} |{cg} |{mdd:>8.2f}% |{res['tax_total']:>12,.0f} |"
+                  f"{res['evac_days']:>6}|{res.get('rate_up', 0):>4}|{res.get('rate_dn', 0):>4}")
             store[nm] = (nav, c, mdd)
         print("-" * 112)
         if y in (2000, 2010): charts[y] = (store, win)
     S = pd.DataFrame(rows)
-    S.to_csv("summary_r9.csv", index=False, encoding="utf-8-sig")
+    S.to_csv(f"summary_rate_a_{RATE_ACCEL}.csv", index=False, encoding="utf-8-sig")
 
     names = [p_[0] for p_ in plans]
     for world in ("옛", "최신"):
@@ -1959,7 +2028,7 @@
                   f"세금 적음 {int((a['세금총액$'] < b['세금총액$']).sum())}/{len(a)}창")
 
     print("\n  [V5] 산출물 md5:")
-    print(f"      summary_r9.csv : {_md5_file('summary_r9.csv')}  ({len(S)}행)")
+    print(f"      summary_rate_a_{RATE_ACCEL}.csv : {_md5_file(f'summary_rate_a_{RATE_ACCEL}.csv')}  ({len(S)}행)")
     print(f"      script         : {self_md5}")
     try:
         import matplotlib
@@ -1984,7 +2053,7 @@
                 a2.plot(nav.index, (nav / nav.cummax() - 1) * 100, lw=1.0, color=palette[k % len(palette)])
             a1.set_yscale("log"); a1.set_ylabel("NAV (USD, Log)"); a1.legend(fontsize=9); a1.grid(alpha=0.3)
             a2.set_ylabel("DD (%)"); a2.grid(alpha=0.3)
-            plt.tight_layout(); out = f"r9_chart_{y}.png"
+            plt.tight_layout(); out = f"rate_a_{RATE_ACCEL}_chart_{y}.png"
             plt.savefig(out, dpi=100, bbox_inches="tight")
             print(f"  · 차트 저장: {out}")
             if in_nb:
