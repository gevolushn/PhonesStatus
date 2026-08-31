"""
result_formatter.py — формування звіту про порівняння статусів телефонів.

Доменний модуль без GUI (ярус C): на вхід — `parsers.comparator.Comparison`,
на вихід — готовий текст. Три представлення того самого звіту:

  • build_segments()     → список (текст, тег) для кольорового tk/CTk-текстбокса;
  • build_plain_text()   → плаский текст для збереження у .txt;
  • build_status_label() → короткий підсумок для рядка статусу.

Теги (`dim`, `accent`, `green`, `red`, `yellow`, `bold`) — імена, які GUI зіставляє з
кольорами поточної теми; сам модуль про кольори нічого не знає.

Про секції «поза перетином» (нове в 1.2.0). Номери, яких немає в одному з джерел,
раніше зникали мовчки — і це було правильно, доки АТС-дані вводились руками: список
«немає в АТС» дорівнював би «все, чого ви не вставили». В авто-режимі ARI віддає ВСІ
endpoint'и, тобто дані вичерпні, і розбіжність стає справжньою знахідкою. Тому секція
«у таблиці, немає в АТС» друкується лише коли `pbx_complete=True`.
"""
from __future__ import annotations

from parsers.comparator import Comparison

# Ширина роздільників і колонок — як у початковій версії звіту.
_LINE_WIDTH: int = 52
_NUMBERS_PER_ROW: int = 8      # щоб довгий список не розтягнувся на сотню рядків

# Іменовані теги оформлення (GUI мапить їх на кольори палітри теми).
TAG_DIM: str = "dim"
TAG_ACCENT: str = "accent"
TAG_GREEN: str = "green"
TAG_RED: str = "red"
TAG_YELLOW: str = "yellow"
TAG_BOLD: str = "bold"

Segment = tuple[str, str]   # (текст, тег)


def _wrap_numbers(numbers: list[str], indent: str = "  ") -> list[str]:
    """Розкладає номери у рядки по _NUMBERS_PER_ROW — компактно і читабельно."""
    rows = []
    for start in range(0, len(numbers), _NUMBERS_PER_ROW):
        chunk = numbers[start:start + _NUMBERS_PER_ROW]
        rows.append(indent + "  ".join(f"{n:<5}" for n in chunk).rstrip())
    return rows


def build_segments(result: Comparison, now: str, pbx_complete: bool = False) -> list[Segment]:
    """
    Кольоровий звіт як послідовність (текст, тег) — GUI вставляє їх підряд.

    `pbx_complete` — чи вичерпні дані АТС (True для авто-режиму ARI). Від нього
    залежить лише секція «у таблиці, немає в АТС».
    """
    out: list[Segment] = [
        (f"{'═' * _LINE_WIDTH}\n", TAG_DIM),
        (f"  Порівняння [{now}]\n", TAG_ACCENT),
        (f"{'═' * _LINE_WIDTH}\n", TAG_DIM),
        (
            f"  Таблиця: {result.table_count} номерів   "
            f"АТС: {result.pbx_count} номерів   "
            f"Спільних: {result.common_count}\n",
            TAG_DIM,
        ),
        (f"{'─' * _LINE_WIDTH}\n", TAG_DIM),
    ]

    if not result.changes:
        out.append(("\n  ✓  Змін немає — всі спільні статуси співпадають.\n", TAG_GREEN))
    else:
        went_on = [c for c in result.changes if c["new"] == "ON"]
        went_off = [c for c in result.changes if c["new"] == "OFF"]

        out.append((f"\n  Знайдено змін: {len(result.changes)}\n\n", TAG_YELLOW))
        out.append((f"  {'Номер':<10}{'Таблиця':<12}{'АТС':<12}Зміна\n", TAG_DIM))
        out.append((f"  {'─' * 9} {'─' * 11} {'─' * 11} {'─' * 20}\n", TAG_DIM))

        for change in went_on:
            out.append((f"  {change['num']:<10}", TAG_BOLD))
            out.append((f"{'OFF':<12}", TAG_RED))
            out.append((f"{'ON':<12}", TAG_GREEN))
            out.append(("↑ підключився\n", TAG_GREEN))

        for change in went_off:
            out.append((f"  {change['num']:<10}", TAG_BOLD))
            out.append((f"{'ON':<12}", TAG_GREEN))
            out.append((f"{'OFF':<12}", TAG_RED))
            out.append(("↓ відключився\n", TAG_RED))

    if result.only_pbx:
        out.append((f"\n{'─' * _LINE_WIDTH}\n", TAG_DIM))
        out.append((f"  ⚠  В АТС, але немає в таблиці: {len(result.only_pbx)}\n", TAG_YELLOW))
        out.append(("     (заведені на АТС, але не внесені в таблицю)\n\n", TAG_DIM))
        for row in _wrap_numbers(result.only_pbx, indent="     "):
            out.append((row + "\n", TAG_BOLD))

    if pbx_complete and result.only_table:
        out.append((f"\n{'─' * _LINE_WIDTH}\n", TAG_DIM))
        out.append((f"  ⚠  У таблиці, але немає в АТС: {len(result.only_table)}\n", TAG_YELLOW))
        out.append(("     (видалені з АТС або помилка в номері)\n\n", TAG_DIM))
        for row in _wrap_numbers(result.only_table, indent="     "):
            out.append((row + "\n", TAG_BOLD))

    out.append((f"\n{'═' * _LINE_WIDTH}\n", TAG_DIM))
    return out


def build_plain_text(result: Comparison, now: str, pbx_complete: bool = False) -> str:
    """Плаский звіт для збереження у .txt (без кольорів і рамок)."""
    lines = [
        f"Порівняння статусів телефонів [{now}]",
        f"Таблиця: {result.table_count} | АТС: {result.pbx_count} "
        f"| Спільних: {result.common_count}",
        "",
    ]
    if not result.changes:
        lines.append("Змін немає — всі спільні статуси співпадають.")
    else:
        lines.append(f"Знайдено змін: {len(result.changes)}")
        lines.append("")
        for change in result.changes:
            direction = ("ON  (підключився)" if change["new"] == "ON"
                         else "OFF (відключився)")
            lines.append(f"{change['num']}  {change['old']} → {direction}")

    if result.only_pbx:
        lines += ["", f"В АТС, але немає в таблиці ({len(result.only_pbx)}):"]
        lines += _wrap_numbers(result.only_pbx, indent="  ")

    if pbx_complete and result.only_table:
        lines += ["", f"У таблиці, але немає в АТС ({len(result.only_table)}):"]
        lines += _wrap_numbers(result.only_table, indent="  ")

    return "\n".join(lines) + "\n"


def build_status_label(result: Comparison, pbx_complete: bool = False) -> tuple[str, str]:
    """Короткий підсумок для рядка статусу: (текст, тег кольору)."""
    extra = len(result.only_pbx) + (len(result.only_table) if pbx_complete else 0)
    if not result.changes:
        if extra:
            return f"✓ Змін немає  ·  поза перетином: {extra}", TAG_YELLOW
        return "✓ Змін немає", TAG_GREEN

    went_on = sum(1 for c in result.changes if c["new"] == "ON")
    went_off = len(result.changes) - went_on
    label = f"⚠ Змін: {len(result.changes)}  (↑{went_on} підкл., ↓{went_off} відкл.)"
    if extra:
        label += f"  ·  поза перетином: {extra}"
    return label, TAG_YELLOW
