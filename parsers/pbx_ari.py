"""
pbx_ari.py — авто-режим АТС: статуси extension'ів через Asterisk REST Interface.

Один запит `GET {base_url}/endpoints` із Basic-авторизацією віддає JSON-масив:
    [{"technology": "PJSIP", "resource": "1001", "state": "online", "channel_ids": []}, ...]

Перевірено на бойовій АТС (Asterisk 18.13 / FreePBX 16.0.45, 224 endpoints, HTTP 200):
станів лише два — `online` / `offline`, жодного `unknown`.

Чому саме ARI, а не GraphQL/REST самого FreePBX: ті віддають лише СТАТИЧНУ
конфігурацію extension'а (`fetchAllExtensions`), а стан реєстрації живе в Asterisk.
Це відома незакрита обмеженість FreePBX, не помилка налаштування.

Контракт (спільний із `parsers/pbx_manual.py`): `dict[номер, 'ON'|'OFF']`.
Залежностей немає — лише `urllib` зі stdlib.

Передумови на боці АТС (разове налаштування):
  - увімкнений Asterisk Builtin mini-HTTP Server, Bind Address 0.0.0.0, порт 8088;
  - користувач у Settings → Asterisk REST Interface Users, Read Only = Yes.
"""
from __future__ import annotations

import base64
import json
import re
import socket
import ssl
import urllib.error
import urllib.request

from core.logger import log

_TIMEOUT_SEC: int = 10

# Ті самі 3-5 цифр, що й у ручному режимі: відсіює трункові псевдо-endpoint'и
# (`SipProvider`, `To_Yeastar`) БЕЗ окремого списку виключень — вони просто не числа.
_RE_EXTENSION = re.compile(r"^\d{3,5}$")


class AriError(Exception):
    """Помилка звернення до ARI з готовим до показу користувачеві текстом."""


def _build_request(base_url: str, user: str, password: str) -> urllib.request.Request:
    """Готує GET-запит до /endpoints із заголовком Basic-авторизації."""
    url = base_url.rstrip("/") + "/endpoints"
    req = urllib.request.Request(url, method="GET")
    credentials = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", "Basic " + credentials)
    return req


def _ssl_context(url: str, insecure: bool) -> ssl.SSLContext | None:
    """Для https з самопідписаним сертифікатом FreePBX — контекст без перевірки."""
    if not (url.lower().startswith("https") and insecure):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _explain(exc: Exception) -> str:
    """Перекладає виняток мережі/HTTP у текст, за яким видно, що робити."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return ("HTTP 401 — невірний логін або пароль ARI, або користувача немає "
                    "в Settings → Asterisk REST Interface Users.")
        if exc.code == 403:
            return "HTTP 403 — користувачу заборонено доступ (перевірте права)."
        if exc.code == 404:
            return "HTTP 404 — перевірте адресу: вона має закінчуватись на /ari."
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return ("Помилка TLS-сертифіката. FreePBX має самопідписаний сертифікат — "
                    "увімкніть «Ігнорувати помилки сертифіката» в налаштуваннях.")
        if isinstance(reason, socket.timeout):
            return ("Таймаут. Сервер недоступний, HTTP-сервер Asterisk слухає лише "
                    "127.0.0.1 (потрібен Bind Address 0.0.0.0), або блокує фаєрвол.")
        if isinstance(reason, ConnectionRefusedError):
            return ("З'єднання відхилено — Asterisk Builtin mini-HTTP Server вимкнений "
                    "або вказано невірний порт (типово 8088).")
        return f"Помилка мережі: {reason}"
    if isinstance(exc, socket.timeout):
        return "Таймаут підключення до АТС."
    return f"{type(exc).__name__}: {exc}"


def read_ari(base_url: str, user: str, password: str, insecure_tls: bool = False) -> dict[str, str]:
    """
    Забирає статуси всіх PJSIP-endpoint'ів з Asterisk ARI.

    Повертає `dict[номер, 'ON'|'OFF']`. Нечислові ресурси (транки `SipProvider`,
    `To_Yeastar`) і стани поза `online`/`offline` тихо пропускаються — у порівняння
    мають потрапляти лише справжні внутрішні номери.

    Кидає `AriError` із текстом, придатним для показу користувачеві.
    """
    if not base_url or not user:
        raise AriError("Не заповнені адреса ARI або логін — перевірте налаштування.")

    log.info(f"ARI-запит: {base_url.rstrip('/')}/endpoints")
    try:
        request = _build_request(base_url, user, password)
        context = _ssl_context(base_url, insecure_tls)
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC, context=context) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception as e:
        message = _explain(e)
        log.error(f"ARI: {message}")
        raise AriError(message) from e

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        log.error(f"ARI повернув не-JSON: {body[:200]}")
        raise AriError("АТС повернула не-JSON — перевірте, що адреса вказує на ARI.") from e

    if not isinstance(payload, list):
        raise AriError("Несподівана відповідь ARI: очікувався список endpoints.")

    phones: dict[str, str] = {}
    skipped = 0
    for endpoint in payload:
        resource = str(endpoint.get("resource", ""))
        state = str(endpoint.get("state", "")).strip().lower()
        if not _RE_EXTENSION.match(resource):
            skipped += 1
            continue
        if state == "online":
            phones[resource] = "ON"
        elif state == "offline":
            phones[resource] = "OFF"
        else:
            skipped += 1

    log.info(f"ARI: отримано {len(payload)} endpoints, взято {len(phones)}, пропущено {skipped}.")
    if not phones:
        raise AriError("АТС не повернула жодного внутрішнього номера (3-5 цифр).")
    return phones
