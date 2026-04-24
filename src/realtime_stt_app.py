"""
프로그램 흐름 설명
1. 사용자가 브라우저에서 이 페이지를 열면 FastAPI가 HTML, CSS, JavaScript를 내려줍니다.
2. 브라우저는 WebSocket으로 서버에 연결하고, 언어/프롬프트/Whisper 모델 설정을 보냅니다.
3. 실시간 녹음을 시작하면 브라우저는 짧은 음성 청크를 서버로 보내고,
   서버는 Whisper로 전사한 뒤 결과를 다시 브라우저로 돌려줍니다.
4. 사용자가 음성 파일을 업로드하면 서버는 임시 파일로 저장한 뒤 Whisper로 전사하고,
   전사 결과를 JSON으로 반환합니다.
5. 프로그램은 오류가 나면 로그 파일에 자세한 내용을 남겨서 초보자도 원인을 추적할 수 있게 돕습니다.

정상 동작에 필요한 설치 항목
1. Python
   - 권장: Python 3.10 ~ 3.12
   - 현재 코드 구조상 Windows에서도 동작하도록 작성되어 있습니다.
2. Python 모듈
   - fastapi: 웹 서버와 API 라우팅
   - uvicorn: FastAPI 실행 서버
   - openai-whisper: 음성 전사 처리
   - jinja2: HTML 템플릿 렌더링
   - python-multipart: 업로드 파일 처리
   - torch: Whisper가 내부적으로 사용하는 딥러닝 엔진
3. 외부 프로그램
   - ffmpeg: mp3, webm, wav 같은 음성 파일을 Whisper가 읽을 수 있게 변환
4. 브라우저
   - 마이크 권한과 MediaRecorder를 지원하는 최신 Chrome / Edge 권장

설치 방법 예시
1. 가상환경 생성
   - python -m venv venv
2. 가상환경 활성화
   - Windows PowerShell: .\venv\Scripts\Activate.ps1
3. pip 업그레이드
   - python -m pip install --upgrade pip
4. Python 모듈 설치
   - pip install fastapi uvicorn openai-whisper jinja2 python-multipart
5. torch 설치
   - CPU 기준 예시: pip install torch torchvision torchaudio
   - GPU 환경이면 PyTorch 공식 사이트의 설치 명령을 사용하는 편이 안전합니다.
6. ffmpeg 설치
   - ffmpeg.exe가 PATH에 잡히도록 설치하거나
   - FFMPEG_PATH, FFMPEG_EXE, FFMPEG_BIN_DIR 환경변수로 경로를 지정할 수 있습니다.

기동 방법 예시
1. 프로젝트 루트로 이동
   - cd c:\study\python
2. 가상환경 활성화
   - .\venv\Scripts\Activate.ps1
3. 서버 실행
   - python src\realtime_stt_app.py
   - 또는 uvicorn realtime_stt_app:app --host 127.0.0.1 --port 8010 --reload
4. 브라우저 접속
   - http://127.0.0.1:8010

문제 발생 시 확인할 것
1. ffmpeg가 없으면 Whisper가 오디오 파일을 읽지 못합니다.
2. python-multipart가 없으면 파일 업로드 API가 실패할 수 있습니다.
3. torch 또는 whisper 설치가 잘못되면 모델 로딩 단계에서 오류가 납니다.
4. 오류 상세 내용은 logs/realtime_stt_app_error.log 파일에 기록됩니다.

추가로 조절할 수 있는 서버 설정값
1. MAX_CONCURRENT_WS_CLIENTS
   - 동시에 접속할 수 있는 WebSocket 사용자 수
   - 예: 5
2. WEBSOCKET_RECEIVE_TIMEOUT_SECONDS
   - 이 시간 동안 클라이언트 메시지가 없으면 서버가 연결을 종료합니다.
   - 예: 120
3. UVICORN_WS_PING_INTERVAL_SECONDS
   - uvicorn이 ping 프레임을 보내는 간격
4. UVICORN_WS_PING_TIMEOUT_SECONDS
   - ping 응답을 기다리는 제한 시간
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import traceback
from pathlib import Path
from threading import Lock, RLock
from typing import Any

import whisper
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE_PATH = LOG_DIR / "realtime_stt_app_error.log"

WINDOWS_FFMPEG_CANDIDATES = (
    BASE_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    BASE_DIR / "ffmpeg" / "bin" / "ffmpeg.exe",
    BASE_DIR / "bin" / "ffmpeg.exe",
)

SUPPORTED_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large")
DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium").strip().lower() or "medium"


def read_int_env(env_name: str, default: int, minimum: int = 1) -> int:
    """정수 환경변수를 읽고, 잘못된 값이 오면 기본값을 사용합니다."""
    raw_value = os.environ.get(env_name, str(default)).strip()
    try:
        return max(minimum, int(raw_value))
    except ValueError:
        return default


def read_float_env(env_name: str, default: float, minimum: float = 0.1) -> float:
    """실수 환경변수를 읽고, 잘못된 값이 오면 기본값을 사용합니다."""
    raw_value = os.environ.get(env_name, str(default)).strip()
    try:
        return max(minimum, float(raw_value))
    except ValueError:
        return default


MAX_CONCURRENT_WS_CLIENTS = read_int_env("MAX_CONCURRENT_WS_CLIENTS", 5, minimum=1)
WEBSOCKET_RECEIVE_TIMEOUT_SECONDS = read_float_env("WEBSOCKET_RECEIVE_TIMEOUT_SECONDS", 120.0, minimum=1.0)
UVICORN_WS_PING_INTERVAL_SECONDS = read_float_env("UVICORN_WS_PING_INTERVAL_SECONDS", 20.0, minimum=1.0)
UVICORN_WS_PING_TIMEOUT_SECONDS = read_float_env("UVICORN_WS_PING_TIMEOUT_SECONDS", 20.0, minimum=1.0)


def configure_logging() -> logging.Logger:
    """오류를 파일로 남기기 위한 logger를 준비합니다."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("realtime_stt_app")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


logger = configure_logging()
active_ws_clients = 0
active_ws_clients_lock = asyncio.Lock()


def ensure_ffmpeg_available() -> str:
    """Whisper가 오디오를 읽을 수 있도록 ffmpeg 실행 파일을 찾습니다."""
    configured_candidates = [
        os.environ.get("FFMPEG_PATH"),
        os.environ.get("FFMPEG_EXE"),
    ]

    configured_bin_dir = os.environ.get("FFMPEG_BIN_DIR")
    if configured_bin_dir:
        configured_candidates.append(str(Path(configured_bin_dir) / "ffmpeg.exe"))

    for candidate in configured_candidates:
        if candidate and Path(candidate).is_file():
            ffmpeg_path = str(Path(candidate).resolve())
            break
    else:
        ffmpeg_path = shutil.which("ffmpeg") or ""
        if not ffmpeg_path:
            for candidate in WINDOWS_FFMPEG_CANDIDATES:
                if candidate.is_file():
                    ffmpeg_path = str(candidate.resolve())
                    break

    if not ffmpeg_path:
        raise RuntimeError(
            "ffmpeg executable was not found. Install FFmpeg and add it to PATH, "
            "or set FFMPEG_PATH/FFMPEG_EXE/FFMPEG_BIN_DIR to its location."
        )

    ffmpeg_dir = str(Path(ffmpeg_path).resolve().parent)
    current_path = os.environ.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    if ffmpeg_dir not in path_entries:
        os.environ["PATH"] = os.pathsep.join([ffmpeg_dir, *path_entries]) if path_entries else ffmpeg_dir

    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", ffmpeg_path)
    return ffmpeg_path


def build_error_details(exc: Exception) -> str:
    """traceback을 하나의 문자열로 합쳐서 로그와 화면에 함께 쓰기 쉽게 만듭니다."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def log_exception_to_file(
    *,
    title: str,
    request: Request | None = None,
    websocket: WebSocket | None = None,
    exc: Exception | None = None,
    extra_message: str | None = None,
) -> None:
    """오류 제목, 요청 정보, traceback을 모두 로그 파일에 남깁니다."""
    message_lines = [title]

    if request is not None:
        message_lines.append(f"method={request.method}")
        message_lines.append(f"url={request.url}")

    if websocket is not None:
        message_lines.append(f"websocket_url={websocket.url}")
        message_lines.append(f"client={websocket.client}")

    if extra_message:
        message_lines.append(extra_message)

    if exc is not None:
        message_lines.append(f"exception_type={type(exc).__name__}")
        message_lines.append(f"exception_message={exc}")
        message_lines.append(build_error_details(exc))

    logger.error("\n".join(message_lines))


class WhisperService:
    """선택된 Whisper 모델을 필요할 때만 메모리에 올리고 재사용합니다."""

    def __init__(self, model_name: str = DEFAULT_WHISPER_MODEL) -> None:
        self.model_name = self.validate_model_name(model_name)
        self._models: dict[str, Any] = {}
        self._model_locks: dict[str, Lock] = {}
        self._models_lock = RLock()
        self._ffmpeg_path: str | None = None

    def validate_model_name(self, model_name: str | None) -> str:
        """사용자가 고른 모델명이 지원 목록 안에 있는지 확인합니다."""
        resolved = (model_name or self.model_name).strip().lower()
        if resolved not in SUPPORTED_WHISPER_MODELS:
            raise ValueError(
                f"Unsupported Whisper model: {resolved}. "
                f"Available models: {', '.join(SUPPORTED_WHISPER_MODELS)}"
            )
        return resolved

    def _get_model_lock(self, model_name: str) -> Lock:
        """모델별 잠금을 따로 두어 동시에 여러 모델을 안전하게 로드합니다."""
        with self._models_lock:
            return self._model_locks.setdefault(model_name, Lock())

    def _get_model(self, model_name: str | None = None) -> Any:
        """아직 로드되지 않은 Whisper 모델이면 이 시점에 로드합니다."""
        resolved_model_name = self.validate_model_name(model_name)
        if resolved_model_name not in self._models:
            model_lock = self._get_model_lock(resolved_model_name)
            with model_lock:
                if resolved_model_name not in self._models:
                    self._models[resolved_model_name] = whisper.load_model(resolved_model_name)
        return self._models[resolved_model_name]

    def transcribe_file(
        self,
        audio_path: str,
        language: str | None,
        prompt: str | None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """오디오 파일 하나를 Whisper로 전사하고 결과 dict를 돌려줍니다."""
        if self._ffmpeg_path is None:
            self._ffmpeg_path = ensure_ffmpeg_available()

        resolved_model_name = self.validate_model_name(model_name)
        model = self._get_model(resolved_model_name)
        options: dict[str, Any] = {"fp16": False}

        if language:
            options["language"] = language
        if prompt:
            options["initial_prompt"] = prompt

        result = model.transcribe(audio_path, **options)
        result["model"] = resolved_model_name
        return result


stt_service = WhisperService(model_name=DEFAULT_WHISPER_MODEL)

app = FastAPI(
    title="Meeting Realtime STT",
    description="FastAPI, HTML, Whisper, WebSocket based meeting transcription web app",
    version="3.2.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def send_ws_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """WebSocket JSON 전송을 한 곳에서 처리합니다."""
    await websocket.send_text(json.dumps(payload, ensure_ascii=False))


async def send_ws_error(websocket: WebSocket, title: str, exc: Exception, extra_message: str = "") -> None:
    """브라우저가 바로 볼 수 있도록 오류 상세 내용을 WebSocket으로 전송합니다."""
    await send_ws_json(
        websocket,
        {
            "type": "error",
            "title": title,
            "message": str(exc),
            "detail": build_error_details(exc),
            "extra": extra_message,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


async def try_acquire_ws_client_slot() -> bool:
    """동시 접속자 수 제한을 넘지 않았을 때만 새 WebSocket 접속을 허용합니다."""
    global active_ws_clients

    async with active_ws_clients_lock:
        if active_ws_clients >= MAX_CONCURRENT_WS_CLIENTS:
            return False
        active_ws_clients += 1
        return True


async def release_ws_client_slot() -> None:
    """WebSocket 연결이 끝나면 사용 중인 접속 슬롯을 반납합니다."""
    global active_ws_clients

    async with active_ws_clients_lock:
        active_ws_clients = max(0, active_ws_clients - 1)


def build_segments(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Whisper segment 중 텍스트가 있는 항목만 화면용으로 정리합니다."""
    return [
        {
            "start": round(float(segment.get("start", 0.0)), 2),
            "end": round(float(segment.get("end", 0.0)), 2),
            "text": (segment.get("text") or "").strip(),
        }
        for segment in result.get("segments", [])
        if (segment.get("text") or "").strip()
    ]


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTPException이 나면 로그를 남기고 JSON 형태로 응답합니다."""
    log_exception_to_file(
        title="HTTPException occurred",
        request=request,
        exc=exc,
        extra_message=f"status_code={exc.status_code} | detail={exc.detail}",
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """처리되지 않은 예외를 로그로 남기고 500 응답을 돌려줍니다."""
    log_exception_to_file(title="Unhandled exception occurred", request=request, exc=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다. logs/realtime_stt_app_error.log 를 확인해 주세요."},
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """메인 HTML 화면을 반환합니다."""
    return templates.TemplateResponse(
        name="meeting_stt.html",
        context={
            "request": request,
            "page_title": "회의 실시간 STT",
            "model_name": stt_service.model_name,
            "supported_models": SUPPORTED_WHISPER_MODELS,
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """서버가 살아 있는지 점검하는 간단한 API입니다."""
    return {
        "status": "ok",
        "model": stt_service.model_name,
        "transport": "websocket+upload",
        "max_concurrent_ws_clients": MAX_CONCURRENT_WS_CLIENTS,
        "websocket_receive_timeout_seconds": WEBSOCKET_RECEIVE_TIMEOUT_SECONDS,
        "uvicorn_ws_ping_interval_seconds": UVICORN_WS_PING_INTERVAL_SECONDS,
        "uvicorn_ws_ping_timeout_seconds": UVICORN_WS_PING_TIMEOUT_SECONDS,
        "active_ws_clients": active_ws_clients,
    }


@app.post("/api/transcribe-file")
async def transcribe_uploaded_file(
    audio_file: UploadFile = File(...),
    language: str = "ko",
    prompt: str = "",
    model_name: str = DEFAULT_WHISPER_MODEL,
) -> dict[str, Any]:
    """업로드된 파일을 Whisper로 전사해 JSON 형태로 돌려줍니다."""
    temp_path: Path | None = None
    resolved_model_name = stt_service.validate_model_name(model_name)
    suffix = Path(audio_file.filename or "").suffix or ".webm"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(await audio_file.read())

        result = await asyncio.to_thread(
            stt_service.transcribe_file,
            str(temp_path),
            language.strip() or "ko",
            prompt.strip(),
            resolved_model_name,
        )
        return {
            "type": "transcript_batch",
            "text": (result.get("text") or "").strip(),
            "language": result.get("language") or language,
            "model": result.get("model") or resolved_model_name,
            "source_name": audio_file.filename or temp_path.name,
            "segments": build_segments(result),
        }
    except Exception as exc:
        log_exception_to_file(
            title="Uploaded audio transcription failed",
            exc=exc,
            extra_message=f"filename={audio_file.filename} | model_name={resolved_model_name}",
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        await audio_file.close()


@app.websocket("/ws/transcribe")
async def websocket_transcribe(websocket: WebSocket) -> None:
    """실시간 음성 청크를 받아 Whisper로 전사한 뒤 바로 다시 돌려줍니다."""
    slot_acquired = await try_acquire_ws_client_slot()
    await websocket.accept()

    if not slot_acquired:
        await send_ws_json(
            websocket,
            {
                "type": "error",
                "title": "동시 접속자 수 초과",
                "message": (
                    f"현재 허용된 동시 접속자 수({MAX_CONCURRENT_WS_CLIENTS})를 초과했습니다. "
                    "잠시 후 다시 시도해 주세요."
                ),
                "detail": "",
                "extra": "",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        await websocket.close(code=1013, reason="Too many concurrent websocket clients")
        return

    language = "ko"
    prompt = ""
    model_name = stt_service.model_name
    chunk_index = 0

    await send_ws_json(
        websocket,
        {
            "type": "ready",
            "message": "WebSocket 연결이 완료되었습니다.",
            "model": model_name,
            "supported_models": list(SUPPORTED_WHISPER_MODELS),
            "receive_timeout_seconds": WEBSOCKET_RECEIVE_TIMEOUT_SECONDS,
            "max_concurrent_clients": MAX_CONCURRENT_WS_CLIENTS,
        },
    )

    try:
        while True:
            try:
                # 정해진 시간 동안 메시지가 없으면 유휴 연결로 보고 종료합니다.
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=WEBSOCKET_RECEIVE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as exc:
                log_exception_to_file(
                    title="WebSocket receive timeout",
                    websocket=websocket,
                    exc=exc,
                    extra_message=f"timeout_seconds={WEBSOCKET_RECEIVE_TIMEOUT_SECONDS}",
                )
                await send_ws_json(
                    websocket,
                    {
                        "type": "error",
                        "title": "WebSocket receive timeout",
                        "message": (
                            f"The connection was closed after "
                            f"{WEBSOCKET_RECEIVE_TIMEOUT_SECONDS} seconds "
                            "without any incoming message."
                        ),
                        "detail": "",
                        "extra": "",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                await websocket.close(code=1000, reason="WebSocket receive timeout")
                break

            if message.get("type") == "websocket.disconnect":
                break

            text_data = message.get("text")
            bytes_data = message.get("bytes")

            if text_data:
                try:
                    payload = json.loads(text_data)
                except json.JSONDecodeError as exc:
                    log_exception_to_file(
                        title="WebSocket JSON parse failed",
                        websocket=websocket,
                        exc=exc,
                        extra_message=f"raw_text={text_data}",
                    )
                    await send_ws_error(websocket, "설정 메시지 해석 실패", exc, text_data)
                    continue

                message_type = payload.get("type", "")

                if message_type == "config":
                    try:
                        language = str(payload.get("language") or "ko").strip() or "ko"
                        prompt = str(payload.get("prompt") or "").strip()
                        model_name = stt_service.validate_model_name(str(payload.get("model_name") or model_name))
                    except Exception as exc:
                        await send_ws_error(websocket, "모델 설정 실패", exc)
                        continue

                    await send_ws_json(
                        websocket,
                        {
                            "type": "config_ack",
                            "language": language,
                            "prompt": prompt,
                            "model": model_name,
                        },
                    )
                    continue

                if message_type == "ping":
                    await send_ws_json(websocket, {"type": "pong"})
                    continue

                await send_ws_json(
                    websocket,
                    {"type": "info", "message": f"지원하지 않는 텍스트 메시지입니다: {message_type}"},
                )
                continue

            if bytes_data:
                chunk_index += 1
                started_at = time.perf_counter()
                temp_path: Path | None = None

                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
                        temp_path = Path(temp_file.name)
                        temp_file.write(bytes_data)

                    result = await asyncio.to_thread(
                        stt_service.transcribe_file,
                        str(temp_path),
                        language,
                        prompt,
                        model_name,
                    )

                    await send_ws_json(
                        websocket,
                        {
                            "type": "transcript",
                            "chunk_index": chunk_index,
                            "text": (result.get("text") or "").strip(),
                            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            "language": result.get("language") or language,
                            "model": result.get("model") or model_name,
                            "segments": build_segments(result),
                        },
                    )
                except Exception as exc:
                    log_exception_to_file(
                        title="Whisper transcription failed over WebSocket",
                        websocket=websocket,
                        exc=exc,
                        extra_message=f"chunk_index={chunk_index} | temp_path={temp_path} | model_name={model_name}",
                    )
                    await send_ws_error(
                        websocket,
                        "WebSocket STT 처리 실패",
                        exc,
                        f"chunk_index={chunk_index} | temp_path={temp_path} | model_name={model_name}",
                    )
                finally:
                    if temp_path and temp_path.exists():
                        temp_path.unlink(missing_ok=True)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", websocket.client)
    except Exception as exc:
        log_exception_to_file(title="Unhandled WebSocket exception", websocket=websocket, exc=exc)
        try:
            await send_ws_error(websocket, "WebSocket 서버 내부 오류", exc)
        except Exception:
            pass
    finally:
        if slot_acquired:
            await release_ws_client_slot()


def main() -> None:
    """uvicorn 서버를 직접 실행할 때 사용하는 진입점입니다."""
    import uvicorn

    uvicorn.run(
        "realtime_stt_app:app",
        host="127.0.0.1",
        port=8010,
        reload=True,
        ws_ping_interval=UVICORN_WS_PING_INTERVAL_SECONDS,
        ws_ping_timeout=UVICORN_WS_PING_TIMEOUT_SECONDS,
    )


if __name__ == "__main__":
    main()
