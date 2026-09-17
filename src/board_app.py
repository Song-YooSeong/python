"""게시판 샘플 프로그램.

FastAPI + SQLite + Jinja2 템플릿으로 만든 기본 게시판입니다.
같은 폴더의 `project_progress_app.py`와 같은 구조(웹 서버 + 파일 DB)를 따릅니다.

기능
    - 글 목록: 검색(제목/내용/작성자), 페이지 나누기
    - 글 상세: 조회수 자동 증가
    - 글 쓰기 / 수정 / 삭제: 글 작성 시 입력한 비밀번호로 본인 확인
    - 댓글 쓰기 / 삭제

실행
    py src\board_app.py
    (또는 py -m uvicorn src.board_app:app --reload --port 8001)
    브라우저에서 http://127.0.0.1:8001 로 접속합니다.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# ---------------------------------------------------------------------------
# 1. 기본 경로와 상수
# ---------------------------------------------------------------------------
# 이 파일은 src 폴더 안에 있지만, templates/static/DB 파일은 프로젝트 루트에 둡니다.
# 그래서 현재 파일 위치(__file__)에서 부모 폴더를 두 번 올라가 BASE_DIR을 잡습니다.
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "board.db"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

PAGE_SIZE = 10  # 한 페이지에 보여줄 글 개수
PAGE_BLOCK = 5  # 아래쪽 페이지 번호를 한 번에 몇 개 보여줄지

POST_NOT_FOUND = "글을 찾을 수 없습니다."
WRONG_PASSWORD = "비밀번호가 맞지 않습니다."

# 검색 종류입니다. 화면의 선택 상자 값과 DB 컬럼을 연결합니다.
SEARCH_FIELDS = {
    "title": "제목",
    "content": "내용",
    "writer": "작성자",
    "all": "제목+내용",
}


# ---------------------------------------------------------------------------
# 2. FastAPI 앱, 정적 파일, HTML 템플릿 설정
# ---------------------------------------------------------------------------
app = FastAPI(title="게시판 샘플")

# /static/board.css 처럼 접근할 수 있게 연결합니다.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# templates 폴더의 board_*.html 파일을 렌더링하기 위한 설정입니다.
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# 3. 비밀번호 저장/확인
# ---------------------------------------------------------------------------
# 비밀번호를 그대로 저장하면 DB 파일만 열어도 다 보입니다.
# 그래서 글마다 다른 소금값(salt)을 만들어 붙이고, 그 결과를 해시로 바꿔 저장합니다.
# 확인할 때는 같은 방법으로 다시 계산해서 저장된 값과 비교합니다.
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """비밀번호를 해시로 바꿉니다. (해시값, 소금값)을 돌려줍니다."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """입력한 비밀번호가 저장된 해시와 같은지 확인합니다."""
    candidate, _ = hash_password(password, salt)
    # secrets.compare_digest는 글자를 하나씩 비교하는 시간 차이를 없애 줍니다.
    return secrets.compare_digest(candidate, password_hash)


# ---------------------------------------------------------------------------
# 4. SQLite DB 연결과 테이블 준비
# ---------------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    """SQLite 연결을 만들고, 조회 결과를 dict처럼 읽을 수 있게 설정합니다."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    # 댓글이 달린 글을 지우면 댓글도 함께 지워지도록 외래키 기능을 켭니다.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    """DB 파일과 테이블을 준비합니다.

    SQLite는 파일 DB입니다. board.db 파일이 없으면 자동으로 만들어지고,
    테이블이 없으면 CREATE TABLE로 새로 생성됩니다.
    """
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS board_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                writer TEXT NOT NULL,
                content TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                view_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS board_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                writer TEXT NOT NULL,
                content TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES board_posts(id) ON DELETE CASCADE
            )
            """
        )
        # 목록은 최신 글부터 보여주므로 작성일 순서로 색인을 만들어 둡니다.
        connection.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON board_posts(created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_comments_post ON board_comments(post_id)")


def now_text() -> str:
    """화면에 그대로 보여줄 수 있는 현재 시각 문자열을 만듭니다."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 5. 입력값 정리
# ---------------------------------------------------------------------------
def clean_text(value: str, *, field: str, max_length: int, required: bool = True) -> str:
    """앞뒤 공백을 없애고 길이를 확인합니다.

    화면의 HTML에도 maxlength/required를 넣지만, 브라우저를 거치지 않고
    직접 요청을 보내는 경우가 있으므로 서버에서 한 번 더 확인합니다.
    """
    text = (value or "").strip()
    if required and not text:
        raise HTTPException(status_code=400, detail=f"{field}을(를) 입력해 주세요.")
    if len(text) > max_length:
        raise HTTPException(status_code=400, detail=f"{field}은(는) {max_length}자까지 입력할 수 있습니다.")
    return text


def load_post(connection: sqlite3.Connection, post_id: int) -> sqlite3.Row:
    """글 한 건을 읽고, 없으면 404 오류를 냅니다."""
    row = connection.execute("SELECT * FROM board_posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=POST_NOT_FOUND)
    return row


def build_page_numbers(page: int, total_pages: int) -> list[int]:
    """화면 아래에 보여줄 페이지 번호 목록을 만듭니다.

    글이 많아지면 번호가 끝없이 늘어나므로, 현재 페이지가 속한 묶음
    (1~5, 6~10 ...)만 보여줍니다.
    """
    if total_pages <= 0:
        return []
    block = (page - 1) // PAGE_BLOCK
    start = block * PAGE_BLOCK + 1
    end = min(start + PAGE_BLOCK - 1, total_pages)
    return list(range(start, end + 1))


# ---------------------------------------------------------------------------
# 6. 화면(HTML)을 돌려주는 경로
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def post_list(
    request: Request,
    page: int = 1,
    keyword: str = "",
    field: str = "all",
) -> HTMLResponse:
    """글 목록 화면입니다. 검색어와 페이지 번호를 받습니다."""
    init_db()
    keyword = keyword.strip()
    if field not in SEARCH_FIELDS:
        field = "all"
    page = max(page, 1)

    # 검색 조건을 WHERE 절로 만듭니다. 값은 ? 자리표시자로 넘겨 SQL 주입을 막습니다.
    where = ""
    params: list[Any] = []
    if keyword:
        like = f"%{keyword}%"
        if field == "title":
            where = "WHERE title LIKE ?"
            params = [like]
        elif field == "content":
            where = "WHERE content LIKE ?"
            params = [like]
        elif field == "writer":
            where = "WHERE writer LIKE ?"
            params = [like]
        else:
            where = "WHERE title LIKE ? OR content LIKE ?"
            params = [like, like]

    with get_connection() as connection:
        total_count = connection.execute(
            f"SELECT COUNT(*) FROM board_posts {where}", params
        ).fetchone()[0]

        total_pages = max(math.ceil(total_count / PAGE_SIZE), 1)
        page = min(page, total_pages)
        offset = (page - 1) * PAGE_SIZE

        rows = connection.execute(
            f"""
            SELECT p.id, p.title, p.writer, p.view_count, p.created_at,
                   (SELECT COUNT(*) FROM board_comments c WHERE c.post_id = p.id) AS comment_count
            FROM board_posts p
            {where}
            ORDER BY p.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, PAGE_SIZE, offset],
        ).fetchall()

    return templates.TemplateResponse(
        "board_list.html",
        {
            "request": request,
            "posts": rows,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_numbers": build_page_numbers(page, total_pages),
            "keyword": keyword,
            "field": field,
            "search_fields": SEARCH_FIELDS,
            # 목록의 번호는 최신 글이 큰 번호가 되도록 전체 개수에서 거꾸로 셉니다.
            "start_number": total_count - offset,
        },
    )


@app.get("/posts/new", response_class=HTMLResponse)
def new_post_form(request: Request) -> HTMLResponse:
    """글쓰기 화면입니다."""
    init_db()
    return templates.TemplateResponse(
        "board_form.html",
        {"request": request, "post": None, "mode": "new", "error": ""},
    )


@app.get("/posts/{post_id}", response_class=HTMLResponse)
def post_detail(request: Request, post_id: int, page: int = 1, keyword: str = "", field: str = "all") -> HTMLResponse:
    """글 상세 화면입니다. 한 번 열 때마다 조회수를 1 올립니다."""
    init_db()
    with get_connection() as connection:
        load_post(connection, post_id)
        connection.execute("UPDATE board_posts SET view_count = view_count + 1 WHERE id = ?", (post_id,))
        post = load_post(connection, post_id)
        comments = connection.execute(
            "SELECT id, writer, content, created_at FROM board_comments WHERE post_id = ? ORDER BY id ASC",
            (post_id,),
        ).fetchall()

    return templates.TemplateResponse(
        "board_detail.html",
        {
            "request": request,
            "post": post,
            "comments": comments,
            # 목록으로 돌아갈 때 보던 페이지와 검색어를 유지하기 위해 그대로 넘깁니다.
            "page": page,
            "keyword": keyword,
            "field": field,
        },
    )


@app.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_form(request: Request, post_id: int) -> HTMLResponse:
    """글 수정 화면입니다. 저장할 때 비밀번호를 확인합니다."""
    init_db()
    with get_connection() as connection:
        post = load_post(connection, post_id)
    return templates.TemplateResponse(
        "board_form.html",
        {"request": request, "post": post, "mode": "edit", "error": ""},
    )


# ---------------------------------------------------------------------------
# 7. 화면에서 보낸 폼을 처리하는 경로
# ---------------------------------------------------------------------------
# 처리 후에는 RedirectResponse로 목록/상세 화면으로 보냅니다.
# 이렇게 하면 브라우저에서 새로 고침을 눌러도 같은 글이 두 번 등록되지 않습니다.
@app.post("/posts")
def create_post(
    title: str = Form(...),
    writer: str = Form(...),
    password: str = Form(...),
    content: str = Form(...),
) -> RedirectResponse:
    """글을 새로 등록합니다."""
    init_db()
    title = clean_text(title, field="제목", max_length=200)
    writer = clean_text(writer, field="작성자", max_length=40)
    content = clean_text(content, field="내용", max_length=10_000)
    password = clean_text(password, field="비밀번호", max_length=100)

    password_hash, salt = hash_password(password)
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO board_posts (title, writer, content, password_hash, password_salt, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, writer, content, password_hash, salt, now_text()),
        )
        new_id = cursor.lastrowid
    return RedirectResponse(url=f"/posts/{new_id}", status_code=303)


@app.post("/posts/{post_id}/edit")
def update_post(
    request: Request,
    post_id: int,
    title: str = Form(...),
    content: str = Form(...),
    password: str = Form(...),
) -> Any:
    """글을 수정합니다. 비밀번호가 맞지 않으면 수정 화면에 오류를 보여 줍니다."""
    init_db()
    title = clean_text(title, field="제목", max_length=200)
    content = clean_text(content, field="내용", max_length=10_000)

    with get_connection() as connection:
        post = load_post(connection, post_id)
        if not verify_password(password, post["password_hash"], post["password_salt"]):
            # 입력한 제목/내용은 그대로 두고 오류만 보여 주어 다시 쓰지 않게 합니다.
            return templates.TemplateResponse(
                "board_form.html",
                {
                    "request": request,
                    "post": {"id": post_id, "title": title, "writer": post["writer"], "content": content},
                    "mode": "edit",
                    "error": WRONG_PASSWORD,
                },
                status_code=400,
            )
        connection.execute(
            "UPDATE board_posts SET title = ?, content = ?, updated_at = ? WHERE id = ?",
            (title, content, now_text(), post_id),
        )
    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/delete")
def delete_post(request: Request, post_id: int, password: str = Form(...)) -> Any:
    """글을 삭제합니다. 댓글도 함께 삭제됩니다(ON DELETE CASCADE)."""
    init_db()
    with get_connection() as connection:
        post = load_post(connection, post_id)
        if not verify_password(password, post["password_hash"], post["password_salt"]):
            comments = connection.execute(
                "SELECT id, writer, content, created_at FROM board_comments WHERE post_id = ? ORDER BY id ASC",
                (post_id,),
            ).fetchall()
            return templates.TemplateResponse(
                "board_detail.html",
                {
                    "request": request,
                    "post": post,
                    "comments": comments,
                    "page": 1,
                    "keyword": "",
                    "field": "all",
                    "error": WRONG_PASSWORD,
                },
                status_code=400,
            )
        connection.execute("DELETE FROM board_posts WHERE id = ?", (post_id,))
    return RedirectResponse(url="/", status_code=303)


@app.post("/posts/{post_id}/comments")
def create_comment(
    post_id: int,
    writer: str = Form(...),
    password: str = Form(...),
    content: str = Form(...),
) -> RedirectResponse:
    """댓글을 등록합니다."""
    init_db()
    writer = clean_text(writer, field="작성자", max_length=40)
    content = clean_text(content, field="댓글 내용", max_length=1_000)
    password = clean_text(password, field="비밀번호", max_length=100)

    password_hash, salt = hash_password(password)
    with get_connection() as connection:
        load_post(connection, post_id)
        connection.execute(
            """
            INSERT INTO board_comments (post_id, writer, content, password_hash, password_salt, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (post_id, writer, content, password_hash, salt, now_text()),
        )
    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


@app.post("/posts/{post_id}/comments/{comment_id}/delete")
def delete_comment(post_id: int, comment_id: int, password: str = Form(...)) -> RedirectResponse:
    """댓글을 삭제합니다. 비밀번호가 맞아야 지워집니다."""
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM board_comments WHERE id = ? AND post_id = ?", (comment_id, post_id)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
        if not verify_password(password, row["password_hash"], row["password_salt"]):
            raise HTTPException(status_code=400, detail=WRONG_PASSWORD)
        connection.execute("DELETE FROM board_comments WHERE id = ?", (comment_id,))
    return RedirectResponse(url=f"/posts/{post_id}", status_code=303)


# ---------------------------------------------------------------------------
# 8. 직접 실행 진입점
# ---------------------------------------------------------------------------
# 아래 코드 부분이 있어서 터미널에서 `py src\board_app.py`로 바로 실행할 수 있습니다.
# 다른 샘플(project_progress_app.py)이 8000번을 쓰므로 게시판은 8001번을 사용합니다.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("BOARD_PORT", "8001")))
