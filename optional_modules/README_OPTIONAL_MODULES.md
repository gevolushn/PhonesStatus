# Опційні модулі

> Практичний каталог модулів, які **не обов'язкові** для роботи програми.
> Підключаються за потреби. Базовий шаблон працює і без жодного з них.
>
> Повніший опис (навіщо вони винесені, коли «підвищувати» до `core/`) — у
> `docs/OPTIONAL_MODULES.md` репозиторію шаблону (не їде в новий проект).

---

## Як підключити модуль

1. **Скопіювати** файл з `optional_modules/core/` у `core/` (або з `optional_modules/gui/` у `gui/`).
   Імпорти всередині модулів уже абсолютні (`from core.x`, `from gui.x`) — після
   переміщення працюють без правок.
2. **Додати залежності** (якщо є) у `requirements.txt`.
3. **Інтегрувати** за сніпетом нижче.
4. **Видалити** з `optional_modules/` те, що точно не знадобиться (необов'язково).

> `optional_modules/` цілком можна видалити з проєкту, якщо нічого з нього не потрібно.

---

## `core/` — опційні модулі ядра

### `crypto.py` — обфускація конфігу
- **Залежності:** немає (stdlib).
- **Що робить:** XOR+Base64 над `settings.json`. ⚠️ **НЕ шифрування** — лише захист від
  випадкового перегляду в текстовому редакторі. Ключ — `SECRET_KEY` з `core/build_info.py`.
- **Інтеграція:** у `config_manager.py` замінити `json.load/dump` на `crypto.decrypt/encrypt`.

### `health.py` — перевірка доступності ресурсів
- **Залежності:** немає (stdlib).
- **Що робить:** фоново перевіряє URL / шлях / порт; емітує `Events.HEALTH_CHANGED` лише при ЗМІНІ стану.
- **Подія:** `health_changed` (kwargs: `name`, `ok`, `label`, `critical`).
- **Інтеграція:**
  ```python
  from core.health import HealthChecker, Resource
  health = HealthChecker(interval_sec=60)
  health.register(Resource("github", "url", "https://api.github.com", critical=False))
  health.start()
  subscribe(Events.HEALTH_CHANGED, self._on_health)
  ```

### `state_manager.py` — runtime-стан програми
- **Залежності:** немає (stdlib).
- **Що робить:** потокобезпечний синглтон `state` (get/set/register/reset); емітує
  `Events.STATE_CHANGED` при зміні значення.
- **Подія:** `state_changed` (kwargs: `key`, `value`, `prev_value`).
- **Інтеграція:**
  ```python
  from core.state_manager import state
  state.register("is_processing", False)
  state.set("is_processing", True)
  subscribe(Events.STATE_CHANGED, self._on_state)
  ```

### `env_loader.py` — `.env` для dev-налаштувань
- **Залежності:** немає (stdlib).
- **Що робить:** читає `.env` у `os.environ` лише в dev (не в `.exe`).
- **Інтеграція** (у `main.py` **найпершим**, до інших імпортів):
  ```python
  from core.env_loader import load_env
  load_env()
  ```
- Не забути додати `.env` у `.gitignore`.

---

## `gui/` — опційні модулі інтерфейсу

### `tray.py` — іконка у системному треї
- **Залежності:** `pystray>=0.19.5`, `Pillow>=10.0.0`.
- **Що робить:** іконка в треї з меню; колбеки автоматично повертаються у GUI-потік.
- **Інтеграція:**
  ```python
  self._tray = TrayIcon(root=self, app_name=build_info.APP_NAME, on_quit=self._quit_app,
      menu_extra=[("Налаштування", self._open_settings), ("Про програму", self._show_about)])
  self._tray.start()
  ```
- У `app_window.py`: `WM_DELETE_WINDOW` → ховати замість закривати; єдина точка виходу
  `_quit_app` з порядком `tray.stop()` **перед** `destroy()`.

### `dialogs.py` — CTk-нативні діалоги
- **Залежності:** немає (понад customtkinter).
- **Що робить:** `confirm()`, `ask_input()` (з валідацією), `ask_file()`/`ask_save_file()`.
  Модальні (`grab_set()`) — на відміну від `UpdateDialog`.
- **Інтеграція:**
  ```python
  from gui.dialogs import confirm, ask_input, ask_file
  if confirm(self, "Видалити", "Незворотно.", danger=True):
      ...
  ```

### `progress.py` — `BackgroundTask`
- **Залежності:** немає (понад customtkinter).
- **Що робить:** блокує кнопки, показує indeterminate-індикатор, виконує задачу в потоці,
  повертає результат через `on_done`/`on_error`.
- **Інтеграція:**
  ```python
  from gui.progress import BackgroundTask
  BackgroundTask(root=self, label="Обробка...", btn_lock=[self._btn]).run(
      work=lambda: heavy(), on_done=self._show_result, on_error=self._show_error)
  ```

### `splash.py` — екран завантаження
- **Залежності:** немає (чистий `tk.Tk`).
- **Що робить:** вікно без рамки з прогрес-баром до відкриття головного вікна.
  ⚠️ Додавати лише якщо старт > 2-3с.
- **Інтеграція** (у `main.py`):
  ```python
  from gui.splash import SplashScreen
  splash = SplashScreen(app_name=build_info.APP_NAME, version=build_info.APP_VERSION)
  splash.set_status("Завантаження...", progress=0.3)
  splash.close()  # перед AppWindow(config)
  ```

---

## Зведення подій Event Bus від опційних модулів

| Подія (`Events.*`) | Модуль | Kwargs |
|---|---|---|
| `HEALTH_CHANGED` | `health.py` | `name`, `ok`, `label`, `critical` |
| `STATE_CHANGED` | `state_manager.py` | `key`, `value`, `prev_value` |

> `CRASH_OCCURRED` тепер у ядрі (`core/crash_reporter.py`) — не опційна.

Імена подій оголошені в `core/events.py` (клас `Events`) — підписуйся на константи,
не на «голі» рядки.
