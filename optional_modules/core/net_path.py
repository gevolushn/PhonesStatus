"""
net_path.py — UNC замість букви мережевого диска. ОПЦІЙНИЙ модуль.

Буква мережевого диска — це не властивість машини, а запис у ТОКЕНІ СЕАНСУ. Наслідки,
кожен з яких виглядає як окремий баг програми:
  - диск, підключений у звичайному сеансі, НЕ видно з-під адміністратора (інший токен,
    інший набір мапінгів) — і навпаки;
  - автозапуск при вході може стартувати РАНІШЕ, ніж Windows відновить постійні мапінги —
    диск тимчасово недоступний, хоча за секунду з'явиться сам;
  - `EnableLinkedConnections=1` (HKLM\\SYSTEM\\CurrentControlSet\\Control\\Lsa) вирівнює
    токени, але вимкнений за замовчуванням — розраховувати на нього не можна.

UNC-шлях (\\\\server\\share) не залежить ні від токена, ні від моменту входу — тому
мережеві шляхи варто резолвити в UNC ЯКНАЙРАНІШЕ, а не використовувати літеру диска
напряму.

Підключення: скопіювати у core/. Типове використання — викликати resolve_unc()
автоматично, коли core.elevation.is_elevated() і шлях є буквою диска (найчастіший
сценарій розбіжності):

    from core.elevation import is_elevated
    from core.net_path import resolve_unc, is_network_path

    if is_elevated() and is_network_path(user_path):
        user_path = resolve_unc(user_path)

Залежності: лише ctypes (winnt mpr.dll), нуль pip-пакетів.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from core.logger import log

_mpr = ctypes.WinDLL("mpr", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_mpr.WNetGetConnectionW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_mpr.WNetGetConnectionW.restype = wintypes.DWORD

_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetDriveTypeW.restype = wintypes.UINT

_ERROR_SUCCESS = 0
_ERROR_MORE_DATA = 234
_DRIVE_REMOTE = 4
_INITIAL_BUFFER_CHARS = 260   # MAX_PATH — вистачає майже завжди, ERROR_MORE_DATA страхує решту


def is_network_path(path: str) -> bool:
    """Чи є шлях буквою диска, підключеного як мережевий ресурс (не UNC, не локальний)."""
    if len(path) < 2 or path[1] != ":":
        return False
    return _kernel32.GetDriveTypeW(path[:3]) == _DRIVE_REMOTE


def resolve_unc(path: str) -> str:
    """
    Перетворює 'Z:\\folder\\file' → '\\\\server\\share\\folder\\file'.

    Якщо буква диска не мережева або резолв не вдався — повертає path БЕЗ ЗМІН:
    найбезпечніший фолбек, гірше не стане, просто не покращиться.
    """
    if not is_network_path(path):
        return path

    drive = path[:2]   # "Z:"
    size = wintypes.DWORD(_INITIAL_BUFFER_CHARS)
    buf = ctypes.create_unicode_buffer(size.value)
    result = _mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size))

    if result == _ERROR_MORE_DATA:
        buf = ctypes.create_unicode_buffer(size.value)
        result = _mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size))

    if result != _ERROR_SUCCESS:
        log.debug(f"WNetGetConnectionW('{drive}') → код {result}, лишаю шлях як є.")
        return path

    return buf.value + path[2:]


def probe_write(path: str) -> bool:
    """
    Чесна перевірка запису — пробним файлом, НЕ os.access (той на Windows не бачить
    прав на мережевому ресурсі — той самий урок, що вже двічі записаний у backlog).

    Навмисно НЕ перевикористовує paths._is_writable(): net_path — опційний модуль, що
    їде окремо в дочірні проєкти без гарантії наявності конкретної внутрішньої функції
    core/paths.py, яка може змінитись.
    """
    probe = os.path.join(path, f".net_probe_{os.getpid()}")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8"):
            pass
    except OSError:
        return False
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return True
