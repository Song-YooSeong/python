# Windows 회의 녹음 요약 앱

## 분석 결과

기존 `src/realtime_stt_app.py`는 브라우저가 마이크를 녹음하고 FastAPI가 업로드된 파일을 처리하는 구조입니다.

1. 브라우저 녹음 또는 오디오 파일 선택
2. FastAPI 임시 파일 저장
3. 5분 단위 오디오 분할
4. OpenAI Audio Transcriptions API 전사
5. 긴 전사문 분할 요약 후 최종 회의자료 생성

새 Windows 앱은 같은 `MeetingSummaryService`를 재사용하므로 전사 모델, 요약 모델, 긴 파일 처리, 설정 파일 형식이 웹 앱과 동일합니다. 화면과 녹음 입력만 PySide6 네이티브 UI와 `sounddevice`로 교체했습니다.

## 개발 실행

가상환경에서 의존성을 설치합니다.

```powershell
venv\Scripts\activate
pip install -r requirements.txt
python src\realtime_stt_windows.py
```

처음 실행하면 실행 파일이 설치된 `MeetingSummary` 폴더 아래에 `config\openai_config.json`이 생성됩니다. 예를 들어 `C:\Program Files\MeetingSummary\config\openai_config.json`입니다. `api_key`에 OpenAI API 키를 입력한 뒤 앱을 다시 처리하면 됩니다.

## Windows 실행 파일 빌드

```powershell
venv\Scripts\pyinstaller.exe --noconfirm --clean realtime_stt_windows.spec
```

빌드 결과는 `dist\MeetingSummary.exe`입니다. `ffmpeg.exe`는 현재 긴 오디오 분할에 필요하므로 실행 파일 또는 PATH에 설치해야 합니다.

## 사용 흐름

1. `녹음 시작`을 누르고 저장할 WAV 경로를 선택합니다.
2. 회의가 끝나면 `녹음 중지`를 누릅니다.
3. 또는 `오디오 파일 열기`로 기존 녹음 파일을 선택합니다.
4. 회의 정보와 전사 힌트를 입력하고 `전사 및 요약`을 누릅니다.
5. 결과를 확인하고 `결과 저장`으로 텍스트 파일을 저장합니다.

OpenAI API 호출은 별도 작업 스레드에서 실행되어 UI가 멈추지 않습니다. API 키와 회의 오디오는 로컬 파일에 기록되며, 오디오 처리를 위해 OpenAI API로 전송됩니다.