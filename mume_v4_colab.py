# -*- coding: utf-8 -*-
# [K12 프록시 — 오프라인 합성 회귀 하니스] 2026-08-06 (2차: K8~K12)
#  (1) 기본 스위치(REC_HOT_INDEX="GSPC"·REC_LAB=False)에서 K12판 run_simulation이
#      K판(bc9d8f3a)과 NAV·매매로그 완전 동일(bit-동일) — 두 method 모두, 합성 df 2종
#  (2) note 회귀: 기본 로그에 'recover_spx_only' 실제 발생(비공허) + 'recover_ndx_only' 부재
#  (3) 스위치 실효성: GATE=NONE·REC=NDX에서 'recover_ndx_only' 실제 발생(치환 행 실행 입증)
#  (4) [5i] 6조합(EXIT=NDX 고정) + boost 변형 무오류
#  ※ 실데이터 K12 회귀는 Colab에서 같은 세션 연속 실행으로 별도 수행.
import sys, types, io, contextlib
import numpy as np
import pandas as pd

try:
    import google as _g
except ImportError:
    _g = types.ModuleType('google'); _g.__path__ = []
    sys.modules['google'] = _g
_gc = types.ModuleType('google.colab'); _gd = types.ModuleType('google.colab.drive')
_gd.mount = lambda *a, **k: print("  [stub] drive.mount 무시(오프라인 하니스)")
_gc.drive = _gd; _g.colab = _gc
sys.modules['google.colab'] = _gc; sys.modules['google.colab.drive'] = _gd

import importlib.util
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

print("▶ 모듈 로드")
K  = _load('k_mod',  'fast_boxx_v3tax_K.py')     # 이번 base (bc9d8f3a)
K2 = _load('k12_mod', 'fast_boxx_v3tax_K12.py')  # 수정본
print("  · K(base) / K12(수정본) 로드 완료")
assert K2.REC_HOT_INDEX == "GSPC" and K2.REC_LAB is False, "K8 기본값 불일치"
assert K2.EXIT_INDEX == "GSPC" and K2.GATE_MODE == "ABS" and K2.EXIT_LAB is False, "K1 기본값 훼손"
print(f"  · 기본값 확인: REC_HOT_INDEX={K2.REC_HOT_INDEX} REC_LAB={K2.REC_LAB} (K1 기본값도 유지)")

def build_df(m0_level):
    N = 3000
    idx = pd.bdate_range('1990-01-02', periods=N)
    t = np.arange(N, dtype=float)
    gspc = 300.0 * np.exp(0.00030 * t) * (1 + 0.18 * np.sin(t / 120.0))
    ndx  = 200.0 * np.exp(0.00035 * t) * (1 + 0.22 * np.sin(t / 120.0 + 0.9))
    r_ndx = np.diff(ndx) / ndx[:-1]
    tqqq = 100.0 * np.cumprod(np.r_[1.0, 1.0 + 3.0 * r_ndx])
    gold = 100.0 * np.exp(0.00010 * t) * (1 + 0.05 * np.sin(t / 200.0 + 2.0))
    boxx = 100.0 * (1.0002 ** t)
    qld  = 100.0 * np.cumprod(np.r_[1.0, 1.0 + 2.0 * r_ndx])
    df = pd.DataFrame(index=idx)
    for name, arr in [('SPY', gspc/3.0), ('QQQ', ndx/2.0), ('TQQQ', tqqq), ('QLD', qld), ('BOXX', boxx), ('gold', gold)]:
        df[name] = arr; df[f'{name}_OPEN'] = arr * 0.999
    df['GSPC_RAW'] = gspc
    df['SPY_SMA200'] = df['GSPC_RAW'].rolling(200).mean()
    df['NDX_RAW'] = ndx
    df['NDX_SMA200'] = df['NDX_RAW'].rolling(200).mean()
    df['M0'] = float(m0_level)
    df['Bubble_Value'] = df['GSPC_RAW'] / df['M0']
    df['Bubble_Pctl'] = df['Bubble_Value'].rolling(int(252*10), min_periods=int(252*3)).apply(
        lambda x: (x[-1] >= x).mean(), raw=True)
    return df.iloc[210:]

W = {'TQQQ': 0.60, 'gold': 0.40}; IC = 100_000.0
n_spx_only_total = 0
dfs = {}
for m0 in [300.0, 262.0]:
    df = build_df(m0); dfs[m0] = df
    print(f"\n▶ 합성 df(M0={m0:.0f}): {len(df)}일 | 버블 {df['Bubble_Value'].min():.2f}~{df['Bubble_Value'].max():.2f}")
    print("  (1) 기본 스위치 동치 (REC_HOT=GSPC)")
    for method in ['fast_recover', 'boost_until_annual']:
        nav_a, log_a = K.run_simulation(df, IC, dict(W), 'base', method=method)
        nav_b, log_b = K2.run_simulation(df, IC, dict(W), 'mod',  method=method)
        same_nav = nav_a.equals(nav_b); same_log = log_a.equals(log_b)
        n_ev = int((log_a['액션'] == '대피(USD대기)').sum()) if not log_a.empty else 0
        n_spx = int((log_a['종류'] == 'recover_spx_only').sum()) if not log_a.empty else 0
        n_ndx_note = int((log_b['종류'] == 'recover_ndx_only').sum()) if not log_b.empty else 0
        print(f"    · {method:<20s}: NAV 동일={same_nav} | 로그 동일={same_log} | 매매 {len(log_a)}건"
              f"(대피 {n_ev}·recover_spx_only {n_spx}) | ndx_only 노트 {n_ndx_note}건")
        assert same_nav and same_log, f"동치 실패: M0={m0}, {method}"
        assert n_ndx_note == 0, "기본 스위치에서 recover_ndx_only 노트 출현(회귀 위반)"
        if method == 'fast_recover':
            n_spx_only_total += n_spx
    # 명시 GSPC == 기본
    nav_e, log_e = K2.run_simulation(df, IC, dict(W), 'x', method='fast_recover', rec_hot_index="GSPC")
    nav_d, log_d = K2.run_simulation(df, IC, dict(W), 'x', method='fast_recover')
    assert nav_e.equals(nav_d) and log_e.equals(log_d), "명시 GSPC vs 기본 불일치"
    print("    ✅ 동치 PASS + 시그니처 폴백 PASS")

assert n_spx_only_total > 0, "합성 2종 모두 recover_spx_only 미발생 — note 회귀 검증 공허(데이터 조정 필요)"
print(f"\n  ✅ note 회귀 비공허 확인: 기본 로그 recover_spx_only 총 {n_spx_only_total}회 발생, ndx_only 0회")

print("\n▶ (3) 스위치 실효성 — GATE=NONE·REC=NDX·EXIT=NDX (핫 경로 강제)")
n_ndx_only_total = 0
for m0, df in dfs.items():
    nav_v, log_v = K2.run_simulation(df, IC, dict(W), 'v', method='fast_recover',
                                     exit_index="NDX", gate_mode="NONE", rec_hot_index="NDX")
    n_no = int((log_v['종류'] == 'recover_ndx_only').sum()) if not log_v.empty else 0
    n_so = int((log_v['종류'] == 'recover_spx_only').sum()) if not log_v.empty else 0
    n_ndx_only_total += n_no
    print(f"  · M0={m0:.0f}: recover_ndx_only {n_no}회 | recover_spx_only {n_so}회(0이어야 정상) | 매매 {len(log_v)}건")
    assert n_so == 0, "REC=NDX인데 spx_only 노트 출현"
assert n_ndx_only_total > 0, "REC=NDX 핫 복귀 미발생 — 치환 행 실행 미입증"
print(f"  ✅ 치환 행 실행 입증: recover_ndx_only 총 {n_ndx_only_total}회")

print("\n▶ (4) [5i] 6조합(EXIT=NDX 고정) + boost 변형 무오류")
df = dfs[300.0]
navs = {}
for gm in ["ABS", "B1", "NONE"]:
    for rh in ["GSPC", "NDX"]:
        nav_v, log_v = K2.run_simulation(df, IC, dict(W), f'{gm}/{rh}', method='fast_recover',
                                         exit_index="NDX", gate_mode=gm, rec_hot_index=rh)
        n_ev = int((log_v['액션'] == '대피(USD대기)').sum()) if not log_v.empty else 0
        navs[(gm, rh)] = nav_v
        print(f"  · GATE={gm:<4s} REC={rh:<4s}: 대피 {n_ev:>2}회 | 최종 {nav_v.iloc[-1]:>12,.0f}")
for gm in ["ABS", "B1", "NONE"]:
    d = "상이" if not navs[(gm, "GSPC")].equals(navs[(gm, "NDX")]) else "동일"
    print(f"  · GATE={gm:<4s}: REC GSPC vs NDX → NAV {d}")
nav_bb, log_bb = K2.run_simulation(df, IC, dict(W), 'b', method='boost_until_annual',
                                   exit_index="NDX", gate_mode="B1", rec_hot_index="NDX")
print(f"  · boost 변형(B1·EXIT=NDX·REC=NDX): 매매 {len(log_bb)}건 | 무오류")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    K2.print_event_table(log_v, df)
assert '합계(구간등락 단순합)' in buf.getvalue()
print("  ✅ 6조합 + boost 변형 + 이벤트표 전부 무오류")

print("\n══ 하니스 종합: 전 항목 PASS — 기본 스위치 완전 동치(K12 합성 기준 충족) + REC 스위치 실효 입증 ══")
