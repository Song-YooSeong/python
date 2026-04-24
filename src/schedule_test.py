"""
프로그램 흐름 설명
1. logging 설정을 먼저 만들어 실행 기록이 파일에 남도록 준비합니다.
2. `job()` 함수는 현재 시간을 읽어 화면과 로그 파일에 같은 내용을 남깁니다.
3. `main()` 함수는 매 분 10초에 `job()`이 실행되도록 schedule에 등록합니다.
4. 무한 반복문에서 `schedule.run_pending()`을 계속 호출해 실행 시간이 된 작업을 수행합니다.
5. 반복문 사이에 1초씩 쉬어서 CPU를 과하게 쓰지 않도록 합니다.
"""

from datetime import datetime
import logging
import schedule
import time

# 실행 결과를 run.log 파일에 기록하도록 logging을 설정합니다.
logging.basicConfig(
    filename="run.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def job() -> None:
    """예약 시간이 되면 현재 시각을 출력하고 로그로 남깁니다."""
    now = datetime.now()
    message = f"보고서 생성 시각: {now:%H:%M:%S}"
    print(message)
    logging.info(message)


def main() -> None:
    """스케줄을 등록하고 계속 감시합니다."""
    print("스케줄러 시작")

    # 매 분 10초가 되는 시점에 job 함수를 실행합니다.
    schedule.every().minute.at(":10").do(job)

    while True:
        # 지금 실행할 시간이 된 작업이 있으면 여기서 호출됩니다.
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
