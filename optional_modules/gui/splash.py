"""
splash.py — вікно завантаження програми. ОПЦІЙНИЙ модуль.

Показується між запуском і відкриттям головного вікна. НЕ додавати у проєкт, якщо
старт швидший за 2-3 секунди — поточний шаблон стартує за < 1с і splash йому не потрібен.

⚠️ tk.Tk, а не ctk.CTk: set_default_color_theme() має викликатись ДО першого CTk-вікна,
   а splash з'являється ще раніше. Тому — чистий tk.Tk з ручними кольорами.

Підключення: скопіювати у gui/.
    splash = SplashScreen(app_name=build_info.APP_NAME, version=build_info.APP_VERSION)
    splash.set_status("Завантаження бази...", progress=0.3)
    splash.close()   # перед відкриттям головного вікна
"""
from __future__ import annotations

import tkinter as tk

from core.logger import log


class SplashScreen:
    """Вікно завантаження без рамки з прогрес-баром на Canvas (без залежностей)."""

    WIDTH = 360
    HEIGHT = 200

    def __init__(self, app_name: str = "MyAppName", version: str = "1.0.0",
                 icon_path: str | None = None) -> None:
        self._app_name = app_name
        self._version = version
        self._progress: float = 0.0

        self._root = tk.Tk()
        self._root.overrideredirect(True)        # без рамки
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#2B2B2B")       # Gray-тема за замовчуванням
        self._root.lift()

        self._center()
        self._build_ui()
        self._root.update()
        log.info("Splash screen показано.")

    def _center(self) -> None:
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - self.WIDTH) // 2
        y = (sh - self.HEIGHT) // 2
        self._root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _build_ui(self) -> None:
        bg, fg, fg_dim, accent = "#2B2B2B", "#E8E8E8", "#AAAAAA", "#1f538d"

        tk.Label(self._root, text=self._app_name, bg=bg, fg=fg,
                 font=("Segoe UI", 18, "bold")).pack(pady=(40, 0))
        tk.Label(self._root, text=self._version, bg=bg, fg=fg_dim,
                 font=("Segoe UI", 10)).pack(pady=(2, 0))

        bar_frame = tk.Frame(self._root, bg=bg)
        bar_frame.pack(pady=(20, 4), padx=40, fill="x")
        self._canvas = tk.Canvas(bar_frame, height=6, bg="#444444", highlightthickness=0, bd=0)
        self._canvas.pack(fill="x")
        self._bar = self._canvas.create_rectangle(0, 0, 0, 6, fill=accent, width=0)
        self._canvas.bind("<Configure>", lambda _: self._update_bar(self._progress))

        self._status_var = tk.StringVar(value="Ініціалізація...")
        tk.Label(self._root, textvariable=self._status_var, bg=bg, fg=fg_dim,
                 font=("Segoe UI", 9)).pack()

    def set_status(self, text: str, progress: float = 0.0) -> None:
        """Оновлює статус і прогрес-бар (progress: 0.0–1.0)."""
        self._progress = max(0.0, min(1.0, progress))
        self._status_var.set(text)
        self._update_bar(self._progress)
        self._root.update()

    def _update_bar(self, progress: float) -> None:
        w = self._canvas.winfo_width()
        if w <= 1:
            return
        self._canvas.coords(self._bar, 0, 0, int(w * progress), 6)

    def close(self) -> None:
        """Закриває splash screen."""
        log.info("Splash screen закрито.")
        try:
            self._root.destroy()
        except Exception:
            pass
