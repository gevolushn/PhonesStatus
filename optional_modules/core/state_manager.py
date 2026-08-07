"""
state_manager.py — єдине сховище runtime-стану програми. ОПЦІЙНИЙ модуль.

Стан — dict[str, Any]. Зміна будь-якого ключа:
  1. Оновлює внутрішній dict
  2. Логує зміну (рівень DEBUG)
  3. Емітує Event Bus подію STATE_CHANGED (key, value, prev_value)

Підключення: скопіювати у core/.
    from core.state_manager import state
    state.register("is_processing", False)
    state.set("is_processing", True)
    subscribe(Events.STATE_CHANGED, self._on_state)
"""
from __future__ import annotations

import threading
from typing import Any

from core.events import Events
from core.logger import log


class StateManager:
    """
    Потокобезпечний глобальний стан програми.
    Ключі реєструються через register() з дефолтом. Незареєстрований теж працює — без reset().
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._defaults: dict[str, Any] = {}
        self._lock = threading.Lock()

    def register(self, key: str, default: Any) -> None:
        """Зареєструвати ключ з дефолтним значенням."""
        with self._lock:
            self._defaults[key] = default
            if key not in self._data:
                self._data[key] = default

    def set(self, key: str, value: Any) -> None:
        """Встановити значення. Емітує STATE_CHANGED лише якщо значення змінилось."""
        with self._lock:
            prev = self._data.get(key)
            if prev == value:
                return
            self._data[key] = value

        log.debug(f"State [{key}]: {prev!r} → {value!r}")
        try:
            from core.events import emit
            emit(Events.STATE_CHANGED, key=key, value=value, prev_value=prev)
        except Exception as e:
            log.warning(f"State emit помилка: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Отримати поточне значення."""
        with self._lock:
            return self._data.get(key, default)

    def reset(self, key: str) -> None:
        """Скинути ключ до зареєстрованого дефолту."""
        if key not in self._defaults:
            log.warning(f"State.reset: ключ '{key}' не зареєстровано.")
            return
        self.set(key, self._defaults[key])

    def reset_all(self) -> None:
        """Скинути всі зареєстровані ключі до дефолтів."""
        with self._lock:
            keys = list(self._defaults.keys())
        for key in keys:
            self.reset(key)

    def snapshot(self) -> dict[str, Any]:
        """Копія поточного стану (для дебагінгу або збереження сесії)."""
        with self._lock:
            return dict(self._data)


# Глобальний синглтон — імпортувати прямо: from core.state_manager import state
state = StateManager()
