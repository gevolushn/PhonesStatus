"""
updater_src.py — вихідний код мінімального updater.exe.

Збирається ОКРЕМО від основної програми (один раз, або після зміни цієї логіки):
    cd assets/updater
    pyinstaller --onefile --noconsole --name updater updater_src.py
Результат (updater.exe) кладеться у assets/updater/ і вбудовується у portable .exe
через build_portable.spec: datas=[("assets/updater/updater.exe", "assets/updater")].

Послідовність роботи:
    1. Читає update_task.json (шлях — перший аргумент командного рядка)
    2. Чекає завершення процесу з pid (Windows API)
    3. Копіює new_exe → current_exe (з backup і кількома спробами)
    4. Якщо restart=True — запускає нову версію
    5. Видаляє себе і update_task.json

Вимоги:
    - ТІЛЬКИ стандартна бібліотека (без pip-залежностей → менший .exe, менше хибних
      спрацювань антивірусу). Тому НЕ може імпортувати core.build_info.
    - Префікс файлів у %TEMP% узгоджується ВРУЧНУ з core/build_info.py TEMP_PREFIX.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ⚠️ Тримати ідентичним до core.build_info.TEMP_PREFIX (цей файл не може його імпортувати).
_TEMP_PREFIX = "phonesstatus_"
_LOG_PATH = os.path.join(tempfile.gettempdir(), f"{_TEMP_PREFIX}updater_log.txt")

_WAIT_TIMEOUT_SEC = 15        # максимум чекаємо завершення основної програми
_POLL_INTERVAL_SEC = 0.5      # крок опитування процесу
_REPLACE_RETRIES = 6          # спроб копіювання (антивірус/ОС можуть тримати файл мить)
_REPLACE_DELAY_SEC = 0.5      # пауза між спробами


def _log(msg: str) -> None:
    """Дописує рядок у лог-файл updater'а (тихо ігнорує помилки запису)."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # лог недоступний — не критично, продовжуємо роботу


def _is_process_running(pid: int) -> bool:
    """
    Чи живий процес із заданим PID (через Windows API).
    WaitForSingleObject(handle, 0) повертає 0x102 (WAIT_TIMEOUT) поки процес ще живий.
    """
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return result == 0x102  # WAIT_TIMEOUT → ще живий


def _wait_for_exit(pid: int) -> bool:
    """Чекає завершення PID до таймауту. True — завершився, False — таймаут."""
    elapsed = 0.0
    while elapsed < _WAIT_TIMEOUT_SEC:
        if not _is_process_running(pid):
            return True
        time.sleep(_POLL_INTERVAL_SEC)
        elapsed += _POLL_INTERVAL_SEC
    return False


def _replace_with_retries(new_exe: str, current_exe: str) -> None:
    """
    Копіює new_exe → current_exe з кількома спробами.

    Чому copy, а не os.replace: new_exe у %TEMP%, current_exe у папці програми — часто
    РІЗНІ томи, тож атомарний rename неможливий (cross-volume). Retry потрібен, бо ОС/
    антивірус можуть коротко тримати щойно завантажений файл або старий .exe після виходу.
    """
    last_err: Exception | None = None
    for attempt in range(1, _REPLACE_RETRIES + 1):
        try:
            shutil.copy2(new_exe, current_exe)
            return
        except Exception as e:
            last_err = e
            _log(f"Спроба {attempt}/{_REPLACE_RETRIES} заміни не вдалась: {e}")
            time.sleep(_REPLACE_DELAY_SEC)
    raise RuntimeError(f"Не вдалося замінити файл після {_REPLACE_RETRIES} спроб: {last_err}")


def _self_delete() -> None:
    """
    Самовидалення updater.exe після роботи (стандартний Windows-трюк ping+del).
    Лише у frozen-режимі (.exe): у dev ми б видалили сам updater_src.py — тому пропускаємо.
    """
    if not getattr(sys, "frozen", False):
        _log("dev-режим — самовидалення пропущено.")
        return
    exe = sys.executable
    cmd = f'cmd /c ping 127.0.0.1 -n 3 > nul && del /f /q "{exe}"'
    subprocess.Popen(cmd, shell=True, creationflags=0x08000000)  # CREATE_NO_WINDOW


def main() -> None:
    """Точка входу updater'а: задача → чекання → заміна → рестарт → самовидалення."""
    _log("=" * 50)
    _log("updater.exe запущено")

    if len(sys.argv) < 2:
        _log("ПОМИЛКА: не передано шлях до update_task.json")
        sys.exit(1)
    task_path = sys.argv[1]
    if not os.path.isfile(task_path):
        _log(f"ПОМИЛКА: файл не знайдено: {task_path}")
        sys.exit(1)

    try:
        with open(task_path, "r", encoding="utf-8") as f:
            task: dict = json.load(f)
    except Exception as e:
        _log(f"ПОМИЛКА читання task: {e}")
        sys.exit(1)

    pid = int(task.get("pid", 0))
    current_exe = task.get("current_exe", "")
    new_exe = task.get("new_exe", "")
    restart = bool(task.get("restart", True))
    _log(f"pid={pid}, current={current_exe}")
    _log(f"new_exe={new_exe}, restart={restart}")
    if not current_exe or not new_exe:
        _log("ПОМИЛКА: current_exe або new_exe порожній")
        sys.exit(1)

    if pid > 0:
        _log(f"Очікую завершення PID {pid}...")
        if _wait_for_exit(pid):
            _log("Процес завершився. Продовжую.")
        else:
            _log(f"Timeout {_WAIT_TIMEOUT_SEC}с — спробую замінити файл усе одно.")
    time.sleep(0.5)  # Windows інколи тримає файл ще мить після завершення процесу

    backup = current_exe + ".bak"
    try:
        if os.path.isfile(current_exe):
            shutil.copy2(current_exe, backup)
            _log(f"Backup: {backup}")
        _replace_with_retries(new_exe, current_exe)
        _log(f"Файл замінено: {new_exe} → {current_exe}")
        if os.path.isfile(backup):
            os.remove(backup)
    except Exception as e:
        _log(f"ПОМИЛКА заміни файлу: {e}")
        if os.path.isfile(backup):   # відкат на стару версію
            try:
                shutil.copy2(backup, current_exe)
                _log("Відновлено backup.")
            except Exception as e2:
                _log(f"ПОМИЛКА відновлення backup: {e2}")
        sys.exit(1)

    for path in (new_exe, task_path):
        try:
            os.remove(path)
            _log(f"Видалено: {path}")
        except Exception as e:
            _log(f"Не вдалось видалити '{path}' (не критично): {e}")

    if restart and os.path.isfile(current_exe):
        try:
            subprocess.Popen(
                [current_exe],
                cwd=os.path.dirname(current_exe),  # cwd = папка програми, не %TEMP%
                creationflags=0x00000008,          # DETACHED_PROCESS
            )
            _log(f"Запущено нову версію: {current_exe}")
        except Exception as e:
            _log(f"ПОМИЛКА запуску нової версії: {e}")
    else:
        _log("restart=False або файл відсутній — не запускаємо.")

    _log("updater.exe завершує роботу.")
    _self_delete()


if __name__ == "__main__":
    main()
