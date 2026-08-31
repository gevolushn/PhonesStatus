"""
app_window.py — головне вікно програми порівняння статусів телефонів.

Порядок __init__ є критичним:
    1. Параметри вікна
    2. GUI-елементи (build_*)
    3. Hotkeys і контекстне меню
    4. subscribe + theme_mgr.load() — ПІСЛЯ всіх віджетів (щоб перший emit дійшов до всіх)
    5. Відновлення геометрії + _load_initial_state()
    6. WM_DELETE_WINDOW

Вікно тримає лише UI і реакції на дії користувача. Читання джерел — у parsers/,
порівняння — у parsers/comparator.py, формування звіту — у formatters/result_formatter.py.
Алгоритмів тут немає.

Два НЕЗАЛЕЖНІ перемикачі режиму (АТС і таблиця) дають чотири робочі комбінації.
Обидва джерела зобов'язані повернути той самий контракт — словник «номер → ON/OFF» —
тому нижче по потоку (compare → formatter) розгалужень за режимом немає взагалі.
"""
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.logger import log
from core import config_manager
from core.events import subscribe, unsubscribe, Events
from core.updater import check_for_updates, should_check_now, mark_checked
import core.build_info as build_info
from gui.widgets import (
    build_action_bar,
    build_auto_body,
    build_footer,
    build_header,
    build_input_panel,
    build_result_panel,
    build_source_panel,
    build_table_manual_body,
    mode_key,
    status_colors,
)
from gui.hotkeys import bind_to_all
from gui.context_menu import AppContextMenu
from gui.progress import BackgroundTask
from gui.settings_window import show_settings
from gui.theme import theme_mgr
from gui.update_dialog import show_update_dialog
from parsers.xlsx_parser import read_xlsx, list_sheets, detect_sheet
from parsers.sheets_parser import read_sheet, SheetsError
from parsers.pbx_manual import read_manual
from parsers.pbx_ari import read_ari, AriError
from parsers.comparator import compare
from formatters.result_formatter import (
    build_plain_text,
    build_segments,
    build_status_label,
)

_DEFAULT_SIZE: tuple[int, int] = (980, 720)
_MIN_SIZE: tuple[int, int] = (900, 660)


class AppWindow(ctk.CTk):
    """Головне вікно CTk. Уся логіка подій програми."""

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config
        self._last_result_txt = ""
        self._status_tag = "green"          # тег кольору поточного рядка статусу
        self._closing = False               # ідемпотентність _on_closing

        self.title(build_info.APP_NAME)
        self.minsize(*_MIN_SIZE)
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)   # панелі джерел
        self.grid_rowconfigure(3, weight=2)   # панель результату

        self.xlsx_path = ctk.StringVar(value=config.get("xlsx_path", ""))

        self._build_ui()

        self._ctx = AppContextMenu(self)
        editable = [self._online.textbox, self._offline.textbox, self._table_manual.entry]
        bind_to_all(editable, self)
        self._ctx.bind_all(editable + [self._result.textbox])

        # Підписка ДО theme_mgr.load(): перший emit одразу застосує палітру до вікна
        subscribe(Events.THEME_CHANGED, self._on_theme_changed)
        theme_mgr.load(root=self, config=self._config)

        self._restore_geometry(config.get("window_geometry", ""))
        self._load_initial_state()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        log.info("Вікно ініціалізовано.")

    # ═══════════════════════════════════════════
    #  ПОБУДОВА ІНТЕРФЕЙСУ
    # ═══════════════════════════════════════════

    def _build_ui(self) -> None:
        """Створює всі області вікна. Layout і стилі — у gui/widgets.py."""
        self._header = build_header(self)
        self._header.frame.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 10))

        self._pbx_panel = build_source_panel(
            self,
            title_text="📡  FreePBX",
            accent_key="accent",
            current_mode=self._config.get("pbx_mode", "manual"),
            on_mode_change=self._on_pbx_mode,
        )
        self._pbx_panel.frame.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 4))
        self._build_pbx_bodies()

        self._table_panel = build_source_panel(
            self,
            title_text="📊  Таблиця",
            accent_key="green",
            current_mode=self._config.get("table_mode", "manual"),
            on_mode_change=self._on_table_mode,
        )
        self._table_panel.frame.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 4))
        self._build_table_bodies()

        self._actions = build_action_bar(
            self, on_run=self._run, on_settings=self._open_settings)
        self._actions.frame.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=10)

        self._result = build_result_panel(self)
        self._result.frame.grid(
            row=3, column=0, columnspan=2, sticky="nsew", padx=16, pady=(4, 0))

        self._footer = build_footer(
            self,
            on_save=self._save_txt,
            on_theme_change=theme_mgr.apply,
            current_mode=self._config.get("appearance_mode", "Dark"),
        )
        self._footer.frame.grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 14))

        self._sync_bodies()

    def _build_pbx_bodies(self) -> None:
        """Обидва тіла панелі АТС створюються один раз; перемикання — grid/grid_remove."""
        body = self._pbx_panel.body

        self._pbx_manual_frame = ctk.CTkFrame(body, fg_color="transparent")
        self._pbx_manual_frame.grid_columnconfigure(0, weight=1)
        self._pbx_manual_frame.grid_rowconfigure((0, 1), weight=1)

        self._online = build_input_panel(
            self._pbx_manual_frame,
            title_text="🟢  ONLINE  (вставте з FreePBX)",
            accent_key="green",
            on_clear=self._clear_online,
        )
        self._online.frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))

        self._offline = build_input_panel(
            self._pbx_manual_frame,
            title_text="🔴  OFFLINE  (вставте з FreePBX)",
            accent_key="red",
            on_clear=self._clear_offline,
        )
        self._offline.frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        self._pbx_auto = build_auto_body(body)

    def _build_table_bodies(self) -> None:
        """Аналогічно для панелі таблиці."""
        body = self._table_panel.body
        self._table_manual = build_table_manual_body(
            body, path_var=self.xlsx_path, on_browse=self._pick_xlsx)
        self._table_auto = build_auto_body(body)

    def _sync_bodies(self) -> None:
        """Показує тіло, що відповідає поточному режиму кожної панелі, і оновлює тексти."""
        pbx_auto = self._config.get("pbx_mode", "manual") == "auto"
        table_auto = self._config.get("table_mode", "manual") == "auto"

        for frame, visible in (
            (self._pbx_manual_frame, not pbx_auto),
            (self._pbx_auto.frame, pbx_auto),
            (self._table_manual.frame, not table_auto),
            (self._table_auto.frame, table_auto),
        ):
            if visible:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_remove()

        self._pbx_auto.target.configure(
            text=self._config.get("ari_url", "") or "— адресу ARI не вказано —")
        user = self._config.get("ari_user", "")
        if not user:
            self._pbx_auto.status.configure(
                text="Логін ARI не заповнений — відкрийте «Налаштування».")
        else:
            self._pbx_auto.status.configure(text=f"Користувач: {user}. Готово до запиту.")

        sheet_url = self._config.get("sheet_url", "").strip()
        self._table_auto.target.configure(
            text=sheet_url or "— посилання на таблицю не вказано —")
        if not sheet_url:
            self._table_auto.status.configure(
                text="Вкажіть посилання й API-ключ у «Налаштування».")
        elif not self._config.get("sheet_api_key", "").strip():
            self._table_auto.status.configure(
                text="API-ключ Google не заповнений — відкрийте «Налаштування».")
        else:
            self._table_auto.status.configure(text="Готово до запиту.")

        self._update_table_hint()

    def _update_table_hint(self) -> None:
        """Показує під полем шляху, який аркуш і колонки будуть використані."""
        sheet = self._config.get("table_sheet", "").strip()
        col_n = self._config.get("table_col_number", "F")
        col_s = self._config.get("table_col_status", "H")
        path = self.xlsx_path.get().strip()

        if sheet:
            sheet_text = f"аркуш «{sheet}»"
        else:
            detected = ""
            if path:
                try:
                    detected = detect_sheet(list_sheets(path))
                except Exception as e:
                    log.warning(f"Не вдалося прочитати список аркушів: {e}")
            sheet_text = (f"аркуш «{detected}» (авто)" if detected
                          else "аркуш: авто не визначився → активний")
        self._table_manual.hint.configure(
            text=f"Номер: {col_n}   ·   Статус: {col_s}   ·   {sheet_text}")

    # ═══════════════════════════════════════════
    #  ТЕМА
    # ═══════════════════════════════════════════

    def _on_theme_changed(self, mode: str, palette: dict) -> None:
        """
        Реакція на зміну теми (Варіант B). Дві речі:
          1) застосовує палітру до не-CTk фону вікна/фреймів (інакше Gray == Dark візуально);
          2) фіксує вибір у конфігу і за remember=True зберігає одразу.
        """
        try:
            self._apply_palette(mode, palette)
        except Exception as e:
            log.warning(f"Не вдалося застосувати палітру до вікна: {e}")
        self._config["appearance_mode"] = theme_mgr.current_mode
        if self._config.get("remember", False):
            config_manager.save_config(self._config)

    def _apply_palette(self, mode: str, palette: dict) -> None:
        """Розфарбовує віджети головної області під поточну палітру й акценти."""
        colors = status_colors(mode)
        self.configure(fg_color=palette["window_bg"])

        self._header.subtitle.configure(text_color=palette["text_dim"])

        for panel, accent_key in (
            (self._pbx_panel, "accent"),
            (self._table_panel, "green"),
        ):
            panel.frame.configure(fg_color=palette["frame_bg"])
            panel.title.configure(text_color=colors[accent_key])

        for panel, accent_key in ((self._online, "green"), (self._offline, "red")):
            panel.frame.configure(fg_color=palette["frame_top"])
            panel.textbox.configure(fg_color=palette["entry_bg"])
            panel.title.configure(text_color=colors[accent_key])
            panel.clear.configure(
                hover_color=palette["frame_bg"], text_color=palette["text_dim"])

        self._table_manual.entry.configure(fg_color=palette["entry_bg"])
        self._table_manual.btn_browse.configure(fg_color=palette["frame_top"])
        self._table_manual.hint.configure(text_color=palette["text_dim"])
        for auto in (self._pbx_auto, self._table_auto):
            auto.target.configure(text_color=palette["text"])
            auto.status.configure(text_color=palette["text_dim"])

        self._actions.btn_settings.configure(fg_color=palette["frame_top"])
        self._result.textbox.configure(fg_color=palette["entry_bg"])
        self._result.status.configure(text_color=colors[self._status_tag])
        self._footer.btn_save.configure(fg_color=palette["frame_top"])

        self._apply_result_tags(mode, palette)

    def _apply_result_tags(self, mode: str, palette: dict) -> None:
        """
        Зіставляє теги звіту з кольорами теми (теги задає formatters/result_formatter).

        Тег "bold" виділяє колонку номера. Жирний ШРИФТ тут задати не можна:
        CTkTextbox.tag_config() свідомо забороняє опцію 'font' (сирий кортеж не пройшов би
        DPI-масштабування CTk і жирні рядки мали б інший розмір за решту тексту).
        Тому виділення робиться основним кольором тексту.
        """
        colors = status_colors(mode)
        box = self._result.textbox
        box.tag_config("dim", foreground=palette["text_dim"])
        box.tag_config("accent", foreground=colors["accent"])
        box.tag_config("green", foreground=colors["green"])
        box.tag_config("red", foreground=colors["red"])
        box.tag_config("yellow", foreground=colors["yellow"])
        box.tag_config("bold", foreground=palette["text"])

    # ═══════════════════════════════════════════
    #  РЕЖИМИ ДЖЕРЕЛ
    # ═══════════════════════════════════════════

    def _on_pbx_mode(self, label: str) -> None:
        """Перемикач АТС. Незалежний від перемикача таблиці."""
        self._config["pbx_mode"] = mode_key(label)
        log.info(f"Режим АТС: {self._config['pbx_mode']}")
        self._sync_bodies()
        self._persist()

    def _on_table_mode(self, label: str) -> None:
        """Перемикач таблиці. Незалежний від перемикача АТС."""
        self._config["table_mode"] = mode_key(label)
        log.info(f"Режим таблиці: {self._config['table_mode']}")
        self._sync_bodies()
        self._persist()

    def _persist(self) -> None:
        """Запис конфігу за remember=True — рішення власника конфігу, не віджетів."""
        if self._config.get("remember", False):
            config_manager.save_config(self._config)

    # ═══════════════════════════════════════════
    #  ОБРОБНИКИ ПОДІЙ
    # ═══════════════════════════════════════════

    def _clear_online(self) -> None:
        self._online.textbox.delete("1.0", "end")

    def _clear_offline(self) -> None:
        self._offline.textbox.delete("1.0", "end")

    def _pick_xlsx(self) -> None:
        """Вибір файлу таблиці телефонів."""
        path = filedialog.askopenfilename(
            parent=self,
            title="Оберіть файл таблиці телефонів",
            filetypes=[("Excel файли", "*.xlsx *.xls"), ("Всі файли", "*.*")],
        )
        if path:
            self.xlsx_path.set(path)
            self._config["xlsx_path"] = path
            log.info(f"Вибрано файл: {path}")
            self._update_table_hint()
            self._persist()

    def _open_settings(self) -> None:
        """Немодальне вікно налаштувань; після змін оновлюємо підказки на панелях."""
        show_settings(
            self, self._config,
            on_save=self._save_settings,
            on_check_updates=self.check_updates_now,
        )

    def _save_settings(self, config: dict) -> None:
        """Колбек вікна налаштувань: зберегти (за remember) і перемалювати підказки."""
        self._persist()
        self._sync_bodies()

    def _run(self) -> None:
        """
        Збирає дані з обох джерел і показує звіт.

        Мережа й читання великого .xlsx — у фоновому потоці (BackgroundTask), інакше
        вікно підморожується. Вміст текстових полів читаємо ЗАЗДАЛЕГІДЬ у GUI-потоці:
        Tk не потокобезпечний, звертатись до віджетів із фонового потоку не можна.
        """
        table_auto = self._config.get("table_mode", "manual") == "auto"
        pbx_auto = self._config.get("pbx_mode", "manual") == "auto"

        if table_auto and not self._config.get("sheet_url", "").strip():
            messagebox.showwarning(
                "Таблиця не налаштована",
                "Вкажіть посилання на Google-таблицю та API-ключ "
                "у «⚙ Налаштування».", parent=self)
            return

        path = self.xlsx_path.get().strip()
        if not table_auto and not path:
            messagebox.showwarning(
                "Таблиця не вибрана",
                "Виберіть файл Excel (.xlsx) або перемкніть таблицю в авто-режим.",
                parent=self)
            return

        online_text = self._online.textbox.get("1.0", "end").strip()
        offline_text = self._offline.textbox.get("1.0", "end").strip()
        if not pbx_auto and not online_text and not offline_text:
            messagebox.showwarning(
                "Немає даних",
                "Вставте номери в поля Online або Offline, "
                "або перемкніть FreePBX в авто-режим.", parent=self)
            return

        config = dict(self._config)   # знімок: фоновий потік не читає живий конфіг

        def work():
            if table_auto:
                table = read_sheet(
                    config.get("sheet_url", ""), config.get("sheet_api_key", ""),
                    config.get("table_sheet", ""),
                    config.get("table_col_number", "F"), config.get("table_col_status", "H"))
            else:
                table = read_xlsx(
                    path, config.get("table_sheet", ""),
                    config.get("table_col_number", "F"), config.get("table_col_status", "H"))

            if pbx_auto:
                pbx = read_ari(
                    config.get("ari_url", ""), config.get("ari_user", ""),
                    config.get("ari_password", ""), bool(config.get("ari_insecure_tls", False)))
            else:
                pbx = read_manual(online_text, offline_text)

            return compare(table, pbx), pbx_auto

        BackgroundTask(
            root=self, label="Збираю дані…", btn_lock=[self._actions.btn_run],
        ).run(work=work, on_done=self._on_run_done, on_error=self._on_run_error)

    def _on_run_done(self, payload) -> None:
        """Успіх фонової задачі: (Comparison, чи вичерпні дані АТС)."""
        result, pbx_complete = payload
        self._show_result(result, pbx_complete)
        if self._config.get("table_mode", "manual") == "auto":
            self._table_auto.status.configure(
                text=f"Отримано {result.table_count} номерів "
                     f"({datetime.now().strftime('%H:%M:%S')}).")
        if self._config.get("pbx_mode", "manual") == "auto":
            self._pbx_auto.status.configure(
                text=f"Отримано {result.pbx_count} номерів "
                     f"({datetime.now().strftime('%H:%M:%S')}).")

    def _on_run_error(self, exc: Exception) -> None:
        """Помилка фонової задачі. AriError і NotImplementedError мають готовий текст."""
        if isinstance(exc, AriError):
            log.error(f"ARI: {exc}")
            self._pbx_auto.status.configure(text=f"Помилка: {exc}")
            messagebox.showerror("Не вдалося отримати дані з АТС", str(exc), parent=self)
        elif isinstance(exc, SheetsError):
            log.error(f"Google Sheets: {exc}")
            self._table_auto.status.configure(text=f"Помилка: {exc}")
            messagebox.showerror("Не вдалося прочитати Google-таблицю", str(exc), parent=self)
        elif isinstance(exc, NotImplementedError):
            messagebox.showinfo("Режим недоступний", str(exc), parent=self)
        else:
            log.error(f"Помилка порівняння: {exc}", exc_info=True)
            messagebox.showerror("Помилка", str(exc), parent=self)

    def _show_result(self, result, pbx_complete: bool) -> None:
        """Виводить кольоровий звіт і готує плаский текст для збереження."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        box = self._result.textbox
        box.configure(state="normal")
        box.delete("1.0", "end")
        for text, tag in build_segments(result, now, pbx_complete):
            box.insert("end", text, tag)
        box.configure(state="disabled")

        label, tag = build_status_label(result, pbx_complete)
        self._status_tag = tag
        self._result.status.configure(
            text=label, text_color=status_colors(theme_mgr.resolved_mode)[tag])

        self._last_result_txt = build_plain_text(result, now, pbx_complete)
        self._footer.btn_save.configure(state="normal")
        log.info(f"Результат відображено. Змін: {len(result.changes)}.")

    def _save_txt(self) -> None:
        """Зберігає останній звіт у .txt."""
        if not self._last_result_txt:
            return
        now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Зберегти результат",
            initialfile=f"phones_changes_{now_str}.txt",
            defaultextension=".txt",
            filetypes=[("Текстовий файл", "*.txt"), ("Всі файли", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._last_result_txt)
            log.info(f"Результат збережено: {path}")
            messagebox.showinfo("Збережено", f"Файл збережено:\n{path}", parent=self)
        except Exception as e:
            log.error(f"Помилка збереження: {e}", exc_info=True)
            messagebox.showerror("Помилка", str(e), parent=self)

    # ═══════════════════════════════════════════
    #  ОНОВЛЕННЯ
    # ═══════════════════════════════════════════

    def _load_initial_state(self) -> None:
        """Відновлює стан із конфігу. Запускає автоперевірку оновлень, якщо пора."""
        if should_check_now(self._config):
            self.after(2000, self._check_updates)   # 2с після старту — не гальмує запуск

    def check_updates_now(self) -> None:
        """
        РУЧНА перевірка оновлень — публічний хук для кнопки в налаштуваннях.

        Відрізняється від автоперевірки одним, але принциповим: користувач ОБОВ'ЯЗКОВО
        отримує відповідь — включно з «у вас найновіша версія» і текстом помилки.
        Мовчанка у відповідь на натиснуту кнопку читається як «програма зламалась».
        """
        self._check_updates(manual=True)

    def _check_updates(self, manual: bool = False) -> None:
        """
        Перевіряє оновлення у фоні. Колбеки повертаються у GUI-потік через after(0, ...).

        Момент перевірки фіксуємо ДО запиту й незалежно від результату: інакше програма
        без мережі била б по API при кожному запуску, ігноруючи обраний інтервал.
        """
        mark_checked(self._config)
        self._persist()
        check_for_updates(
            on_update_found=lambda info: self.after(
                0, lambda: show_update_dialog(self, info, on_ready_to_exit=self._request_shutdown)
            ),
            on_no_update=(lambda: self.after(0, self._on_no_update)) if manual else None,
            on_error=((lambda msg: self.after(0, self._on_check_error, msg)) if manual
                      else (lambda msg: log.warning(f"Перевірка оновлень: {msg}"))),
        )

    def _request_shutdown(self) -> None:
        """
        Callback для `core.updater.launch_update` — кличеться З ФОНОВОГО ПОТОКУ.

        `core/` не знає про Tkinter, тож маршалінг у GUI-потік — відповідальність
        викликача, той самий принцип, що вже діє для `on_progress`.
        """
        self.after(0, self._on_closing)

    def _on_no_update(self) -> None:
        """Тільки для ручної перевірки — автоматична мовчить свідомо."""
        messagebox.showinfo(
            "Оновлень немає",
            f"Встановлено найновішу версію — {build_info.APP_VERSION}.", parent=self,
        )

    def _on_check_error(self, message: str) -> None:
        log.warning(f"Перевірка оновлень: {message}")
        messagebox.showwarning(
            "Не вдалося перевірити оновлення",
            f"{message}\n\nПеревірте з'єднання або спробуйте пізніше.",
            parent=self,
        )

    # ═══════════════════════════════════════════
    #  СТАН І ЗАКРИТТЯ
    # ═══════════════════════════════════════════

    def _restore_geometry(self, saved_geometry: str = "") -> None:
        """Відновлює розмір/позицію з конфігу; без збереженого — центрує вікно."""
        self.update_idletasks()
        if saved_geometry:
            try:
                self.geometry(saved_geometry)
                return
            except Exception as e:
                log.warning(f"Некоректна збережена геометрія '{saved_geometry}': {e}")
        w, h = _DEFAULT_SIZE
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _on_closing(self) -> None:
        """
        ЄДИНА точка виходу з програми. Ідемпотентна.

        Без прапорця закриття під час оновлення (яке саме викликає цей метод через
        `_request_shutdown`) могло пройти вдруге — WM_DELETE_WINDOW і колбек апдейтера
        цілком можуть накластись у часі.
        """
        if self._closing:
            return
        self._closing = True

        log.info("Ініційовано закриття програми.")
        unsubscribe(Events.THEME_CHANGED, self._on_theme_changed)
        self._ctx.destroy()

        self._config["xlsx_path"] = self.xlsx_path.get()
        self._config["window_geometry"] = self.geometry()
        if self._config.get("remember", False):
            config_manager.save_config(self._config)
        else:
            config_manager.delete_config()

        log.info("Програма завершує роботу.")
        self.destroy()
