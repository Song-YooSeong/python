"""FastAPI 서버이자 사용자 Python 프로그램 실행 관리자입니다.

프로그램 전체 흐름
1. 사용자가 브라우저, curl, Postman 같은 도구로 main.py 서버에 HTTP 요청을 보냅니다.
2. 일반 예제 API(/hello, /todos 등)는 main.py 안에서 바로 응답합니다.
3. 사용자 프로그램 호출 API(/apps/{program}/{path})는 src/user_programs 폴더에서
   {program}.py 파일을 찾습니다.
4. main.py는 HTTP 요청 정보를 JSON으로 정리해서 사용자 프로그램의 stdin으로 전달합니다.
5. 사용자 프로그램은 stdin에서 요청 JSON을 읽고, 처리 결과 JSON을 stdout으로 출력합니다.
6. main.py는 stdout의 JSON을 읽어 FastAPI Response로 바꾼 뒤 사용자에게 HTTP 응답합니다.

동시 호출 처리 방식
- 요청마다 새로운 Python 프로세스를 실행하므로 stdin/stdout 파이프가 요청끼리 섞이지 않습니다.
- asyncio.create_subprocess_exec()를 사용해 사용자 프로그램 실행 중에도 서버가 다른 요청을
  받을 수 있게 합니다.
- PROGRAM_SEMAPHORE로 동시에 실행되는 사용자 프로그램 수를 제한해 서버 과부하를 줄입니다.
"""

from pathlib import Path
import asyncio
import json
import sys
import time
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field


# FastAPI 앱을 생성합니다.
# title, description은 Swagger 문서 화면에서 보기 좋게 보여 줍니다.
app = FastAPI(
    title="Beginner FastAPI Example",
    description="초보자가 웹 요청 방식을 연습할 수 있도록 만든 예제입니다.",
    version="1.0.0",
)


# 웹에서 실행할 사용자 Python 프로그램을 모아 둘 폴더입니다.
# 예: src/user_programs/hello.py 파일을 만든 뒤 /programs/run API로 실행할 수 있습니다.
BASE_DIR = Path(__file__).resolve().parent
USER_PROGRAM_DIR = BASE_DIR / "user_programs"
DEFAULT_PROGRAM_TIMEOUT_SECONDS = 10
MAX_PROGRAM_TIMEOUT_SECONDS = 60
MAX_CONCURRENT_PROGRAMS = 10

# 동시에 너무 많은 사용자 프로그램이 실행되어 서버가 과부하되지 않도록 제한합니다.
PROGRAM_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_PROGRAMS)


# 메모리에만 저장되는 간단한 데이터 저장소입니다.
# 프로그램을 다시 실행하면 내용이 초기화됩니다.
todos: list[dict] = [
    {"id": 1, "title": "FastAPI 공부하기", "done": False},
    {"id": 2, "title": "GET 요청 테스트하기", "done": True},
]


# 요청 본문(body)으로 받을 데이터 형식을 정의합니다.
# title은 할 일 제목, done은 완료 여부입니다.
class TodoCreate(BaseModel):
    title: str = Field(..., min_length=1, description="할 일 제목")
    done: bool = Field(default=False, description="완료 여부")


# 수정 요청에서는 title, done 둘 다 선택 입력이 가능하도록 Optional을 사용합니다.
class TodoUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, description="수정할 제목")
    done: Optional[bool] = Field(default=None, description="수정할 완료 여부")


# 웹 요청으로 Python 프로그램을 실행할 때 받을 데이터 형식입니다.
class ProgramRunRequest(BaseModel):
    """POST /programs/run에서 사용자 프로그램을 직접 실행할 때 받는 요청 형식입니다."""

    program: str = Field(
        ...,
        description="실행할 Python 파일명 또는 user_programs 기준 상대 경로. 예: hello.py",
        examples=["hello.py"],
    )
    args: list[str] = Field(
        default_factory=list,
        description="프로그램에 전달할 명령행 인자 목록입니다.",
        examples=[["홍길동", "3"]],
    )
    stdin: Optional[str] = Field(
        default=None,
        description="input() 또는 표준 입력으로 전달할 문자열입니다.",
    )
    timeout_seconds: int = Field(
        default=DEFAULT_PROGRAM_TIMEOUT_SECONDS,
        ge=1,
        le=MAX_PROGRAM_TIMEOUT_SECONDS,
        description="프로그램 최대 실행 시간입니다.",
    )


class ProgramHttpResult(BaseModel):
    """사용자 프로그램이 stdout으로 출력해야 하는 HTTP 응답 형식입니다."""

    status_code: int = Field(default=200, ge=100, le=599, description="HTTP 응답 상태 코드")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP 응답 헤더")
    body: object = Field(default_factory=dict, description="HTTP 응답 본문")
    media_type: str = Field(default="application/json", description="HTTP 응답 Content-Type")


def find_todo(todo_id: int) -> Optional[dict]:
    # id가 같은 todo를 찾으면 반환하고, 없으면 None을 반환합니다.
    for todo in todos:
        if todo["id"] == todo_id:
            return todo
    return None


def ensure_user_program_dir() -> None:
    # 폴더가 없으면 자동 생성해서 사용자가 프로그램 파일을 넣기 쉽게 합니다.
    # 예: 처음 실행 시 src/user_programs 폴더가 없더라도 여기서 만들어집니다.
    USER_PROGRAM_DIR.mkdir(parents=True, exist_ok=True)


def resolve_user_program(program: str) -> Path:
    # 웹 요청 값으로 서버의 아무 파일이나 실행하지 못하도록 user_programs 폴더 안으로 제한합니다.
    ensure_user_program_dir()

    # 사용자가 "sample.py"라고 보내면 src/user_programs/sample.py로 해석합니다.
    # resolve()는 ".." 같은 상대 경로를 모두 정리한 실제 절대 경로를 만들어 줍니다.
    program_path = (USER_PROGRAM_DIR / program).resolve()
    try:
        # relative_to()가 성공해야 program_path가 USER_PROGRAM_DIR 안에 있다는 뜻입니다.
        program_path.relative_to(USER_PROGRAM_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="user_programs 폴더 밖의 파일은 실행할 수 없습니다.")

    # 이 예제는 Python 파일 실행만 지원하므로 .py 확장자만 허용합니다.
    if program_path.suffix.lower() != ".py":
        raise HTTPException(status_code=400, detail="Python .py 파일만 실행할 수 있습니다.")
    if not program_path.exists() or not program_path.is_file():
        raise HTTPException(status_code=404, detail=f"프로그램 파일을 찾을 수 없습니다: {program}")

    return program_path


def build_program_command(program_path: Path, args: list[str] | None = None) -> list[str]:
    # 현재 FastAPI 서버와 같은 Python 실행 파일로 사용자 프로그램을 실행합니다.
    # shell=True를 쓰지 않고 리스트로 명령을 전달하면 명령어 주입 위험을 줄일 수 있습니다.
    return [sys.executable, str(program_path), *(args or [])]


def list_user_programs() -> list[dict]:
    # user_programs 폴더 아래의 .py 파일 목록을 Swagger나 웹 화면에서 확인할 수 있게 반환합니다.
    ensure_user_program_dir()
    programs: list[dict] = []

    for path in sorted(USER_PROGRAM_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        relative_path = path.relative_to(USER_PROGRAM_DIR).as_posix()
        programs.append(
            {
                "program": relative_path,
                "size_bytes": path.stat().st_size,
                "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)),
            }
        )

    return programs


async def run_user_program_process(
    program_path: Path,
    args: list[str] | None = None,
    stdin: str | None = None,
    timeout_seconds: int = DEFAULT_PROGRAM_TIMEOUT_SECONDS,
    request_id: str | None = None,
) -> dict:
    # 사용자 프로그램 실행 공통 함수입니다.
    # /programs/run 과 /apps/{program} 양쪽에서 같은 방식으로 프로세스를 실행합니다.
    # 각 HTTP 요청마다 새 프로세스를 만들기 때문에 stdin/stdout 파이프는 서로 공유되지 않습니다.
    command = build_program_command(program_path, args)

    # request_id는 로그/응답에서 "이 결과가 어떤 요청의 결과인지" 추적하기 위한 값입니다.
    # HTTP 호출에서는 클라이언트가 X-Request-Id 헤더로 직접 줄 수도 있고, 없으면 새로 만듭니다.
    request_id = request_id or uuid4().hex
    started_at = time.perf_counter()

    # subprocess는 bytes를 주고받으므로 문자열 stdin을 UTF-8 bytes로 바꿉니다.
    stdin_bytes = stdin.encode("utf-8") if stdin is not None else None

    async with PROGRAM_SEMAPHORE:
        # 세마포어 안에 들어온 요청만 실제 프로세스를 실행합니다.
        # 동시에 너무 많은 프로그램이 실행되면 OS/서버 자원이 부족해질 수 있기 때문입니다.
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(USER_PROGRAM_DIR),
        )

        try:
            # communicate()는 stdin을 보내고, 프로그램이 종료될 때까지 stdout/stderr를 모읍니다.
            # wait_for()로 제한 시간을 걸어 무한 실행되는 프로그램을 막습니다.
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(stdin_bytes),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            # 제한 시간을 넘긴 프로그램은 강제로 종료하고, 그때까지 나온 출력만 응답에 담습니다.
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return {
                "request_id": request_id,
                "command": command,
                "timed_out": True,
                "timeout_seconds": timeout_seconds,
                "elapsed_ms": elapsed_ms,
                "stdout": stdout_bytes.decode("utf-8", errors="replace"),
                "stderr": stderr_bytes.decode("utf-8", errors="replace"),
                "return_code": None,
            }

    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    return {
        "request_id": request_id,
        "command": command,
        "timed_out": False,
        "elapsed_ms": elapsed_ms,
        "stdout": stdout_bytes.decode("utf-8", errors="replace"),
        "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        "return_code": process.returncode,
        "success": process.returncode == 0,
    }


async def build_http_envelope(request: Request, subpath: str) -> dict:
    # 실제 HTTP 요청 정보를 사용자 프로그램이 이해하기 쉬운 JSON 형태로 변환합니다.
    request_id = request.headers.get("x-request-id") or uuid4().hex

    # request.body()는 HTTP 요청 본문을 bytes로 읽어 옵니다.
    # 사용자 프로그램이 텍스트와 JSON 둘 다 쓸 수 있도록 body, json 두 형태로 전달합니다.
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
    json_body = None

    if body_text:
        try:
            json_body = json.loads(body_text)
        except json.JSONDecodeError:
            json_body = None

    return {
        "request_id": request_id,
        "method": request.method,
        "path": "/" + subpath if subpath else "/",
        "query": dict(request.query_params),
        "headers": dict(request.headers),
        "body": body_text,
        "json": json_body,
    }


def parse_program_http_response(program_name: str, run_info: dict) -> ProgramHttpResult:
    # 사용자 프로그램은 stdout에 JSON 응답을 출력해야 합니다.
    # 예: {"status_code": 200, "body": {"message": "ok"}}
    stdout = run_info.get("stdout") or ""
    stderr = run_info.get("stderr") or ""

    # 시간이 너무 오래 걸린 경우 클라이언트에게 504 Gateway Timeout 형태로 알려 줍니다.
    if run_info.get("timed_out"):
        raise HTTPException(status_code=504, detail=run_info)

    # 사용자 프로그램 자체에서 예외가 나거나 종료 코드가 0이 아니면 서버 오류로 처리합니다.
    if run_info.get("return_code") != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "사용자 프로그램 실행 중 오류가 발생했습니다.",
                "program": program_name,
                "stderr": stderr,
                "return_code": run_info.get("return_code"),
            },
        )

    try:
        # stdout은 문자열이므로 json.loads()로 Python dict/list 형태로 바꿉니다.
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "사용자 프로그램이 올바른 JSON 응답을 출력하지 않았습니다.",
                "program": program_name,
                "stdout": stdout,
                "stderr": stderr,
            },
        )

    # Pydantic 모델로 검증하면 status_code 범위, headers 타입 같은 기본 오류를 잡을 수 있습니다.
    return ProgramHttpResult.model_validate(payload)


def to_fastapi_response(result: ProgramHttpResult) -> Response:
    # 사용자 프로그램이 만든 응답 형식을 FastAPI 응답 객체로 변환합니다.
    # JSON 응답은 ensure_ascii=False로 만들어 한글이 \uXXXX 형태로 깨져 보이지 않게 합니다.
    if result.media_type == "application/json":
        content = json.dumps(result.body, ensure_ascii=False)
    elif isinstance(result.body, str):
        content = result.body
    else:
        content = json.dumps(result.body, ensure_ascii=False)

    return Response(
        content=content,
        status_code=result.status_code,
        headers=result.headers,
        media_type=result.media_type,
    )


@app.get("/")
async def read_root():
    # 가장 기본적인 GET 요청 예시입니다.
    # 브라우저에서 http://127.0.0.1:8000/ 로 접속하면 이 응답이 보입니다.
    return {
        "message": "FastAPI 서버가 정상적으로 실행 중입니다.",
        "docs": "/docs",
        "program_api": {
            "list": "/programs",
            "run": "/programs/run",
            "http_call": "/apps/{program}/{path}",
            "program_folder": str(USER_PROGRAM_DIR),
            "max_concurrent_programs": MAX_CONCURRENT_PROGRAMS,
        },
    }


@app.get("/hello")
async def say_hello(name: str = Query("world", description="인사할 이름")):
    # Query는 URL 쿼리 문자열 값을 받습니다.
    # 예: /hello?name=python
    return {"message": f"Hello, {name}!"}


@app.get("/todos")
async def list_todos(done: Optional[bool] = Query(default=None, description="완료 여부로 필터링")):
    # done 값이 없으면 전체 목록을 반환합니다.
    if done is None:
        return {"items": todos, "count": len(todos)}

    # done=True 또는 done=False 값이 오면 조건에 맞는 항목만 추립니다.
    filtered_items = [todo for todo in todos if todo["done"] == done]
    return {"items": filtered_items, "count": len(filtered_items)}


@app.get("/todos/{todo_id}")
async def get_todo(todo_id: int):
    # Path Parameter 예시입니다.
    # /todos/1 처럼 URL 경로 안의 값을 받아옵니다.
    todo = find_todo(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="해당 할 일을 찾을 수 없습니다.")
    return todo


@app.post("/todos", status_code=201)
async def create_todo(todo: TodoCreate, user_agent: Optional[str] = Header(default=None)):
    # POST 요청은 보통 새로운 데이터를 만들 때 사용합니다.
    # todo 변수에는 JSON 본문이 자동으로 파싱되어 들어옵니다.
    new_id = max((item["id"] for item in todos), default=0) + 1

    new_todo = {
        "id": new_id,
        "title": todo.title,
        "done": todo.done,
    }
    todos.append(new_todo)

    # Header 값도 이렇게 받을 수 있습니다.
    return {
        "message": "할 일이 등록되었습니다.",
        "item": new_todo,
        "request_user_agent": user_agent,
    }


@app.put("/todos/{todo_id}")
async def update_todo(todo_id: int, todo_update: TodoUpdate):
    # PUT 요청은 기존 데이터를 수정할 때 자주 사용합니다.
    todo = find_todo(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="수정할 할 일을 찾을 수 없습니다.")

    # 값이 들어온 항목만 수정합니다.
    if todo_update.title is not None:
        todo["title"] = todo_update.title
    if todo_update.done is not None:
        todo["done"] = todo_update.done

    return {
        "message": "할 일이 수정되었습니다.",
        "item": todo,
    }


@app.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int):
    # DELETE 요청은 데이터를 삭제할 때 사용합니다.
    todo = find_todo(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="삭제할 할 일을 찾을 수 없습니다.")

    todos.remove(todo)
    return {"message": "할 일이 삭제되었습니다."}


@app.get("/headers")
async def read_headers(x_token: Optional[str] = Header(default=None)):
    # 요청 헤더 값을 확인하는 예시입니다.
    # 예: X-Token: my-secret-token
    return {
        "message": "헤더 확인 완료",
        "x_token": x_token,
    }


@app.get("/programs")
async def get_programs():
    # 실행 가능한 사용자 Python 프로그램 목록을 보여 줍니다.
    # 사용자는 이 API로 어떤 프로그램을 /apps/{program}에서 호출할 수 있는지 확인할 수 있습니다.
    programs = list_user_programs()
    return {
        "program_dir": str(USER_PROGRAM_DIR),
        "items": programs,
        "count": len(programs),
        "usage": {
            "direct_run": "src/user_programs 폴더에 .py 파일을 넣고 POST /programs/run 으로 실행하세요.",
            "http_call": "HTTP 프로그램은 POST /apps/{program}/{path} 또는 GET /apps/{program}/{path} 로 호출하세요.",
            "sample": "/apps/http_sample/hello?name=홍길동",
        },
    }


@app.get("/programs/http-usage")
async def get_http_program_usage():
    # HTTP 방식 사용자 프로그램을 어떻게 호출하고 어떤 응답을 받는지 예시를 제공합니다.
    return {
        "description": "main.py가 /apps/{program}/{path} 요청을 받아 src/user_programs/{program}.py를 실행합니다.",
        "program_contract": {
            "input": "사용자 프로그램은 stdin으로 HTTP 요청 정보 JSON을 받습니다.",
            "output": "사용자 프로그램은 stdout으로 status_code, headers, media_type, body가 담긴 JSON을 출력합니다.",
            "concurrency": "요청마다 새 프로세스와 독립 stdin/stdout 파이프를 사용하고 request_id로 요청을 구분합니다.",
        },
        "examples": [
            {
                "name": "GET 호출",
                "request": "GET http://127.0.0.1:8000/apps/http_sample/hello?name=홍길동",
                "response_body_example": {
                    "message": "안녕하세요, 홍길동님!",
                    "called_program": "http_sample.py",
                    "path": "/hello",
                },
            },
            {
                "name": "POST JSON 호출",
                "request": "POST http://127.0.0.1:8000/apps/http_sample/echo",
                "request_body": {"message": "테스트 요청입니다.", "count": 3},
                "response_body_example": {
                    "message": "요청 본문을 그대로 돌려주는 echo 예제입니다.",
                    "received_json": {"message": "테스트 요청입니다.", "count": 3},
                    "received_text": "{\"message\":\"테스트 요청입니다.\",\"count\":3}",
                },
            },
        ],
    }


@app.post("/programs/run")
async def run_program(request: ProgramRunRequest):
    # 사용자가 작성한 Python 파일을 별도 프로세스로 실행합니다.
    # shell=True를 쓰지 않기 때문에 명령어 주입 위험을 줄일 수 있습니다.
    # 이 API는 HTTP 요청 모양을 전달하지 않고, 단순히 파일 + args + stdin으로 실행합니다.
    program_path = resolve_user_program(request.program)
    run_info = await run_user_program_process(
        program_path=program_path,
        args=request.args,
        stdin=request.stdin,
        timeout_seconds=request.timeout_seconds,
    )

    return {
        "program": request.program,
        **run_info,
    }


@app.api_route("/apps/{program}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/apps/{program}/{subpath:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def call_http_program(program: str, request: Request, subpath: str = ""):
    # HTTP 요청으로 들어온 program 이름을 실제 Python 파일로 찾아 실행합니다.
    # 예: GET /apps/http_sample/hello?name=Kim -> src/user_programs/http_sample.py 실행
    program_path = resolve_user_program(f"{program}.py")

    # FastAPI의 Request 객체를 사용자 프로그램이 읽을 수 있는 JSON 봉투(envelope)로 바꿉니다.
    envelope = await build_http_envelope(request, subpath)

    # envelope JSON을 stdin으로 넘기면 사용자 프로그램은 sys.stdin.read()로 읽을 수 있습니다.
    run_info = await run_user_program_process(
        program_path=program_path,
        stdin=json.dumps(envelope, ensure_ascii=False),
        timeout_seconds=DEFAULT_PROGRAM_TIMEOUT_SECONDS,
        request_id=envelope["request_id"],
    )

    # 사용자 프로그램의 stdout JSON을 검증하고 FastAPI 응답으로 변환합니다.
    program_response = parse_program_http_response(program, run_info)
    return to_fastapi_response(program_response)


# 이 파일을 직접 실행하면 uvicorn 서버를 시작합니다.
# 터미널에서 `python3 src/main.py` 로 실행할 수 있습니다.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
