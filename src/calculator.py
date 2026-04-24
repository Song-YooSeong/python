"""
프로그램 흐름 설명
1. tkinter로 계산기 창을 만들고, 숫자 표시 영역과 버튼 영역을 준비합니다.
2. 사용자가 버튼이나 키보드로 숫자와 연산자를 입력하면 내부 상태를 바꿉니다.
3. 연산자가 눌리면 현재 숫자를 저장하고 다음 숫자 입력을 기다립니다.
4. '='가 눌리면 저장된 값과 현재 값을 실제로 계산해 화면에 보여줍니다.
5. 오류가 나면 화면에 Error를 표시하고 다시 계산을 시작할 수 있게 상태를 초기화합니다.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, DivisionByZero, InvalidOperation
from tkinter import font


class CalculatorApp:
    """간단한 사칙연산 계산기 화면과 동작을 관리합니다."""

    def __init__(self, root: tk.Tk) -> None:
        # root는 tkinter가 만든 메인 창 객체입니다.
        self.root = root
        self.root.title("Calculator")
        self.root.geometry("360x520")
        self.root.minsize(320, 460)
        self.root.configure(bg="#f3f3f3")

        # 화면에 보여줄 숫자와 계산 기록을 StringVar로 관리합니다.
        self.display_var = tk.StringVar(value="0")
        self.history_var = tk.StringVar(value="")

        # current_input은 현재 사용자가 입력 중인 숫자 문자열입니다.
        self.current_input = "0"
        # left_value는 이전에 저장된 왼쪽 피연산자입니다.
        self.left_value: Decimal | None = None
        # pending_operator는 아직 계산되지 않고 대기 중인 연산자입니다.
        self.pending_operator: str | None = None
        # 다음 숫자를 새로 입력해야 하는지 표시하는 플래그입니다.
        self.reset_input = False

        self._build_ui()
        self._bind_keys()

    def _build_ui(self) -> None:
        """계산기 화면의 라벨과 버튼을 배치합니다."""
        display_font = font.Font(family="Segoe UI", size=30, weight="bold")
        history_font = font.Font(family="Segoe UI", size=11)
        button_font = font.Font(family="Segoe UI", size=14)

        container = tk.Frame(self.root, bg="#f3f3f3", padx=12, pady=12)
        container.pack(fill="both", expand=True)

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

        buttons = tk.Frame(container, bg="#f3f3f3")
        buttons.pack(fill="both", expand=True)

        for row in range(5):
            buttons.rowconfigure(row, weight=1)
        for col in range(4):
            buttons.columnconfigure(col, weight=1)

        # 각 버튼은 (표시 글자, 눌렀을 때 실행할 함수, 배경색) 형태로 정리합니다.
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
                    spacer = tk.Frame(buttons, bg="#f3f3f3")
                    spacer.grid(row=row_index, column=col_index, sticky="nsew", padx=4, pady=4)
                    continue

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
        """키보드 입력도 버튼과 같은 동작으로 연결합니다."""
        self.root.bind("<Key>", self._handle_keypress)
        self.root.bind("<Return>", lambda _: self.calculate_result())
        self.root.bind("<KP_Enter>", lambda _: self.calculate_result())
        self.root.bind("<BackSpace>", lambda _: self.backspace())
        self.root.bind("<Escape>", lambda _: self.clear_all())

    def _handle_keypress(self, event: tk.Event) -> None:
        """사용자가 누른 키를 해석해 알맞은 기능을 호출합니다."""
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
        """숫자 버튼을 눌렀을 때 현재 입력 문자열을 갱신합니다."""
        if self.reset_input or self.current_input == "Error":
            self.current_input = digit
            self.reset_input = False
        elif self.current_input == "0":
            self.current_input = digit
        else:
            self.current_input += digit
        self._update_display()

    def input_decimal(self) -> None:
        """소수점을 한 번만 입력할 수 있게 처리합니다."""
        if self.reset_input or self.current_input == "Error":
            self.current_input = "0."
            self.reset_input = False
        elif "." not in self.current_input:
            self.current_input += "."
        self._update_display()

    def clear_all(self) -> None:
        """계산기 상태를 완전히 초기화합니다."""
        self.current_input = "0"
        self.left_value = None
        self.pending_operator = None
        self.reset_input = False
        self.history_var.set("")
        self._update_display()

    def backspace(self) -> None:
        """현재 입력의 마지막 글자를 지웁니다."""
        if self.reset_input or self.current_input == "Error":
            self.current_input = "0"
            self.reset_input = False
        elif len(self.current_input) <= 1 or (self.current_input.startswith("-") and len(self.current_input) == 2):
            self.current_input = "0"
        else:
            self.current_input = self.current_input[:-1]
        self._update_display()

    def toggle_sign(self) -> None:
        """현재 숫자의 부호를 바꿉니다."""
        if self.current_input in {"0", "Error"}:
            return
        if self.current_input.startswith("-"):
            self.current_input = self.current_input[1:]
        else:
            self.current_input = f"-{self.current_input}"
        self._update_display()

    def set_operator(self, operator: str) -> None:
        """연산자를 저장하고 다음 숫자 입력을 준비합니다."""
        current_value = self._to_decimal(self.current_input)
        if current_value is None:
            self._show_error()
            return

        if self.pending_operator and not self.reset_input:
            result = self._perform_operation(self.left_value, current_value, self.pending_operator)
            if result is None:
                self._show_error()
                return
            self.left_value = result
            self.current_input = self._format_decimal(result)
        else:
            self.left_value = current_value

        self.pending_operator = operator
        self.reset_input = True
        self.history_var.set(f"{self._format_decimal(self.left_value)} {self._symbol(operator)}")
        self._update_display()

    def calculate_result(self) -> None:
        """현재까지 입력된 식을 실제로 계산합니다."""
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

        self.current_input = self._format_decimal(result)
        self.display_var.set(self.current_input)
        self.history_var.set(f"{expression} =")
        self.left_value = result
        self.pending_operator = None
        self.reset_input = True

    def _perform_operation(self, left: Decimal | None, right: Decimal, operator: str) -> Decimal | None:
        """선택된 연산자에 따라 실제 계산을 수행합니다."""
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
            return None
        return None

    def _update_display(self) -> None:
        """현재 입력 값을 화면에 반영합니다."""
        self.display_var.set(self.current_input)

    def _show_error(self) -> None:
        """오류가 발생했을 때 화면과 내부 상태를 초기화합니다."""
        self.current_input = "Error"
        self.display_var.set("Error")
        self.history_var.set("")
        self.left_value = None
        self.pending_operator = None
        self.reset_input = True

    @staticmethod
    def _to_decimal(value: str) -> Decimal | None:
        """문자열을 Decimal로 바꿔 float보다 안정적으로 계산합니다."""
        try:
            return Decimal(value)
        except InvalidOperation:
            return None

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        """불필요한 0을 제거해 보기 좋은 숫자 문자열로 바꿉니다."""
        normalized = value.normalize()
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _symbol(operator: str) -> str:
        """필요하면 연산자 표시 문자를 바꿔 쓰기 위한 함수입니다."""
        return operator


def main() -> None:
    """계산기 프로그램을 시작합니다."""
    root = tk.Tk()
    CalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
