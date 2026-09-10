"""Windows 전용 회의 녹음 전사·요약 프로그램 진입점.

이 프로그램은 FastAPI 서버를 실행하지 않습니다.
PySide6 GUI에서 마이크 녹음 또는 오디오 파일을 선택하고 OpenAI API로
전사·요약한 결과를 화면에 표시한 뒤 텍스트 파일로 저장합니다.
"""

from realtime_stt_windows import main


if __name__ == "__main__":
    raise SystemExit(main())
