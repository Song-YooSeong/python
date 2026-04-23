from __future__ import annotations

import tkinter as tk
from decimal import Decimal, DivisionByZero, InvalidOperation
from tkinter import font


class CalculatorApp:
    def __init__(self, root: tk.Tk) -> None:
        # root는 tkinter가 만든 "메인 창" 객체입니다.
        self.root = root
        self.root.title("Calculator")
        self.root.geometry("360x520")
        self.root.minsize(320, 460)
        self.root.configure(bg="#f3f3f3")

        # 화면에 표시할 문자열을 저장하는 변수입니다.
        # StringVar를 쓰면 값이 바뀔 때 라벨도 자동으로 갱신됩니다.
        self.display_var = tk.StringVar(value="0")
        self.history_var = tk.StringVar(value="")

        # current_input: 사용자가 지금 입력 중인 숫자
        self.current_input = "0"
        # left_value: 연산자 왼쪽에 있는 값(예: 12 + 3 에서 12)
        self.left_value: Decimal | None = None
        # pending_operator: 아직 계산되지 않고 대기 중인 연산자
        self.pending_operator: str | None = None
        # True이면 다음 숫자 입력 시 기존 숫자를 지우고 새로 시작합니다.
        self.reset_input = False

        # 화면 구성과 키보드 연결을 시작할 때 한 번만 만듭니다.
        self._build_ui()
        self._bind_keys()

    def _build_ui(self) -> None:
        # 계산기 화면에서 사용할 글꼴 크기를 정합니다.
        display_font = font.Font(family="Segoe UI", size=30, weight="bold")
        history_font = font.Font(family="Segoe UI", size=11)
        button_font = font.Font(family="Segoe UI", size=14)

        # container는 계산기 전체를 담는 바깥 프레임입니다.
        container = tk.Frame(self.root, bg="#f3f3f3", padx=12, pady=12)
        container.pack(fill="both", expand=True)

        # 이전 계산식이나 현재 연산 상태를 보여주는 작은 영역입니다.
        history_label = tk.Label(
            container,
            textvariable=self.history_var,
            anchor="e",
            bg="#f3f3f3",
            fg="#6a6a6a",
            font=history_font,
            pady=10,
        )
        history_label.pack(fill="x")

        # 실제 숫자가 크게 보이는 메인 표시창입니다.
        display_label = tk.Label(
            container,
            textvariable=self.display_var,
            anchor="e",
            bg="#ffffff",
            fg="#111111",
            relief="flat",
            padx=16,
            pady=18,
            font=display_font,
        )
        display_label.pack(fill="x", pady=(0, 12))

        # 버튼들을 담는 영역입니다.
        buttons = tk.Frame(container, bg="#f3f3f3")
        buttons.pack(fill="both", expand=True)

        # 모든 줄과 칸이 창 크기에 맞춰 고르게 늘어나도록 설정합니다.
        for row in range(5):
            buttons.rowconfigure(row, weight=1)
        for col in range(4):
            buttons.columnconfigure(col, weight=1)

        # 버튼의 글자, 눌렀을 때 실행할 함수, 배경색을 표 형태로 정리했습니다.
        layout = [
            [("C", self.clear_all, "#d9d9d9"), ("BS", self.backspace, "#d9d9d9"), ("+/-", self.toggle_sign, "#d9d9d9"), ("/", lambda: self.set_operator("/"), "#ffb84d")],
            [("7", lambda: self.input_digit("7"), "#ffffff"), ("8", lambda: self.input_digit("8"), "#ffffff"), ("9", lambda: self.input_digit("9"), "#ffffff"), ("*", lambda: self.set_operator("*"), "#ffb84d")],
            [("4", lambda: self.input_digit("4"), "#ffffff"), ("5", lambda: self.input_digit("5"), "#ffffff"), ("6", lambda: self.input_digit("6"), "#ffffff"), ("-", lambda: self.set_operator("-"), "#ffb84d")],
            [("1", lambda: self.input_digit("1"), "#ffffff"), ("2", lambda: self.input_digit("2"), "#ffffff"), ("3", lambda: self.input_digit("3"), "#ffffff"), ("+", lambda: self.set_operator("+"), "#ffb84d")],
            [("0", lambda: self.input_digit("0"), "#ffffff"), (".", self.input_decimal, "#ffffff"), ("=", self.calculate_result, "#ffd27f"), ("", None, "#f3f3f3")],
        ]

        for row_index, row in enumerate(layout):
            for col_index, (label, command, bg_color) in enumerate(row):
                if not label:
                    # 빈칸도 같은 크기를 유지하도록 보이지 않는 프레임을 넣습니다.
                    spacer = tk.Frame(buttons, bg="#f3f3f3")
                    spacer.grid(row=row_index, column=col_index, sticky="nsew", padx=4, pady=4)
                    continue

                # 실제 버튼 생성
                button = tk.Button(
                    buttons,
                    text=label,
                    command=command,
                    font=button_font,
                    bg=bg_color,
                    fg="#111111",
                    activebackground="#e8e8e8",
                    bd=0,
                    relief="flat",
                )
                button.grid(row=row_index, column=col_index, sticky="nsew", padx=4, pady=4)

    def _bind_keys(self) -> None:
        # 마우스뿐 아니라 키보드로도 계산기를 조작할 수 있게 연결합니다.
        self.root.bind("<Key>", self._handle_keypress)
        self.root.bind("<Return>", lambda _: self.calculate_result())
        self.root.bind("<KP_Enter>", lambda _: self.calculate_result())
        self.root.bind("<BackSpace>", lambda _: self.backspace())
        self.root.bind("<Escape>", lambda _: self.clear_all())

    def _handle_keypress(self, event: tk.Event) -> None:
        # keysym은 특수키 이름, char는 실제 입력 문자입니다.
        key = event.keysym
        char = event.char

        if char.isdigit():
            self.input_digit(char)
            return

        if char == ".":
            self.input_decimal()
            return

        if char in "+-*/":
            self.set_operator(char)
            return

        if char == "=":
            self.calculate_result()
            return

        if key in {"Delete", "c", "C"}:
            self.clear_all()

    def input_digit(self, digit: str) -> None:
        # 새 계산을 시작해야 하거나 오류 상태였다면 숫자를 새로 씁니다.
        if self.reset_input or self.current_input == "Error":
            self.current_input = digit
            self.reset_input = False
        elif self.current_input == "0":
            # 맨 처음 0만 있는 상태에서는 새 숫자로 교체합니다.
            self.current_input = digit
        else:
            # 이미 숫자가 있으면 뒤에 이어 붙입니다.
            self.current_input += digit
        self._update_display()

    def input_decimal(self) -> None:
        # 소수점은 숫자 하나당 한 번만 들어갈 수 있습니다.
        if self.reset_input or self.current_input == "Error":
            self.current_input = "0."
            self.reset_input = False
        elif "." not in self.current_input:
            self.current_input += "."
        self._update_display()

    def clear_all(self) -> None:
        # 계산기 상태를 처음 상태로 완전히 되돌립니다.
        self.current_input = "0"
        self.left_value = None
        self.pending_operator = None
        self.reset_input = False
        self.history_var.set("")
        self._update_display()

    def backspace(self) -> None:
        # 마지막에 입력한 글자 하나를 지웁니다.
        if self.reset_input or self.current_input == "Error":
            self.current_input = "0"
            self.reset_input = False
        elif len(self.current_input) <= 1 or (self.current_input.startswith("-") and len(self.current_input) == 2):
            # 한 자리만 남았으면 0으로 돌아갑니다.
            self.current_input = "0"
        else:
            self.current_input = self.current_input[:-1]
        self._update_display()

    def toggle_sign(self) -> None:
        # 양수/음수를 서로 바꿉니다.
        if self.current_input in {"0", "Error"}:
            return
        if self.current_input.startswith("-"):
            self.current_input = self.current_input[1:]
        else:
            self.current_input = f"-{self.current_input}"
        self._update_display()

    def set_operator(self, operator: str) -> None:
        # 현재 화면의 문자열을 실제 계산 가능한 숫자(Decimal)로 바꿉니다.
        current_value = self._to_decimal(self.current_input)
        if current_value is None:
            self._show_error()
            return

        if self.pending_operator and not self.reset_input:
            # 이미 연산자가 있는 상태에서 또 다른 연산자를 누르면
            # 앞 계산을 먼저 끝내고 결과를 왼쪽 값으로 저장합니다.
            result = self._perform_operation(self.left_value, current_value, self.pending_operator)
            if result is None:
                self._show_error()
                return
            self.left_value = result
            self.current_input = self._format_decimal(result)
        else:
            # 첫 연산이라면 현재 입력값을 왼쪽 값으로 저장합니다.
            self.left_value = current_value

        self.pending_operator = operator
        # 다음 숫자 입력 때 새 숫자를 받도록 플래그를 켭니다.
        self.reset_input = True
        self.history_var.set(f"{self._format_decimal(self.left_value)} {self._symbol(operator)}")
        self._update_display()

    def calculate_result(self) -> None:
        # 연산자나 왼쪽 값이 없으면 계산할 것이 없습니다.
        if not self.pending_operator or self.left_value is None:
            self._update_display()
            return

        right_value = self._to_decimal(self.current_input)
        if right_value is None:
            self._show_error()
            return

        expression = f"{self._format_decimal(self.left_value)} {self._symbol(self.pending_operator)} {self._format_decimal(right_value)}"
        result = self._perform_operation(self.left_value, right_value, self.pending_operator)
        if result is None:
            self._show_error()
            return

        # 계산 결과를 다시 화면과 내부 상태에 저장합니다.
        self.current_input = self._format_decimal(result)
        self.display_var.set(self.current_input)
        self.history_var.set(f"{expression} =")
        self.left_value = result
        self.pending_operator = None
        self.reset_input = True

    def _perform_operation(self, left: Decimal | None, right: Decimal, operator: str) -> Decimal | None:
        # left가 비어 있으면 사실상 계산 없이 right를 그대로 사용합니다.
        if left is None:
            return right

        try:
            if operator == "+":
                return left + right
            if operator == "-":
                return left - right
            if operator == "*":
                return left * right
            if operator == "/":
                return left / right
        except (DivisionByZero, InvalidOperation):
            # 0으로 나누기 같은 잘못된 계산은 None으로 알려줍니다.
            return None
        return None

    def _update_display(self) -> None:
        # 현재 입력 문자열을 화면에 반영합니다.
        self.display_var.set(self.current_input)

    def _show_error(self) -> None:
        # 오류가 나면 화면을 Error로 바꾸고 계산 상태를 초기화합니다.
        self.current_input = "Error"
        self.display_var.set("Error")
        self.history_var.set("")
        self.left_value = None
        self.pending_operator = None
        self.reset_input = True

    @staticmethod
    def _to_decimal(value: str) -> Decimal | None:
        # 문자열을 Decimal로 바꾸면 float보다 소수 계산이 더 안정적입니다.
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        # 2.5000 -> 2.5, 10.0 -> 10 처럼 보기 좋게 정리합니다.
        normalized = value.normalize()
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _symbol(operator: str) -> str:
        # 필요하면 연산자 표시 문자를 바꿀 때 사용하는 함수입니다.
        return operator


def main() -> None:
    # tkinter 창을 만들고 계산기 프로그램을 실행합니다.
    root = tk.Tk()
    app = CalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
