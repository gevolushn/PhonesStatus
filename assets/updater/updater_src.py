"""
updater_src.py — вихідний код мінімального updater.exe.

Збирається ОКРЕМО від основної програми (один раз, або після зміни цієї логіки):
    cd assets/updater
    pyinstaller --onefile --noconsole --name updater updater_src.py
Результат (updater.exe) кладеться у assets/updater/ і вбудовується у portable .exe
через build_portable.spec: datas=[("assets/updater/updater.exe", "assets/updater")].

Послідовність роботи:
    1. Читає update_task.json (шлях — перший аргумент командного рядка)
    2. Переносить свій лог поруч із current_exe (до цього моменту — у %TEMP%)
    3. Чекає завершення процесу з pid (Windows API), потім — поки образ .exe реально
       не звільниться (перевірка відкриттям на запис, сильніший сигнал за сам pid)
    4. Копіює new_exe → current_exe (з backup і кількома спробами)
    5. Провал заміни НЕ веде до негайного виходу: backup відновлюється одразу
    6. Якщо restart=True — запускає те, що є на диску (нову версію АБО відновлену
       стару) незалежно від того, вдалась заміна чи ні
    7. Прибирає backup, видаляє себе і update_task.json
    8. Виходить з кодом 1, лише якщо заміна не вдалась (ПІСЛЯ спроби рестарту)

    Головний інваріант: апдейтер, який не зміг оновити, зобов'язаний повернути стару
    версію в робочий стан. Провал оновлення — нормальний сценарій (антивірус,
    блокування файлу, немає прав), а не аварія.

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

# Ранні рядки логу (до того, як прочитано task.json і відомо, де лежить програма) йдуть у
# %TEMP% — іншого місця ще не знаємо. `_relocate_log()` переносить ЛОГ ДАЛІ поруч із .exe,
# щойно current_exe стає відомий: провал оновлення інакше видно лише в файлі, про
# існування якого користувач і не здогадується (%TEMP% ніхто не переглядає).
_log_path = os.path.join(tempfile.gettempdir(), f"{_TEMP_PREFIX}updater_log.txt")

# 60, не 15: штатний вихід програми з фоновим доменом (asyncio, довгі з'єднання) коштує
# до ~30с самих лише таймаутів. Апдейтер, що здається за 15с, намагається перезаписати ще
# живий .exe — Windows цього не дозволяє, і спрацьовує саме той сценарій, якого весь цей
# модуль намагається уникнути.
_WAIT_TIMEOUT_SEC = 60         # максимум чекаємо завершення процесу / звільнення .exe
_POLL_INTERVAL_SEC = 0.5       # крок опитування процесу / файлу
_REPLACE_RETRIES = 6           # спроб копіювання (антивірус/ОС можуть тримати файл мить)
_REPLACE_DELAY_SEC = 0.5       # пауза між спробами


def _log(msg: str) -> None:
    """Дописує рядок у лог-файл updater'а (тихо ігнорує помилки запису)."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # лог недоступний — не критично, продовжуємо роботу


def _relocate_log(app_dir: str) -> None:
    """
    Переносить ПОДАЛЬШИЙ лог поруч із .exe програми, а не в %TEMP%.

    Викликається, щойно з task.json відомий `current_exe`. Ранні рядки (до цього моменту)
    лишаються в %TEMP% — там їх лічені штуки, і без них не обійтись, бо до читання task.json
    ми ще не знаємо, куди переносити.
    """
    global _log_path
    _log_path = os.path.join(app_dir, f"{_TEMP_PREFIX}updater_log.txt")
    _log(f"Лог перенесено поруч із програмою: {_log_path}")


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


def _wait_until_openable_for_write(path: str, timeout: float) -> bool:
    """
    Чекає, поки файл реально відкриється на запис — сильніший сигнал за зникнення PID.

    Процес зникає зі списку процесів РАНІШЕ, ніж Windows остаточно звільняє образ .exe.
    Спроба замінити файл одразу після завершення PID нерідко натикається на «файл ще
    використовується» — цей прийом чекає прямої відповіді ОС, а не здогадується за станом
    процесу. Той самий клас прийому, що вже описаний для `paths._is_writable`: питати ОС
    дією, а не станом. Побічно знімає й гонку за instance-mutex: до моменту, коли образ
    справді звільнено, ОС уже відпустила і пов'язані з процесом handle-и.
    """
    elapsed = 0.0
    while elapsed < timeout:
        try:
            with open(path, "r+b"):
                return True
        except OSError:
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

    _relocate_log(os.path.dirname(current_exe))

    if pid > 0:
        _log(f"Очікую завершення PID {pid}...")
        if _wait_for_exit(pid):
            _log("Процес завершився. Продовжую.")
        else:
            _log(f"Timeout {_WAIT_TIMEOUT_SEC}с — спробую замінити файл усе одно.")

    if os.path.isfile(current_exe):
        if _wait_until_openable_for_write(current_exe, _WAIT_TIMEOUT_SEC):
            _log("Образ .exe звільнено — файл відкривається на запис.")
        else:
            _log(f"Timeout {_WAIT_TIMEOUT_SEC}с — .exe досі заблокований, "
                 f"спробую замінити все одно.")

    # ── Заміна файлу ────────────────────────────────────────────────────────
    # replace_ok=False НЕ означає негайний вихід (див. нижче): якщо заміна не вдалась,
    # відновлюємо backup і намагаємось ЗАПУСТИТИ те, що лишилось на диску — стару робочу
    # версію. Раніше `sys.exit(1)` стояв рівно тут, і гілка рестарту нижче була
    # НЕДОСЯЖНА саме тоді, коли потрібна найбільше: користувач бачив, що програма зникла
    # з трея, а назад нічого не запустилось, без жодного повідомлення.
    replace_ok = False
    backup = current_exe + ".bak"
    have_backup = False
    try:
        if os.path.isfile(current_exe):
            shutil.copy2(current_exe, backup)
            have_backup = True
            _log(f"Backup: {backup}")
        _replace_with_retries(new_exe, current_exe)
        _log(f"Файл замінено: {new_exe} → {current_exe}")
        replace_ok = True
    except Exception as e:
        _log(f"ПОМИЛКА заміни файлу: {e}")
        if have_backup:
            try:
                shutil.copy2(backup, current_exe)
                _log("Відновлено попередню версію з backup.")
            except Exception as e2:
                _log(f"ПОМИЛКА відновлення backup: {e2}")

    for path in (new_exe, task_path):
        try:
            os.remove(path)
            _log(f"Видалено: {path}")
        except Exception as e:
            _log(f"Не вдалось видалити '{path}' (не критично): {e}")

    # ── Рестарт — ЗАВЖДИ, незалежно від replace_ok ──────────────────────────
    # На диску в будь-якому разі лежить якась робоча версія: нова (успіх) або відновлена
    # стара (відкат). Провал оновлення — нормальний сценарій (антивірус, блокування
    # файлу, немає прав), а не аварія: апдейтер, який не зміг оновити, зобов'язаний
    # повернути стару версію в робочий стан і запустити її.
    if restart and os.path.isfile(current_exe):
        try:
            subprocess.Popen(
                [current_exe],
                cwd=os.path.dirname(current_exe),  # cwd = папка програми, не %TEMP%
                creationflags=0x00000008,          # DETACHED_PROCESS
            )
            _log(f"Запущено {'нову версію' if replace_ok else 'відновлену попередню версію'}: "
                 f"{current_exe}")
        except Exception as e:
            _log(f"ПОМИЛКА запуску: {e}")
    else:
        _log("restart=False або файл відсутній — не запускаємо.")

    # Бекап прибираємо ОСТАННІМ, а не одразу після копіювання (D-28): якщо старт вище
    # не вдався, є з чого відновитись наступною спробою — на диску, а не лише в лозі.
    if have_backup and os.path.isfile(backup):
        try:
            os.remove(backup)
        except Exception as e:
            _log(f"Не вдалось видалити backup '{backup}' (не критично): {e}")

    _log("updater.exe завершує роботу.")
    _self_delete()

    if not replace_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
