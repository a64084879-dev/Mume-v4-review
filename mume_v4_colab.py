# -*- coding: utf-8 -*-
"""
vr_auto_runner_toss.py — vr_signal_bot <-> vr_toss_adapter 글루 [토스 전용]  rev.6
════════════════════════════════════════════════════════════════════════
★ rev.6 (2026-09-29, ACCT-1 · 사양서 v0.5 "계좌 변동 감지·확인형 반영" 1단계) — 승인 전 초안.
  · 정규 실행(22:30 KST)에서 체결 동기화 직후 실계좌(보유주수·현금)와 원장(shares·Pool)을 대조해
    차이를 '건(#번호)'으로 만들어 리포트에서 묻고, 은박사님이 <code>/예 N</code>으로 답하면 다음 정규
    실행이 재감지 후 반영한다. 반영은 전부 봇 명령(/setpos·/lumpsum)을 그대로 호출해 수행 —
    러너에 새 원장 산식을 두지 않는다(= 손으로 치던 명령을 봇이 대신 침).
  · 1단계 범위: 매매 없는 처리(원장 맞춤·Pool만·처음 등록) + 현금만 변동·|N|≥2는 기존 목돈
    경로(/lumpsum v 자동집행) 재사용(ACCT_LUMP_V). 주식+현금 복합 변동의 비례 매매(신규 주문
    코드)는 2단계 — 1단계에서는 원장 맞춤만 제안하고 필요한 매매 주수를 안내한다.
  · 현금 필드: 토스 buying-power 응답엔 총예수금이 없어(cashBuyingPower뿐) C_a = 주문가능금액
    + Σ(대기 매수주문 잔량×지정가×(1+수수료율))로 역산. 종전 '미체결 있으면 감지 건너뜀'(K-E)
    제약이 사라지고, 종전 '미신고 입출금 감지'(CASH_GAP_ALERT) 블록은 이 감지로 대체(환경변수
    CASH_GAP_ALERT는 더 이상 읽지 않음).
  · 답 형식 /예 N·/아니오 N(건번호 필수): 봇 process_commands가 "/"로 시작하지 않는 메시지를
    건너뛰므로(봇 불가침) 명령형으로 받는다. 건번호 필수 = "본 건과 다른 건은 절대 집행 안 함".
  · 불일치 안내 정합: 건이 열려 있을 때 probe·reconcile의 🚨 /setpos 처방 문구를 "건 #N에 답하세요"로
    치환(reconcile은 프레임워크 불가침 → auto._notify 래핑으로 문구만 치환, 판정·중단 동작 무수정).
  · 봇·어댑터·프레임워크 무수정. 환경변수: ACCT_CHANGE_MIN / ACCT_FIX_MAX_N / ACCT_CASE_DAYS /
    ACCT_FEE / ACCT_KRW_MIN / ACCT_LUMP_V (아래 표).

★ rev.5 (2026-07-26, 은박사 승인): 문서만 갱신 — 코드 로직 무변경.
  · [T1] 요지를 어댑터 rev.4 정정과 정합화(사각 2종: 앱 수동매매 + 응답 유실 접수).
  · 호출량 표기 교정(아래 rev.4 ※ 항목에 인라인) — 166콜은 코드 구조상 산정(정확),
    '약 3분'은 페이싱 하한 추정. 지연 포함 3~6분 가능, 실제 소요는 G1 실측으로 확정.
  · 어댑터 확인필요 (e)(f) 신설 반영 — 상세는 vr_toss_adapter.py rev.5 헤더.
    (f)=취소 비동기(PENDING_CANCEL): 장중 재실행 시 rotate '취소 후 잔존' 오탐 가능,
    안전측 실패(배치 스킵+알림·다음 실행 자가치유). 프레임워크 불가침이라 코드 조치 없음.

★ rev.4 (2026-07-25, 은박사 승인):
  [G1-b] _EXPECT["order_one"]에서 "execution" 제거. journal 모드가 PENDING 주문도
         매 실행 조회하므로, 부재 시 첫날부터 매 실행 전면중단(DOA)이었다.
         무음 0체결 방어는 어댑터 [A5]가 종결 응답에서 받는다(검사 지점만 축소).
  [하4]  _TRANSIENT 에 "[429]" 추가 — 지속 유량초과가 야간 5분 재시도를 못 타고
         즉시 크래시하던 분류 오류 교정. 대괄호 포함 매칭(오분류 방지).
  [중2]  목돈 접수실패 안내문 교정 — 응답 유실 체결은 저널 미등재라 원장에 반영되지
         않는다는 점(구조적 사각)과 복구 경로를 명시. 종전 "다음 실행 자동 판정"은
         플래그만 정리되고 원장은 틀린 채로 남는 절반의 참이었다.
  ※ 호출량 산정(코드 구조 기준·rev.5 표기 교정): 정상 크론 실행당 order_one 166콜
     (전일 사다리 83 + 당일 접수 83 — verify_placed 가 사다리 배치 뒤에 돌며 당일
     PENDING 분을 전량 재조회하기 때문). 콜 수는 구조상 정확하나 소요 '약 3분'은
     1.1s 페이싱 하한 추정 — 네트워크 지연 포함 시 3~6분 가능. [T1] 구조 비용이며
     실제 소요·429 발생은 G1 실측으로 확정(재시도 예산 17분 내 여유 확인 포함).

★ rev.3 (2026-07-25, 은박사 승인): [R7] probe 불일치 경보 2분기 —
  미종결 잔존 = '체결 반영 대기'(개입 금지·자동 해소 안내) / 미종결 0건 = 실제 괴리(수동 확인).
  어댑터 rev.3 [A4](종결 주문만 원장 반영)의 일시 괴리를 오염으로 오인해 /setpos·/lumpsum
  개입 → 이중계상되는 사고 문구를 차단. 상세는 probe 내 주석.
  + [G1-a] _EXPECT["orders"]에서 미사용 필드 "status" 제거(오탐 전면중단 경로 차단).
  + probe get_fills 주석을 토스 실제 동작(저널 상세조회)으로 교체 — 키움 [K1] 잔재 제거.

★ 불가침 (한 글자도 수정하지 않는다)
    vr_signal_bot.py · vr_broker_adapter.py · vr_toss_adapter.py
  이 파일만 고친다. 어댑터 보강은 전부 '상속·래핑'으로 한다.

★ KIS 실측(2026-07-12~13)에서 얻은 경화를 전부 이식했다
  [N1] 키 공백 → strip (앱키 앞 스페이스 1칸이 반나절을 날렸다)
  [N2] 레이트리밋 → _PacedSession이 최소 호출간격 강제 + HTTP 429 백오프
       토스: 레이트리밋 그룹별 상이 [확인필요]. 429 시 Retry-After 존중.
  [N3] 토큰 무효 → 1회 재인증(쿨다운 존중). 토큰 파일 캐시 공유로 재발급 최소화.
  [G1] 스키마 가드 — 어댑터가 .get() 하는 필드를 '전부' 검사. 조용한 0/[] 금지.
  [G2] AUTO_MODE — 체결보고 명령 거부 (sync_fills와 이중반영 방지)
  [G4] 조회 프로브 — DRY에서도 항상.
  [F3] verify_placed — 접수한 주문이 조회에 실제로 보이는가
  [Q1] 프로브를 '명령 처리 뒤'에 (허위 불일치 경보 방지)

★ 토스 고유 주의 (2026-07-25 공식 openapi-docs 열람)
  [T1] 체결조회: GET /orders?status=CLOSED 가 현재 400 closed-not-supported.
       → FILLS_MODE=journal(기본): 접수분을 주문저널에 적재 후 미종결분만 상세 조회.
       ⚠️ journal 모드 사각 2종(어댑터 rev.4 정정과 동일 — rev.5에서 요지 정합화):
         (1) 앱 수동매매 — 저널에 애초 없음.
         (2) 응답 유실 접수(timeout-after-accept) — orderId 를 못 받아 저널 미등재.
       두 경우 모두 probe 의 보유수량 괴리검출('미종결 0건' 분기)이 안전망 — 복구는 /setpos.
       토스가 CLOSED를 열면 FILLS_MODE=closed 로 전환(그 경로는 키움 날짜스캔과 동형).
  [T1b] 수수료: execution.commission + tax 실값 제공 → 키움식 FEE_RATE 추정 불요(폴백으로만 잔존).
  [T2] 예약주문 API 없음(일반주문+조건주문뿐). uses_reservation=False 경로로만 운용.
       예약 계열 7종은 어댑터가 TossError 로 차단 — 무음 대체 금지.
  [T3] 모의서버 없음. 실계좌 소액 검증만 가능 → L1 이중잠금이 키움보다 중요.
  [K5·유지] 미체결 판정 = quantity − execution.filledQuantity > 0 (토스에 잔량 필드 없어 산출).

★★ 실계좌 안전장치 ★★
  [L1] 토스는 모의서버 없음 → 실주문은 DRY_RUN=off AND LIVE_ARM=on 이중잠금 [T3]
  [L2] 동적 주수 상한 max(CAP_FLOOR, ⌈보유수×CAP_RATIO⌉) — 넘으면 중단. 금액상한 불요(주수 막으면 자동).
  [L3] 배선 순서: 실전 DRY 프로브 → 1주 실측 → LIVE_ARM  (모의 단계 없음 [T3])

━━ 환경변수 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TOSS_CLIENT_ID / TOSS_CLIENT_SECRET      (필수)
  TOSS_ACCOUNT                             (권장. accountSeq — X-Tossinvest-Account 헤더 필수.
                                            미지정 시 GET /api/v1/accounts 자동조회, 다계좌면 중단)
  FILLS_MODE=journal  journal=주문저널 우회(기본) / closed=토스 CLOSED 개방 시 전환 [T1]
  ※ KIWOOM_MOCK 대응 변수 없음 — 토스 모의서버 부재 [T3]
  ※ KIWOOM_EXCD 대응 변수 없음 — 토스는 거래소구분 필드 없음
  DRY_RUN=on        주문 안 냄(프로브만)
  LIVE_ARM=off      ★실전(MOCK=off)에서 실주문하려면 on 필요
  AUTO_MODE=off     on이면 체결보고 명령 거부(실주문 시 필수)
  AUTO_RECOVER=off
  KS_ONLY=off       ★KS-OPEN(2026-07-28): on이면 아침 킬스위치 전용(대피·복귀만. 사다리·명령·프로브·리포트·ping 스킵)
  LADDER_ONLY=off   ★LADDER-ONLY(2026-07-31): on이면 데이마켓 사다리 전용(대피·복귀 절대 미집행 — 신호 있으면 위임)
  CAP_RATIO=0.05 / CAP_FLOOR=50   동적 주수 상한(보유×0.05, min 50주). 정상 lot의 1.34배.
  SYNC_SINCE=       YYYY-MM-DD (journal 모드는 저널 미종결분만 조회 — 창 축소 이득이 키움보다 작다)
  SYMBOL=TQQQ
  ★ACCT-1(rev.6) 계좌 변동 감지·확인형 반영 (사양서 v0.5 §8 파라미터 표)
  ACCT_CHANGE_MIN=5     잔돈 문턱(USD). 주수 차이 0 이고 현금 차이가 이 미만이면 변동 없음으로 본다.
  ACCT_FIX_MAX_N=1      허용 오차(주). 통일 규칙 N의 |N|≤이 값이면 매매 없이 원장 맞춤.
  ACCT_CASE_DAYS=7      질문 유효기간(일). 지나면 같은 내용을 새 건번호로 다시 묻는다.
  ACCT_FEE=0.001        수수료율(N 계산·대기주문 증거금 역산). 토스 미국주식 0.1%(2026-09-29 실측 $4.35/$4,353.66).
  ACCT_KRW_MIN=500000   원화 예수금이 이 이상이면 환전 안내 한 줄.
  ACCT_LUMP_V=on        현금만 변동·|N|≥2 → 기존 목돈 경로(/lumpsum ±금액 v, 장중 자동집행) 제안. off면 Pool만 맞춤 제안.
  + TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / FRED_API_KEY / HEALTHCHECK_URL
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, time, traceback, math

import vr_signal_bot as bot
from vr_broker_adapter import LadderAutomator, daily_run, rolling_since, Fill, OrderReq
from vr_toss_adapter import TossAdapter, TossError

ON = bot.ON
DRY_RUN      = ON(os.environ.get("DRY_RUN", "on"))
LIVE_ARM     = ON(os.environ.get("LIVE_ARM", "off"))
AUTO_MODE    = ON(os.environ.get("AUTO_MODE", "off"))
AUTO_RECOVER = ON(os.environ.get("AUTO_RECOVER", "off"))
KS_ONLY      = ON(os.environ.get("KS_ONLY", "off"))   # ★KS-OPEN(2026-07-28 은박사 승인): 아침 킬스위치 전용 실행
LADDER_ONLY  = ON(os.environ.get("LADDER_ONLY", "off"))   # ★LADDER-ONLY(2026-07-31 은박사 승인): 데이마켓 사다리 전용 실행
# KIWOOM_MOCK 대응 없음 [T3] — 토스 모의서버 부재. L1은 DRY_RUN/LIVE_ARM 2축으로만 판정.
FILLS_MODE   = os.environ.get("FILLS_MODE", "journal").strip().lower()   # [T1]
SYNC_SINCE   = os.environ.get("SYNC_SINCE", "").strip()
# ★ACCT-1(rev.6, 2026-09-29): 종전 '미신고 입출금 감지'(CASH_GAP_ALERT, 알림만)를 계좌 변동 감지·확인형
#   반영으로 대체. 파라미터는 사양서 v0.5 §8 표. CASH_GAP_ALERT 환경변수는 더 이상 읽지 않는다.
ACCT_CHANGE_MIN = float(os.environ.get("ACCT_CHANGE_MIN", "5"))     # 잔돈 문턱(USD)
ACCT_FIX_MAX_N  = int(os.environ.get("ACCT_FIX_MAX_N", "1"))        # 허용 오차(주)
ACCT_CASE_DAYS  = int(os.environ.get("ACCT_CASE_DAYS", "7"))        # 질문 유효기간(일)
ACCT_FEE        = float(os.environ.get("ACCT_FEE", "0.001"))        # 수수료율(추정) — 토스 미국주식 0.1%
ACCT_KRW_MIN    = float(os.environ.get("ACCT_KRW_MIN", "500000"))   # 원화 환전 안내 문턱(KRW)
ACCT_LUMP_V     = ON(os.environ.get("ACCT_LUMP_V", "on"))           # 현금만 변동·|N|≥2 → 기존 목돈 경로 재사용
ACCT_SMALL_USD  = 3000.0                                            # 처음 시작 소액 안내(총액 미만이면 안내)
ACCT_RECO_USD   = 5000.0                                            # 처음 시작 권장 총액(안내 문구용)
_ACCT_YES = ("/예", "/네", "/응", "/yes", "/y")
_ACCT_NO  = ("/아니오", "/아니요", "/no", "/n")
_CTX = {}   # run()이 채운다: 이번 실행의 감지 스냅샷("detect") — 답 처리기가 '본 건 = 이번 감지' 확인에 사용
SYMBOL       = os.environ.get("SYMBOL", "TQQQ")
# EXCD 대응 없음 — 토스 주문·조회 바디에 거래소구분 필드가 존재하지 않음.

# [L2] 동적 주수 상한: max(CAP_FLOOR, ceil(보유수×CAP_RATIO)).
#   CAP_RATIO=0.05 = 정상 lot(보유수×0.0374, 봇 budget>V 방어로 보장되는 절대상한)의 1.34배.
#   여유 1.34배 근거 = ceil 올림 + est 근사오차 + budget=V 경계안전.
#   (전수검증: pool/V 0.01~2.0 × 계좌 10주~10만주 2587건 오탐 0, 최소여유 12주. 봇우회 오주문 정상×1.5부터 차단.)
#   계좌 성장에 자동 대응(보유수 연동) → 상한 수동조정 불요. 금액 상한은 불요(금액=주수×주가, 주수 막으면 자동 제한).
CAP_RATIO = float(os.environ.get("CAP_RATIO", "0.05"))
CAP_FLOOR = int(os.environ.get("CAP_FLOOR", "50"))

TG_LIMIT = 3800
# ★R4 교정(2026-07-23): /deposit 추가. /deposit_done이 차단인데 러너에 deposit 자동집행이 없어
#   예약이 영구 잔존 → 매일 "확정하세요" ↔ "⛔ 거부" 모순 루프. /lumpsum v가 같은 공식(P/V 고정)으로
#   기능을 완전 대체하고 자동 집행되므로 입구에서 막고 안내한다.
BLOCKED_IN_AUTO = {"/buy", "/sell", "/exit", "/enter", "/deposit", "/deposit_done", "/lumpsum_done"}


# ══ 알림 ═══════════════════════════════════════════════════════════
class Notifier:
    URGENT = ("🚨", "🔴", "⚠", "⛔")
    def __init__(self, sink):
        self.sink = sink; self.buf = []
    def __call__(self, m):
        if any(u in m.lstrip()[:3] for u in self.URGENT):
            self.sink(m)
        else:
            self.buf.append(m)
    def flush(self):
        if not self.buf: return
        chunk = []
        for m in self.buf:
            if sum(len(x) + 1 for x in chunk) + len(m) > TG_LIMIT and chunk:
                self.sink("\n".join(chunk)); chunk = []
            chunk.append(m)
        if chunk: self.sink("\n".join(chunk))
        self.buf = []


# ══ [N2][N3] 네트워크 경화 세션 래퍼 ═══════════════════════════════
class _PacedSession:
    """어댑터의 requests.Session을 감싸 (a)최소 호출간격 (b)429 백오프
       (c)토큰 무효 1회 재인증. 토스 레이트리밋: 그룹별 상이 [확인필요] — 키움과 동일한 1.1s 보수값 유지."""
    # AUTH_RC 삭제 — 토스는 return_code 체계가 없고 HTTP 401/403 으로만 인증오류를 알린다.
    #   ★재인증은 토스에서 더 중요하다: client당 유효 토큰 1개, 재발급 시 기존 토큰 즉시 무효화.

    def __init__(self, real, owner, min_gap=1.1):
        self._real, self._owner, self._gap = real, owner, min_gap
        self._last = 0.0

    def _pace(self):
        wait = self._gap - (time.time() - self._last)
        if wait > 0: time.sleep(wait)
        self._last = time.time()

    def post(self, url, **kw):
        r = None
        for attempt in range(4):
            self._pace()
            r = self._real.post(url, **kw)
            if r.status_code == 429:                       # 유량초과 → 적응형 백오프
                self._gap = min(self._gap * 1.5, 3.0)
                print(f"[레이트리밋] 간격 {self._gap:.1f}s 상향 후 재시도")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (401, 403) and attempt == 0 and "/oauth2/" not in url:
                if self._owner._reauth():
                    h = dict(kw.get("headers") or {})
                    h["authorization"] = f"Bearer {self._owner._token}"
                    kw["headers"] = h
                    continue
            return r
        return r

    def get(self, url, **kw):
        # ★E33 [P1] 승인(2026-07-25): 401/403 → _reauth 1회 → 재시도. POST 분기를 그대로 옮김.
        #   근거: 이 클래스 독스트링이 "(c)토큰 무효 1회 재인증"을 자기 속성으로 선언한다.
        #   키움은 전 호출이 POST라 GET에 없어도 그 속성이 성립했으나, 토스는 조회가 전부 GET이라
        #   (잔고·예수금·현재가·미체결·주문상세) 선언된 속성이 호출 대부분에서 깨져 있었다.
        #   토스는 client당 유효 토큰 1개 — 외부에서 재발급되면 크론이 든 토큰이 즉시 죽는다.
        #   ⚠️ 429는 넣지 않는다: 어댑터 _req가 Retry-After 존중으로 이미 처리(이중처리 방지).
        #   ✅ GET은 멱등이라 재시도에 이중주문 위험이 구조적으로 없다. _reauth는 65초 쿨다운 보유.
        for attempt in range(2):
            self._pace()
            r = self._real.get(url, **kw)
            if r.status_code in (401, 403) and attempt == 0 and "/oauth2/" not in url:
                if self._owner._reauth():
                    h = dict(kw.get("headers") or {})
                    h["authorization"] = f"Bearer {self._owner._token}"
                    kw["headers"] = h
                    continue
            return r
        return r


# ══ [G1] 스키마 가드 ═══════════════════════════════════════════════
class GuardedToss(TossAdapter):
    """어댑터 무수정 — 상속만. 필드 계약 검증 + 실계좌 주문 상한."""

    # 어댑터가 실제로 .get() 하는 필드를 전부 검사.
    # ★키움에서 얻은 교훈 그대로 적용(2026-07-23 사고): 가드가 어댑터보다 낡으면 정상 응답을
    #   불일치로 판정해 전면 중단시킨다. 반드시 '어댑터가 실제로 .get() 하는 이름'에 맞춰둘 것.
    #   ⚠️ 아래 필드명은 2026-07-25 공식 openapi-docs 기준이며 아직 실계좌 미실측이다.
    #   행이 생겨 다르면 가드가 걸러낸다(설계대로) — 조용한 0/[] 보다 큰소리 중단이 옳다.
    _EXPECT = {
        "holdings":  ["symbol", "quantity"],                      # + averagePurchasePrice
        # ★(2026-07-25 승인) "status" 제거 — list_open_orders·_mk_fill 어디서도 이 EP의 status를
        #   읽지 않는다(실측). 읽지 않는 필드를 요구하면 토스가 목록에서 생략할 때 정상 응답이
        #   오탐 전면중단을 부른다(7-23 키움 사고 동형). journal 모드의 결정적 status 판독은
        #   order_one EP이며 아래 항목에 그대로 남아 방어 공백 없음.
        #   side/execution은 추가하지 않는다 — side는 키움 원형이 의도적으로 관용(취소는 주문번호 기반),
        #   execution은 미체결 행에서 정당하게 부재 가능해 넣으면 그 자체가 오탐원이 된다.
        "orders":    ["orderId", "symbol", "quantity"],           # GET 목록(OPEN / 개방 시 CLOSED)
        # ★[G1-b](2026-07-25 승인) "execution" 제거 — journal 모드는 미종결(PENDING) 주문도
        #   매 실행 order_one 으로 조회한다([A4] 이후에도 상태 확인 자체는 계속한다).
        #   "미체결 행에서 execution 은 정당하게 부재 가능"이라는 논리는 바로 위 orders 항목에서
        #   이미 채택한 것인데 여기만 미적용이라 자기모순이었다 — 부재 시 sync_fills 예외로
        #   첫날부터 매 실행 전면중단(DOA)이 된다. 무음 0체결 방어는 어댑터 [A5]가
        #   '종결 주문에 execution 키가 통째로 없으면 raise'로 받으므로 총량은 보전된다.
        "order_one": ["orderId", "status"],                       # [T1] 체결 확정 경로(FILLS_MODE=journal)
        "prices":    ["symbol", "lastPrice"],
        "buypower":  ["cashBuyingPower"],
        "accounts":  ["accountSeq"],
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._placed = []
        self._sess = _PacedSession(self._sess, self, 1.1)
        self._last_auth = 0.0
        self._multifill_alerted = False   # [치명3] 다행 감지 알림 — 실행당 1회(get_fills가 실행당 3~4회 호출됨)
        self._cap_shares = None           # [L2] 동적 상한용 보유수 캐시(실행당 1회 조회, 사다리 여러 칸 재조회 방지)
        self._px_cache   = None           # ★W6: 현재가 캐시(괴리검사용, 실행당 1회 — 칸마다 조회 방지)
        self._ladder_rsv_n = 0            # [치명A] 이번 실행 실제 예약 배치 건수 → 래치를 '실배치'에 결속(배치0건이면 래치 안 함)

    def _reauth(self):
        if time.time() - self._last_auth < 65:
            print("[재인증 보류] 쿨다운 — 원래 오류를 그대로 올린다")
            return False
        self._last_auth = time.time()
        self._token = None; self._exp = 0
        try: os.remove(".toss_token_live.json")
        except Exception: pass
        try:
            self.authenticate()
            print("[재인증] 새 토큰 발급 — 재시도")
            return True
        except Exception as e:
            print(f"[재인증 실패] {e}")
            return False

    @staticmethod
    def _key_of(path):
        """EP(키→경로) 역인덱스. order_one/cancel 은 {oid} 치환분이라 정규식 대조."""
        import re
        for k, v in TossAdapter.EP.items():
            if re.fullmatch(re.escape(v).replace(r"\{oid\}", "[^/]+"), path):
                return k
        return None

    def _audit(self, method, path, d):
        # ★GET(조회)만 감사한다. POST(주문접수·취소)의 result 는 {orderId,...} 단건이라
        #   목록 스키마 기준으로 보면 전건 누락으로 오판된다 — 키움은 전부 POST라 이 구분이 없었다.
        if method != "GET": return
        key = self._key_of(path)
        need = self._EXPECT.get(key, [])
        if not need: return
        res = d.get("result") if isinstance(d, dict) else None
        if isinstance(res, list):
            rows = res
        elif isinstance(res, dict):
            # ★E32(2026-07-25 검증에서 발견): 빈 목록([])은 falsy → or 체인이 [res]로 낙착해
            #   잔고 0주(신규 계좌)에서 스키마 '오탐' 전면중단을 일으켰다. 원형 의도는
            #   "빈 목록 = 정상 통과, 필드명 불일치만 중단". 명시적 존재 검사로 교정.
            for _k in ("items", "orders", "accounts"):
                if isinstance(res.get(_k), list):
                    rows = res[_k]; break
            else:
                rows = [res]
        else:
            return
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows: return
        miss = [k for k in need if not any(k in r for r in rows)]
        if miss:
            raise TossError(
                f"🔴 스키마 불일치[{key}/{path}]: 누락 {miss}. 조용한 0/[] 반환 = "
                f"킬스위치 무음실패·이중사다리 경로 → 중단. 실제 키={list(rows[0].keys())}")

    def _req(self, method, path, payload, err, with_account=True, params=None):
        d = super()._req(method, path, payload, err, with_account=with_account, params=params)
        self._audit(method, path, d)
        return d

    # ── [L2] 동적 주수 상한 ──────────────────────────────────
    def _cap_qty(self, symbol):
        """상한 = max(CAP_FLOOR, ceil(보유수×CAP_RATIO)) = 정상 lot의 1.34배.
           보유수는 실행당 1회 조회 후 캐시. 조회 실패 시 예외 전파(무음실패 금지)."""
        if self._cap_shares is None:
            self._cap_shares = float(self.get_holdings(symbol).shares)
        return max(CAP_FLOOR, math.ceil(self._cap_shares * CAP_RATIO))

    def _cached_price(self, symbol):
        """★W6(2026-07-24): 현재가를 실행당 1회만 조회하고 캐시.
           종전엔 사다리 칸마다 get_price를 불러 60칸이면 +60콜(페이싱 1.1s → 약 1분 낭비).
           괴리 검사용 기준가는 실행 중 바뀌어도 무의미하므로 캐시가 정확도에 무해하다."""
        if getattr(self, "_px_cache", None) is None:
            self._px_cache = float(self.get_price(symbol))
        return self._px_cache

    # ── [L2] 실계좌 주문 상한 ──────────────────────────────────
    def place_order(self, req):
        qty = int(req.qty)
        # [치명2] tag 분기 — 킬스위치·복귀는 계좌 규모와 무관하게 전량 집행돼야 한다.
        #   killswitch: 매도 수량=실보유(killswitch_evacuate가 get_holdings로 산정) → 상한 예외 안전.
        #   recover   : 매수 notional≤pool(recover_enter의 min(veff,pool)) → 상한 예외 안전.
        #   그 외(ladder 등)만 동적 주수 상한 유지. 지정가 괴리 검사는 tag 무관 유지.
        #   금액 상한 불요: 금액=주수×주가라 주수를 막으면 금액도 자동 제한(주가 상승은 정상이라 안 막음).
        _tag = (getattr(req, "tag", "") or "").lower()
        # ★R1 교정(2026-07-23): lumpsum 면제 추가. 목돈 주수는 사용자가 지정한 금액에서 유도되고
        #   (qty×price ≤ |lump| 구조 보장) 예수금이 최종 방어다. 상한에 걸리면 집행 불가 →
        #   pending 잔존 → 매일 재시도·알림 루프. AUTO에선 /lumpsum_done도 차단이라 해소 경로마저 없음.
        _exempt = _tag in ("killswitch", "recover", "lumpsum")
        if not _exempt:
            cap = self._cap_qty(req.symbol)
            if qty > cap:
                raise TossError(f"⛔ 주문 상한 초과: {qty}주 > 동적상한 {cap}주(보유×{CAP_RATIO}). "
                                  f"사다리 오계산·V 오입력 의심 → 중단(계좌 보호).")
        # ★[2026-07-17] 지정가 괴리 방어 — V 오설정 대량 오주문 실증 후 추가.
        #   개별 주문 크기(qty·notional)는 상한 안 넘어도, '지정가가 현재가에서 튀면'
        #   V가 잘못된 것(예: V=200,000/1269주 → 매도 지정가 236, 현재가 71의 3배).
        #   지정가가 현재가의 2.5배↑ 또는 0.4배↓면 비정상 → 거부(계좌 보호).
        # ★W1 교정(2026-07-24): ladder_buy는 '하한'만 면제한다.
        #   심부 매수칸 지정가 = 최소밴드/s 라서 Pool/V ≳ 1.28부터 최심부가 0.4배 아래로 내려간다(실측).
        #   그 칸들은 정상 계산 결과인데 매일 거부돼 최심부가 영구 누락됐다(봇 ① 절단방지와 정면 모순).
        #   V 오설정은 compute_ladder의 start_px 기준 −1 센티널(2.5/0.4)이 상류에서 이미 차단하므로
        #   여기 하한은 중복 방어다. 상한(2.5배)·주수 cap·매도측 검사는 그대로 유지한다.
        lim = float(req.limit_price or 0)
        if lim > 0:
            try:
                mkt = self._cached_price(req.symbol)
            except Exception:
                mkt = 0.0
            if mkt > 0:
                r = lim / mkt
                # ★A(2026-07-24): 방향별 면제. 매도 상단칸 = sell_reach(1.5)×센티널허용(2.5)
                #   → 최대 3.75×현재가가 '정상값'이라 상한 2.5를 매도 사다리에 두면
                #   급락장(anchor/현재가 1.67↑ = −40%)부터 상단 매도칸이 거부되기 시작하고
                #   −54%(2.17배)에선 50칸 전량 거부된다(실측).
                #   V 오설정은 상류 compute_ladder −1 센티널이 주문 전에 차단하므로 방어 공백 없음.
                #   반대쪽 검사는 유지(무해한 이중방어). killswitch/recover/lumpsum은 ±10% 지정이라
                #   양방향 검사 그대로 적용된다.
                _low_exempt  = (_tag == "ladder_buy")    # 매수 사다리: 하한 면제(W1)
                _high_exempt = (_tag == "ladder_sell")   # 매도 사다리: 상한 면제(A)
                if (r > 2.5 and not _high_exempt) or (r < 0.4 and not _low_exempt):
                    raise TossError(
                        f"⛔ 지정가 괴리 — {req.side} {qty}주 @ {lim:.2f} vs 현재가 {mkt:.2f} "
                        f"({r:.1f}배). V 오설정 의심 → 중단(계좌 보호). "
                        f"V를 '보유×현재가'에 맞게 재설정하세요.")
        oid = super().place_order(req)
        if oid:
            self._placed.append((str(oid), req.side, qty))
        return oid

    # ── [L2+] 사다리 예약 상한 (rev.4 예약경로) ─────────────────────
    #   place_ladder_reserve도 place_order와 동일 상한: 칸 qty·notional·지정가 괴리.
    #   사다리라 tag 면제 없음(대피/복귀=sell_at_open/buy_at_open은 부모 그대로 = 면제).
    def place_ladder_reserve(self, side, symbol, qty, limit, strt_dt, end_dt):
        q = int(qty); px = float(limit or 0)
        cap = self._cap_qty(symbol)   # 동적: 정상 lot의 1.34배. 금액상한 불요(주수 막으면 자동 제한).
        if q > cap:
            raise TossError(f"⛔ 예약 상한 초과: {q}주 > 동적상한 {cap}주(보유×{CAP_RATIO}). "
                              f"사다리 오계산·V 오입력 의심 → 중단(계좌 보호).")
        if px > 0:   # 지정가 괴리(정상 사다리는 현재가의 0.6~1.6배)
            try: mkt = self._cached_price(symbol)
            except Exception: mkt = 0.0
            # ★W1+A(2026-07-24): 이 메서드는 전부 사다리 칸 — 매수=하한 면제, 매도=상한 면제.
            #   반대쪽 검사는 유지(정상값이 닿지 않는 무해한 이중방어). 근거는 place_order A와 동일.
            _sd = str(side).lower()
            if mkt > 0 and ((px > mkt*2.5 and _sd != "sell") or (px < mkt*0.4 and _sd != "buy")):
                raise TossError(f"⛔ 예약 지정가 괴리 — {side} {q}주 @ {px:.2f} vs 현재가 {mkt:.2f}. "
                                  f"V 오설정 의심 → 중단(계좌 보호).")
        oid = super().place_ladder_reserve(side, symbol, q, px, strt_dt, end_dt)
        if oid:
            self._placed.append((str(oid), side, q))
            self._ladder_rsv_n += 1   # [치명A] 실제 배치 성공 카운트(래치 트리거)
        return oid

    def get_fills(self, symbol, since):
        """[치명3 보험] 부분체결 다행 대비 — (filled_at,order_id,side)로 집계.
           어댑터 원본이 '주문당 누적 1행'이면 항등(무해). 행별(부분체결마다 별도 행) 응답이면
           같은 주문의 여러 행이 dedup 키 충돌로 소실되던 것을 방지.
           병합: 수량 합 · 가중평균 체결가 · 수수료 합. 원본 등장 순서 보존."""
        raw = super().get_fills(symbol, since)
        agg = {}; order = []
        for f in raw:
            k = (f.filled_at, f.order_id, f.side)
            if k in agg:
                a = agg[k]; tot = a.qty + f.qty
                aprice = (a.price * a.qty + f.price * f.qty) / tot if tot else f.price
                agg[k] = Fill(f.symbol, f.side, int(tot), aprice, a.fee + f.fee, f.order_id, f.filled_at)
            else:
                agg[k] = f; order.append(k)
        merged = [agg[k] for k in order]
        # [치명3 다행 감지] 병합이 실제로 일어났으면(원시 행수 > 주문 수) 알림. 실행당 1회.
        #   부분체결은 인위 재현이 어려워 자연 발생을 기다려야 형태(증분 b / 누적 c) 확정 가능.
        #   이 알림이 그 트리거 — 당일 즉시 인지(없으면 익일 reconcile 중단이 첫 징후).
        #   날짜가 바뀌면 재발 허용(5영업일 창 리마인더, 창 지나면 자연 소멸).
        if len(raw) > len(merged) and not self._multifill_alerted:
            self._multifill_alerted = True
            from collections import Counter
            cnt = Counter((f.order_id, f.side) for f in raw)
            parts = [f"{m.order_id}({m.side}) {cnt[(m.order_id, m.side)]}행→{m.qty}주"
                     for m in merged if cnt.get((m.order_id, m.side), 1) > 1]
            try:
                bot._tg("ℹ️ 부분체결 다행 감지 — 원시 " + str(len(raw)) + "행 → " + str(len(merged)) +
                        "주문 병합.\n   " + "; ".join(parts) +
                        "\n   ⚠️ 원시 행별 값이 '증분'이면 현행 합산 정확, '누적'이면 과계상. "
                        "원시 응답 형태 실측 확정 필요(다음 reconcile이 불일치 시 자동중단).")
            except Exception:
                pass
        return merged

    # ── [F3] 접수 주문 가시성 ──────────────────────────────────
    def verify_placed(self, symbol, since):
        if not self._placed: return None
        norm = lambda x: str(x or "").strip().lstrip("0")     # 0패딩 정규화
        try:
            opens = {norm(o.get("order_id")) for o in self.list_open_orders(symbol)}
            fills = {norm(f.order_id) for f in self.get_fills(symbol, since)}
        except TossError as e:
            return f"🚨 접수주문 가시성 확인 실패: {e}"
        # [중C] 예약경로: 예약번호는 개장 전이라 미체결·체결에 안 뜸 → 예약목록(rsrv_ord_no)도 대조 대상에 포함.
        rsvs = set()
        if getattr(self, "uses_reservation", False):
            try:
                rsvs = {norm(r["rsrv_ord_no"]) for r in self.list_reservations(symbol) if r.get("rsrv_ord_no")}
            except Exception:
                rsvs = set()
        ghost = [o for o, _s, _q in self._placed if norm(o) not in opens and norm(o) not in fills and norm(o) not in rsvs]
        # [중C 폴백] 접수 응답 id가 ord_no인지 rsrv_ord_no인지는 G1 실측. 개별 대조가 id 필드 불일치로 실패해도
        #   실제 예약 건수 ≥ 접수 건수면 ghost 아님(건수 대조 — 이중사다리 오경보 방지).
        if ghost and getattr(self, "uses_reservation", False) and len(rsvs) >= len(self._placed):
            ghost = []
        if ghost:
            return (f"🚨🚨 접수한 주문 {ghost} 이 미체결·체결·예약 어디에도 없음 — "
                    f"조회가 주문을 못 본다는 뜻. cancel-first 무력 → 이중 사다리 위험.")
        return None


# ══ [G2] AUTO_MODE 명령 가드 ═══════════════════════════════════════
_orig_apply = getattr(bot.apply_command, "_vr_orig", bot.apply_command)   # ★멱등: reload/이중임포트 시 패치 중첩(무한재귀) 방지
def _guarded_apply(pos, text, price_hint, Veff_target=None):
    t = (text or "").strip().split()
    cmd = t[0].lower().split("@", 1)[0] if t else ""
    # ★ACCT-1: 계좌 변동 건 답(/예 N · /아니오 N)은 봇에 넘기지 않고 러너가 처리한다(봇 불가침).
    if cmd in _ACCT_YES or cmd in _ACCT_NO:
        return _acct_answer(pos, text, price_hint)
    if AUTO_MODE and cmd in BLOCKED_IN_AUTO:
        _alt = ("\n   입출금은 <code>/lumpsum ±금액 v</code>(목돈공식·자동집행) 또는 "
                "<code>/lumpsum ±금액 pool</code>(Pool만)을 쓰세요."
                if cmd in ("/deposit", "/deposit_done", "/lumpsum_done") else "")
        return pos, (f"⛔ AUTO_MODE — <code>{cmd}</code> 거부.\n"
                     f"   체결은 증권사 API로 자동 동기화됩니다(이중반영 방지).{_alt}")
    return _orig_apply(pos, text, price_hint, Veff_target)
_guarded_apply._vr_orig = _orig_apply
bot.apply_command = _guarded_apply


# ══ [ACCT-1] 계좌 변동 감지·확인형 반영 (사양서 v0.5, 1단계 · rev.6) ═══════════════
#   흐름(정규 실행): 체결동기화 → _acct_detect(조회·분류·질문 또는 승인건 집행) → process_commands
#   (/예 N → _acct_answer → 이번 실행 감지와 같은 건일 때만 집행) → probe → 목돈 → 롤오버 → daily_run.
#   원장 변경은 전부 봇 명령 문자열(/setpos·/lumpsum)을 _orig_apply로 호출한다 — 러너 자체 산식 없음.
#   저장되는 키: pos["acct_case"](열린 건) · pos["acct_seq"](건번호 카운터) · pos["acct_declined"](아니오 한 건)
#   · pos["acct_last"](마지막 반영 기록). 봇 /setpos는 이 키들을 건드리지 않는다(다음 감지가 자연 해소).

def _acct_now():
    return bot.pd.Timestamp.now(tz="Asia/Seoul")

def _acct_snapshot(broker):
    """실계좌 스냅샷(조회만·주문 없음). C_a = 주문가능금액 + Σ대기 매수주문 잔량×지정가×(1+수수료율).
       토스 buying-power 응답엔 총예수금 필드가 없어(cashBuyingPower뿐) 대기 매수 증거금을 역산해 더한다.
       매도 대기주문은 증거금이 없어 더하지 않는다. 오차 = 수수료 예치 반올림(9/29 실측 36건 $0.2 안쪽)."""
    held  = broker.get_holdings(SYMBOL)
    opens = broker.list_open_orders(SYMBOL) or []
    cash_bp = float(broker.get_cash_usd())
    reserve = 0.0
    for o in opens:
        if str(o.get("side", "")).lower() == "buy":
            try:
                reserve += float(o.get("qty") or 0) * float(o.get("price") or 0) * (1.0 + ACCT_FEE)
            except Exception:
                pass
    px = float(broker._cached_price(SYMBOL)) if hasattr(broker, "_cached_price") else float(broker.get_price(SYMBOL))
    return {"S_a": float(held.shares), "C_a": round(cash_bp + reserve, 2), "cash_bp": round(cash_bp, 2),
            "reserve": round(reserve, 2), "n_open": len(opens), "px": px}

def _acct_krw(broker):
    """원화 예수금(주문가능) — 환전 안내용. 실패해도 감지를 막지 않는다(None)."""
    try:
        d = broker._req("GET", broker.EP["buypower"], None, "원화예수금조회", params={"currency": "KRW"})
        res = d.get("result") or {}
        return float(broker._num(res.get("cashBuyingPower"))) if "cashBuyingPower" in res else None
    except Exception:
        return None

def _acct_classify(pos, snap, price_hint):
    """감지 결과를 '건'으로 분류 — 순수 계산(API·원장 무접촉). None = 반영할 변동 없음.
       [사양 §3 통일 규칙] r = P_l÷S_l, N = (C_a − r×S_a) ÷ (r + P×(1+f)) 반올림.
         |N| ≤ 허용 오차 → 매매 없이 원장 맞춤(현금만이면 /lumpsum pool!, 주수 변동이면 /setpos, V' = V×S_a÷S_l)
         |N| ≥ 2, 현금만 변동 → 기존 목돈 경로(/lumpsum v: 비중대로 매수·매도 + V×(1+ΔC/총자산)) — 책 207쪽과 동치
         |N| ≥ 2, 주수+현금 복합 → [1단계] 원장 맞춤만 제안 + 비례 매매 주수 안내(자동 매매는 2단계)
       [사양 §4] 원장 없음 → 처음 시작(보유 있으면 /setpos 등록, 현금뿐이면 안내). [§2-6] CASH 중 → Pool만."""
    S_l = float(pos.get("shares", 0.0) or 0.0); P_l = float(pos.get("pool", 0.0) or 0.0)
    V = float(pos.get("V", 0.0) or 0.0); state = str(pos.get("state", "INVESTED"))
    S_a = float(snap["S_a"]); C_a = float(snap["C_a"]); px = float(snap.get("px") or 0.0)
    dS = S_a - S_l; dC = round(C_a - P_l, 2)
    today = _acct_now().strftime("%Y-%m-%d")
    lcs = str(pos.get("last_cycle_start") or today)
    base = {"dS": dS, "dC": dC, "S_a": S_a, "C_a": C_a, "S_l": S_l, "P_l": P_l, "V": V, "px": px,
            "state": state, "price_hint": float(price_hint or 0.0), "N": 0, "V_new": V, "cmd": None}
    if S_l == 0 and P_l == 0:                                   # (c) 원장 없음 → 처음 시작
        if S_a > 0:
            base.update(kind="first_hold", cmd=f"/setpos {S_a:g} {C_a:.2f} 0 {today} INVESTED",
                        V_new=S_a * float(price_hint or 0.0))
            return base
        if C_a >= ACCT_CHANGE_MIN:
            base.update(kind="first_cash", N=(int(C_a * 0.9 / px) if px > 0 else 0))
            return base
        return None
    if abs(dS) < 0.5 and abs(dC) < ACCT_CHANGE_MIN:            # 잔돈 문턱 이내 → 변동 없음
        return None
    if state == "CASH":                                         # (d) 대피 중 → Pool만
        base.update(kind="cash_pool", cmd=(f"/lumpsum {dC:+.2f} pool!" if abs(dC) >= ACCT_CHANGE_MIN else None))
        return base
    if S_l <= 0 or px <= 0:                                     # 비정상(INVESTED인데 0주·가격 없음) → 원장 맞춤(V 유지)
        base.update(kind="fix_pos", cmd=f"/setpos {S_a:g} {C_a:.2f} {V:.2f} {lcs} {state}")
        return base
    r = P_l / S_l
    N = int(round((C_a - r * S_a) / (r + px * (1.0 + ACCT_FEE))))
    base["N"] = N
    if abs(N) <= ACCT_FIX_MAX_N:                                # (a) 매매 없이 원장 맞춤
        if abs(dS) < 0.5:
            base.update(kind="fix_pool", cmd=f"/lumpsum {dC:+.2f} pool!")
        else:
            V_new = V * S_a / S_l
            base.update(kind="fix_pos", cmd=f"/setpos {S_a:g} {C_a:.2f} {V_new:.2f} {lcs} {state}", V_new=V_new)
        return base
    if abs(dS) < 0.5:                                           # 현금만 변동·|N|≥2
        total = S_l * float(price_hint or px) + P_l
        if ACCT_LUMP_V and total > 0:
            w = S_l * float(price_hint or px) / total
            base.update(kind="lump_v", cmd=f"/lumpsum {dC:+.2f} v", V_new=V * (1.0 + dC / total),
                        q_est=int(abs(dC) * w / px) if px > 0 else 0, w=w)
        else:
            base.update(kind="fix_pool", cmd=f"/lumpsum {dC:+.2f} pool!")
        return base
    V_new = V * S_a / S_l                                       # 복합 변동·|N|≥2 → [1단계] 원장 맞춤만
    base.update(kind="mixed", cmd=f"/setpos {S_a:g} {C_a:.2f} {V_new:.2f} {lcs} {state}", V_new=V_new,
                V_trade=V * (S_a + N) / S_l)
    return base

def _acct_same(a, b):
    """같은 변동인가(재감지 기준: 주수 차이 동일, 현금 차이 ±$1 이내)."""
    try:
        return abs(float(a["dS"]) - float(b["dS"])) < 0.5 and abs(float(a["dC"]) - float(b["dC"])) <= 1.0
    except Exception:
        return False

def _acct_message(case, cid, opened, asked, snap=None, dry=False):
    """질문 문구(사양 §5): 금액 병기·유효기간·복사용 답 줄. HTML(봇 _tg 파서)."""
    k = case["kind"]; dS = case["dS"]; dC = case["dC"]; px = case.get("px") or 0.0
    try:
        exp = (bot.pd.Timestamp(opened) + bot.pd.Timedelta(days=ACCT_CASE_DAYS)).strftime("%m-%d")
    except Exception:
        exp = "?"
    L = [("[DRY] " if dry else "") + f"🧾 <b>계좌 변동 감지 [건 #{cid}]</b>" + (f" (재질문 {asked}회차)" if asked > 1 else "")]
    if k in ("first_hold", "first_cash"):
        L.append(f"   원장이 비어 있고 실계좌에 주식 {case['S_a']:g}주 · 현금 {case['C_a']:,.2f} USD가 있습니다.")
    else:
        _ds = f"주식 {dS:+g}주" if abs(dS) >= 0.5 else "주식 변동 없음"
        _dc = f"현금 {dC:+,.2f} USD" if abs(dC) >= ACCT_CHANGE_MIN else "현금 변동 없음"
        L.append(f"   {_ds} · {_dc}  (원장 {case['S_l']:g}주·Pool {case['P_l']:,.2f} → 실계좌 {case['S_a']:g}주·현금 {case['C_a']:,.2f})")
    if snap and snap.get("reserve", 0) > 0:
        L.append(f"   (실계좌 현금 = 주문가능 {snap['cash_bp']:,.2f} + 대기 매수주문 {snap['n_open']}건 증거금 {snap['reserve']:,.2f} 역산)")
    side = "매수" if case.get("N", 0) > 0 else "매도"
    if k == "fix_pool":
        L.append(f"   처리안: 매매 없이 Pool만 맞춤 — Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} ({dC:+,.2f}) · V·주식 그대로")
    elif k == "fix_pos":
        L.append(f"   처리안: 매매 없이 원장 맞춤 — 주식 {case['S_l']:g} → {case['S_a']:g} · Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} · "
                 f"V {case['V']:,.0f} → {case['V_new']:,.0f} (주수 비례)")
    elif k == "lump_v":
        L.append(f"   처리안: 책 목돈 공식 — 현재 비중(주식 {case.get('w',0):.0%})대로 {side} 약 {case.get('q_est',0)}주 ≈ ${case.get('q_est',0)*px:,.0f} "
                 f"(집행가에 따라 주수 변동, 나머지는 Pool) · V {case['V']:,.0f} → {case['V_new']:,.0f} · 장중 지정가(±10%) 자동 집행")
        if dC < 0:
            L.append("   ※ 매도가 실현되면 해외주식 양도소득세 대상입니다(연 250만 원 기본공제 초과분 22%).")
    elif k == "mixed":
        L.append(f"   처리안 ① 예 → 매매 없이 원장 맞춤: 주식 → {case['S_a']:g} · Pool → {case['C_a']:,.2f} · V {case['V']:,.0f} → {case['V_new']:,.0f}")
        L.append(f"   ② 책 비율(Pool÷주식 유지) 복원에는 {side} 약 {abs(case['N'])}주 ≈ ${abs(case['N'])*px:,.0f} 필요 — "
                 f"1단계에서는 자동 매매가 없습니다. 앱에서 직접 {side}하시면 다음 실행이 새 건으로 감지해 원장을 맞춥니다(그때 V ≈ {case.get('V_trade',0):,.0f}).")
        if case["N"] < 0:
            L.append("   ※ 매도가 실현되면 해외주식 양도소득세 대상입니다(연 250만 원 기본공제 초과분 22%).")
    elif k == "cash_pool":
        L.append(f"   처리안: 대피(CASH) 중 — Pool {case['P_l']:,.2f} → {case['C_a']:,.2f} · V 그대로 · 매매 없음")
        if case["S_a"] > 0:
            L.append(f"   ⚠️ 대피 중인데 실계좌에 주식 {case['S_a']:g}주가 있습니다 — 앱에서 확인하세요(자동 반영 없음).")
    elif k == "first_hold":
        tot = case["S_a"] * px + case["C_a"]
        ratio = (case["C_a"] / tot) if tot > 0 else 0.0
        L.append(f"   처리안: 처음 등록(매매 없음) — 주식 {case['S_a']:g}주 · Pool {case['C_a']:,.2f} · "
                 f"V = {case['S_a']:g}×전일종가 {case['price_hint']:,.2f} = {case['V_new']:,.0f} · 사이클 시작 = 오늘 · 매수한도 = Pool×50%")
        if ratio < 0.10:
            L.append(f"   ⚠️ Pool 비중 {ratio:.0%} — 책 권장(10~20%)보다 낮아 사다리 매수 여력이 부족합니다.")
        if tot < ACCT_SMALL_USD:
            L.append(f"   ℹ️ 총액 ${tot:,.0f} — $3,000 미만이면 사다리가 1~2칸뿐입니다. ${ACCT_RECO_USD:,.0f} 이상을 권장합니다(막지는 않음).")
    elif k == "first_cash":
        n = case.get("N", 0); tot = case["C_a"]
        L.append(f"   처리안: 처음 시작(현금뿐) — 책 방식은 주식 ⌊현금×0.9÷가격⌋ = {n}주 ≈ ${n*px:,.0f} 매수, Pool ≈ {tot - n*px:,.0f}(10%).")
        L.append("   1단계에서는 자동 매수가 없습니다 — 앱에서 위 주수를 사시면 다음 실행이 '처음 등록' 건으로 묻습니다.")
        if tot < ACCT_SMALL_USD:
            L.append(f"   ℹ️ 총액 ${tot:,.0f} — $3,000 미만이면 사다리가 1~2칸뿐입니다. ${ACCT_RECO_USD:,.0f} 이상을 권장합니다(막지는 않음).")
    if k not in ("first_hold", "first_cash") and dC < -ACCT_CHANGE_MIN:
        L.append("   ⚠️ 실제 현금이 원장 Pool보다 적습니다 — 반영 전까지 사다리 매수 주문이 거절될 수 있습니다. "
                 "TQQQ가 아닌 종목을 사셨으면 <code>/아니오</code>로 답하세요.")
    if case.get("cmd"):
        L.append(f"   원장 명령(예 시 봇이 실행): <code>{case['cmd']}</code>")
        if not dry:
            L.append(f"   → 반영 <code>/예 {cid}</code>   ·   보류 <code>/아니오 {cid}</code>   (유효 {exp}까지, 답 없으면 매 리포트 반복)")
    return "\n".join(L)

def _acct_execute(pos, cur, price_hint):
    """승인된 건 집행 = 봇 명령 호출. 성공 → 건 종료·기록. 실패(봇 거부) → approved 유지, 다음 실행 재시도."""
    cmd = cur.get("cmd")
    pos2, res = _orig_apply(pos, cmd, price_hint)
    ok = bool(res) and not str(res).lstrip().startswith(("⚠️", "❓", "⛔", "🚨"))
    if ok:
        pos2.pop("acct_case", None); pos2.pop("acct_declined", None)
        pos2["acct_last"] = {"id": cur["id"], "kind": cur["kind"], "cmd": cmd, "at": _acct_now().strftime("%Y-%m-%d %H:%M")}
        return pos2, f"✅ <b>계좌 변동 건 #{cur['id']} 반영</b> — 원장 명령 <code>{cmd}</code>\n{res}"
    cur["approved"] = True; pos2["acct_case"] = cur
    return pos2, f"🚨 계좌 변동 건 #{cur['id']} 집행 실패 — 유효기간 내 다음 실행에서 재감지 후 자동 재시도합니다.\n{res}"

def _acct_answer(pos, text, price_hint):
    """/예 N · /아니오 N 처리. 건번호 필수(본 건과 다른 건 집행 금지). 집행은 '이번 실행 감지 = 그 건'일 때만."""
    t = (text or "").strip().split()
    cmd = t[0].lower().split("@", 1)[0] if t else ""
    yes = cmd in _ACCT_YES
    cur = pos.get("acct_case")
    if not cur:
        return pos, "ℹ️ 열린 계좌 변동 건이 없습니다(이미 해소됐거나 아직 감지 전)."
    try:
        n = int(t[1]) if len(t) > 1 else None
    except Exception:
        n = None
    if n is None:
        return pos, f"⚠️ 건번호를 붙여 주세요 — 현재 열린 건은 #{cur['id']}: <code>/예 {cur['id']}</code> 또는 <code>/아니오 {cur['id']}</code>"
    if n != int(cur["id"]):
        return pos, (f"⚠️ 건번호 불일치 — 보내신 #{n}, 현재 열린 건은 #{cur['id']}(내용이 바뀌어 새 번호). "
                     f"현재 건을 확인한 뒤 <code>/예 {cur['id']}</code> 또는 <code>/아니오 {cur['id']}</code>.")
    if not yes:
        pos["acct_declined"] = {k: cur.get(k) for k in ("id", "kind", "dS", "dC", "S_a", "C_a")}
        pos.pop("acct_case", None)
        _after = ("다음 실행에서 차이가 남아 있으면 매매 없이 원장만 맞추는 안을 새 건으로 제안합니다."
                  if cur.get("kind") == "lump_v" else "변동 내용이 바뀔 때까지 다시 묻지 않습니다(리포트에 보류 한 줄만).")
        return pos, f"⏸️ 계좌 변동 건 #{cur['id']} 보류(아니오). {_after}"
    if not cur.get("cmd"):
        return pos, f"ℹ️ 건 #{cur['id']}는 안내 전용(자동 반영 항목 없음)입니다."
    if DRY_RUN:
        return pos, f"[DRY] 건 #{cur['id']} 승인 접수 — DRY_RUN이라 원장을 바꾸지 않습니다(LIVE 실행에서 집행)."
    det = _CTX.get("detect") or {}
    if not det.get("case") or not _acct_same(det["case"], cur):
        cur["approved"] = True; pos["acct_case"] = cur
        return pos, (f"⏸️ 건 #{cur['id']} 승인 접수 — 이번 실행 재감지가 건 내용과 맞지 않거나 조회에 실패해 집행을 보류합니다. "
                     f"다음 실행에서 재감지 후 같은 내용이면 자동 집행합니다.")
    return _acct_execute(pos, cur, price_hint)

def _acct_detect(broker, pos, notifier, price_hint):
    """[ACCT-1] 정규 실행마다: 실계좌 조회 → 분류 → (승인건이면 집행 / 아니면 질문). DRY는 미리보기만(저장 없음)."""
    _CTX["detect"] = None
    if pos.get("pending_lump") or pos.get("lump_in_flight") or pos.get("evac_pending") \
       or pos.get("recover_pending") or pos.get("recover_retry"):
        notifier("⏸️ 계좌 변동 감지 보류 — 목돈·대피·복귀 집행이 진행 중입니다(확정 후 다음 실행에서 감지).")
        return pos
    try:
        snap = _acct_snapshot(broker)
    except Exception as e:
        notifier(f"⚠️ 계좌 변동 감지 생략(조회 실패): {e}")
        return pos
    case = _acct_classify(pos, snap, price_hint)
    _CTX["detect"] = {"snap": snap, "case": case}
    krw = _acct_krw(broker)
    if krw is not None and krw >= ACCT_KRW_MIN:
        notifier(f"💱 원화 예수금 ₩{krw:,.0f} — 달러로 환전하시면 다음 실행이 입금으로 감지합니다.")
    now = _acct_now(); today = now.strftime("%Y-%m-%d")
    if DRY_RUN:
        if case is None:
            notifier("[DRY] 계좌 변동 없음 — 실계좌와 원장 일치(잔돈 문턱 이내). ※DRY는 체결 미동기화 상태의 미리보기")
        else:
            notifier(_acct_message(case, "미리보기", today, 1, snap, dry=True) + "\n   ※DRY: 건 저장·답 처리 없음(체결 미동기화 미리보기)")
        return pos
    cur = pos.get("acct_case")
    if case is None:
        changed = False
        if cur:
            notifier(f"✅ 계좌 변동 건 #{cur['id']} 해소 — 실계좌와 원장이 일치합니다(별도 조치 없음)."); pos.pop("acct_case", None); changed = True
        if pos.get("acct_declined"):
            pos.pop("acct_declined", None); changed = True
        if changed: bot.save_position(pos)
        return pos
    if cur and _acct_same(cur, case):
        if cur.get("approved"):                                 # 승인됐으나 집행 못 한 건 → 자동 재시도
            pos, msg = _acct_execute(pos, cur, price_hint); bot.save_position(pos); notifier(msg); return pos
        try:
            expired = (now.tz_localize(None) - bot.pd.Timestamp(cur["opened"])).days >= ACCT_CASE_DAYS
        except Exception:
            expired = True
        if expired:
            cid = int(pos.get("acct_seq", 0)) + 1; pos["acct_seq"] = cid
            cur = dict(case, id=cid, opened=today, asked=1)
        else:
            cur["asked"] = int(cur.get("asked", 1)) + 1
    else:
        dec = pos.get("acct_declined")
        if dec and _acct_same(dec, case):
            if dec.get("kind") == "lump_v" and case["kind"] == "lump_v":   # 예비 경로: 매매 없이 Pool만
                case = dict(case, kind="fix_pool", cmd=f"/lumpsum {case['dC']:+.2f} pool!")
            else:
                notifier(f"⏸️ 계좌 변동 건 #{dec.get('id')} 보류 중(아니오) — 주식 {case['dS']:+g}주 · 현금 {case['dC']:+,.2f}. 변동이 바뀌면 다시 묻습니다.")
                return pos
        cid = int(pos.get("acct_seq", 0)) + 1; pos["acct_seq"] = cid
        cur = dict(case, id=cid, opened=today, asked=1)
    pos["acct_case"] = cur
    bot.save_position(pos)
    notifier(_acct_message(cur, cur["id"], cur["opened"], cur.get("asked", 1), snap))
    return pos


# ══ [G6] 목돈 자동 집행 ═══════════════════════════════════════════
def _us_market_open():
    """미국 정규장 개장 중인가(XNYS). 판정 불가하면 False — 보수적으로 집행을 미룬다."""
    try:
        import pandas_market_calendars as mcal
        now = bot.pd.Timestamp.now(tz="America/New_York")
        d = now.strftime("%Y-%m-%d")
        sch = mcal.get_calendar("XNYS").schedule(start_date=d, end_date=d)
        if sch.empty:
            return False
        return bool(sch.iloc[0]["market_open"] <= now <= sch.iloc[0]["market_close"])
    except Exception:
        return False


def apply_pending_lump(broker, pos, price, notify):
    """목돈(/lumpsum ±금액 v|pool) 자동 집행 — AUTO_MODE 전용.
       · pool 모드: Pool만 증감. 주문 없음 → 장 시간 무관.
       · v 모드   : 책 공식. Pool 증감 + V 재설정(P/V 고정, V×(1+M/총자산)) +
                   현재 비중대로 즉시 매수/매도(marketable limit). 체결은 다음 실행 sync_fills가 반영.
                   장 마감이면 집행하지 않고 대기 — 사다리 '전량취소'에 휩쓸리는 사고를 원천 차단.
       · DRY_RUN : 계산만 알리고 원장·주문 모두 손대지 않는다."""
    lump = float(pos.get("pending_lump", 0.0) or 0.0)
    mode = str(pos.get("pending_lump_mode", "") or "").lower()
    if not lump or mode not in ("v", "pool"):
        return pos
    # ★㉡(2026-07-23): 직전 목돈이 체결 대기 중이면 중첩 집행 금지.
    #   두 건이 겹치면 V가 두 번 재설정되고 사다리 게이트도 꼬인다. 확정 후 다음 실행에 처리.
    if pos.get("lump_in_flight"):
        notify(f"⏸️ 목돈 {lump:+,.0f} 대기 — 이전 목돈이 체결 대기 중입니다. 확정 후 집행합니다.")
        return pos

    ev    = float(pos.get("shares", 0.0)) * price
    pool  = float(pos.get("pool", 0.0))
    total = ev + pool
    w     = 0.0 if pos.get("state") == "CASH" else (ev / total if total > 0 else 1.0)
    act   = "추가" if lump > 0 else "인출"

    # ── Pool 보충/인출 (V 불변, 주문 없음) ──
    # ★B안(2026-07-23) 이후 pool 모드는 봇 /lumpsum 단계에서 즉시 확정된다.
    #   여기 도달하는 건 구버전 상태파일에 남은 예약뿐 → 폴백으로 안전 처리.
    if mode == "pool":
        newpool = pool + lump
        if newpool < 0:
            pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
            bot.save_position(pos)
            notify(f"⚠️ 목돈 취소 — Pool {pool:,.0f}에서 {abs(lump):,.0f} 인출 불가. "
                   f"주식까지 줄이려면 <code>/lumpsum {lump:+.0f} v</code>.")
            return pos
        if DRY_RUN:
            notify(f"[DRY] Pool {act} {abs(lump):,.0f} → {pool:,.0f}→{newpool:,.0f} (원장 미변경)")
            return pos
        pos["pool"] = newpool
        pos["cyc_budget"] = max(0.0, newpool) * bot.BUY_LIMIT; pos["cyc_used"] = 0.0
        pos.pop("ladder_placed_for", None)          # 한도 바뀜 → 사다리 재게시
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
        bot.save_position(pos)
        notify(f"💰 <b>Pool {act} {abs(lump):,.0f} 반영</b> — Pool {pool:,.0f} → {newpool:,.0f} (V 불변)")
        return pos

    # ── 목돈 공식 (V 재설정 + 비율대로 즉시 매매) ──
    if total <= 0:
        notify("⚠️ 목돈(v) 보류 — 총자산 0이라 비중 계산 불가. <code>/setpos</code>로 원장을 먼저 맞추세요.")
        return pos
    # ★R3(2026-07-23): 집행 직전 재검증. 봇 F3는 '예약 시점' 가격 기준이라, 예약↔집행 사이 급락
    #   (장 마감이면 며칠 이월 가능)이나 레거시 예약이면 관통한다. Pool 음수·V 음수 사고 차단.
    if lump < 0 and (-lump) >= total:
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None); bot.save_position(pos)
        notify(f"🚨 목돈 인출 취소 — 요청 {abs(lump):,.0f} ≥ 현재 총자산 {total:,.0f}. "
               f"예약 시점 이후 하락한 것으로 보입니다. 금액을 줄여 다시 예약하세요.")
        return pos
    # ※ 여기서 'pool+lump<0'을 막으면 안 된다(2026-07-23 회귀 교정). 러너는 비동기 회계 —
    #   Pool이 인출액 전액을 먼저 흡수하고 매도대금은 다음 실행 sync_fills로 들어온다.
    #   따라서 인출 직후 Pool이 일시 음수인 것이 정상 경로다(책 예시2: 2,000−10,000 → 매도 9,000 유입 → 1,000).
    #   총자산 초과는 위 1차 가드가 이미 차단하고, V_new≤0도 그와 수학적으로 동치라 별도 검사 불필요.
    # ★R5(2026-07-23): limit·qty를 실시간 현재가로 산출. price_hint(전일 완성 종가)로 잡으면
    #   +10% 이상 갭업 시 매수 limit이 시장 아래 → 미체결인데 pending은 소거돼 재시도가 없다.
    px_live = price
    try:
        _p = float(broker.get_price(SYMBOL))
        if _p > 0: px_live = _p
    except Exception:
        pass
    side  = "buy" if lump > 0 else "sell"
    qty   = int(abs(lump * w) / px_live) if px_live > 0 else 0     # 정수 주수(내림), 나머지는 Pool
    if side == "sell":
        qty = min(qty, int(float(pos.get("shares", 0.0))))
    V_old = float(pos.get("V", 0.0)); V_new = V_old * (1.0 + lump / total)
    limit = round(px_live * (1.10 if side == "buy" else 0.90), 2)  # marketable limit(킬스위치와 동일 방식)
    # 매도대금까지 포함한 '최종' Pool로 검사(qty 내림 잔차가 커서 음수가 되는 극단 케이스만 차단).
    if lump < 0 and (pool + lump + qty * px_live) < -1.0:
        pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None); bot.save_position(pos)
        notify(f"🚨 목돈 취소 — 매도대금 포함 최종 Pool({pool+lump+qty*px_live:,.0f})이 음수입니다. 재예약 필요.")
        return pos

    if DRY_RUN:
        notify(f"[DRY] 목돈 {lump:+,.0f}({act}) — {side} {qty}주 @{limit} · "
               f"Pool {pool:,.0f}→{pool+lump:,.0f} · V {V_old:,.0f}→{V_new:,.0f} (원장·주문 미실행)")
        return pos
    if not _us_market_open():
        notify(f"⏸️ 목돈 {lump:+,.0f} 대기 — 미국장 마감. 다음 장중 실행에 집행합니다.")
        return pos

    # ★2단계 커밋(2026-07-24): 예약 소거·원장을 '주문 전'에 확정한다.
    #   종전엔 주문 접수 → 소거·저장 순이라, 그 사이(order_sleep 포함 2~3초)에 강제종료되면
    #   pending이 남아 다음 실행이 같은 목돈을 재집행했다(이중매수·V 2회 스케일 = 자금 리스크).
    #   순서를 뒤집으면 실패측이 '유실'로 떨어진다 — 봇 exactly-once ②와 같은 방향이고,
    #   유실 케이스도 Pool·V는 이미 정합이라 사다리가 남은 현금을 정상 소화한다(자가치유).
    pos["pool"] = pool + lump
    pos["V"]    = V_new
    # ★R2+K-D 교정(2026-07-23): 여기서 ladder_placed_for/cyc_budget을 건드리지 않는다.
    #   · ladder_placed_for pop → 같은 실행에서 새 V로 사다리 재게시 → shares는 체결 전(구주수)이라
    #     매수단 전체가 현재가 위에 깔려 즉시 폭주 체결(실측). day_only 재배치라 cancel-first가
    #     목돈 주문까지 삼킨다. → 체결 확정될 때까지 사다리를 아예 보류(lump_in_flight 게이트).
    #   · budget 리셋도 체결 후로 미룬다. sync_fills가 목돈 매수를 cyc_used에 가산하므로(K-D)
    #     지금 리셋하면 예산이 목돈에 전소돼 사이클 내내 사다리 매수 불능이 된다.
    pos.pop("pending_lump", None); pos.pop("pending_lump_mode", None)
    if qty > 0:
        pos["lump_in_flight"] = "PENDING"   # 주문 접수 전 사다리 보류 — 접수 성공 시 실제 주문번호로 교체
    bot.save_position(pos)

    _oid = None
    if qty > 0:
        try:
            _oid = broker.place_order(OrderReq(SYMBOL, side, qty, limit, "DAY", "LIMIT", "lumpsum"))
            pos["lump_in_flight"] = str(_oid) if _oid else "PENDING"   # falsy oid 방어
            bot.save_position(pos)
        except Exception as e:
            # ★교정(2026-07-24): pop하지 않고 PENDING을 유지한다.
            #   timeout-after-accept(브로커는 접수했는데 응답만 유실)면 주문이 살아 체결되는데,
            #   pop하면 해소기가 못 잡아 cyc_used 리셋이 누락되고 "매매 불발" 알림이 오보가 된다.
            #   PENDING 해소기가 진짜 거부(다음 실행 '상태 불명' 정리)와 체결(_filled 확정)을 모두 처리한다.
            _rest = "남은 현금은 사다리가 소화합니다" if lump > 0 else "매도가 안 됐으므로 Pool만 줄어든 상태입니다"
            notify(f"🚨 목돈 주문 접수 실패(또는 응답 유실) — <b>Pool·V는 이미 반영</b>됐습니다: {e}\n"
                   f"   ⚠️ <code>/lumpsum</code> 재예약 금지(두 번 조정됩니다). {_rest}.\n"
                   f"   · 다음 실행이 플래그를 자동 정리합니다.\n"
                   f"   · ⚠️ 단, <b>응답만 유실되고 주문이 실제 체결된 경우</b>는 주문번호를 못 받아\n"
                   f"     저널에 없으므로 체결이 원장에 반영되지 않습니다(구조적 사각 [T1]).\n"
                   f"     → 다음 프로브가 '미종결 0건 + 보유 불일치'로 알립니다. "
                   f"그때는 <code>/setpos</code>로 실보유에 맞추세요.\n"
                   f"   · 지금 <code>/status</code>와 앱 체결내역을 대조해두시면 판단이 빠릅니다.")
            return pos

    if qty <= 0:
        # CASH v모드 등 매매 수량 0 — 순수 원장 조정. '접수' 문구가 나가면 오해를 부른다.
        notify(f"💵 <b>목돈 {lump:+,.0f} 반영({act})</b> — 매매 없음(수량 0) · "
               f"Pool {pool:,.0f}→{pos['pool']:,.0f} · V {V_old:,.0f}→{V_new:,.0f}")
        return pos
    notify(f"💵 <b>목돈 {lump:+,.0f} 집행({act})</b> — {side} {qty}주 접수 @{limit}(marketable) · "
           f"Pool {pool:,.0f}→{pos['pool']:,.0f} · V {V_old:,.0f}→{V_new:,.0f}\n"
           f"   체결 확정까지 사다리는 보류됩니다(즉시체결 방지).")
    return pos


# ══ [G4] 조회 프로브 ═══════════════════════════════════════════════
def _resolve_lump(broker, pos, notifier):
    """★LUMP-RESOLVE(2026-08-12 은박사님 승인 v2): 목돈 체결확정 해소기 — 정규 실행 750블록의
       ★R2 사후처리(구 760~807행)를 로직 무변경으로 추출(3분기·문구·판정식 전부 원문 그대로).
       원 위치와 868행 집행 직후(체결 확인 시에만)의 2곳에서 호출된다. pos 반환."""
    _oid = pos.get("lump_in_flight")
    if _oid:
        # ★R-B(2026-07-24): 앞에서 세면(=[1:2]) filled_at에 시각(콜론)이 들어갈 때 어긋나
        #   체결을 '미체결 소멸'로 오판 → 허위 알림 + /setv 되돌리기 유도(V 오염) + 예산 리셋 누락.
        #   신키 f"{filled_at}:{order_id}:{side}" → [-2], 구키 f"{filled_at}:{order_id}" → [-1].
        #   뒤에서 세면 filled_at 형식과 무관하게 안전하다.
        # ★B(2026-07-24): 0-패딩 정규화. 접수응답 ord_no와 ust21150 ord_no의 패딩이
        #   다르면 체결을 '미체결 소멸'로 오분류한다. 원장 조치는 같지만 알림이 거짓이 되고,
        #   그 문구가 되돌리기를 유도해 V 오염 위험이 있다. verify_placed와 동일 norm으로 양변 통일.
        #   "PENDING" 센티널은 lstrip("0")에 불변이고 어떤 키와도 불일치라 무해하다.
        _norm = lambda x: str(x or "").strip().lstrip("0")
        def _oid_of(k):
            _p = str(k).split(":")
            return {_norm(_p[-2]) if len(_p) >= 3 else None,
                    _norm(_p[-1]) if len(_p) >= 2 else None}
        _filled = any(_norm(_oid) in _oid_of(k) for k in (pos.get("fills_seen") or {}))
        if _filled:
            pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
            pos["cyc_used"]   = 0.0          # K-D: 목돈 체결분이 사다리 예산을 먹지 않도록 여기서 리셋
            pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
            bot.save_position(pos)
            notifier("✅ 목돈 체결 확정 — 매수한도 재설정·사다리 재개")
        else:
            try: _open = broker.list_open_orders(SYMBOL)
            except Exception: _open = [{"_unknown": True}]
            if _oid == "PENDING" and not _open:
                # ★2단계 커밋의 잔존(2026-07-24): 주문번호를 남기기 전에 죽은 경우.
                #   미체결 주문이 없으므로 (a)접수 자체가 안 됐거나 (b)이미 체결됐다.
                #   두 경우 모두 Pool은 정합(목돈 반영 완료)이므로 예산 재설정이 정답이다.
                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
                pos["cyc_used"]   = 0.0
                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
                bot.save_position(pos)
                notifier("ℹ️ 목돈 주문 상태 불명(접수 직전 중단) — Pool·V는 반영됨. "
                         "미체결 없음을 확인해 사다리를 재개합니다. <code>/status</code>로 보유 확인 권장.")
            elif not _open:                    # DAY 만료·취소로 소멸 → 매매 없이 Pool·V만 바뀐 상태
                # ★교정(2026-07-24): 종전 문구가 "재예약하거나 /setv로 되돌리세요"였는데,
                #   이 시점엔 Pool·V가 이미 커밋돼 있어 재예약하면 pool 2회 가산 + V 2회 스케일이 된다
                #   (바로 위 접수실패 분기는 정확히 그 반대로 경고하고 있었다 — 비대칭 해소).
                #   원장 상태가 PENDING 분기와 동일하므로 예산 리셋도 동일하게 한다.
                pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
                pos["cyc_used"]   = 0.0
                pos.pop("ladder_placed_for", None); pos.pop("lump_in_flight", None)
                bot.save_position(pos)
                notifier("🚨 목돈 주문 미체결 소멸 — 매매 없이 <b>Pool·V는 이미 반영</b>된 상태입니다.\n"
                         "   ⚠️ <code>/lumpsum</code> 재예약 금지(Pool 2회 가산·V 2회 조정됩니다).\n"
                         "   · 그대로 두면 남은 현금을 사다리가 소화합니다(권장).\n"
                         "   · 되돌리려면 <code>/setv @현재가</code> + <code>/lumpsum ∓금액 pool</code>.")
    return pos

def probe(broker, pos, since, notify):
    acct = "<b>실계좌</b>"   # [T3] 토스는 실계좌뿐
    L = [f"🔍 <b>조회 프로브</b> (주문 없음) — 토스 {acct}"]
    L.append(f"   현재가 ${broker.get_price(SYMBOL):,.2f}")

    held = broker.get_holdings(SYMBOL)
    bs = float(pos.get("shares", 0.0))
    ok = abs(held.shares - bs) <= 0.5
    L.append(f"   실보유 {held.shares:g}주 vs 봇 {bs:g}주  {'✅' if ok else '불일치'}")

    opens = broker.list_open_orders(SYMBOL)
    L.append(f"   미체결 {len(opens)}건")

    fills = broker.get_fills(SYMBOL, since)     # 저널 미종결분 order_one 상세조회 — 미종결 건수에 비례해 소요(날짜 루프 아님)
    L.append(f"   체결({since}~) {len(fills)}건")

    try:
        L.append(f"   예수금 ${broker.get_cash_usd():,.0f} "
                 f"(Pool ${float(pos.get('pool',0)):,.0f})")
    except Exception as e:
        L.append(f"   예수금 조회 생략: {e}")

    notify("\n".join(L))
    if not ok and pos.get("acct_case"):
        # ★ACCT-1: 건이 열려 있으면 /setpos 처방 대신 건 답변으로 유도(수동 명령과 자동 반영의 이중계상 방지).
        _cid = pos["acct_case"].get("id")
        notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주. 계좌 변동 건 #{_cid}로 처리 중 — "
               f"리포트의 <code>/예 {_cid}</code>·<code>/아니오 {_cid}</code>로 답하세요(수동 <code>/setpos</code> 불필요).")
        return ok
    if not ok:
        # ★R7(2026-07-25 승인): 불일치 경보를 2분기로. 종전 단일 문구("수동 확인 필요")는
        #   '체결 반영 대기' 상황(어댑터 [A4]: 종결 주문만 원장 반영 → 장중 재실행 시 일시 괴리)에서
        #   /setpos·/lumpsum 개입을 유도해 다음 실행 자동반영과 이중계상되는 사고 문구였다.
        #   무인 시스템의 알림은 그 자체로 행동 지침이어야 한다 — 분기 기준(미종결 잔존)은
        #   위에서 이미 조회한 opens 재사용(추가 API 콜 0). 미종결 잔존 중 앱 수동매매가 겹친
        #   극단 케이스도 종결 후 다음 실행에서 '미종결 0건' 분기가 잡는다 — 오판 영구화 없음.
        if opens:   # 미종결 주문 잔존 = 체결 반영 대기 중일 가능성
            notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주.\n"
                   f"   미종결 주문 {len(opens)}건 잔존 → <b>체결 반영 대기</b>일 가능성이 높습니다.\n"
                   f"   ⛔ <code>/setpos</code>·<code>/lumpsum</code> 금지(다음 실행 자동반영 시 이중계상).\n"
                   f"   → 주문 종결 후 다음 실행에서 자동 해소됩니다. 그때도 불일치면 그때 수동 확인.")
        else:       # 미종결 없음 = 진짜 불일치(앱 수동매매 등 [T1])
            notify(f"🚨 포지션 불일치 — 봇 {bs:g}주 vs 실보유 {held.shares:g}주. "
                   f"미종결 주문 없음 → 앱 수동매매 등 실제 괴리 의심. reconcile이 사다리를 "
                   f"중단시킵니다. 수동 확인 필요(앱 매매였다면 <code>/setpos</code>로 정정).")
    return ok


# ══ 러너 ═══════════════════════════════════════════════════════════
def make_broker():
    # [N1] 공백/개행 방어
    ak = os.environ.get("TOSS_CLIENT_ID", "").strip()
    sk = os.environ.get("TOSS_CLIENT_SECRET", "").strip()
    acc = os.environ.get("TOSS_ACCOUNT", "").strip()
    if not (ak and sk):
        raise SystemExit("환경변수 필요: TOSS_CLIENT_ID / TOSS_CLIENT_SECRET")
    b = GuardedToss(ak, sk, acc)          # [T3] mock 인자 없음(전달 시 어댑터가 차단)
    b.FILLS_MODE = FILLS_MODE             # [T1] 저널 격리 스위치 주입
    return b


def run():
    # [L1] 실전(MOCK=off)에서 실주문하려면 LIVE_ARM 필요
    if (not DRY_RUN) and (not LIVE_ARM):     # [T3] 모의 축 없음 → 2축 이중잠금
        msg = ("⛔ 기동 거부 — 토스 <b>실계좌</b>에 실주문을 내려 합니다.\n"
               "   LIVE_ARM=on 을 함께 켜야 합니다(이중 잠금).\n"
               "   토스는 모의서버가 없습니다 — DRY_RUN=on 으로 먼저 완주하세요. [T3]")
        try: bot._tg(msg)
        except Exception: pass
        raise SystemExit(msg)

    if (not DRY_RUN) and (not AUTO_MODE):
        msg = ("⛔ 기동 거부 — DRY_RUN=off 인데 AUTO_MODE=off.\n"
               "   체결이 자동동기화 + 수동 /buy 로 두 번 반영됩니다.")
        try: bot._tg(msg)
        except Exception: pass
        raise SystemExit(msg)

    if KS_ONLY and LADDER_ONLY:
        print("⛔ KS_ONLY와 LADDER_ONLY는 동시 지정 불가 — 기동 거부"); return
    mode = ("DRY" if DRY_RUN else "LIVE") + "/실계좌" + ("/KS전용" if KS_ONLY else "") + ("/사다리전용" if LADDER_ONLY else "")      # [T3]
    banner = (f"⚙️ 토스 {mode} · AUTO_MODE={'on' if AUTO_MODE else 'off'} · "
              f"자동복귀={'on' if AUTO_RECOVER else 'off'} · 체결조회={FILLS_MODE} · "
              f"상한 보유×{CAP_RATIO}(min {CAP_FLOOR}주, 동적)")
    if AUTO_MODE and not AUTO_RECOVER:   # [중4] 복귀 교착 위험 조합
        banner += ("\n⚠️ AUTO_MODE=on · 자동복귀=off — 복귀신호 시 /enter가 거부되어 CASH 고착 위험. "
                   "토스 LIVE는 자동복귀=on 권장(탈출구는 /setpos뿐).")
    if AUTO_MODE:   # 입출금 안내 — ★2026-07-23 목돈 자동집행 도입으로 절차 자체가 바뀌었다.
        banner += ("\nℹ️ 입출금·입고·배당은 봇이 감지해 리포트에서 묻습니다(<code>/예 N</code>·<code>/아니오 N</code>). "
                   "수동 <code>/lumpsum ±금액 v|pool</code>도 그대로 됩니다. 크론 정지·SYNC_SINCE 조작 불필요.")   # ★ACCT-1
    print(banner)

    df  = bot.build_data()
    # [치명1/봇 8번 이식] 봇 main과 동일하게 '완성된 전일 종가' 단일 뷰로 통일.
    #   장중 크론(예: 23:40 KST=10:40 ET)에서 미완성 당일봉으로 킬스위치·월말·price_hint를
    #   판정하는 드리프트 차단. attrs(티커별 신선도)는 슬라이스에서 유실될 수 있어 명시 이관.
    _df2 = bot._drop_live_bar(df)
    if _df2 is not df: _df2.attrs = df.attrs
    df = _df2
    pos = bot.load_position()

    broker   = make_broker()
    notifier = Notifier(bot._tg)
    auto     = LadderAutomator(broker, SYMBOL, dry_run=DRY_RUN, notify=notifier)

    # ★R2 게이트(2026-07-23): 목돈 주문이 체결 대기 중이면 사다리를 배치하지 않는다.
    #   day_only 재배치라 cancel-first가 목돈 주문까지 취소하고, shares는 체결 전(구주수)인데
    #   V만 신규라 매수단 전체가 시장가 위에 깔려 즉시 폭주 체결된다(실측).
    _orig_rotate = auto.rotate_cycle
    def _gated_rotate(pos, *a, **kw):
        if pos.get("lump_in_flight"):
            notifier("⏸️ 목돈 체결 대기 — 오늘 사다리 배치 보류(동기화 후 재개)")
            return []
        return _orig_rotate(pos, *a, **kw)
    auto.rotate_cycle = _gated_rotate

    # ★ACCT-1: 건이 열려 있는 동안 프레임워크 reconcile의 🚨 /setpos 처방 문구를 "건 #N에 답하세요"로 치환.
    #   (문구만 치환 — 판정·사다리 중단 동작은 프레임워크 원문 그대로. 두 가지 V 숫자가 동시에 나가
    #    한쪽을 손으로 따라 치는 사고 방지.)
    _orig_recon = auto.reconcile
    def _acct_recon(pos, quiet=False):
        _case = pos.get("acct_case")
        if not _case:
            return _orig_recon(pos, quiet)
        _saved = auto._notify
        def _swap(m):
            if str(m).lstrip().startswith("🚨 포지션 불일치"):
                _saved(f"🚨 포지션 불일치(실보유≠원장) — 계좌 변동 건 #{_case.get('id')}로 처리 중입니다. "
                       f"리포트의 <code>/예 {_case.get('id')}</code>·<code>/아니오 {_case.get('id')}</code>로 답하세요"
                       f"(수동 <code>/setpos</code> 불필요). 해소 전까지 사다리 배치는 중단됩니다.")
            else:
                _saved(m)
        auto._notify = _swap
        try:
            return _orig_recon(pos, quiet)
        finally:
            auto._notify = _saved
    auto.reconcile = _acct_recon

    px_col = ("TQQQ_REAL" if ("TQQQ_REAL" in df.columns and
                              not bot.pd.isna(df["TQQQ_REAL"].iloc[-1])) else "TQQQ")
    price_hint = float(df[px_col].iloc[-1])   # ★ACCT-1: 감지(처음 등록 V·목돈 비중)에 필요해 앞으로 이동(값 동일)

    since = rolling_since(5)
    if SYNC_SINCE and SYNC_SINCE > since:
        since = SYNC_SINCE
        # ★B 관련(2026-07-24): 좁히기는 '그 이전 체결을 영구히 무시'하는 설정이다.
        #   프레임워크 프루닝 하한 교정으로 '좁힘→복원 시 이중반영'은 막혔지만,
        #   좁힌 창에서 한 번도 반영되지 않은 옛 체결은 SYNC_SINCE를 제거하면 그때 들어온다.
        #   → 한 번 설정했으면 계속 유지하는 게 안전하다.
        notifier(f"ℹ️ SYNC_SINCE={SYNC_SINCE} 적용 — 이 날짜 이전 체결은 무시됩니다. "
                 f"⚠️ 나중에 이 설정을 <b>제거하면</b> 미반영 옛 체결이 원장에 들어옵니다(유지 권장).")

    if (not DRY_RUN) and (not KS_ONLY) and (not LADDER_ONLY):   # ★KS-OPEN·LADDER-ONLY: 보조 실행은 daily_run의 ①sync가 담당(중복 억제). 목돈 사후처리·입출금 감지도 정규 실행 몫.
        try:
            pos = auto.sync_fills(pos, since)
            bot.save_position(pos)
        except Exception as e:
            bot._tg(f"🚨 체결동기화 실패 — 이후 단계 중단(안전): {e}")
            notifier.flush()
            raise

        # ★R2 사후처리: 목돈 주문의 체결 확정 여부 판정 → 예산·사다리 재정렬(수동 /lumpsum_done과 동일 의미)
        pos = _resolve_lump(broker, pos, notifier)   # ★LUMP-RESOLVE: 원 블록을 추출 함수 호출로 대체(동작 동일)

        # ★K-B 교정: 어댑터가 last_recover_check를 '집행/확정일'(UTC today)로 찍는다.
        #   봇 /exit와 동일하게 '판정일'(evac_sig_date, 7일 이내)로 교정 — 그 사이 월말이
        #   소급복귀 후보에서 빠져 복귀가 최대 한 달 지연되는 것을 막는다.
        try:
            _esd = pos.get("evac_sig_date")
            if pos.get("state") == "CASH" and _esd:
                _fresh = 0 <= (bot._wall_today() - bot.pd.Timestamp(_esd)).days <= 7
                if _fresh and pos.get("last_recover_check") != _esd:
                    pos["last_recover_check"] = _esd
                    pos.pop("evac_sig_date", None)
                    bot.save_position(pos)
                    notifier(f"ℹ️ 소급복귀 기준일 교정 → {_esd}(대피 판정일)")
        except Exception:
            pass

    # ★ACCT-1(rev.6): 계좌 변동 감지·질문(체결 반영 직후 → 남는 차이 = 외부 입출금·입고·배당·수동매매).
    #   종전 '미신고 입출금 감지'(알림만·미체결 있으면 스킵) 블록을 대체. DRY는 미리보기만.
    #   정규 실행에서만(사다리 전용·KS 전용 실행은 체결 동기화가 daily_run 안에 있어 여기서 감지하면 오탐).
    if not (KS_ONLY or LADDER_ONLY):
        pos = _acct_detect(broker, pos, notifier, price_hint)

    pos = bot.ensure_V(pos, price_hint)

    V_tmp = pos.get("V", 0.0) or (pos.get("shares", 0.0) * price_hint)
    if ON(bot.VOLTGT_ON) and pos.get("cyc_scale") is not None:
        scale = float(pos["cyc_scale"])
    else:
        rv = float(df["RV"].iloc[-1]) if not bot.pd.isna(df["RV"].iloc[-1]) else float("nan")
        scale = (min(1.0, bot.VOLTGT_TARGET / rv)
                 if (ON(bot.VOLTGT_ON) and rv == rv and rv > 0) else 1.0)
    if KS_ONLY or LADDER_ONLY:
        cmd_results = []   # ★KS-OPEN·LADDER-ONLY: 명령 창구는 정규 실행으로 단일화(오프셋 경합 원천 차단)
    else:
        pos, cmd_results = bot.process_commands(pos, price_hint, V_tmp * scale)

    # [Q1] 프로브는 명령 처리 뒤.
    # ★교정(2026-07-24): 목돈 집행 '앞'으로 이동. 뒤에 두면 집행일에
    #   주문→즉시체결→probe 순서가 되어 원장(체결 미반영) vs 실보유가 어긋나
    #   허위 "🚨 포지션 불일치" 경보가 뜬다. 체결은 다음 실행 sync가 정상 반영한다.
    if not (KS_ONLY or LADDER_ONLY):   # ★KS-OPEN·LADDER-ONLY: 프로브는 정규 실행 몫
        probe(broker, pos, since, notifier)

    # ★목돈 자동 집행 — 명령 처리 직후·롤오버 전.
    #   AUTO_MODE에서만 자동. 수동 모드는 기존 /lumpsum_done 경로 유지(이중처리 방지).
    if (AUTO_MODE or DRY_RUN) and not (KS_ONLY or LADDER_ONLY):   # ★KS-OPEN·LADDER-ONLY: 목돈 집행도 정규 실행 몫
        pos = apply_pending_lump(broker, pos, price_hint, notifier)
        # ★LUMP-RESOLVE(2026-08-12 은박사님 승인 v2): 같은 실행 내 목돈 해소 — 사다리 공백 교정.
        #   ①게이트 잔존 시에만 ②sync 1회(fills_seen 키 기반 멱등 — 750블록·daily_run ①sync가 이미
        #   공존하는 기존 구조와 동일 전제) ③'이 주문' 체결이 fills_seen에서 확인될 때만 _resolve_lump
        #   호출 → 정상 체결(✅) 분기만 도달. 미확인 시 무동작(추가 알림 0) — PENDING·미체결소멸 분기는
        #   여기서 절대 타지 않는다(허위 '미체결 소멸' 원천 차단). 판정식은 해소기 원문(★R-B 뒤에서
        #   세는 키 파싱·★B 0패딩 정규화)과 동일 코드 재사용.
        _lr_oid = pos.get("lump_in_flight")
        if _lr_oid and (not DRY_RUN):
            try:
                pos = auto.sync_fills(pos, since)
                bot.save_position(pos)
            except Exception as _lr_e:
                bot._tg(f"⚠️ 목돈 즉시해소용 체결동기화 실패 — 보류 유지(다음 정규 실행이 처리): {_lr_e}")
            else:
                _lr_norm = lambda x: str(x or "").strip().lstrip("0")
                def _lr_oid_of(k):
                    _p = str(k).split(":")
                    return {_lr_norm(_p[-2]) if len(_p) >= 3 else None,
                            _lr_norm(_p[-1]) if len(_p) >= 2 else None}
                if any(_lr_norm(_lr_oid) in _lr_oid_of(k) for k in (pos.get("fills_seen") or {})):
                    pos = _resolve_lump(broker, pos, notifier)   # 체결 확인됨 → ✅ 분기만 도달


    # ★R6 교정(2026-07-23): 롤오버를 명령·목돈 뒤로. 봇 순서(commands→rollover)와 정렬.
    #   책 방식과도 일치 — 목돈을 먼저 반영하고 '새 Pool' 기준으로 V+Pool/G를 계산해야 한다.
    #   (기존 순서면 pool 즉시확정이 경계일과 겹칠 때 lump/G(=10%)만큼 미반영)
    pos, roll_msg, cycle_changed = bot._cycle_rollover(pos, df)
    if cycle_changed:
        bot.save_position(pos)
    if (KS_ONLY or LADDER_ONLY) and roll_msg:
        notifier(f"🔄 {roll_msg}")   # ★KS-OPEN·LADDER-ONLY: 보조 실행엔 리포트가 없으므로 V갱신을 알림으로 보존(롤오버 자체는 날짜키 멱등 — 무수정)

    if pos.get("shares", 0) == 0 and pos.get("pool", 0) == 0 and not cmd_results:
        notifier.flush()
        bot._tg("⚠️ 포지션 미등록 — <code>/setpos</code> 먼저. 자동매매 스킵.")
        return

    # [중6] 복귀확정(sync)으로 cyc_budget이 pop된 상태면 봇 규칙(pool*BUY_LIMIT)으로 재설정.
    #   pop만 두면 다음 롤오버까지 매일 '현재 pool×50%'로 재계산되어 누적매수가 발산(부동예산).
    #   여기서 동결하면 봇 /enter(N1)의 "복귀일 Pool의 50% 총한도 동결" 의미를 정확히 미러.
    #   BUY_LIMIT은 bot 참조(봇 단일 진실). daily_run '전'에 실행 → 이번 회차부터 동결 적용.
    if pos.get("state") == "INVESTED" and pos.get("cyc_budget") is None:
        pos["cyc_budget"] = max(0.0, pos.get("pool", 0.0)) * bot.BUY_LIMIT
        pos["cyc_used"] = 0.0
        bot.save_position(pos)

    # [강화안] 대피 예약취소 3회 실패로 남은 예약 재취소(대피조건 무관·최우선). 성공 시 플래그 해제.
    #   재매수 후 다음 실행에 대피조건이 해소(반등)됐어도 잔존 매수예약을 청소 → 폭락 재매수/킬스위치 무력화 방지.
    #   daily_run 전에 실행 → 이번 회차 사다리 재배치와 안 섞임.
    if pos.get("evac_recancel") and getattr(broker, "uses_reservation", False) and not DRY_RUN:
        try:
            c = broker.cancel_all_reservations(SYMBOL)
            bot._tg(f"🧹 대피 잔존 예약 {c}건 재취소 완료(취소실패 후속 청소)")
            pos.pop("evac_recancel", None); bot.save_position(pos)
        except Exception as e:
            bot._tg(f"⚠️ 대피 잔존 예약 재취소 실패 — 다음 실행 재시도: {e}")

    pos = daily_run(auto, pos, bot.compute_signal, df, since, bot.save_position,
                    auto_recover=AUTO_RECOVER, compute_ladder=bot.compute_ladder,
                    ks_only=KS_ONLY, ladder_only=LADDER_ONLY)

    # ★A(2026-07-24): 복귀 신호가 실제로 떴는데 자동복귀가 꺼져 있으면 긴급 알림.
    #   러너는 "수동 /enter 정책"이라 접수하지 않는데, AUTO_MODE에선 그 /enter가 가드에 막힌다
    #   → CASH 고착. 시작 배너 경고만으론 그날 놓치기 쉬우므로 신호 시점에 다시 알린다.
    if AUTO_MODE and not AUTO_RECOVER and pos.get("state") == "CASH":
        try:
            _s = bot.compute_signal(df, pos)
            if str(_s.get("copy_cmd") or "").strip().lower().startswith("/enter") or _s.get("ks_recover"):
                bot._tg("🚨 <b>복귀 신호 발생 — 그러나 자동복귀가 꺼져 있습니다(AUTO_RECOVER=off)</b>\n"
                        "   러너가 접수하지 않았고, AUTO_MODE라 수동 <code>/enter</code>도 거부됩니다.\n"
                        "   → <b>AUTO_RECOVER=on</b>으로 바꾼 뒤 다시 실행하세요(CASH 고착 방지).")
        except Exception:
            pass

    try:
        ghost = broker.verify_placed(SYMBOL, since)
        if ghost: bot._tg(ghost)
    except Exception as e:
        bot._tg(f"🚨 접수주문 가시성 확인 중 오류: {e}")

    notifier.flush()

    if KS_ONLY or LADDER_ONLY:
        # ★KS-OPEN(2026-07-28)·LADDER-ONLY(2026-07-31): 보조 실행은 일일 리포트·Healthchecks ping을
        #   내지 않는다. 감시·리포트 기준은 정규 실행 유지. 대피·복귀·경고 알림은 위에서 이미 발송됨.
        print(("[KS전용]" if KS_ONLY else "[사다리전용]") + " 리포트·ping 스킵 — 정규 실행 몫")
        return

    s = bot.compute_signal(df, pos)
    head = [banner]
    head += bot.render_echo_head(pos, cmd_results)   # ★R-A(2026-07-24): 통지 재전송 안전망을 러너에도 미러.
                                                     #   누락 시 ⏮가 안 뜨고 echo가 최대 11개까지 누적된다(키움에서 실측된 사례).
    if cmd_results:
        head.append("✅ <b>처리된 명령</b>")
        head += [f"   • {r}" for r in cmd_results]
    if roll_msg:
        head.append(f"🔄 {roll_msg}")
    report = "\n".join(head) + "\n\n" + bot.build_report(s, df)

    if bot._tg(report):
        bot._ping()
        bot.clear_echo(pos)                          # ★R-A: 발송 성공 시에만 소거(실패면 잔존 → 다음 실행 ⏮)
        # [치명A + DRY제외] 실제 예약이 '전량' 배치됐을 때만 래치. DRY는 place_ladder_reserve를 안 타
        #   카운터가 0 → 래치 안 함(DRY를 며칠 돌려도 사이클 안 잠김). DRY→LIVE 전환 시 그날 바로 실제 사다리 배치.
        #   부작용: DRY 리포트에 사다리 매일 재표시(=DRY 로그로 사다리 내용 확인 이점). 부분실패도 익일 자가치유.
        _need = len(s.get("buy_ladder", [])) + len(s.get("sell_ladder", []))
        # ★W2(2026-07-24): _ladder_rsv_n은 '예약경로'에서만 증가한다. 토스는 예약 API 자체가 없어 uses_reservation=False [T2]
        #   (day_only 매일 재배치)라 항상 0 → 이 조건은 영원히 거짓이었다(사문).
        #   day_only에선 매일 재배치가 정상 동작이므로 래치 자체가 불필요 — 명시적으로 건너뛴다.
        _day_only = str(getattr(broker, "max_validity", "")).upper() == "DAY" or \
                    not getattr(broker, "uses_reservation", False)
        if (not _day_only) and s.get("ladder_posted") and broker._ladder_rsv_n >= _need:
            pos["ladder_placed_for"] = str(s["cyc_start"]); bot.save_position(pos)
        rcd = s.get("recover_check_date")
        recovering = bool(s.get("ks_recover")) or (s.get("action_ks") == "🔵 복귀")
        if rcd and not recovering and rcd != pos.get("last_recover_check", ""):
            pos["last_recover_check"] = rcd; bot.save_position(pos)
    else:
        print("[경고] 텔레그램 전송 실패"); print(report)


if __name__ == "__main__":
    # ★[2026-07-17] 무인(야간) 재시도 래퍼 — 두 원칙 엄수:
    #   원칙1(절대): 전체가 절대 GitHub 한계(yml timeout)를 넘지 않는다. run()은 시작하면
    #     못 멈추므로, '다음 run을 시작하면 한계를 넘을지'를 매번 실측 기반으로 판정해 막는다.
    #   원칙2(적당): 한계 안에서 과하지 않게, 5분 간격으로 여러 번 시도(서버 회복 시간 확보).
    #   중간 실패는 조용히(알림 X). 최종 실패에만 알림 1번(도배 방지). 놓쳐도 다음날 소급복구.
    #   fail-fast: 비일시 오류(V괴리·토큰 등)는 재시도 없이 즉시 크래시.
    import time as _time
    _TRANSIENT = ("MCI", "전송 오류", "후처리", "timeout", "timed out",
                  "Connection", "Read timed", "temporarily", "일시", "잠시",
                  "Max retries", "Remote end", "Bad Gateway", "502", "503", "504",
                  # ★(2026-07-25 승인) 지속 429 추가. 어댑터 _req 는 1회 재시도 후에도 429면
                  #   TossError "…실패[429]…" 를 올리는데, 목록에 없어 즉시 크래시했다.
                  #   유량초과는 정의상 일시적이고 5분 대기가 정확히 맞는 처방이다.
                  #   토스 레이트리밋 임계 미실측(확인필요 b)이라 더욱 필요하다.
                  #   ★대괄호까지 포함해 매칭한다 — 어댑터 포맷이 f"실패[{status_code}]" 라
                  #     맨 "429"로 두면 주문번호·가격 문자열에 우연히 429가 섞인 치명 오류를
                  #     일시오류로 오분류해 17분을 낭비하고 알림이 늦어진다.
                  "[429]")
    def _is_transient(e):
        s = str(e)
        return any(k.lower() in s.lower() for k in _TRANSIENT)

    _BUDGET     = 17 * 60      # 재시도 총예산 17분. yml timeout(아래 19분)보다 2분 여유=알림시간.
    _RETRY_GAP  = 5 * 60       # 재시도 간격 5분(서버 회복 시간).
    _ALERT_BUF  = 40           # 크래시 후 알림 전송 여유(초).
    _t0         = _time.time()
    _attempt    = 0
    _last_err   = None
    _last_run_s = 6 * 60       # 다음 run 소요 예측 초기값(첫 실측 전엔 6분 가정).
    while True:
        _elapsed = _time.time() - _t0
        # ★원칙1 핵심: 다음 run이 '실측된 소요시간'만큼 걸린다고 보고, 그게 예산을 넘으면 시작 안 함.
        #   (첫 run은 _attempt==0이라 무조건 1회는 실행 — 단 yml timeout이 최후 방어선.)
        if _attempt > 0 and (_elapsed + _last_run_s + _ALERT_BUF) >= _BUDGET:
            bot._emergency_tg(
                f"🚨 야간 재시도 {_attempt}회 실패(경과 {_elapsed/60:.1f}분) — 서버 장애 추정. "
                f"오늘 매매 스킵(다음 실행이 5영업일 소급으로 자동복구). 마지막: {_last_err}")
            print(f"[재시도 종료-예산] {_last_err}")
            raise SystemExit(1)
        _attempt += 1
        _rs = _time.time()
        try:
            run()
            break                              # 성공 → 종료
        except Exception as e:
            _last_run_s = _time.time() - _rs   # ★이번 run이 실제로 걸린 시간 → 다음 예측에 사용
            _last_err = e
            _elapsed = _time.time() - _t0
            if not _is_transient(e):            # 비일시 → 즉시 크래시
                bot._emergency_tg(e)
                print(f"[크래시-비일시] {e}"); traceback.print_exc()
                raise
            # 5분 대기 전에도 검사: 대기 후 다음 run이 예산 넘으면 대기 생략 → 즉시 판정.
            if (_elapsed + _RETRY_GAP + _last_run_s + _ALERT_BUF) >= _BUDGET:
                print(f"[대기 생략 — 남은시간 부족, 경과 {_elapsed/60:.1f}분]")
                continue
            print(f"[야간 재시도 {_attempt}회 경과 {_elapsed/60:.1f}분, "
                  f"직전 run {_last_run_s/60:.1f}분] {e} → 5분 후 재시도(조용히)")
            _time.sleep(_RETRY_GAP)
