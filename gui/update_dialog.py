"""
update_dialog.py — немодальний діалог оновлення.
Не використовує grab_set() — головне вікно залишається активним (проблема OBS вирішена).
Esc закриває діалог, якщо не йде завантаження. Підписується на THEME_CHANGED.
"""
from __future__ import annotations

import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from core.events import subscribe, unsubscribe, Events
from core.logger import log
from core.updater import UpdateInfo, launch_update
import core.build_info as build_info
from gui.theme import theme_mgr


def show_update_dialog(parent: ctk.CTk, info: UpdateInfo) -> "UpdateDialog":
    """Створює і показує діалог оновлення."""
    dialog = UpdateDialog(parent, info)
    dialog.focus()
    return dialog


class UpdateDialog(ctk.CTkToplevel):
    """Немодальний CTkToplevel з changelog і прогрес-баром."""

    _GITHUB_RELEASES_URL = f"https://github.com/{build_info.GITHUB_REPO}/releases"

    def __init__(self, parent: ctk.CTk, info: UpdateInfo) -> None:
        super().__init__(parent)
        self._parent = parent
        self._info = info
        self._downloading = False

        self.title(f"Доступне оновлення v{info.version}")
        self.geometry("560x460")
        self.minsize(480, 380)
        self.transient(parent)
        # grab_set() — СВІДОМО НЕ ВИКЛИКАЄМО

        self._center_on_parent()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # рядок changelog-боксу розтягується

        self._build_header()
        self._build_changelog()
        self._build_progress()
        self._build_buttons()

        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        subscribe(Events.THEME_CHANGED, self._on_theme)
        self._on_theme(mode=theme_mgr.resolved_mode, palette=theme_mgr.get_palette())

    def _build_header(self) -> None:
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        frame.grid(row=0, column=0, padx=20, pady=(16, 0), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame, text=f"🎉  Доступне оновлення — v{self._info.version}",
            font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            frame,
            text=f"Поточна версія: {build_info.APP_VERSION}  →  Нова: {self._info.version}",
            font=ctk.CTkFont(size=12), anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_changelog(self) -> None:
        # Фікс: лейбл і бокс — у ОКРЕМИХ рядках grid (раніше обидва в row=1 з pady-хаком,
        # що накладались при зміні шрифту/масштабу).
        ctk.CTkLabel(
            self, text="Що нового:", font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(12, 2), sticky="nw")
        self._changelog_box = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", state="disabled",
        )
        self._changelog_box.grid(row=2, column=0, padx=20, pady=(0, 0), sticky="nsew")
        self._changelog_box.configure(state="normal")
        self._changelog_box.insert("1.0", self._info.changelog or "(Changelog відсутній)")
        self._changelog_box.configure(state="disabled")

    def _build_progress(self) -> None:
        self._progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._progress_frame.grid(row=3, column=0, padx=20, pady=(8, 0), sticky="ew")
        self._progress_frame.grid_columnconfigure(0, weight=1)
        self._progress_bar = ctk.CTkProgressBar(self._progress_frame, mode="indeterminate", height=8)
        self._progress_bar.grid(row=0, column=0, sticky="ew")
        self._progress_label = ctk.CTkLabel(
            self._progress_frame, text="Завантаження...", font=ctk.CTkFont(size=11), anchor="w",
        )
        self._progress_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._progress_frame.grid_remove()

    def _build_buttons(self) -> None:
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=4, column=0, padx=20, pady=16, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        self._btn_github = ctk.CTkButton(
            btn_frame, text="🌐  Відкрити GitHub Releases",
            command=self._open_github, fg_color="transparent", border_width=1, width=200,
        )
        self._btn_github.grid(row=0, column=0, sticky="w")
        right = ctk.CTkFrame(btn_frame, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        self._btn_later = ctk.CTkButton(
            right, text="Пізніше", command=self._on_close,
            fg_color="transparent", border_width=1, width=90,
        )
        self._btn_later.grid(row=0, column=0, padx=(0, 8))
        update_label = ("⬇  Оновити автоматично" if build_info.DISTRIBUTION == "portable"
                        else "⬇  Встановити оновлення")
        self._btn_update = ctk.CTkButton(
            right, text=update_label, command=self._on_update_click, width=190,
        )
        self._btn_update.grid(row=0, column=1)

    def _on_update_click(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self._set_buttons_state("disabled")
        self._show_progress(True)
        log.info(f"Оновлення до v{self._info.version}")
        launch_update(root=self._parent, info=self._info, on_progress=self._on_progress)

    def _on_progress(self, pct: int) -> None:
        self.after(0, self._update_progress_ui, pct)

    def _update_progress_ui(self, pct: int) -> None:
        if pct == -1:
            self._show_progress(False)
            self._set_buttons_state("normal")
            self._downloading = False
            messagebox.showerror(
                "Помилка оновлення",
                "Не вдалося завантажити оновлення.\n"
                "Перевірте з'єднання або завантажте вручну з GitHub.", parent=self,
            )
        elif pct < 100:
            self._progress_label.configure(text=f"Завантаження... {pct}%")
        else:
            self._progress_label.configure(text="Завантажено. Застосовую оновлення...")

    def _open_github(self) -> None:
        webbrowser.open(self._GITHUB_RELEASES_URL)

    def _on_escape(self, _event=None) -> None:
        if not self._downloading:
            self._on_close()

    def _on_close(self) -> None:
        if self._downloading:
            return
        self.destroy()

    def _show_progress(self, visible: bool) -> None:
        if visible:
            self._progress_frame.grid()
            self._progress_bar.start()
        else:
            self._progress_bar.stop()
            self._progress_frame.grid_remove()

    def _set_buttons_state(self, state: str) -> None:
        self._btn_update.configure(state=state)
        self._btn_later.configure(state=state)
        self._btn_github.configure(state=state)

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        dw, dh = 560, 460
        x = self._parent.winfo_x() + (self._parent.winfo_width() - dw) // 2
        y = self._parent.winfo_y() + (self._parent.winfo_height() - dh) // 2
        self.geometry(f"{dw}x{dh}+{x}+{y}")

    def _on_theme(self, mode: str, palette: dict) -> None:
        # CTk-віджети appearance_mode підхоплюють самі, але фон Toplevel за палітрою
        # (важливо для Gray, де CTk-режим == Dark) треба застосувати вручну.
        try:
            self.configure(fg_color=palette["window_bg"])
        except Exception:
            pass  # діалог міг бути вже знищений — не критично

    def destroy(self) -> None:
        unsubscribe(Events.THEME_CHANGED, self._on_theme)
        super().destroy()
