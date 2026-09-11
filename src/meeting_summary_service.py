from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from openai import OpenAI

def get_app_dir() -> Path:
    """실행 환경에 맞는 애플리케이션 폴더를 반환합니다."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_app_dir()
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE_PATH = CONFIG_DIR / "openai_config.json"
LOG_FILE_PATH = LOG_DIR / "meeting_summary_app_error.log"

TRANSCRIPTION_CHUNK_SECONDS = 5 * 60
DIRECT_SUMMARY_MAX_CHARS = 60_000
TRANSCRIPT_SUMMARY_CHUNK_CHARS = 40_000

DEFAULT_CONFIG = {
    "api_key": "",
    "summary_model": "",
    "transcription_model": "gpt-4o-mini-transcribe",
    "meeting_language": "ko",
}


def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meeting_summary_app")
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


def build_error_details(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def log_exception_to_file(*, title: str, request=None, exc: Exception | None = None, extra_message: str | None = None) -> None:
    message_lines = [title]
    if request is not None:
        message_lines.extend([f"method={request.method}", f"url={request.url}"])
    if extra_message:
        message_lines.append(extra_message)
    if exc is not None:
        message_lines.extend([
            f"exception_type={type(exc).__name__}",
            f"exception_message={exc}",
            build_error_details(exc),
        ])
    logger.error("\n".join(message_lines))


def ensure_config_file() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE_PATH.exists():
        CONFIG_FILE_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def load_openai_config() -> dict[str, str]:
    ensure_config_file()
    try:
        raw_config = json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI 설정 JSON 형식이 올바르지 않습니다: {CONFIG_FILE_PATH}") from exc
    config = {**DEFAULT_CONFIG, **raw_config}
    return {key: str(value).strip() for key, value in config.items()}


class MeetingSummaryService:
    def __init__(self, config_path: Path = CONFIG_FILE_PATH) -> None:
        self.config_path = config_path

    def _get_client(self, config: dict[str, str]) -> OpenAI:
        api_key = config.get("api_key", "")
        if not api_key:
            raise RuntimeError(f"OpenAI API key가 없습니다. {self.config_path} 파일의 api_key에 값을 넣어주세요.")
        return OpenAI(api_key=api_key)

    def list_models(self) -> list[str]:
        """OpenAI 계정에서 사용할 수 있는 모델 ID를 최신 목록으로 가져옵니다."""

        config = load_openai_config()
        client = self._get_client(config)
        models = client.models.list()
        model_ids = {
            str(getattr(model, "id", "")).strip()
            for model in models.data
        }
        return sorted(model_id for model_id in model_ids if model_id)

    def _resolve_model(self, *, config: dict[str, str], selected_model: str) -> str:
        """사용자 선택 모델 또는 OpenAI에서 조회한 첫 모델을 결정합니다."""

        if selected_model.strip():
            return selected_model.strip()
        configured_model = config.get("summary_model", "").strip()
        if configured_model:
            return configured_model
        available_models = self.list_models()
        if not available_models:
            raise RuntimeError("OpenAI에서 사용할 수 있는 모델을 찾지 못했습니다.")
        return available_models[0]

    def _find_ffmpeg(self) -> str:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path
        local_ffmpeg = BASE_DIR / "ffmpeg.exe"
        if local_ffmpeg.exists():
            return str(local_ffmpeg)
        raise RuntimeError("긴 오디오 처리를 위해 ffmpeg가 필요합니다. ffmpeg를 설치하거나 프로젝트 폴더에 넣어 주세요.")

    def _split_audio_for_transcription(self, audio_path: Path, output_dir: Path) -> list[Path]:
        command = [
            self._find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_path),
            "-vn", "-map", "0:a:0", "-f", "segment", "-segment_time", str(TRANSCRIPTION_CHUNK_SECONDS),
            "-reset_timestamps", "1", "-c:a", "libmp3lame", "-b:a", "64k",
            str(output_dir / "transcription_chunk_%03d.mp3"),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=60 * 30)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"오디오 분할 중 오류가 발생했습니다: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"오디오 파일을 분할하지 못했습니다. ffmpeg 오류: {detail}")
        chunk_paths = sorted(output_dir.glob("transcription_chunk_*.mp3"))
        if not chunk_paths:
            raise RuntimeError("전사할 오디오 조각 파일이 만들어지지 않았습니다.")
        return chunk_paths

    def _transcribe_audio_file(self, *, client: OpenAI, transcription_model: str, audio_path: Path, prompt: str, language: str) -> str:
        with audio_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=transcription_model, file=audio_file, prompt=prompt or None, language=language or None,
            )
        return (getattr(transcription, "text", "") or "").strip()

    def _split_text_by_chars(self, text: str, chunk_size: int) -> list[str]:
        chunks: list[str] = []
        current_lines: list[str] = []
        current_size = 0
        for line in text.splitlines():
            line_size = len(line) + 1
            if current_lines and current_size + line_size > chunk_size:
                chunks.append("\n".join(current_lines).strip())
                current_lines = []
                current_size = 0
            current_lines.append(line)
            current_size += line_size
        if current_lines:
            chunks.append("\n".join(current_lines).strip())
        return [chunk for chunk in chunks if chunk]

    def _request_meeting_summary(self, *, client: OpenAI, summary_model: str, source_name: str, title: str, focus: str, output_language: str, transcript: str, mode_note: str = "") -> str:
        response = client.responses.create(
            model=summary_model,
            instructions="You are an expert meeting assistant. Summarize meeting transcripts into clear, actionable meeting materials. Use the requested output language. Do not invent facts.",
            input=(
                f"Output language: {output_language}\nMeeting title: {title}\nSource file: {source_name}\n"
                f"Summary focus: {focus}\n{mode_note}\n\n"
                "Create meeting materials with these sections:\n"
                "1. 회의 개요\n2. 핵심 요약\n3. 주요 논의 내용\n4. 결정 사항\n"
                "5. 후속 조치(Action Items) - 담당자와 기한이 없으면 '미정'으로 표시\n"
                "6. 리스크 및 확인 필요 사항\n\n"
                f"Transcript:\n{transcript}"
            ),
        )
        summary = (getattr(response, "output_text", "") or "").strip()
        if not summary:
            raise RuntimeError("OpenAI 요약 응답이 비어 있습니다.")
        return summary

    def transcribe_audio(self, audio_path: Path, filename: str, prompt: str, language: str) -> str:
        config = load_openai_config()
        client = self._get_client(config)
        transcription_model = config.get("transcription_model") or DEFAULT_CONFIG["transcription_model"]
        with tempfile.TemporaryDirectory(prefix="meeting-audio-chunks-") as chunk_dir_name:
            chunk_paths = self._split_audio_for_transcription(audio_path, Path(chunk_dir_name))
            transcript_parts: list[str] = []
            for index, chunk_path in enumerate(chunk_paths, start=1):
                chunk_prompt = prompt
                if len(chunk_paths) > 1:
                    chunk_prompt = f"{prompt}\n\nThis is part {index} of {len(chunk_paths)} from the same meeting recording. Keep names and terms consistent with the previous and next parts.".strip()
                chunk_text = self._transcribe_audio_file(client=client, transcription_model=transcription_model, audio_path=chunk_path, prompt=chunk_prompt, language=language)
                if chunk_text:
                    transcript_parts.append(f"[Part {index}/{len(chunk_paths)}]\n{chunk_text}")
        return "\n\n".join(transcript_parts).strip()

    def summarize_meeting(self, *, transcript: str, source_name: str, meeting_title: str, summary_focus: str, language: str, model: str = "") -> str:
        """전사문을 OpenAI에 보내 회의자료 형식으로 요약합니다.

        `model`이 비어 있으면 설정 파일의 기본 요약 모델을 사용합니다.
        값이 있으면 화면에서 사용자가 선택한 모델을 우선 사용합니다.
        """
        if not transcript:
            raise RuntimeError("전사 결과가 비어 있어 회의 요약을 만들 수 없습니다.")
        config = load_openai_config()
        client = self._get_client(config)
        # 우선순위: 화면에서 선택한 모델 -> 설정 파일의 모델 -> OpenAI 조회 결과의 첫 모델
        summary_model = self._resolve_model(config=config, selected_model=model)
        title = meeting_title.strip() or Path(source_name).stem or "회의"
        focus = summary_focus.strip() or "핵심 논의, 결정 사항, 후속 조치 목록을 중심으로 정리"
        output_language = language.strip() or config.get("meeting_language") or "ko"
        if len(transcript) <= DIRECT_SUMMARY_MAX_CHARS:
            return self._request_meeting_summary(client=client, summary_model=summary_model, source_name=source_name, title=title, focus=focus, output_language=output_language, transcript=transcript)
        transcript_chunks = self._split_text_by_chars(transcript, TRANSCRIPT_SUMMARY_CHUNK_CHARS)
        partial_summaries: list[str] = []
        for index, chunk in enumerate(transcript_chunks, start=1):
            partial_summary = self._request_meeting_summary(
                client=client, summary_model=summary_model, source_name=f"{source_name} part {index}/{len(transcript_chunks)}", title=title,
                focus=f"This is one part of a long meeting transcript. Extract only facts, decisions, risks, and action items from part {index}/{len(transcript_chunks)}. {focus}",
                output_language=output_language, transcript=chunk,
                mode_note=f"Long transcript partial summarization: part {index}/{len(transcript_chunks)}.",
            )
            partial_summaries.append(f"[Partial summary {index}/{len(transcript_chunks)}]\n{partial_summary}")
        return self._request_meeting_summary(
            client=client, summary_model=summary_model, source_name=source_name, title=title,
            focus=f"{focus} Combine the partial summaries into one final meeting material without duplication.",
            output_language=output_language, transcript="\n\n".join(partial_summaries),
            mode_note="The transcript below contains partial summaries of a long meeting transcript.",
        )

    def chat(self, *, message: str, context: str = "", model: str = "", language: str = "ko") -> str:
        """회의 요약/전사문을 참고해 사용자의 질문에 답합니다.

        이 함수는 화면 자체를 알지 못합니다. 질문과 회의 문맥을 문자열로 받아
        OpenAI에 전달하고, 답변 문자열만 반환하므로 Windows 화면과 웹 화면에서
        같은 기능을 재사용할 수 있습니다.
        """

        if not message.strip():
            raise RuntimeError("채팅 질문을 입력해 주세요.")

        config = load_openai_config()
        client = self._get_client(config)
        # 채팅도 요약과 같은 모델 선택 상자를 사용합니다.
        selected_model = self._resolve_model(config=config, selected_model=model)
        response = client.responses.create(
            model=selected_model,
            instructions=(
                "You are a helpful meeting assistant. Answer using the meeting context when provided. "
                "Use the requested language. Do not invent facts; clearly say when the context does not contain the answer."
            ),
            input=(
                f"Output language: {language.strip() or 'ko'}\n"
                f"Meeting context:\n{context.strip() or '(No meeting context provided.)'}\n\n"
                f"User question:\n{message.strip()}"
            ),
        )
        answer = (getattr(response, "output_text", "") or "").strip()
        if not answer:
            raise RuntimeError("OpenAI 채팅 응답이 비어 있습니다.")
        return answer

    def transcribe_and_summarize(self, *, audio_path: Path, source_name: str, transcription_prompt: str, meeting_title: str, summary_focus: str, language: str, model: str = "") -> dict[str, str]:
        """음성 전사와 회의 요약을 순서대로 실행합니다."""

        # 먼저 음성을 글자로 바꾸고, 그 결과를 요약 함수에 넘깁니다.
        # 두 작업을 하나의 메서드로 묶어 화면에서는 한 번만 호출하면 됩니다.
        transcript = self.transcribe_audio(audio_path, source_name, transcription_prompt, language)
        summary = self.summarize_meeting(transcript=transcript, source_name=source_name, meeting_title=meeting_title, summary_focus=summary_focus, language=language, model=model)
        return {"transcript": transcript, "summary": summary}
