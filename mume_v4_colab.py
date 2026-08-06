===== fast_divergence_alert 드라이런 출력 (칠판 게시용) =====
script md5 = 13b5aea090bb1b42cf16a5c64f31fa48 | python 3.12.13
yfinance 0.2.66

----- CASE 2007-11-26 : python3 fast_divergence_alert.py 2007-11-26 -----
[DRY_RUN]
🚨 [대피 권고] S&P만 이탈 14일째 — 역대 가짜가 도달한 적 없는 구간.
이 선을 넘긴 것은 2007년(진짜, 21일 지속) 한 번뿐입니다. 대피 검토 시점.
버블 1686.71 | S&P -5.2% | 나스닥 +2.1%

[stderr]
/content/fast_divergence_alert.py:38: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  today_et = dt.datetime.utcnow() - dt.timedelta(hours=4)
----- CASE 2007-11-26 종료 (returncode=0) -----

----- CASE 2023-10-27 : python3 fast_divergence_alert.py 2023-10-27 -----
[DRY_RUN]
⚠ [2008형 감시] S&P만 200일선 아래 — 오늘 3일째 (나스닥은 위)
버블 735.09 | S&P 선 대비 -3.1% | 나스닥 +1.2%
참고: 지난 40년 가짜 경보는 전부 11일 안에 끝났습니다. 관찰 계속.

[stderr]
/content/fast_divergence_alert.py:38: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  today_et = dt.datetime.utcnow() - dt.timedelta(hours=4)
----- CASE 2023-10-27 종료 (returncode=0) -----

----- CASE 2024-06-03 : python3 fast_divergence_alert.py 2024-06-03 -----
조건 미충족 — 무발송

[stderr]
/content/fast_divergence_alert.py:38: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
  today_et = dt.datetime.utcnow() - dt.timedelta(hours=4)
----- CASE 2024-06-03 종료 (returncode=0) -----

===== 출력 끝 — 위 블록 전체를 칠판(mume_v4_colab.py)에 붙여넣어 커밋 =====

(동일 내용이 divergence_dryrun_output.txt 로도 저장됨)

