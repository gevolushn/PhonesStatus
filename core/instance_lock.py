"""
instance_lock.py — не дозволяє запустити другу копію програми (Windows).

Метод — Windows Named Mutex через ctypes: нуль залежностей, ОС сама прибирає mutex
при будь-якому завершенні (stale lock неможливий), атомарна перевірка+створення.
Так роблять Chrome, Steam, Visual Studio.
"""
import ctypes
import sys

from core.logger import log
import core.build_info as build_info


def check_single_instance():
    """
    Створює Windows mutex. Якщо mutex уже існує — показує повідомлення і виходить.

    Повертає handle — обов'язково зберігати у змінній (наприклад, у main()), щоб GC
    не зібрав його й mutex жив до завершення процесу.
    """
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, build_info.APP_MUTEX)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log.warning("Друга копія програми вже запущена.")
        ctypes.windll.user32.MessageBoxW(
            0,
            "Програма вже запущена.",
            build_info.APP_NAME,
            0x30,  # MB_ICONWARNING
        )
        sys.exit(0)
    return mutex
