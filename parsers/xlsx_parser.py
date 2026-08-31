"""
xlsx_parser.py — ручний режим таблиці: читання телефонів з локального .xlsx.

Контракт (спільний із `parsers/sheets_parser.py`): `dict[номер, 'ON'|'OFF']`.

Правила інтерпретації рядка (що є номером, що є статусом, як обирається аркуш)
живуть НЕ тут, а в `parsers/table_rules.py` — спільні з Google Sheets, щоб два
джерела однієї й тієї самої таблиці не могли розійтись у поведінці.

Аркуш і колонки приходять параметрами з конфігу (з 1.2.0). Причина конкретна:
розкладка вже переїжджала (до 2026-08 номер лежав у колонці B, потім B стала
«Поверх», номер поїхав у F), і кожен такий переїзд означав правку коду й реліз.
"""
from __future__ import annotations

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from core.logger import log
from parsers.table_rules import (
    DEFAULT_COL_NUMBER,
    DEFAULT_COL_STATUS,
    col_index,
    detect_sheet,
    rows_to_phones,
)

__all__ = [
    "read_xlsx", "list_sheets", "preview_columns",
    "detect_sheet", "DEFAULT_COL_NUMBER", "DEFAULT_COL_STATUS",
]


def list_sheets(path: str) -> list[str]:
    """Назви всіх аркушів книги — для випадайки в налаштуваннях."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def preview_columns(path: str, sheet: str = "", max_columns: int = 26) -> list[tuple[str, str]]:
    """
    Пари (літера, підказка) для випадайки вибору колонки: [('F', 'Внутрішній'), ...].

    Підказка — перша непорожня комірка колонки згори (типово заголовок). Якщо
    колонка порожня — підказка порожня, але літера все одно пропонується.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
        hints: dict[int, str] = {}
        for row_index, row in enumerate(ws.iter_rows(values_only=True)):
            if row_index > 20:            # заголовок не буває нижче — далі лише дані
                break
            for column_index, value in enumerate(row[:max_columns]):
                if column_index not in hints and value not in (None, ""):
                    hints[column_index] = str(value).strip()
        return [
            (get_column_letter(i + 1), hints.get(i, ""))
            for i in range(max_columns)
        ]
    finally:
        wb.close()


def read_xlsx(
    path: str,
    sheet: str = "",
    col_number: str = DEFAULT_COL_NUMBER,
    col_status: str = DEFAULT_COL_STATUS,
) -> dict[str, str]:
    """
    Повертає `dict[внутрішній_номер, 'ON'|'OFF']`.

    `sheet` порожній → автовизначення (`table_rules.detect_sheet`), далі фолбек на
    активний аркуш.
    """
    log.info(f"Читаю xlsx: {path}")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet and sheet in wb.sheetnames:
            ws = wb[sheet]
            log.info(f"Аркуш обрано явно: '{sheet}'")
        else:
            if sheet:
                log.warning(f"Аркуш '{sheet}' не знайдено — переходжу до автовизначення.")
            detected = detect_sheet(wb.sheetnames)
            if detected:
                ws = wb[detected]
                log.info(f"Аркуш визначено автоматично: '{detected}'")
            else:
                ws = wb.active
                log.warning(f"Підходящий аркуш не знайдено, беру активний: '{ws.title}'")

        phones = rows_to_phones(
            ws.iter_rows(values_only=True),
            col_index(col_number, DEFAULT_COL_NUMBER),
            col_index(col_status, DEFAULT_COL_STATUS),
        )
    finally:
        wb.close()

    log.info(f"Зчитано {len(phones)} номерів з таблиці (колонки {col_number}/{col_status}).")
    return phones
