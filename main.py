"""
main.py — точка входу програми.
Порядок: crash_handler → lock → cleanup → updater_cleanup → config → color_theme → GUI → finally
"""
import os

import customtkinter as ctk

from core.logger import log
from core import instance_lock, cleanup, config_manager, paths
from core.crash_reporter import install_crash_handler
from core.updater import cleanup_update_artifacts
import core.build_info as build_info
from gui.app_window import AppWindow


def _resolve_theme_path(theme_name: str) -> str:
    """Шлях до assets/themes/<name>.json. Якщо немає — CTk 'blue' як запасний."""
    path = os.path.join(paths.assets_dir(), "themes", f"{theme_name}.json")
    if os.path.isfile(path):
        return path
    log.warning(f"Файл теми не знайдено: '{path}'. Використовується CTk 'blue'.")
    return "blue"


def main() -> None:
    install_crash_handler(app_name=build_info.APP_NAME)  # ⓪ ловити крах навіть на старті
    _mutex = instance_lock.check_single_instance()   # ① один екземпляр
    cleanup.clean_old_logs()                          # ② очищення старих логів
    cleanup_update_artifacts()                        # ③ очищення залишків оновлення

    log.info("═" * 50)
    log.info(f"{build_info.APP_NAME} — старт (v{build_info.APP_VERSION})")
    log.info("═" * 50)

    config = config_manager.load_config()             # ④ конфіг

    theme_path = _resolve_theme_path(config.get("color_theme", "neutral"))
    ctk.set_default_color_theme(theme_path)           # ⑤ акцентна тема (до перших CTk-віджетів)
    log.info(f"Акцентна тема: {theme_path}")

    try:
        app = AppWindow(config)                       # ⑥ GUI
        app.mainloop()
    except KeyboardInterrupt:
        log.warning("Примусове завершення (Ctrl+C).")
    except Exception as e:
        log.error(f"Критична помилка: {e}", exc_info=True)
        try:
            import tkinter as tk
            from tkinter import messagebox
            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Критична помилка",
                f"Програма завершилась із помилкою:\n\n{e}\n\nДеталі у logs/",
            )
            _root.destroy()
        except Exception:
            pass
    finally:
        remember = config_manager.load_config().get("remember", False)
        if not remember:
            # Режим «без слідів»: тут чистимо ЛИШЕ лог поточної сесії (логер —
            # власність main, цей виклик закриває його хендлери). Конфіг видаляє
            # app_window._on_closing — він тримає config-dict і рішення save vs delete.
            # Розподіл свідомий (див. docs/DECISIONS.md).
            log.info("remember=False → видаляємо лог поточної сесії.")
            cleanup.delete_current_log()
        else:
            log.info("Програма завершила роботу.")


if __name__ == "__main__":
    main()
