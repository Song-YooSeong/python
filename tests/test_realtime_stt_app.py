"""
실시간 STT FastAPI 서버의 기본 동작 확인 테스트
===========================================

이 테스트는 다음 내용을 확인합니다.
1. `/api/health` 가 정상 응답을 주는지 확인합니다.
2. `/` 메인 화면이 HTML 로 열리는지 확인합니다.
3. WebSocket 연결 직후 ready 메시지를 받는지 확인합니다.
"""

from fastapi.testclient import TestClient

from src.realtime_stt_app import app


client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    """상태 확인 API 가 websocket 전송 방식을 포함해 정상 응답하는지 검사합니다."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["transport"] == "websocket"


def test_index_page_contains_title() -> None:
    """메인 화면이 HTML 로 열리고 제목 문자열을 포함하는지 검사합니다."""
    response = client.get("/")

    assert response.status_code == 200
    assert "회의 실시간 STT" in response.text


def test_websocket_ready_message() -> None:
    """WebSocket 연결 직후 ready 메시지를 받는지 검사합니다."""
    with client.websocket_connect("/ws/transcribe") as websocket:
        payload = websocket.receive_json()

    assert payload["type"] == "ready"
