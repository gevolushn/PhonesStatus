"""
ip_sync.py — оркестрація двох сценаріїв, які викликає GUI.

  resolve_and_list(cfg) → list[Row]     «Спарсити»: читає MAC із таблиці, питає
                                        роутер, повертає список. У ТАБЛИЦЮ НЕ ПИШЕ.
  write_ips(cfg, rows)  → WriteResult   «Додати в таблицю»: пише вже спарсене.

Розділення на два кроки — свідоме: запис у спільну зовнішню таблицю має відбуватись
лише явним кліком, щоб оператор знав, коли таблиця змінюється.

⚠️ Головне правило модуля: `write_ips` ПЕРЕЧИТУЄ MAC-колонку безпосередньо перед
записом і зіставляє за MAC. Номери рядків, відомі на момент парсингу, не
використовуються — тому їх немає навіть у `Row`. Між «Спарсити» і «Додати в таблицю»
може минути скільки завгодно часу, і хтось інший цілком може вставити чи видалити
рядок: за кешованими позиціями IP тихо поїхали б у сусідні рядки, без жодної
помилки. Один зайвий read-запит прибирає цілий клас багів.

Модуль говорить із Google-таблицею завжди, незалежно від режиму звірки: MAC живуть
там навіть тоді, коли статуси вводяться руками.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from openpyxl.utils import column_index_from_string

from core.logger import log
from integrations.google_sheets import GoogleSheetsError, SheetsClient
from integrations.mikrotik import DASH, normalize_mac, resolve_ips
from parsers.sheets_parser import _column_letter
from parsers.table_rules import DEFAULT_COL_NUMBER, col_index, normalize_number

# Літера колонки: одна-три латинські літери й нічого більше.
_RE_COLUMN = re.compile(r"^[A-Za-z]{1,3}$")


@dataclass(frozen=True)
class Row:
    """
    Один телефон: що знайшли й що запишемо.

    ⚠️ Номера рядка тут НЕМАЄ навмисно — див. докстрінг модуля.
    """
    number: str     # внутрішній номер із таблиці; "" якщо в рядку його немає
    mac: str        # нормалізований, 12 hex
    ip: str         # IP або прочерк


@dataclass
class WriteResult:
    """Підсумок запису для показу користувачеві."""
    written: int = 0                                  # комірок оновлено (за відповіддю Google)
    skipped: int = 0                                  # рядків із MAC, для яких IP не парсили
    errors: list[str] = field(default_factory=list)   # попередження, що не спинили запис


# ─── Налаштування ─────────────────────────────────────────────────────────────

def _strict_column(letter: str, title: str) -> int:
    """
    Літера колонки → 0-based індекс, БЕЗ тихого фолбеку на дефолт.

    ⚠️ Саме тут `table_rules.col_index` не годиться: він при кривій літері мовчки
    бере дефолт і пише попередження в лог. Для читання це рятівна поведінка, для
    ЗАПИСУ — спосіб залити IP у чужу колонку робочої таблиці. Краще відмовитись.
    """
    value = str(letter or "").strip()
    if not _RE_COLUMN.match(value):
        raise GoogleSheetsError(
            f"Колонка «{title}» задана некоректно ({value or 'порожньо'}). "
            f"Вкажіть літеру колонки в налаштуваннях, наприклад J."
        )
    return column_index_from_string(value.upper()) - 1


def _client(cfg: dict) -> SheetsClient:
    """Клієнт Sheets із збережених облікових даних."""
    return SheetsClient(
        str(cfg.get("google_client_id", "")),
        str(cfg.get("google_client_secret", "")),
        str(cfg.get("google_oauth_refresh_token", "")),
    )


def _sheet_url(cfg: dict) -> str:
    """Посилання на таблицю — те саме, що в авто-режимі звірки."""
    url = str(cfg.get("sheet_url", "")).strip()
    if not url:
        raise GoogleSheetsError(
            "Не вказано посилання на Google-таблицю — заповніть його в налаштуваннях. "
            "MAC-адреси читаються звідти навіть у ручному режимі звірки."
        )
    return url


def _columns(cfg: dict, need_ip: bool) -> tuple[int, int, int]:
    """
    Індекси колонок «номер», «MAC» і (за потреби) «IP» з перевіркою на колізію.

    ⚠️ Колонка IP не має збігатися з жодною іншою: вказати там `F` означало б
    затерти внутрішні номери в робочій таблиці. Це найдорожча можлива помилка
    в усій фічі, і єдине місце, де її ще можна дешево спіймати, — тут.
    """
    idx_number = col_index(cfg.get("table_col_number") or DEFAULT_COL_NUMBER,
                           DEFAULT_COL_NUMBER)
    idx_mac = _strict_column(cfg.get("table_col_mac", ""), "MAC")
    if not need_ip:
        return idx_number, idx_mac, -1

    idx_ip = _strict_column(cfg.get("table_col_ip", ""), "IP")
    busy = {
        idx_number: "номера",
        idx_mac: "MAC",
        col_index(cfg.get("table_col_status") or "H", "H"): "статусу",
    }
    if idx_ip in busy:
        raise GoogleSheetsError(
            f"Колонка IP ({_column_letter(idx_ip)}) збігається з колонкою "
            f"{busy[idx_ip]} — запис затер би наявні дані. Виберіть вільну колонку."
        )
    return idx_number, idx_mac, idx_ip


def _cell(row: list, index: int) -> object:
    """
    Значення комірки або "" — рядок може бути коротшим за потрібну колонку.

    Sheets API не надсилає хвостові порожні комірки, тому це не рідкість, а норма.
    """
    return row[index] if 0 <= index < len(row) else ""


# ─── Сценарій 1: спарсити ─────────────────────────────────────────────────────

def resolve_and_list(cfg: dict) -> list[Row]:
    """
    Читає номер+MAC із таблиці, питає роутер, повертає список рядків.

    У таблицю НЕ пише — це окрема дія (`write_ips`).

    Кидає `GoogleSheetsError`, `GoogleAuthError` або `MikrotikError` — усі з
    текстом, придатним для показу користувачеві.
    """
    url = _sheet_url(cfg)
    idx_number, idx_mac, _ = _columns(cfg, need_ip=False)
    col_number = str(cfg.get("table_col_number") or DEFAULT_COL_NUMBER)
    col_mac = str(cfg.get("table_col_mac", "")).strip()

    _, rows = _client(cfg).read_columns(url, str(cfg.get("table_sheet", "")),
                                        [col_number, col_mac])

    pairs: list[tuple[str, str]] = []
    for row in rows:
        mac = normalize_mac(str(_cell(row, idx_mac)))
        if not mac:
            continue        # порожній або сміттєвий MAC — рядок просто не наш
        pairs.append((normalize_number(_cell(row, idx_number)) or "", mac))

    log.info(f"IP-sync: у таблиці {len(rows)} рядків, з валідним MAC — {len(pairs)}.")
    if not pairs:
        raise GoogleSheetsError(
            f"У колонці {col_mac} не знайдено жодної MAC-адреси. "
            f"Перевірте, чи правильно вказана колонка."
        )

    ips = resolve_ips(
        str(cfg.get("mikrotik_url", "")),
        str(cfg.get("mikrotik_user", "")),
        str(cfg.get("mikrotik_password", "")),
        [mac for _, mac in pairs],
    )
    return [Row(number=number, mac=mac, ip=ips.get(mac, DASH)) for number, mac in pairs]


# ─── Сценарій 2: записати ─────────────────────────────────────────────────────

def write_ips(cfg: dict, rows: list[Row]) -> WriteResult:
    """
    Записує спарсені IP у колонку таблиці.

    ⚠️ Перед записом MAC-колонка ПЕРЕЧИТУЄТЬСЯ, і зіставлення йде за MAC, а не за
    позицією в списку `rows` — див. докстрінг модуля.

    Дубль MAC у таблиці → IP пишеться в усі його рядки (природний наслідок обходу
    рядків, а не окреме правило). Рядки з порожнім MAC пропускаються.
    """
    result = WriteResult()
    if not rows:
        result.errors.append("Немає спарсеного списку — спершу натисніть «Спарсити».")
        return result

    url = _sheet_url(cfg)
    _, idx_mac, idx_ip = _columns(cfg, need_ip=True)
    col_mac = str(cfg.get("table_col_mac", "")).strip()
    letter_ip = _column_letter(idx_ip)

    ip_by_mac = {row.mac: row.ip for row in rows}

    # Один клієнт на читання і запис: він тримає access-токен, і другий екземпляр
    # означав би зайвий запит на оновлення токена рівно нізащо.
    client = _client(cfg)

    # Аркуш беремо ТОЙ САМИЙ, що повернуло читання: визначати його вдруге —
    # означало б припустити, що між двома викликами він не змінився.
    sheet, table_rows = client.read_columns(url, str(cfg.get("table_sheet", "")), [col_mac])

    updates: dict[str, str] = {}
    for position, row in enumerate(table_rows, start=1):     # A1-нотація 1-based
        mac = normalize_mac(str(_cell(row, idx_mac)))
        if not mac:
            continue
        ip = ip_by_mac.get(mac)
        if ip is None:
            # MAC з'явився в таблиці вже після парсингу — писати нема чого
            result.skipped += 1
            continue
        updates[f"{letter_ip}{position}"] = ip

    if result.skipped:
        result.errors.append(
            f"{result.skipped} рядків з'явилось у таблиці після парсингу — "
            f"для них IP не записано. Натисніть «Спарсити» ще раз."
        )

    if not updates:
        result.errors.append("Жоден MAC зі списку не знайдено в таблиці.")
        return result

    result.written = client.write_cells(url, sheet, updates)
    if result.written != len(updates):
        result.errors.append(
            f"Google підтвердив {result.written} комірок із {len(updates)} надісланих."
        )
    log.info(f"IP-sync: записано {result.written}, пропущено {result.skipped}.")
    return result
