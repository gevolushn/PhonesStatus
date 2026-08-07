"""
cleanup.py — очищення логів при старті та виході.
"""
import glob
import logging
import os

from core.logger import log
from core.paths import logs_dir as _logs_dir

# Скільки останніх лог-файлів тримати при старті.
# НЕ стираємо вчорашнє: рідкісна помилка минулої сесії має лишитись для діагностики.
_KEEP_DAYS: int = 30


def clean_old_logs() -> None:
    """
    Видаляє старі логи, лишаючи _KEEP_DAYS найновіших файлів app_*.log.

    Раніше стиралось усе крім сьогоднішнього — це знищувало саме ті дані, заради
    яких лог існує (помилка вчора ввечері → стерта сьогодні до перегляду).
    """
    logs_dir = _logs_dir()
    if not os.path.isdir(logs_dir):
        return
    logs = sorted(glob.glob(os.path.join(logs_dir, "app_*.log")))
    deleted = 0
    for path in logs[:-_KEEP_DAYS] if _KEEP_DAYS > 0 else logs:
        try:
            os.remove(path)
            deleted += 1
        except Exception as e:
            log.warning(f"Не вдалося видалити лог '{path}': {e}")
    if deleted:
        log.info(f"Видалено {deleted} старих лог-файлів (тримаємо останні {_KEEP_DAYS}).")


def delete_current_log() -> None:
    """
    Видаляє лог поточної сесії (режим 'без слідів', remember=False).
    Свідомо стирає саме поточний файл — на відміну від clean_old_logs.
    """
    from datetime import datetime

    logs_dir = _logs_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = os.path.join(logs_dir, f"app_{today}.log")
    logger = logging.getLogger("AppLogger")
    for handler in logger.handlers[:]:
        try:
            handler.close()
            logger.removeHandler(handler)
        except Exception:
            pass
    try:
        if os.path.isfile(log_path):
            os.remove(log_path)
        if os.path.isdir(logs_dir) and not os.listdir(logs_dir):
            os.rmdir(logs_dir)
    except Exception:
        pass
