PASS T3a 감지→건 생성(fix_pool)
PASS T3a N=1(0.71 반올림)·허용오차 내
PASS T3a 질문 문구에 금액·답 줄
PASS T3a /예 1 → 집행(Pool 11,719.16·V 불변·주식 불변)
PASS T3a 반영 메시지에 원장 명령 표기
PASS T3a 다음 실행 변동 없음(질문 없음·건 없음)
PASS T3b 감지→lump_v, N=11
PASS T3b V' = V×(1+ΔC/총자산)
PASS T3b 예상 주수 = int(1000×w/px) = 10 (목돈 경로는 내림)
PASS T3b /예 → 목돈 예약 등록(pending_lump 1000 v)·건 종료
PASS T3b 목돈 대기 중 감지 보류
PASS T4 현금 역산: 주문가능 11,421.10 + 대기매수 4,582.80×1.001 = 16,008.48 (실측 총예수금 16,008.52와 $0.04 차)
PASS T4 N = 57(제안 57주)
PASS T4 복합 변동 → mixed(1단계: 원장 맞춤 제안 + 매수 57주 안내)
PASS T4 V_trade = 41,128×652÷514 = 52,170
PASS T4 P=78 → 56주
PASS T4 질문에 증거금 역산 표기
PASS T4-after 변동 바뀜 → 새 건 #2, fix_pos, N=0
PASS T8 옛 건번호 /예 1 거부(현재 #2)
PASS T8 번호 없는 /예 거부
PASS T4-after /예 2 → 원장 652·11,650.51·V 52,169.6(=41,128×652÷514) — 수동 /setpos 652 11651 52170 과 동치
PASS T4-after 매수한도 = Pool×50%(=/setpos 동일)·cyc_used 0
PASS T4c /아니오 → 건 종료·declined 기록
PASS T4c 다음 실행 → 예비 경로(Pool만) 새 건 #2
PASS T4c 그것도 아니오 → 보류 한 줄만·건 없음
PASS T4c 변동이 바뀌면 다시 묻는다(새 건 #3)
PASS T5 인출 → lump_v(매도), N<0, 양도세 문구, 현금부족 경고
PASS T5 /예 → 목돈 인출 예약(-3000 v)
PASS T6 처음 등록(보유 있음) 건
PASS T6 /예 → 등록: 236주·Pool 2,000·V=236×76=17,936·사이클 시작 오늘·한도 1,000
PASS T7 처음 시작(현금뿐) 안내: ⌊20,000×0.9÷76⌋=236주
PASS T7 /예 → 안내 전용(원장 무변경)
PASS T12 소액($500) 처음 시작 안내($3,000 미만 문구)
PASS T10 CASH 중 입금 → cash_pool
PASS T10 /예 → Pool 20,500·V 18,000 유지·매매 없음
PASS T13② +10,000 → lump_v: 매수 150주=$9,000·V 30,000
PASS T13③ 매도+인출 후 → fix_pos: 150주·Pool 1,000·V 10,000
PASS T13③' −1,000 → lump_v: 매도 15주=$900·V 19,000
PASS T8 재감지 불일치 → 집행 보류·approved 기록
PASS T8 다음 실행 같은 내용 → 자동 집행(Pool 11,719.16)
PASS T8 유효기간 7일 경과 → 새 건번호 #2로 계속 질문
PASS T8 답 없으면 같은 건 반복(재질문 2회차)
PASS T11 현금 차이 $4.99(<$5) → 변동 없음
PASS T11 원화 75만 원 → 환전 안내
PASS DRY 감지 미리보기·건 저장 없음
PASS T2 순서: sync_fills → _acct_detect → process_commands
PASS T1 현금 필드: cashBuyingPower + 대기 매수 증거금 역산(코드 확인)

합계: PASS 47 / FAIL 0
