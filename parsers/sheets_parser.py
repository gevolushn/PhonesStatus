"""
sheets_parser.py — авто-режим таблиці: читання з Google Sheets. ЗАГЛУШКА.

Модуль навмисно порожній: у 1.2.0 реалізовано лише авто-режим АТС (`pbx_ari.py`),
а джерело таблиці лишається ручним (`xlsx_parser.py`). Каркас стоїть тут, щоб
перемикач «Таблиця: Ручний / Авто» уже мав куди підключитись.

Контракт, який модуль зобов'язаний віддати (той самий, що й `xlsx_parser.read_xlsx`):
    dict[номер, 'ON'|'OFF']

Досліджений, але НЕ реалізований план:
  - публічна таблиця («будь-хто з посиланням» → Переглядач):
    `https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=<GID>`
    через `urllib` + stdlib `csv`, нуль нових залежностей. `export?format=csv`
    віддає сирий дамп зі збереженими позиціями колонок, тож ті самі літери
    `table_col_number` / `table_col_status` обслуговують і .xlsx, і Sheets;
  - приватна таблиця: OAuth 2.0 installed-app (loopback) із refresh-token у data/.
    Скоуп `spreadsheets.readonly` — «sensitive», екран «unverified app»,
    у режимі Testing refresh-token живе 7 днів.

Запис назад у таблицю не планується — рішення власника: доступ лише read-only.
"""
from __future__ import annotations


def read_sheet(url: str, sheet: str, col_number: str, col_status: str) -> dict[str, str]:
    """
    Читає таблицю телефонів із Google Sheets. НЕ РЕАЛІЗОВАНО.

    Сигнатура зафіксована навмисно — дзеркалить `xlsx_parser.read_xlsx`, щоб
    підключення звелося до заміни одного виклику у вікні.
    """
    raise NotImplementedError(
        "Авто-режим таблиці (Google Sheets) ще не реалізований — "
        "перемкніть «Таблиця» у ручний режим і виберіть .xlsx."
    )
