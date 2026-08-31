"""
cleanup.py — очищення логів при старті та виході.
"""
import glob
import logging
import os
import re
from datetime import datetime, timedelta

from core.logger import log
from core.paths import logs_dir as _logs_dir

# Скільки ДНІВ тримати логи при старті (не файлів — див. _parse_log_date).
# НЕ стираємо вчорашнє: рідкісна помилка минулої сесії має лишитись для діагностики.
_KEEP_DAYS: int = 30

_LOG_NAME_RE = re.compile(r"^app_(\d{4}-\d{2}-\d{2})\.log$")


def _parse_log_date(path: str) -> datetime | None:
    """Дата з імені файлу app_YYYY-MM-DD.log, або None якщо ім'я не за форматом."""
    m = _LOG_NAME_RE.match(os.path.basename(path))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d")
    except ValueError:
        return None


def clean_old_logs() -> None:
    """
    Видаляє логи СТАРШІ за _KEEP_DAYS днів (за датою в імені файлу, не за кількістю).

    Раніше зріз рахував ФАЙЛИ (`logs[:-30]`), а докстрінг і DECISIONS.md обіцяли ДНІ —
    для програми, яку запускають зрідка, 30 файлів розтягувались на місяці, а обіцяні
    «30 днів» ретенції не виконувались. Файли з іменем не за форматом (хтось поклав щось
    вручну) не чіпаємо — не наша справа їх видаляти.

    Раніше стиралось усе крім сьогоднішнього — це знищувало саме ті дані, заради
    яких лог існує (помилка вчора ввечері → стерта сьогодні до перегляду).
    """
    logs_dir = _logs_dir()
    if not os.path.isdir(logs_dir):
        return
    cutoff = datetime.now() - timedelta(days=_KEEP_DAYS)
    deleted = 0
    for path in glob.glob(os.path.join(logs_dir, "app_*.log")):
        file_date = _parse_log_date(path)
        if file_date is None or file_date >= cutoff:
            continue
        try:
            os.remove(path)
            deleted += 1
        except Exception as e:
            log.warning(f"Не вдалося видалити лог '{path}': {e}")
    if deleted:
        log.info(f"Видалено {deleted} старих лог-файлів (тримаємо останні {_KEEP_DAYS} днів).")


def delete_current_log() -> None:
    """
    Видаляє лог поточної сесії (режим 'без слідів', remember=False).
    Свідомо стирає саме поточний файл — на відміну від clean_old_logs.
    """
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
        # Best-effort: файл міг лишитись заблокованим (антивірус читає щойно закритий
        # лог) — не критично, наступний запуск почне новий файл незалежно від цього.
        pass
