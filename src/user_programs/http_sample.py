"""main.py의 /apps/http_sample/... API로 호출되는 샘플 사용자 프로그램입니다.

프로그램 전체 흐름
1. 사용자가 main.py 서버에 HTTP 요청을 보냅니다.
   예: GET /apps/http_sample/hello?name=홍길동
2. main.py는 이 파일(src/user_programs/http_sample.py)을 새 Python 프로세스로 실행합니다.
3. main.py는 HTTP 요청 정보를 JSON 문자열로 만들어 이 프로그램의 stdin에 넣어 줍니다.
4. 이 프로그램은 sys.stdin.read()로 요청 JSON을 읽고, handle_request()에서 경로별로 처리합니다.
5. 처리 결과는 {"status_code": ..., "headers": ..., "media_type": ..., "body": ...} 형태로 만듭니다.
6. 마지막에 print()로 응답 JSON을 stdout에 출력하면, main.py가 그 값을 HTTP 응답으로 변환합니다.

중요한 규칙
- 이 파일은 FastAPI 서버를 직접 띄우지 않습니다.
- print()로 stdout에 출력하는 값은 반드시 JSON이어야 합니다.
- 디버깅용 출력도 stdout에 섞이면 main.py가 JSON 파싱에 실패할 수 있으니 주의합니다.
- 동시에 호출되어도 main.py가 요청마다 새 프로세스를 만들기 때문에 request_id와 파라미터가 섞이지 않습니다.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime


def make_response(status_code: int = 200, body: object | None = None, request_id: str = "") -> dict:
    """main.py가 HTTP 응답으로 바꿀 수 있는 표준 응답 형식을 만듭니다."""
    # main.py는 이 딕셔너리를 읽어서 FastAPI Response로 변환합니다.
    # body에는 실제 사용자에게 돌려줄 JSON 내용을 넣습니다.
    return {
        "status_code": status_code,
        "headers": {
            # 응답 헤더에도 어떤 사용자 프로그램이 처리했는지 표시합니다.
            "X-User-Program": "http_sample",
            # request_id를 헤더로 내려주면 클라이언트와 서버 로그를 맞춰 보기 쉽습니다.
            "X-Request-Id": request_id,
        },
        "media_type": "application/json",
        "body": body if body is not None else {},
    }


def handle_request(request: dict) -> dict:
    """main.py에서 전달받은 HTTP 요청 정보를 처리합니다."""
    # request에는 main.py가 만든 HTTP 요청 정보가 들어 있습니다.
    # 예: method, path, query, headers, body, json, request_id
    method = request.get("method", "GET")
    path = request.get("path", "/")
    query = request.get("query", {})
    json_body = request.get("json")
    request_id = request.get("request_id", "")

    # GET /apps/http_sample/hello?name=홍길동 요청을 처리하는 예제입니다.
    # main.py가 /apps/http_sample 부분을 제거하고 path="/hello"로 전달합니다.
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

    # POST /apps/http_sample/echo 요청을 처리하는 예제입니다.
    # 클라이언트가 보낸 JSON 본문과 원본 텍스트 본문을 그대로 응답에 넣어 확인할 수 있습니다.
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

    # GET /apps/http_sample/time 요청을 처리하는 예제입니다.
    # 사용자 프로그램이 서버에서 실제로 실행된 시간을 반환합니다.
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

        # delay 값만큼 일부러 대기해 여러 요청이 동시에 처리되는 상황을 테스트합니다.
        # 너무 오래 대기하지 않도록 최대 5초로 제한합니다.
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

    # 위에서 처리하지 않은 method/path 조합은 404 응답으로 알려 줍니다.
    # 어떤 예제를 호출할 수 있는지도 같이 내려줘서 테스트하기 쉽게 합니다.
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
        # main.py가 stdin으로 넣어 준 JSON 문자열을 읽습니다.
        # stdin이 비어 있으면 빈 요청({})으로 처리해 예외를 줄입니다.
        request = json.loads(sys.stdin.read() or "{}")
        response = handle_request(request)
    except Exception as exc:
        # 사용자 프로그램에서 예외가 나도 main.py가 이해할 수 있는 JSON 형식으로 응답합니다.
        # 이렇게 하면 클라이언트는 500 응답과 오류 메시지를 받을 수 있습니다.
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

    # stdout에는 최종 응답 JSON 하나만 출력합니다.
    # main.py는 이 값을 json.loads()로 읽기 때문에 다른 print 로그를 섞으면 안 됩니다.
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
