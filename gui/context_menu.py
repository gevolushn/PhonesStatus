"""
context_menu.py — адаптивне ПКМ-меню (Entry / Readonly / Textbox).
Підписується на THEME_CHANGED через Event Bus. НЕ імпортує gui.theme напряму.
При закритті вікна/діалогу — обов'язково викликати ctx.destroy().
"""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from core.events import subscribe, unsubscribe, Events


class AppContextMenu:
    """Контекстне меню, що адаптується під тип віджета і поточну тему."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._menu: tk.Menu | None = None   # поточне меню — щоб знищувати попереднє
        self._menu_bg = "#F9F9F9"
        self._menu_fg = "#1A1A1A"
        self._menu_active_bg = "#E5E7EB"
        self._menu_active_fg = "#1A1A1A"
        subscribe(Events.THEME_CHANGED, self._on_theme)

    def bind_all(self, widgets: list[tk.Widget]) -> None:
        """Прив'язує ПКМ до переданих віджетів."""
        for widget in widgets:
            widget.bind("<Button-3>", lambda e, w=widget: self._show(e, w))

    def _show(self, event: tk.Event, widget: tk.Widget) -> None:
        # tk.Menu не звільняється GC-ом Python — лишається дочірнім віджетом root,
        # доки явно не .destroy(). Без цього кожен ПКМ-клік накопичує нове меню.
        if self._menu is not None:
            self._menu.destroy()
            self._menu = None
        self._menu = self._build_menu(widget)
        if self._menu is None:
            return
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _build_menu(self, widget: tk.Widget) -> tk.Menu | None:
        menu = tk.Menu(
            self._root, tearoff=0,
            bg=self._menu_bg, fg=self._menu_fg,
            activebackground=self._menu_active_bg,
            activeforeground=self._menu_active_fg,
            relief="flat", bd=0,
        )
        is_textbox = isinstance(widget, ctk.CTkTextbox)
        is_entry = isinstance(widget, (ctk.CTkEntry, tk.Entry))
        is_combo = isinstance(widget, ctk.CTkComboBox)
        if is_textbox or is_entry:
            menu.add_command(label="Вирізати",    command=lambda: widget.event_generate("<<Cut>>"))
            menu.add_command(label="Копіювати",   command=lambda: widget.event_generate("<<Copy>>"))
            menu.add_command(label="Вставити",    command=lambda: widget.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="Вибрати все", command=lambda: widget.event_generate("<<SelectAll>>"))
            if is_textbox:
                menu.add_separator()
                menu.add_command(label="Скасувати", command=lambda: widget.event_generate("<<Undo>>"))
        elif is_combo:
            menu.add_command(label="Копіювати", command=lambda: widget.event_generate("<<Copy>>"))
        else:
            return None
        return menu

    def _on_theme(self, mode: str, palette: dict) -> None:
        self._menu_bg        = palette.get("menu_bg",        self._menu_bg)
        self._menu_fg        = palette.get("menu_fg",        self._menu_fg)
        self._menu_active_bg = palette.get("menu_active_bg", self._menu_active_bg)
        self._menu_active_fg = palette.get("menu_active_fg", self._menu_active_fg)

    def destroy(self) -> None:
        """Відписка від Event Bus і знищення меню. Викликати при закритті вікна/діалогу."""
        unsubscribe(Events.THEME_CHANGED, self._on_theme)
        if self._menu is not None:
            self._menu.destroy()
            self._menu = None
