"""
dialogs.py — кастомні діалоги у стилі CustomTkinter. ОПЦІЙНИЙ модуль.

Замінюють стандартні tkinter-діалоги (messagebox/simpledialog), що не знають про тему.
Три типи: confirm, ask_input, ask_file/ask_save_file.

⚠️ grab_set() ТУТ викликається (модальні діалоги-питання) — на відміну від UpdateDialog,
   де він свідомо НЕ викликається (інформаційний, не блокує головне вікно).

Підключення: скопіювати у gui/.
    from gui.dialogs import confirm, ask_input, ask_file
"""
from __future__ import annotations

import os
from typing import Callable

import customtkinter as ctk

from core.events import subscribe, unsubscribe, Events
from gui.theme import theme_mgr
from gui.window_utils import center_on_parent


# ─── Базовий клас для всіх діалогів ──────────────────────────────────────────

class _BaseDialog(ctk.CTkToplevel):
    """Базовий клас: центрування, тема, Esc, модальність (grab_set)."""

    def __init__(self, parent: ctk.CTk, title: str, width: int = 420, height: int = 220) -> None:
        super().__init__(parent)
        self._parent = parent
        self._result = None

        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()   # модальний — блокує батьківське вікно

        self._center(width, height)
        self.grid_columnconfigure(0, weight=1)

        subscribe(Events.THEME_CHANGED, self._on_theme)
        self._on_theme(mode=theme_mgr.resolved_mode, palette=theme_mgr.get_palette())
        self.bind("<Escape>", self._on_escape)

    def _center(self, w: int, h: int) -> None:
        center_on_parent(self, self._parent, w, h)

    def _on_theme(self, mode: str, palette: dict) -> None:
        try:
            self.configure(fg_color=palette["window_bg"])
        except Exception:
            pass

    def _on_escape(self, _event=None) -> None:
        self._result = None
        self.destroy()

    def destroy(self) -> None:
        unsubscribe(Events.THEME_CHANGED, self._on_theme)
        super().destroy()

    def wait_result(self):
        """Блокує виконання поки діалог не закриється. Повертає _result."""
        self.wait_window()
        return self._result


# ─── 1. confirm() ─────────────────────────────────────────────────────────────

class _ConfirmDialog(_BaseDialog):
    """Діалог підтвердження. Замінює messagebox.askyesno. danger=True → червона кнопка."""

    def __init__(self, parent, title, message, confirm_text="OK",
                 cancel_text="Скасувати", danger=False) -> None:
        super().__init__(parent, title, width=420, height=180)

        ctk.CTkLabel(
            self, text=message, font=ctk.CTkFont(size=13),
            wraplength=370, justify="left", anchor="w",
        ).grid(row=0, column=0, padx=24, pady=(20, 16), sticky="ew")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, padx=24, pady=(0, 20), sticky="e")

        ctk.CTkButton(
            btn_frame, text=cancel_text, width=100,
            fg_color="transparent", border_width=1, command=self._on_cancel,
        ).pack(side="left", padx=(0, 8))

        confirm_colors = {"fg_color": "#8d1f1f", "hover_color": "#5e1414"} if danger else {}
        ctk.CTkButton(
            btn_frame, text=confirm_text, width=100, command=self._on_confirm, **confirm_colors,
        ).pack(side="left")

    def _on_confirm(self) -> None:
        self._result = True
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = False
        self.destroy()


def confirm(parent, title, message, confirm_text="OK",
            cancel_text="Скасувати", danger=False) -> bool:
    """
    Діалог підтвердження у стилі CustomTkinter. Повертає True/False.

    Приклад:
        if confirm(self, "Видалити файл", "Цю дію не можна скасувати.", danger=True):
            os.remove(path)
    """
    dialog = _ConfirmDialog(parent, title, message, confirm_text, cancel_text, danger)
    return dialog.wait_result() or False


# ─── 2. ask_input() ───────────────────────────────────────────────────────────

class _InputDialog(_BaseDialog):
    """Діалог введення тексту з валідацією в реальному часі. Замінює simpledialog.askstring."""

    def __init__(self, parent, title, label, default="", placeholder="",
                 validator: Callable[[str], str | None] | None = None) -> None:
        super().__init__(parent, title, width=420, height=230)
        self._validator = validator

        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=13), anchor="w").grid(
            row=0, column=0, padx=24, pady=(20, 4), sticky="w")

        self._entry = ctk.CTkEntry(self, width=370, placeholder_text=placeholder)
        self._entry.grid(row=1, column=0, padx=24, pady=(0, 4), sticky="ew")
        if default:
            self._entry.insert(0, default)

        self._error_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="#e05252", anchor="w")
        self._error_label.grid(row=2, column=0, padx=24, pady=0, sticky="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=24, pady=(8, 20), sticky="e")
        ctk.CTkButton(
            btn_frame, text="Скасувати", width=100,
            fg_color="transparent", border_width=1, command=self._on_cancel,
        ).pack(side="left", padx=(0, 8))
        self._btn_ok = ctk.CTkButton(btn_frame, text="OK", width=100, command=self._on_ok)
        self._btn_ok.pack(side="left")

        self._entry.bind("<Return>", lambda _: self._on_ok())
        self._entry.bind("<KeyRelease>", self._on_key)
        self._entry.focus()

    def _on_key(self, _event=None) -> None:
        if self._validator is None:
            return
        error = self._validator(self._entry.get())
        self._error_label.configure(text=error or "")
        self._btn_ok.configure(state="normal" if not error else "disabled")

    def _on_ok(self) -> None:
        value = self._entry.get().strip()
        if self._validator:
            error = self._validator(value)
            if error:
                self._error_label.configure(text=error)
                return
        self._result = value
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.destroy()


def ask_input(parent, title, label, default="", placeholder="",
              validator: Callable[[str], str | None] | None = None) -> str | None:
    """
    Діалог введення тексту. validator: (str) → str|None (рядок помилки або None).
    Кнопка OK блокується поки є помилка. Повертає рядок або None.

    Приклад:
        def _check(v):
            return "Поле порожнє" if not v else None
        name = ask_input(self, "Назва", "Введіть назву:", validator=_check)
    """
    dialog = _InputDialog(parent, title, label, default, placeholder, validator)
    return dialog.wait_result()


# ─── 3. ask_file() / ask_save_file() ──────────────────────────────────────────

def ask_file(parent, title="Відкрити файл",
             filetypes: list[tuple[str, str]] | None = None,
             initialdir: str | None = None) -> str | None:
    """
    Обгортка над filedialog.askopenfilename. Нативний діалог Windows не стилізується —
    функція уніфікує виклик і дозволяє замінити реалізацію у майбутньому. Повертає шлях або None.
    """
    from tkinter import filedialog
    result = filedialog.askopenfilename(
        parent=parent, title=title,
        filetypes=filetypes or [("Всі файли", "*.*")],
        initialdir=initialdir or os.path.expanduser("~"),
    )
    return result or None


def ask_save_file(parent, title="Зберегти файл",
                  filetypes: list[tuple[str, str]] | None = None,
                  defaultextension: str = "", initialfile: str = "",
                  initialdir: str | None = None) -> str | None:
    """Обгортка над filedialog.asksaveasfilename. Повертає шлях для збереження або None."""
    from tkinter import filedialog
    result = filedialog.asksaveasfilename(
        parent=parent, title=title,
        filetypes=filetypes or [("Всі файли", "*.*")],
        defaultextension=defaultextension, initialfile=initialfile,
        initialdir=initialdir or os.path.expanduser("~"),
    )
    return result or None
