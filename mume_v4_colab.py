
코드를 정밀 검토하겠습니다. 먼저 업로드된 파일을 찾아서 기계적 검사(구문/미정의명/미사용 import)부터 확정하고, 그 위에 로직 감사를 얹겠습니다.파일 재구성 중 오류 위험 인식했음파일 재구성 중 오류 위험 인식했음업로드 폴더엔 실물이 없고 본문 인라인으로만 들어왔습니다. 정확히 그대로 파일로 재구성해 구문·미정의명 검사를 돌리겠습니다.코드 오류를 다층적으로 분석하고 심각도별 정리했다코드 오류를 다층적으로 분석하고 심각도별 정리했다기계적 검사부터: 구문 오류 없음, pyflakes 기준 미정의명(NameError) 없음 — reconcile/submit_orders/loc_submit_allowed가 try/except import에서 except 시 정의되지 않는 비대칭이 있지만, 호출부가 전부 adapter is not None 뒤에 있어 런타임에 안전합니다(수동 확인 완료). 미사용 import는 typing.Optional과 mume_v4_core.unit_amount 둘.
그 위에 로직 감사입니다. 심각도순으로, 그리고 이 파일만으로 확정되는 것과 타 모듈/백테스터 없이는 단정 못 하는 것을 구분했습니다.
A. 백테스터·실거래 정합성 (값이 어긋나면 킬스위치/B1 발동 시점이 백테스트와 달라짐 — 최우선)

M0 소스·스케일이 백테스터와 같은지 미검증. 봇은 FRED BOGMBASE + if m0.max()>100000: m0/=1000 휴리스틱으로 버블을 계산합니다. laoer_vr_compare.py가 같은 시리즈·같은 정규화를 쓰는지 같은 날짜에서 값 단위로 대조해야 합니다. HY OAS·이중가격 때 물렸던 "두 소스가 미묘하게 다름" 부류입니다. 제 원칙상 백테스터 소스를 보기 전엔 정합을 단정하지 않습니다. 덧붙여 >100000 휴리스틱 자체가 FRED 단위 변경 한 번에 조용히 깨집니다.
SMA200을 native 거래일이 아니라 영업일 리인덱스 시계열에서 계산. pd.date_range(..., freq="B")는 미국장 휴장일(7/4, 추수감사절 등)을 포함하고, 그 자리는 ffill로 직전 종가가 채워집니다. 그러면 rolling(200)이 실제 거래일 200개가 아니라 "거래일 ~190 + 중복 10"을 덮어, 임계 근처에서 above_sma200 불리언이 하루 어긋날 수 있습니다. 백테스터가 거래일 기준 SMA200이면 불일치. GSPC는 native 인덱스로 두고 M0만 리인덱스하는 편이 안전합니다.
신호일 선택에 타임존 off-by-one. bubble.index.date < datetime.date.today()에서 today()는 GitHub Actions(UTC) 날짜인데 GSPC 인덱스는 미장 날짜입니다. 크론이 UTC 자정 전에 돌면 방금 마감한 세션이 < today로 배제되어 신호가 1일 stale해집니다. 느린 오버레이라 판단이 뒤집히는 일은 드물지만, 결정론이 깨져 실거래 발동일이 백테스트 대비 하루 밀릴 수 있습니다. wall-clock 대신 "데이터의 마지막 완결 bar"를 기준으로 잡는 게 깔끔합니다.
(부수) ^GSPC period="max"는 1927년부터, M0는 1985년부터라 리인덱스 시 1985 이전 M0가 bfill로 1985년 값이 날조됩니다. 현재 신호(ts=최근)·B1(10년창)엔 영향 없지만, 나중에 전체기간 percentile을 쓰면 지뢰입니다.

B. 중간 (동작에 영향 가능 — 어댑터 소스로 확인 필요)

제출 분기가 loc_submit_allowed를 확인하지 않음. 표시용 else 분기만 창을 체크하고, 실제 제출하는 elif approved_date==today_kst: 분기는 바로 submit_orders를 호출합니다. 현재는 "아침 실행 = 새 거래일 → approved_date 리셋 → 제출 안 됨, 저녁 실행만 제출" 구조 + 크론 타이밍으로 창을 맞추고 있지만, submit_orders가 내부에서 창을 막지 않는다면 잘못된 시각에 제출될 여지가 있습니다. 제출 직전에도 게이트를 거는 걸 권장합니다.
reconcile의 cash 반환값 미사용. shares·avg는 증권사 실측으로 보정하는데 balance/현금은 보정하지 않습니다. 수수료·배당·이자 드리프트가 상태에 영영 반영되지 않습니다. 의도라면 OK지만 갭입니다.
ks_liquidate MOC 주문이 price=0.0. core의 다른 MOC(리버스 첫날 등)가 price=None을 쓴다면 관례 불일치입니다. fmt_orders가 o.price is not None으로 판정하므로 이 주문은 "MOC $0.00 × N주"로 표시됩니다(확정 표시 버그). 또 broker 어댑터가 MOC에서 price를 읽으면 0.0이 위험합니다. → price=None으로 통일하고, fmt_orders를 o.kind!="MOC" 기준으로 견고화하세요.
다중 신규거래일 + 어댑터 정상 시 pos가 day1 값만 반영. day2+는 fills=[]로 처리되는데, reconcile가 "date 시점"이 아니라 "현재 계좌"를 조회한다면 pos(현재)와 st.shares(day1까지)가 어긋나 실측보정이 과·저교정될 수 있습니다. reconcile의 date 인자 의미를 확인하세요.

C. 낮음/코스메틱/엣지

미사용 import 2개: Optional, unit_amount (pyflakes 확인).
fetch_ohlc 35일 창 — 봇이 ~7주 이상 정지하면 pending_orders가 겨냥한 날이 창 밖으로 나가 잘못된 날에 체결 추정. 일일 크론이면 사실상 무해.
/set 값 검증·클램프 없음 (shares -5, t 99(>split) 그대로 반영). 개인봇이라 우선순위 낮음.
VOLTGT vtag가 b1_evac에서도 "매수축소"로 표시 — 어차피 매수 freeze라 무해하나 오해 소지.
pending_hash/approved_hash가 _default_state에 없음(.get()로 안전하나 명시가 깔끔).

정합성 로직 자체는 맞게 짜여 있습니다 — 확인차: infer_fills의 4분기(매수 LOC 종가≤P / 매도 LOC 종가≥P / 지정가매도 고가≥P / MOC 무조건종가)는 헤더 규칙과 정확히 일치, 킬스위치>B1 우선순위, 데이터부재 시 대피상태 유지, /ok 해시가드(승인 이후 주문표 변경 시 제출 차단), 새 거래일 시 approved/submitted 리셋 — 모두 의도대로입니다. VOLTGT의 balance 임시축소→복원도 상태 회계를 오염시키지 않습니다(단, 아래 단서).
감사 불가 항목 (원칙상 명시): mume_v4_core.py/mume_v4_state.py/mume_v4_broker.py가 없어 다음은 값으로 검증하지 못했습니다 — State 생성자 시그니처, suggest_orders가 balance를 매수에만 쓰는지(sell이 balance에 의존하면 VOLTGT balance 스케일이 매도 주문을 오염시킴), update_state 반환·이벤트 스키마, reconcile/submit_orders/loc_submit_allowed 내부, core MOC의 price 관례. 그리고 laoer_vr_compare.py 없이 A1~A3의 버블/SMA200/M0 정합은 단정하지 않습니다.
세 모듈과 백테스터의 버블 계산부(M0 시리즈·SMA200 산출 라인)를 올려주시면 A그룹 정합과 B그룹의 어댑터 의존 항목을 값 단위로 마저 검증하겠습니다. 그중 A1(M0 소스 일치)과 7번(MOC price=0.0)이 우선 손볼 후보로 보입니다.
