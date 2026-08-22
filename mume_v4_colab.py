--- /mnt/user-data/outputs/fs_scorecard.py	2026-08-22 09:44:59.719404000 +0000
+++ fs_scorecard.py	2026-08-22 10:01:48.235446665 +0000
@@ -33,7 +33,7 @@
 RET_DD         = 0.10
 FETCH_START    = "1985-10-01"
 EXIT_INDEX     = "NDX"     # 명세 §3-1: 사건 수 대조는 동일 설정 실행분과만
-FRED_CSV       = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
+FRED_CSV       = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1985-10-01"   # ★수정1: 기본 3년창 방지
 M0_PATHS       = ["m0_full.csv", "/content/drive/MyDrive/m0_full.csv"]
 
 def _md5s(s): return hashlib.md5(s.encode() if isinstance(s, str) else s).hexdigest()[:8]
@@ -50,8 +50,10 @@
         pass
     return None
 
-def fetch_fred(sid, min_rows=100):
-    """FRED 시리즈 수신 — 캐시 로컬+드라이브 동시 저장(Colab 표준), 재실행 시 캐시 우선."""
+def fetch_fred(sid, min_rows=100, max_start=None):
+    """FRED 시리즈 수신 — 캐시 로컬+드라이브 동시 저장(Colab 표준), 재실행 시 캐시 우선.
+       ★수정2(감사역): max_start 가드 — 시리즈 시작일이 이보다 늦으면 절단 수신으로 간주.
+       절단된 기존 캐시는 자동 무시하고 재수신하며, 재수신도 늦으면 실행 중단·보고."""
     fn = f"fred_{sid}.csv"
     db = _ensure_drive()
     for p in [fn] + ([f"{db}/{fn}"] if db else []):
@@ -59,6 +61,9 @@
             try:
                 s = pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0].dropna()
                 if len(s) >= min_rows:
+                    if max_start is not None and s.index[0] > pd.Timestamp(max_start):
+                        print(f"  · {sid} 캐시 절단 감지({p}: {s.index[0].date()} 시작) — 무시하고 재수신")
+                        continue
                     print(f"  · {sid} 캐시 사용: {p} ({len(s)}행, md5={_md5_file(p)})")
                     return s
             except Exception:
@@ -74,6 +79,9 @@
         try: s.to_csv(f"{db}/{fn}")
         except Exception: pass
     print(f"  · {sid} 수신: {len(s)}행 ({s.index[0].date()}~{s.index[-1].date()}) — 캐시 로컬{'+드라이브' if db else ''} 저장")
+    if max_start is not None and s.index[0] > pd.Timestamp(max_start):
+        raise SystemExit(f"★중단: {sid} 시작일 {s.index[0].date()} > 허용 {max_start} — 절단 수신. "
+                         f"신용 채점 무효 방지를 위해 실행을 멈춥니다(감사역 수정 2).")
     return s
 
 def fetch_m0():
@@ -141,7 +149,7 @@
     sahm = ma3 - ma3.rolling(12).min()                      # 명세 §0 정의(자체 계산)
     avail = sahm.copy()
     avail.index = (sahm.index + pd.offsets.MonthBegin(1)) + pd.Timedelta(days=9)   # M+1월 10일
-    hy = fetch_fred("BAMLH0A0HYM2")
+    hy = fetch_fred("BAMLH0A0HYM2", max_start="1997-01-10")   # ★수정2: 절단 수신 시 중단
     baa = fetch_fred("DBAA"); g10 = fetch_fred("DGS10")
     fb = (baa - g10.reindex(baa.index).ffill()).dropna()
     cut = pd.Timestamp("1996-12-31")
@@ -183,10 +191,13 @@
     sahm, sahm_rt, avail, c, usrec = build_macro()
 
     # ── SAHMREALTIME 대조표 1회(명세 §3-3) ──
-    both = pd.concat([sahm.rename('자체'), sahm_rt.rename('FRED')], axis=1).dropna()
+    rt_al = sahm_rt.copy()                                   # ★선택(감사역 §4): 실시간 시리즈는 한 달 뒤
+    rt_al.index = rt_al.index - pd.offsets.MonthBegin(1)     #   시점 기준 — 한 달 당겨 정렬 후 비교
+    both = pd.concat([sahm.rename('자체'), rt_al.rename('FRED')], axis=1).dropna()
     diff = (both['자체'] - both['FRED']).abs()
-    print(f"\n  [대조] 자체 Sahm vs SAHMREALTIME: 겹침 {len(both)}개월 · 최대차 {diff.max():.3f} · "
-          f"불일치(>0.05) {int((diff > 0.05).sum())}건" + (" — 보고 요망" if (diff > 0.05).any() else " ✓"))
+    print(f"\n  [대조] 자체 Sahm vs SAHMREALTIME(한 달 시프트 정렬): 겹침 {len(both)}개월 · "
+          f"최대차 {diff.max():.3f} · 불일치(>0.05) {int((diff > 0.05).sum())}건"
+          + (" — 보고 요망" if (diff > 0.05).any() else " ✓"))
 
     dates = list(ndx.index)
     pos = {d: k for k, d in enumerate(dates)}
