"""
updater.py — перевірка оновлень через GitHub Releases API та запуск оновлення.

Нуль зовнішніх залежностей — тільки urllib зі stdlib.

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
from typing import Callable, NamedTuple

from core.logger import log
import core.build_info as build_info
import core.paths as paths

_API_BASE = "https://api.github.com"
_TEMP_DIR = tempfile.gettempdir()

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


def launch_update(root, info: UpdateInfo, on_progress: Callable[[int], None]) -> None:
    """Запускає завантаження і оновлення у фоновому потоці."""
    threading.Thread(
        target=_download_and_apply,
        args=(root, info, on_progress),
        daemon=True, name="UpdateDownloader",
    ).start()


def cleanup_update_artifacts() -> None:
    """
    Видаляє файли від попереднього оновлення з %TEMP%.
    Викликати при старті програми в main.py.
    """
    import glob

    prefix = build_info.TEMP_PREFIX
    patterns = [
        os.path.join(_TEMP_DIR, f"{prefix}updater.exe"),
        os.path.join(_TEMP_DIR, f"{prefix}update_task.json"),
        os.path.join(_TEMP_DIR, f"{prefix}updater_log.txt"),
        os.path.join(_TEMP_DIR, f"{build_info.APP_NAME}_*_portable.exe"),
        os.path.join(_TEMP_DIR, f"{build_info.APP_NAME}_*_setup.exe"),
    ]
    deleted = 0
    for pattern in patterns:
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
    suffix = _ASSET_SUFFIX.get(build_info.DISTRIBUTION, "")
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


def _download_and_apply(root, info: UpdateInfo, on_progress: Callable[[int], None]) -> None:
    dest = os.path.join(_TEMP_DIR, info.asset_name)
    source_url = (info.asset_api_url
                  if build_info.GITHUB_PRIVATE and build_info.GITHUB_TOKEN
                  else info.download_url)
    try:
        _download_file(source_url, dest, on_progress)
    except Exception as exc:
        log.error(f"Помилка завантаження: {exc}")
        on_progress(-1)
        return
    if build_info.DISTRIBUTION == "portable":
        _apply_portable(root, dest)
    elif build_info.DISTRIBUTION == "installed":
        _apply_installed(root, dest)
    else:
        log.error(f"Невідомий DISTRIBUTION: '{build_info.DISTRIBUTION}'")
        on_progress(-1)


def _get_updater_exe_path() -> str:
    return os.path.join(paths.assets_dir(), "updater", "updater.exe")


def _apply_portable(root, new_exe_path: str) -> None:
    import shutil
    import subprocess

    updater_dst = os.path.join(_TEMP_DIR, f"{build_info.TEMP_PREFIX}updater.exe")
    try:
        shutil.copy2(_get_updater_exe_path(), updater_dst)
    except Exception as e:
        log.error(f"Не вдалося скопіювати updater.exe: {e}")
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
        return
    try:
        subprocess.Popen([updater_dst, task_path], creationflags=0x00000008)  # DETACHED_PROCESS
        log.info("updater.exe запущено.")
    except Exception as e:
        log.error(f"Не вдалося запустити updater.exe: {e}")
        return
    root.after(0, root.destroy)


def _apply_installed(root, installer_path: str) -> None:
    import subprocess

    try:
        subprocess.Popen(
            [installer_path, "/VERYSILENT", "/NORESTART"],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        log.info(f"Installer запущено: {installer_path}")
    except Exception as e:
        log.error(f"Не вдалося запустити installer: {e}")
        return
    root.after(0, root.destroy)
