"""
config_manager.py — збереження та завантаження data/settings.json.

Атомарний запис (tmp + fsync + os.replace) і версійна міграція схеми конфігу.

Секретні поля (SECRET_FIELDS) шифруються НА ДИСКУ через Windows DPAPI (`core/dpapi.py`):
у пам'яті програми вони завжди відкритим текстом, у файлі — токеном `dpapi:...`.
Опційний `optional_modules/core/crypto.py` шаблону в проєкт свідомо НЕ брали: він
чесно називає себе обфускацією (XOR+Base64 з вшитим у .exe ключем), а пароль ARI —
справжній секрет, не «службове поле від випадкового перегляду».
"""
import json
import os
from typing import Callable

from core import dpapi
from core.logger import log
from core.paths import data_dir as _data_dir

# ─── Поточна версія схеми конфігу ─────────────────────────────────────────────
# Підвищувати щоразу, коли змінюється СТРУКТУРА конфігу (перейменування ключа,
# зміна типу значення) — не значення. НЕ прив'язувати до APP_VERSION: конфіг і
# програма версіонуються незалежно.
CONFIG_VERSION: int = 2
# ⚠️ 1.3.0 додала шість ключів (MikroTik, Google OAuth, колонки MAC/IP) і НЕ підвищила
# версію — свідомо. Міграція потрібна там, де старе значення треба ПЕРЕТВОРИТИ; нові
# ключі з дефолтами підхоплює `{**DEFAULT_CONFIG, **loaded}` у load_config. Порожня
# міграція лише створила б видимість роботи.


def config_path() -> str:
    """
    Повний шлях до data/settings.json — рахується ПРИ КОЖНОМУ зверненні, не на імпорті.

    Раніше тут була константа `CONFIG_FILE = _get_config_path()`. Поки корінь запису був
    один-єдиний (`app_dir()`), різниці не було. Але `paths.writable_root()` обирає корінь
    у рантаймі (і може відступити в %LOCALAPPDATA%/%TEMP%), а `save_config()` робить
    `makedirs(_data_dir())` СВІЖО — тобто заморожена константа й свіжий makedirs почали б
    вказувати в різні місця: тека створюється одна, запис іде в іншу. Функція знімає цей
    клас розходжень назавжди.
    """
    return os.path.join(_data_dir(), "settings.json")


# Ключі проєкту. config_version — завжди перше поле.
#
# ⚠️ remember=True (а не шаблонний False) — свідоме відхилення від дефолту шаблону.
# Режим «без слідів» стирає конфіг при виході, тобто шлях до таблиці й геометрію вікна
# довелося б задавати щоразу заново. Для робочого інструмента з осмисленими
# налаштуваннями дефолт інвертовано.
DEFAULT_CONFIG: dict = {
    "config_version":    CONFIG_VERSION,
    "remember":          True,
    "appearance_mode":   "Dark",     # "Light" / "Gray" / "Dark" / "System"
    "color_theme":       "neutral",  # назва файлу з assets/themes/ (без .json)
    "update_check":      "never",    # "startup" / "daily" / "weekly" / "never"
    #                                  ← "never" до появи GitHub-релізів; вмикається одним рядком
    "last_update_check": "",         # ISO-8601; службове, пише core.updater.mark_checked()
    # ── Проєктні ключі ──
    "xlsx_path":         "",         # шлях до таблиці телефонів (.xlsx)
    "window_geometry":   "",         # "ШхВ+X+Y" останньої сесії; порожньо → центр екрана
    # Режими джерел — НЕЗАЛЕЖНІ один від одного (можна ручний PBX + авто таблиця й навпаки)
    "pbx_mode":          "manual",   # "manual" (вставка з FreePBX) / "auto" (Asterisk ARI)
    "table_mode":        "manual",   # "manual" (локальний .xlsx) / "auto" (Google Sheets)
    # Asterisk ARI (auto-режим PBX)
    "ari_url":           "http://192.168.192.1:8088/ari",
    "ari_user":          "",
    "ari_password":      "",         # ← SECRET_FIELDS: на диску лежить як dpapi:<base64>
    "ari_insecure_tls":  False,      # ігнорувати помилки сертифіката (для https на 8089)
    # Розкладка таблиці — літери колонок, як в Excel (спільні для .xlsx і Google Sheets)
    "table_sheet":       "",         # назва аркуша; порожньо → автовизначення за «телефон»
    "table_col_number":  "F",        # колонка внутрішнього номера
    "table_col_status":  "H",        # колонка статусу (ON/OFF)
    # Колонки MAC та IP (1.3.0) — дефолту НЕМАЄ навмисно, на відміну від номера й статусу.
    # Ті дві читаються, і вигаданий дефолт щонайгірше дасть порожній результат. Колонка IP
    # ЗАПИСУЄТЬСЯ: дефолт «навмання» затер би чужі дані в спільній робочій таблиці.
    # Порожньо → функція вважається неналаштованою, кнопки заблоковані.
    "table_col_mac":     "",         # колонка MAC-адреси телефона
    "table_col_ip":      "",         # колонка, КУДИ пишемо знайдений IP
    # Google Sheets (auto-режим таблиці)
    "sheet_url":         "",         # посилання з адресного рядка браузера
    "sheet_api_key":     "",         # ← SECRET_FIELDS: на диску лежить як dpapi:<base64>
    # MikroTik (1.3.0) — IP телефонів із DHCP-lease роутера
    "mikrotik_url":      "",         # ⚠️ З ПОРТОМ: https://192.168.0.1:8443 (REST на www-ssl)
    "mikrotik_user":     "",         # окремий read-only користувач, не admin
    "mikrotik_password": "",         # ← SECRET_FIELDS
    # Google OAuth (1.3.0) — запис IP у таблицю. Усі три ставляться кнопками в
    # налаштуваннях і вручну не редагуються.
    "google_client_id":     "",      # ← SECRET_FIELDS; з client_secret.json
    "google_client_secret": "",      # ← SECRET_FIELDS; з client_secret.json
    "google_oauth_refresh_token": "",  # ← SECRET_FIELDS; з кнопки «Авторизувати Google»
}

# Поля, які на диску зберігаються зашифрованими (див. core/dpapi.py).
#
# ⚠️ google_client_id технічно не таємниця (це публічний ідентифікатор клієнта), але
# лежить тут навмисно: пара id+secret має жити й помирати разом. Якщо конфіг перенесуть
# на іншу машину, DPAPI очистить secret — і без цього рядка лишився б id без пари,
# а помилка виглядала б як «Google не впізнав клієнта» замість «завантажте JSON знову».
SECRET_FIELDS: tuple[str, ...] = (
    "ari_password",
    "sheet_api_key",
    "mikrotik_password",
    "google_client_id",
    "google_client_secret",
    "google_oauth_refresh_token",
)


# ─── Таблиця міграцій ─────────────────────────────────────────────────────────
# Ключ — версія, ДО якої приводимо конфіг. Кожна функція: dict → dict.
# Додавати нові міграції тільки знизу, НІКОЛИ не редагувати наявні.

def _migrate_1_to_2(config: dict) -> dict:
    """
    v1→v2: вимикач `check_updates` (bool) → режим `update_check` (рядок) + `last_update_check`.

    Саме той випадок, який `{**DEFAULT, **loaded}` НЕ покриває: старий ключ лишився б у
    конфігу назавжди, а новий підхопив би дефолт, мовчки скасувавши вибір користувача.
    У цьому проєкті `check_updates` було `false`, тож коректний результат — `"never"`.
    """
    enabled = config.pop("check_updates", True)
    config["update_check"] = "startup" if enabled else "never"
    config.setdefault("last_update_check", "")
    return config


_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    2: _migrate_1_to_2,
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


def _decrypt_secrets(config: dict) -> dict:
    """
    Розшифровує секретні поля після читання з диска.

    Помилка розшифрування — не аварія: конфіг могли скопіювати з іншого ПК чи
    облікового запису Windows, або змінилась APP_NAME (ентропія). Тоді поле
    очищається і користувач вводить його заново — мовчки лишити токен у пам'яті
    гірше, бо програма спробувала б авторизуватись у ARI нечитабельним паролем.
    """
    for key in SECRET_FIELDS:
        value = config.get(key, "")
        if not dpapi.is_protected(value):
            continue
        try:
            config[key] = dpapi.unprotect(value)
        except Exception as e:
            log.error(f"Не вдалося розшифрувати '{key}': {e}. Поле очищено — введіть заново.")
            config[key] = ""
    return config


def _encrypt_secrets(config: dict) -> dict:
    """
    Шифрує секретні поля перед записом. Повертає КОПІЮ — конфіг у пам'яті
    лишається відкритим (інакше наступне читання ключа дало б токен).

    Якщо DPAPI недоступний — пишемо відкритим текстом із гучним попередженням:
    втратити налаштування користувача гірше, ніж зберегти їх незашифрованими,
    але мовчати про це не можна.
    """
    result = dict(config)
    for key in SECRET_FIELDS:
        value = str(result.get(key, "") or "")
        if not value or dpapi.is_protected(value):
            continue
        try:
            result[key] = dpapi.protect(value)
        except Exception as e:
            log.error(f"DPAPI недоступний, '{key}' збережено ВІДКРИТИМ ТЕКСТОМ: {e}")
    return result


def load_config() -> dict:
    """Завантажує конфіг, мігрує за потреби. При помилці — дефолтні значення."""
    config_file = config_path()
    if not os.path.isfile(config_file):
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        loaded = _run_migrations(loaded)
        return _decrypt_secrets({**DEFAULT_CONFIG, **loaded})
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
    config_file = config_path()
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    config_to_save = {**config, "config_version": CONFIG_VERSION}
    keys = {**DEFAULT_CONFIG, **config_to_save}
    clean = {k: config_to_save.get(k, DEFAULT_CONFIG.get(k, "")) for k in keys}
    clean = _encrypt_secrets(clean)
    tmp = config_file + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())       # на диск до rename — захист від раптового вимкнення
        os.replace(tmp, config_file)   # атомарна заміна (на Windows — MoveFileEx)
        log.info(f"Конфіг збережено: {config_file}")
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
    config_file = config_path()
    if not os.path.isfile(config_file):
        return True
    try:
        os.remove(config_file)
        log.info("Конфіг видалено.")
        return True
    except Exception as e:
        log.error(f"Не вдалося видалити конфіг: {e}")
        return False
