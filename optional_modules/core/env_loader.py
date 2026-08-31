"""
env_loader.py — читання .env для dev-налаштувань. ОПЦІЙНИЙ модуль.

Кладе значення з .env у os.environ (setdefault, не перезаписує вже встановлені змінні
процесу). У .exe (frozen) .env НЕ читається ніколи — секрети фізично не потрапляють у
бінарник.

⚠️ Сам по собі цей модуль нічого не змінює в поведінці програми: він лише наповнює
os.environ. Щоб .env реально на щось впливав (інший GITHUB_REPO при розробці, інший
рівень логування тощо), відповідний код має явно ЧИТАТИ потрібну змінну з os.environ —
типово в build_info.py:
    GITHUB_REPO: str = os.environ.get("GITHUB_REPO", "username/MyAppName")
Без такого читання значення з .env просто лежать у os.environ незатребувані.

Підключення: скопіювати у core/, викликати в main.py САМИМ ПЕРШИМ, до інших імпортів:
    from core.env_loader import load_env
    load_env()

.env (додати у .gitignore):
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
