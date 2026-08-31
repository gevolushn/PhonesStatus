"""
widgets.py — створення та розміщення GUI-елементів. Тільки layout і стилі.
Ніякої бізнес-логіки.

⚠️ Інваріант теми Gray (фікс прихованої крихкості):
Режим "Gray" мапиться у CTk appearance "Dark", тож CTk-віджети самі беруть ТЕМНУ
палітру, а не сіру. Щоб віджети у головній області відповідали палітрі теми, створюй
їх через фабрики make_* нижче (вони підставляють fg_color з PALETTE), або явно
передавай fg_color із theme_mgr.get_palette(). Інакше кнопки/поля виглядатимуть
темнішими за сірий фон.

Акцентні кольори статусів (ON / OFF / попередження) палітра шаблону не описує —
вони живуть у STATUS_COLORS нижче, окремим набором на кожен режим теми.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

import customtkinter as ctk

from core.events import subscribe, Events

# Готові акценти для кольорових кнопок (копіювати при потребі):
_BTN_BLUE    = {"fg_color": "#1f538d", "hover_color": "#14375e"}
_BTN_GREEN   = {"fg_color": "#2d7a2d", "hover_color": "#1a5c1a"}
_BTN_RED     = {"fg_color": "#8d1f1f", "hover_color": "#5e1414"}
_BTN_ORANGE  = {"fg_color": "#8d5a1f", "hover_color": "#5e3a0f"}
_BTN_NEUTRAL: dict = {}

_MODE_LABELS: dict[str, str] = {
    "Light":  "☀  Світла",
    "Gray":   "🌥  Сіра",
    "Dark":   "🌙  Темна",
    "System": "⚙  Система",
}
_LABEL_TO_MODE: dict[str, str] = {v: k for k, v in _MODE_LABELS.items()}

# ─── Акценти статусів по режимах теми ─────────────────────────────────────────
# Темні режими беруть палітру попередньої версії програми (One Dark); для світлої
# теми ті самі кольори нечитабельні на білому — узято темніші відповідники.
STATUS_COLORS: dict[str, dict[str, str]] = {
    "Light": {"green": "#2e7d32", "red": "#c62828", "yellow": "#b26a00", "accent": "#1565c0"},
    "Gray":  {"green": "#98c379", "red": "#e06c75", "yellow": "#e5c07b", "accent": "#61afef"},
    "Dark":  {"green": "#98c379", "red": "#e06c75", "yellow": "#e5c07b", "accent": "#61afef"},
}
_DEFAULT_STATUS_MODE: str = "Dark"

_FONT_UI = ("Segoe UI", 13)
_FONT_MONO = "Consolas"

# Шрифт поля результату — звіт вирівняний пробілами, тож моноширинний обов'язковий.
RESULT_FONT: tuple[str, int] = (_FONT_MONO, 13)


def status_colors(mode: str) -> dict[str, str]:
    """Акцентні кольори (green/red/yellow/accent) для заданого resolved-режиму теми."""
    return STATUS_COLORS.get(mode, STATUS_COLORS[_DEFAULT_STATUS_MODE])


def _palette() -> dict[str, str]:
    """Палітра поточної теми (для інваріанту Gray у фабриках)."""
    from gui.theme import theme_mgr
    return theme_mgr.get_palette()


# ─── Фабрики з палітрою теми (інваріант Gray) ─────────────────────────────────

def make_frame(parent, **kw) -> ctk.CTkFrame:
    """CTkFrame із fg_color з палітри теми (за замовчуванням frame_bg)."""
    kw.setdefault("fg_color", _palette()["frame_bg"])
    return ctk.CTkFrame(parent, **kw)


def make_button(parent, text: str, **kw) -> ctk.CTkButton:
    """CTkButton із нейтральним fg_color з палітри (передай _BTN_* для акценту)."""
    kw.setdefault("fg_color", _palette()["frame_top"])
    return ctk.CTkButton(parent, text=text, **kw)


def make_entry(parent, **kw) -> ctk.CTkEntry:
    """CTkEntry із fg_color з палітри теми (entry_bg)."""
    kw.setdefault("fg_color", _palette()["entry_bg"])
    return ctk.CTkEntry(parent, **kw)


# ─── Складові головного вікна ─────────────────────────────────────────────────

class Header(NamedTuple):
    """Шапка вікна: назва програми + підзаголовок про джерела даних."""
    frame:    ctk.CTkFrame
    title:    ctk.CTkLabel
    subtitle: ctk.CTkLabel


class InputPanel(NamedTuple):
    """Панель вставки номерів із FreePBX (Online або Offline)."""
    frame:   ctk.CTkFrame
    title:   ctk.CTkLabel
    clear:   ctk.CTkButton
    textbox: ctk.CTkTextbox


class SourcePanel(NamedTuple):
    """
    Панель одного джерела даних із власним перемикачем Ручний/Авто.

    `body` — порожній контейнер, який наповнює викликач: два різні набори віджетів
    (ручний і авто) створюються один раз і показуються/ховаються через grid/grid_remove,
    а не перестворюються на кожне перемикання.
    """
    frame:  ctk.CTkFrame
    title:  ctk.CTkLabel
    switch: ctk.CTkSegmentedButton
    body:   ctk.CTkFrame


class TableManualBody(NamedTuple):
    """Ручний режим таблиці: шлях до .xlsx + «Огляд…» + підказка про розкладку."""
    frame:      ctk.CTkFrame
    entry:      ctk.CTkEntry
    btn_browse: ctk.CTkButton
    hint:       ctk.CTkLabel


class AutoBody(NamedTuple):
    """Авто-режим будь-якого джерела: рядок цілі + рядок стану останнього запиту."""
    frame:  ctk.CTkFrame
    target: ctk.CTkLabel
    status: ctk.CTkLabel


class ActionBar(NamedTuple):
    """Рядок дій: «Порівняти» + «Налаштування»."""
    frame:        ctk.CTkFrame
    btn_run:      ctk.CTkButton
    btn_settings: ctk.CTkButton


class ResultPanel(NamedTuple):
    """Панель результату: заголовок, короткий статус і текст звіту (readonly)."""
    frame:   ctk.CTkFrame
    title:   ctk.CTkLabel
    status:  ctk.CTkLabel
    textbox: ctk.CTkTextbox


class Footer(NamedTuple):
    """Нижній рядок: перемикач теми ліворуч, «Зберегти TXT» праворуч."""
    frame:    ctk.CTkFrame
    switcher: ctk.CTkOptionMenu
    btn_save: ctk.CTkButton


def build_header(parent: ctk.CTkBaseClass) -> Header:
    """Шапка вікна. Кольори підзаголовка/назви застосовує підписник теми."""
    palette = _palette()
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(2, weight=1)

    title = ctk.CTkLabel(
        frame, text="📞  Phones Status",
        font=ctk.CTkFont(family=_FONT_UI[0], size=18, weight="bold"), anchor="w",
    )
    title.grid(row=0, column=0, sticky="w")

    subtitle = ctk.CTkLabel(
        frame, text="FreePBX  ↔  Таблиця Excel",
        font=ctk.CTkFont(family=_FONT_UI[0], size=12), anchor="w",
        text_color=palette["text_dim"],
    )
    subtitle.grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(4, 0))
    return Header(frame=frame, title=title, subtitle=subtitle)


def build_input_panel(
    parent: ctk.CTkBaseClass,
    *,
    title_text: str,
    accent_key: str,
    on_clear: Callable[[], None],
) -> InputPanel:
    """
    Панель із заголовком, кнопкою «очистити» і полем вставки номерів.

    accent_key — ключ у STATUS_COLORS ("green" для Online, "red" для Offline);
    фактичний колір застосовує підписник теми в app_window.
    """
    palette = _palette()
    frame = make_frame(parent)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)

    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
    head.grid_columnconfigure(0, weight=1)

    title = ctk.CTkLabel(
        head, text=title_text,
        font=ctk.CTkFont(family=_FONT_UI[0], size=13, weight="bold"), anchor="w",
        text_color=status_colors(_current_mode())[accent_key],
    )
    title.grid(row=0, column=0, sticky="w")

    clear = ctk.CTkButton(
        head, text="✕ очистити", command=on_clear,
        width=90, height=24, corner_radius=6,
        font=ctk.CTkFont(family=_FONT_UI[0], size=11),
        fg_color="transparent", hover_color=palette["frame_top"],
        text_color=palette["text_dim"],
    )
    clear.grid(row=0, column=1, sticky="e")

    textbox = ctk.CTkTextbox(
        frame, font=ctk.CTkFont(family=_FONT_MONO, size=12),
        undo=True, wrap="none", fg_color=palette["entry_bg"],
    )
    textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    return InputPanel(frame=frame, title=title, clear=clear, textbox=textbox)


MODE_MANUAL: str = "Ручний"
MODE_AUTO: str = "Авто"
_MODE_TO_KEY: dict[str, str] = {MODE_MANUAL: "manual", MODE_AUTO: "auto"}
_KEY_TO_MODE: dict[str, str] = {v: k for k, v in _MODE_TO_KEY.items()}


def mode_key(label: str) -> str:
    """Підпис перемикача -> значення для конфігу ("manual"/"auto")."""
    return _MODE_TO_KEY.get(label, "manual")


def mode_label(key: str) -> str:
    """Значення з конфігу -> підпис перемикача."""
    return _KEY_TO_MODE.get(key, MODE_MANUAL)


def build_source_panel(
    parent: ctk.CTkBaseClass,
    *,
    title_text: str,
    accent_key: str,
    current_mode: str,
    on_mode_change: Callable[[str], None],
) -> SourcePanel:
    """
    Панель джерела: заголовок + перемикач Ручний/Авто у шапці, порожнє тіло під ним.

    Перемикачі двох панелей НЕЗАЛЕЖНІ - свідомо: типовий робочий сценарій це
    авто-АТС + ручна таблиця, поки Google Sheets не підключений.
    """
    frame = make_frame(parent)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)

    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
    head.grid_columnconfigure(0, weight=1)

    title = ctk.CTkLabel(
        head, text=title_text,
        font=ctk.CTkFont(family=_FONT_UI[0], size=13, weight="bold"), anchor="w",
        text_color=status_colors(_current_mode())[accent_key],
    )
    title.grid(row=0, column=0, sticky="w")

    switch = ctk.CTkSegmentedButton(
        head, values=[MODE_MANUAL, MODE_AUTO], command=on_mode_change,
        height=26, font=ctk.CTkFont(family=_FONT_UI[0], size=11), width=150,
    )
    switch.set(mode_label(current_mode))
    switch.grid(row=0, column=1, sticky="e")

    body = ctk.CTkFrame(frame, fg_color="transparent")
    body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(0, weight=1)
    return SourcePanel(frame=frame, title=title, switch=switch, body=body)


def build_table_manual_body(
    parent: ctk.CTkBaseClass,
    *,
    path_var: ctk.StringVar,
    on_browse: Callable[[], None],
) -> TableManualBody:
    """Тіло ручного режиму таблиці: поле шляху, кнопка огляду, підказка про колонки."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)

    entry = make_entry(frame, textvariable=path_var, height=32)
    entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

    btn_browse = make_button(frame, "Огляд...", command=on_browse, width=100, height=32)
    btn_browse.grid(row=0, column=1)

    hint = ctk.CTkLabel(
        frame, text="", anchor="w", justify="left",
        font=ctk.CTkFont(family=_FONT_UI[0], size=11),
    )
    hint.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    return TableManualBody(frame=frame, entry=entry, btn_browse=btn_browse, hint=hint)


def build_auto_body(parent: ctk.CTkBaseClass) -> AutoBody:
    """Тіло авто-режиму: куди ходимо і що відповіло минулого разу."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)

    target = ctk.CTkLabel(
        frame, text="", anchor="w", justify="left",
        font=ctk.CTkFont(family=_FONT_MONO, size=11),
    )
    target.grid(row=0, column=0, sticky="ew")

    status = ctk.CTkLabel(
        frame, text="", anchor="w", justify="left", wraplength=380,
        font=ctk.CTkFont(family=_FONT_UI[0], size=11),
    )
    status.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    return AutoBody(frame=frame, target=target, status=status)


def build_action_bar(
    parent: ctk.CTkBaseClass,
    *,
    on_run: Callable[[], None],
    on_settings: Callable[[], None],
) -> ActionBar:
    """Рядок дій під панелями джерел."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)

    btn_settings = make_button(
        frame, "⚙  Налаштування", command=on_settings, width=170, height=32)
    btn_settings.grid(row=0, column=0, sticky="w")

    btn_run = ctk.CTkButton(
        frame, text="▶  Порівняти", command=on_run, width=170, height=32,
        font=ctk.CTkFont(family=_FONT_UI[0], size=13, weight="bold"), **_BTN_BLUE,
    )
    btn_run.grid(row=0, column=1, sticky="e")
    return ActionBar(frame=frame, btn_run=btn_run, btn_settings=btn_settings)


def build_result_panel(parent: ctk.CTkBaseClass) -> ResultPanel:
    """Панель результату — нередаговане текстове поле з кольоровими тегами."""
    palette = _palette()
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(1, weight=1)
    frame.grid_rowconfigure(1, weight=1)

    title = ctk.CTkLabel(
        frame, text="📋  Результат",
        font=ctk.CTkFont(family=_FONT_UI[0], size=14, weight="bold"), anchor="w",
    )
    title.grid(row=0, column=0, sticky="w", pady=(0, 4))

    status = ctk.CTkLabel(
        frame, text="", font=ctk.CTkFont(family=_FONT_UI[0], size=12), anchor="w",
    )
    status.grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(0, 4))

    textbox = ctk.CTkTextbox(
        frame, font=ctk.CTkFont(family=RESULT_FONT[0], size=RESULT_FONT[1]),
        wrap="none", state="disabled", fg_color=palette["entry_bg"],
    )
    textbox.grid(row=1, column=0, columnspan=2, sticky="nsew")
    return ResultPanel(frame=frame, title=title, status=status, textbox=textbox)


def build_footer(
    parent: ctk.CTkBaseClass,
    *,
    on_save: Callable[[], None],
    on_theme_change: Callable[[str], None],
    current_mode: str = "Dark",
) -> Footer:
    """Нижній рядок: перемикач теми і кнопка збереження звіту."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(1, weight=1)

    switcher = build_theme_switcher(frame, on_change=on_theme_change, current_mode=current_mode)
    switcher.grid(row=0, column=0, sticky="w")

    btn_save = make_button(
        frame, "💾  Зберегти TXT", command=on_save, width=160, height=30, state="disabled",
    )
    btn_save.grid(row=0, column=2, sticky="e")
    return Footer(frame=frame, switcher=switcher, btn_save=btn_save)


def build_theme_switcher(
    parent: ctk.CTkBaseClass,
    on_change: Callable[[str], None],
    current_mode: str = "Dark",
) -> ctk.CTkOptionMenu:
    """Компактний перемикач теми. Синхронізується через Event Bus."""
    labels = list(_MODE_LABELS.values())
    var = ctk.StringVar(value=_MODE_LABELS.get(current_mode, _MODE_LABELS["Dark"]))

    def _on_select(label: str) -> None:
        mode = _LABEL_TO_MODE.get(label)
        if mode:
            on_change(mode)

    option_menu = ctk.CTkOptionMenu(
        parent, values=labels, variable=var, command=_on_select,
        width=140, height=28, corner_radius=6, dynamic_resizing=False, anchor="w",
    )

    def _on_theme_changed(mode: str, palette: dict) -> None:
        # РЕГРЕСІЯ D-15: підпис НЕ можна брати з параметра mode цієї події.
        # theme.py emit-ить resolved_mode (System резолвиться в Light/Dark) — саме
        # тому, що підписники (палітра тощо) не мають думати про System. Але це та
        # сама подія, на яку підписаний і сам перемикач: узявши з неї mode, він
        # миттєво перемикав власний підпис «Система» назад на «Темна» при виборі.
        # theme_mgr.current_mode — єдине місце, де "System" лишається "System".
        from gui.theme import theme_mgr
        new_label = _MODE_LABELS.get(theme_mgr.current_mode)
        if new_label and var.get() != new_label:
            var.set(new_label)

    # Тримаємо СИЛЬНЕ посилання на колбек і StringVar на самому віджеті: інакше
    # слабке посилання Event Bus зібрало б локальну функцію одразу після return
    # (підписка стала б тихим no-op). Живуть, доки живе option_menu.
    option_menu._theme_cb = _on_theme_changed  # type: ignore[attr-defined]
    option_menu._theme_var = var               # type: ignore[attr-defined]
    subscribe(Events.THEME_CHANGED, _on_theme_changed)
    return option_menu


def _current_mode() -> str:
    """Поточний resolved-режим теми (для стартових кольорів акцентів)."""
    from gui.theme import theme_mgr
    return theme_mgr.resolved_mode
