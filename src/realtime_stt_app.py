"""회의 녹음 파일을 전사(STT)하고 회의자료로 요약하는 FastAPI 프로그램.

처리 흐름을 한눈에 보면 다음 순서로 움직입니다.

1. 사용자가 브라우저에서 `http://127.0.0.1:8010/`에 접속합니다.
2. FastAPI가 `templates/meeting_stt.html` 화면을 내려줍니다.
3. 화면의 JavaScript(`static/meeting_stt.js`)가 마이크 녹음 또는 파일 선택을 처리합니다.
4. 사용자가 "회의자료 요약 생성" 버튼을 누르면 `/api/summarize-recording`으로 음성 파일이 업로드됩니다.
5. 서버는 업로드 파일을 임시 파일로 저장하고, OpenAI Audio Transcriptions API로 전사합니다.
6. 전사된 텍스트를 OpenAI Responses API에 보내 회의 요약, 결정 사항, Action Item 등을 만듭니다.
7. 서버가 JSON으로 전사문과 요약문을 돌려주면 화면이 결과 영역에 표시합니다.

기동 순서는 파일 맨 아래의 `if __name__ == "__main__": main()`에서 시작됩니다.
`main()`은 uvicorn 서버를 실행하고, uvicorn은 이 파일의 `app` 객체(FastAPI 앱)를 찾아
HTTP 요청을 받을 준비를 합니다.
"""

from __future__ import annotations

import json
import logging
import tempfile
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI

# ---------------------------------------------------------------------------
# 경로와 기본 설정
# ---------------------------------------------------------------------------
# __file__은 현재 파일(src/realtime_stt_app.py)의 위치입니다.
# parent.parent를 사용해 프로젝트 루트(c:\study\python)를 기준 경로로 잡습니다.
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE_PATH = CONFIG_DIR / "openai_config.json"
LOG_FILE_PATH = LOG_DIR / "meeting_summary_app_error.log"

# OpenAI 음성 전사 API는 큰 파일을 보내면 시간이 오래 걸리고 실패 가능성도 커집니다.
# 이 예제는 초보자가 테스트하기 쉽게 25MB까지만 받도록 제한합니다.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}

# 설정 파일이 없을 때 자동 생성할 기본값입니다.
# api_key는 사용자가 직접 config/openai_config.json에 입력해야 합니다.
DEFAULT_CONFIG = {
    "api_key": "",
    "summary_model": "gpt-5.2",
    "transcription_model": "gpt-4o-mini-transcribe",
    "meeting_language": "ko",
}


def configure_logging() -> logging.Logger:
    """오류를 파일에 남기기 위한 logger를 준비합니다.

    서버에서 문제가 생겼을 때 브라우저에는 간단한 메시지만 보여주고,
    자세한 원인은 `logs/meeting_summary_app_error.log`에 기록합니다.
    """

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("meeting_summary_app")
    logger.setLevel(logging.INFO)

    # uvicorn reload 또는 테스트 과정에서 이 함수가 여러 번 호출될 수 있습니다.
    # 이미 handler가 있으면 중복 로그가 쌓이지 않도록 그대로 반환합니다.
    if logger.handlers:
        return logger

    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


logger = configure_logging()


def build_error_details(exc: Exception) -> str:
    """예외의 전체 traceback을 문자열로 바꿉니다."""

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def log_exception_to_file(
    *,
    title: str,
    request: Request | None = None,
    exc: Exception | None = None,
    extra_message: str | None = None,
) -> None:
    """요청 정보와 예외 정보를 로그 파일에 보기 좋게 남깁니다."""

    message_lines = [title]

    if request is not None:
        message_lines.append(f"method={request.method}")
        message_lines.append(f"url={request.url}")

    if extra_message:
        message_lines.append(extra_message)

    if exc is not None:
        message_lines.append(f"exception_type={type(exc).__name__}")
        message_lines.append(f"exception_message={exc}")
        message_lines.append(build_error_details(exc))

    logger.error("\n".join(message_lines))


def ensure_config_file() -> None:
    """설정 파일이 없으면 기본 설정 파일을 자동으로 만듭니다."""

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE_PATH.exists():
        return

    CONFIG_FILE_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def load_openai_config() -> dict[str, str]:
    """OpenAI 설정 파일을 읽고, 누락된 값은 DEFAULT_CONFIG로 채웁니다."""

    ensure_config_file()
    try:
        raw_config = json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI 설정 JSON 형식이 올바르지 않습니다: {CONFIG_FILE_PATH}") from exc

    config = {**DEFAULT_CONFIG, **raw_config}

    # JSON에는 숫자/불리언 등도 들어갈 수 있으므로 모든 값을 문자열로 통일합니다.
    return {key: str(value).strip() for key, value in config.items()}


class MeetingSummaryService:
    """OpenAI API 호출을 담당하는 서비스 클래스.

    FastAPI 라우터는 HTTP 요청/응답만 처리하고, 실제 업무 로직(STT와 요약)은
    이 클래스에 모아두었습니다. 이렇게 나누면 화면/API 코드와 AI 처리 코드를
    따로 이해할 수 있어 유지보수가 쉬워집니다.
    """

    def __init__(self, config_path: Path = CONFIG_FILE_PATH) -> None:
        self.config_path = config_path

    def _load_config(self) -> dict[str, str]:
        """현재 설정 파일을 읽습니다. 요청 때마다 읽어 서버 재시작 없이 설정 변경을 반영합니다."""

        return load_openai_config()

    def _get_client(self, config: dict[str, str]) -> OpenAI:
        """OpenAI API 클라이언트를 만듭니다."""

        api_key = config.get("api_key", "")
        if not api_key:
            raise RuntimeError(
                f"OpenAI API key가 없습니다. {self.config_path} 파일의 api_key에 값을 넣어주세요."
            )
        return OpenAI(api_key=api_key)

    def transcribe_audio(self, audio_path: Path, filename: str, prompt: str, language: str) -> str:
        """음성 파일을 텍스트로 변환합니다.

        `prompt`에는 참석자 이름, 자주 나오는 제품명, 프로젝트명처럼
        모델이 헷갈릴 수 있는 단어를 넣으면 전사 품질에 도움이 됩니다.
        """

        config = self._load_config()
        client = self._get_client(config)
        transcription_model = config.get("transcription_model") or DEFAULT_CONFIG["transcription_model"]

        with audio_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=transcription_model,
                file=audio_file,
                prompt=prompt or None,
                language=language or None,
            )

        return (getattr(transcription, "text", "") or "").strip()

    def summarize_meeting(
        self,
        *,
        transcript: str,
        source_name: str,
        meeting_title: str,
        summary_focus: str,
        language: str,
    ) -> str:
        """전사된 회의록 텍스트를 회의자료 형태로 요약합니다."""

        if not transcript:
            raise RuntimeError("전사 결과가 비어 있어 회의 요약을 만들 수 없습니다.")

        config = self._load_config()
        client = self._get_client(config)
        summary_model = config.get("summary_model") or DEFAULT_CONFIG["summary_model"]

        title = meeting_title.strip() or Path(source_name).stem or "회의"
        focus = summary_focus.strip() or "핵심 논의, 결정 사항, 후속 조치 목록을 중심으로 정리"
        output_language = language.strip() or config.get("meeting_language") or "ko"

        response = client.responses.create(
            model=summary_model,
            instructions=(
                "You are an expert meeting assistant. Summarize meeting transcripts into clear, "
                "actionable meeting materials. Use the requested output language. Do not invent facts."
            ),
            input=(
                f"Output language: {output_language}\n"
                f"Meeting title: {title}\n"
                f"Source file: {source_name}\n"
                f"Summary focus: {focus}\n\n"
                "Create meeting materials with these sections:\n"
                "1. 회의 개요\n"
                "2. 핵심 요약\n"
                "3. 주요 논의 내용\n"
                "4. 결정 사항\n"
                "5. 후속 조치(Action Items) - 담당자와 기한이 없으면 '미정'으로 표시\n"
                "6. 리스크 및 확인 필요 사항\n\n"
                f"Transcript:\n{transcript}"
            ),
        )

        summary = (getattr(response, "output_text", "") or "").strip()
        if not summary:
            raise RuntimeError("OpenAI 요약 응답이 비어 있습니다.")
        return summary

    def transcribe_and_summarize(
        self,
        *,
        audio_path: Path,
        source_name: str,
        transcription_prompt: str,
        meeting_title: str,
        summary_focus: str,
        language: str,
    ) -> dict[str, str]:
        """전사와 요약을 순서대로 실행합니다."""

        transcript = self.transcribe_audio(audio_path, source_name, transcription_prompt, language)
        summary = self.summarize_meeting(
            transcript=transcript,
            source_name=source_name,
            meeting_title=meeting_title,
            summary_focus=summary_focus,
            language=language,
        )
        return {"transcript": transcript, "summary": summary}


# 서비스 객체는 앱 시작 시 한 번 만들어두고 요청마다 재사용합니다.
summary_service = MeetingSummaryService()

# ---------------------------------------------------------------------------
# FastAPI 앱 생성과 화면 연결
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Meeting Recording Summary",
    description="Record meeting audio locally, upload it, and summarize it with the OpenAI API.",
    version="4.0.0",
)

# 브라우저가 /static/meeting_stt.css, /static/meeting_stt.js를 요청할 수 있게 연결합니다.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """사용자가 잘못된 파일을 올리는 등 예상 가능한 HTTP 오류를 JSON으로 응답합니다."""

    log_exception_to_file(
        title="HTTPException occurred",
        request=request,
        exc=exc,
        extra_message=f"status_code={exc.status_code} | detail={exc.detail}",
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """처리하지 못한 예외가 서버 밖으로 새지 않도록 마지막 안전망 역할을 합니다."""

    log_exception_to_file(title="Unhandled exception occurred", request=request, exc=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다. logs/meeting_summary_app_error.log 파일을 확인해 주세요."},
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """메인 화면을 렌더링합니다.

    Jinja2 템플릿에 모델명, 설정 파일 경로 같은 값을 넘기면
    `meeting_stt.html`에서 `{{ summary_model }}`처럼 사용할 수 있습니다.
    """

    ensure_config_file()
    config = load_openai_config()
    return templates.TemplateResponse(
        name="meeting_stt.html",
        context={
            "request": request,
            "page_title": "회의 녹음 요약",
            "summary_model": config.get("summary_model", DEFAULT_CONFIG["summary_model"]),
            "transcription_model": config.get("transcription_model", DEFAULT_CONFIG["transcription_model"]),
            "config_path": str(CONFIG_FILE_PATH),
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """서버 상태를 확인하는 API입니다.

    브라우저 화면에는 직접 쓰지 않지만, 테스트나 운영 점검에서
    "서버가 살아 있는지", "API 키가 설정되었는지" 빠르게 확인할 수 있습니다.
    """

    ensure_config_file()
    config = load_openai_config()
    return {
        "status": "ok",
        "mode": "record-upload-summary",
        "summary_model": config.get("summary_model"),
        "transcription_model": config.get("transcription_model"),
        "config_path": str(CONFIG_FILE_PATH),
        "api_key_configured": bool(config.get("api_key")),
    }


async def save_upload_to_temp_file(audio_file: UploadFile) -> Path:
    """업로드된 음성 파일을 임시 파일로 저장합니다.

    FastAPI의 UploadFile은 서버 메모리/임시 저장소에 있는 파일 같은 객체입니다.
    OpenAI SDK에는 실제 파일 경로에서 연 파일 객체를 넘기는 편이 단순하므로,
    여기서 OS 임시 폴더에 한 번 저장했다가 처리가 끝나면 삭제합니다.
    """

    suffix = Path(audio_file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"지원하지 않는 오디오 형식입니다. 지원 형식: {supported}")

    temp_path: Path | None = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)

            # 파일을 한 번에 읽지 않고 1MB씩 나누어 읽습니다.
            # 이렇게 하면 큰 파일도 메모리를 과하게 쓰지 않고 처리할 수 있습니다.
            while True:
                chunk = await audio_file.read(1024 * 1024)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="업로드 파일은 25MB 이하여야 합니다.")

                temp_file.write(chunk)
        return temp_path
    except Exception:
        # 저장 도중 오류가 나면 반쯤 만들어진 임시 파일을 지웁니다.
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


@app.post("/api/summarize-recording")
async def summarize_recording(
    audio_file: UploadFile = File(...),
    language: str = "ko",
    transcription_prompt: str = "",
    meeting_title: str = "",
    summary_focus: str = "",
) -> dict[str, str]:
    """화면에서 업로드한 녹음 파일을 전사하고 요약합니다.

    화면의 `FormData` 필드 이름과 이 함수의 매개변수 이름이 서로 맞아야 합니다.
    예를 들어 JavaScript에서 `formData.append("audio_file", file)`로 보냈기 때문에
    여기서도 `audio_file`이라는 이름으로 받습니다.
    """

    temp_path: Path | None = None
    source_name = audio_file.filename or "meeting-recording.webm"

    try:
        temp_path = await save_upload_to_temp_file(audio_file)

        # OpenAI SDK 호출은 동기 함수라 오래 걸릴 수 있습니다.
        # run_in_threadpool로 별도 작업 스레드에서 실행해 FastAPI 이벤트 루프가 막히지 않게 합니다.
        result = await run_in_threadpool(
            summary_service.transcribe_and_summarize,
            audio_path=temp_path,
            source_name=source_name,
            transcription_prompt=transcription_prompt.strip(),
            meeting_title=meeting_title.strip(),
            summary_focus=summary_focus.strip(),
            language=language.strip() or "ko",
        )
        return {
            "type": "meeting_summary",
            "source_name": source_name,
            "transcript": result["transcript"],
            "summary": result["summary"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_exception_to_file(
            title="Meeting recording summarization failed",
            exc=exc,
            extra_message=f"filename={source_name}",
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        # 성공/실패와 관계없이 임시 파일과 업로드 파일 핸들을 정리합니다.
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        await audio_file.close()


def main() -> None:
    """개발용 uvicorn 서버를 실행합니다."""

    import uvicorn

    uvicorn.run(
        "realtime_stt_app:app",
        host="127.0.0.1",
        port=8010,
        reload=False,
    )


if __name__ == "__main__":
    main()
