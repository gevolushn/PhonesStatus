"""
instance_lock.py — не дозволяє запустити другу копію програми (Windows).

Метод — Windows Named Mutex через ctypes: нуль залежностей, ОС сама прибирає mutex
при будь-якому завершенні (stale lock неможливий), атомарна перевірка+створення.
Так роблять Chrome, Steam, Visual Studio.

⚠️ Простір імен — 'Local\\' за замовчуванням, НЕ 'Global\\'. 'Global\\' потребує
привілею SeCreateGlobalPrivilege, якого немає у фільтрованому (не-elevated) токені
звичайного користувача. З ним `CreateMutexW` повертав NULL + ERROR_ACCESS_DENIED(5), а
стара версія коду перевіряла лише «код == 183 (ALREADY_EXISTS)» і йшла далі — захист від
другої копії вимикався МОВЧКИ для будь-кого, хто запускав програму без адмінських прав.

Якщо потрібен один екземпляр на всю МАШИНУ (включно з іншими користувачами) — це
свідомий вибір: `check_single_instance(namespace="Global")`. Тоді ERROR_ACCESS_DENIED
логується явно, і йде фолбек на Local — краще захист у межах сеансу, ніж жодного захисту.

Логіка розділена на дві частини:
    acquire()               — чиста: без MessageBox, без sys.exit. Тестопридатна.
    check_single_instance() — тонка обгортка з UI-реакцією на другу копію.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from core.logger import log
import core.build_info as build_info

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5

# argtypes/restype — обов'язково на x64: без явних сигнатур ctypes вважає, що функція
# повертає 32-бітний int, і покажчик HANDLE (64-бітний) мовчки обрізається. Той самий
# клас багів, що вже описаний для DPAPI в docs/BACKLOG.md.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
_user32.MessageBoxW.restype = ctypes.c_int


def _create_mutex(name: str) -> tuple[wintypes.HANDLE | None, int]:
    """Один виклик CreateMutexW. Повертає (handle або None, GetLastError())."""
    handle = _kernel32.CreateMutexW(None, False, name)
    error = ctypes.get_last_error()   # ЗАВЖДИ одразу після виклику — не між ctypes-викликами
    return handle, error


def acquire(namespace: str = "Local") -> tuple[wintypes.HANDLE | None, bool]:
    """
    Створює mutex єдиного екземпляра. Без побічних ефектів UI — придатна для тестів.

    Повертає (handle, already_running). handle може бути None, навіть якщо
    already_running=False — якщо mutex не вдалось створити взагалі (рідкісний системний
    збій): викликач тоді просто не отримує захисту, але й не падає з винятком.
    """
    name = f"{namespace}\\{build_info.APP_MUTEX}"
    handle, error = _create_mutex(name)

    if handle is None and error == _ERROR_ACCESS_DENIED and namespace == "Global":
        log.warning(
            "Немає прав на простір імен 'Global\\' (SeCreateGlobalPrivilege) — "
            "переходжу на 'Local\\'. Захист діятиме в межах поточного сеансу, "
            "не всієї машини."
        )
        handle, error = _create_mutex(f"Local\\{build_info.APP_MUTEX}")

    if handle is None:
        log.warning(f"Не вдалося створити mutex єдиного екземпляра (код помилки {error}).")
        return None, False

    return handle, error == _ERROR_ALREADY_EXISTS


def check_single_instance(namespace: str = "Local"):
    """
    acquire() + реакція на другу копію: повідомлення і вихід.

    Повертає handle — обов'язково зберігати у змінній (наприклад, у main()), щоб GC
    не зібрав його й mutex жив до завершення процесу.
    """
    handle, already_running = acquire(namespace)
    if already_running:
        log.warning("Друга копія програми вже запущена.")
        _user32.MessageBoxW(
            0,
            "Програма вже запущена.",
            build_info.APP_NAME,
            0x30,  # MB_ICONWARNING
        )
        sys.exit(0)
    return handle
