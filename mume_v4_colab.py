--- kelly17_research_r4.py	2026-08-15 10:05:27.549446316 +0000
+++ kelly17_research_r6.py	2026-08-15 13:30:39.470248821 +0000
@@ -23,6 +23,10 @@
 EXTRA_REPAY_PCT = 30
 # ★ on이면 정본 비교표 모드, off면 표준 52창 주행
 COMPARE_MODE = "on"
+# ★ on이면 R6 혼합비율 스윕 모드(FAST:VR 배분 12점 × R1 24창). 다른 모드보다 우선한다.
+SWEEP_MODE = "on"
+# ★ on이면 스윕을 비교 창 세트(시작 14 × 종료 6)로 확장. 기본 off(R1 24창)
+SWEEP_WIDE = "off"
 
 import os, hashlib
 import numpy as np
@@ -84,6 +88,22 @@
                     "2013-01-02", "2016-01-02", "2019-01-02", "2022-01-02", "2024-01-02"]  # FAST 정본 93행
 CMP_END_DATES = ["2018-12-31", "2020-12-31", "2021-12-31", "2022-12-30", "2024-12-31", "2026-07-10"]  # VR 정본 원문
 FAST_STD_INIT = 100_000.0             # FAST 정본 관행 초기값(INITIAL_CAPITAL, 96행)
+# ── [R6] 혼합비율 스윕 점(사양 R6-2): 총액 $207,300 고정, (점, FAST시작, VR시작, 참고표시) ──
+R6_TOTAL = 207_300.0
+R6_POINTS = [("P0",  207_300.0,       0.0, "FAST 단독(정본 대조점)"),
+             ("P1",  200_000.0,   7_300.0, "현행(회귀 대조점)"),
+             ("P2",  186_570.0,  20_730.0, ""),
+             ("P3",  165_840.0,  41_460.0, ""),
+             ("P4",  145_110.0,  62_190.0, ""),
+             ("P5",  124_380.0,  82_920.0, "나스닥 노출 금액 동일(기존 정지선 위치)"),
+             ("P6",  103_650.0, 103_650.0, ""),
+             ("P7",   82_920.0, 124_380.0, ""),
+             ("P8",   62_190.0, 145_110.0, ""),
+             ("P9",   41_460.0, 165_840.0, ""),
+             ("P10",  20_730.0, 186_570.0, ""),
+             ("P11",       0.0, 207_300.0, "VR 단독(정본 대조점)")]
+R6_CHART_POINTS = ["P0", "P1", "P4", "P7", "P11"]     # 겹침 그래프 대표 점(사양 R6-3)
+R6_MDD_REF = -55.0                                    # 낙폭 참고선(%)
 FETCH_START_DATE = FETCH_START
 END_DATE = pd.Timestamp.today().strftime('%Y-%m-%d')
 
@@ -1536,6 +1556,166 @@
         prev = ye[y]
     return rows
 
+def main_sweep(D, self_md5):
+    """★R6 신설(사양 R6-2~R6-5): FAST:VR 혼합비율 스윕. 엔진 함수 무수정 — run_r4의 기존 인자
+       (fast_init·vr_init·vr_stock_w)만 점별로 바꿔 호출한다(1699·1705행 전례와 동일 방식)."""
+    print("  · [SWEEP 모드] MONTHLY_M·EXTRA_REPAY_PCT·COMPARE_MODE는 무시되고 적립 0·단일 시나리오로 강제됩니다.")
+    print(f"  · 제로베이스 실험 — 봉인 조항 없음. 표의 '현행'·'정지선' 표시는 위치 참고용이며 제약이 아닙니다.")
+    print(f"  · 총액 ${R6_TOTAL:,.0f} 고정 · VR 시작 분할 {VR_START_STOCK_W*100:.1f}:{(1-VR_START_STOCK_W)*100:.1f} 전 점 동일")
+    for tag, f0, v0, note in R6_POINTS:                 # 사양 R6-5: 합계 보존 실행 시 검산
+        assert abs((f0 + v0) - R6_TOTAL) < 1e-6, f"{tag} 합계 불일치: {f0 + v0}"
+    assert R6_POINTS[1][1] == 200_000.0 and R6_POINTS[1][2] == 7_300.0, "P1 금액 고정 위반"
+
+    if ON(SWEEP_WIDE):
+        wins = []
+        starts = sorted(set(VR_START_DATES) | set(FAST_START_DATES))
+        for sd in starts:
+            for ed in CMP_END_DATES:
+                s_t, e_t = pd.Timestamp(sd), pd.Timestamp(ed)
+                if s_t < D.index[0] or e_t <= s_t or e_t > D.index[-1]: continue
+                w = D.index[(D.index >= s_t) & (D.index <= e_t)]
+                if len(w) >= 260: wins.append((f"{sd}~{ed}", sd, w))
+        print(f"  · 창 세트: 비교 창 확장(SWEEP_WIDE=on) — {len(wins)}창")
+    else:
+        wins = []
+        for y in R1_YEARS:
+            start = D.index[D.index >= f"{y}-01-01"][0]
+            wins.append((str(y), y, D.index[(D.index >= start) & (D.index < start + pd.DateOffset(years=WINDOW_Y))]))
+        print(f"  · 창 세트: R1 완결 17년 {len(wins)}창(기본)")
+    print(f"  · 주행 횟수: {len(wins)} × {len(R6_POINTS)} = {len(wins) * len(R6_POINTS)}회")
+
+    # ── G2 실행 검문소(사양 R6-4): 양 끝점을 각각 다른 정본 엔진과 직접 대조 ──
+    print("\n" + "-" * 118)
+    print("  [G2] 양 끝점 대조 — ⓐ P0 ↔ 정본 run_simulation(207,300·W_A) / ⓑ P11 ↔ 정본 run_vr(207,300·Pool 23.4%)")
+    for label, y, win in [w for w in wins if str(w[1]) in ("1994", "2000", "2010")][:3]:
+        sub = D.loc[win]; yrs = (win[-1] - win[0]).days / 365.25
+        r0 = run_r4(D, win, 0.0, 0.0, fast_init=R6_TOTAL, vr_init=0.0)
+        c0 = (float(r0['nav'].iloc[-1]) / R6_TOTAL) ** (1 / yrs) - 1
+        nav_o, _ = run_simulation(sub, R6_TOTAL, W_A, method='fast_recover')
+        co = (float(nav_o.iloc[-1]) / R6_TOTAL) ** (1 / yrs) - 1
+        da = (c0 - co) * 100
+        r11 = run_r4(D, win, 0.0, 0.0, fast_init=0.0, vr_init=R6_TOTAL)
+        c11 = (float(r11['nav'].iloc[-1]) / R6_TOTAL) ** (1 / yrs) - 1
+        vr_o = run_vr(sub, R6_TOTAL, 1.0 - VR_START_STOCK_W, HOLD_G, HOLD_LIMIT, killswitch=True)
+        cv = vr_o['cagr']
+        db = (c11 - cv) * 100
+        okA, okB = abs(da) <= 0.5, abs(db) <= 0.5
+        print(f"    [{label}] ⓐ P0 {c0*100:6.2f}% vs 정본 {co*100:6.2f}% → 차 {da:+.3f}%p {'PASS' if okA else '★FAIL'} | "
+              f"ⓑ P11 {c11*100:6.2f}% vs 정본 {cv*100:6.2f}% → 차 {db:+.3f}%p {'PASS' if okB else '★FAIL'}")
+        assert okA and okB, f"G2 실패: {label} (어긋나면 실험 중단 — 사양 R6-4)"
+
+    # ── 본 스윕 ──
+    print("\n" + "-" * 118)
+    print(f"  [V3] 창 무결({len(wins)}창) · [V4] BOXX 대역 ↔ 단기금리 ±0.3%p")
+    rows = []; navs = {}
+    for label, y, win in wins:
+        sub = D.loc[win]
+        assert not sub[['TQQQ', 'gold', 'GSPC_RAW', 'NDX_RAW', 'IRXD', 'Bubble_Value']].isna().any().any(), f"{label} 결측"
+        yrs = (win[-1] - win[0]).days / 365.25
+        bx = sub['BOXX']; b_cagr = (bx.iloc[-1] / bx.iloc[0]) ** (1 / yrs) - 1
+        v4 = abs(b_cagr * 100 - float(sub['IRX'].mean()))
+        assert v4 <= 0.3, f"V4 실패 {label}: {v4:.2f}%p"
+        rl = sub['TQQQ'].pct_change().to_numpy()[1:]
+        cmask = rl <= CRISIS_DD
+        for tag, f0, v0, note in R6_POINTS:
+            res = run_r4(D, win, 0.0, 0.0, fast_init=f0, vr_init=v0)    # 적립 0·시나리오 1개(강제)
+            nav = res['nav']; after = float(nav.iloc[-1])
+            cg = (after / R6_TOTAL) ** (1 / yrs) - 1 if after > 0 else float('nan')
+            mdd = float((nav / nav.cummax() - 1).min()) * 100
+            r_adj = ((nav - res['cf']) / nav.shift(1) - 1.0).to_numpy()[1:]
+            worst = float(np.nanmin(r_adj[cmask]) * 100) if cmask.any() else float('nan')
+            rows.append({"창": label, "점": tag, "FAST시작$": round(f0, 0), "VR시작$": round(v0, 0),
+                         "VR비중%": round(v0 / R6_TOTAL * 100, 2),
+                         "CAGR%": round(cg * 100, 3) if cg == cg else "", "MDD%": round(mdd, 2),
+                         "최종배수": round(after / R6_TOTAL, 3), "세금총액$": round(res['tax_total'], 0),
+                         "KS발동": res['n_exit'], "대피일수": res['evac_days'],
+                         "위기일최악%": round(worst, 3) if worst == worst else "", "참고": note})
+            if str(y) in ("2000", "2010") and tag in R6_CHART_POINTS:
+                navs.setdefault(str(y), {})[tag] = (nav, cg, mdd)
+        print(f"    {label}: {win[0].date()}~{win[-1].date()} {yrs:5.2f}년 {len(win):>5,}일 | "
+              f"[V4] BOXX {b_cagr*100:5.2f}% vs IRX {float(sub['IRX'].mean()):5.2f}% ({v4:.2f}%p PASS)")
+    S = pd.DataFrame(rows)
+    S.to_csv("summary_r6_sweep.csv", index=False, encoding="utf-8-sig")
+
+    # ── 콘솔 매트릭스 3장(행=창, 열=P0~P11) ──
+    tags = [t for t, _, _, _ in R6_POINTS]
+    for title, col, fmt in [("① 연복리 수익률(%)", "CAGR%", "{:>7.2f}"),
+                            ("② 최대낙폭(%)", "MDD%", "{:>7.1f}"),
+                            ("③ 세금총액($)", "세금총액$", "{:>7,.0f}")]:
+        print("\n" + "=" * 118)
+        print(f"  [매트릭스] {title} — 행=창 시작, 열=VR 비중")
+        print("    " + "창".ljust(10) + "".join(f"{t:>8}" for t in tags))
+        print("    " + " ".ljust(10) + "".join(f"{v0/R6_TOTAL*100:>7.0f}%" for _, _, v0, _ in R6_POINTS))
+        for label, y, win in wins:
+            cells = []
+            for t in tags:
+                v = S[(S["창"] == label) & (S["점"] == t)][col]
+                cells.append(fmt.format(float(v.iloc[0])) if len(v) and v.iloc[0] != "" else "      —")
+            print("    " + str(label).ljust(10) + "".join(cells))
+        med = [pd.to_numeric(S[S["점"] == t][col], errors='coerce').median() for t in tags]
+        print("    " + "중앙값".ljust(9) + "".join(fmt.format(m) if m == m else "      —" for m in med))
+
+    print("\n  [V5] 산출물 md5 — 칠판 업로드 후 감사역이 raw+캐시버스팅으로 수신·대조:")
+    print(f"      summary_r6_sweep.csv : {_md5_file('summary_r6_sweep.csv')}  ({len(S)}행)")
+    print(f"      script               : {self_md5}")
+
+    # ── 그래프: ①비율축 요약 ②대표 창 겹침 ──
+    try:
+        import matplotlib
+        try:
+            from IPython import get_ipython
+            in_nb = (get_ipython() is not None) or ('google.colab' in __import__('sys').modules)
+        except Exception:
+            in_nb = False
+        if not in_nb: matplotlib.use("Agg")
+        import matplotlib.pyplot as plt
+        _setup_korean_font()
+        xs = [v0 / R6_TOTAL * 100 for _, _, v0, _ in R6_POINTS]
+        med_c = [pd.to_numeric(S[S["점"] == t]["CAGR%"], errors='coerce').median() for t in tags]
+        med_m = [pd.to_numeric(S[S["점"] == t]["MDD%"], errors='coerce').median() for t in tags]
+        fig, ax1 = plt.subplots(figsize=(12, 7))
+        ax1.set_title(f"R6 혼합비율 스윕 — VR 비중별 {len(wins)}창 중앙값 (총액 ${R6_TOTAL:,.0f}, 적립 0)")
+        ax1.plot(xs, med_c, "o-", color="crimson", lw=2, label="중앙 연복리(좌)")
+        ax1.set_xlabel("VR 비중 (%)"); ax1.set_ylabel("연복리 (%)", color="crimson")
+        ax1.grid(alpha=0.3)
+        ax2 = ax1.twinx()
+        ax2.plot(xs, med_m, "s--", color="#1f77b4", lw=2, label="중앙 최대낙폭(우)")
+        ax2.axhline(R6_MDD_REF, color="gray", ls=":", lw=1.5, label=f"{R6_MDD_REF:.0f}% 참고선")
+        ax2.set_ylabel("최대낙폭 (%)", color="#1f77b4")
+        h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
+        ax1.legend(h1 + h2, l1 + l2, fontsize=9, loc="best")
+        plt.tight_layout(); plt.savefig("r6_sweep_summary.png", dpi=100, bbox_inches="tight")
+        print("  · 차트 저장: r6_sweep_summary.png")
+        if in_nb:
+            try: plt.show()
+            except Exception: pass
+        plt.close()
+        cols = {"P0": "#7f7f7f", "P1": "crimson", "P4": "#2ca02c", "P7": "#ff7f0e", "P11": "#1f77b4"}
+        for ykey, store in sorted(navs.items()):
+            fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 8),
+                                         gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
+            a1.set_title(f"R6 스윕 대표 창 {ykey} 시작 — VR 비중별 자산 곡선")
+            for t in R6_CHART_POINTS:
+                if t not in store: continue
+                nav, cg, mdd = store[t]
+                pct = next(v0 / R6_TOTAL * 100 for tg, _, v0, _ in R6_POINTS if tg == t)
+                a1.plot(nav.index, nav, lw=1.5, color=cols.get(t),
+                        label=f"{t} VR {pct:.0f}% (CAGR {cg*100:.1f}%, MDD {mdd:.1f}%)")
+                a2.plot(nav.index, (nav / nav.cummax() - 1) * 100, lw=1.1, color=cols.get(t))
+            a1.set_yscale("log"); a1.set_ylabel("NAV (USD, Log)"); a1.legend(fontsize=9); a1.grid(alpha=0.3)
+            a2.axhline(R6_MDD_REF, color="gray", ls=":", lw=1.2)
+            a2.set_ylabel("DD (%)"); a2.grid(alpha=0.3)
+            plt.tight_layout(); out = f"r6_chart_{ykey}.png"
+            plt.savefig(out, dpi=100, bbox_inches="tight")
+            print(f"  · 차트 저장: {out}")
+            if in_nb:
+                try: plt.show()
+                except Exception: pass
+            plt.close()
+    except Exception as e:
+        print(f"  · 차트 생략({str(e)[:70]})")
+    print("=" * 118)
+
 def main_compare(D, self_md5):
     """★v3 비교 모드(사양 v1.1 불변·판정 로직 무변경): 정본 창 세트(시작 합집합 14 × 종료 6)에서
        R4통합 | FAST단독(정본 run_simulation) | VR단독(정본 run_vr) | TQQQ보유 | QQQ보유 병렬 비교."""
@@ -1681,6 +1861,8 @@
 
     D = build_master()
     print(f"  · 기준 달력: ^NDX 실거래일 {D.index[0].date()} ~ {D.index[-1].date()} ({len(D)}일)")
+    if ON(SWEEP_MODE):
+        return main_sweep(D, self_md5)
     if ON(COMPARE_MODE):
         return main_compare(D, self_md5)
     wins = _win_list(D.index)
