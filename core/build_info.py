"""
build_info.py — ЄДИНЕ джерело правди про ідентичність і збірку програми.

Тут зведено всі ідентифікатори проєкту. Решта модулів імпортують значення звідси,
а не дублюють хардкод. При старті нового проєкту редагується лише блок «ручної
ідентичності» (5 рядків).

DISTRIBUTION НЕ редагується вручну — приходить із core/_build_dist.py, який пише
spec при freeze (build_portable.spec / build_installed.spec). У dev-режимі файлу
немає → падаємо на дефолт "portable".

⚠️ Безпека токена. GITHUB_TOKEN вшивається у portable .exe і витягується з бінарника
елементарним `strings`. Це неминуче для desktop-програми без сервера-проксі, тож:
  - приватний реліз → fine-grained PAT, обмежений ТІЛЬКИ Contents:Read-only на ОДНОМУ репо;
  - публічний реліз → GITHUB_PRIVATE = False, токен не потрібен (порожній рядок).
Ніколи не клади сюди класичний PAT з широкими правами.
"""
from __future__ import annotations

# ─── Ручна ідентичність (редагується при старті нового проєкту) ───────────────
APP_NAME: str        = "PhonesStatus"              # ← людська назва (title вікна, MessageBox, логи)
APP_VERSION: str     = "1.1.0"                     # ← оновлювати перед кожним релізом
GITHUB_REPO: str     = "gevolushn/PhonesStatus"    # ← реальний репозиторій
GITHUB_PRIVATE: bool = True                        # ← False → публічний (без токену)
GITHUB_TOKEN: str    = ""                          # ← ЗАПОВНИТИ ВРУЧНУ: fine-grained PAT,
#                                                    лише Contents:Read-only на цьому репо.
#                                                    Поки порожній — перевірка оновлень дасть 401/404
#                                                    (очікувано; check_updates у конфігу = false).

# ─── Версія шаблону, на якій побудовано проєкт (інформаційно) ──────────────────
TEMPLATE_VERSION: str = "2.3.2"  # ← база шаблону; бампати ПІСЛЯ кожної синхронізації з шаблоном
#   (процедура — docs/HOW_UPDATE_YOUR_PROJECT.md у репо шаблону). На роботу програми НЕ впливає,
#   потрібне лише щоб знати свою стартову точку при оновленні ядра.

# ─── Тип дистрибуції (пишеться spec-ом у core/_build_dist.py при freeze) ───────
try:
    from core._build_dist import DISTRIBUTION
except ImportError:
    DISTRIBUTION = "portable"  # dev-дефолт; у .exe файл присутній і дає реальний режим

# ─── Похідні значення (обчислюються, НЕ дублюються вручну) ─────────────────────
APP_MUTEX: str  = f"Global\\{APP_NAME}_SingleInstance"   # instance_lock
SECRET_KEY: str = f"{APP_NAME}_ObfuscationKey_2026"      # лише для опційного crypto.py
#                                                          ⚠️ НЕ криптостійкий ключ — обфускація
TEMP_PREFIX: str = "phonesstatus_"  # ← технічний префікс файлів у %TEMP%.
#   Узгоджується вручну з assets/updater/updater_src.py (_LOG_PATH) — той збирається
#   ОКРЕМИМ .exe і НЕ може імпортувати build_info. Тримати ідентичним.
