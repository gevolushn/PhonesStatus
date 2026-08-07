"""
paths.py — ЄДИНЕ джерело правди про базові шляхи програми (frozen vs dev). ЯДРО.

Один раз виводить корінь програми:
  - frozen (.exe):        папка з .exe (sys.executable);
  - dev (python main.py): корінь проєкту (на рівень вище за core/, бо цей файл — у core/).

Решта модулів беруть готові шляхи звідси, не повторюючи блок getattr(sys, 'frozen').
Так усунено 7 копій одного й того ж виведення кореня — баг-клас: одна копія дрейфне
(зміна розкладки папок, інша глибина dirname), решта мовчки вкажуть не туди, і це видно
лише у зібраному .exe, не в dev.

Чому корінь рахується від ЦЬОГО файлу, а не від __file__ викликача: paths.py завжди
лежить у core/, тож глибина dirname фіксована тут. Викликачі (навіть main.py у корені,
якому раніше треба було на один dirname менше) більше не думають про власну глибину.

Залежності — ТІЛЬКИ os/sys (без core.logger), щоб logger міг імпортувати paths без циклу:
    paths → (os, sys);  logger → paths;  решта → logger.
"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """Корінь програми: папка з .exe (frozen) або корінь проєкту (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Цей файл — core/paths.py → корінь проєкту на рівень вище за core/.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def logs_dir() -> str:
    """Папка logs/ поруч із .exe або main.py."""
    return os.path.join(app_dir(), "logs")


def data_dir() -> str:
    """Папка data/ (settings.json та вхідні файли)."""
    return os.path.join(app_dir(), "data")


def assets_dir() -> str:
    """Папка assets/ (icons, images, themes, updater)."""
    return os.path.join(app_dir(), "assets")
