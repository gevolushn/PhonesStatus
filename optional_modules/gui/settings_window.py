"""
settings_window.py — вікно налаштувань за замовчуванням. ОПЦІЙНИЙ модуль.

Підключати, коли програмі треба дати користувачеві керування темою, режимом «без слідів»
і частотою перевірки оновлень без правки `data/settings.json` руками.

Залежності: немає (понад customtkinter).

Три рішення, які варто розуміти перед правками:

1. **Зміни застосовуються ОДРАЗУ, кнопки «Скасувати» немає.** Тема в шаблоні й так
   перемикається миттєво (`theme_mgr.apply` емітить подію на все вікно) — відкотити її
   «Скасуванням» не вийшло б, і вийшла б класична напівправда: частину полів кнопка
   повертає, частину ні. Тому модель одна для всіх полів: змінив — застосувалось.

2. **Вікно не володіє конфігом.** Воно мутує переданий dict і кличе `on_save`; рішення
   «зберігати чи ні» лишається за власником (у режимі `remember=False` конфіг свідомо
   НЕ переживає вихід — вікно налаштувань не має права це порушити).

3. **Один екземпляр.** `show_settings()` повертає вже відкрите вікно замість другого:
   два вікна налаштувань писали б у той самий dict і затирали одне одного.

Не використовує `grab_set()` — як і `UpdateDialog`, головне вікно лишається активним.

Підключення: скопіювати у `gui/`, у `app_window.py` додати:
    from gui.settings_window import show_settings

    def _open_settings(self) -> None:
        show_settings(self, self._config, on_save=self._save_settings,
                      on_check_updates=self.check_updates_now)

    def _save_settings(self, config: dict) -> None:
        if config.get("remember", False):
            config_manager.save_config(config)
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import customtkinter as ctk

from core.events import subscribe, unsubscribe, Events
from core.logger import log
from core.updater import UPDATE_CHECK_MODES
import core.build_info as build_info
from gui.theme import theme_mgr
from gui.widgets import build_theme_switcher
from gui.window_utils import center_on_parent, get_instance, raise_window

# Підписи режимів автоперевірки. Порядок у GUI бере core.updater.UPDATE_CHECK_MODES —
# єдине джерело; тут лише людські назви.
_CHECK_LABELS: dict[str, str] = {
    "startup": "При кожному запуску",
    "daily":   "Раз на добу",
    "weekly":  "Раз на тиждень",
    "never":   "Не перевіряти",
}

_instance: "SettingsWindow | None" = None


def show_settings(
    parent: ctk.CTk,
    config: dict,
    on_save: Callable[[dict], None],
    on_check_updates: Callable[[], None] | None = None,
) -> "SettingsWindow":
    """Відкриває вікно налаштувань (або піднімає вже відкрите)."""
    global _instance
    existing = get_instance(_instance)
    if existing is not None:
        raise_window(existing)   # РЕГРЕСІЯ D-08: focus() не міняв z-order
        return existing
    _instance = SettingsWindow(parent, config, on_save, on_check_updates)
    raise_window(_instance)
    return _instance


class SettingsWindow(ctk.CTkToplevel):
    """Немодальне вікно налаштувань. Зміни застосовуються одразу."""

    def __init__(
        self,
        parent: ctk.CTk,
        config: dict,
        on_save: Callable[[dict], None],
        on_check_updates: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._config = config
        self._on_save = on_save
        self._on_check_updates = on_check_updates

        self.title("Налаштування")
        self.minsize(420, 340)   # менше за старе 480×560 — прокрутка бере решту (D-33)
        self.transient(parent)
        # grab_set() — СВІДОМО НЕ ВИКЛИКАЄМО (див. docstring модуля)

        self.grid_columnconfigure(0, weight=1)
        center_on_parent(self, self._parent, 460, 380)

        # Вміст — у CTkScrollableFrame, а не прямо на self (D-33). Шаблонне вікно з
        # двома розділами вміщується й так, але дефект з'являється рівно тоді, коли
        # ПРОЄКТ додає свої розділи — тобто в кожному реальному проєкті, і кожен ловив
        # би його наосліп: без прокрутки нижні розділи й кнопка «Закрити» недосяжні
        # НІЯКИМ способом, включно з розтягуванням вікна.
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        self._build_appearance()
        self._build_updates()
        self._build_footer()   # ПОЗА self._body — футер лишається закріпленим

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        subscribe(Events.THEME_CHANGED, self._on_theme)
        self._on_theme(mode=theme_mgr.resolved_mode, palette=theme_mgr.get_palette())

    # ── Секції ────────────────────────────────────────────────────────────────

    def _build_appearance(self) -> None:
        body = self._body
        ctk.CTkLabel(
            body, text="Вигляд", font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(16, 4), sticky="ew")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text="Тема:", anchor="w").grid(row=0, column=0, sticky="w")
        # Перевикористовуємо готовий перемикач: він сам синхронізується через Event Bus,
        # тож тема, змінена в головному вікні, оновить і це поле.
        switcher = build_theme_switcher(
            parent=row,
            on_change=theme_mgr.apply,
            current_mode=self._config.get("appearance_mode", "System"),
        )
        switcher.grid(row=0, column=1, sticky="e")

        self._remember_var = ctk.BooleanVar(value=bool(self._config.get("remember", False)))
        ctk.CTkCheckBox(
            body, text="Запам'ятовувати налаштування між запусками",
            variable=self._remember_var, command=self._on_remember_toggle,
        ).grid(row=2, column=0, padx=20, pady=(8, 0), sticky="w")
        ctk.CTkLabel(
            body, text="Вимкнено — конфіг і лог видаляються при виході («без слідів»).",
            font=ctk.CTkFont(size=11), text_color="gray60", anchor="w", wraplength=380,
            justify="left",
        ).grid(row=3, column=0, padx=(44, 20), pady=(2, 0), sticky="ew")

    def _build_updates(self) -> None:
        body = self._body
        ctk.CTkLabel(
            body, text="Оновлення", font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).grid(row=4, column=0, padx=20, pady=(18, 4), sticky="ew")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=5, column=0, padx=20, pady=(0, 4), sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text="Перевіряти:", anchor="w").grid(row=0, column=0, sticky="w")

        labels = [_CHECK_LABELS[m] for m in UPDATE_CHECK_MODES if m in _CHECK_LABELS]
        current = str(self._config.get("update_check", "startup"))
        if current not in _CHECK_LABELS:
            log.warning(f"Невідомий update_check='{current}' у конфігу → показую 'startup'.")
            current = "startup"
        self._check_var = ctk.StringVar(value=_CHECK_LABELS[current])
        ctk.CTkOptionMenu(
            row, values=labels, variable=self._check_var, command=self._on_check_mode,
            width=180, height=28, dynamic_resizing=False, anchor="w",
        ).grid(row=0, column=1, sticky="e")

        self._last_check_label = ctk.CTkLabel(
            body, text=self._last_check_text(), font=ctk.CTkFont(size=11),
            text_color="gray60", anchor="w",
        )
        self._last_check_label.grid(row=6, column=0, padx=20, pady=(4, 0), sticky="ew")

        if self._on_check_updates is not None:
            ctk.CTkButton(
                body, text="🔄  Перевірити зараз", command=self._on_check_click,
                width=180, fg_color="transparent", border_width=1,
            ).grid(row=7, column=0, padx=20, pady=(8, 0), sticky="w")

    def _build_footer(self) -> None:
        """Кнопка «Закрити» — на self, ПОЗА self._body: не має ховатись у прокрутці."""
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, padx=20, pady=16, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer, text=f"{build_info.APP_NAME}  ·  {build_info.APP_VERSION}",
            font=ctk.CTkFont(size=11), text_color="gray60", anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(footer, text="Закрити", command=self._on_close, width=100).grid(
            row=0, column=1, sticky="e",
        )

    # ── Реакції ───────────────────────────────────────────────────────────────

    def _on_remember_toggle(self) -> None:
        self._config["remember"] = bool(self._remember_var.get())
        log.info(f"Налаштування: remember={self._config['remember']}")
        self._apply()

    def _on_check_mode(self, label: str) -> None:
        for mode, text in _CHECK_LABELS.items():
            if text == label:
                self._config["update_check"] = mode
                log.info(f"Налаштування: update_check={mode}")
                self._apply()
                return

    def _on_check_click(self) -> None:
        if self._on_check_updates is None:
            return
        self._on_check_updates()
        # Момент перевірки ставить сам updater (mark_checked) — просто перечитуємо.
        self._last_check_label.configure(text=self._last_check_text())

    def _apply(self) -> None:
        """Віддає рішення про збереження власнику конфігу (див. п.2 у docstring)."""
        try:
            self._on_save(self._config)
        except Exception as e:
            log.error(f"Не вдалося застосувати налаштування: {e}", exc_info=True)

    # ── Допоміжне ─────────────────────────────────────────────────────────────

    def _last_check_text(self) -> str:
        raw = str(self._config.get("last_update_check", "")).strip()
        if not raw:
            return "Ще не перевірялось."
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            return "Остання перевірка: невідомо."
        return f"Остання перевірка: {when.strftime('%d.%m.%Y %H:%M')}"

    def _on_theme(self, mode: str, palette: dict) -> None:
        # CTk-віджети appearance_mode підхоплюють самі, але фон Toplevel за палітрою
        # (важливо для Gray, де CTk-режим == Dark) треба застосувати вручну. Фон
        # прокрутки — окремо: CTkScrollableFrame не йде за PALETTE сам, інакше на темі
        # Gray вміст лежить на іншому відтінку, ніж вікно.
        try:
            self.configure(fg_color=palette["window_bg"])
            self._body.configure(fg_color=palette["window_bg"])
        except Exception:
            pass  # вікно могло бути вже знищене — не критично

    def _on_close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        global _instance
        unsubscribe(Events.THEME_CHANGED, self._on_theme)
        _instance = None
        super().destroy()
