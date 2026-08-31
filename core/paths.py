"""
paths.py — ЄДИНЕ джерело правди про базові шляхи програми (frozen vs dev). ЯДРО.

ТРИ корені, не один. Плутати їх — найпідступніший клас багів PyInstaller і Windows-прав:

  app_dir()      — де програма ЛЕЖИТЬ: папка з .exe (frozen) / корінь проєкту (dev).
                   Це факт про розташування, а НЕ обіцянка, що туди можна писати.
  resource_dir() — де лежать ВШИТІ ресурси: sys._MEIPASS (frozen) / корінь проєкту (dev).
                   Від нього — те, що програма ЧИТАЄ з datas=[...]: assets/.
  writable_root()— куди програма реально МОЖЕ писати: app_dir(), а якщо туди не можна —
                   %LOCALAPPDATA%\\<APP_NAME>, у крайньому разі %TEMP%\\<APP_NAME>.
                   Від нього — logs/, data/, конфіг, файли користувача.

Чому app_dir() і resource_dir() не збігаються: обидва spec шаблону збирають onefile, а
onefile розпаковує datas=[...] у ТИМЧАСОВУ теку sys._MEIPASS, а НЕ поруч із .exe. Шлях до
вшитого ресурсу, порахований від app_dir(), у такому .exe просто не існує. У dev (_MEIPASS
немає) і в --onedir (_MEIPASS == папка з .exe) обидва корені однакові — саме тому баг не
видно ніде, крім готового onefile-.exe (див. docs/BUILD.md).

Чому app_dir() і writable_root() не збігаються: portable-програму за визначенням кладуть
куди завгодно, а Windows не дає звичайному користувачу створювати теки в корені C:\\, у
C:\\Program Files\\ і на дисках із суворими ACL. Раніше шаблон мовчки припускав протилежне
і падав ДО встановлення краш-репортера — користувач бачив голий трейсбек PyInstaller
замість вікна програми.

Правило: ПИШЕМО → від writable_root(); ЧИТАЄМО вшите → від resource_dir();
         «де я лежу» → app_dir() (напр. .env у dev, шлях для автозапуску).

⚠️ Доступність запису перевіряється ПРОБНИМ ФАЙЛОМ, а не os.access(): на Windows
os.access(path, os.W_OK) дивиться лише на атрибут «тільки читання» і нічого не знає ні про
ACL, ні про права на мережевому ресурсі — тобто бадьоро рапортує «можна» там, де перший же
запис впаде. Питати ОС дією, а не станом.

⚠️ Вибір робиться ОДИН раз і кешується. Інакше шлях міг би змінитись посеред сесії, і
частина даних осіла б в одному місці, частина в іншому.

Решта модулів беруть готові шляхи звідси, не повторюючи блок getattr(sys, 'frozen').
Так усунено 7 копій одного й того ж виведення кореня — баг-клас: одна копія дрейфне
(зміна розкладки папок, інша глибина dirname), решта мовчки вкажуть не туди, і це видно
лише у зібраному .exe, не в dev.

Чому корінь рахується від ЦЬОГО файлу, а не від __file__ викликача: paths.py завжди
лежить у core/, тож глибина dirname фіксована тут. Викликачі (навіть main.py у корені,
якому раніше треба було на один dirname менше) більше не думають про власну глибину.

Залежності на рівні модуля — ТІЛЬКИ os/sys/tempfile (без core.logger), щоб logger міг
імпортувати paths без циклу:
    paths → (os, sys, tempfile);  logger → paths;  решта → logger.
core.build_info імпортується ЛАЗІ (усередині функції) — щоб інваріант вище лишався
істинним навіть якщо build_info у дочірньому проєкті обросте власними імпортами.
"""
from __future__ import annotations

import os
import sys
import tempfile

# Кеш вибору кореня для запису: рішення приймається один раз за сесію (див. docstring).
_WRITABLE_ROOT: str | None = None
_FALLBACK_REASON: str | None = None

# Символи, заборонені в іменах папок Windows (APP_NAME може містити будь-що).
_INVALID_NAME_CHARS = '<>:"/\\|?*'


def app_dir() -> str:
    """Корінь програми: папка з .exe (frozen) або корінь проєкту (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Цей файл — core/paths.py → корінь проєкту на рівень вище за core/.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """
    Корінь ВШИТИХ ресурсів (усе з datas=[...] у .spec).

    Один рядок покриває три режими: onefile (_MEIPASS — тимчасова тека розпакування),
    onedir (_MEIPASS == папка з .exe) і dev (_MEIPASS відсутній → корінь проєкту).
    """
    return getattr(sys, "_MEIPASS", app_dir())


def _app_folder_name() -> str:
    """Ім'я теки програми для %LOCALAPPDATA% / %TEMP% — з APP_NAME, безпечне для Windows."""
    try:
        from core import build_info  # лазі-імпорт: тримає paths вільним від імпортів модуля
        raw = str(getattr(build_info, "APP_NAME", "") or "")
    except Exception:
        raw = ""
    cleaned = "".join("_" if ch in _INVALID_NAME_CHARS else ch for ch in raw)
    # Windows не дозволяє імена з провідними/кінцевими пробілами й крапками.
    cleaned = cleaned.strip(" .")
    return cleaned or "PythonApp"


def _is_writable(directory: str) -> bool:
    """
    Чи можна реально писати в теку — перевірка створенням і видаленням пробного файлу.

    Саме дією, не os.access(): на Windows останній не бачить ні ACL, ні прав на
    мережевому ресурсі (див. docstring модуля).
    """
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return False
    probe = os.path.join(directory, f".write_probe_{os.getpid()}")
    try:
        with open(probe, "w", encoding="utf-8"):
            pass
    except OSError:
        return False
    try:
        os.remove(probe)
    except OSError:
        # Записати вдалося — саме це й перевіряли. Пробний файл прибрати не змогли:
        # тека все одно придатна, лишати його не страшно (нульовий розмір).
        pass
    return True


def _write_candidates() -> list[str]:
    """Кандидати на корінь запису, у порядку спадання бажаності."""
    name = _app_folder_name()
    candidates = [app_dir()]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, name))
    candidates.append(os.path.join(tempfile.gettempdir(), name))
    return candidates


def writable_root() -> str:
    """
    Корінь для ВСЬОГО, що програма пише (logs/, data/, конфіг).

    Порядок: app_dir() → %LOCALAPPDATA%\\<APP_NAME> → %TEMP%\\<APP_NAME>.
    Результат кешується на всю сесію. Якщо довелось відступити від app_dir(),
    fallback_reason() поверне пояснення — main() зобов'язаний його показати:
    мовчазний переїзд даних гірший за саму проблему, бо користувач шукатиме
    settings.json поруч із .exe, а його там уже немає.
    """
    global _WRITABLE_ROOT, _FALLBACK_REASON
    if _WRITABLE_ROOT is not None:
        return _WRITABLE_ROOT

    candidates = _write_candidates()
    rejected: list[str] = []
    for candidate in candidates:
        if _is_writable(candidate):
            _WRITABLE_ROOT = candidate
            if rejected:
                _FALLBACK_REASON = (
                    f"Дані програми перенесено у '{candidate}': немає прав на запис у "
                    f"{', '.join(rejected)}."
                )
            return candidate
        rejected.append(f"'{candidate}'")

    # Не пишеться НІКУДИ (рідко, але тоді програма все одно мусить запуститись).
    _WRITABLE_ROOT = candidates[-1]
    _FALLBACK_REASON = (
        f"Не знайдено теки з правом запису (перевірено: {', '.join(rejected)}). "
        f"Використовую '{_WRITABLE_ROOT}' — запис, найімовірніше, не працюватиме."
    )
    return _WRITABLE_ROOT


def fallback_reason() -> str | None:
    """
    Чому дані лежать не поруч із .exe (None — усе штатно).

    Викликати ПІСЛЯ writable_root(); main() показує це попередження одразу після банера.
    """
    return _FALLBACK_REASON


def reset_writable_root_cache() -> None:
    """Скидає кеш вибору кореня. Потрібно ЛИШЕ тестам — у проді шлях не має мінятись."""
    global _WRITABLE_ROOT, _FALLBACK_REASON
    _WRITABLE_ROOT = None
    _FALLBACK_REASON = None


def logs_dir() -> str:
    """Папка logs/ — від writable_root() (запис має пережити вихід із програми)."""
    return os.path.join(writable_root(), "logs")


def data_dir() -> str:
    """Папка data/ (settings.json та вхідні файли) — від writable_root()."""
    return os.path.join(writable_root(), "data")


def assets_dir() -> str:
    """
    Папка assets/ (icons, images, themes, updater) — ВШИТА в .exe, тому від resource_dir().

    ⚠️ ТІЛЬКИ ДЛЯ ЧИТАННЯ. У onefile-збірці це тимчасова тека, яка зникає після виходу з
    програми: записане туди мовчки втрачається. Усе, що програма пише, іде в data_dir()
    або logs_dir().
    """
    return os.path.join(resource_dir(), "assets")
