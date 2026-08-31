"""
sheets_parser.py — авто-режим таблиці: читання телефонів із Google Sheets.

Контракт (спільний із `parsers/xlsx_parser.py`): `dict[номер, 'ON'|'OFF']`.
Правила інтерпретації рядка — у `parsers/table_rules.py`, ті самі, що для `.xlsx`.
Залежностей немає — лише `urllib` зі stdlib.

Чому Sheets API з API-ключем, а не анонімний `export?format=csv`
────────────────────────────────────────────────────────────────
Анонімне завантаження працює, доки Google не вирішить, що трафік підозрілий: у
відповідь може прийти HTML-сторінка «unusual traffic», 429 або капча — і жоден
вибір формату цього не змінює, бо запит іде без будь-якої ідентифікації. З
API-ключем запити рахуються по КВОТІ проєкту Google Cloud, а не по евристиках
проти зловживань. Це і є та надійність, якої анонімний шлях дати не може.

Перевірено емпірично (2026-08-31) на таблиці, розшареній як «будь-хто з посиланням»:
  - `spreadsheets.get` віддає список аркушів — HTTP 200;
  - `values.get` із `valueRenderOption=UNFORMATTED_VALUE` віддає числа ЧИСЛАМИ
    (`1216`, а не `"1216"`), тож правило «комірка має бути чистим числом»
    (`901 (Binotel)` відкидається) працює так само, як із локальним `.xlsx`.

Що потрібно від користувача (вводиться у вікні налаштувань):
  - посилання на таблицю — приймається у звичайному вигляді з адресного рядка;
  - API-ключ із Google Cloud Console; на диску зберігається зашифрованим
    (`core/dpapi.py`, поле в `config_manager.SECRET_FIELDS`).

Доступ лише на ЧИТАННЯ — запис назад у таблицю не планується (рішення власника).
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from core.logger import log
from parsers.table_rules import (
    DEFAULT_COL_NUMBER,
    DEFAULT_COL_STATUS,
    col_index,
    detect_sheet,
    rows_to_phones,
)

_API_BASE: str = "https://sheets.googleapis.com/v4/spreadsheets"
_TIMEOUT_SEC: int = 15

# ID у посиланні: .../spreadsheets/d/<ID>/edit?usp=sharing
_RE_SHEET_ID = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
# Голий ID, якщо користувач вставив саме його, а не URL
_RE_BARE_ID = re.compile(r"^[a-zA-Z0-9_-]{20,}$")


class SheetsError(Exception):
    """Помилка звернення до Google Sheets із готовим до показу текстом."""


def extract_id(url: str) -> str:
    """
    Витягує ID таблиці з посилання. Приймає і повний URL, і голий ID.

    Користувач копіює адресу з браузера як є — розбирати її має програма,
    а не людина.
    """
    value = (url or "").strip()
    if not value:
        raise SheetsError("Посилання на Google-таблицю не вказано.")
    match = _RE_SHEET_ID.search(value)
    if match:
        return match.group(1)
    if _RE_BARE_ID.match(value):
        return value
    raise SheetsError(
        "Не вдалося розпізнати посилання на Google-таблицю. "
        "Скопіюйте адресу з рядка браузера цілком."
    )


def _quote_sheet(name: str) -> str:
    """Ім'я аркуша для A1-нотації: у лапках, внутрішні лапки подвоюються."""
    return "'" + name.replace("'", "''") + "'"


def _explain(exc: Exception) -> str:
    """Перекладає виняток у текст, за яким видно, що робити далі."""
    if isinstance(exc, urllib.error.HTTPError):
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            detail = str(payload.get("error", {}).get("message", ""))[:200]
        except Exception:
            pass
        if exc.code == 400:
            # Google віддає 400 і на протухлий/невалідний ключ, і на криву назву
            # аркуша. Розрізняти обов'язково: інакше користувач шукає помилку в
            # аркуші, поки насправді треба перевипустити ключ (перевірено на живому
            # API — ключ протух між двома запитами й дав саме 400).
            low = detail.lower()
            if "api key" in low or "api_key" in low:
                return ("Ключ Google недійсний або протух — перевипустіть його в "
                        f"Google Cloud Console. {detail}")
            return f"HTTP 400 — некоректний запит (найімовірніше назва аркуша). {detail}"
        if exc.code == 403:
            return ("HTTP 403 — доступ заборонено. Перевірте: у Google Cloud Console "
                    "увімкнено Google Sheets API; ключ не обмежений іншим API; "
                    f"таблиця відкрита «будь-хто з посиланням». {detail}")
        if exc.code == 404:
            return "HTTP 404 — таблицю не знайдено. Перевірте посилання."
        if exc.code == 429:
            return "HTTP 429 — перевищено квоту запитів. Спробуйте за хвилину."
        return f"HTTP {exc.code} {exc.reason}. {detail}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return "Таймаут: Google не відповів. Перевірте з'єднання."
        return f"Помилка мережі: {reason}"
    if isinstance(exc, socket.timeout):
        return "Таймаут: Google не відповів."
    return f"{type(exc).__name__}: {exc}"


def _get(url: str) -> dict:
    """GET + розбір JSON. Будь-яка помилка стає SheetsError із людським текстом."""
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SEC) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception as e:
        message = _explain(e)
        log.error(f"Google Sheets: {message}")
        raise SheetsError(message) from e

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        # Типовий випадок — замість JSON прийшла HTML-сторінка входу чи капчі
        log.error(f"Google Sheets повернув не-JSON: {body[:200]}")
        raise SheetsError(
            "Google повернув не JSON, а сторінку — найімовірніше таблиця не відкрита "
            "за посиланням або ключ недійсний."
        ) from e
    if not isinstance(payload, dict):
        raise SheetsError("Несподівана відповідь Google Sheets.")
    return payload


def list_sheets(url: str, api_key: str) -> list[str]:
    """Назви аркушів таблиці — для випадайки в налаштуваннях і для автовизначення."""
    if not api_key:
        raise SheetsError("API-ключ Google не вказано — заповніть його в налаштуваннях.")
    sheet_id = extract_id(url)
    request_url = (
        f"{_API_BASE}/{sheet_id}"
        f"?key={urllib.parse.quote(api_key)}&fields=sheets.properties.title"
    )
    payload = _get(request_url)
    return [
        s.get("properties", {}).get("title", "")
        for s in payload.get("sheets", [])
        if s.get("properties", {}).get("title")
    ]


def read_sheet(
    url: str,
    api_key: str,
    sheet: str = "",
    col_number: str = DEFAULT_COL_NUMBER,
    col_status: str = DEFAULT_COL_STATUS,
) -> dict[str, str]:
    """
    Повертає `dict[внутрішній_номер, 'ON'|'OFF']` із Google-таблиці.

    `sheet` порожній → автовизначення тим самим правилом, що для `.xlsx`
    (`table_rules.detect_sheet`), далі фолбек на перший аркуш.

    Запитується діапазон від колонки A до дальшої з двох потрібних — щоб індекси
    збігалися з літерами й не тягнути зайвих колонок.
    """
    if not api_key:
        raise SheetsError("API-ключ Google не вказано — заповніть його в налаштуваннях.")
    sheet_id = extract_id(url)

    titles = list_sheets(url, api_key)
    if not titles:
        raise SheetsError("У таблиці немає жодного аркуша.")

    if sheet and sheet in titles:
        chosen = sheet
        log.info(f"Аркуш обрано явно: '{chosen}'")
    else:
        if sheet:
            log.warning(f"Аркуш '{sheet}' не знайдено — переходжу до автовизначення.")
        detected = detect_sheet(titles)
        chosen = detected or titles[0]
        log.info(
            f"Аркуш визначено автоматично: '{chosen}'" if detected
            else f"Підходящий аркуш не знайдено, беру перший: '{chosen}'"
        )

    idx_number = col_index(col_number, DEFAULT_COL_NUMBER)
    idx_status = col_index(col_status, DEFAULT_COL_STATUS)
    last_letter = _column_letter(max(idx_number, idx_status))
    cell_range = f"{_quote_sheet(chosen)}!A:{last_letter}"

    request_url = (
        f"{_API_BASE}/{sheet_id}/values/{urllib.parse.quote(cell_range)}"
        f"?key={urllib.parse.quote(api_key)}&valueRenderOption=UNFORMATTED_VALUE"
    )
    log.info(f"Google Sheets: запит діапазону {cell_range}")
    payload = _get(request_url)

    rows = payload.get("values", [])
    phones = rows_to_phones(rows, idx_number, idx_status)
    log.info(
        f"Google Sheets: рядків {len(rows)}, зчитано {len(phones)} номерів "
        f"(колонки {col_number}/{col_status})."
    )
    if not phones:
        raise SheetsError(
            f"На аркуші «{chosen}» не знайдено жодного номера зі статусом. "
            f"Перевірте колонки: зараз номер={col_number}, статус={col_status}."
        )
    return phones


def _column_letter(index_zero_based: int) -> str:
    """0-based індекс → літера колонки (0 → A). Локально, щоб не тягти openpyxl."""
    letters = ""
    index = index_zero_based + 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters
