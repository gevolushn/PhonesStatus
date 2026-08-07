"""
app_window.py — головне вікно програми порівняння статусів телефонів.

Порядок __init__ є критичним:
    1. Параметри вікна
    2. GUI-елементи (build_*)
    3. Hotkeys і контекстне меню
    4. subscribe + theme_mgr.load() — ПІСЛЯ всіх віджетів (щоб перший emit дійшов до всіх)
    5. Відновлення геометрії + _load_initial_state()
    6. WM_DELETE_WINDOW

Вікно тримає лише UI і реакції на дії користувача. Читання таблиці й тексту з FreePBX —
у parsers/, порівняння — у parsers/comparator.py, формування звіту — у
formatters/result_formatter.py. Алгоритмів тут немає.
"""
from datetime import datetime
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.logger import log
from core import config_manager
from core.events import subscribe, unsubscribe, Events
from core.updater import check_for_updates
import core.build_info as build_info
from gui.widgets import (
    build_control_bar,
    build_footer,
    build_header,
    build_input_panel,
    build_result_panel,
    status_colors,
)
from gui.hotkeys import bind_to_all
from gui.context_menu import AppContextMenu
from gui.theme import theme_mgr
from gui.update_dialog import show_update_dialog
from parsers.xlsx_parser import read_xlsx, parse_text_block
from parsers.comparator import compare
from formatters.result_formatter import (
    build_plain_text,
    build_segments,
    build_status_label,
)

_DEFAULT_SIZE: tuple[int, int] = (920, 680)
_MIN_SIZE: tuple[int, int] = (880, 640)


class AppWindow(ctk.CTk):
    """Головне вікно CTk. Уся логіка подій програми."""

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config
        self._last_result_txt = ""
        self._status_tag = "green"          # тег кольору поточного рядка статусу

        self.title(build_info.APP_NAME)
        self.minsize(*_MIN_SIZE)
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)   # панелі вводу
        self.grid_rowconfigure(3, weight=2)   # панель результату

        self.xlsx_path = ctk.StringVar(value=config.get("xlsx_path", ""))

        self._build_ui()

        self._ctx = AppContextMenu(self)
        editable = [self._online.textbox, self._offline.textbox, self._control.entry]
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

        self._online = build_input_panel(
            self,
            title_text="🟢  ONLINE  (вставте з FreePBX)",
            accent_key="green",
            on_clear=self._clear_online,
        )
        self._online.frame.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 4))

        self._offline = build_input_panel(
            self,
            title_text="🔴  OFFLINE  (вставте з FreePBX)",
            accent_key="red",
            on_clear=self._clear_offline,
        )
        self._offline.frame.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 4))

        self._control = build_control_bar(
            self, path_var=self.xlsx_path, on_browse=self._pick_xlsx, on_run=self._run)
        self._control.frame.grid(
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

        for panel, accent_key in ((self._online, "green"), (self._offline, "red")):
            panel.frame.configure(fg_color=palette["frame_bg"])
            panel.textbox.configure(fg_color=palette["entry_bg"])
            panel.title.configure(text_color=colors[accent_key])
            panel.clear.configure(
                hover_color=palette["frame_top"], text_color=palette["text_dim"])

        self._control.entry.configure(fg_color=palette["entry_bg"])
        self._control.btn_browse.configure(fg_color=palette["frame_top"])

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
        Тому виділення робиться основним кольором тексту — саме ним номер і виглядав
        у попередній версії, решта колонок лишається приглушеною або акцентною.
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
            log.info(f"Вибрано файл: {path}")

    def _run(self) -> None:
        """Читає таблицю й вставлені блоки FreePBX, порівнює статуси, показує звіт."""
        path = self.xlsx_path.get().strip()
        online_text = self._online.textbox.get("1.0", "end").strip()
        offline_text = self._offline.textbox.get("1.0", "end").strip()

        if not path:
            messagebox.showwarning(
                "Таблиця не вибрана",
                "Будь ласка, виберіть файл Excel (.xlsx).", parent=self)
            return
        if not online_text and not offline_text:
            messagebox.showwarning(
                "Немає даних",
                "Вставте номери в поля Online або Offline.", parent=self)
            return

        try:
            xlsx_phones = read_xlsx(path)
        except Exception as e:
            log.error(f"Помилка читання Excel: {e}", exc_info=True)
            messagebox.showerror("Помилка читання Excel", str(e), parent=self)
            return

        online_nums = parse_text_block(online_text)
        offline_nums = parse_text_block(offline_text)

        try:
            changes, pbx = compare(xlsx_phones, online_nums, offline_nums)
        except Exception as e:
            log.error(f"Помилка порівняння: {e}", exc_info=True)
            messagebox.showerror("Помилка порівняння", str(e), parent=self)
            return

        self._show_result(changes, xlsx_phones, pbx)

    def _show_result(self, changes: list, xlsx_phones: dict, pbx: dict) -> None:
        """Виводить кольоровий звіт і готує плаский текст для збереження."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        box = self._result.textbox
        box.configure(state="normal")
        box.delete("1.0", "end")
        for text, tag in build_segments(changes, xlsx_phones, pbx, now):
            box.insert("end", text, tag)
        box.configure(state="disabled")

        label, tag = build_status_label(changes)
        self._status_tag = tag
        self._result.status.configure(
            text=label, text_color=status_colors(theme_mgr.resolved_mode)[tag])

        self._last_result_txt = build_plain_text(changes, xlsx_phones, pbx, now)
        self._footer.btn_save.configure(state="normal")
        log.info(f"Результат відображено. Змін: {len(changes)}.")

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
    #  СТАН І ЗАКРИТТЯ
    # ═══════════════════════════════════════════

    def _load_initial_state(self) -> None:
        """Відновлює стан із конфігу. Запускає перевірку оновлень, якщо увімкнена."""
        if self._config.get("check_updates", False):
            self.after(2000, self._check_updates)   # 2с після старту — не гальмує запуск

    def _check_updates(self) -> None:
        """Перевіряє оновлення у фоні. Показує діалог, якщо є нова версія."""
        check_for_updates(
            on_update_found=lambda info: self.after(0, lambda: show_update_dialog(self, info)),
            on_error=lambda msg: log.warning(f"Перевірка оновлень: {msg}"),
        )

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
        """Зберігає стан (або видаляє конфіг за remember=False) і закриває вікно."""
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
