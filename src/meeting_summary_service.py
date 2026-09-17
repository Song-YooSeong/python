from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
from openai import OpenAI

def get_app_dir() -> Path:
    """실행 환경에 맞는 애플리케이션 폴더를 반환합니다."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_app_dir()
LOG_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE_PATH = CONFIG_DIR / "openai_config.json"
LOG_FILE_PATH = LOG_DIR / "meeting_summary_app_error.log"

TRANSCRIPTION_CHUNK_SECONDS = 5 * 60
DIRECT_SUMMARY_MAX_CHARS = 60_000
TRANSCRIPT_SUMMARY_CHUNK_CHARS = 40_000

# ----------------------------------------------------------------------
# Word 저장 서식
#
# 아래 값은 참조 회의록
# "한국은행-네이버 협업회의록_20260903.docx"를 Word로 열어 실제 적용된 값을
# 그대로 읽어 온 것입니다. 이 문서와 같은 모양으로 저장하기 위한 설정입니다.
# ----------------------------------------------------------------------
WORD_FONT_NAME = "나눔스퀘어"  # 참조 문서의 본문 글꼴
WORD_TITLE_FONT_SIZE_PT = 12  # 문서 제목과 큰 절 제목 (굵게)
WORD_SUBTITLE_FONT_SIZE_PT = 10  # "주요 안건" 같은 작은 소제목 (굵게)
WORD_BODY_FONT_SIZE_PT = 10  # 본문과 목록 내용
WORD_PAGE_MARGIN_CM = 1.27  # 참조 문서의 사방 여백

# 참조 문서의 글머리 기호는 Word 기본 조합인 Symbol "" 와 Courier New "o"를
# 번갈아 사용합니다. 기호마다 전용 글꼴을 쓰기 때문에 크기를 따로 보정하지 않아도
# 모두 같은 크기(10pt)로 보입니다.
BULLET_LEVEL_STYLES = (
    ("", "Symbol"),  # 1단계: 채운 원
    ("o", "Courier New"),  # 2단계: 빈 원
)
# 참조 문서의 목록 들여쓰기(Word가 보고한 실제 값)입니다.
BULLET_FIRST_INDENT_PT = 26.35  # 1단계 문단 왼쪽 여백 (0.93cm)
BULLET_INDENT_STEP_PT = 10.5  # 한 단계 내려갈 때마다 늘어나는 폭 (0.37cm)
BULLET_HANGING_INDENT_PT = 8.5  # 기호와 글자를 갈라 놓는 내어쓰기 (0.3cm)
BULLET_SPACE_BEFORE_FIRST_PT = 5  # 목록 첫 항목 위 간격
BULLET_SPACE_BEFORE_PT = 3  # 이어지는 항목 위 간격
BULLET_SPACE_AFTER_PT = 5  # 목록 항목 아래 간격

BULLET_LEVEL_COUNT = 9  # Word 글머리 기호 목록이 지원하는 단계 수
# 이 프로그램이 만든 글머리 기호 정의를 다시 찾기 위한 표시입니다("MEET"의 16진수).
BULLET_NUMBERING_NSID = "4D454554"

# 요약문(Markdown)을 Word 문단으로 바꾸기 위한 표현식입니다.
MD_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
MD_BULLET_PATTERN = re.compile(r"^(\s*)[-*+]\s+(.*)$")
MD_NUMBERED_PATTERN = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
MD_BOLD_ONLY_PATTERN = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*$")
MD_RULE_PATTERN = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")
MD_TABLE_DIVIDER_PATTERN = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")
MD_INLINE_PATTERN = re.compile(r"(\*\*.+?\*\*|__.+?__|\*[^*\s].*?\*|`.+?`)")

DEFAULT_CONFIG = {
    "api_key": "",
    "summary_model": "",
    "transcription_model": "gpt-4o-mini-transcribe",
    "meeting_language": "ko",
}


def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meeting_summary_app")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


logger = configure_logging()


def build_error_details(exc: Exception) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def log_exception_to_file(*, title: str, request=None, exc: Exception | None = None, extra_message: str | None = None) -> None:
    message_lines = [title]
    if request is not None:
        message_lines.extend([f"method={request.method}", f"url={request.url}"])
    if extra_message:
        message_lines.append(extra_message)
    if exc is not None:
        message_lines.extend([
            f"exception_type={type(exc).__name__}",
            f"exception_message={exc}",
            build_error_details(exc),
        ])
    logger.error("\n".join(message_lines))


def ensure_config_file() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE_PATH.exists():
        CONFIG_FILE_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def load_openai_config() -> dict[str, str]:
    ensure_config_file()
    try:
        raw_config = json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI 설정 JSON 형식이 올바르지 않습니다: {CONFIG_FILE_PATH}") from exc
    config = {**DEFAULT_CONFIG, **raw_config}
    return {key: str(value).strip() for key, value in config.items()}


def _style_run(run, *, size_pt: float, bold: bool = False, italic: bool = False, color: RGBColor | None = None) -> None:
    """글자 하나하나(run)에 글꼴 이름과 크기를 지정합니다.

    한글은 `w:eastAsia` 글꼴을 따로 지정해야 Word에서 같은 글꼴로 보입니다.
    """
    run.font.name = WORD_FONT_NAME
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    run._element.rPr.rFonts.set(qn("w:eastAsia"), WORD_FONT_NAME)


def _strip_inline_marks(text: str) -> tuple[str, bool, bool, bool]:
    """`**굵게**`, `*기울임*`, `` `코드` `` 표시를 떼어내고 서식 정보를 돌려줍니다."""
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        return text[2:-2], True, False, False
    if text.startswith("__") and text.endswith("__") and len(text) > 4:
        return text[2:-2], True, False, False
    if text.startswith("`") and text.endswith("`") and len(text) > 2:
        return text[1:-1], False, False, True
    if text.startswith("*") and text.endswith("*") and len(text) > 2:
        return text[1:-1], False, True, False
    return text, False, False, False


def _add_markdown_text(paragraph, text: str, *, size_pt: int, bold: bool = False) -> None:
    """한 문단 안의 Markdown 강조 표시를 Word 서식으로 바꿔 넣습니다."""
    if not text:
        return
    for part in MD_INLINE_PATTERN.split(text):
        if not part:
            continue
        content, is_bold, is_italic, is_code = _strip_inline_marks(part)
        if not content:
            continue
        run = paragraph.add_run(content)
        _style_run(run, size_pt=size_pt, bold=bold or is_bold, italic=is_italic)
        if is_code:
            run.font.name = "Consolas"


def _add_heading_paragraph(document: Document, text: str, *, level: int = 1) -> None:
    """제목 문단을 추가합니다.

    참조 문서를 따라 큰 제목(문서 제목, 번호 절 제목)은 12pt 굵은 글씨,
    그 아래 소제목("주요 안건" 등)은 10pt 굵은 글씨로 넣습니다.
    """
    size_pt = WORD_TITLE_FONT_SIZE_PT if level <= 2 else WORD_SUBTITLE_FONT_SIZE_PT
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(7.5 if level > 1 else 0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.keep_with_next = True
    _add_markdown_text(paragraph, text, size_pt=size_pt, bold=True)


def _bullet_level_style(level: int) -> tuple[str, str]:
    """목록 단계에 맞는 (기호, 기호 글꼴)을 돌려줍니다.

    참조 문서처럼 Symbol "" 와 Courier New "o"를 번갈아 사용합니다.
    """
    return BULLET_LEVEL_STYLES[level % len(BULLET_LEVEL_STYLES)]


def _bullet_indent_pt(level: int) -> float:
    """목록 단계별 문단 왼쪽 여백(pt)을 돌려줍니다."""
    return BULLET_FIRST_INDENT_PT + BULLET_INDENT_STEP_PT * level


def _build_bullet_abstract_num_xml(abstract_num_id: int) -> str:
    """Word의 다단계 글머리 기호 정의(w:abstractNum)를 만듭니다.

    참조 문서와 같은 기호/글꼴/들여쓰기를 단계별로 지정합니다.
    `w:suff`는 넣지 않아 Word 기본값(탭)을 그대로 사용합니다.
    """
    levels = []
    # Word는 글자 크기를 0.5pt 단위(half-point)로 저장합니다.
    half_points = int(round(WORD_BODY_FONT_SIZE_PT * 2))
    for level in range(BULLET_LEVEL_COUNT):
        symbol, symbol_font = _bullet_level_style(level)
        indent_twips = Pt(_bullet_indent_pt(level)).twips
        hanging_twips = Pt(BULLET_HANGING_INDENT_PT).twips
        levels.append(
            f'<w:lvl w:ilvl="{level}">'
            f'<w:start w:val="1"/>'
            f'<w:numFmt w:val="bullet"/>'
            f'<w:lvlText w:val="{symbol}"/>'
            f'<w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="{indent_twips}" w:hanging="{hanging_twips}"/></w:pPr>'
            f'<w:rPr>'
            f'<w:rFonts w:ascii="{symbol_font}" w:hAnsi="{symbol_font}" w:hint="default"/>'
            f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>'
            f'</w:rPr>'
            f'</w:lvl>'
        )
    return (
        f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abstract_num_id}">'
        f'<w:nsid w:val="{BULLET_NUMBERING_NSID}"/>'
        f'<w:multiLevelType w:val="hybridMultilevel"/>'
        f'<w:name w:val="회의자료 글머리 기호"/>'
        + "".join(levels)
        + "</w:abstractNum>"
    )


def ensure_bullet_numbering(document: Document) -> int:
    """문서에 글머리 기호 목록 정의를 넣고 그 numId를 돌려줍니다.

    이미 만들어 둔 정의가 있으면 그대로 다시 사용합니다.
    """
    numbering = document.part.numbering_part.element

    # 이미 이 프로그램이 만든 정의가 있는지 nsid 표시로 찾습니다.
    for abstract_num in numbering.findall(qn("w:abstractNum")):
        nsid = abstract_num.find(qn("w:nsid"))
        if nsid is None or nsid.get(qn("w:val")) != BULLET_NUMBERING_NSID:
            continue
        abstract_id = abstract_num.get(qn("w:abstractNumId"))
        for num in numbering.findall(qn("w:num")):
            reference = num.find(qn("w:abstractNumId"))
            if reference is not None and reference.get(qn("w:val")) == abstract_id:
                return int(num.get(qn("w:numId")))

    used_abstract_ids = [
        int(element.get(qn("w:abstractNumId"))) for element in numbering.findall(qn("w:abstractNum"))
    ]
    used_num_ids = [int(element.get(qn("w:numId"))) for element in numbering.findall(qn("w:num"))]
    abstract_num_id = max(used_abstract_ids, default=-1) + 1
    num_id = max(used_num_ids, default=0) + 1

    abstract_element = parse_xml(_build_bullet_abstract_num_xml(abstract_num_id))
    # numbering.xml은 abstractNum이 모두 앞에, num이 모두 뒤에 와야 합니다.
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract_element)
    else:
        numbering.append(abstract_element)
    numbering.append(
        parse_xml(
            f'<w:num {nsdecls("w")} w:numId="{num_id}">'
            f'<w:abstractNumId w:val="{abstract_num_id}"/>'
            f"</w:num>"
        )
    )
    return num_id


def _add_bullet_paragraph(
    document: Document, text: str, *, level: int, num_id: int, is_first: bool = False
) -> None:
    """Word의 글머리 기호 목록으로 동작하는 문단을 추가합니다.

    기호는 목록 정의가 만들고, 들여쓰기는 참조 문서처럼 문단에도 같은 값을
    지정합니다. Word에서 Tab/Shift+Tab으로 단계를 바꾸면 기호도 함께 바뀝니다.
    """
    level = min(level, BULLET_LEVEL_COUNT - 1)
    paragraph = document.add_paragraph()
    paragraph_format = paragraph.paragraph_format
    paragraph_format.space_before = Pt(
        BULLET_SPACE_BEFORE_FIRST_PT if is_first else BULLET_SPACE_BEFORE_PT
    )
    paragraph_format.space_after = Pt(BULLET_SPACE_AFTER_PT)
    paragraph_format.left_indent = Pt(_bullet_indent_pt(level))
    # 음수 first_line_indent가 Word의 "내어쓰기"입니다.
    paragraph_format.first_line_indent = Pt(-BULLET_HANGING_INDENT_PT)
    numbering_properties = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    numbering_properties.get_or_add_ilvl().val = level
    numbering_properties.get_or_add_numId().val = num_id
    _add_markdown_text(paragraph, text, size_pt=WORD_BODY_FONT_SIZE_PT)


def _add_body_paragraph(document: Document, text: str, *, indent_level: int = 0, marker: str = "") -> None:
    """본문 문단을 10pt로 추가합니다.

    `marker`를 주면 번호 목록("1.")처럼 보이게 하고, 들여쓰기는 글머리 기호
    목록과 같은 단계 폭을 사용해 문서 전체의 줄이 맞도록 합니다.
    """
    paragraph = document.add_paragraph()
    paragraph_format = paragraph.paragraph_format
    if marker:
        paragraph_format.space_before = Pt(BULLET_SPACE_BEFORE_PT)
        paragraph_format.space_after = Pt(BULLET_SPACE_AFTER_PT)
        paragraph_format.left_indent = Pt(_bullet_indent_pt(indent_level))
        paragraph_format.first_line_indent = Pt(-BULLET_HANGING_INDENT_PT)
        marker_run = paragraph.add_run(f"{marker}\t")
        _style_run(marker_run, size_pt=WORD_BODY_FONT_SIZE_PT)
    else:
        paragraph_format.space_before = Pt(7.5 if indent_level == 0 else 0)
        paragraph_format.space_after = Pt(0)
        if indent_level:
            paragraph_format.left_indent = Pt(_bullet_indent_pt(indent_level - 1))
    _add_markdown_text(paragraph, text, size_pt=WORD_BODY_FONT_SIZE_PT)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _add_markdown_table(document: Document, rows: list[str]) -> None:
    """Markdown 표를 Word 표로 바꿉니다.

    참조 문서의 표처럼 테두리가 있는 Table Grid를 쓰고, 머리글은 10pt 굵은
    글씨, 내용은 10pt로 넣습니다.
    """
    header_cells = _split_table_row(rows[0])
    body_rows = [_split_table_row(row) for row in rows[1:]]
    column_count = max([len(header_cells)] + [len(row) for row in body_rows])
    table = document.add_table(rows=1, cols=column_count)
    table.style = "Table Grid"
    for index, cell_text in enumerate(header_cells):
        # 새 셀의 첫 문단은 비어 있으므로 그대로 사용합니다.
        _add_markdown_text(table.rows[0].cells[index].paragraphs[0], cell_text, size_pt=WORD_BODY_FONT_SIZE_PT, bold=True)
    for body_row in body_rows:
        cells = table.add_row().cells
        for index, cell_text in enumerate(body_row[:column_count]):
            _add_markdown_text(cells[index].paragraphs[0], cell_text, size_pt=WORD_BODY_FONT_SIZE_PT)


def _split_leading_heading(markdown_text: str) -> tuple[str, str]:
    """요약문 맨 앞의 큰 제목(`# 제목`)과 나머지 본문을 나눠서 돌려줍니다."""
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        heading_match = MD_HEADING_PATTERN.match(line.strip())
        if heading_match and len(heading_match.group(1)) == 1:
            return heading_match.group(2).strip(), "\n".join(lines[index + 1:])
        return "", markdown_text
    return "", markdown_text


def _resolve_list_level(indent_widths: list[int], indent_width: int) -> int:
    """앞선 목록 줄과 비교해서 이 줄이 몇 번째 하위 단계인지 계산합니다.

    Markdown은 들여쓰기를 2칸으로도 4칸으로도 쓰기 때문에 칸 수를 그대로
    나누면 단계가 건너뛸 수 있습니다. 지금까지 나온 들여쓰기 너비를 쌓아 두고
    순서대로 0, 1, 2단계를 매기면 두 경우 모두 올바르게 처리됩니다.
    """
    while indent_widths and indent_width < indent_widths[-1]:
        indent_widths.pop()
    if not indent_widths or indent_width > indent_widths[-1]:
        indent_widths.append(indent_width)
    return len(indent_widths) - 1


def render_markdown_to_document(document: Document, markdown_text: str) -> None:
    """OpenAI가 만든 Markdown 요약문을 Word 문단으로 옮깁니다.

    제목(`#`, `##`, `**제목**`)은 12pt 굵은 글씨, 나머지 본문과 목록은 10pt로
    저장합니다. 글머리 기호 목록은 Word의 글머리 기호 기능으로 만들어서
    Word에서 열었을 때 실제 목록처럼 단계를 바꾸고 이어 쓸 수 있습니다.
    """
    bullet_num_id = ensure_bullet_numbering(document)
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    # 이어지는 목록에서만 단계를 세고, 목록이 끝나면 비웁니다.
    indent_widths: list[int] = []
    index = 0
    while index < len(lines):
        # 탭은 공백 4칸으로 바꿔 들여쓰기 너비를 일관되게 셉니다.
        line = lines[index].expandtabs(4).rstrip()
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if MD_RULE_PATTERN.match(stripped):
            indent_widths.clear()
            index += 1
            continue

        # 표는 머리글 줄과 구분선 줄이 이어서 나옵니다.
        if stripped.startswith("|") and index + 1 < len(lines) and MD_TABLE_DIVIDER_PATTERN.match(lines[index + 1]):
            table_rows = [stripped]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_rows.append(lines[index].strip())
                index += 1
            _add_markdown_table(document, table_rows)
            indent_widths.clear()
            continue

        heading_match = MD_HEADING_PATTERN.match(stripped)
        if heading_match:
            _add_heading_paragraph(document, heading_match.group(2).strip(), level=len(heading_match.group(1)))
            indent_widths.clear()
            index += 1
            continue

        bullet_match = MD_BULLET_PATTERN.match(line)
        if bullet_match:
            # Word의 글머리 기호 목록으로 넣어 단계별 기호를 Word가 만들게 합니다.
            # 참조 문서처럼 목록의 첫 항목만 위 간격을 조금 더 줍니다.
            is_first_item = not indent_widths
            indent_level = _resolve_list_level(indent_widths, len(bullet_match.group(1)))
            _add_bullet_paragraph(
                document,
                bullet_match.group(2).strip(),
                level=indent_level,
                num_id=bullet_num_id,
                is_first=is_first_item,
            )
            index += 1
            continue

        numbered_match = MD_NUMBERED_PATTERN.match(line)
        if numbered_match:
            content = numbered_match.group(3).strip()
            number = numbered_match.group(2)
            # "1. 회의 개요"처럼 번호 뒤가 통째로 굵은 글씨면 절 제목으로 봅니다.
            bold_only = MD_BOLD_ONLY_PATTERN.match(content)
            if bold_only and not numbered_match.group(1):
                _add_heading_paragraph(document, f"{number}. {bold_only.group(1).strip()}", level=2)
                indent_widths.clear()
            else:
                # 번호 목록은 번호를 그대로 쓰고 들여쓰기 규칙만 같이 적용합니다.
                indent_level = _resolve_list_level(indent_widths, len(numbered_match.group(1)))
                _add_body_paragraph(document, content, indent_level=indent_level, marker=f"{number}.")
            index += 1
            continue

        # 줄 전체가 굵은 글씨면 절 제목으로 처리합니다.
        bold_only = MD_BOLD_ONLY_PATTERN.match(stripped)
        if bold_only:
            _add_heading_paragraph(document, bold_only.group(1).strip(), level=2)
            indent_widths.clear()
            index += 1
            continue

        _add_body_paragraph(document, stripped)
        indent_widths.clear()
        index += 1


class MeetingSummaryService:
    def __init__(self, config_path: Path = CONFIG_FILE_PATH) -> None:
        self.config_path = config_path

    def _get_client(self, config: dict[str, str]) -> OpenAI:
        api_key = config.get("api_key", "")
        if not api_key:
            raise RuntimeError(f"OpenAI API key가 없습니다. {self.config_path} 파일의 api_key에 값을 넣어주세요.")
        return OpenAI(api_key=api_key)

    def list_models(self) -> list[str]:
        """OpenAI 계정에서 사용할 수 있는 모델 ID를 최신 목록으로 가져옵니다."""

        config = load_openai_config()
        client = self._get_client(config)
        models = client.models.list()
        model_ids = {
            str(getattr(model, "id", "")).strip()
            for model in models.data
        }
        return sorted(model_id for model_id in model_ids if model_id)

    def _resolve_model(self, *, config: dict[str, str], selected_model: str) -> str:
        """사용자 선택 모델 또는 OpenAI에서 조회한 첫 모델을 결정합니다."""

        if selected_model.strip():
            return selected_model.strip()
        configured_model = config.get("summary_model", "").strip()
        if configured_model:
            return configured_model
        available_models = self.list_models()
        if not available_models:
            raise RuntimeError("OpenAI에서 사용할 수 있는 모델을 찾지 못했습니다.")
        return available_models[0]

    def _find_ffmpeg(self) -> str:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path
        local_ffmpeg = BASE_DIR / "ffmpeg.exe"
        if local_ffmpeg.exists():
            return str(local_ffmpeg)
        raise RuntimeError("긴 오디오 처리를 위해 ffmpeg가 필요합니다. ffmpeg를 설치하거나 프로젝트 폴더에 넣어 주세요.")

    def _split_audio_for_transcription(self, audio_path: Path, output_dir: Path) -> list[Path]:
        command = [
            self._find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_path),
            "-vn", "-map", "0:a:0", "-f", "segment", "-segment_time", str(TRANSCRIPTION_CHUNK_SECONDS),
            "-reset_timestamps", "1", "-c:a", "libmp3lame", "-b:a", "64k",
            str(output_dir / "transcription_chunk_%03d.mp3"),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=60 * 30)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"오디오 분할 중 오류가 발생했습니다: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"오디오 파일을 분할하지 못했습니다. ffmpeg 오류: {detail}")
        chunk_paths = sorted(output_dir.glob("transcription_chunk_*.mp3"))
        if not chunk_paths:
            raise RuntimeError("전사할 오디오 조각 파일이 만들어지지 않았습니다.")
        return chunk_paths

    def _transcribe_audio_file(self, *, client: OpenAI, transcription_model: str, audio_path: Path, prompt: str, language: str) -> str:
        with audio_path.open("rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=transcription_model, file=audio_file, prompt=prompt or None, language=language or None,
            )
        return (getattr(transcription, "text", "") or "").strip()

    def _split_text_by_chars(self, text: str, chunk_size: int) -> list[str]:
        chunks: list[str] = []
        current_lines: list[str] = []
        current_size = 0
        for line in text.splitlines():
            line_size = len(line) + 1
            if current_lines and current_size + line_size > chunk_size:
                chunks.append("\n".join(current_lines).strip())
                current_lines = []
                current_size = 0
            current_lines.append(line)
            current_size += line_size
        if current_lines:
            chunks.append("\n".join(current_lines).strip())
        return [chunk for chunk in chunks if chunk]

    def _request_meeting_summary(self, *, client: OpenAI, summary_model: str, source_name: str, title: str, focus: str, output_language: str, transcript: str, mode_note: str = "") -> str:
        response = client.responses.create(
            model=summary_model,
            instructions="You are an expert meeting assistant. Summarize meeting transcripts into clear, actionable meeting materials. Use the requested output language. Do not invent facts.",
            input=(
                f"Output language: {output_language}\nMeeting title: {title}\nSource file: {source_name}\n"
                f"Summary focus: {focus}\n{mode_note}\n\n"
                "Create meeting materials with these sections:\n"
                "1. 회의 개요\n2. 핵심 요약\n3. 주요 논의 내용\n4. 결정 사항\n"
                "5. 후속 조치(Action Items) - 담당자와 기한이 없으면 '미정'으로 표시\n"
                "6. 리스크 및 확인 필요 사항\n\n"
                f"Transcript:\n{transcript}"
            ),
        )
        summary = (getattr(response, "output_text", "") or "").strip()
        if not summary:
            raise RuntimeError("OpenAI 요약 응답이 비어 있습니다.")
        return summary

    def transcribe_audio(self, audio_path: Path, filename: str, prompt: str, language: str) -> str:
        config = load_openai_config()
        client = self._get_client(config)
        transcription_model = config.get("transcription_model") or DEFAULT_CONFIG["transcription_model"]
        with tempfile.TemporaryDirectory(prefix="meeting-audio-chunks-") as chunk_dir_name:
            chunk_paths = self._split_audio_for_transcription(audio_path, Path(chunk_dir_name))
            transcript_parts: list[str] = []
            for index, chunk_path in enumerate(chunk_paths, start=1):
                chunk_prompt = prompt
                if len(chunk_paths) > 1:
                    chunk_prompt = f"{prompt}\n\nThis is part {index} of {len(chunk_paths)} from the same meeting recording. Keep names and terms consistent with the previous and next parts.".strip()
                chunk_text = self._transcribe_audio_file(client=client, transcription_model=transcription_model, audio_path=chunk_path, prompt=chunk_prompt, language=language)
                if chunk_text:
                    transcript_parts.append(f"[Part {index}/{len(chunk_paths)}]\n{chunk_text}")
        return "\n\n".join(transcript_parts).strip()

    def summarize_meeting(self, *, transcript: str, source_name: str, meeting_title: str, summary_focus: str, language: str, model: str = "") -> str:
        """전사문을 OpenAI에 보내 회의자료 형식으로 요약합니다.

        `model`이 비어 있으면 설정 파일의 기본 요약 모델을 사용합니다.
        값이 있으면 화면에서 사용자가 선택한 모델을 우선 사용합니다.
        """
        if not transcript:
            raise RuntimeError("전사 결과가 비어 있어 회의 요약을 만들 수 없습니다.")
        config = load_openai_config()
        client = self._get_client(config)
        # 우선순위: 화면에서 선택한 모델 -> 설정 파일의 모델 -> OpenAI 조회 결과의 첫 모델
        summary_model = self._resolve_model(config=config, selected_model=model)
        title = meeting_title.strip() or Path(source_name).stem or "회의"
        focus = summary_focus.strip() or "핵심 논의, 결정 사항, 후속 조치 목록을 중심으로 정리"
        output_language = language.strip() or config.get("meeting_language") or "ko"
        if len(transcript) <= DIRECT_SUMMARY_MAX_CHARS:
            return self._request_meeting_summary(client=client, summary_model=summary_model, source_name=source_name, title=title, focus=focus, output_language=output_language, transcript=transcript)
        transcript_chunks = self._split_text_by_chars(transcript, TRANSCRIPT_SUMMARY_CHUNK_CHARS)
        partial_summaries: list[str] = []
        for index, chunk in enumerate(transcript_chunks, start=1):
            partial_summary = self._request_meeting_summary(
                client=client, summary_model=summary_model, source_name=f"{source_name} part {index}/{len(transcript_chunks)}", title=title,
                focus=f"This is one part of a long meeting transcript. Extract only facts, decisions, risks, and action items from part {index}/{len(transcript_chunks)}. {focus}",
                output_language=output_language, transcript=chunk,
                mode_note=f"Long transcript partial summarization: part {index}/{len(transcript_chunks)}.",
            )
            partial_summaries.append(f"[Partial summary {index}/{len(transcript_chunks)}]\n{partial_summary}")
        return self._request_meeting_summary(
            client=client, summary_model=summary_model, source_name=source_name, title=title,
            focus=f"{focus} Combine the partial summaries into one final meeting material without duplication.",
            output_language=output_language, transcript="\n\n".join(partial_summaries),
            mode_note="The transcript below contains partial summaries of a long meeting transcript.",
        )

    def chat(self, *, message: str, context: str = "", model: str = "", language: str = "ko") -> str:
        """회의 요약/전사문을 참고해 사용자의 질문에 답합니다.

        이 함수는 화면 자체를 알지 못합니다. 질문과 회의 문맥을 문자열로 받아
        OpenAI에 전달하고, 답변 문자열만 반환하므로 Windows 화면과 웹 화면에서
        같은 기능을 재사용할 수 있습니다.
        """

        if not message.strip():
            raise RuntimeError("채팅 질문을 입력해 주세요.")

        config = load_openai_config()
        client = self._get_client(config)
        # 채팅도 요약과 같은 모델 선택 상자를 사용합니다.
        selected_model = self._resolve_model(config=config, selected_model=model)
        response = client.responses.create(
            model=selected_model,
            instructions=(
                "You are a helpful meeting assistant. Answer using the meeting context when provided. "
                "Use the requested language. Do not invent facts; clearly say when the context does not contain the answer."
            ),
            input=(
                f"Output language: {language.strip() or 'ko'}\n"
                f"Meeting context:\n{context.strip() or '(No meeting context provided.)'}\n\n"
                f"User question:\n{message.strip()}"
            ),
        )
        answer = (getattr(response, "output_text", "") or "").strip()
        if not answer:
            raise RuntimeError("OpenAI 채팅 응답이 비어 있습니다.")
        return answer

    def save_summary_as_word(
        self,
        *,
        output_path: Path,
        summary: str,
        meeting_title: str = "",
        source_name: str = "",
        transcript: str = "",
    ) -> Path:
        """회의자료 요약을 Word(.docx) 파일로 저장합니다.

        글꼴(나눔스퀘어), 크기(제목 12pt / 본문 10pt), 글머리 기호, 여백을
        참조 회의록과 같게 맞춥니다. 화면을 알지 못하는 함수이므로
        Windows 앱과 웹 앱에서 똑같이 사용할 수 있습니다.
        """

        if not summary.strip():
            raise RuntimeError("저장할 회의자료 요약 내용이 없습니다.")

        document = Document()
        # 기본 스타일을 맞춰 두면 따로 지정하지 않은 문단도 같은 글꼴/크기가 됩니다.
        normal_style = document.styles["Normal"]
        normal_style.font.name = WORD_FONT_NAME
        normal_style.font.size = Pt(WORD_BODY_FONT_SIZE_PT)
        normal_style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), WORD_FONT_NAME)
        normal_style.paragraph_format.space_before = Pt(0)
        normal_style.paragraph_format.space_after = Pt(0)

        # 참조 문서와 같은 A4 사방 1.27cm 여백을 적용합니다.
        for section in document.sections:
            section.top_margin = Cm(WORD_PAGE_MARGIN_CM)
            section.bottom_margin = Cm(WORD_PAGE_MARGIN_CM)
            section.left_margin = Cm(WORD_PAGE_MARGIN_CM)
            section.right_margin = Cm(WORD_PAGE_MARGIN_CM)

        # 요약문이 큰 제목으로 시작하면 문서 제목이 두 번 나오지 않도록 정리합니다.
        summary_body = summary.strip()
        leading_heading, remaining_body = _split_leading_heading(summary_body)
        title = meeting_title.strip() or leading_heading or Path(source_name).stem or "회의자료 요약"
        if leading_heading and leading_heading.replace(" ", "") == title.replace(" ", ""):
            summary_body = remaining_body
        _add_heading_paragraph(document, title, level=1)

        # 어떤 녹음에서 언제 만든 문서인지 알 수 있도록 안내 줄을 넣습니다.
        info_items = [f"작성일: {datetime.now():%Y-%m-%d %H:%M}"]
        if source_name:
            info_items.append(f"원본 파일: {source_name}")
        info_paragraph = document.add_paragraph()
        info_paragraph.paragraph_format.space_after = Pt(8)
        info_run = info_paragraph.add_run("  |  ".join(info_items))
        _style_run(info_run, size_pt=WORD_BODY_FONT_SIZE_PT, color=RGBColor(0x5D, 0x68, 0x74))

        render_markdown_to_document(document, summary_body)

        if transcript.strip():
            # 원문 전사는 참고 자료이므로 새 쪽에서 시작합니다.
            page_break_paragraph = document.add_paragraph()
            page_break_paragraph.add_run().add_break(WD_BREAK.PAGE)
            _add_heading_paragraph(document, "원문 전사", level=1)
            for line in transcript.strip().replace("\r\n", "\n").split("\n"):
                if line.strip():
                    _add_body_paragraph(document, line.strip())

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output_path))
        return output_path

    def transcribe_and_summarize(self, *, audio_path: Path, source_name: str, transcription_prompt: str, meeting_title: str, summary_focus: str, language: str, model: str = "") -> dict[str, str]:
        """음성 전사와 회의 요약을 순서대로 실행합니다."""

        # 먼저 음성을 글자로 바꾸고, 그 결과를 요약 함수에 넘깁니다.
        # 두 작업을 하나의 메서드로 묶어 화면에서는 한 번만 호출하면 됩니다.
        transcript = self.transcribe_audio(audio_path, source_name, transcription_prompt, language)
        summary = self.summarize_meeting(transcript=transcript, source_name=source_name, meeting_title=meeting_title, summary_focus=summary_focus, language=language, model=model)
        return {"transcript": transcript, "summary": summary}
