from __future__ import annotations

import sys
import threading
import wave
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QComboBox,
    QSplitter,
    QStyleFactory,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from meeting_summary_service import MeetingSummaryService

DEFAULT_SUMMARY_MODEL = "gpt-5.4"
INPUT_HEIGHT = 32


class RecordingThread(QThread):
    saved = Signal(str)
    failed = Signal(str)

    def __init__(self, output_path: Path, sample_rate: int = 16000) -> None:
        super().__init__()
        self.output_path = output_path
        self.sample_rate = sample_rate
        self._stop_event = threading.Event()
        self._frames: list[bytes] = []

    def run(self) -> None:
        try:
            def capture_callback(indata, _frames, _time, status) -> None:
                if status:
                    self.failed.emit(str(status))
                self._frames.append(bytes(indata))

            with sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                callback=capture_callback,
            ):
                while not self._stop_event.wait(0.1):
                    pass

            if not self._frames:
                raise RuntimeError("녹음된 음성이 없습니다.")

            with wave.open(str(self.output_path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(self.sample_rate)
                audio_file.writeframes(b"".join(self._frames))
            self.saved.emit(str(self.output_path))
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self) -> None:
        self._stop_event.set()


class ProcessingThread(QThread):
    """긴 전사/요약 작업을 화면과 분리해 실행하는 작업 스레드입니다.

    OpenAI 요청을 화면 스레드에서 직접 실행하면 응답을 기다리는 동안 창이
    멈춘 것처럼 보입니다. QThread에서 실행한 뒤 Signal로 결과만 화면에 전달합니다.
    """
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, audio_path: Path, values: dict[str, str]) -> None:
        super().__init__()
        self.audio_path = audio_path
        self.values = values

    def run(self) -> None:
        try:
            result = MeetingSummaryService().transcribe_and_summarize(
                audio_path=self.audio_path,
                source_name=self.audio_path.name,
                transcription_prompt=self.values["prompt"],
                meeting_title=self.values["title"],
                summary_focus=self.values["focus"],
                language=self.values["language"] or "ko",
                model=self.values["model"],
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelListThread(QThread):
    """OpenAI에 모델 목록을 요청하는 백그라운드 스레드입니다."""

    completed = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(MeetingSummaryService().list_models())
        except Exception as exc:
            self.failed.emit(str(exc))


class ChatThread(QThread):
    """채팅 요청을 별도 스레드에서 처리해 Windows 창이 멈추지 않게 합니다."""
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, message: str, context: str, model: str, language: str) -> None:
        super().__init__()
        self.message = message
        self.context = context
        self.model = model
        self.language = language

    def run(self) -> None:
        try:
            # 실제 OpenAI 호출은 이 백그라운드 스레드에서 실행됩니다.
            answer = MeetingSummaryService().chat(
                message=self.message,
                context=self.context,
                model=self.model,
                language=self.language or "ko",
            )
            self.completed.emit(answer)
        except Exception as exc:
            self.failed.emit(str(exc))


class MeetingSummaryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.recording_thread: RecordingThread | None = None
        self.processing_thread: ProcessingThread | None = None
        self.chat_thread: ChatThread | None = None
        self.model_list_thread: ModelListThread | None = None
        self.chat_markdown = ""
        self.selected_audio_path: Path | None = None
        self.setWindowTitle("회의 녹음 요약")
        # 가로:세로가 16:9가 되도록 프로그램을 처음 열 때 사용할 크기입니다.
        # 사용자는 이후 창을 자유롭게 확대하거나 축소할 수 있습니다.
        # 초기 세로 공간을 조금 더 확보해 제목, 회의 정보, 결과 영역이 잘리지 않게 합니다.
        self.resize(1280, 750)
        self.setMinimumSize(1050, 650)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel("회의 녹음 요약")
        title.setObjectName("pageTitle")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        root.addWidget(title)

        subtitle = QLabel("마이크로 녹음하거나 오디오 파일을 열어 전사문과 회의자료를 생성합니다.")
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(subtitle)

        options = QGroupBox("회의 정보")
        options.setObjectName("sectionCard")
        fields = QGridLayout(options)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("예: 주간 운영 회의")
        self.title_input.setFixedHeight(INPUT_HEIGHT)
        self.language_input = QLineEdit("ko")
        self.language_input.setMaximumWidth(100)
        self.language_input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.model_input = QComboBox()
        self.model_input.addItem("OpenAI 모델을 불러오는 중...")
        self.model_input.setEnabled(False)
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("참석자, 프로젝트명, 제품명 등")
        self.prompt_input.setFixedHeight(INPUT_HEIGHT)
        self.prompt_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.focus_input = QLineEdit()
        self.focus_input.setPlaceholderText("예: 결정 사항과 담당자별 후속 조치 중심")
        self.focus_input.setFixedHeight(INPUT_HEIGHT)
        self.focus_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title_label = QLabel("회의 제목")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fields.addWidget(title_label, 0, 0)
        fields.addWidget(self.title_input, 0, 1, 1, 3)
        language_label = QLabel("언어 코드")
        language_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fields.addWidget(language_label, 0, 4)
        fields.addWidget(self.language_input, 0, 5)
        model_label = QLabel("OpenAI 모델")
        model_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fields.addWidget(model_label, 0, 6)
        fields.addWidget(self.model_input, 0, 7)
        # 제목과 전사 힌트는 같은 폭으로, 요약 관점은 레이블 바로 옆에서 넓게 배치합니다.
        prompt_label = QLabel("전사 힌트")
        prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fields.addWidget(prompt_label, 1, 0)
        fields.addWidget(self.prompt_input, 1, 1, 1, 3)
        focus_label = QLabel("요약 관점")
        focus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fields.addWidget(focus_label, 1, 4)
        fields.addWidget(self.focus_input, 1, 5, 1, 3)
        options.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addWidget(options, 4)

        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        self.record_button = QPushButton("녹음 시작")
        self.record_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("녹음 중지")
        self.stop_button.setEnabled(False)
        self.open_button = QPushButton("오디오 파일 열기")
        self.process_button = QPushButton("전사 및 요약")
        self.process_button.setObjectName("primaryButton")
        self.save_button = QPushButton("결과 저장")
        self.save_button.setEnabled(False)
        action_buttons = (self.record_button, self.stop_button, self.open_button, self.process_button, self.save_button)
        for index, button in enumerate(action_buttons):
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMaximumWidth(145)
            actions.addWidget(button, index // 2, index % 2)
        controls.addLayout(actions, 1)
        root.addLayout(controls)

        self.file_label = QLabel("선택된 오디오 파일 없음")
        root.addWidget(self.file_label)

        results_panel = QWidget()
        results_panel.setMinimumHeight(0)
        results = QHBoxLayout(results_panel)
        results.setSpacing(11)
        summary_box = QGroupBox("회의자료 요약")
        summary_box.setObjectName("resultCard")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(16, 18, 16, 16)
        summary_header = QHBoxLayout()
        summary_hint = QLabel("AI가 정리한 회의 핵심 내용")
        summary_hint.setObjectName("cardHint")
        self.toggle_transcript_button = QPushButton("원문 보기")
        self.clear_summary_button = QPushButton("Clear")
        self.clear_summary_button.setObjectName("clearButton")
        self.clear_summary_button.setToolTip("회의자료 요약 내용을 지웁니다.")
        summary_header.addWidget(summary_hint)
        summary_header.addStretch()
        summary_header.addWidget(self.toggle_transcript_button)
        summary_header.addWidget(self.clear_summary_button)
        summary_layout.addLayout(summary_header)
        # QTextBrowser는 일반 텍스트뿐 아니라 Markdown 문법도 제목/목록으로 렌더링합니다.
        self.summary_output = QTextBrowser()
        self.summary_output.setReadOnly(True)
        self.summary_output.setPlaceholderText("회의자료 요약 결과가 여기에 표시됩니다.")
        summary_layout.addWidget(self.summary_output)
        self.transcript_box = QGroupBox("원문 전사")
        self.transcript_box.setObjectName("resultCard")
        transcript_layout = QVBoxLayout(self.transcript_box)
        transcript_layout.setContentsMargins(16, 18, 16, 16)
        transcript_header = QHBoxLayout()
        transcript_hint = QLabel("회의 음성을 문자로 변환한 원문")
        transcript_hint.setObjectName("cardHint")
        self.clear_transcript_button = QPushButton("Clear")
        self.clear_transcript_button.setObjectName("clearButton")
        self.clear_transcript_button.setToolTip("원문 전사 내용을 지웁니다.")
        transcript_header.addWidget(transcript_hint)
        transcript_header.addStretch()
        transcript_header.addWidget(self.clear_transcript_button)
        transcript_layout.addLayout(transcript_header)
        self.transcript_output = QPlainTextEdit()
        self.transcript_output.setReadOnly(True)
        self.transcript_output.setPlaceholderText("원문 전사 결과가 여기에 표시됩니다.")
        transcript_layout.addWidget(self.transcript_output)
        self.transcript_box.setVisible(False)
        results.addWidget(summary_box)
        results.addWidget(self.transcript_box)
        chat_box = QGroupBox("회의 내용과 채팅")
        chat_box.setObjectName("resultCard")
        chat_box.setMinimumHeight(0)
        chat_layout = QVBoxLayout(chat_box)
        chat_layout.setContentsMargins(16, 18, 16, 16)
        chat_header = QHBoxLayout()
        chat_hint = QLabel("요약과 전사 내용을 바탕으로 AI에게 질문하세요")
        chat_hint.setObjectName("cardHint")
        self.clear_chat_button = QPushButton("Clear")
        self.clear_chat_button.setObjectName("clearButton")
        self.clear_chat_button.setToolTip("채팅 질문과 답변을 모두 지웁니다.")
        chat_header.addWidget(chat_hint)
        chat_header.addStretch()
        chat_header.addWidget(self.clear_chat_button)
        chat_layout.addLayout(chat_header)
        # 채팅 답변도 Markdown으로 표시해 ChatGPT와 비슷하게 읽을 수 있게 합니다.
        self.chat_output = QTextBrowser()
        self.chat_output.setReadOnly(True)
        self.chat_output.setPlaceholderText("회의자료를 생성한 뒤 질문을 입력하세요.")
        chat_layout.addWidget(self.chat_output)
        chat_actions = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("예: 결정된 사항과 담당자를 알려줘")
        self.chat_button = QPushButton("질문 보내기")
        self.chat_button.setObjectName("primaryButton")
        chat_actions.addWidget(self.chat_input)
        chat_actions.addWidget(self.chat_button)
        chat_layout.addLayout(chat_actions)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(8)
        splitter.addWidget(results_panel)
        splitter.addWidget(chat_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 220])
        root.addWidget(splitter, 1)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("statusLabel")
        root.addWidget(self.status_label)

        self.record_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.open_button.clicked.connect(self.open_audio)
        self.process_button.clicked.connect(self.process_audio)
        self.save_button.clicked.connect(self.save_results)
        self.toggle_transcript_button.clicked.connect(self.toggle_transcript)
        self.chat_button.clicked.connect(self.send_chat)
        self.chat_input.returnPressed.connect(self.send_chat)
        self.clear_summary_button.clicked.connect(self.clear_summary)
        self.clear_transcript_button.clicked.connect(self.clear_transcript)
        self.clear_chat_button.clicked.connect(self.clear_chat)
        self.load_models()
        self.setStyleSheet(
            "QMainWindow { background-color: #f2f4f7; }"
            "QWidget { color: #202830; font-size: 13px; }"
            "QLabel#pageTitle { color: #1f3b57; font-size: 20px; font-weight: 700; }"
            "QLabel#pageSubtitle { color: #5f6b78; padding-bottom: 2px; }"
            "QGroupBox { background-color: #ffffff; border: 1px solid #c8ced6;"
            " margin-top: 8px; padding: 10px; font-weight: 600; }"
            "QGroupBox#sectionCard { background-color: #fbfcfd; }"
            "QLabel#cardHint { color: #5d6874; font-size: 12px; font-weight: 400; }"
            "QLabel#statusLabel { color: #40566b; padding: 4px 2px; }"
            "QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser { border: 1px solid #b8c1cb;"
            " padding: 4px 6px; background-color: #ffffff; selection-background-color: #c9dced; }"
            "QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextBrowser:focus { border: 1px solid #4b7ea8; }"
            "QPushButton { padding: 5px 10px; border: 1px solid #aeb8c2;"
            " background-color: #eef1f4; }"
            "QPushButton:hover { background-color: #e2e8ee; border-color: #7d91a4; }"
            "QPushButton#primaryButton { background-color: #dbe8f4; border-color: #86a8c5;"
            " color: #1e4668; font-weight: 600; }"
            "QPushButton#primaryButton:hover { background-color: #cbddec; }"
            "QPushButton#clearButton { padding: 3px 8px; color: #5d6874; font-size: 12px; }"
            "QPushButton:disabled { color: #8b949d; background-color: #edf0f2; }"
        )

    def start_recording(self) -> None:
        output_path, _ = QFileDialog.getSaveFileName(
            self, "녹음 파일 저장 위치", f"meeting-recording-{datetime.now():%Y%m%d-%H%M%S}.wav", "WAV 파일 (*.wav)"
        )
        if not output_path:
            return
        self.recording_thread = RecordingThread(Path(output_path))
        self.recording_thread.saved.connect(self.recording_saved)
        self.recording_thread.failed.connect(self.show_error)
        self.recording_thread.start()
        self.record_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.set_status("녹음 중입니다. 중지 버튼을 누르면 WAV 파일로 저장합니다.")

    def stop_recording(self) -> None:
        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop()
            self.stop_button.setEnabled(False)
            self.set_status("녹음 파일을 저장하는 중입니다...")

    def recording_saved(self, path: str) -> None:
        self.selected_audio_path = Path(path)
        self.file_label.setText(f"선택된 파일: {path}")
        self.record_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.set_status("녹음이 저장되었습니다. 전사 및 요약을 실행할 수 있습니다.")

    def load_models(self) -> None:
        """프로그램 시작 시 OpenAI의 최신 모델 목록을 비동기로 가져옵니다."""
        self.model_list_thread = ModelListThread()
        self.model_list_thread.completed.connect(self.models_loaded)
        self.model_list_thread.failed.connect(self.models_failed)
        self.set_status("OpenAI에서 사용 가능한 모델을 불러오는 중입니다...")
        self.model_list_thread.start()

    def models_loaded(self, models: list[str]) -> None:
        """OpenAI가 반환한 모델 ID를 선택 상자에 표시합니다."""
        self.model_input.clear()
        available_models = list(models)
        if DEFAULT_SUMMARY_MODEL not in available_models:
            available_models.insert(0, DEFAULT_SUMMARY_MODEL)
        self.model_input.addItems(available_models)
        self.model_input.setCurrentText(DEFAULT_SUMMARY_MODEL)
        self.model_input.setEnabled(bool(available_models))
        self.process_button.setEnabled(bool(available_models))
        if models:
            self.set_status(f"{len(models)}개의 OpenAI 모델을 불러왔습니다. 기본 모델: {DEFAULT_SUMMARY_MODEL}")
        else:
            self.set_status(f"OpenAI 모델 목록을 불러오지 못했지만 {DEFAULT_SUMMARY_MODEL}을 기본 모델로 설정했습니다.")

    def models_failed(self, message: str) -> None:
        """모델 목록 조회 실패 시 사용자가 원인을 알 수 있도록 안내합니다."""
        self.model_input.clear()
        self.model_input.addItem("모델을 불러오지 못했습니다")
        self.model_input.setEnabled(False)
        self.process_button.setEnabled(False)
        self.show_error(f"OpenAI 모델 목록을 불러오지 못했습니다.\n{message}")

    def open_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "오디오 파일 선택", "", "오디오 파일 (*.wav *.mp3 *.m4a *.webm *.mp4 *.mpeg *.mpga)"
        )
        if path:
            self.selected_audio_path = Path(path)
            self.file_label.setText(f"선택된 파일: {path}")
            self.set_status("오디오 파일을 선택했습니다.")

    def process_audio(self) -> None:
        """선택한 오디오를 백그라운드에서 전사하고 요약하도록 시작합니다."""
        if not self.selected_audio_path:
            self.show_error("먼저 녹음하거나 오디오 파일을 선택해 주세요.")
            return
        if not self.model_input.currentText() or not self.model_input.isEnabled():
            self.show_error("먼저 OpenAI 모델 목록을 불러와야 합니다.")
            return
        values = {
            "title": self.title_input.text().strip(),
            "language": self.language_input.text().strip() or "ko",
            "prompt": self.prompt_input.text().strip(),
            "focus": self.focus_input.text().strip(),
            "model": self.model_input.currentText(),
        }
        # 입력 위젯의 값을 하나의 딕셔너리로 모아 작업 스레드에 전달합니다.
        self.processing_thread = ProcessingThread(self.selected_audio_path, values)
        self.processing_thread.completed.connect(self.processing_completed)
        self.processing_thread.failed.connect(self.processing_failed)
        self.process_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.set_status("OpenAI API로 전사와 요약을 생성하고 있습니다...")
        self.processing_thread.start()

    def processing_completed(self, result: dict) -> None:
        """백그라운드 작업이 끝났을 때 요약문과 전사문을 화면에 표시합니다."""
        self.summary_output.setMarkdown(result.get("summary", ""))
        self.transcript_output.setPlainText(result.get("transcript", ""))
        self.save_button.setEnabled(True)
        self.process_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.set_status("전사와 회의자료 요약이 완료되었습니다.")

    def clear_summary(self) -> None:
        """회의자료 요약 영역만 비웁니다."""
        self.summary_output.clear()
        self.set_status("회의자료 요약 내용을 지웠습니다.")

    def clear_transcript(self) -> None:
        """원문 전사 영역만 비웁니다."""
        self.transcript_output.clear()
        self.set_status("원문 전사 내용을 지웠습니다.")

    def toggle_transcript(self) -> None:
        """원문 전사 영역을 표시하거나 숨깁니다."""
        is_visible = self.transcript_box.isVisible()
        self.transcript_box.setVisible(not is_visible)
        self.toggle_transcript_button.setText("원문 숨기기" if not is_visible else "원문 보기")

    def clear_chat(self) -> None:
        """채팅 질문과 답변을 모두 비우고 새 대화를 시작합니다."""
        self.chat_markdown = ""
        self.chat_output.clear()
        self.set_status("채팅 내용을 지웠습니다.")

    def processing_failed(self, message: str) -> None:
        self.process_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.show_error(message)

    def send_chat(self) -> None:
        """현재 결과를 문맥으로 사용해 사용자의 채팅 질문을 보냅니다."""
        message = self.chat_input.text().strip()
        if not message:
            self.set_status("질문을 입력해 주세요.")
            return
        # 모델이 회의 내용을 참고할 수 있도록 요약문과 원문을 하나로 합칩니다.
        context = "\n\n".join(
            value for value in (
                self.summary_output.toPlainText().strip(),
                self.transcript_output.toPlainText().strip(),
            ) if value
        )
        self.chat_markdown += f"### 나\n\n{message}\n\n"
        self.chat_output.setMarkdown(self.chat_markdown)
        self.scroll_chat_to_bottom()
        self.chat_input.clear()
        self.chat_button.setEnabled(False)
        self.set_status("회의 내용을 바탕으로 채팅 답변을 생성하고 있습니다...")
        # 채팅도 요약과 마찬가지로 별도 스레드에서 실행합니다.
        self.chat_thread = ChatThread(
            message=message,
            context=context,
            model=self.model_input.currentText(),
            language=self.language_input.text().strip() or "ko",
        )
        self.chat_thread.completed.connect(self.chat_completed)
        self.chat_thread.failed.connect(self.chat_failed)
        self.chat_thread.start()

    def chat_completed(self, answer: str) -> None:
        """채팅 스레드가 성공하면 질문과 답변을 대화창에 추가합니다."""
        self.chat_markdown += f"### OpenAI\n\n{answer}\n\n"
        self.chat_output.setMarkdown(self.chat_markdown)
        self.scroll_chat_to_bottom()
        self.chat_button.setEnabled(True)
        self.set_status(f"{self.model_input.currentText()} 모델의 채팅 답변을 받았습니다.")

    def scroll_chat_to_bottom(self) -> None:
        """새 메시지를 표시한 뒤 채팅 스크롤을 마지막 줄로 이동합니다."""
        # Markdown을 HTML로 다시 그리는 작업이 끝난 다음 스크롤해야 정확한 위치를 얻습니다.
        QTimer.singleShot(
            0,
            lambda: self.chat_output.verticalScrollBar().setValue(
                self.chat_output.verticalScrollBar().maximum()
            ),
        )

    def chat_failed(self, message: str) -> None:
        """채팅 실패 시 버튼을 되살리고 공통 오류 창을 보여줍니다."""
        self.chat_button.setEnabled(True)
        self.show_error(message)

    def save_results(self) -> None:
        summary = self.summary_output.toPlainText().strip()
        transcript = self.transcript_output.toPlainText().strip()
        path, _ = QFileDialog.getSaveFileName(self, "회의자료 저장", "meeting-summary.txt", "텍스트 파일 (*.txt)")
        if path:
            Path(path).write_text(f"[회의자료 요약]\n{summary}\n\n[원문 전사]\n{transcript}\n", encoding="utf-8")
            self.set_status("회의자료를 저장했습니다.")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def show_error(self, message: str) -> None:
        self.set_status("오류가 발생했습니다.")
        QMessageBox.critical(self, "회의 녹음 요약", message)


def main() -> int:
    app = QApplication(sys.argv)
    native_style = QStyleFactory.create("WindowsVista") or QStyleFactory.create("Windows")
    if native_style is not None:
        app.setStyle(native_style)
    window = MeetingSummaryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())