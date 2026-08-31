"""
table_rules.py — правила читання таблиці телефонів, СПІЛЬНІ для всіх її джерел.

Навіщо окремий модуль. Таблиця приходить із двох місць: локальний `.xlsx`
(`xlsx_parser`) і Google Sheets (`sheets_parser`). Обидва дають на вхід матрицю
значень, і обидва зобов'язані інтерпретувати її ОДНАКОВО. Якщо правила лежали б
у кожному модулі своєю копією, вони гарантовано розійшлися б на першій же правці —
класика: у .xlsx номер `1026.0` нормалізується, а в Sheets ні, і половина номерів
тихо зникає з порівняння.

Тут живуть чотири рішення, кожне з реальною причиною:
  - який токен вважається внутрішнім номером;
  - як нормалізується число з Excel;
  - які значення вважаються статусом;
  - як обирається аркуш, коли користувач не вказав його явно.
"""
from __future__ import annotations

import re

from openpyxl.utils import column_index_from_string

from core.logger import log

# Дефолтна розкладка — та сама, що була вшита в код до 1.2.0.
DEFAULT_COL_NUMBER: str = "F"   # «Внутрішній»
DEFAULT_COL_STATUS: str = "H"   # «Статус»

# Аркуш обирається за назвою: має містити «телефон» і не містити жодного з виключень.
_SHEET_KEYWORD: str = "телефон"
_SHEET_EXCLUDE: tuple[str, ...] = ("старий", "copy of", "експорт")

# Внутрішній номер — ЦІЛКОМ числовий токен, 3-5 цифр.
_RE_EXTENSION = re.compile(r"^\d{3,5}$")

# Приймаються лише ці два статуси (після .strip().upper()).
_VALID_STATUSES: frozenset[str] = frozenset({"ON", "OFF"})


def col_index(letter: str, fallback: str) -> int:
    """
    Літера колонки Excel → 0-based індекс. Хибне значення → дефолт із гучним логом.

    Літери, а не числа, свідомо: користувач бачить у таблиці саме `F` і `H`,
    і має вводити те, що бачить.
    """
    try:
        return column_index_from_string(str(letter).strip().upper()) - 1
    except Exception:
        log.warning(f"Некоректна літера колонки {letter!r} — беру дефолт {fallback}.")
        return column_index_from_string(fallback) - 1


def detect_sheet(sheet_names: list[str]) -> str:
    """
    Автовизначення аркуша за назвою. Повертає "" якщо кандидатів немає.

    Кандидати — назви з «телефон», без слів із `_SHEET_EXCLUDE`. Якщо кандидатів
    кілька, береться ОСТАННІЙ у порядку аркушів (він найновіший).

    ⚠️ На робочому .xlsx це НЕ спрацьовує: єдиний аркуш зветься
    «Copy of Телефони 27.08.2026», тобто відпадає за виключенням `copy of`, і рятує
    лише фолбек на активний аркуш. Саме тому в 1.2.0 з'явився явний вибір аркуша.
    """
    candidates = [
        name for name in sheet_names
        if _SHEET_KEYWORD in name.lower()
        and not any(bad in name.lower() for bad in _SHEET_EXCLUDE)
    ]
    return candidates[-1] if candidates else ""


def normalize_number(raw: object) -> str | None:
    """
    Значення комірки → внутрішній номер, або None якщо це не номер.

    `int(float(...))` — щоб `1026.0` з Excel став `1026` (Excel зберігає цілі як float).

    ⚠️ Комірка має бути ЧИСТИМ числом: `901 (Binotel)` не розпізнається. Це свідомо —
    номери зовнішньої АТС Binotel поза нашим порівнянням.
    """
    if raw is None:
        return None
    try:
        number = str(int(float(str(raw))))
    except (ValueError, TypeError):
        return None
    return number if _RE_EXTENSION.match(number) else None


def normalize_status(raw: object) -> str | None:
    """Значення комірки → 'ON'/'OFF', або None якщо статус не розпізнано."""
    if raw is None or raw == "":
        return None
    status = str(raw).strip().upper()
    return status if status in _VALID_STATUSES else None


def rows_to_phones(
    rows,
    idx_number: int,
    idx_status: int,
) -> dict[str, str]:
    """
    Матриця значень → `dict[номер, 'ON'|'OFF']`. ЄДИНА реалізація для всіх джерел.

    `rows` — будь-яка послідовність послідовностей (кортежі openpyxl або списки
    з Google Sheets API). Рядки, коротші за потрібну колонку, пропускаються: у
    Sheets API хвостові порожні комірки просто не приходять.
    """
    min_columns = max(idx_number, idx_status) + 1
    phones: dict[str, str] = {}
    for row in rows:
        if len(row) < min_columns:
            continue
        number = normalize_number(row[idx_number])
        if number is None:
            continue
        status = normalize_status(row[idx_status])
        if status is None:
            continue
        phones[number] = status
    return phones
