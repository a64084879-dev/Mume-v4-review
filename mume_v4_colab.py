name: TQQQ/GLD Daily Bot

# ───────────────────────────────────────────────────────────
#  실행 스케줄
#   - cron은 UTC 기준. '0 22 * * *' = UTC 21:30 매일 = KST 06:30 매일
#   - 뉴욕장 마감 후 전 거래일 종가 기준 지표 수집
#   - workflow_dispatch: Actions 탭에서 수동 실행("Run workflow") 가능
# ───────────────────────────────────────────────────────────
on:
  schedule:
    - cron: '37 22 * * *'
  workflow_dispatch:

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: 저장소 체크아웃
        uses: actions/checkout@v4

      - name: 파이썬 환경 설정
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      # ─── 캐시 복원/저장 (CSV 캐시 + last_report_date.txt 보존) ───
      #  연휴로 캐시가 날아가도 봇은 전체 재계산해 현재 상태를 정확히 복원하므로
      #  치명적이지 않음. 캐시는 속도·신호누락방지용 안전장치.
      - name: 봇 캐시 복원
        uses: actions/cache@v4
        with:
          path: ./bot_cache
          key: bot-cache-${{ runner.os }}-${{ github.run_id }}
          restore-keys: |
            bot-cache-${{ runner.os }}-

      - name: 패키지 설치
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: 봇 스크립트 실행
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          HEALTHCHECK_URL: ${{ secrets.HEALTHCHECK_URL }}
          BOT_CACHE_DIR: ./bot_cache
        run: |
          mkdir -p ./bot_cache
          python bot.py

      - name: 2008형 디버전스 알림 실행
        if: always()
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FAST_TG_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          FAST_TG_CHAT: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python fast_divergence_alert.py

      - name: 연말 점검 리마인더 (KST 12월 20일에만 발송)
        if: always()
        env:
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FAST_TG_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          FAST_TG_CHAT: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          python fast_yearend_reminder.py
