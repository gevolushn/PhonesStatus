"""
hotkeys.py — Ctrl+C/V/X/A/Z для всіх полів.
Fallback через keycode для кирилиці (розкладка UA/RU).
"""
import tkinter as tk

_KEY_MAP = {67: "copy", 86: "paste", 88: "cut", 65: "select_all", 90: "undo"}


def handle_key(event: tk.Event) -> str | None:
    """Обробник <Control-KeyPress>. Повертає 'break' якщо дію виконано."""
    if not (event.state & 0x4):  # Ctrl не натиснуто
        return None
    sym = event.keysym.lower()
    action = (
        "copy"       if sym in ("c", "с") else
        "paste"      if sym in ("v", "м") else
        "cut"        if sym in ("x", "ч") else
        "select_all" if sym in ("a", "ф") else
        "undo"       if sym in ("z", "я") else
        _KEY_MAP.get(event.keycode)
    )
    if not action:
        return None
    widget = event.widget
    try:
        if action == "copy":
            widget.event_generate("<<Copy>>")
        elif action == "paste":
            widget.event_generate("<<Paste>>")
        elif action == "cut":
            widget.event_generate("<<Cut>>")
        elif action == "select_all":
            widget.tag_add("sel", "1.0", "end") if hasattr(widget, "tag_add") \
                else widget.select_range(0, "end")
        elif action == "undo":
            widget.event_generate("<<Undo>>")
    except Exception:
        pass
    return "break"


def bind_to_all(widgets: list[tk.Widget], root: tk.Misc) -> None:
    """Прив'язує обробник гарячих клавіш до переданих віджетів."""
    for w in widgets:
        w.bind("<Control-KeyPress>", handle_key)
