"""
google_sheets.py — запис IP у ту саму Google-таблицю, що читається в авто-режимі.

Чому окремий модуль, а не розширення `parsers/sheets_parser.py`
───────────────────────────────────────────────────────────────
Читання авто-режиму працює на API-ключі, а ключ дає доступ ТІЛЬКИ на читання.
Запис потребує OAuth2 з обліковим записом власника таблиці — інша авторизація,
інший життєвий цикл, інші помилки. Виходить два шляхи читання однієї таблиці з
різною авторизацією, і це свідомо: чистий шов, нульовий ризик зламати робочу звірку.
`parsers/sheets_parser.py` цим модулем НЕ змінюється й не імпортує його.

Залежностей немає — лише stdlib (`urllib`, `json`, `http.server`, `webbrowser`,
`hashlib`, `secrets`, `threading`).

OAuth2 loopback flow
────────────────────
Кнопка в налаштуваннях → локальний сервер на `127.0.0.1:<вільний порт>` → сторінка
згоди у браузері за умовчанням → Google редіректить на loopback із `code` → обмін
`code` на `refresh_token` → токен лягає під DPAPI.

Для клієнта типу Desktop App Google дозволяє будь-який порт loopback без реєстрації
redirect URI. Прив'язка саме до `127.0.0.1` (не `0.0.0.0`) — тоді Windows Firewall
не питає дозволу. Embedded-браузер (webview/CEF) не використовуємо принципово:
важка залежність, і Google блокує такі клієнти помилкою `disallowed_useragent`.

`access_token` живе годину, тримається ТІЛЬКИ в пам'яті й оновлюється автоматично.
На диск іде лише `refresh_token`.

⚠️ Три пастки, кожна перевірена на живому API
─────────────────────────────────────────────
1. Токен передається заголовком `Authorization: Bearer`, а НЕ параметром
   `?access_token=` в URL: токен у query-рядку осідає в логах серверів і проксі,
   і Google цей спосіб задепрекейтив.
2. Значення комірок пише `…/values:batchUpdate`, а НЕ `…:batchUpdate` — це різні
   ендпоінти: другий міняє структуру книги.
3. `valueInputOption=RAW` обов'язковий і саме RAW, щоб Sheets не переінтерпретував
   записане (інакше «192.168.1.1» має шанс поїхати як дата чи формула).

⚠️ Пастка 7 днів
────────────────
Consent screen типу External у статусі «Testing» вбиває refresh-токен через 7 днів.
Застосунок переведено в «In production» — там ліміту немає. Але токен усе одно може
бути відкликаний (вручну користувачем, 6 місяців простою, повернення застосунку в
Testing). Тоді Google віддає `invalid_grant`, і це ШТАТНИЙ стан, а не аварія:
модуль кидає `GoogleAuthError`, GUI чистить збережений токен і просить авторизуватись
заново. Мовчазний збій запису тут неприпустимий — користувач шукав би проблему
в MikroTik або правах на таблицю.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.logger import log
from parsers.sheets_parser import _column_letter, _quote_sheet, extract_id
from parsers.table_rules import col_index, detect_sheet

_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
_API_BASE: str = "https://sheets.googleapis.com/v4/spreadsheets"
_SCOPE: str = "https://www.googleapis.com/auth/spreadsheets"

_TIMEOUT_SEC: int = 20
_TOKEN_LEEWAY_SEC: int = 60      # оновлюємо трохи раніше, ніж протухне


class GoogleAuthError(Exception):
    """Помилка авторизації Google з готовим до показу текстом."""


class GoogleSheetsError(Exception):
    """Помилка звернення до Sheets API з готовим до показу текстом."""


# ─── Облікові дані клієнта ────────────────────────────────────────────────────

def load_client_json(path: str) -> tuple[str, str]:
    """
    Дістає `client_id` і `client_secret` з JSON, який Google дає при створенні
    OAuth-клієнта.

    Значення далі зберігаються в конфігу під DPAPI, тож сам файл потрібен рівно
    один раз. У збірку вони НЕ вшиваються: вшитий у portable `.exe` secret
    дістається звичайним `strings`, а зміна клієнта вимагала б перезбірки.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError as e:
        raise GoogleAuthError("Файл не знайдено.") from e
    except json.JSONDecodeError as e:
        raise GoogleAuthError("Це не JSON — виберіть файл, завантажений із Google Cloud.") from e
    except OSError as e:
        log.error(f"Не вдалося прочитати client JSON: {e}")
        raise GoogleAuthError(f"Не вдалося прочитати файл: {e}") from e

    if not isinstance(payload, dict):
        raise GoogleAuthError("Несподіваний вміст файлу.")

    if "web" in payload:
        raise GoogleAuthError(
            "Це файл клієнта типу «Web application». Потрібен тип «Desktop app» — "
            "лише він дозволяє авторизацію через локальний порт."
        )

    section = payload.get("installed")
    if not isinstance(section, dict):
        raise GoogleAuthError(
            "У файлі немає секції «installed» — це не облікові дані OAuth-клієнта "
            "типу «Desktop app»."
        )

    client_id = str(section.get("client_id", "")).strip()
    client_secret = str(section.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        raise GoogleAuthError("У файлі бракує client_id або client_secret.")

    log.info("Облікові дані OAuth-клієнта прочитано з JSON.")
    return client_id, client_secret


# ─── Низькорівневі запити ─────────────────────────────────────────────────────

def _http_detail(exc: urllib.error.HTTPError) -> tuple[str, str]:
    """
    Витягує з тіла помилки код і текст Google. Читати можна ЛИШЕ раз — тому
    робимо це в одному місці й далі передаємо вже розібране.

    Повертає `(машинний код помилки, людський текст)`.
    """
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except Exception:
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    # Формат ендпоінта токенів: {"error": "invalid_grant", "error_description": "..."}
    code = payload.get("error")
    if isinstance(code, str):
        return code, str(payload.get("error_description", ""))[:200]
    # Формат Sheets API: {"error": {"status": "...", "message": "..."}}
    if isinstance(code, dict):
        return str(code.get("status", "")), str(code.get("message", ""))[:200]
    return "", ""


def _post_form(url: str, fields: dict[str, str]) -> dict:
    """
    POST у форматі `application/x-www-form-urlencoded` — так спілкується ендпоінт
    токенів Google (JSON він не приймає).

    Помилки перекладає у `GoogleAuthError`, окремо виділяючи `invalid_grant`.
    """
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, detail = _http_detail(e)
        log.error(f"OAuth: HTTP {e.code}, error={code}, {detail}")
        if code == "invalid_grant":
            raise GoogleAuthError(
                "Google відкликав доступ — потрібна повторна авторизація. "
                "Це буває, якщо доступ прибрали вручну в акаунті Google або "
                "програмою не користувались понад пів року."
            ) from e
        if code == "invalid_client":
            raise GoogleAuthError(
                "Google не впізнав OAuth-клієнта — завантажте client_secret.json ще раз."
            ) from e
        raise GoogleAuthError(f"Помилка авторизації Google: {code or e.code}. {detail}") from e
    except urllib.error.URLError as e:
        raise GoogleAuthError(f"Немає зв'язку з Google: {e.reason}") from e
    except socket.timeout as e:
        raise GoogleAuthError("Google не відповів вчасно.") from e

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise GoogleAuthError("Google повернув не-JSON у відповідь на запит токена.") from e
    if not isinstance(payload, dict):
        raise GoogleAuthError("Несподівана відповідь ендпоінта токенів Google.")
    return payload


# ─── Loopback-сервер для перехоплення redirect ────────────────────────────────

def _html_page(title: str, message: str) -> bytes:
    """Сторінка, яку побачить користувач у браузері після згоди."""
    return (
        "<!doctype html><html lang='uk'><head><meta charset='utf-8'>"
        f"<title>{title}</title></head>"
        "<body style=\"font-family:Segoe UI,sans-serif;background:#1e1e1e;color:#e6e6e6;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0\">"
        f"<div style='text-align:center'><h2>{title}</h2><p>{message}</p></div>"
        "</body></html>"
    ).encode("utf-8")


class _CallbackHandler(BaseHTTPRequestHandler):
    """Ловить єдиний GET-редірект від Google і кладе результат на сервер."""

    def do_GET(self) -> None:                                    # noqa: N802 (ім'я від BaseHTTP)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        # Браузер тягне /favicon.ico — це не наш редірект, мовчки відсікаємо
        if "code" not in params and "error" not in params:
            self.send_response(404)
            self.end_headers()
            return

        server = self.server
        if params.get("state", [""])[0] != server.expected_state:   # type: ignore[attr-defined]
            # Чужий запит на наш тимчасовий порт — не приймаємо його за відповідь Google
            server.auth_error = "Не збігся параметр state — авторизацію відхилено."  # type: ignore[attr-defined]
            page = _html_page("Авторизацію відхилено", "Спробуйте ще раз у програмі.")
        elif "error" in params:
            reason = params["error"][0]
            server.auth_error = (                                    # type: ignore[attr-defined]
                "Ви не надали дозвіл." if reason == "access_denied"
                else f"Google повернув помилку: {reason}"
            )
            page = _html_page("Дозвіл не надано", "Поверніться до програми.")
        else:
            server.auth_code = params["code"][0]                     # type: ignore[attr-defined]
            page = _html_page("Готово", "Авторизацію завершено — поверніться до програми.")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)
        server.done.set()                                            # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        """BaseHTTPRequestHandler за замовчуванням пише в stderr — у нас свій лог."""
        log.info("OAuth loopback: " + (fmt % args))


def _pkce_pair() -> tuple[str, str]:
    """
    PKCE: секрет і його SHA-256 у base64url без вирівнювання.

    Захищає обмін коду навіть якщо хтось перехопить редірект — для Desktop-клієнта
    це головний захист, бо `client_secret` там за визначенням не є таємницею.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize(client_id: str, client_secret: str, timeout_sec: int = 180) -> str:
    """
    Проводить повний OAuth-цикл і повертає `refresh_token`.

    Викликати ТІЛЬКИ у фоновому потоці (`gui/progress.BackgroundTask`): функція
    блокується, доки користувач не завершить згоду в браузері.

    ⚠️ `access_type=offline` і `prompt=consent` обов'язкові разом — без них Google
    віддасть лише access-токен, і після перезапуску програми доступ доведеться
    відновлювати вручну щоразу.
    """
    if not client_id or not client_secret:
        raise GoogleAuthError(
            "Спершу завантажте client_secret.json — без нього авторизувати нема чим."
        )

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    try:
        server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    except OSError as e:
        log.error(f"Не вдалося підняти loopback-сервер: {e}")
        raise GoogleAuthError(
            "Не вдалося відкрити локальний порт для відповіді Google — найпевніше "
            "заважає фаєрвол або антивірус."
        ) from e

    server.expected_state = state       # type: ignore[attr-defined]
    server.auth_code = ""               # type: ignore[attr-defined]
    server.auth_error = ""              # type: ignore[attr-defined]
    server.done = threading.Event()     # type: ignore[attr-defined]

    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = _AUTH_URL + "?" + urllib.parse.urlencode(params)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"OAuth: локальний сервер на порту {port}, відкриваю браузер.")

    try:
        if not webbrowser.open(auth_url):
            raise GoogleAuthError("Не вдалося відкрити браузер для авторизації.")
        if not server.done.wait(timeout_sec):    # type: ignore[attr-defined]
            raise GoogleAuthError(
                f"Авторизацію не завершено за {timeout_sec // 60} хв. Спробуйте ще раз."
            )
        if server.auth_error:                    # type: ignore[attr-defined]
            raise GoogleAuthError(server.auth_error)     # type: ignore[attr-defined]
        code = server.auth_code                  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()

    payload = _post_form(_TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })

    refresh_token = str(payload.get("refresh_token", ""))
    if not refresh_token:
        # Буває, якщо доступ уже було надано раніше, а prompt=consent не спрацював:
        # без refresh-токена програма змогла б писати лише до кінця цієї години.
        raise GoogleAuthError(
            "Google не повернув refresh-токен. Відкличте доступ програмі на "
            "myaccount.google.com/permissions і авторизуйтесь ще раз."
        )
    log.info("OAuth: refresh-токен отримано.")
    return refresh_token


# ─── Клієнт Sheets ────────────────────────────────────────────────────────────

class SheetsClient:
    """
    Читання й запис таблиці під OAuth-авторизацією.

    Клас, а не набір функцій, — бо між викликами треба тримати access-токен і час
    його протухання. Решта проєкту стилістично функційна; це свідомий виняток,
    альтернативою був би глобальний стан або запит нового токена на кожну дію.
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        if not refresh_token:
            raise GoogleAuthError("Немає авторизації Google — натисніть «Авторизувати».")
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str = ""
        self._expires_at: float = 0.0

    # ── токен ────────────────────────────────────────────────────────────────

    def _token(self) -> str:
        """Дійсний access-токен; оновлює його мовчки, коли час вийшов."""
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token

        log.info("OAuth: оновлюю access-токен.")
        payload = _post_form(_TOKEN_URL, {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        })
        token = str(payload.get("access_token", ""))
        if not token:
            raise GoogleAuthError("Google не повернув access-токен.")
        lifetime = int(payload.get("expires_in", 3600))
        self._access_token = token
        self._expires_at = time.monotonic() + max(lifetime - _TOKEN_LEEWAY_SEC, 60)
        return token

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _request(self, url: str, body: dict | None = None) -> dict:
        """
        Запит до Sheets API. ⚠️ Токен іде заголовком `Authorization: Bearer`,
        а не параметром URL (див. пастку 1 у докстрінгу модуля).
        """
        if body is None:
            request = urllib.request.Request(url, method="GET")
        else:
            request = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"), method="POST")
            request.add_header("Content-Type", "application/json; charset=utf-8")
        request.add_header("Authorization", "Bearer " + self._token())

        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, detail = _http_detail(e)
            message = self._explain_http(e.code, status, detail)
            log.error(f"Sheets: {message}")
            raise GoogleSheetsError(message) from e
        except urllib.error.URLError as e:
            raise GoogleSheetsError(f"Немає зв'язку з Google: {e.reason}") from e
        except socket.timeout as e:
            raise GoogleSheetsError("Google не відповів вчасно.") from e

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            log.error(f"Sheets: розбір JSON не вдався ({e.msg}, позиція {e.pos} "
                      f"з {len(raw)}). Початок відповіді: {raw[:200]}")
            raise GoogleSheetsError(f"Google повернув не-JSON ({e.msg}).") from e
        if not isinstance(payload, dict):
            raise GoogleSheetsError("Несподівана відповідь Sheets API.")
        return payload

    @staticmethod
    def _explain_http(code: int, status: str, detail: str) -> str:
        """Перекладає HTTP-помилку Sheets у текст, за яким видно, що робити."""
        if code == 401:
            return "HTTP 401 — авторизація не діє. Авторизуйтесь у Google заново."
        if code == 403:
            return ("HTTP 403 — обліковий запис, під яким пройшла авторизація, не має "
                    f"прав РЕДАКТОРА цієї таблиці (або вимкнено Sheets API). {detail}")
        if code == 404:
            return "HTTP 404 — таблицю не знайдено. Перевірте посилання."
        if code == 400:
            return f"HTTP 400 — некоректний запит (найімовірніше назва аркуша). {detail}"
        if code == 429:
            return "HTTP 429 — перевищено квоту запитів. Спробуйте за хвилину."
        return f"HTTP {code} {status}. {detail}"

    # ── аркуші ───────────────────────────────────────────────────────────────

    def list_sheets(self, sheet_url: str) -> list[str]:
        """Назви аркушів таблиці."""
        sheet_id = extract_id(sheet_url)
        payload = self._request(f"{_API_BASE}/{sheet_id}?fields=sheets.properties.title")
        return [
            s.get("properties", {}).get("title", "")
            for s in payload.get("sheets", [])
            if s.get("properties", {}).get("title")
        ]

    def _choose_sheet(self, sheet_url: str, requested: str) -> str:
        """
        Явно вказаний аркуш → автовизначення → перший.

        ⚠️ Та сама послідовність, що в `parsers/sheets_parser.read_sheet`, і саме
        тому важлива: у Sheets API поняття «активний аркуш» не існує, тож до
        побудови A1-діапазону назва має бути вже конкретною. Правило автовизначення
        не дублюється — воно живе в `parsers/table_rules.detect_sheet`; тут лише
        порядок фолбеків, який не можна винести, не правлячи читання авто-режиму.
        """
        titles = self.list_sheets(sheet_url)
        if not titles:
            raise GoogleSheetsError("У таблиці немає жодного аркуша.")
        if requested and requested in titles:
            return requested
        if requested:
            log.warning(f"Аркуш '{requested}' не знайдено — переходжу до автовизначення.")
        chosen = detect_sheet(titles) or titles[0]
        log.info(f"Аркуш для запису IP: '{chosen}'")
        return chosen

    # ── читання й запис ──────────────────────────────────────────────────────

    def read_columns(self, sheet_url: str, sheet: str,
                     columns: list[str]) -> tuple[str, list[list]]:
        """
        Читає діапазон від колонки A до дальшої з потрібних.

        Повертає `(назва аркуша, рядки)`. Назва повертається навмисно: викликач
        має писати в ТОЙ САМИЙ аркуш, який прочитав, а не визначати його вдруге.

        `valueRenderOption=UNFORMATTED_VALUE` — числа приходять числами, тож
        правило «комірка має бути чистим числом» працює так само, як для `.xlsx`.
        """
        sheet_id = extract_id(sheet_url)
        chosen = self._choose_sheet(sheet_url, sheet)
        last = max(col_index(c, "A") for c in columns) if columns else 0
        cell_range = f"{_quote_sheet(chosen)}!A:{_column_letter(last)}"
        url = (f"{_API_BASE}/{sheet_id}/values/{urllib.parse.quote(cell_range)}"
               f"?valueRenderOption=UNFORMATTED_VALUE")
        log.info(f"Sheets: читаю діапазон {cell_range}")
        payload = self._request(url)
        rows = payload.get("values", [])
        if not isinstance(rows, list):
            raise GoogleSheetsError("Несподіваний формат значень таблиці.")
        return chosen, rows

    def write_cells(self, sheet_url: str, sheet: str, updates: dict[str, str]) -> int:
        """
        Записує комірки одним запитом. `updates` — `{"K5": "10.0.0.7", ...}`,
        адреси без назви аркуша (її додаємо тут).

        Повертає кількість фактично оновлених комірок за відповіддю Google.

        ⚠️ Ендпоінт саме `values:batchUpdate` (значення), а не `:batchUpdate`
        (структура книги), і `valueInputOption` саме `RAW` — інакше Sheets має
        право переінтерпретувати записане.
        """
        if not updates:
            log.info("Sheets: писати нічого.")
            return 0
        sheet_id = extract_id(sheet_url)
        prefix = _quote_sheet(sheet)
        body = {
            "valueInputOption": "RAW",
            "data": [
                {"range": f"{prefix}!{cell}", "values": [[value]]}
                for cell, value in updates.items()
            ],
        }
        log.info(f"Sheets: записую {len(updates)} комірок на аркуш '{sheet}'.")
        payload = self._request(f"{_API_BASE}/{sheet_id}/values:batchUpdate", body=body)
        written = int(payload.get("totalUpdatedCells", 0))
        log.info(f"Sheets: оновлено {written} комірок.")
        return written
