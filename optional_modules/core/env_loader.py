"""
env_loader.py — читання .env для dev-налаштувань. ОПЦІЙНИЙ модуль.

Дозволяє тестувати з іншим GITHUB_REPO або вимкнути автооновлення при розробці,
не міняючи build_info.py. У .exe (frozen) .env НЕ читається ніколи — секрети фізично
не потрапляють у бінарник.

Підключення: скопіювати у core/, викликати в main.py САМИМ ПЕРШИМ, до інших імпортів:
    from core.env_loader import load_env
    load_env()

.env (додати у .gitignore):
    CHECK_UPDATES=false
    GITHUB_REPO=myname/MyApp-dev
    LOG_LEVEL=DEBUG
"""
import os
import sys


def load_env() -> None:
    """Читає .env у корені проєкту в os.environ (setdefault). Тільки якщо не frozen."""
    if getattr(sys, "frozen", False):
        return  # у .exe .env не читається ніколи
    from core.paths import app_dir  # лазі-імпорт: load_env викликається до інших імпортів
    env_path = os.path.join(app_dir(), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
