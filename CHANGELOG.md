# Changelog

Усі помітні зміни цього проєкту документуються тут.
Формат — [Keep a Changelog](https://keepachangelog.com/uk/), версіонування — [SemVer](https://semver.org/lang/uk/).

## [Unreleased]

## [1.1.0] — 2026-08-06
### Added
- Ядро Python Desktop App Template `2.3.2`: `core/paths.py` (єдине джерело шляхів),
  `core/events.py` (Event Bus), `core/build_info.py` (єдина точка ідентичності),
  `core/crash_reporter.py` (окремий `crash_*.log` + подія `CRASH_OCCURRED`),
  `core/updater.py` (оновлення через GitHub Releases), `gui/theme.py`, `gui/update_dialog.py`.
- Чотири теми оформлення — Світла / Сіра / Темна / Система — з плавним переходом
  і перемикачем у нижньому рядку вікна.
- Глобальний захват логів: `print()`, `stderr` і необроблені винятки (включно з фоновими
  потоками) потрапляють у `logs/app_YYYY-MM-DD.log` навіть у `.exe` без консолі.
- `formatters/result_formatter.py` — формування звіту винесене з головного вікна
  (кольорові сегменти для GUI + плаский текст для `.txt`).
- `build_portable.spec` — збірка portable `.exe` через PyInstaller.
- `CLAUDE.md`, `README.md`, `CHANGELOG.md`, `.gitignore`.

### Changed
- Інтерфейс переписано з `tkinter/ttk` на **CustomTkinter** за структурою шаблону
  (`gui/app_window.py` + фабрики та конструктори layout у `gui/widgets.py`).
- Налаштування переїхали з `settings.json` у корені в `data/settings.json`;
  запис тепер атомарний (tmp + fsync + `os.replace`) і має версійну міграцію схеми.
  Дефолт `remember` інвертовано на `true`, щоб шлях до таблиці й геометрія вікна
  переживали закриття програми.
- `core/logger.py`, `core/cleanup.py`, `core/config_manager.py`, `core/instance_lock.py`
  замінені на модулі шаблону; шляхи більше не обчислюються в кожному файлі окремо.
- `clean_old_logs()` тримає логи 30 днів (раніше стирались усі, крім сьогоднішнього).
- Ім'я програми уніфіковано до `PhonesStatus` (заголовок вікна, mutex, банер логу, ім'я `.exe`).

### Unchanged
- Алгоритми `parsers/xlsx_parser.py` і `parsers/comparator.py` перенесені **байт-у-байт**:
  вибір аркуша, колонки B/H, фільтр `^\d{3,5}$`, правило порівняння не змінювались.
- Формат звіту (текст, колонки, символи) збережено дослівно.

### Notes
- Автоперевірка оновлень **вимкнена** (`check_updates: false`) — GitHub-релізів ще немає.
- `assets/updater/updater.exe` не зібрано; потрібен перед першою portable-збіркою.
- `core/paths.py` взято зі шаблону без змін, тому в onefile-збірці вшиті ресурси
  (`assets/themes/neutral.json`, `updater.exe`) не знайдуться — див. розділ про відому
  ваду ядра в `CLAUDE.md`.

## [1.0.0] — до міграції
### Added
- Порівняння статусів телефонів: читання таблиці Excel, парсинг вставлених списків
  Online/Offline з FreePBX, кольоровий звіт про зміни, збереження звіту у `.txt`.
- Інтерфейс на `tkinter/ttk` (тема One Dark), гарячі клавіші з підтримкою кирилиці,
  контекстне меню, один екземпляр через Windows mutex, логування у `logs/`.

> Версії 1.0.0 у коді не було — секцію відновлено при міграції для повноти історії.
