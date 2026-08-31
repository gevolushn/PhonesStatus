"""
pbx_manual.py — ручний режим АТС: розбір тексту, вставленого з FreePBX.

Раніше жив у `xlsx_parser.py` (парсер FreePBX усередині модуля Excel — історична
випадковість міграції). Виділено окремо в 1.2.0, коли з'явився другий постачальник
того самого контракту — `parsers/pbx_ari.py`.

Контракт (спільний для обох режимів АТС): `dict[номер, 'ON'|'OFF']`.
"""
from __future__ import annotations

import re

from core.logger import log

# Внутрішній номер — ЦІЛКОМ числовий токен із 3-5 цифр.
_RE_EXTENSION = re.compile(r"^\d{3,5}$")


def parse_text_block(text: str) -> set[str]:
    """
    Парсить текст із FreePBX (рядки вигляду 'PJSIP  1001  0' або просто '1001').
    Повертає множину номерів.

    Рядок ріжеться по пробілах і береться ПЕРШИЙ токен, який ЦІЛКОМ складається
    з 3-5 цифр; решта рядка ігнорується.

    ⚠️ Перевірений на практиці наслідок: номер, «вклеєний» у більший токен, НЕ
    розпізнається — `SIP/1005-00001` пропускається, бо токен не є чистим числом.
    Так само відкидаються `12` (закоротко) і `123456` (задовго). Це свідома
    поведінка, а не баг: підтримка формату `SIP/xxxx-...` — окреме рішення.
    """
    numbers: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r"\s+", line):
            if _RE_EXTENSION.match(part):
                numbers.add(part)
                break
    log.info(f"Розпарсено {len(numbers)} номерів з текстового блоку.")
    return numbers


def read_manual(online_text: str, offline_text: str) -> dict[str, str]:
    """
    Зводить два вставлені блоки в спільний контракт `dict[номер, 'ON'|'OFF']`.

    ⚠️ При дублі (номер вклеїли в ОБИДВА поля) перемагає OFF — спершу розкладаємо
    всі online, потім offline затирає. Правило переїхало сюди з `comparator.py`
    у 1.2.0: це артефакт саме ручного вводу, ARI дублів не дає взагалі.
    """
    pbx: dict[str, str] = {}
    for num in parse_text_block(online_text):
        pbx[num] = "ON"
    for num in parse_text_block(offline_text):
        pbx[num] = "OFF"
    return pbx
