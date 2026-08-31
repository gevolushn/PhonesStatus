"""
progress.py — BackgroundTask: фонова задача з прогрес-індикатором. ОПЦІЙНИЙ модуль.

Прибирає copy-paste патерну «заблокувати кнопку → показати індикатор → запустити
поток → розблокувати». Усі UI-операції — через root.after(0, ...), потокобезпечно.

Підключення: скопіювати у gui/.
    from gui.progress import BackgroundTask

    def _on_parse_click(self):
        BackgroundTask(root=self, label="Обробка...", btn_lock=[self._btn_parse]).run(
            work=lambda: self._parser.run(self._input.get()),
            on_done=lambda result: self._output.set(result),
            on_error=self._show_error,
        )
"""
from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk


class BackgroundTask:
    """
    Запускає work() у фоновому потоці, показуючи indeterminate-прогрес і блокуючи кнопки.
    Після завершення приховує індикатор, розблоковує кнопки і викликає on_done/on_error.
    """

    def __init__(self, root, label: str = "Обробка...", btn_lock: list | None = None) -> None:
        self._root = root
        self._label_text = label
        self._btn_lock = btn_lock or []
        self._bar: ctk.CTkProgressBar | None = None

    def run(
        self,
        work: Callable,
        on_done: Callable | None = None,
        on_error: Callable | None = None,
    ) -> None:
        """Блокує кнопки, показує індикатор, виконує work() у потоці."""
        self._lock(True)
        self._show()

        def _worker() -> None:
            try:
                result = work()
            except Exception as exc:
                # ⚠️ ВІДХИЛЕННЯ ВІД ШАБЛОНУ (2.5.0) — виправлений дефект.
                # Python наприкінці блоку except неявно робить `del exc`. Шаблонний
                # `lambda: self._finish(on_error, exc)` захоплює вільну змінну за
                # посиланням і виконується ПІЗНІШЕ (через after) — коли `exc` уже
                # не існує, тож замість on_error спрацьовував NameError у лог.
                # Тобто гілка помилки в BackgroundTask не працювала НІКОЛИ.
                # Фікс — прив'язати виняток значенням через дефолт параметра.
                self._root.after(0, lambda e=exc: self._finish(on_error, e))
                return
            self._root.after(0, lambda r=result: self._finish(on_done, r))

        threading.Thread(target=_worker, daemon=True, name="BackgroundTask").start()

    # ── Внутрішнє ─────────────────────────────────────────────────────────────

    def _show(self) -> None:
        self._bar = ctk.CTkProgressBar(self._root, mode="indeterminate", height=6, width=240)
        self._bar.place(relx=0.5, rely=0.99, anchor="s")  # накладка внизу, не ламає layout
        self._bar.start()

    def _hide(self) -> None:
        if self._bar is not None:
            self._bar.stop()
            self._bar.destroy()
            self._bar = None

    def _lock(self, locked: bool) -> None:
        state = "disabled" if locked else "normal"
        for btn in self._btn_lock:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _finish(self, callback: Callable | None, payload) -> None:
        self._hide()
        self._lock(False)
        if callback is not None:
            callback(payload)
