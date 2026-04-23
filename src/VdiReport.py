from __future__ import annotations

import platform
import re
from copy import copy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import PhotoImage, StringVar, Tk
from tkinter import filedialog, messagebox, ttk
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Side


SYSTEM_NAME = platform.system()


def get_default_base_dir() -> Path:
    if SYSTEM_NAME == "Windows":
        return Path("C:/VDI")
    return Path.home() / "VDI"


def get_default_ui_font() -> str:
    if SYSTEM_NAME == "Windows":
        return "Malgun Gothic"
    if SYSTEM_NAME == "Darwin":
        return "Apple SD Gothic Neo"
    return "Noto Sans CJK KR"


DEFAULT_BASE_DIR = get_default_base_dir()
DEFAULT_UI_FONT = get_default_ui_font()
DEFAULT_VDI_LOG_PATH = DEFAULT_BASE_DIR / "1.vdilog.xlsx"
DEFAULT_USER_INFO_PATH = DEFAULT_BASE_DIR / "2.userinfo.xlsx"
DEFAULT_OUTPUT_DIR = DEFAULT_BASE_DIR
TEMPLATE_PATH = DEFAULT_BASE_DIR / "3.VdiConnectReport.xlsx"

TITLE_TEXT = "VDI 접속현황"
WINDOW_TITLE = "VDI 접속 현황"
OUTPUT_FILENAME_PREFIX = "3.VdiConnectReport"

COL_NO = "No"
COL_CONNECTED_AT = "접속시간(KST)"
COL_CLIENT_IP = "접속단말 IP"
COL_ROLE = "역할"
COL_EMPLOYEE_NO = "사번"
COL_NAME = "이름"
COL_EMAIL = "이메일"
COL_PHONE = "전화번호"
COL_APPROVER = "확인담당자"
COL_REASON = "접속사유"

REPORT_HEADERS = [
    COL_NO,
    COL_CONNECTED_AT,
    COL_CLIENT_IP,
    COL_ROLE,
    COL_EMPLOYEE_NO,
    COL_NAME,
    COL_EMAIL,
    COL_PHONE,
    COL_APPROVER,
    COL_REASON,
]

KST = ZoneInfo("Asia/Seoul")
EMPLOYEE_PATTERN = re.compile(r"(?i)\\+[n]?[b](\d{5,8})")
CLIENT_IP_PATTERN = re.compile(
    r'(?i)(?:ClientIP|Client IP|clientip|client_ip|ClientIpAddress|ForwardedClientIpAddress)\s*["=:]+\s*"?(?P<ip>[0-9]{1,3}(?:\.[0-9]{1,3}){3})'
)
IP_FALLBACK_PATTERN = re.compile(r"\b([0-9]{1,3}(?:\.[0-9]{1,3}){3})\b")
SOLID_SIDE = Side(style="thin", color="000000")
SOLID_BORDER = Border(
    left=SOLID_SIDE,
    right=SOLID_SIDE,
    top=SOLID_SIDE,
    bottom=SOLID_SIDE,
)


@dataclass
class UserInfo:
    role: str = ""
    employee_no: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    approver: str = ""


@dataclass
class ReportRow:
    connected_at: datetime
    connected_at_text: str
    client_ip: str
    role: str
    employee_no: str
    name: str
    email: str
    phone: str
    approver: str
    reason: str = ""

    def as_excel_row(self, number: int) -> list[Any]:
        return [
            number,
            self.connected_at_text,
            self.client_ip,
            self.role,
            self.employee_no,
            self.name,
            self.email,
            self.phone,
            self.approver,
            self.reason,
        ]


def value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("\u3000", "").strip()


def normalize_employee_no(value: Any) -> str:
    text = value_to_text(value).upper().replace(" ", "")
    if not text:
        return ""

    match = EMPLOYEE_PATTERN.search(text)
    if match:
        return f"NB{match.group(1)}"

    if re.fullmatch(r"NB\d{5,8}", text):
        return text
    if re.fullmatch(r"B\d{5,8}", text):
        return f"NB{text[1:]}"
    return text


def parse_logtime(value: Any) -> tuple[datetime, str]:
    if isinstance(value, datetime):
        parsed = value.astimezone(KST).replace(tzinfo=None) if value.tzinfo else value
        return parsed, parsed.strftime("%Y-%m-%d %H:%M:%S")

    text = value_to_text(value)
    if not text:
        raise ValueError("logtime 값이 비어 있습니다.")

    candidate = text.replace("T", " ").replace("Z", "+00:00")
    parsed: datetime | None = None

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(f"logtime 형식을 해석할 수 없습니다: {text}")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)

    return parsed, parsed.strftime("%Y-%m-%d %H:%M:%S")


def extract_employee_no(body_text: str) -> str:
    match = EMPLOYEE_PATTERN.search(body_text)
    if not match:
        return ""
    return f"NB{match.group(1)}"


def extract_client_ip(body_text: str) -> str:
    match = CLIENT_IP_PATTERN.search(body_text)
    if match:
        return match.group("ip")

    for candidate in IP_FALLBACK_PATTERN.findall(body_text):
        if not candidate.startswith("127."):
            return candidate
    return ""


def load_log_rows(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [value_to_text(cell).lower() for cell in rows[0]]
    data_rows: list[dict[str, Any]] = []

    for row in rows[1:]:
        if all(value_to_text(cell) == "" for cell in row):
            continue

        item: dict[str, Any] = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            item[header] = row[index] if index < len(row) else None
        data_rows.append(item)

    return data_rows


def load_user_info(path: Path) -> dict[str, UserInfo]:
    workbook = load_workbook(path, data_only=True)
    sheet = workbook.active
    users: dict[str, UserInfo] = {}

    for row_index in range(3, sheet.max_row + 1):
        role = value_to_text(sheet.cell(row=row_index, column=2).value)
        name = value_to_text(sheet.cell(row=row_index, column=3).value)
        employee_no = normalize_employee_no(sheet.cell(row=row_index, column=4).value)
        phone = value_to_text(sheet.cell(row=row_index, column=5).value)
        email = value_to_text(sheet.cell(row=row_index, column=6).value)
        approver = value_to_text(sheet.cell(row=row_index, column=7).value)

        if not employee_no:
            continue

        users[employee_no] = UserInfo(
            role=role,
            employee_no=employee_no,
            name=name,
            email=email,
            phone=phone,
            approver=approver,
        )

    return users


def build_report_rows(log_path: Path, users: dict[str, UserInfo]) -> list[ReportRow]:
    report_rows: list[ReportRow] = []

    for row in load_log_rows(log_path):
        body = value_to_text(row.get("body"))
        if not body:
            continue

        employee_no = extract_employee_no(body)
        if not employee_no:
            continue

        connected_at, connected_at_text = parse_logtime(row.get("logtime"))
        client_ip = extract_client_ip(body)
        user = users.get(employee_no, UserInfo(employee_no=employee_no))

        report_rows.append(
            ReportRow(
                connected_at=connected_at,
                connected_at_text=connected_at_text,
                client_ip=client_ip,
                role=user.role,
                employee_no=employee_no,
                name=user.name,
                email=user.email,
                phone=user.phone,
                approver=user.approver,
                reason="",
            )
        )

    report_rows.sort(key=lambda item: item.connected_at)
    return report_rows


def clear_existing_data_rows(worksheet: Any) -> None:
    if worksheet.max_row > 2:
        worksheet.delete_rows(3, worksheet.max_row - 2)


def copy_row_style(worksheet: Any, target_row: int, style_row: int, max_col: int) -> None:
    source_height = worksheet.row_dimensions[style_row].height
    if source_height is not None:
        worksheet.row_dimensions[target_row].height = source_height

    for column_index in range(1, max_col + 1):
        source_cell = worksheet.cell(row=style_row, column=column_index)
        target_cell = worksheet.cell(row=target_row, column=column_index)
        target_cell._style = copy(source_cell._style)
        if source_cell.has_style:
            target_cell.font = copy(source_cell.font)
            target_cell.fill = copy(source_cell.fill)
            target_cell.border = copy(source_cell.border)
            target_cell.alignment = copy(source_cell.alignment)
            target_cell.protection = copy(source_cell.protection)
            target_cell.number_format = source_cell.number_format


def apply_solid_border_to_data_area(worksheet: Any, start_row: int, end_row: int, max_col: int) -> None:
    for row_index in range(start_row, end_row + 1):
        for column_index in range(1, max_col + 1):
            worksheet.cell(row=row_index, column=column_index).border = SOLID_BORDER


def apply_data_alignment(worksheet: Any, start_row: int, end_row: int, max_col: int) -> None:
    for row_index in range(start_row, end_row + 1):
        for column_index in range(1, max_col + 1):
            cell = worksheet.cell(row=row_index, column=column_index)
            current_alignment = cell.alignment

            if column_index == 1:
                horizontal = "right"
            elif column_index == 7:
                horizontal = "left"
            else:
                horizontal = "center"

            cell.alignment = Alignment(
                horizontal=horizontal,
                vertical="center",
                text_rotation=getattr(current_alignment, "textRotation", 0),
                wrap_text=getattr(current_alignment, "wrap_text", None),
                shrink_to_fit=getattr(current_alignment, "shrink_to_fit", None),
                indent=getattr(current_alignment, "indent", 0),
                relativeIndent=getattr(current_alignment, "relativeIndent", None),
                justifyLastLine=getattr(current_alignment, "justifyLastLine", None),
                readingOrder=getattr(current_alignment, "readingOrder", None),
            )


def write_report_from_template(template_path: Path, output_path: Path, rows: list[ReportRow]) -> None:
    workbook = load_workbook(template_path)
    sheet = workbook.active
    max_col = len(REPORT_HEADERS)
    style_row = 3 if sheet.max_row >= 3 else 2

    clear_existing_data_rows(sheet)

    sheet.cell(row=1, column=1, value=TITLE_TEXT)
    for column_index, header in enumerate(REPORT_HEADERS, start=1):
        sheet.cell(row=2, column=column_index, value=header)

    for index, row in enumerate(rows, start=1):
        target_row = index + 2
        copy_row_style(sheet, target_row, style_row, max_col)
        for column_index, value in enumerate(row.as_excel_row(index), start=1):
            sheet.cell(row=target_row, column=column_index, value=value)

    if rows:
        apply_solid_border_to_data_area(sheet, 3, len(rows) + 2, max_col)
        apply_data_alignment(sheet, 3, len(rows) + 2, max_col)

    workbook.save(output_path)


def validate_required_files(log_path: Path, user_info_path: Path) -> None:
    required_files = (log_path, user_info_path, TEMPLATE_PATH)
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {', '.join(missing_files)}")


class VdiWindow:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1440x860")
        self.root.minsize(1100, 600)

        self.preview_rows: list[ReportRow] = []
        self.sort_reverse: dict[str, bool] = {}

        self.log_path_var = StringVar(value=str(DEFAULT_VDI_LOG_PATH))
        self.user_info_path_var = StringVar(value=str(DEFAULT_USER_INFO_PATH))
        self.output_dir_var = StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.status_var = StringVar(
            value="VDI 로그 파일과 사용자정보 파일을 선택한 뒤 미리보기를 실행하세요."
        )

        self.columns = [f"col_{index}" for index in range(len(REPORT_HEADERS))]
        self.tree: ttk.Treeview
        self.icons = self._build_icons()
        self.reason_editor: ttk.Entry | None = None
        self.reason_editor_var = StringVar()
        self.editing_item_id: str | None = None

        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        style.configure("Header.TLabel", font=(DEFAULT_UI_FONT, 10, "bold"))
        style.configure("Status.TLabel", padding=(8, 6))
        style.configure("Action.TButton", padding=(12, 8))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)

        file_frame = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        file_frame.grid(row=0, column=0, sticky="ew")
        file_frame.columnconfigure(1, weight=1)

        self._add_path_row(
            file_frame,
            row=0,
            label_text="VDI 로그파일",
            variable=self.log_path_var,
            button_text="찾아보기",
            command=self.select_log_file,
        )
        self._add_path_row(
            file_frame,
            row=1,
            label_text="사용자정보파일",
            variable=self.user_info_path_var,
            button_text="찾아보기",
            command=self.select_user_info_file,
        )
        self._add_path_row(
            file_frame,
            row=2,
            label_text="출력폴더",
            variable=self.output_dir_var,
            button_text="폴더선택",
            command=self.select_output_dir,
        )

        button_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        button_frame.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            button_frame,
            text="미리보기 생성",
            image=self.icons["preview"],
            compound="left",
            style="Action.TButton",
            command=self.generate_preview,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            button_frame,
            text="파일 저장",
            image=self.icons["save"],
            compound="left",
            style="Action.TButton",
            command=self.save_report,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            button_frame,
            text="미리보기 초기화",
            image=self.icons["clear"],
            compound="left",
            style="Action.TButton",
            command=self.clear_preview,
        ).pack(side="left")
        ttk.Label(
            button_frame,
            text="접속사유는 미리보기 표의 마지막 열을 클릭해 바로 수정할 수 있습니다.",
        ).pack(side="right")

        table_frame = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=self.columns,
            show="headings",
            selectmode="browse",
            height=20,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<ButtonRelease-1>", self.handle_tree_click)
        self.tree.bind("<Configure>", lambda _event: self.close_reason_editor(save=True))

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        widths = [70, 170, 140, 110, 120, 120, 220, 130, 130, 220]
        anchors = ["e", "center", "center", "center", "center", "center", "w", "center", "center", "w"]

        for index, (column_id, header, width, anchor) in enumerate(
            zip(self.columns, REPORT_HEADERS, widths, anchors)
        ):
            self.tree.heading(column_id, text=header, command=lambda idx=index: self.sort_preview_by_column(idx))
            self.tree.column(column_id, width=width, minwidth=80, anchor=anchor, stretch=True)

        status = ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel", relief="sunken")
        status.grid(row=3, column=0, sticky="ew")

    def _add_path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label_text: str,
        variable: StringVar,
        button_text: str,
        command: Any,
    ) -> None:
        ttk.Label(parent, text=label_text, style="Header.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text=button_text, command=command).grid(
            row=row, column=2, sticky="ew", padx=(8, 0), pady=4
        )

    def _build_icons(self) -> dict[str, PhotoImage]:
        return {
            "preview": self._create_preview_icon(),
            "save": self._create_save_icon(),
            "clear": self._create_clear_icon(),
        }

    def _get_existing_initial_dir(self, current_text: str, fallback: Path) -> Path:
        current_path = Path(current_text).expanduser() if current_text.strip() else fallback
        if current_path.exists():
            return current_path if current_path.is_dir() else current_path.parent

        fallback = fallback.expanduser()
        if fallback.exists():
            return fallback if fallback.is_dir() else fallback.parent
        return Path.home()

    def _fill_rect(self, image: PhotoImage, x1: int, y1: int, x2: int, y2: int, color: str) -> None:
        image.put(color, to=(x1, y1, x2, y2))

    def _draw_circle(self, image: PhotoImage, center_x: int, center_y: int, radius: int, color: str) -> None:
        for y in range(center_y - radius, center_y + radius + 1):
            for x in range(center_x - radius, center_x + radius + 1):
                if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2:
                    image.put(color, (x, y))

    def _create_preview_icon(self) -> PhotoImage:
        image = PhotoImage(width=24, height=24)
        self._fill_rect(image, 4, 2, 15, 20, "#3B7BD6")
        self._fill_rect(image, 6, 4, 13, 18, "#FFFFFF")
        self._fill_rect(image, 11, 2, 15, 6, "#9CC2F4")
        self._fill_rect(image, 7, 7, 12, 8, "#C8D7EE")
        self._fill_rect(image, 7, 10, 12, 11, "#C8D7EE")
        self._fill_rect(image, 7, 13, 11, 14, "#C8D7EE")
        self._draw_circle(image, 15, 15, 5, "#1DB9C3")
        self._draw_circle(image, 15, 15, 3, "#DDEFF8")
        self._fill_rect(image, 18, 18, 22, 22, "#28507E")
        self._fill_rect(image, 17, 17, 19, 19, "#28507E")
        return image

    def _create_save_icon(self) -> PhotoImage:
        image = PhotoImage(width=24, height=24)
        self._fill_rect(image, 3, 2, 16, 20, "#3B7BD6")
        self._fill_rect(image, 5, 4, 14, 18, "#FFFFFF")
        self._fill_rect(image, 6, 5, 13, 8, "#D7E4F6")
        self._fill_rect(image, 10, 5, 12, 8, "#285FA8")
        self._fill_rect(image, 7, 12, 12, 13, "#C8D7EE")
        self._fill_rect(image, 7, 15, 12, 16, "#C8D7EE")
        self._fill_rect(image, 17, 5, 21, 15, "#3FAE57")
        self._fill_rect(image, 15, 13, 23, 16, "#3FAE57")
        self._fill_rect(image, 18, 15, 20, 20, "#3FAE57")
        self._fill_rect(image, 16, 17, 22, 19, "#3FAE57")
        return image

    def _create_clear_icon(self) -> PhotoImage:
        image = PhotoImage(width=24, height=24)
        self._fill_rect(image, 5, 3, 18, 20, "#425875")
        self._fill_rect(image, 7, 5, 16, 18, "#FFFFFF")
        self._fill_rect(image, 8, 8, 14, 9, "#CCD6E4")
        self._fill_rect(image, 8, 11, 14, 12, "#CCD6E4")
        self._fill_rect(image, 8, 14, 13, 15, "#CCD6E4")
        self._draw_circle(image, 7, 7, 5, "#FF8A1D")
        self._draw_circle(image, 7, 7, 3, "#FFFFFF")
        self._fill_rect(image, 8, 2, 12, 5, "#FF8A1D")
        self._fill_rect(image, 14, 14, 22, 20, "#6C809E")
        self._fill_rect(image, 14, 18, 22, 20, "#ECEFF4")
        return image

    def select_log_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="VDI 로그파일 선택",
            initialdir=str(self._get_existing_initial_dir(self.log_path_var.get(), DEFAULT_VDI_LOG_PATH.parent)),
            filetypes=[("Excel 파일", "*.xlsx"), ("모든 파일", "*.*")],
        )
        if selected:
            self.log_path_var.set(selected)

    def select_user_info_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="사용자정보파일 선택",
            initialdir=str(self._get_existing_initial_dir(self.user_info_path_var.get(), DEFAULT_USER_INFO_PATH.parent)),
            filetypes=[("Excel 파일", "*.xlsx"), ("모든 파일", "*.*")],
        )
        if selected:
            self.user_info_path_var.set(selected)

    def select_output_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="출력폴더 선택",
            initialdir=str(self._get_existing_initial_dir(self.output_dir_var.get(), DEFAULT_OUTPUT_DIR)),
        )
        if selected:
            self.output_dir_var.set(selected)

    def clear_preview(self) -> None:
        self.close_reason_editor(save=False)
        self.preview_rows = []
        self.sort_reverse = {}
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.status_var.set("미리보기가 초기화되었습니다.")

    def generate_preview(self) -> None:
        try:
            self.close_reason_editor(save=True)
            log_path = Path(self.log_path_var.get().strip())
            user_info_path = Path(self.user_info_path_var.get().strip())
            validate_required_files(log_path, user_info_path)
            users = load_user_info(user_info_path)
            self.preview_rows = build_report_rows(log_path, users)
            self.sort_reverse = {}
            self.refresh_table()
            self.status_var.set(f"미리보기 생성 완료: {len(self.preview_rows)}건")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))
            self.status_var.set("미리보기 생성 중 오류가 발생했습니다.")

    def refresh_table(self) -> None:
        self.close_reason_editor(save=True)
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        for row_index, row in enumerate(self.preview_rows, start=1):
            values = row.as_excel_row(row_index)
            self.tree.insert("", "end", iid=str(row_index - 1), values=values)

    def handle_tree_click(self, event: Any) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            self.close_reason_editor(save=True)
            return

        item_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not item_id or column_id != f"#{len(REPORT_HEADERS)}":
            self.close_reason_editor(save=True)
            return

        self.open_reason_editor(item_id, column_id)

    def open_reason_editor(self, item_id: str, column_id: str) -> None:
        self.close_reason_editor(save=True)
        bbox = self.tree.bbox(item_id, column_id)
        if not bbox:
            return

        x, y, width, height = bbox
        row = self.preview_rows[int(item_id)]
        self.editing_item_id = item_id
        self.reason_editor_var.set(row.reason)
        self.reason_editor = ttk.Entry(self.tree, textvariable=self.reason_editor_var)
        self.reason_editor.place(x=x, y=y, width=width, height=height)
        self.reason_editor.focus_set()
        self.reason_editor.selection_range(0, "end")
        self.reason_editor.bind("<Return>", lambda _event: self.close_reason_editor(save=True))
        self.reason_editor.bind("<Escape>", lambda _event: self.close_reason_editor(save=False))
        self.reason_editor.bind("<FocusOut>", lambda _event: self.close_reason_editor(save=True))

    def close_reason_editor(self, save: bool) -> None:
        if self.reason_editor is None:
            return

        item_id = self.editing_item_id
        editor = self.reason_editor
        value = self.reason_editor_var.get().strip()

        self.reason_editor = None
        self.editing_item_id = None
        editor.destroy()

        if save and item_id is not None and item_id.isdigit():
            row_index = int(item_id)
            if 0 <= row_index < len(self.preview_rows):
                self.preview_rows[row_index].reason = value
                values = self.preview_rows[row_index].as_excel_row(row_index + 1)
                self.tree.item(item_id, values=values)
                self.status_var.set(f"접속사유 수정 완료: {self.preview_rows[row_index].employee_no}")

    def sort_preview_by_column(self, column_index: int) -> None:
        if not self.preview_rows:
            return

        self.close_reason_editor(save=True)

        reverse = self.sort_reverse.get(self.columns[column_index], False)

        if column_index == 0:
            self.preview_rows.reverse()
        elif column_index == 1:
            self.preview_rows.sort(key=lambda row: row.connected_at, reverse=reverse)
        elif column_index == 2:
            self.preview_rows.sort(
                key=lambda row: tuple(int(part) for part in row.client_ip.split(".")) if row.client_ip else (),
                reverse=reverse,
            )
        elif column_index == 3:
            self.preview_rows.sort(key=lambda row: row.role.casefold(), reverse=reverse)
        elif column_index == 4:
            self.preview_rows.sort(key=lambda row: row.employee_no.casefold(), reverse=reverse)
        elif column_index == 5:
            self.preview_rows.sort(key=lambda row: row.name.casefold(), reverse=reverse)
        elif column_index == 6:
            self.preview_rows.sort(key=lambda row: row.email.casefold(), reverse=reverse)
        elif column_index == 7:
            self.preview_rows.sort(key=lambda row: row.phone.casefold(), reverse=reverse)
        elif column_index == 8:
            self.preview_rows.sort(key=lambda row: row.approver.casefold(), reverse=reverse)
        elif column_index == 9:
            self.preview_rows.sort(key=lambda row: row.reason.casefold(), reverse=reverse)

        self.sort_reverse[self.columns[column_index]] = not reverse
        self.refresh_table()

        direction = "내림차순" if reverse else "오름차순"
        self.status_var.set(f"미리보기 정렬 완료: {REPORT_HEADERS[column_index]} {direction}")

    def build_output_path(self, suffix: str = ".xlsx") -> Path:
        output_dir_text = self.output_dir_var.get().strip()
        if not output_dir_text:
            raise ValueError("출력폴더를 선택해 주세요.")

        output_dir = Path(output_dir_text)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        return output_dir / f"{OUTPUT_FILENAME_PREFIX}_{timestamp}{suffix}"

    def save_report(self) -> None:
        try:
            self.close_reason_editor(save=True)
            if not self.preview_rows:
                self.generate_preview()
                if not self.preview_rows:
                    return

            output_path = self.build_output_path()
            write_report_from_template(TEMPLATE_PATH, output_path, self.preview_rows)
            messagebox.showinfo("완료", f"보고서가 저장되었습니다.\n{output_path}")
            self.status_var.set(f"파일 저장 완료: {output_path}")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))
            self.status_var.set("파일 저장 중 오류가 발생했습니다.")


def main() -> None:
    root = Tk()
    VdiWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
