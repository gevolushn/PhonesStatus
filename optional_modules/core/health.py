"""
health.py — перевірка доступності зовнішніх ресурсів. ОПЦІЙНИЙ модуль.

Реєструєш ресурси (URL, шлях, порт), запускаєш checker. Перевірка — у фоновому
потоці; результати — через Event Bus подію HEALTH_CHANGED (emit лише при ЗМІНІ стану).

Підключення: скопіювати у core/.
    from core.health import HealthChecker, Resource
    health = HealthChecker(interval_sec=60)
    health.register(Resource("github", "url", "https://api.github.com", critical=False))
    health.start()
    subscribe(Events.HEALTH_CHANGED, self._on_health)
"""
from __future__ import annotations

import os
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from core.events import Events
from core.logger import log


@dataclass
class Resource:
    name:     str                          # унікальний ключ
    kind:     Literal["url", "path", "port"]
    target:   str                          # URL / шлях / "host:port"
    critical: bool  = False                # True → програма не може без нього
    label:    str   = ""                   # зрозуміла назва для UI
    timeout:  float = 5.0

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.name


class HealthChecker:
    """Фоновий перевіряч доступності зареєстрованих ресурсів."""

    def __init__(self, interval_sec: float = 60.0) -> None:
        self._interval = interval_sec
        self._resources: dict[str, Resource] = {}
        self._status: dict[str, bool] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Публічний API ────────────────────────────────────────────────────────

    def register(self, resource: Resource) -> None:
        """Додати ресурс. Можна викликати до start()."""
        with self._lock:
            self._resources[resource.name] = resource
            self._status[resource.name] = True  # оптимістичний початковий стан

    def start(self) -> None:
        """Запустити фонову перевірку."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="HealthChecker")
        self._thread.start()
        log.info(f"HealthChecker запущено ({len(self._resources)} ресурсів, "
                 f"інтервал {self._interval}с).")

    def stop(self) -> None:
        """Зупинити фонову перевірку (викликати при виході)."""
        self._stop.set()

    def check_now(self) -> None:
        """Ручна перевірка всіх ресурсів у фоні."""
        threading.Thread(target=self._check_all, daemon=True, name="HealthChecker.manual").start()

    def snapshot(self) -> dict[str, bool]:
        """Поточний кешований стан без мережевих викликів."""
        with self._lock:
            return dict(self._status)

    def is_ok(self, name: str) -> bool:
        """Швидка перевірка одного ресурсу за кешем."""
        with self._lock:
            return self._status.get(name, False)

    # ── Внутрішня логіка ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        self._check_all()  # перша перевірка одразу
        while not self._stop.wait(timeout=self._interval):
            self._check_all()

    def _check_all(self) -> None:
        with self._lock:
            resources = list(self._resources.values())

        for res in resources:
            ok = self._check_one(res)
            with self._lock:
                prev = self._status.get(res.name)
                self._status[res.name] = ok

            # Емітуємо тільки при зміні стану або при першому запуску
            if ok != prev or prev is None:
                if ok:
                    log.info(f"Health [{res.name}] → OK ({res.label})")
                else:
                    log.warning(f"Health [{res.name}] → FAIL ({res.label})")
                try:
                    from core.events import emit
                    emit(Events.HEALTH_CHANGED, name=res.name, ok=ok,
                         label=res.label, critical=res.critical)
                except Exception as e:
                    log.warning(f"Health emit помилка: {e}")

    def _check_one(self, res: Resource) -> bool:
        try:
            if res.kind == "url":
                return self._check_url(res)
            elif res.kind == "path":
                return self._check_path(res)
            elif res.kind == "port":
                return self._check_port(res)
            log.warning(f"Health: невідомий тип '{res.kind}' для '{res.name}'")
            return False
        except Exception as e:
            log.debug(f"Health [{res.name}] виняток: {e}")
            return False

    @staticmethod
    def _check_url(res: Resource) -> bool:
        req = urllib.request.Request(res.target, method="HEAD")
        req.add_header("User-Agent", "HealthChecker/1.0")
        try:
            with urllib.request.urlopen(req, timeout=res.timeout) as resp:
                return resp.status < 400
        except urllib.error.HTTPError as e:
            return e.code < 500   # 4xx — сервер живий, просто відповів помилкою
        except Exception:
            return False

    @staticmethod
    def _check_path(res: Resource) -> bool:
        """
        Існування + запис — ПРОБНИМ ФАЙЛОМ, не os.access(W_OK).

        os.access на Windows дивиться лише на атрибут «тільки читання» і нічого не
        знає ні про ACL, ні про права на мережевому ресурсі — рапортує «доступно» там,
        де перший же запис впаде. Якщо target — файл, а не тека, пробний запис іде в
        його батьківську теку (перезаписувати довільний існуючий файл заради перевірки
        небезпечно).
        """
        if not os.path.exists(res.target):
            return False
        directory = res.target if os.path.isdir(res.target) else os.path.dirname(res.target)
        probe = os.path.join(directory or ".", f".health_probe_{os.getpid()}")
        try:
            with open(probe, "w", encoding="utf-8"):
                pass
        except OSError:
            return False
        finally:
            try:
                os.remove(probe)
            except OSError:
                pass
        return True

    @staticmethod
    def _check_port(res: Resource) -> bool:
        host, _, port_str = res.target.rpartition(":")
        if not host or not port_str:
            return False
        with socket.create_connection((host, int(port_str)), timeout=res.timeout):
            return True
