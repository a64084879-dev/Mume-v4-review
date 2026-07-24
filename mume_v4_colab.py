감사 판정

4개 파일 전부 컴파일·정합·실행검증 통과. 치명 결함 0건. 원문을 컨테이너에 그대로 전사해 py_compile 4/4 통과 후, 118개 실행 케이스(사다리 계산·체결동기화·명령 처리·일일 오케스트레이션·러너 가드)를 전수 PASS로 확인했습니다. 다만 구성 조건부 결함 1건(A), 잠재 함정 1건(B), 사문 불일치 1건(C)을 새로 확인했고, A·B 모두 코드 실행으로 재현했습니다. 현행 운영 수칙(SYNC_SINCE 미사용)이 지켜지면 B는 휴면 상태입니다.

신규 발견 (실증 재현 완료)

[A] 중 · 구성 조건부 — AUTO_MODE=on + AUTO_RECOVER=off 조합에서 복귀 교착 + 허위 보고

같은 환경에서 세 가지를 동시에 실증했습니다: ① daily_run은 복귀 신호에 "수동 복귀 정책(/enter로 실행)"을 안내하고 ② 그 /enter는 러너 가드가 ⛔ 거부하며 ③ build_report의 AUTO 분기는 "러너가 이번 실행에서 이미 접수했습니다"라고 출력합니다(대피는 참이지만 복귀+AUTO_RECOVER=off에선 거짓). 결과: CASH 고착 + 오보. 월말 복귀 신호 시에만 노출되는 조합 문제라 코드 단독 결함은 아니지만, 워크플로 설정 실수 한 번으로 발화합니다. 권고: 키움 LIVE는 AUTO_RECOVER=on을 고정 수칙으로. 원하시면 러너(수정 가능 파일)에 이 조합 감지 시 시작 경고 + 복귀신호 시 교정 알림을 추가할 수 있습니다.

[B] 중 · 잠재 함정 — SYNC_SINCE 좁힘→복원 시 체결 이중반영

sync_fills의 프루닝 컷오프가 since에 결속되어 있어 수치로 재현됩니다: 정상 반영(110주) → 같은 창 재실행 불변(대조군 확인) → SYNC_SINCE=오늘로 좁힌 실행에서 최근 체결 키가 프루닝 삭제 → 기본 5영업일 창 복귀 → 같은 체결 재적용 120주(이중반영). 트리거는 "최근 5영업일 내 체결 존재 + SYNC_SINCE를 체결일 이후로 일시 좁혔다 되돌림"뿐이라, 현행 수칙대로 SYNC_SINCE를 안 쓰면 발화하지 않습니다. 권고: SYNC_SINCE는 '과거로 넓히기' 전용, 좁히기 금지 명문화. 근본 해결(프루닝 컷오프에 rolling_since(5) 하한)은 프레임워크 수정이라 승인 필요하며, 러너 단독으로도 "SYNC_SINCE가 5영업일보다 미래면 무시+경고" 가드를 넣을 수 있습니다.

[C] 하 · 사문 — 키움 _reserve 주석("미국=000030") vs 코드(US_STEX="ND") 불일치. uses_reservation=False라 실행 무영향. 예약 경로 부활 시에만 재검.

소소 3건: _count_buy가 pool 잔액 미갱신(보수 방향이라 무해 — 스윕 54조합 절단 0건으로 확인) · DRY 리포트의 "걸었습니다" 문구 과장(배너로 식별 가능) · 야간재시도 _TRANSIENT에 "500" 미포함(일시 500도 즉시 크래시 — 인증 fail-fast 관점에선 타당, 현행 유지 권고).

실행 검증 내역 (118/118 PASS)

compute_ladder(12): nearest 포함/제외/2칸 경계, 센티널 −1·−2, lot 분리 실증(1301주 → 매도 lot 6·매수 lot 2), 절단없음 스윕(계좌 10~12만주 × Pool/V 0.01~1.99 = 54조합 0건), sell_reach 상한, 매도 체인 정합.

sync_fills(15): 멱등·부분체결 델타·구키 하위호환·side 분리 키·CASH 확정 시 판정일 스탬프(신선 3일=사용/묵은 9일=오늘)·복귀 확정 시 retry/budget/래치 전소거·pending 만료해제(전일자·불리언 해제, 당일자 유지)·프루닝, 그리고 위 발견 B 재현 3케이스.

daily_run(22): cancel-first→잔존0 확인→배치(매수 2주씩 2칸·매도 6주씩 1칸, 태그·가격·qty 전건 일치), cancel_all의 건별 qty 전달 확인, 센티널·빈사다리 시 기존주문 보존, 취소실패/잔존/리컨실 불일치 시 배치 중단, 대피(사다리 취소→실보유 150주 매도 @0.90×→pending→sync로 CASH 확정), 보유조회·매도접수 실패 시 "성공한 척 금지"(INVESTED 유지), 복귀 접수(min(Veff,pool)÷주문가, 당일 pending 중복가드, retry 신호무관 재시도, recon 게이트), evac_pending 익일 완결, DRY 원장 무접촉.

봇 명령(21): /buy CASH 거부·정상 cyc_used 가산, /exit 멱등+판정일 스탬프, /deposit 음수 거부, /setpos 과거일 14일 위상 정규화(직후 롤오버 k=0 확인)+플래그 전소거, /lumpsum pool 즉시확정·기존 v예약 대체 고지·인출 클램프·과인출 거부, v 총자산 이상 거부, /lumpsum_done 부호 불일치·CASH 매매 거부·pool 레거시·V 공식 일치, exactly-once(offset 원자저장·재수신 전량 스킵·낡은 명령 폐기·echo 저장/재렌더/소거), 롤오버 k=2 산식·CASH 동결.

러너(38): 스키마 가드(stk_cd 통과·낡은 필드명 차단·미등록 TR 무검사), cap 차단/통과 경계 + killswitch·recover·lumpsum 면제, 지정가 괴리 매트릭스 4방향(매수 하한 면제·매도 상한 면제·반대방향 차단·killswitch 양방향 유지), get_fills 다행 병합(수량 합·가중평균가·수수료 합·순서 보존·감지 알림), _oid_of 신/구키 역파싱, 목돈 2단계(선입금→체결대기 중복 없음→V 재설정·래치 해제→DAY 만료 재접수→CASH 무주문 확정), Notifier 긴급/버퍼 라우팅, AUTO 가드(/enter·/buy·/deposit·/exit@ 차단, /lumpsum·/status 허용).

파일 간 정합 — 통과 확인

compute_ladder 4-튜플 계약이 전 호출부(봇 /ladder·compute_signal·러너 콜백·daily_run) 일치, 센티널이 러너 거부철학 미러까지 전파. dedup 키(날짜:ID:side) ↔ 러너 _oid_of ↔ verify_placed 0패딩 norm 삼자 정합. evac_sig_date 3경로(봇 /exit·sync CASH확정·killswitch R4) 모두 판정일 우선+7일 신선도+소비 규칙 동일. cap/괴리 면제는 봇 상류 센티널과 상보적(방어 공백 없음). day_only에서 러너 실행순서 = 봇 main 순서(sync→명령→롤오버→신호), 이중 sync는 멱등이라 무해. exactly-once의 tg_offset·pending_echo를 러너가 render_echo_head/clear_echo로 완전 미러. 23:40 KST 크론에서 DAY 주문은 당일 16:00 ET 만료라 목돈-사다리 공존 위험 사실상 없음(단, 사다리 실효 커버리지는 10:40~16:00 ET — 기지 트레이드오프).

잔존 [실측] 항목(코드에 이미 표기된 G1 계열): ust21150 다행 응답의 증분/누적 형태, 실전 수수료율, us_unfilled/us_filled 스키마 실측(현재 0행), 인증계열 return_code 후보.

운영 수칙 재확인: ① 키움 LIVE = AUTO_RECOVER=on 고정 ② SYNC_SINCE 미사용(특히 좁히기 금지) ③ 봇 단독 워크플로와 러너 이중 가동 금지. A·B의 러너측 가드 추가를 원하시면 승인 주시면 러너 파일만 수정해 반영하겠습니다.
