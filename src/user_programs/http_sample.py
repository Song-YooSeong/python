"""main.py의 /apps/http_sample/... API로 호출되는 샘플 사용자 프로그램입니다.

이 파일은 직접 웹 서버를 띄우지 않습니다. 대신 main.py가 HTTP 요청 정보를 JSON으로
표준 입력(stdin)에 넣어 실행하면, 이 프로그램이 처리 결과를 JSON으로 표준 출력(stdout)에
내보냅니다.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime


def make_response(status_code: int = 200, body: object | None = None, request_id: str = "") -> dict:
    """main.py가 HTTP 응답으로 바꿀 수 있는 표준 응답 형식을 만듭니다."""
    return {
        "status_code": status_code,
        "headers": {
            "X-User-Program": "http_sample",
            "X-Request-Id": request_id,
        },
        "media_type": "application/json",
        "body": body if body is not None else {},
    }


def handle_request(request: dict) -> dict:
    """main.py에서 전달받은 HTTP 요청 정보를 처리합니다."""
    method = request.get("method", "GET")
    path = request.get("path", "/")
    query = request.get("query", {})
    json_body = request.get("json")
    request_id = request.get("request_id", "")

    if method == "GET" and path == "/hello":
        name = query.get("name", "world")
        return make_response(
            request_id=request_id,
            body={
                "message": f"안녕하세요, {name}님!",
                "called_program": "http_sample.py",
                "request_id": request_id,
                "path": path,
            }
        )

    if method == "POST" and path == "/echo":
        return make_response(
            request_id=request_id,
            body={
                "message": "요청 본문을 그대로 돌려주는 echo 예제입니다.",
                "request_id": request_id,
                "received_json": json_body,
                "received_text": request.get("body", ""),
            }
        )

    if method == "GET" and path == "/time":
        return make_response(
            request_id=request_id,
            body={
                "message": "서버에서 사용자 프로그램이 실행된 시간입니다.",
                "request_id": request_id,
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    if method == "GET" and path == "/slow":
        # 동시 호출 테스트용 예제입니다.
        # 각 요청은 독립 프로세스로 실행되므로 name, request_id가 다른 요청과 섞이지 않아야 합니다.
        name = query.get("name", "world")
        delay_seconds = min(float(query.get("delay", "1")), 5.0)
        time.sleep(delay_seconds)
        return make_response(
            request_id=request_id,
            body={
                "message": f"{delay_seconds}초 대기 후 응답했습니다.",
                "name": name,
                "request_id": request_id,
                "path": path,
            },
        )

    return make_response(
        status_code=404,
        request_id=request_id,
        body={
            "message": "http_sample.py에서 처리하지 않는 경로입니다.",
            "request_id": request_id,
            "method": method,
            "path": path,
            "available_examples": [
                "GET /apps/http_sample/hello?name=홍길동",
                "GET /apps/http_sample/time",
                "GET /apps/http_sample/slow?name=홍길동&delay=2",
                "POST /apps/http_sample/echo",
            ],
        },
    )


def main() -> None:
    """stdin으로 요청 JSON을 받아 처리한 뒤 stdout으로 응답 JSON을 출력합니다."""
    try:
        request = json.loads(sys.stdin.read() or "{}")
        response = handle_request(request)
    except Exception as exc:
        request_id = ""
        if "request" in locals() and isinstance(request, dict):
            request_id = request.get("request_id", "")
        response = make_response(
            status_code=500,
            request_id=request_id,
            body={
                "message": "사용자 프로그램 처리 중 오류가 발생했습니다.",
                "request_id": request_id,
                "error": str(exc),
            },
        )

    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
