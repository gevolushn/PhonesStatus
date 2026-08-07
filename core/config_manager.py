"""
config_manager.py — збереження та завантаження data/settings.json.

Атомарний запис (tmp + fsync + os.replace) і версійна міграція схеми конфігу.

Обфускація — опційна (optional_modules/core/crypto.py, XOR+Base64, НЕ криптостійка):
замінити json.load/dump на crypto.decrypt/encrypt, якщо треба сховати конфіг від
випадкового перегляду в текстовому редакторі.
"""
import json
import os

from core.logger import log
from core.paths import data_dir as _data_dir

# ─── Поточна версія схеми конфігу ─────────────────────────────────────────────
# Підвищувати щоразу, коли змінюється СТРУКТУРА конфігу (перейменування ключа,
# зміна типу значення) — не значення. НЕ прив'язувати до APP_VERSION: конфіг і
# програма версіонуються незалежно.
CONFIG_VERSION: int = 1


def _get_config_path() -> str:
    return os.path.join(_data_dir(), "settings.json")


CONFIG_FILE = _get_config_path()

# Ключі проєкту. config_version — завжди перше поле.
#
# ⚠️ remember=True (а не шаблонний False) — свідоме відхилення від дефолту шаблону.
# Режим «без слідів» стирає конфіг при виході, тобто шлях до таблиці й геометрію вікна
# довелося б задавати щоразу заново. Для робочого інструмента з осмисленими
# налаштуваннями дефолт інвертовано.
DEFAULT_CONFIG: dict = {
    "config_version":  CONFIG_VERSION,
    "remember":        True,
    "appearance_mode": "Dark",     # "Light" / "Gray" / "Dark" / "System"
    "color_theme":     "neutral",  # назва файлу з assets/themes/ (без .json)
    "check_updates":   False,      # автоперевірка оновлень — вимкнена до появи GitHub-релізів
    # ── Проєктні ключі ──
    "xlsx_path":       "",         # шлях до таблиці телефонів (.xlsx)
    "window_geometry": "",         # "ШхВ+X+Y" останньої сесії; порожньо → центр екрана
}


# ─── Таблиця міграцій ─────────────────────────────────────────────────────────
# Ключ — версія, ДО якої приводимо конфіг. Кожна функція: dict → dict.
# Додавати нові міграції тільки знизу, НІКОЛИ не редагувати наявні.

def _migrate_1_to_2(config: dict) -> dict:
    """
    Приклад-заготовка міграції v1→v2 (поки не активна).
    - перейменування ключа: config["new"] = config.pop("old")
    - нове поле:            config.setdefault("new_field", default)
    """
    return config


_MIGRATIONS: dict[int, callable] = {
    # 2: _migrate_1_to_2,   # розкоментувати, коли CONFIG_VERSION стане 2
}
# ─────────────────────────────────────────────────────────────────────────────


def _run_migrations(config: dict) -> dict:
    """Послідовно застосовує міграції від збереженої версії конфігу до CONFIG_VERSION."""
    saved_version = int(config.get("config_version", 1))
    if saved_version == CONFIG_VERSION:
        return config

    log.info(f"Конфіг версії {saved_version}, поточна {CONFIG_VERSION} — міграція.")
    for target in range(saved_version + 1, CONFIG_VERSION + 1):
        fn = _MIGRATIONS.get(target)
        if fn is None:
            log.warning(f"Міграція v{target - 1}→v{target} відсутня — пропускаю.")
            continue
        try:
            config = fn(config)
            config["config_version"] = target
            log.info(f"Міграція до v{target} — успішно.")
        except Exception as e:
            log.error(f"Помилка міграції до v{target}: {e}", exc_info=True)
            # Краще частково мігрований конфіг, ніж аварійний вихід
    return config


def load_config() -> dict:
    """Завантажує конфіг, мігрує за потреби. При помилці — дефолтні значення."""
    if not os.path.isfile(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        loaded = _run_migrations(loaded)
        return {**DEFAULT_CONFIG, **loaded}
    except Exception as e:
        log.error(f"Помилка читання конфігу: {e}. Скидаю до дефолтних.")
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> bool:
    """
    Зберігає конфіг у data/settings.json атомарно.

    Пишемо в .tmp, робимо fsync (дані фізично на диску), і лише потім os.replace()
    атомарно підміняє основний файл. Уривання процесу посеред запису ніколи не
    лишає обрізаний settings.json (інакше load_config впав би й мовчки скинув усе).
    """
    os.makedirs(_data_dir(), exist_ok=True)
    config_to_save = {**config, "config_version": CONFIG_VERSION}
    keys = {**DEFAULT_CONFIG, **config_to_save}
    clean = {k: config_to_save.get(k, DEFAULT_CONFIG.get(k, "")) for k in keys}
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())       # на диск до rename — захист від раптового вимкнення
        os.replace(tmp, CONFIG_FILE)   # атомарна заміна (на Windows — MoveFileEx)
        log.info(f"Конфіг збережено: {CONFIG_FILE}")
        return True
    except Exception as e:
        log.error(f"Помилка збереження конфігу: {e}")
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False


def delete_config() -> bool:
    """Видаляє data/settings.json (режим 'без слідів')."""
    if not os.path.isfile(CONFIG_FILE):
        return True
    try:
        os.remove(CONFIG_FILE)
        log.info("Конфіг видалено.")
        return True
    except Exception as e:
        log.error(f"Не вдалося видалити конфіг: {e}")
        return False
