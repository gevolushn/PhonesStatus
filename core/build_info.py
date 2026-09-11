"""
build_info.py — ЄДИНЕ джерело правди про ідентичність і збірку програми.

Тут зведено всі ідентифікатори проєкту. Решта модулів імпортують значення звідси,
а не дублюють хардкод. При старті нового проєкту редагується лише блок «ручної
ідентичності» (4 рядки).

DISTRIBUTION НЕ редагується вручну — приходить із core/_build_dist.py, який пише
spec при freeze (build_portable.spec / build_installed.spec). У dev-режимі файлу
немає → падаємо на дефолт "portable".

⚠️ Безпека токена. GITHUB_TOKEN вшивається у portable .exe і витягується з бінарника
елементарним `strings`. Це неминуче для desktop-програми без сервера-проксі, тож:
  - приватний реліз → fine-grained PAT, обмежений ТІЛЬКИ Contents:Read-only на ОДНОМУ репо;
  - публічний реліз → GITHUB_PRIVATE = False, токен не потрібен (порожній рядок).
Ніколи не клади сюди класичний PAT з широкими правами.

GITHUB_TOKEN сюди НЕ пишеться напряму — цей файл версіюється, і покладений токен
НАЗАВЖДИ осідає в git-історії (не «прибирається», лише відкликається й перевипускається).
Токен живе в core/_build_secrets.py (у .gitignore, ніколи не комітиться): скопіювати
core/_build_secrets.py.example, заповнити, зберегти. Без файлу — дефолт "" (dev-режим,
оновлення локально не тестуються).
"""
from __future__ import annotations

# ─── Ручна ідентичність (редагується при старті нового проєкту) ───────────────
APP_NAME: str        = "PhonesStatus"              # ← людська назва (title вікна, MessageBox, логи)
APP_VERSION: str     = "1.3.0"                     # ← оновлювати перед кожним релізом
GITHUB_REPO: str     = "gevolushn/PhonesStatus"    # ← реальний репозиторій
GITHUB_PRIVATE: bool = True                        # ← False → публічний (без токену)

# ─── Токен — НЕ тут. core/_build_secrets.py (gitignored), див. докстрінг файлу ─
try:
    from core._build_secrets import GITHUB_TOKEN
except ImportError:
    GITHUB_TOKEN: str = ""   # dev-дефолт; немає core/_build_secrets.py → оновлення локально не тестуються

# ─── Версія шаблону, на якій побудовано проєкт (інформаційно) ──────────────────
TEMPLATE_VERSION: str = "2.5.0"  # ← база шаблону; бампати ПІСЛЯ кожної синхронізації з шаблоном
#   (процедура — docs/HOW_UPDATE_YOUR_PROJECT.md у репо шаблону). На роботу програми НЕ впливає,
#   потрібне лише щоб знати свою стартову точку при оновленні ядра.

# ─── Тип дистрибуції (пишеться spec-ом у core/_build_dist.py при freeze) ───────
try:
    from core._build_dist import DISTRIBUTION
except ImportError:
    DISTRIBUTION = "portable"  # dev-дефолт; у .exe файл присутній і дає реальний режим

# ─── Похідні значення (обчислюються, НЕ дублюються вручну) ─────────────────────
APP_MUTEX: str  = f"{APP_NAME}_SingleInstance"   # instance_lock — БЕЗ простору імен:
#   Local\/Global\ додає сам instance_lock.acquire() (дефолт — Local\, див. docstring там)
SECRET_KEY: str = f"{APP_NAME}_ObfuscationKey_2026"      # лише для опційного crypto.py
#                                                          ⚠️ НЕ криптостійкий ключ — обфускація
TEMP_PREFIX: str = "phonesstatus_"  # ← технічний префікс файлів у %TEMP%.
#   Узгоджується вручну з assets/updater/updater_src.py (_LOG_PATH) — той збирається
#   ОКРЕМИМ .exe і НЕ може імпортувати build_info. Тримати ідентичним.
