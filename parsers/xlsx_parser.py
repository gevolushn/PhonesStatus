"""
xlsx_parser.py — читання таблиці телефонів з Excel файлу.
Шукає аркуш з "телефон" в назві, читає колонки B (номер) та H (статус).
"""
import re
from core.logger import log
from openpyxl import load_workbook


def read_xlsx(path: str) -> dict[str, str]:
    """
    Повертає словник {внутрішній_номер: 'ON' або 'OFF'}.
    Колонка B (індекс 1) — номер телефону, колонка H (індекс 7) — статус.
    """
    log.info(f"Читаю xlsx: {path}")
    wb = load_workbook(path, read_only=True, data_only=True)

    # Шукаємо аркуші з "телефон" в назві, ігноруємо старі копії та службові
    EXCLUDE = ("старий", "copy of", "експорт")
    candidates = [
        name for name in wb.sheetnames
        if "телефон" in name.lower()
        and not any(ex in name.lower() for ex in EXCLUDE)
    ]

    ws = None
    if candidates:
        # Беремо останній у списку (найновіший за порядком аркушів)
        chosen = candidates[-1]
        ws = wb[chosen]
        log.info(f"Знайдено аркуш: '{chosen}' (кандидати: {candidates})")
    else:
        ws = wb.active
        log.warning(f"Підходящий аркуш не знайдено, беру активний: '{ws.title}'")

    phones = {}
    for row in ws.iter_rows(values_only=True):
        if len(row) < 8:
            continue
        raw_num    = row[1]
        raw_status = row[7]

        if raw_num is None:
            continue
        try:
            num = str(int(float(str(raw_num))))
        except (ValueError, TypeError):
            continue

        if not re.match(r'^\d{3,5}$', num):
            continue

        status = str(raw_status).strip().upper() if raw_status else None
        if status not in ('ON', 'OFF'):
            continue

        phones[num] = status

    wb.close()
    log.info(f"Зчитано {len(phones)} номерів з таблиці.")
    return phones


def parse_text_block(text: str) -> set[str]:
    """
    Парсить текст з FreePBX (рядки вигляду 'PJSIP  1001  0' або просто '1001').
    Повертає множину числових номерів.
    """
    numbers = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r'\s+', line):
            if re.match(r'^\d{3,5}$', part):
                numbers.add(part)
                break
    log.info(f"Розпарсено {len(numbers)} номерів з текстового блоку.")
    return numbers
