"""
comparator.py — логіка порівняння статусів телефонів.
"""
from core.logger import log


def compare(
    xlsx_phones: dict[str, str],
    online_nums: set[str],
    offline_nums: set[str],
) -> tuple[list[dict], dict[str, str]]:
    """
    Порівнює статуси з таблиці та з FreePBX.
    Повертає (список змін, словник FreePBX статусів).

    Зміна: {'num': '1026', 'old': 'OFF', 'new': 'ON'}
    Тільки номери, які є в обох джерелах і статус відрізняється.
    """
    pbx: dict[str, str] = {}
    for n in online_nums:
        pbx[n] = 'ON'
    for n in offline_nums:
        pbx[n] = 'OFF'

    common  = set(xlsx_phones.keys()) & set(pbx.keys())
    changes = []

    for num in sorted(common, key=lambda x: int(x)):
        old = xlsx_phones[num]
        new = pbx[num]
        if old != new:
            changes.append({'num': num, 'old': old, 'new': new})

    log.info(
        f"Порівняння: таблиця={len(xlsx_phones)}, "
        f"FreePBX={len(pbx)}, спільних={len(common)}, змін={len(changes)}"
    )
    return changes, pbx
