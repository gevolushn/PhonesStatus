"""
updater.py — перевірка оновлень через GitHub Releases API та запуск оновлення.

Нуль зовнішніх залежностей — тільки urllib зі stdlib.

⚠️ Модуль НЕ знає про GUI-стек (жодного tkinter). `launch_update()` приймає
`on_ready_to_exit` — простий callback, а не Tk-об'єкт `root`. Раніше `_apply_portable`/
`_apply_installed` робили `root.after(0, root.destroy)` напряму: це (а) знищувало вікно,
а не виходило з програми штатно (конфіг не зберігався, трей лишав іконку-привида), і
(б) прив'язувало ядро до Tkinter непомітно для аналізу імпортів. Викликач (GUI) сам
вирішує, ЩО таке «готовий вийти», і сам маршалить колбек у свій потік — так само, як уже
робить `on_progress`. Той самий принцип, що й у `should_check_now`/`mark_checked`: ядро
не знає про побічні ефекти виклику.

Два режими дистрибуції (з core.build_info.DISTRIBUTION):
    portable  → витягує updater.exe з assets у %TEMP%, записує update_task.json,
                завершує програму — updater.exe замінює .exe і перезапускає.
    installed → скачує новий Setup.exe у %TEMP%, запускає з /VERYSILENT /NORESTART,
                завершує програму — інсталятор оновлює по-тихому.

Режим репозиторію — через core.build_info:
    GITHUB_PRIVATE = False → без токену (публічний)
    GITHUB_PRIVATE = True  → з GITHUB_TOKEN (приватний)
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Callable, NamedTuple

from core.logger import log
import core.build_info as build_info
import core.paths as paths

_API_BASE = "https://api.github.com"
_TEMP_DIR = tempfile.gettempdir()

# Сигнальні коди для on_progress (0..100 — нормальний хід завантаження).
# Обидві фази мусять мати ЯВНИЙ код помилки: мовчазний return лишав діалог оновлення
# з нескінченним прогрес-баром, заблокованими кнопками і вимкненим Esc — вікно
# неможливо було закрити (див. gui/update_dialog.py).
PROGRESS_DOWNLOAD_FAILED = -1   # не вдалося завантажити asset
PROGRESS_APPLY_FAILED = -2      # завантажено, але не вдалося застосувати

# Режими автоперевірки (ключ `update_check` у конфігу). Порядок = порядок у GUI.
UPDATE_CHECK_MODES: tuple[str, ...] = ("startup", "daily", "weekly", "never")
_CHECK_INTERVAL_DAYS: dict[str, int] = {"startup": 0, "daily": 1, "weekly": 7}

_ASSET_SUFFIX: dict[str, str] = {
    "portable":  "_portable.exe",
    "installed": "_setup.exe",
}


class UpdateInfo(NamedTuple):
    """Інформація про доступне оновлення."""
    version: str
    changelog: str
    download_url: str   # browser_download_url — для публічного репо
    asset_name: str
    asset_api_url: str  # asset["url"] (API-URL) — для приватного завантаження через octet-stream


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Не йде за HTTP-редіректом автоматично — обробляємо його вручну (див. _download_file)."""

    def redirect_request(self, *args, **kwargs):
        return None


def check_for_updates(
    on_update_found: Callable[[UpdateInfo], None],
    on_no_update: Callable[[], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Перевіряє наявність оновлень у фоновому потоці."""
    threading.Thread(
        target=_check_worker,
        args=(on_update_found, on_no_update, on_error),
        daemon=True, name="UpdateChecker",
    ).start()


def launch_update(
    info: UpdateInfo,
    on_progress: Callable[[int], None],
    on_ready_to_exit: Callable[[], None],
) -> None:
    """
    Запускає завантаження і оновлення у фоновому потоці.

    `on_ready_to_exit` кличеться, коли оновлення успішно застосоване і програма може
    завершуватись — З ФОНОВОГО ПОТОКУ, так само як і `on_progress`. Викликач відповідає за
    штатний вихід (зберегти конфіг, зупинити трей) і за безпечне повернення у свій потік
    (`self.after(0, ...)` для Tkinter).
    """
    threading.Thread(
        target=_download_and_apply,
        args=(info, on_progress, on_ready_to_exit),
        daemon=True, name="UpdateDownloader",
    ).start()


def should_check_now(config: dict) -> bool:
    """
    Чи пора АВТОМАТИЧНО перевіряти оновлення (політика з ключа `update_check`).

    Функція чиста: читає dict і нічого не зберігає — рішення про запис лишається за
    викликачем (у режимі `remember=False` конфіг узагалі не переживає вихід із програми,
    тож `daily` там природно вироджується у перевірку при кожному запуску).

    РУЧНА перевірка цю функцію НЕ питає: кнопку користувач натиснув свідомо.
    """
    mode = str(config.get("update_check", "startup"))
    if mode not in UPDATE_CHECK_MODES:
        log.warning(f"Невідомий режим update_check='{mode}' → трактую як 'startup'.")
        mode = "startup"
    if mode == "never":
        return False

    days = _CHECK_INTERVAL_DAYS[mode]
    if days == 0:
        return True

    raw = str(config.get("last_update_check", "")).strip()
    if not raw:
        return True                      # ще жодного разу не перевіряли
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        log.warning(f"Некоректний last_update_check='{raw}' → перевіряю зараз.")
        return True

    now = datetime.now()
    if last > now:
        # Годинник системи перевели назад (або конфіг приїхав з іншої машини). Без цієї
        # гілки перевірка «замерзла б» до настання майбутньої дати — мовчки й надовго.
        log.warning("last_update_check у майбутньому — скидаю і перевіряю зараз.")
        return True
    return (now - last) >= timedelta(days=days)


def mark_checked(config: dict) -> None:
    """
    Фіксує момент перевірки в config-dict. Зберігає викликач (див. should_check_now).

    Ставиться при КОЖНІЙ фактичній перевірці, зокрема невдалій: інакше програма без
    мережі била б по API при кожному запуску, ігноруючи обраний інтервал.
    """
    config["last_update_check"] = datetime.now().isoformat(timespec="seconds")


def cleanup_update_artifacts() -> None:
    """
    Видаляє файли від попереднього оновлення з %TEMP%.
    Викликати при старті програми в main.py.
    """
    import glob

    prefix = build_info.TEMP_PREFIX
    updater_exe = os.path.join(_TEMP_DIR, f"{prefix}updater.exe")
    other_patterns = [
        os.path.join(_TEMP_DIR, f"{prefix}update_task.json"),
        os.path.join(_TEMP_DIR, f"{prefix}updater_log.txt"),
        os.path.join(_TEMP_DIR, f"{build_info.APP_NAME}_*_portable.exe"),
        os.path.join(_TEMP_DIR, f"{build_info.APP_NAME}_*_setup.exe"),
    ]
    deleted = 0

    # updater.exe самовидаляється сам (ping+del із затримкою ~2с). Якщо він у цю мить ще
    # живий, файл заблокований — це ОЧІКУВАНИЙ стан, а не помилка. Голосний warning на
    # рівному місці привчає ігнорувати попередження, серед яких загубиться справжнє.
    if os.path.isfile(updater_exe):
        try:
            os.remove(updater_exe)
            deleted += 1
            log.info(f"Видалено артефакт оновлення: {updater_exe}")
        except OSError as e:
            log.debug(f"updater.exe ще активний (самовидалиться сам): {e}")

    for pattern in other_patterns:
        for path in glob.glob(pattern):
            try:
                os.remove(path)
                deleted += 1
                log.info(f"Видалено артефакт оновлення: {path}")
            except Exception as e:
                log.warning(f"Не вдалося видалити '{path}': {e}")
    if deleted:
        log.info(f"Очищено {deleted} артефакт(ів) оновлення з %TEMP%.")


# ── Внутрішня логіка ──────────────────────────────────────────────────────────

def _api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{build_info.APP_NAME}-Updater/{build_info.APP_VERSION}",
    }
    if build_info.GITHUB_PRIVATE and build_info.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {build_info.GITHUB_TOKEN}"
    return headers


def _fetch_latest_release() -> dict:
    url = f"{_API_BASE}/repos/{build_info.GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers=_api_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError("GitHub API: невірний токен або репо приватне без токену.")
        if e.code == 404:
            raise RuntimeError(f"Репо '{build_info.GITHUB_REPO}' не знайдено або немає релізів.")
        raise RuntimeError(f"GitHub API HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Мережева помилка: {e.reason}")


def _parse_version(tag: str) -> tuple[int, ...]:
    """
    Стійкий парсер версії без зовнішніх залежностей.
    Відрізає префікс 'v', бере лише провідні цифри кожного сегмента.

    УВАГА: pre-release-суфікс ВТРАЧАЄТЬСЯ → '1.2.0-rc1' трактується == '1.2.0'.
    Якщо колись знадобляться канали rc/beta — перейти на packaging.version.Version.
    """
    clean = tag[1:] if tag.lower().startswith("v") else tag
    clean = clean.strip()
    parts: list[int] = []
    for seg in clean.split("."):
        m = re.match(r"\d+", seg)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts) if parts else (0,)


def _is_newer(remote_tag: str, current_tag: str) -> bool:
    """True, якщо remote строго новіша за current. Нормалізує довжину кортежів нулями."""
    a = list(_parse_version(remote_tag))
    b = list(_parse_version(current_tag))
    length = max(len(a), len(b))
    a += [0] * (length - len(a))   # (1,2) → (1,2,0), щоб 1.2 не вважалось старшим за 1.2.0
    b += [0] * (length - len(b))
    return tuple(a) > tuple(b)


def _find_asset(assets: list[dict]) -> dict | None:
    """
    Знаходить asset під поточний DISTRIBUTION.

    Невідомий DISTRIBUTION НЕ підставляє порожній суфікс: `"...".endswith("")` завжди
    істинне, тож раніше повертався ПЕРШИЙ-ліпший asset релізу (типово чужий бінарник під
    інший режим дистрибуції) — і про помилку дізнавались лише ПІСЛЯ завантаження.
    """
    suffix = _ASSET_SUFFIX.get(build_info.DISTRIBUTION)
    if suffix is None:
        log.error(f"Невідомий DISTRIBUTION: '{build_info.DISTRIBUTION}'.")
        return None
    for asset in assets:
        if asset.get("name", "").lower().endswith(suffix.lower()):
            return asset
    return None


def _check_worker(on_update_found, on_no_update, on_error) -> None:
    try:
        release = _fetch_latest_release()
        remote_tag = release.get("tag_name", "")
        if not _is_newer(remote_tag, build_info.APP_VERSION):
            log.info(f"Оновлення не потрібне: {build_info.APP_VERSION} >= {remote_tag}")
            if on_no_update:
                on_no_update()
            return
        asset = _find_asset(release.get("assets", []))
        if not asset:
            raise RuntimeError(
                f"Реліз {remote_tag} знайдено, але asset для "
                f"'{build_info.DISTRIBUTION}' відсутній."
            )
        info = UpdateInfo(
            version=remote_tag.lstrip("v"),
            changelog=release.get("body", "").strip(),
            download_url=asset["browser_download_url"],
            asset_name=asset["name"],
            asset_api_url=asset["url"],   # API-URL asset-а для приватного завантаження
        )
        log.info(f"Знайдено оновлення: {remote_tag} ({info.asset_name})")
        on_update_found(info)
    except Exception as exc:
        log.error(f"Помилка перевірки оновлень: {exc}")
        if on_error:
            on_error(str(exc))


def _download_file(url: str, dest: str, on_progress: Callable[[int], None]) -> None:
    """
    Завантажує asset у dest. Качає у dest+'.part', звіряє розмір, потім os.replace.

    Приватний репо: url — API-URL asset-а (asset["url"]). GitHub віддає 302 на S3.
        Редірект обробляємо ВРУЧНУ і другий запит на S3 робимо БЕЗ Authorization —
        так не залежимо від того, чи скидає urllib заголовок авторизації при крос-
        хостовому редіректі (інакше S3 поверне '400 Only one auth mechanism').
    Публічний репо: url — browser_download_url, взагалі без заголовків авторизації.
    """
    is_private = build_info.GITHUB_PRIVATE and build_info.GITHUB_TOKEN
    user_agent = _api_headers()["User-Agent"]

    if is_private:
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(
            url, headers={**_api_headers(), "Accept": "application/octet-stream"}
        )
        try:
            resp = opener.open(req, timeout=60)            # прямої відповіді без редіректу
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                # другий запит на S3 БЕЗ Authorization
                resp = urllib.request.urlopen(
                    urllib.request.Request(
                        e.headers["Location"], headers={"User-Agent": user_agent}
                    ),
                    timeout=60,
                )
            else:
                raise
    else:
        resp = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": user_agent}), timeout=60
        )

    part = dest + ".part"
    try:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(part, "wb") as f:
            while chunk := resp.read(65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    on_progress(min(int(downloaded / total * 100), 99))
    finally:
        resp.close()

    # Верифікація цілісності: обрив зв'язку не має пройти як успіх
    if total > 0 and downloaded != total:
        if os.path.isfile(part):
            os.remove(part)
        raise RuntimeError(f"Неповне завантаження: {downloaded}/{total} байт")

    os.replace(part, dest)   # атомарно: «готовий» файл з'являється лише цілим
    log.info(f"Завантажено: {dest} ({downloaded} байт)")


def _download_and_apply(
    info: UpdateInfo,
    on_progress: Callable[[int], None],
    on_ready_to_exit: Callable[[], None],
) -> None:
    dest = os.path.join(_TEMP_DIR, info.asset_name)
    source_url = (info.asset_api_url
                  if build_info.GITHUB_PRIVATE and build_info.GITHUB_TOKEN
                  else info.download_url)
    try:
        _download_file(source_url, dest, on_progress)
    except Exception as exc:
        log.error(f"Помилка завантаження: {exc}")
        on_progress(PROGRESS_DOWNLOAD_FAILED)
        return
    if build_info.DISTRIBUTION == "portable":
        _apply_portable(dest, on_progress, on_ready_to_exit)
    elif build_info.DISTRIBUTION == "installed":
        _apply_installed(dest, on_progress, on_ready_to_exit)
    else:
        log.error(f"Невідомий DISTRIBUTION: '{build_info.DISTRIBUTION}'")
        on_progress(PROGRESS_APPLY_FAILED)


def _get_updater_exe_path() -> str:
    """
    Шлях до вшитого updater.exe.

    assets_dir() рахується від resource_dir() (sys._MEIPASS), а НЕ від папки з .exe —
    інакше в onefile-збірці файл не знаходиться і portable-оновлення не працює взагалі.
    """
    return os.path.join(paths.assets_dir(), "updater", "updater.exe")


def _apply_portable(
    new_exe_path: str,
    on_progress: Callable[[int], None],
    on_ready_to_exit: Callable[[], None],
) -> None:
    import shutil
    import subprocess

    updater_src = _get_updater_exe_path()
    if not os.path.isfile(updater_src):
        log.error(
            f"updater.exe не знайдено: '{updater_src}'. Portable-оновлення неможливе. "
            f"Зберіть updater.exe (assets/updater/README.txt) і перезберіть програму."
        )
        on_progress(PROGRESS_APPLY_FAILED)
        return
    updater_dst = os.path.join(_TEMP_DIR, f"{build_info.TEMP_PREFIX}updater.exe")
    try:
        shutil.copy2(updater_src, updater_dst)
    except Exception as e:
        log.error(f"Не вдалося скопіювати updater.exe: {e}")
        on_progress(PROGRESS_APPLY_FAILED)
        return
    task = {
        "pid":          os.getpid(),
        "current_exe":  sys.executable if getattr(sys, "frozen", False)
                        else os.path.abspath(sys.argv[0]),
        "new_exe":      new_exe_path,
        "distribution": build_info.DISTRIBUTION,
        "restart":      True,
    }
    task_path = os.path.join(_TEMP_DIR, f"{build_info.TEMP_PREFIX}update_task.json")
    try:
        with open(task_path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Не вдалося записати update_task.json: {e}")
        on_progress(PROGRESS_APPLY_FAILED)
        return
    try:
        subprocess.Popen([updater_dst, task_path], creationflags=0x00000008)  # DETACHED_PROCESS
        log.info("updater.exe запущено.")
    except Exception as e:
        log.error(f"Не вдалося запустити updater.exe: {e}")
        on_progress(PROGRESS_APPLY_FAILED)
        return
    on_ready_to_exit()


def _apply_installed(
    installer_path: str,
    on_progress: Callable[[int], None],
    on_ready_to_exit: Callable[[], None],
) -> None:
    import subprocess

    try:
        subprocess.Popen(
            [installer_path, "/VERYSILENT", "/NORESTART"],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        log.info(f"Installer запущено: {installer_path}")
    except Exception as e:
        log.error(f"Не вдалося запустити installer: {e}")
        on_progress(PROGRESS_APPLY_FAILED)
        return
    on_ready_to_exit()
