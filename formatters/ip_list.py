"""
ip_list.py — текст списку IP для поля в головному вікні.

Доменний модуль без GUI, як `formatters/result_formatter.py`: на вхід список
`integrations.ip_sync.Row`, на вихід готовий плаский текст. Вікно лише вставляє
результат, форматування в `insert()` не пишеться.

Кольорових сегментів тут свідомо НЕМАЄ, на відміну від звіту порівняння. У звіті
колір ніс сенс (підключився / відключився), а список IP — довідка: одна колонка
значень, у якій підсвічувати нічого. Одноманітність заради одноманітності коштувала б
другого представлення й тегів, які GUI мусив би зіставляти з палітрою.

Ширина — 44 символи проти 52 у звіті. Поля стоять поруч, і звіт про зміни статусів
важливіший за довідку про адреси, тому вужчий саме цей список. Ширина розрахована
під найдовший можливий рядок (номер + повний MAC + IPv4) без переносів.
"""
from __future__ import annotations

from integrations.ip_sync import Row
from integrations.mikrotik import DASH

_LINE_WIDTH: int = 44


def _display_mac(mac: str) -> str:
    """
    Нормалізований MAC (12 hex) → звичний вигляд `00:04:13:D8:CA:40`.

    Усередині програми MAC зберігається без роздільників — інакше його не
    зіставити з таблицею, де написання довільне. Але показувати таке людині,
    яка звіряє список із Winbox, незручно.
    """
    if len(mac) != 12:
        return mac
    return ":".join(mac[i:i + 2] for i in range(0, 12, 2))


def _sort_key(row: Row) -> tuple[int, int, str]:
    """
    Сортування за номером як ЧИСЛОМ (так само, як у звіті порівняння).

    Рядки без номера — у кінець: вони є в таблиці лише завдяки MAC, і в списку,
    впорядкованому за номерами, їм місця немає.
    """
    if row.number.isdigit():
        return 0, int(row.number), row.mac
    return 1, 0, row.mac


def format_ip_list(rows: list[Row], now: str = "") -> str:
    """
    Список «номер · MAC · IP» готовим текстом.

    `now` — мітка часу для заголовка; порожня прибирає її зовсім.
    """
    if not rows:
        return "Список порожній — натисніть «Спарсити»."

    found = sum(1 for row in rows if row.ip != DASH)
    title = f"  IP телефонів{f' [{now}]' if now else ''}"

    lines = [
        "═" * _LINE_WIDTH,
        title,
        "═" * _LINE_WIDTH,
        f"  У мережі: {found}   Немає: {len(rows) - found}   Усього: {len(rows)}",
        "─" * _LINE_WIDTH,
        "",
        f"  {'Номер':<6}{'MAC':<19}IP",
        f"  {'─' * 5} {'─' * 18} {'─' * 15}",
    ]
    lines += [
        f"  {(row.number or '·'):<6}{_display_mac(row.mac):<19}{row.ip}"
        for row in sorted(rows, key=_sort_key)
    ]
    lines += ["", "═" * _LINE_WIDTH]
    return "\n".join(lines) + "\n"
