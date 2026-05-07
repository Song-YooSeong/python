"""회의 녹음 요약 FastAPI 서버의 기본 동작 확인 테스트.

이 테스트는 실제 OpenAI API를 호출하지 않습니다.
서버가 정상적으로 뜨는지, 메인 화면이 렌더링되는지,
잘못된 업로드 파일을 친절하게 거절하는지만 빠르게 확인합니다.
"""

from fastapi.testclient import TestClient

from src.realtime_stt_app import app


client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    """상태 확인 API가 현재 서버 설정을 JSON으로 돌려주는지 검사합니다."""

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "record-upload-summary"
    assert "summary_model" in payload
    assert "transcription_model" in payload


def test_index_page_contains_title() -> None:
    """메인 화면이 HTML로 열리고 현재 화면 제목을 포함하는지 검사합니다."""

    response = client.get("/")

    assert response.status_code == 200
    assert "회의 녹음 요약" in response.text
    assert "회의자료 요약 생성" in response.text


def test_summarize_recording_rejects_unsupported_file_type() -> None:
    """지원하지 않는 파일 확장자를 업로드하면 400 오류를 반환하는지 검사합니다."""

    response = client.post(
        "/api/summarize-recording",
        files={"audio_file": ("note.txt", b"not audio", "text/plain")},
    )

    assert response.status_code == 400
    assert "지원하지 않는 오디오 형식" in response.json()["detail"]
