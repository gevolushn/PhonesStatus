"""
crash_reporter.py — глобальний перехоплювач необроблених виключень. ЯДРО.

Встановлює sys.excepthook і threading.excepthook, ПЕРЕВИЗНАЧАЮЧИ базові хуки з
core/logger.py (там необроблений виняток лише пишеться в app.log). Тут — багатша
логіка: повний traceback у окремий logs/crash_YYYY-MM-DD_HH-MM-SS.log (не в app.log
— щоб легко знайти), короткий підсумок у app.log через log.critical, і Event Bus
подія CRASH_OCCURRED (kwargs: crash_log_path, summary).

Викликається в main() ПЕРШИМ (до instance_lock і GUI), щоб ловити навіть краш на
старті. Базові хуки логера лишаються запобіжником на вікно між імпортом і викликом
install_crash_handler.

    from core.crash_reporter import install_crash_handler
    install_crash_handler(app_name=build_info.APP_NAME)

Підписатись на сповіщення (опційно, у GUI):
    subscribe(Events.CRASH_OCCURRED, self._on_crash)   # kwargs: crash_log_path, summary
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime

from core.events import Events
from core.logger import log
from core.paths import logs_dir as _logs_dir


def install_crash_handler(app_name: str = "App") -> None:
    """Встановлює глобальні перехоплювачі необроблених виключень (GUI + фонові потоки)."""

    def _handle(exc_type, exc_value, exc_tb) -> None:
        # KeyboardInterrupt не є помилкою — не перехоплюємо
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _write_crash(exc_type, exc_value, exc_tb, app_name)

    def _handle_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is None or issubclass(args.exc_type, SystemExit):
            return
        _write_crash(
            args.exc_type, args.exc_value, args.exc_traceback, app_name,
            thread_name=args.thread.name if args.thread else "unknown",
        )

    sys.excepthook = _handle
    threading.excepthook = _handle_thread
    log.info("CrashReporter встановлено.")


def _write_crash(exc_type, exc_value, exc_tb, app_name: str, thread_name: str | None = None) -> None:
    """Пише crash-лог і емітує подію CRASH_OCCURRED."""
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    logs_dir = _logs_dir()
    os.makedirs(logs_dir, exist_ok=True)
    crash_path = os.path.join(logs_dir, f"crash_{stamp}.log")

    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    summary = f"{exc_type.__name__}: {exc_value}"
    where = f"Thread: {thread_name}" if thread_name else "Main thread"

    header = (
        f"{'=' * 60}\n"
        f"{app_name} — CRASH REPORT\n"
        f"Time:   {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Where:  {where}\n"
        f"{'=' * 60}\n\n"
    )

    try:
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(tb_text)
    except Exception as write_err:
        log.error(f"Не вдалося записати crash-лог: {write_err}")

    log.critical(f"НЕОБРОБЛЕНИЙ ВИНЯТОК [{where}]: {summary}")
    log.critical(f"Crash-лог: {crash_path}")

    # Notify GUI через Event Bus (якщо він ініціалізований)
    try:
        from core.events import emit
        emit(Events.CRASH_OCCURRED, crash_log_path=crash_path, summary=summary)
    except Exception:
        pass  # Event Bus може ще не бути ініціалізований при старті
