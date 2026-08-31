"""
comparator.py — логіка порівняння статусів телефонів. ОДИН модуль на всі режими.

Ключовий інваріант: обидва джерела дають ОДНАКОВУ структуру — `dict[номер, 'ON'|'OFF']`.
Звідки вони прийшли (ручна вставка чи ARI, локальний .xlsx чи Google Sheets) —
comparator не знає і знати не повинен. Тому для чотирьох комбінацій режимів тут
рівно одна гілка коду.

Історія: до 1.2.0 сигнатура була `compare(xlsx_phones, online: set, offline: set)` —
асиметрична, бо ручна вставка природно дає дві множини. Правило «при дублі в обох
блоках перемагає OFF» переїхало звідси у `parsers/pbx_manual.py`: це артефакт саме
ручного вводу (номер вклеїли в обидва поля), а ARI дублів не дає взагалі.
"""
from __future__ import annotations

from typing import NamedTuple

from core.logger import log


class Comparison(NamedTuple):
    """
    Результат порівняння двох джерел.

    changes    — статус відрізняється: [{'num': '1026', 'old': 'OFF', 'new': 'ON'}]
    only_table — номер є в таблиці, але АТС його не знає (видалений extension?)
    only_pbx   — номер є в АТС, але його немає в таблиці (завели й не внесли?)
    """
    changes: list[dict]
    only_table: list[str]
    only_pbx: list[str]
    table_count: int
    pbx_count: int
    common_count: int


def _by_number(num: str) -> tuple[int, int, str]:
    """Сортування номерів як чисел; нечислові (якщо колись з'являться) — у кінець, за абеткою."""
    return (0, int(num), "") if num.isdigit() else (1, 0, num)


def compare(table: dict[str, str], pbx: dict[str, str]) -> Comparison:
    """
    Порівнює статуси з таблиці та з АТС.

    Змінами вважаються лише номери, присутні В ОБОХ джерелах із різним статусом —
    це правило не змінювалось із 1.0.0. Номери поза перетином більше не зникають
    мовчки: вони їдуть окремими списками, а показувати їх чи ні — вирішує формат
    звіту (у ручному режимі список «немає в АТС» — це просто все, що не вставили).
    """
    table_keys, pbx_keys = set(table), set(pbx)
    common = table_keys & pbx_keys

    changes = [
        {"num": num, "old": table[num], "new": pbx[num]}
        for num in sorted(common, key=_by_number)
        if table[num] != pbx[num]
    ]
    only_table = sorted(table_keys - pbx_keys, key=_by_number)
    only_pbx = sorted(pbx_keys - table_keys, key=_by_number)

    log.info(
        f"Порівняння: таблиця={len(table)}, АТС={len(pbx)}, спільних={len(common)}, "
        f"змін={len(changes)}, лише в таблиці={len(only_table)}, лише в АТС={len(only_pbx)}"
    )
    return Comparison(
        changes=changes,
        only_table=only_table,
        only_pbx=only_pbx,
        table_count=len(table),
        pbx_count=len(pbx),
        common_count=len(common),
    )
