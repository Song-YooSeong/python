from __future__ import annotations

import sys
import threading
import wave
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from PySide6.QtCore import QThread, Signal
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
    QVBoxLayout,
    QWidget,
)

from meeting_summary_service import MeetingSummaryService


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
            )
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MeetingSummaryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.recording_thread: RecordingThread | None = None
        self.processing_thread: ProcessingThread | None = None
        self.selected_audio_path: Path | None = None
        self.setWindowTitle("회의 녹음 요약")
        self.resize(1120, 820)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("회의 녹음 요약")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        root.addWidget(title)

        subtitle = QLabel("마이크로 녹음하거나 오디오 파일을 열어 전사문과 회의자료를 생성합니다.")
        subtitle.setStyleSheet("color: #5f6b76; font-size: 14px;")
        root.addWidget(subtitle)

        options = QGroupBox("회의 정보")
        fields = QGridLayout(options)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("예: 주간 운영 회의")
        self.language_input = QLineEdit("ko")
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("참석자, 프로젝트명, 제품명 등")
        self.focus_input = QLineEdit()
        self.focus_input.setPlaceholderText("예: 결정 사항과 담당자별 후속 조치 중심")
        fields.addWidget(QLabel("회의 제목"), 0, 0)
        fields.addWidget(self.title_input, 0, 1)
        fields.addWidget(QLabel("언어 코드"), 0, 2)
        fields.addWidget(self.language_input, 0, 3)
        fields.addWidget(QLabel("전사 힌트"), 1, 0)
        fields.addWidget(self.prompt_input, 1, 1, 1, 3)
        fields.addWidget(QLabel("요약 관점"), 2, 0)
        fields.addWidget(self.focus_input, 2, 1, 1, 3)
        root.addWidget(options)

        actions = QHBoxLayout()
        self.record_button = QPushButton("녹음 시작")
        self.record_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("녹음 중지")
        self.stop_button.setEnabled(False)
        self.open_button = QPushButton("오디오 파일 열기")
        self.process_button = QPushButton("전사 및 요약")
        self.process_button.setObjectName("primaryButton")
        self.save_button = QPushButton("결과 저장")
        self.save_button.setEnabled(False)
        for button in (self.record_button, self.stop_button, self.open_button, self.process_button, self.save_button):
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)

        self.file_label = QLabel("선택된 오디오 파일 없음")
        self.status_label = QLabel("대기 중")
        self.status_label.setStyleSheet("color: #0b766e; font-weight: 600;")
        root.addWidget(self.file_label)
        root.addWidget(self.status_label)

        results = QHBoxLayout()
        summary_box = QGroupBox("회의자료 요약")
        summary_layout = QVBoxLayout(summary_box)
        self.summary_output = QPlainTextEdit()
        self.summary_output.setReadOnly(True)
        summary_layout.addWidget(self.summary_output)
        transcript_box = QGroupBox("원문 전사")
        transcript_layout = QVBoxLayout(transcript_box)
        self.transcript_output = QPlainTextEdit()
        self.transcript_output.setReadOnly(True)
        transcript_layout.addWidget(self.transcript_output)
        results.addWidget(summary_box)
        results.addWidget(transcript_box)
        root.addLayout(results, 1)

        self.record_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.open_button.clicked.connect(self.open_audio)
        self.process_button.clicked.connect(self.process_audio)
        self.save_button.clicked.connect(self.save_results)
        self.setStyleSheet(
            "QMainWindow { background: #f3f6f7; } QWidget { font-size: 13px; }"
            " QGroupBox { background: white; border: 1px solid #d5dfe2; border-radius: 8px;"
            " margin-top: 8px; padding: 12px; font-weight: 600; }"
            " QLineEdit, QPlainTextEdit { border: 1px solid #ccd7db; border-radius: 6px;"
            " padding: 8px; background: white; }"
            " QPushButton { padding: 9px 15px; border: 0; border-radius: 6px;"
            " background: #e0e8ea; font-weight: 600; }"
            " QPushButton#primaryButton { background: #087f78; color: white; }"
            " QPushButton:disabled { color: #879397; background: #e7ecee; }"
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

    def open_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "오디오 파일 선택", "", "오디오 파일 (*.wav *.mp3 *.m4a *.webm *.mp4 *.mpeg *.mpga)"
        )
        if path:
            self.selected_audio_path = Path(path)
            self.file_label.setText(f"선택된 파일: {path}")
            self.set_status("오디오 파일을 선택했습니다.")

    def process_audio(self) -> None:
        if not self.selected_audio_path:
            self.show_error("먼저 녹음하거나 오디오 파일을 선택해 주세요.")
            return
        values = {
            "title": self.title_input.text().strip(),
            "language": self.language_input.text().strip() or "ko",
            "prompt": self.prompt_input.text().strip(),
            "focus": self.focus_input.text().strip(),
        }
        self.processing_thread = ProcessingThread(self.selected_audio_path, values)
        self.processing_thread.completed.connect(self.processing_completed)
        self.processing_thread.failed.connect(self.processing_failed)
        self.process_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.set_status("OpenAI API로 전사와 요약을 생성하고 있습니다...")
        self.processing_thread.start()

    def processing_completed(self, result: dict) -> None:
        self.summary_output.setPlainText(result.get("summary", ""))
        self.transcript_output.setPlainText(result.get("transcript", ""))
        self.save_button.setEnabled(True)
        self.process_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.set_status("전사와 회의자료 요약이 완료되었습니다.")

    def processing_failed(self, message: str) -> None:
        self.process_button.setEnabled(True)
        self.record_button.setEnabled(True)
        self.open_button.setEnabled(True)
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
    window = MeetingSummaryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())