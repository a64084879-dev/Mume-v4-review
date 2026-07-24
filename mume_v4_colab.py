# -*- coding: utf-8 -*-
"""
vr_kiwoom_adapter.py — 키움증권 REST API 어댑터 (BrokerAdapter 구현)  rev.4
════════════════════════════════════════════════════════════════════════
★ rev.4 (2026-07-20): 07:30 개장전 예약 집행 전환 — 사다리 예약 인프라 추가.
  place_ladder_reserve(기간예약 잔량주문 rsrv_ord_tp="2" + 지정가 frgn_trde_tp="00") ·
  list_reservations(ust21201 미취소 예약 조회) · cancel_reservation(ust21202) · cancel_all_reservations.
  책 예시(127p 매수점=최소밴드/n, 129p 매도점=최대밴드/n) 및 "2주치 지정가 예약매매"와 정합.
  프레임워크가 place_order→예약주문으로 개조될 때 사용(대피/복귀=_reserve 시장가, 사다리=이 메서드 지정가).

★ rev.3 (2026-07-20): 공식 postman 컬렉션(Kiwoom-Securities/Kiwoom-REST-API)으로
  전 TR 요청·응답 필드를 전수 재검증 → rev.2의 추정 오류 3종 교정.
  ① 종목코드 필드명: 대부분 TR은 stk_cd(12) — rev.2의 stk_cd는 틀림. (현재가 usa20100만 stk_cd 20)
     ★영향: 요청뿐 아니라 '응답 파싱'도 stk_cd로. 특히 잔고(ust21070) 응답이 stk_cd라
       rev.2는 항상 미보유 오판 → 킬스위치가 보유0으로 봐 매도 불발되는 치명버그였다.
  ② stex_tp: 6자리 국가코드(미국=000030). 주문계열(매수/매도/취소/미체결/현재가) TR엔 필드 자체가 없음.
     rev.2가 넣던 stex_tp="ND"는 값·존재 모두 오류. 잔고/체결은 빈값(전체조회) 유지, 예약은 000030.
  ③ _reserve(ust21200)는 프레임워크 미사용(죽은 코드) — 아래 주석 참조. 명세만 일치시켜 둠.
  ⚠️ postman 명세로 필드는 확정됐으나 실서버 동작(stex_tp=000030 처리, 응답 필드 실재)은 G1(라이브 1주)로 최종 확인.

★ rev.2 (2026-07-12): 공식 명세서(키움_REST_API_문서.xlsx, 339 TR) 수령 →
  국내(dostk) 추정 코드를 미국(us) 스펙으로 전면 교체(rev.3에서 필드명 오류 교정).

━━ 공식 확정 사항 (추정 아님 — 명세서 원문) ━━━━━━━━━━━━━━━━━━━━
  · 도메인   실전 https://api.kiwoom.com  /  모의 https://mockapi.kiwoom.com
  · 토큰     POST /oauth2/token  body{grant_type,appkey,secretkey}
             → token / token_type / expires_dt(YYYYMMDDHHMMSS)   ★expires_in 아님
  · URL 3개  /api/us/ordr(주문) · /api/us/acnt(계좌) · /api/us/mrkcond(시세)
             ★전부 POST. api-id 헤더로 TR 분기. 계좌번호는 body에 넣지 않는다(앱키 귀속).
  · 페이징   요청/응답 '헤더'의 cont-yn / next-key
  · 응답목록 result_list  (※명세서 응답예제에 result_lsit 오타 존재 → 양쪽 모두 수용)
  · 숫자     전부 String. 수량은 12자리 0-padding("000000000001"), 단가는 소수 4자리.
  · 거래소   stex_tp = 6자리 국가코드(000030=미국). ★주문계열 TR엔 stex_tp 필드 자체가 없음:
             현재가/매수/매도/취소/미체결 = 없음 · 잔고/체결 = 있음(빈값=전체조회) · 예약 = 000030 필수.
  · 종목코드 ★TR별로 필드명이 다름: 현재가(usa20100)=stk_cd(20자리) / 그 외 전부=stk_cd(12자리).
  · 매매구분 trde_tp = 00:지정가 03:시장가 26:VWAP지정 27:TWAP지정 ★30:LOC 36/37:VWAP/TWAP시장가
  · 매도매수 slby_tp = 1:매도, 2:매수
  · 레이트   TR별 1req/s(버스트2), 초과 시 HTTP 429

━━ TR 매핑 (공식) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  au10001 토큰 · usa20100 현재가 · ust20000 매수 · ust20001 매도 · ust20003 취소
  ust21070 원장잔고 · ust21050 원장미체결 · ust21150 일별주문체결내역 · ust21110 예수금

━━ 설계 주의 (명세서에서 드러난 구조 차이) ━━━━━━━━━━━━━━━━━━━━
 [K1] ust21150(체결)은 '하루 단위' 조회다(ord_dt 1개). KIS ccnl처럼 기간(strt~end)이 없다.
      → get_fills(since)는 since~오늘을 '날짜 루프'로 하루씩 조회한다.
      → 응답에 날짜 필드가 없다 → filled_at은 '조회에 사용한 ord_dt'로 채운다.
        (프레임워크 dedup 키 = filled_at:order_id:side → 날짜가 정확해야 충돌 없음)
 [K2] ust21150 응답에 '수수료 필드가 없다' → FEE_RATE 추정 유지. [실측필요]
 [K3] ust21150의 side는 slby_tp_nm(한글명)뿐 — 코드값 미보장. 이름으로 판정하되
      판정불가면 KiwoomError(기본 sell 낙착 금지 — pool 역방향 오염 방지).
 [K4] 취소(ust20003)는 수량을 받지 않는다(orig_ord_no+stex_tp+stk_cd → 원주문 취소).
      qty 인자는 프레임워크 3인자 시그니처 호환용으로 받되 사용하지 않는다.
 [K5] 미체결 판정은 ord_remnq(주문잔량)>0. cntr_qty(체결수량)와 별도 필드로 동시 제공된다.
════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import time, json, datetime, requests
from vr_broker_adapter import BrokerAdapter, OrderReq, Fill, Position


class KiwoomError(Exception):
    """키움 API 오류 — 조용한 실패 금지, 상위 전파(킬스위치 무음 차단)."""
    pass


class KiwoomAdapter(BrokerAdapter):
    name = "kiwoom"
    LIVE = "https://api.kiwoom.com"
    MOCK = "https://mockapi.kiwoom.com"
    # [K2] ust21150 응답에 수수료 필드 없음 → 요율로 추정. 2026-07-14 실측 확정:
    #   · 모의계좌: 왕복 2회 역산 모두 1.0%(모의 서버 기본값, 비현실적으로 높음)
    #   · 실전 우대계좌: 0.07% (은박사 계약 요율)
    #   생성자 fee_rate 인자로 주입(모의검증=0.01 / 실전=0.0007). 기본은 실전 우대.
    FEE_RATE = 0.0007         # 실전 우대계좌 기본. 모의 검증 시 fee_rate=0.01 로 생성.
    max_validity = "DAY"      # ★실측: 키움 REST 미국 예약(ust21200) 실서버 미지원 확정 → 실시간 주문 방식으로 복원.
                              #   day_only=True → 프레임워크가 매일 fresh 사다리를 place_order(지정가 DAY)로 배치.
    uses_reservation = False  # ★실측: 예약 불가 → place_order 실시간 경로. 사다리=지정가, 킬스위치=marketable limit(장중).
                              #   (예약 관련 메서드 place_ladder_reserve 등은 잔존하나 미사용 — 키움이 예약 열면 재활성 가능)
                              #   프레임워크가 이 플래그로 예약경로 분기. KIS/토스는 플래그 없음(정규경로 유지).

    U_ORDR = "/api/us/ordr"   # 주문 (POST)
    U_ACNT = "/api/us/acnt"   # 계좌 (POST)
    U_MKT  = "/api/us/mrkcond"# 시세 (POST)

    API = {                    # ✅ 공식 명세서 확정 (2026-07-12)
        "token":      "au10001",   # 접근토큰 발급
        "us_price":   "usa20100",  # 미국주식 현재가 종목정보
        "us_buy":     "ust20000",  # 미국주식 매수 주문
        "us_sell":    "ust20001",  # 미국주식 매도 주문
        "us_cancel":  "ust20003",  # 미국주식 취소 주문
        "us_balance": "ust21070",  # 미국주식 원장잔고확인
        "us_unfilled":"ust21050",  # 미국주식 원장 미체결
        "us_filled":  "ust21150",  # 미국주식 일별 주문체결내역
        "us_cash":    "ust21110",  # 해외주식 예수금
        "us_rsv":     "ust21200",  # 🟠 미국주식 기간예약주문 (개장 자동체결) — G1 라이브 검증 전 provisional
        "us_rsv_list":"ust21201",  # 미국주식 예약주문 내역조회 (걸린 예약 목록)
        "us_rsv_cncl":"ust21202",  # 미국주식 예약주문 취소 (rsrv_dt + rsrv_ord_no)
    }

    TRDE = {"LIMIT": "00", "MARKET": "03", "LOC": "30"}   # 매매구분(공식)
    US_STEX = "ND"        # ★실측+명세 확정: 미국 거래소구분 [NA=AMEX, ND=NASDAQ, NY=NYSE]. TQQQ=ND. (rev.3 "000030"은 오류)

    def __init__(self, appkey, secretkey, account_no="", mock=True, excd="ND", fee_rate=None):
        self.appkey = str(appkey).strip()          # [N1] 공백/개행 방어 (KIS 실증 교훈)
        self.secretkey = str(secretkey).strip()
        self.account = str(account_no).strip()     # body에 불필요(앱키 귀속). 로그·식별용.
        self.mock = mock
        self.excd = excd                           # ★rev.3: stex_tp엔 미사용(US_STEX=000030 사용).
                                                   #   러너 KIWOOM_EXCD 하위호환·로그용으로만 보존.
        self.BASE = self.MOCK if mock else self.LIVE
        # 수수료율: 명시 주입 우선 → 없으면 모의 1.0% / 실전 우대 0.07% 자동
        if fee_rate is not None:
            self.FEE_RATE = float(fee_rate)
        elif mock:
            self.FEE_RATE = 0.01               # 모의 서버 기본값(실측)
        # else: 클래스 기본 0.0007(실전 우대) 사용
        self._token = None
        self._exp = 0
        self._sess = requests.Session()
        self._query_sleep = 1.1                    # TR당 1req/s(공식) — 보수적으로 1.1
        self._order_sleep = 1.1

    # ── 인증 ────────────────────────────────────────────────────
    def authenticate(self):
        if self._token and time.time() < self._exp - 60:
            return
        cache = f".kiwoom_token_{'mock' if self.mock else 'live'}.json"
        try:
            with open(cache) as f:
                cd = json.load(f)
            if cd.get("exp", 0) > time.time() + 120:
                self._token = cd["token"]; self._exp = cd["exp"]; return
        except Exception:
            pass
        body = {"grant_type": "client_credentials",
                "appkey": self.appkey, "secretkey": self.secretkey}
        r = self._sess.post(f"{self.BASE}/oauth2/token",
                            headers={"Content-Type": "application/json;charset=UTF-8",
                                     "api-id": self.API["token"]},
                            data=json.dumps(body), timeout=10)
        if r.status_code != 200:
            raise KiwoomError(f"인증 실패[{r.status_code}]: {r.text[:120]}")
        d = r.json()
        self._token = d.get("token") or d.get("access_token")
        if not self._token:
            raise KiwoomError(f"토큰 없음: {d}")
        # ✅공식: expires_dt = "YYYYMMDDHHMMSS"(KST). expires_in(초)은 없다.
        exp_dt = str(d.get("expires_dt", "") or "")
        if len(exp_dt) == 14 and exp_dt.isdigit():
            try:
                # ★K-A 교정(2026-07-23): expires_dt는 KST 문자열. naive로 두면 UTC 서버(A1/Actions)에서
                #   로컬=UTC로 해석돼 실제보다 9시간 늦게 만료 인식 → 죽은 토큰으로 호출.
                self._exp = datetime.datetime.strptime(exp_dt, "%Y%m%d%H%M%S").replace(
                    tzinfo=datetime.timezone(datetime.timedelta(hours=9))).timestamp()
            except Exception:
                self._exp = time.time() + 3600
        else:
            self._exp = time.time() + int(d.get("expires_in", 3600) or 3600)
        try:
            with open(cache, "w") as f:
                json.dump({"token": self._token, "exp": self._exp}, f)
        except Exception:
            pass

    def _headers(self, api_id, cont_yn="N", next_key=""):
        self.authenticate()
        h = {"Content-Type": "application/json;charset=UTF-8",
             "authorization": f"Bearer {self._token}", "api-id": api_id}
        if cont_yn == "Y":
            h["cont-yn"] = "Y"; h["next-key"] = next_key
        return h

    # ── 공통 POST ───────────────────────────────────────────────
    def _post(self, path, api_id, body, err, paged=False):
        """paged=True면 응답 헤더 cont-yn/next-key로 result_list를 이어붙인다."""
        rows = []; cont_yn, next_key = "N", ""
        d = {}
        for _ in range(10):
            r = self._sess.post(f"{self.BASE}{path}",
                                headers=self._headers(api_id, cont_yn, next_key),
                                data=json.dumps(body), timeout=10)
            if r.status_code == 429:                        # 유량초과 → 백오프 1회
                time.sleep(1.5)
                r = self._sess.post(f"{self.BASE}{path}",
                                    headers=self._headers(api_id, cont_yn, next_key),
                                    data=json.dumps(body), timeout=10)
            if r.status_code != 200:
                raise KiwoomError(f"{err} 실패[{r.status_code}]: {r.text[:150]}")
            d = r.json()
            # 200 + 본문 return_code로 오류를 주는 구조(KIS rt_cd 교훈) — 반드시 검사.
            rc = d.get("return_code")
            if rc is not None and str(rc) not in ("0", "None"):
                raise KiwoomError(f"{err} 오류[return_code={rc}]: {d.get('return_msg','')}")
            if not paged:
                time.sleep(self._query_sleep)
                return d
            rows += self._rows(d)
            cy = (r.headers.get("cont-yn", "") or "").upper()
            nk = r.headers.get("next-key", "") or ""
            time.sleep(self._query_sleep)
            if cy != "Y" or not nk or nk == next_key:       # 커서 에코 방어
                break
            cont_yn, next_key = "Y", nk
        return {"result_list": rows}

    @staticmethod
    def _rows(d):
        """result_list 추출. ※명세서 응답예제에 'result_lsit' 오타가 있어 양쪽 수용."""
        return d.get("result_list") or d.get("result_lsit") or []

    @staticmethod
    def _num(v):
        """0-padding 문자열("000000000001")·소수 문자열·None 안전 변환."""
        try:
            s = str(v if v is not None else "0").strip()
            return float(s) if s else 0.0
        except Exception:
            return 0.0

    # ── 조회 ────────────────────────────────────────────────────
    def get_holdings(self, symbol) -> Position:
        # ust21070 원장잔고확인. 전체조회(빈값) → result_list에서 심볼 매칭.
        # ★rev.3: 요청·응답 모두 stk_cd(공식 postman). rev.2의 stk_cd는 응답 매칭 실패 →
        #   항상 미보유 오판(킬스위치 매도 불발)이던 치명버그. stex_tp는 빈값=전체조회(미국만 잡아도 무해).
        d = self._post(self.U_ACNT, self.API["us_balance"],
                       {"stex_tp": "", "stk_cd": ""}, "잔고조회", paged=True)
        for h in self._rows(d):
            if str(h.get("stk_cd", "")).strip() == symbol:
                return Position(symbol,
                                self._num(h.get("poss_qty")),          # 보유수량
                                self._num(h.get("frgn_stk_book_uv")))  # 매입단가
        return Position(symbol, 0.0)   # 조회성공 + 미보유

    def get_cash_usd(self) -> float:
        # ust21110 해외주식 예수금 → result_list[USD].fc_ord_alowa(외화주문가능금액)
        d = self._post(self.U_ACNT, self.API["us_cash"], {}, "예수금조회")
        for c in self._rows(d):
            if str(c.get("crnc_code", "")).upper() == "USD":
                return self._num(c.get("fc_ord_alowa") or c.get("fc_entra"))
        return 0.0

    def get_price(self, symbol) -> float:
        # ★실측 확정: usa20100 요청은 stk_cd + stex_tp(둘 다 필수). rev.3의 "stex_tp 없음"은 실서버서 거부됨.
        d = self._post(self.U_MKT, self.API["us_price"],
                       {"stk_cd": symbol, "stex_tp": self.US_STEX}, "현재가조회")
        # ★2026-07-17 실측 수정: 키움 cur_prc는 부호가 '등락 방향'이다.
        #   상승일 "+76.2469" / 하락일 "-72.2150" — 부호 뒤 숫자가 실제 가격.
        #   기존 _num은 "-72.21"을 -72.21로 만들어 <=0 판정 → 하락장마다 크래시(실측).
        #   → 절댓값을 취한다. cur_prc가 비면 base_close_pric(부호 없는 종가) 폴백.
        px = abs(self._num(d.get("cur_prc")))
        if px <= 0:
            px = abs(self._num(d.get("base_close_pric")))   # 장 마감·미확정 시 종가
        if px <= 0:
            raise KiwoomError(f"현재가 0/미확정: {symbol} (휴장·심볼·거래소구분 확인)")
        return px

    def list_open_orders(self, symbol) -> list:
        # ust21050 원장 미체결. ord_dt 미입력 = 오늘.
        # ★rev.3: 공식 요청은 ord_dt·slby_tp·stk_cd만(stex_tp 없음). 응답 종목코드도 stk_cd.
        d = self._post(self.U_ACNT, self.API["us_unfilled"],
                       {"ord_dt": "", "slby_tp": "0", "stk_cd": ""},
                       "미체결조회", paged=True)
        out = []
        for o in self._rows(d):
            if symbol and str(o.get("stk_cd", "")).strip() != symbol:
                continue
            if self._num(o.get("ord_remnq")) <= 0:         # [K5] 잔량 0 = 이미 체결/취소
                continue
            sb = str(o.get("slby_tp", "")).strip()          # 1:매도 2:매수
            side = "buy" if sb == "2" else ("sell" if sb == "1" else "")
            # side 미지는 관용 — 취소는 ord_no 기반이라 무해(엄격화하면 rotate 교착).
            out.append({"order_id": str(o.get("ord_no", "")).strip(),
                        "side": side,
                        "price": o.get("ord_uv"),
                        "qty": self._num(o.get("ord_remnq"))})
        return out

    def get_fills(self, symbol, since) -> list:
        """[K1] ust21150은 '하루 단위' 조회(ord_dt 1개) → since~오늘 날짜 루프.
           [계약, 3사 통일] (filled_at:order_id)당 누적 체결수량 1행.
           filled_at = 조회에 사용한 ord_dt(YYYYMMDD) — 응답에 날짜 필드가 없다."""
        try:
            d0 = datetime.datetime.strptime(str(since)[:10], "%Y-%m-%d").date()
        except Exception:
            d0 = datetime.date.today() - datetime.timedelta(days=7)
        today = datetime.date.today()
        if (today - d0).days > 14:                  # 폭주 방지(1일=1콜×1.1초)
            d0 = today - datetime.timedelta(days=14)

        fills = []
        day = d0
        while day <= today:
            if day.weekday() >= 5:                  # 주말 스킵(미국장 없음)
                day += datetime.timedelta(days=1); continue
            ymd = day.strftime("%Y%m%d")
            d = self._post(self.U_ACNT, self.API["us_filled"],
                           {"ord_dt": ymd, "query_tp": "1", "slby_tp": "0",
                            "stex_tp": "", "stk_cd": ""},
                           f"체결조회({ymd})", paged=True)
            for o in self._rows(d):
                if symbol and str(o.get("stk_cd", "")).strip() != symbol:
                    continue
                fq = self._num(o.get("cntr_qty"))           # 누적 체결수량
                if fq <= 0:
                    continue
                price = self._num(o.get("cntr_uv"))         # 체결단가
                if price <= 0:
                    raise KiwoomError(f"체결단가 0 — 오염 방지 중단: ord_no={o.get('ord_no')}")
                # [K3] 코드값 미보장 → 한글 구분명 우선. 판정불가면 중단(sell 낙착 금지).
                nm = str(o.get("slby_tp_nm", ""))
                sb = str(o.get("slby_tp", "")).strip()
                if "매수" in nm or sb == "2":
                    side = "buy"
                elif "매도" in nm or sb == "1":
                    side = "sell"
                else:
                    raise KiwoomError(
                        f"체결 side 판정불가(slby_tp_nm={nm!r}, slby_tp={sb!r}) — 필드 실측 확정 필요. "
                        f"기본 sell 낙착은 pool 역방향 오염 위험이라 중단.")
                oid = str(o.get("ord_no", "")).strip()
                if not oid:
                    raise KiwoomError(f"체결에 주문번호 없음 — dedup 키 오염 위험 → 중단: {o}")
                fee = fq * price * self.FEE_RATE            # [K2] 응답에 수수료 없음 → 추정
                fills.append(Fill(symbol, side, int(fq), price, fee, oid, ymd))
            day += datetime.timedelta(days=1)
        return fills

    # ── 주문 ────────────────────────────────────────────────────
    def place_order(self, req: OrderReq) -> str:
        api_id = self.API["us_buy"] if req.side == "buy" else self.API["us_sell"]
        kind = (getattr(req, "order_kind", "") or "LIMIT").upper()
        limit = float(req.limit_price or 0)

        if kind == "LOC":
            trde = self.TRDE["LOC"]                 # ✅공식: 30 = LOC(종가지정가)
            if limit <= 0:                          # LOC도 ord_uv 필수(명세: 30이면 단가 입력)
                px = self.get_price(req.symbol)
                limit = round(px * 0.90, 2) if req.side == "sell" else round(px * 1.10, 2)
        elif kind in ("MARKET", "MOC", "MOO"):
            trde = self.TRDE["MARKET"]
            limit = 0.0                             # 시장가는 ord_uv 빈값
        else:
            trde = self.TRDE["LIMIT"]
            if limit <= 0:
                raise KiwoomError(f"지정가 주문 단가 0 이하 — 안전 중단: side={req.side}")

        # ★실측+명세 확정: ust20000/20001 Body = stex_tp(ND) + stk_cd + ord_qty + ord_uv + trde_tp.
        #   (rev.3의 stk_cd·stex_tp없음은 실서버서 "필수 stk_cd"·"종목없음"으로 거부됨 — 실측으로 확인)
        body = {"stex_tp": self.US_STEX,
                "stk_cd": req.symbol,
                "ord_qty": str(int(req.qty)),
                "ord_uv": ("" if trde == self.TRDE["MARKET"] else f"{limit:.2f}"),
                "trde_tp": trde}
        d = self._post(self.U_ORDR, api_id, body, "주문")
        oid = str(d.get("ord_no", "") or "").strip()
        if not oid:
            raise KiwoomError(f"주문접수이나 주문번호 없음 — 추적불능: {d}")
        time.sleep(self._order_sleep)
        return oid

    # ── ⚫ 기간예약주문(ust21200) — ★현재 프레임워크 미사용(죽은 코드) ★ ─────────────────
    #   [중요] killswitch_evacuate/recover_enter/사다리는 전부 place_order(정규 지정가)로
    #   '장중' 실행한다(vr_broker_adapter.py 참조). sell_at_open/buy_at_open(=이 _reserve)은
    #   코드 어디에서도 호출되지 않는다. 따라서 크론은 '장중(KST 23:40)'이어야 하며, 07:30 개장전
    #   예약 집행을 도입하려면 프레임워크(대피·복귀·사다리)를 place_order→_reserve로 개조해야 한다.
    #   그 개조 시 이 메서드를 쓰도록 필드는 공식 postman(Kiwoom-REST-API)으로 미리 확정해 둔다:
    #   ⚫ rev.3 교정: stex_tp="000030"(미국) · stk_cd · frgn_trde_tp 00지정가/03시장가 · ord_uv 단가.
    #   ★ rsrv_ord_tp 구분 (책 + 과거검증 2026-07-12 확정):
    #     · 킬스위치 대피/복귀 = 다음 영업일 '시초가 1회' → rsrv_ord_tp="1"(일반예약) + frgn_trde_tp="03"(시장가).
    #       rsrv_strt_dt=rsrv_end_dt=다음 영업일(당일 1회 집행). ← 이 _reserve의 기본 용도.
    #     · 사다리(2주치) = rsrv_ord_tp="2"(기간예약 잔량주문) + frgn_trde_tp="00"(지정가).
    #       예약수량−체결수량=잔량을 기간 동안 매일 재접수, 잔량 0이면 자동종료. rsrv_strt_dt~rsrv_end_dt=사이클 2주.
    #       (지정수량주문 rsrv_ord_tp="3"은 매일 최초수량 전량 재제출이라 사다리에 부적합.)
    #       → 사다리 예약은 개조 시 별도 경로로 rsrv_ord_tp="2"를 지정할 것(이 메서드는 대피/복귀 1회용).
    #   ⚠️ 실서버 동작(응답 rsrv_ord_no/frcs_dt, stex_tp·rsrv_ord_tp 처리)은 G1(라이브 1주)로 최종 확인 필요.
    @staticmethod
    def _kst_today():
        """예약 날짜용 KST 오늘(YYYYMMDD). Actions는 UTC이고 크론 22:30 UTC=KST 07:30이라
           UTC date는 KST 전날 → 한국 증권사(키움) 예약 기준일에 맞춰 KST로 산정.
           ※ 조회용 date.today()(get_fills 등)는 ET/UTC 정합이라 불변. 예약 날짜 계열만 KST."""
        return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime("%Y%m%d")

    def _reserve(self, side, symbol, qty, limit=None) -> str:
        today = self._kst_today()
        is_lmt = (limit is not None) and (float(limit) > 0)   # limit 주면 지정가 예약, 없으면 시장가
        body = {
            "stex_tp":      self.US_STEX,     # ★rev.3: 미국=000030 (rev.2 "ND"는 값·존재 오류)
            "am_pm_tp":     "A",              # 오전예약 → 미국 정규장 개장 시 실행
            "rsrv_ord_tp":  "1",              # 예약구분: 1일반 (당일 개장 1회)
            "rsrv_strt_dt": today,            # 기간예약시작일자(YYYYMMDD)
            "rsrv_end_dt":  today,            # 기간예약종료일자(YYYYMMDD)
            "stk_cd":     symbol,           # ★rev.3: stk_cd (rev.2 stk_cd 오류)
            "ord_qty":      str(int(qty)),
            "ord_uv":       (f"{float(limit):.4f}" if is_lmt else ""),  # 지정가=단가 / 시장가=빈값
            "stop_pric":    "",               # 스탑가 없음
            "frgn_trde_tp": ("00" if is_lmt else "03"),  # ★공식: 00지정가 03시장가
            "slby_tp":      ("1" if side == "sell" else "2"),  # 1매도 2매수
        }
        d = self._post(self.U_ORDR, self.API["us_rsv"], body, "예약주문")
        oid = str(d.get("ord_no", "") or d.get("rsrv_ord_no", "") or "").strip()
        if not oid:
            raise KiwoomError(f"예약주문 접수 불명확(주문번호 없음) — 안전 중단(수동확인): {d}")
        time.sleep(self._order_sleep)
        return oid

    def sell_at_open(self, symbol, qty, tag="killswitch", limit=None) -> str:
        return self._reserve("sell", symbol, qty, limit)

    def buy_at_open(self, symbol, qty, tag="recover", limit=None) -> str:
        return self._reserve("buy", symbol, qty, limit)

    # ── 🪜 사다리 예약 인프라 (책: 2주치 지정가 예약매매) ─────────────────────────────
    #   place_ladder_reserve = 기간예약(잔량주문 rsrv_ord_tp="2") + 지정가(frgn_trde_tp="00").
    #   책 예시(127p·129p) 검증: 매수점=최소밴드/n, 매도점=최대밴드/n. 봇 compute_ladder 각 칸을 예약.
    #   미체결분은 잔량으로 매일 재접수, 잔량 0이면 자동종료(책: 밴드 닿으면 체결, 미체결 유지).
    #   ⚠️ 실서버 잔량 재접수·예약 동시개수 한도는 G1(라이브 1주)로 최종 확인.
    def place_ladder_reserve(self, side, symbol, qty, limit, strt_dt, end_dt) -> str:
        """사다리 1칸 예약. strt_dt~end_dt=사이클 2주(YYYYMMDD). limit=칸 지정가(compute_ladder 출력)."""
        if float(limit) <= 0:
            raise KiwoomError(f"사다리 예약 지정가 0 이하 — 안전 중단: {side} {symbol}")
        strt_dt = max(str(strt_dt), self._kst_today())   # [중E] 과거 시작일 방지(재실행 시 옛 cyc_start를 KST오늘로 clamp)
        body = {
            "stex_tp":      self.US_STEX,     # 미국=000030
            "am_pm_tp":     "A",              # 오전예약
            "rsrv_ord_tp":  "2",              # ★기간예약(잔량주문): 잔량 매일 재접수, 잔량0 자동종료
            "rsrv_strt_dt": str(strt_dt),     # 사이클 시작일
            "rsrv_end_dt":  str(end_dt),      # 사이클 종료일(2주)
            "stk_cd":     symbol,
            "ord_qty":      str(int(qty)),    # lot 묶음 반영된 칸 수량
            "ord_uv":       f"{float(limit):.4f}",   # ★지정가 단가
            "stop_pric":    "",
            "frgn_trde_tp": "00",             # ★00 = 지정가
            "slby_tp":      ("1" if side == "sell" else "2"),
        }
        d = self._post(self.U_ORDR, self.API["us_rsv"], body, "사다리예약")
        oid = str(d.get("rsrv_ord_no", "") or d.get("ord_no", "") or "").strip()
        if not oid:
            raise KiwoomError(f"사다리 예약 접수 불명확(예약번호 없음): {d}")
        time.sleep(self._order_sleep)
        return oid

    def list_reservations(self, symbol="") -> list:
        """ust21201 미취소 예약 조회 → [{rsrv_dt, rsrv_ord_no, side, qty, symbol}].
           사이클 갱신·대피 시 '걸린 예약'을 찾아 취소하기 위한 조회."""
        body = {"rsrv_cncl_yn": "N",          # 미취소분만
                "stex_tp": self.US_STEX, "stk_cd": symbol or ""}
        d = self._post(self.U_ORDR, self.API["us_rsv_list"], body, "예약조회", paged=True)
        out = []
        for r in self._rows(d):
            if symbol and str(r.get("stk_cd", "")).strip() != symbol:
                continue
            sb = str(r.get("slby_tp", "")).strip()
            side = "sell" if sb == "1" else ("buy" if sb == "2" else "")
            out.append({"rsrv_dt": str(r.get("rsrv_dt", "")).strip(),
                        "rsrv_ord_no": str(r.get("rsrv_ord_no", "")).strip(),
                        "side": side,
                        "qty": self._num(r.get("ord_qty")),
                        "symbol": str(r.get("stk_cd", "")).strip()})
        return out

    def cancel_reservation(self, rsrv_dt, rsrv_ord_no, symbol) -> bool:
        """ust21202 예약 취소. rsrv_dt·rsrv_ord_no·stex_tp·stk_cd 전부 필수(공식).
           응답은 filler뿐 → _post의 return_code 검사로 오류 판정(예외 안 나면 성공)."""
        if not str(rsrv_ord_no).strip() or not str(rsrv_dt).strip():
            raise KiwoomError(f"예약취소 인자 부족(rsrv_dt={rsrv_dt}, no={rsrv_ord_no})")
        body = {"rsrv_dt": str(rsrv_dt).strip(),
                "rsrv_ord_no": str(rsrv_ord_no).strip(),
                "stex_tp": self.US_STEX, "stk_cd": symbol}
        self._post(self.U_ORDR, self.API["us_rsv_cncl"], body, "예약취소")
        time.sleep(self._order_sleep)
        return True

    def cancel_all_reservations(self, symbol="") -> int:
        """걸린 예약 전량 취소(사이클 갱신·대피용). 조회→각 취소.
           실패 시 예외 전파(무음실패 차단 — rotate가 '취소완료' 오인해 이중예약 방지)."""
        n = 0; fails = []
        for r in self.list_reservations(symbol):
            if not r["rsrv_ord_no"]:
                continue
            try:
                if self.cancel_reservation(r["rsrv_dt"], r["rsrv_ord_no"], r["symbol"] or symbol):
                    n += 1
            except Exception as e:
                fails.append((r["rsrv_ord_no"], str(e)))
        if fails:
            raise KiwoomError(f"예약취소 {len(fails)}건 실패: {fails[:3]}")
        return n

    def cancel_order(self, order_id, symbol="", qty=None) -> bool:
        """[K4] 공식 취소(ust20003) = orig_ord_no·stk_cd·cncl_qty(N). cncl_qty 생략=전량취소.
           qty는 프레임워크 3인자 시그니처 호환용 — 받되 사용하지 않는다(전량취소)."""
        # ★실측+명세 확정: 취소(ust20003) = orig_ord_no + stex_tp(ND) + stk_cd. (rev.3 "stex_tp 없음"은 오류)
        body = {"orig_ord_no": str(order_id).strip(),
                "stex_tp": self.US_STEX,
                "stk_cd": symbol}
        d = self._post(self.U_ORDR, self.API["us_cancel"], body, "취소")
        time.sleep(self._order_sleep)
        if not str(d.get("ord_no", "") or "").strip():
            raise KiwoomError(f"취소 성공 불명확 — 안전 중단(수동확인 필요): {d}")
        return True
