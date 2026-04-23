
from datetime import datetime
import schedule
import time
import logging

logging.basicConfig(
    filename="run.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def job():
    now=datetime.now()
    msg = f"보고서 생성 : {now:%H:%M:%S}"
    print(msg)
    logging.info(msg)

def main():
    print("스케줄러 시작")
    schedule.every().minute.at(":10").do(job)

    while True:

        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()    