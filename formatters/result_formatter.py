"""
result_formatter.py — формування звіту про порівняння статусів телефонів.

Доменний модуль без GUI (ярус C): на вхід — результат `parsers.comparator.compare`,
на вихід — готовий текст. Два представлення того самого звіту:

  • build_segments()   → список (текст, тег) для кольорового tk/CTk-текстбокса;
  • build_plain_text() → плаский текст для збереження у .txt;
  • build_status_label() → короткий підсумок для рядка статусу.

Тексти, ширини колонок і символи перенесені з GUI дослівно — формат звіту не змінювався.
Теги (`dim`, `accent`, `green`, `red`, `yellow`, `bold`) — імена, які GUI зіставляє з
кольорами поточної теми; сам модуль про кольори нічого не знає.
"""
from __future__ import annotations

# Ширина роздільників і колонок — як у початковій версії звіту.
_LINE_WIDTH: int = 52

# Іменовані теги оформлення (GUI мапить їх на кольори палітри теми).
TAG_DIM: str = "dim"
TAG_ACCENT: str = "accent"
TAG_GREEN: str = "green"
TAG_RED: str = "red"
TAG_YELLOW: str = "yellow"
TAG_BOLD: str = "bold"

Segment = tuple[str, str]   # (текст, тег)


def build_segments(
    changes: list[dict],
    xlsx_phones: dict[str, str],
    pbx: dict[str, str],
    now: str,
) -> list[Segment]:
    """
    Кольоровий звіт як послідовність (текст, тег) — GUI вставляє їх підряд.

    Порядок і вміст блоків збережено з попередньої версії: шапка з датою, рядок
    підсумків, потім або «змін немає», або таблиця (спершу ті, що підключились,
    потім ті, що відключились).
    """
    common = set(xlsx_phones) & set(pbx)
    out: list[Segment] = [
        (f"{'═' * _LINE_WIDTH}\n", TAG_DIM),
        (f"  Порівняння [{now}]\n", TAG_ACCENT),
        (f"{'═' * _LINE_WIDTH}\n", TAG_DIM),
        (
            f"  Таблиця: {len(xlsx_phones)} номерів   "
            f"FreePBX: {len(pbx)} номерів   "
            f"Спільних: {len(common)}\n",
            TAG_DIM,
        ),
        (f"{'─' * _LINE_WIDTH}\n", TAG_DIM),
    ]

    if not changes:
        out.append(("\n  ✓  Змін немає — всі статуси співпадають.\n", TAG_GREEN))
    else:
        went_on = [c for c in changes if c["new"] == "ON"]
        went_off = [c for c in changes if c["new"] == "OFF"]

        out.append((f"\n  Знайдено змін: {len(changes)}\n\n", TAG_YELLOW))
        out.append((f"  {'Номер':<10}{'Таблиця':<12}{'FreePBX':<12}Зміна\n", TAG_DIM))
        out.append((f"  {'─' * 9} {'─' * 11} {'─' * 11} {'─' * 20}\n", TAG_DIM))

        for ch in went_on:
            out.append((f"  {ch['num']:<10}", TAG_BOLD))
            out.append((f"{'OFF':<12}", TAG_RED))
            out.append((f"{'ON':<12}", TAG_GREEN))
            out.append(("↑ підключився\n", TAG_GREEN))

        for ch in went_off:
            out.append((f"  {ch['num']:<10}", TAG_BOLD))
            out.append((f"{'ON':<12}", TAG_GREEN))
            out.append((f"{'OFF':<12}", TAG_RED))
            out.append(("↓ відключився\n", TAG_RED))

    out.append((f"\n{'═' * _LINE_WIDTH}\n", TAG_DIM))
    return out


def build_plain_text(
    changes: list[dict],
    xlsx_phones: dict[str, str],
    pbx: dict[str, str],
    now: str,
) -> str:
    """Плаский звіт для збереження у .txt (без кольорів і рамок)."""
    lines = [
        f"Порівняння статусів телефонів [{now}]",
        f"Таблиця: {len(xlsx_phones)} | FreePBX: {len(pbx)} "
        f"| Спільних: {len(set(xlsx_phones) & set(pbx))}",
        "",
    ]
    if not changes:
        lines.append("Змін немає — всі статуси співпадають.")
    else:
        lines.append(f"Знайдено змін: {len(changes)}")
        lines.append("")
        for ch in changes:
            direction = "ON  (підключився)" if ch["new"] == "ON" else "OFF (відключився)"
            lines.append(f"{ch['num']}  {ch['old']} → {direction}")
    return "\n".join(lines) + "\n"


def build_status_label(changes: list[dict]) -> tuple[str, str]:
    """Короткий підсумок для рядка статусу: (текст, тег кольору)."""
    if not changes:
        return "✓ Змін немає", TAG_GREEN
    went_on = sum(1 for c in changes if c["new"] == "ON")
    went_off = len(changes) - went_on
    return (
        f"⚠ Змін: {len(changes)}  (↑{went_on} підкл., ↓{went_off} відкл.)",
        TAG_YELLOW,
    )
