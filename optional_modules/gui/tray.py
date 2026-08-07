"""
tray.py — іконка у системному треї. ОПЦІЙНИЙ модуль.

Підключати, коли програма має жити у фоні (згортання замість закриття).

Залежності: pystray>=0.19.5, Pillow>=10.0.0 (розкоментувати у requirements.txt).
Іконка: assets/icons/icon.png, або автоматичний fallback-кружечок.

⚠️ pystray має власний event loop → запускається у daemon-потоці, а всі колбеки
   загортаються у root.after(0, ...) (єдиний безпечний місток до tkinter mainloop).
   stop() ОБОВ'ЯЗКОВО викликати ПЕРЕД destroy(), інакше іконка лишається в треї
   до перезавантаження Explorer.

Підключення: скопіювати у gui/.
    self._tray = TrayIcon(root=self, app_name=build_info.APP_NAME, on_quit=self._quit_app,
        menu_extra=[("Налаштування", self._open_settings), ("Про програму", self._show_about)])
    self._tray.start()
"""
from __future__ import annotations

import os
import threading
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from core.logger import log
from core.paths import app_dir


class TrayIcon:
    """Іконка у треї з меню. Колбеки автоматично повертаються у GUI-потік через root.after."""

    def __init__(
        self,
        root,
        app_name: str,
        on_quit: Callable[[], None],
        menu_extra: list[tuple[str, Callable | None]] | None = None,
        icon_path: str | None = None,
    ) -> None:
        self._root = root
        self._app_name = app_name
        self._on_quit = on_quit
        self._menu_extra = menu_extra or []
        self._icon_path = icon_path or os.path.join(app_dir(), "assets", "icons", "icon.png")
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def _load_image(self) -> Image.Image:
        """Завантажує icon.png або малює fallback-кружечок."""
        try:
            if os.path.isfile(self._icon_path):
                return Image.open(self._icon_path)
        except Exception as e:
            log.warning(f"Не вдалося завантажити іконку трею '{self._icon_path}': {e}")
        # Fallback — простий кружечок
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(31, 83, 141, 255))
        return img

    def _wrap(self, callback: Callable | None) -> Callable:
        """Загортає колбек у root.after(0, ...) — безпечне повернення у GUI-потік."""
        def _wrapped(_icon=None, _item=None) -> None:
            if callback is not None:
                self._root.after(0, callback)
        return _wrapped

    def _build_menu(self) -> pystray.Menu:
        items = []
        for label, callback in self._menu_extra:
            if callback is None:
                items.append(pystray.Menu.SEPARATOR)
            else:
                items.append(pystray.MenuItem(label, self._wrap(callback)))
        items.append(pystray.MenuItem("Вихід", self._wrap(self._on_quit)))
        return pystray.Menu(*items)

    def start(self) -> None:
        """Запускає іконку у daemon-потоці."""
        self._icon = pystray.Icon(
            self._app_name, self._load_image(), self._app_name, self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="TrayIcon")
        self._thread.start()
        log.info("Іконку трею запущено.")

    def stop(self) -> None:
        """Зупиняє іконку. Викликати ПЕРЕД root.destroy()."""
        if self._icon is not None:
            try:
                self._icon.stop()
                log.info("Іконку трею зупинено.")
            except Exception as e:
                log.warning(f"Помилка зупинки іконки трею: {e}")
            self._icon = None
