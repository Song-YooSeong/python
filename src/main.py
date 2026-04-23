from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field


# FastAPI 앱을 생성합니다.
# title, description은 Swagger 문서 화면에서 보기 좋게 보여 줍니다.
app = FastAPI(
    title="Beginner FastAPI Example",
    description="초보자가 웹 요청 방식을 연습할 수 있도록 만든 예제입니다.",
    version="1.0.0",
)


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


def find_todo(todo_id: int) -> Optional[dict]:
    # id가 같은 todo를 찾으면 반환하고, 없으면 None을 반환합니다.
    for todo in todos:
        if todo["id"] == todo_id:
            return todo
    return None


@app.get("/")
async def read_root():
    # 가장 기본적인 GET 요청 예시입니다.
    # 브라우저에서 http://127.0.0.1:8000/ 로 접속하면 이 응답이 보입니다.
    return {
        "message": "FastAPI 서버가 정상적으로 실행 중입니다.",
        "docs": "/docs",
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


# 이 파일을 직접 실행하면 uvicorn 서버를 시작합니다.
# 터미널에서 `python3 src/main.py` 로 실행할 수 있습니다.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
