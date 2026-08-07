"""
events.py — легковагий Event Bus для міжмодульної комунікації. Нуль залежностей.

Використання:
    from core.events import subscribe, unsubscribe, emit, Events

    subscribe(Events.THEME_CHANGED, self._on_theme)
    emit(Events.THEME_CHANGED, mode="Dark", palette={...})
    unsubscribe(Events.THEME_CHANGED, self._on_theme)   # бажано, але не обов'язково

Правила:
    - Імена подій беруться з класу Events (константи) — одрук дає AttributeError,
      а не тиху поломку (emit за «голим» рядком просто не знайшов би підписників).
    - Аргументи emit() передаються як **kwargs у колбек.
    - Помилки у колбеках логуються, але не переривають інші колбеки.
    - Підписники тримаються СЛАБКО (WeakMethod): коли власник зник — підписка
      прибирається сама. Тому підписувати треба МЕТОДИ (self._on_theme), не голі лямбди.
"""
from __future__ import annotations

import logging
import weakref
from collections import defaultdict
from typing import Callable


class Events:
    """
    Імена подій Event Bus — єдине джерело правди.

    Базові події ядра — THEME_CHANGED, CRASH_OCCURRED. Решта належать ОПЦІЙНИМ
    модулям (optional_modules/) і реально emit-яться лише якщо модуль підключено.
    """
    THEME_CHANGED  = "theme_changed"    # gui/theme.py
    CRASH_OCCURRED = "crash_occurred"   # core/crash_reporter.py

    # ── Опційні модулі (optional_modules/) ──
    HEALTH_CHANGED = "health_changed"   # core/health.py
    STATE_CHANGED  = "state_changed"    # core/state_manager.py


# Кожен елемент — weakref-обгортка над колбеком (WeakMethod або weakref.ref)
_listeners: dict[str, list] = defaultdict(list)
log = logging.getLogger("AppLogger")


def _wrap(callback: Callable):
    """
    Загортає колбек у слабке посилання.
    Зв'язаний метод (має __self__) → WeakMethod (звичайний weakref.ref на bound-метод
    помер би одразу). Звичайна функція → weakref.ref.
    """
    if hasattr(callback, "__self__"):
        return weakref.WeakMethod(callback)
    return weakref.ref(callback)


def subscribe(event: str, callback: Callable) -> None:
    """Підписує колбек на подію (без дублів)."""
    if not hasattr(callback, "__self__") and getattr(callback, "__name__", "") == "<lambda>":
        # Гола лямбда без власника — WeakMethod/weakref збере її одразу, підписка стане
        # тихим no-op. Попереджаємо про цей класичний foot-gun. Названі функції, на які
        # розробник свідомо тримає посилання (напр. атрибут віджета), не чіпаємо.
        log.warning(
            f"subscribe('{event}'): передано голу лямбду — слабке посилання збере її "
            f"одразу. Підписуй self._метод або тримай посилання на названу функцію."
        )
    refs = _listeners[event]
    if not any(r() == callback for r in refs):
        refs.append(_wrap(callback))


def unsubscribe(event: str, callback: Callable) -> None:
    """Знімає підписку. Безпечно викликати навіть якщо підписки вже немає."""
    refs = _listeners.get(event)
    if not refs:
        return
    _listeners[event] = [r for r in refs if r() is not None and r() != callback]


def emit(event: str, **kwargs) -> None:
    """
    Викликає всіх живих підписників події. Мертві (власник зник) — прибирає.

    Ітеруємо КОПІЮ списку, тому підписка/відписка всередині колбека безпечна.
    Перезбираємо список лише якщо знайшли мертві посилання.
    """
    refs = _listeners.get(event)
    if not refs:
        return
    dead = []
    for ref in list(refs):
        cb = ref()
        if cb is None:          # власник зібраний GC
            dead.append(ref)
            continue
        try:
            cb(**kwargs)
        except Exception as exc:
            log.error(f"Помилка у підписнику '{event}' ({cb!r}): {exc}", exc_info=True)
    if dead:
        _listeners[event] = [r for r in refs if r not in dead]


def clear(event: str | None = None) -> None:
    """Очищає підписки однієї події або всіх (event=None)."""
    if event is None:
        _listeners.clear()
    else:
        _listeners[event].clear()


def listeners_count(event: str) -> int:
    """Кількість ЖИВИХ підписників події (для діагностики/тестів)."""
    return sum(1 for r in _listeners.get(event, []) if r() is not None)
