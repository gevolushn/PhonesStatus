"""
window_utils.py — виправляє один клас дефекту, скопійований у шаблоні тричі. ЯДРО.

Три файли (update_dialog.py, settings_window.py, dialogs.py) незалежно винаходили те
саме центрування Toplevel і ту саму перевірку «вікно вже відкрите» — і всі три несли
той самий дефект: центрування не враховувало межі екрана, а `focus()` не піднімало
вікно на передній план. Одна копія — один захист замість трьох окремих.

Чотири функції:
    raise_window(window)                        — підняти на передній план + фокус
    center_on_parent(window, parent, w, h)       — центрувати з клампом у межі екрана
    get_instance(instance)                       — жива instance чи None (ловить TclError)
    clamp_to_screen(window)                      — притиснути ГОТОВЕ geometry в межі екрана
    reset_entry(entry, placeholder="", show="")  — скинути CTkEntry без залиплого плейсхолдера
"""
from __future__ import annotations


def raise_window(window) -> None:
    """
    Піднімає вікно на передній план і повертає йому фокус.

    `window.focus()` (застаріле, лише фокус клавіатури) НЕ змінює z-order — вікно, за
    яке зайшла тема чи клік по головному вікну, лишається позаду. Далі кожне повторне
    відкриття виглядає як «нічого не відбувається»; користувач повідомляє це як «вікно
    закрилось і більше не відкривається».
    """
    window.deiconify()
    window.lift()
    window.focus_force()


def get_instance(instance):
    """
    Повертає instance, якщо він живий, інакше None.

    `winfo_exists()` на вже знищеному Tcl-об'єкті може кинути `TclError`, а не тихо
    повернути `False` — залежить від того, наскільки глибоко Tcl встиг прибрати
    внутрішній стан. Без цього мертве посилання назавжди блокує створення нового вікна:
    патерн одного екземпляра (`show_settings`, `show_update_dialog`) ламається саме тут.
    """
    if instance is None:
        return None
    try:
        if instance.winfo_exists():
            return instance
    except Exception:
        pass
    return None


def center_on_parent(window, parent, width: int, height: int) -> None:
    """
    Центрує window відносно parent, з клампом у межі екрана.

    Якщо parent прихований (`withdraw()` — типовий стан для згорнутого в трей головного
    вікна), його координати вже НЕ екранні: центруємо по екрану замість цього. Координати
    завжди клампляться в [0, розмір_екрана - розмір_вікна] — і коли батько видимий, і
    коли ні. Формула коректно притискає вікно до лівого/верхнього краю й тоді, коли саме
    вікно більше за екран (величезний шрифт): `screen - width` стає від'ємним, і
    `max(0, ...)` дає 0, а не негативну позицію.

    ⚠️ Мультимонітор: Tkinter не має рідного API за межами `winfo_screenwidth/height`
    (лише основний екран). На кількох моніторах вікно клампиться в межі ОСНОВНОГО —
    прийнятний компроміс для діалогів, повний мультимонітор — за межами цього шаблону.
    """
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()

    if parent is not None and parent.winfo_viewable():
        x = parent.winfo_x() + (parent.winfo_width() - width) // 2
        y = parent.winfo_y() + (parent.winfo_height() - height) // 2
    else:
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2

    x = max(0, min(x, screen_w - width))
    y = max(0, min(y, screen_h - height))
    window.geometry(f"{width}x{height}+{x}+{y}")


def clamp_to_screen(window) -> None:
    """
    Притискає ВЖЕ встановлену geometry вікна в межі екрана, не чіпаючи розмір.

    Для позиції, що приходить ЗЗОВНІ (збережений конфіг, монітор, якого вже немає):
    просто зсуває вікно назад у видиму область. Викликати ПІСЛЯ встановлення geometry
    (з відновленої позиції чи після `deiconify()`).
    """
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    w, h = window.winfo_width(), window.winfo_height()
    x, y = window.winfo_x(), window.winfo_y()

    new_x = max(0, min(x, screen_w - w))
    new_y = max(0, min(y, screen_h - h))
    if (new_x, new_y) != (x, y):
        window.geometry(f"+{new_x}+{new_y}")


def _has_keyboard_focus(widget) -> bool:
    """Чи тримає ВІДЖЕТ (не його підкомпонент) фокус клавіатури прямо зараз."""
    focused = widget.focus_get()
    if focused is None:
        return False
    target = str(widget)
    path = str(focused)
    # Крапка обов'язкова: без неї ".!ctkentry2" збігається з ".!ctkentry" за startswith.
    return path == target or path.startswith(target + ".")


def reset_entry(entry, placeholder: str = "", show: str = "") -> None:
    """
    Очищає CTkEntry й ставить нову підказку, не лишаючи плейсхолдер «залиплим».

    CustomTkinter 5.2.2: `configure(placeholder_text=...)` вмикає підказку БЕЗ перевірки
    фокуса — навіть на полі, яке фокус уже тримає. Вимикається підказка лише обробником
    `<FocusIn>`, а цієї події в такому разі вже не буде (фокус нікуди не йшов). Наслідок:
    користувач бачить і друкує свій текст, але сірим кольором плейсхолдера, а `entry.get()`
    при цьому віддає ПОРОЖНІЙ рядок — не те, що на екрані. Типовий сценарій — покроковий
    діалог/майстер, що перебудовує підказку на кожному кроці, лишаючи фокус на полі.

    `insert(0, "")` — єдиний ПУБЛІЧНИЙ спосіб зняти залиплий плейсхолдер (кличе
    `_deactivate_placeholder()` всередині), без звертання до приватних полів CTk.
    """
    entry.delete(0, "end")
    entry.configure(show=show, placeholder_text=placeholder)
    if _has_keyboard_focus(entry):
        entry.insert(0, "")
