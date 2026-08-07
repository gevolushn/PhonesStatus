"""
logger.py — глобальний логер програми.
Лог-файл: logs/app_YYYY-MM-DD.log поруч із .exe або main.py.

Окрім явних викликів log.*, логер перехоплює ВСЕ, що інакше зникло б у .exe
(--noconsole), де sys.stdout/stderr ведуть «у нікуди»:
  • print() і будь-який вивід у stdout            → рівень INFO
  • вивід у stderr (помилки/warnings бібліотек)   → рівень WARNING
  • необроблені виключення (main + фонові потоки) → рівень CRITICAL з traceback

Так лог-файл містить повну картину сесії — для діагностики навіть дрібних помилок.
Опційний core/crash_reporter.py додатково пише кожен крах в окремий crash_*.log і
сповіщає GUI через Event Bus — він ПЕРЕВИЗНАЧАЄ базові excepthook'и звідси, але без
нього працює цей мінімум (необроблений виняток усе одно потрапить у app.log).

Імпорт у будь-якому модулі:
    from core.logger import log
    log.info("повідомлення")
    log.warning("попередження")
    log.error("помилка", exc_info=True)
"""
import logging
import os
import sys
import threading
from datetime import datetime

from core.paths import logs_dir as _logs_dir


class _StreamToLog:
    """Файлоподібний об'єкт: перенаправляє все, що пишуть у stdout/stderr, у логер.

    Без цього у .exe (--noconsole) print() і помилки сторонніх бібліотек зникають
    безслідно. Рядки накопичуються в буфері й віддаються логеру по '\\n'
    (logging додає власний перенос рядка).
    """

    def __init__(self, logger: logging.Logger, level: int, fallback) -> None:
        self._logger = logger
        self._level = level
        self._fallback = fallback            # оригінальний потік для аварійного запису
        self._buffer = ""
        self._lock = threading.Lock()
        self._local = threading.local()      # прапорець реентрантності (на потік)

    def write(self, message: str) -> None:
        # Реентрантний виклик: логер без хендлерів → lastResort пише в sys.stderr →
        # потрапляє сюди знову. Пишемо напряму в оригінальний потік, щоб уникнути
        # нескінченної рекурсії та дедлоку на self._lock.
        if getattr(self._local, "busy", False):
            if self._fallback is not None:
                self._fallback.write(message)
            return
        self._local.busy = True
        try:
            with self._lock:
                self._buffer += message
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if line.strip():
                        self._logger.log(self._level, line)
        finally:
            self._local.busy = False

    def flush(self) -> None:
        if getattr(self._local, "busy", False):
            return
        with self._lock:
            if self._buffer.strip():
                self._logger.log(self._level, self._buffer)
            self._buffer = ""

    def isatty(self) -> bool:
        # Деякі бібліотеки питають це перед кольоровим виводом.
        return False


def _redirect_std_streams(logger: logging.Logger) -> None:
    """Підміняє sys.stdout/stderr на проксі в логер. stdout→INFO, stderr→WARNING."""
    sys.stdout = _StreamToLog(logger, logging.INFO, sys.__stdout__)
    sys.stderr = _StreamToLog(logger, logging.WARNING, sys.__stderr__)


def _install_excepthook(logger: logging.Logger) -> None:
    """Базовий перехоплювач необроблених виключень (main-потік + фонові потоки).

    Гарантує, що жоден необроблений виняток не зникне мовчки. Опційний
    core/crash_reporter.py перевизначає ці хуки багатшою логікою (окремий
    crash_*.log + Event Bus); без нього лишається цей мінімум.
    """

    def _hook(exc_type, exc_value, exc_tb) -> None:
        # KeyboardInterrupt не є помилкою — стандартна поведінка.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("НЕОБРОБЛЕНИЙ ВИНЯТОК", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is None or issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "unknown"
        logger.critical(
            f"НЕОБРОБЛЕНИЙ ВИНЯТОК у потоці '{name}'",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def setup_logger() -> logging.Logger:
    """Налаштовує і повертає синглтон-логер 'AppLogger'. Повторний виклик — той самий логер."""
    logs_dir = _logs_dir()
    os.makedirs(logs_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(logs_dir, f"app_{today}.log")
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    logger = logging.getLogger("AppLogger")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    logger.addHandler(fh)

    # Консоль — тільки при розробці (не .exe). Пишемо в ОРИГІНАЛЬНИЙ stderr
    # (sys.__stderr__), щоб після підміни sys.stderr нижче не виникло рекурсії.
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler(stream=sys.__stderr__)
        sh.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        logger.addHandler(sh)

    # Перехоплюємо все решта: потоки виводу і необроблені виключення.
    # ВАЖЛИВО: робити ПІСЛЯ створення StreamHandler — інакше він захопить проксі.
    _redirect_std_streams(logger)
    _install_excepthook(logger)

    return logger


log = setup_logger()
