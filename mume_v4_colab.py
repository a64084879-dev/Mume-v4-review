--- /mnt/user-data/outputs/fs_scorecard.py	2026-08-22 10:02:30.066371000 +0000
+++ fs_scorecard.py	2026-08-22 11:02:59.153898650 +0000
@@ -32,6 +32,13 @@
 RET_WIN2       = 252       # 병기 전용(채점 기준은 126 고정)
 RET_DD         = 0.10
 FETCH_START    = "1985-10-01"
+# ── 신용 c(t) 3원 접합(추록1 §2, 2026-08-22 재가): 임계·판정식 무변경 ──
+MIRROR_URL     = "https://raw.githubusercontent.com/csaladenes/eco-archive/master/BAMLH0A0HYM2.csv"
+MIRROR_MD5     = "ec8668ebf7bd9e5a7cf68e15c993482c"   # 고정 — 불일치 시 실행 중단(추록1 §3a)
+HY_CUT         = "1996-12-31"     # 이전 = 폴백(기존)
+MIRROR_END     = "2021-03-19"     # 미러 구간 끝
+GAP_END        = "2023-08-21"     # 공백(폴백) 구간 끝 — 이후 = 현행 FRED
+FRESH_DAYS     = 14               # 추록1 §3c: 현행 구간 마지막 관측 최신성
 EXIT_INDEX     = "NDX"     # 명세 §3-1: 사건 수 대조는 동일 설정 실행분과만
 FRED_CSV       = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1985-10-01"   # ★수정1: 기본 3년창 방지
 M0_PATHS       = ["m0_full.csv", "/content/drive/MyDrive/m0_full.csv"]
@@ -84,6 +91,36 @@
                          f"신용 채점 무효 방지를 위해 실행을 멈춥니다(감사역 수정 2).")
     return s
 
+def fetch_mirror():
+    """추록1 §2: GitHub 미러(1996-12-31~2021-03-19). 캐시 로컬+드라이브 — 사용 전마다 md5 재검증,
+       다운로드본도 md5 불일치면 즉시 중단(행수가 아니라 md5로 가드)."""
+    fn = "hy_mirror_BAMLH0A0HYM2.csv"
+    db = _ensure_drive()
+    raw = None
+    for p_ in [fn] + ([f"{db}/{fn}"] if db else []):
+        if os.path.exists(p_):
+            b = open(p_, 'rb').read()
+            if hashlib.md5(b).hexdigest() == MIRROR_MD5:
+                print(f"  · 미러 캐시 사용: {p_} (md5 일치 {MIRROR_MD5[:8]})")
+                raw = b; break
+            print(f"  · 미러 캐시 md5 불일치({p_}) — 무시하고 재수신")
+    if raw is None:
+        r = requests.get(MIRROR_URL, timeout=60); r.raise_for_status()
+        raw = r.content
+        got = hashlib.md5(raw).hexdigest()
+        if got != MIRROR_MD5:
+            raise SystemExit(f"★중단: 미러 md5 {got[:8]} ≠ 고정 {MIRROR_MD5[:8]} — 무결성 실패(추록1 §3a).")
+        open(fn, 'wb').write(raw)
+        if db:
+            try: open(f"{db}/{fn}", 'wb').write(raw)
+            except Exception: pass
+        print(f"  · 미러 수신: md5 일치 {MIRROR_MD5[:8]} — 캐시 로컬{'+드라이브' if db else ''} 저장")
+    df = pd.read_csv(io.BytesIO(raw))
+    df.columns = ['DATE', 'V']
+    s = pd.to_numeric(df.set_index(pd.to_datetime(df['DATE']))['V'], errors='coerce').dropna()
+    print(f"  · 미러 유효 관측 {len(s)}개 ({s.index[0].date()}~{s.index[-1].date()}) — 결측 자동 제거")
+    return s
+
 def fetch_m0():
     """M0(BOGMBASE, 십억$) — 백테스터 정본 캐시(m0_full.csv) 우선 재사용(명세 §1)."""
     db = _ensure_drive()
@@ -149,16 +186,28 @@
     sahm = ma3 - ma3.rolling(12).min()                      # 명세 §0 정의(자체 계산)
     avail = sahm.copy()
     avail.index = (sahm.index + pd.offsets.MonthBegin(1)) + pd.Timedelta(days=9)   # M+1월 10일
-    hy = fetch_fred("BAMLH0A0HYM2", max_start="1997-01-10")   # ★수정2: 절단 수신 시 중단
+    hy_new = fetch_fred("BAMLH0A0HYM2")                        # 현행 3년 롤링 창(추록1 §2)
+    if (pd.Timestamp.now().normalize() - hy_new.index[-1]).days > FRESH_DAYS:
+        raise SystemExit(f"★중단: 현행 FRED 마지막 관측 {hy_new.index[-1].date()}가 "
+                         f"실행일 기준 {FRESH_DAYS}일 초과(추록1 §3c).")
+    mir = fetch_mirror()
     baa = fetch_fred("DBAA"); g10 = fetch_fred("DGS10")
     fb = (baa - g10.reindex(baa.index).ffill()).dropna()
-    cut = pd.Timestamp("1996-12-31")
-    c = pd.concat([fb[fb.index < cut], hy[hy.index >= cut]]).sort_index()
+    cut, me, ge = pd.Timestamp(HY_CUT), pd.Timestamp(MIRROR_END), pd.Timestamp(GAP_END)
+    c = pd.concat([fb[fb.index < cut],                          # ~1996-12-30 폴백(기존)
+                   mir[(mir.index >= cut) & (mir.index <= me)], # 미러
+                   fb[(fb.index > me) & (fb.index <= ge)],      # 공백 폴백(사건 0건 — 추록1 §2)
+                   hy_new[hy_new.index > ge]]).sort_index()     # 현행
     c = c[~c.index.duplicated()]
-    ov = pd.concat([fb, hy], axis=1, keys=['fb', 'hy']).dropna()
-    if len(ov) > 50:
-        print(f"  · 폴백 겹침 보고(1997~): 상관 {ov['fb'].corr(ov['hy']):.3f} · "
-              f"평균 수준차(하이일드−폴백) {float((ov['hy']-ov['fb']).mean()):+.2f}%p ({len(ov)}일)")
+    if c.index[0] > pd.Timestamp("1997-01-10"):
+        raise SystemExit(f"★중단: 접합 후 c(t) 시작일 {c.index[0].date()} > 1997-01-10(추록1 §3b).")
+    ov1 = pd.concat([fb, mir], axis=1, keys=['fb', 'x']).dropna()
+    ov2 = pd.concat([fb, hy_new], axis=1, keys=['fb', 'x']).dropna()
+    print(f"  · 겹침 보고 ①폴백↔미러(1996-12-31~{MIRROR_END}): 상관 {ov1['fb'].corr(ov1['x']):.3f} · "
+          f"수준차(미러−폴백) {float((ov1['x']-ov1['fb']).mean()):+.2f}%p ({len(ov1)}일)")
+    print(f"  · 겹침 보고 ②폴백↔현행(2023-08-22~): 상관 {ov2['fb'].corr(ov2['x']):.3f} · "
+          f"수준차(현행−폴백) {float((ov2['x']-ov2['fb']).mean()):+.2f}%p ({len(ov2)}일)")
+    print("  · 미러↔현행 직접 겹침 없음(공백 2021-03-20~2023-08-21 존재 — 폴백으로 접합, 추록1 §4)")
     usrec = fetch_fred("USREC", min_rows=50)
     return sahm, sahm_rt, avail, c, usrec
 
@@ -173,6 +222,16 @@
     cv = float(s.iloc[-1])
     return cv, float(cv - s.iloc[-MIN126:].min()), float(cv - s.iloc[-1 - D20])
 
+def _src_of(c, t):
+    """채점에 쓰인 c(t)의 소스(추록1 §4): 전일 마지막 관측일 기준."""
+    s = c[c.index < t]
+    if not len(s): return "결측"
+    d = s.index[-1]
+    if d < pd.Timestamp(HY_CUT): return "폴백"
+    if d <= pd.Timestamp(MIRROR_END): return "미러"
+    if d <= pd.Timestamp(GAP_END): return "폴백"
+    return "현행"
+
 def main():
     print("=" * 110)
     print("  [거짓 탈출·복귀 채점표] 명세 v1(md5 0931ca7e) — 관찰 전용 · 킬스위치 판정 무변경 · 임계 사전 고정")
@@ -226,7 +285,7 @@
                             스프레드=(round(cv, 2) if cv == cv else "결측"),
                             초과min126=(round(over, 2) if over == over else ""), Δ20=(round(d20, 2) if d20 == d20 else ""),
                             S2=s2, 점수=E, 추가하락pct=round(dd * 100, 1), USREC=int(has_rec),
-                            정답=truth, 판정=hit))
+                            소스=_src_of(c, t), 정답=truth, 판정=hit))
 
     # ── 복귀 채점 ──
     rt_rows = []
@@ -254,7 +313,7 @@
         rt_rows.append(dict(종류="복귀", 날짜=str(t.date()), 탈출일=str(ed.date()) if ed is not None else "",
                             버블=round(r['bub'], 3), 스프레드=(round(cv, 2) if cv == cv else "결측"),
                             peak=(round(peak, 2) if peak == peak else ""), Δ20=(round(d20, 2) if d20 == d20 else ""),
-                            점수=R, 정답=truth, 정답252=t252, 판정=hit))
+                            점수=R, 소스=_src_of(c, t), 정답=truth, 정답252=t252, 판정=hit))
 
     T = pd.DataFrame(ex_rows + rt_rows)
     T.to_csv("fs_scorecard.csv", index=False, encoding="utf-8-sig")
@@ -263,16 +322,16 @@
     print("\n" + "-" * 110)
     print("  [채점표 — 탈출]  (지표는 전일 기준 · Sahm은 발표지연 반영 가용 최신월)")
     print(f"   {'날짜':^12}|{'버블':>6}|{'Sahm':>6}|{'S1':>3}|{'스프레드':>8}|{'초과':>6}|{'Δ20':>6}|{'S2':>3}|"
-          f"{'E':>3}|{'추가하락':>8}|{'REC':>4}|{'정답':^4}|{'판정':^4}")
+          f"{'E':>3}|{'추가하락':>8}|{'REC':>4}|{'소스':^4}|{'정답':^4}|{'판정':^4}")
     for r in ex_rows:
         print(f"   {r['날짜']:^12}|{r['버블']:>6}|{str(r['Sahm']):>6}|{r['S1']:>3}|{str(r['스프레드']):>8}|"
               f"{str(r['초과min126']):>6}|{str(r['Δ20']):>6}|{r['S2']:>3}|{r['점수']:>3}|"
-              f"{r['추가하락pct']:>7.1f}%|{r['USREC']:>4}|{r['정답']:^4}|{r['판정']:^4}")
+              f"{r['추가하락pct']:>7.1f}%|{r['USREC']:>4}|{r['소스']:^4}|{r['정답']:^4}|{r['판정']:^4}")
     print("\n  [채점표 — 복귀]  (peak = 대피 에피소드 내 스프레드 최고)")
-    print(f"   {'날짜':^12}|{'탈출일':^12}|{'스프레드':>8}|{'peak':>7}|{'Δ20':>6}|{'R':>3}|{'정답':^4}|{'252일':^5}|{'판정':^4}")
+    print(f"   {'날짜':^12}|{'탈출일':^12}|{'스프레드':>8}|{'peak':>7}|{'Δ20':>6}|{'R':>3}|{'소스':^4}|{'정답':^4}|{'252일':^5}|{'판정':^4}")
     for r in rt_rows:
         print(f"   {r['날짜']:^12}|{r['탈출일']:^12}|{str(r['스프레드']):>8}|{str(r['peak']):>7}|"
-              f"{str(r['Δ20']):>6}|{r['점수']:>3}|{r['정답']:^4}|{r['정답252']:^5}|{r['판정']:^4}")
+              f"{str(r['Δ20']):>6}|{r['점수']:>3}|{r['소스']:^4}|{r['정답']:^4}|{r['정답252']:^5}|{r['판정']:^4}")
 
     # ── 혼동행렬(신호별·합산) ──
     def _mat(rows, key, name):
