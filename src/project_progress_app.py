from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator


# ---------------------------------------------------------------------------
# 1. 기본 경로와 상수
# ---------------------------------------------------------------------------
# 이 파일은 src 폴더 안에 있지만, templates/static/DB 파일은 프로젝트 루트에 둡니다.
# 그래서 현재 파일 위치(__file__)에서 부모 폴더를 두 번 올라가 BASE_DIR을 잡습니다.
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "project_progress.db"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# 화면에서 보여줄 기본 메시지입니다. 이스케이프 문자열이 아니라 한글을 직접 씁니다.
WAITING = "대기"
NOT_FOUND_MESSAGE = "작업을 찾을 수 없습니다."

# 상태는 사용자가 직접 입력하지 않고 공정준수율로 자동 계산합니다.
# DB에는 영문 코드로 저장하고, 화면(JavaScript)에서 초록/노랑/빨강으로 표시합니다.
GREEN = "green"
YELLOW = "yellow"
RED = "red"


# ---------------------------------------------------------------------------
# 2. FastAPI 앱, 정적 파일, HTML 템플릿 설정
# ---------------------------------------------------------------------------
# FastAPI 앱 객체는 웹 서버의 중심입니다.
# - "/" 요청은 HTML 화면을 반환합니다.
# - "/api/tasks" 요청은 JSON 데이터 CRUD를 처리합니다.
app = FastAPI(title="프로젝트 진척관리")

# /static/project_progress.css, /static/project_progress.js 처럼 접근할 수 있게 연결합니다.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# templates/project_progress.html 파일을 FastAPI에서 렌더링하기 위한 설정입니다.
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# 3. 브라우저에서 서버로 들어오는 입력값 검증 모델
# ---------------------------------------------------------------------------
class TaskPayload(BaseModel):
    """작업 등록/수정 시 브라우저가 보내는 JSON 구조입니다.

    중요한 점:
    - 사용자는 과제, Task, 날짜, 담당자, 산출물, 비고만 입력합니다.
    - 상태, 계획진척률, 실제진척률, 공정준수율은 이 모델에 없습니다.
      즉, 사용자가 개발자 도구로 값을 억지로 보내도 서버는 그 값을 받지 않습니다.
    - 계산값은 calculate_task_metrics()에서 서버가 다시 계산합니다.
    """

    project: str = Field(default="", max_length=200)
    task: str = Field(min_length=1, max_length=200)
    plan_start_date: Optional[str] = None
    plan_end_date: Optional[str] = None
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    owner: str = Field(default="", max_length=80)
    deliverable: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=300)

    @validator(
        "plan_start_date",
        "plan_end_date",
        "actual_start_date",
        "actual_end_date",
        pre=True,
    )
    def normalize_date(cls, value: Any) -> Optional[str]:
        """날짜 입력값을 YYYY-MM-DD 문자열로 정리합니다.

        HTML의 <input type="date">는 보통 "2026-05-08" 형식으로 값을 보냅니다.
        빈 값은 None으로 바꾸어 DB에 NULL로 저장되게 합니다.
        잘못된 날짜 문자열이 들어오면 사용자가 알 수 있도록 오류를 발생시킵니다.
        """
        if value is None or value == "":
            return None
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


# ---------------------------------------------------------------------------
# 4. SQLite DB 연결과 테이블 준비
# ---------------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    """SQLite 연결을 만들고, 조회 결과를 dict처럼 읽을 수 있게 설정합니다."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """프로그램 시작 또는 API 호출 시 DB 테이블을 준비합니다.

    SQLite는 파일 DB입니다. project_progress.db 파일이 없으면 자동으로 만들어지고,
    project_tasks 테이블이 없으면 CREATE TABLE로 새로 생성됩니다.

    이미 예전 버전의 DB가 있는 사용자를 위해 project/note 컬럼이 없을 경우
    ALTER TABLE로 자동 추가합니다. 이것을 간단한 마이그레이션이라고 부릅니다.
    """
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL DEFAULT '',
                task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '대기',
                plan_start_date TEXT,
                plan_end_date TEXT,
                plan_progress_rate INTEGER NOT NULL DEFAULT 0,
                actual_start_date TEXT,
                actual_end_date TEXT,
                actual_progress_rate INTEGER NOT NULL DEFAULT 0,
                completion_compliance_rate INTEGER NOT NULL DEFAULT 0,
                owner TEXT NOT NULL DEFAULT '',
                deliverable TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(project_tasks)").fetchall()
        }
        migrations = {
            "project": "ALTER TABLE project_tasks ADD COLUMN project TEXT NOT NULL DEFAULT ''",
            "note": "ALTER TABLE project_tasks ADD COLUMN note TEXT NOT NULL DEFAULT ''",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                connection.execute(statement)


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """sqlite3.Row 객체를 FastAPI가 JSON으로 반환하기 쉬운 dict로 바꿉니다."""
    return {key: row[key] for key in row.keys()}


# ---------------------------------------------------------------------------
# 5. 진척률과 신호등 계산 규칙
# ---------------------------------------------------------------------------
def parse_date(value: Optional[str]) -> Optional[date]:
    """DB/입력값의 날짜 문자열을 date 객체로 바꿉니다."""
    if not value:
        return None
    return date.fromisoformat(value)


def calculate_elapsed_rate(start_text: Optional[str], end_text: Optional[str], today: date) -> int:
    """시작일, 종료일, 오늘 날짜로 진행률을 0~100 사이의 정수로 계산합니다.

    계산 방식은 엑셀 파일의 공식과 같은 개념입니다.
    예를 들어 시작일이 5월 1일, 종료일이 5월 11일이고 오늘이 5월 8일이면
    전체 기간 10일 중 7일이 지난 것으로 보아 약 70%가 됩니다.

    날짜가 비어 있으면 계산할 수 없으므로 0%로 처리합니다.
    시작일과 종료일이 같은 경우에는 오늘이 시작일 이후면 100%, 이전이면 0%입니다.
    """
    start = parse_date(start_text)
    end = parse_date(end_text)
    if not start or not end:
        return 0
    if start == end:
        return 100 if today >= start else 0

    rate = (today - start).days / (end - start).days
    return round(max(0, min(1, rate)) * 100)


def calculate_task_metrics(payload: TaskPayload, today: Optional[date] = None) -> Dict[str, Any]:
    """작업 한 건의 계획진척률, 실제진척률, 공정준수율, 상태를 계산합니다.

    전체 규칙:
    1. 계획진척률 = 계획시작일/계획종료일/오늘 날짜로 계산합니다.
    2. 실제진척률 = 실제시작일/실제종료일을 우선 사용합니다.
       실제 날짜가 일부 비어 있으면 계획 날짜를 보조 기준으로 사용합니다.
       실제시작일과 실제종료일이 모두 비어 있으면 아직 실제 진행이 없다고 보고 0%입니다.
    3. 공정준수율 = 실제진척률 / 계획진척률입니다.
       100%를 넘지 않도록 최대값을 100으로 제한합니다.
    4. 상태 신호등:
       - 80% 이상: green
       - 50% 이상 80% 미만: yellow
       - 50% 미만: red
    """
    base_date = today or date.today()

    plan_progress_rate = calculate_elapsed_rate(
        payload.plan_start_date,
        payload.plan_end_date,
        base_date,
    )
    actual_progress_rate = calculate_elapsed_rate(
        payload.actual_start_date or payload.plan_start_date,
        payload.actual_end_date or payload.plan_end_date,
        base_date,
    )

    # 실제 일정이 전혀 입력되지 않은 작업은 실제진척률을 0으로 고정합니다.
    if not payload.actual_start_date and not payload.actual_end_date:
        actual_progress_rate = 0

    if plan_progress_rate == 0:
        completion_compliance_rate = 100 if actual_progress_rate > 0 else 0
    else:
        completion_compliance_rate = round(min(1, actual_progress_rate / plan_progress_rate) * 100)

    if completion_compliance_rate >= 80:
        status = GREEN
    elif completion_compliance_rate >= 50:
        status = YELLOW
    else:
        status = RED

    return {
        "status": status,
        "plan_progress_rate": plan_progress_rate,
        "actual_progress_rate": actual_progress_rate,
        "completion_compliance_rate": completion_compliance_rate,
    }


def refresh_task_metrics(connection: sqlite3.Connection) -> None:
    """목록을 보여주기 직전에 모든 작업의 계산값을 오늘 기준으로 다시 갱신합니다.

    계획진척률은 오늘 날짜가 바뀌면 자동으로 달라져야 합니다.
    그래서 DB에 저장된 값만 그대로 보여주지 않고, 조회할 때마다 다시 계산합니다.
    """
    rows = connection.execute(
        """
        SELECT id, project, task, plan_start_date, plan_end_date,
               actual_start_date, actual_end_date, owner, deliverable, note
        FROM project_tasks
        """
    ).fetchall()

    for row in rows:
        payload = TaskPayload(
            project=row["project"] or "",
            task=row["task"],
            plan_start_date=row["plan_start_date"],
            plan_end_date=row["plan_end_date"],
            actual_start_date=row["actual_start_date"],
            actual_end_date=row["actual_end_date"],
            owner=row["owner"] or "",
            deliverable=row["deliverable"] or "",
            note=row["note"] or "",
        )
        metrics = calculate_task_metrics(payload)
        connection.execute(
            """
            UPDATE project_tasks
            SET status = ?,
                plan_progress_rate = ?,
                actual_progress_rate = ?,
                completion_compliance_rate = ?
            WHERE id = ?
            """,
            (
                metrics["status"],
                metrics["plan_progress_rate"],
                metrics["actual_progress_rate"],
                metrics["completion_compliance_rate"],
                row["id"],
            ),
        )


# ---------------------------------------------------------------------------
# 6. FastAPI 라우트
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    """서버가 켜질 때 DB를 먼저 준비합니다."""
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """브라우저에서 첫 화면을 열 때 HTML을 반환합니다."""
    return templates.TemplateResponse("project_progress.html", {"request": request})


@app.get("/api/tasks")
def list_tasks() -> List[Dict[str, Any]]:
    """작업 목록을 JSON 배열로 반환합니다.

    화면의 JavaScript는 이 API를 호출해서 테이블을 그립니다.
    반환 직전에 refresh_task_metrics()를 호출하므로 오늘 기준 진척률이 반영됩니다.
    """
    init_db()
    with get_connection() as connection:
        refresh_task_metrics(connection)
        rows = connection.execute(
            """
            SELECT *
            FROM project_tasks
            ORDER BY
                CASE WHEN plan_start_date IS NULL THEN 1 ELSE 0 END,
                plan_start_date,
                id
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskPayload) -> Dict[str, Any]:
    """새 작업을 등록합니다.

    브라우저가 보낸 입력값을 그대로 저장하지 않고, 먼저 calculate_task_metrics()로
    상태/진척률/공정준수율을 계산한 뒤 함께 저장합니다.
    """
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    metrics = calculate_task_metrics(payload)

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO project_tasks (
                project, task, status, plan_start_date, plan_end_date, plan_progress_rate,
                actual_start_date, actual_end_date, actual_progress_rate,
                completion_compliance_rate, owner, deliverable, note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.project.strip(),
                payload.task.strip(),
                metrics["status"],
                payload.plan_start_date,
                payload.plan_end_date,
                metrics["plan_progress_rate"],
                payload.actual_start_date,
                payload.actual_end_date,
                metrics["actual_progress_rate"],
                metrics["completion_compliance_rate"],
                payload.owner.strip(),
                payload.deliverable.strip(),
                payload.note.strip(),
                now,
                now,
            ),
        )
        task_id = cursor.lastrowid
        row = connection.execute("SELECT * FROM project_tasks WHERE id = ?", (task_id,)).fetchone()

    return row_to_dict(row)


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskPayload) -> Dict[str, Any]:
    """기존 작업을 수정합니다.

    수정할 때도 등록과 같은 규칙을 사용합니다.
    사용자는 날짜와 텍스트만 바꾸고, 계산값은 서버가 다시 산출합니다.
    """
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    metrics = calculate_task_metrics(payload)

    with get_connection() as connection:
        exists = connection.execute("SELECT id FROM project_tasks WHERE id = ?", (task_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MESSAGE)

        connection.execute(
            """
            UPDATE project_tasks
            SET project = ?,
                task = ?,
                status = ?,
                plan_start_date = ?,
                plan_end_date = ?,
                plan_progress_rate = ?,
                actual_start_date = ?,
                actual_end_date = ?,
                actual_progress_rate = ?,
                completion_compliance_rate = ?,
                owner = ?,
                deliverable = ?,
                note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload.project.strip(),
                payload.task.strip(),
                metrics["status"],
                payload.plan_start_date,
                payload.plan_end_date,
                metrics["plan_progress_rate"],
                payload.actual_start_date,
                payload.actual_end_date,
                metrics["actual_progress_rate"],
                metrics["completion_compliance_rate"],
                payload.owner.strip(),
                payload.deliverable.strip(),
                payload.note.strip(),
                now,
                task_id,
            ),
        )
        row = connection.execute("SELECT * FROM project_tasks WHERE id = ?", (task_id,)).fetchone()

    return row_to_dict(row)


@app.delete("/api/tasks/{task_id}", status_code=204, response_class=Response)
def delete_task(task_id: int) -> Response:
    """작업 한 건을 삭제합니다.

    204 응답은 본문이 없어야 하므로 Response(status_code=204)를 명시합니다.
    """
    init_db()
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM project_tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MESSAGE)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 7. 직접 실행 진입점
# ---------------------------------------------------------------------------
# 아래 코드 덕분에 터미널에서 `py src\project_progress_app.py`로 바로 실행할 수 있습니다.
# uvicorn 명령을 직접 쓰고 싶다면 `py -m uvicorn src.project_progress_app:app --reload`도 가능합니다.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
