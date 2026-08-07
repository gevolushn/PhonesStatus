"""
theme.py — менеджер тем програми (Light / Gray / Dark / System) з плавним fade.
Синглтон theme_mgr — імпортувати скрізь як: from gui.theme import theme_mgr

ThemeManager — ЧИСТИЙ UI-стан: застосовує appearance_mode і робить emit(THEME_CHANGED).
Він НЕ зберігає конфіг сам (Варіант B): персистентність і застосування палітри до вікна —
справа підписника app_window._on_theme_changed. Так прибрано I/O всередині fade-анімації.

Режим "Gray" (Word-style, #2B2B2B) і "Dark" обидва мапляться у CTk appearance "Dark",
тож різниця між ними живе у PALETTE — і має застосовуватись підписниками вручну
(інакше Gray візуально == Dark).
"""
from __future__ import annotations

import customtkinter as ctk

from core.events import emit, Events
from core.logger import log

PALETTE: dict[str, dict[str, str]] = {
    "Light": {
        "window_bg": "#F3F3F3", "frame_bg": "#EBEBEB", "frame_top": "#E5E5E5",
        "text": "#1A1A1A", "text_dim": "#666666", "border": "#C0C0C0",
        "entry_bg": "#FFFFFF",
        "menu_bg": "#F9F9F9", "menu_fg": "#1A1A1A",
        "menu_active_bg": "#E5E7EB", "menu_active_fg": "#1A1A1A",
        "scrollbar": "#BBBBBB", "scrollbar_hover": "#999999", "separator": "#D1D5DB",
    },
    "Gray": {
        "window_bg": "#2B2B2B", "frame_bg": "#333333", "frame_top": "#3A3A3A",
        "text": "#E8E8E8", "text_dim": "#AAAAAA", "border": "#555555",
        "entry_bg": "#3D3D3D",
        "menu_bg": "#2E2E2E", "menu_fg": "#E8E8E8",
        "menu_active_bg": "#454545", "menu_active_fg": "#FFFFFF",
        "scrollbar": "#555555", "scrollbar_hover": "#777777", "separator": "#484848",
    },
    "Dark": {
        "window_bg": "#1A1A1A", "frame_bg": "#212121", "frame_top": "#282828",
        "text": "#DEDEDE", "text_dim": "#888888", "border": "#444444",
        "entry_bg": "#2A2A2A",
        "menu_bg": "#1E1E1E", "menu_fg": "#DEDEDE",
        "menu_active_bg": "#333333", "menu_active_fg": "#FFFFFF",
        "scrollbar": "#444444", "scrollbar_hover": "#666666", "separator": "#333333",
    },
}

_CTK_MODE: dict[str, str] = {"Light": "Light", "Gray": "Dark", "Dark": "Dark", "System": "System"}
VALID_MODES: tuple[str, ...] = ("Light", "Gray", "Dark", "System")
DEFAULT_MODE: str = "Dark"
_FADE_DURATION_MS: int = 80
_FADE_ALPHA_DIM: float = 0.75


def _get_system_mode() -> str:
    """Зчитує системну тему Windows (Light/Dark). При помилці — Dark."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "Light" if value == 1 else "Dark"
    except Exception:
        return "Dark"


class ThemeManager:
    """Менеджер appearance_mode з fade-переходом. Не пише конфіг — лише emit."""

    def __init__(self) -> None:
        self._root = None
        self._current_mode = DEFAULT_MODE
        self._resolved_mode = DEFAULT_MODE

    def load(self, root: ctk.CTk, config: dict) -> None:
        """Ініціалізує тему з конфігу ПІСЛЯ побудови всіх віджетів (щоб emit дійшов до підписників)."""
        self._root = root
        mode = config.get("appearance_mode", DEFAULT_MODE)
        if mode not in VALID_MODES:
            mode = _get_system_mode()
        self._current_mode = mode
        self._resolved_mode = _get_system_mode() if mode == "System" else mode
        ctk.set_appearance_mode(_CTK_MODE[mode])
        log.info(f"Тема ініціалізована: {mode}")
        emit(Events.THEME_CHANGED, mode=self._resolved_mode, palette=self._get_palette())

    def apply(self, mode: str) -> None:
        """Перемикає режим теми з fade-анімацією. Вибір зберігає підписник у app_window."""
        if mode not in VALID_MODES or mode == self._current_mode:
            return
        self._current_mode = mode
        self._resolved_mode = _get_system_mode() if mode == "System" else mode
        if self._root and self._root.winfo_exists():
            self._fade_out()

    def _fade_out(self) -> None:
        self._root.wm_attributes("-alpha", _FADE_ALPHA_DIM)
        self._root.after(_FADE_DURATION_MS, self._switch)

    def _switch(self) -> None:
        # Вікно могло зникнути за час fade (80 мс) — без перевірки буде TclError
        if not (self._root and self._root.winfo_exists()):
            return
        ctk.set_appearance_mode(_CTK_MODE[self._current_mode])
        # Конфіг НЕ пишемо тут (Варіант B): персистентність — підписник у app_window.
        emit(Events.THEME_CHANGED, mode=self._resolved_mode, palette=self._get_palette())
        self._root.after(_FADE_DURATION_MS, self._fade_in)

    def _fade_in(self) -> None:
        if self._root and self._root.winfo_exists():
            self._root.wm_attributes("-alpha", 1.0)

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def resolved_mode(self) -> str:
        return self._resolved_mode

    def get_palette(self) -> dict[str, str]:
        """Палітра поточного (resolved) режиму. Для tk.Menu, Canvas, фабрики віджетів."""
        return self._get_palette()

    def _get_palette(self) -> dict[str, str]:
        return PALETTE.get(self._resolved_mode, PALETTE[DEFAULT_MODE])


theme_mgr = ThemeManager()
