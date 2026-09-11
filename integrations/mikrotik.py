"""
mikrotik.py — поточні IP телефонів з DHCP-lease роутера MikroTik.

Один запит `GET {url}/rest/ip/dhcp-server/lease` із Basic-авторизацією віддає
JSON-масив lease. Залежностей немає — лише `urllib` зі stdlib.

⚠️ REST живе на вебсервісі `www-ssl`, а НЕ на `api`/`api-ssl`. Попри назву, «API»
у MikroTik — окремий бінарний протокол на портах 8728/8729; він вимагав би або
pip-бібліотеки, або ~150 рядків саморобної реалізації протоколу. REST — це urllib.
Сервіси `api`/`api-ssl` лишаються вимкненими.

Передумови на боці роутера (разове налаштування):
  - `/user group add name=api-ro policy=read,rest-api` + користувач у цій групі
    (політика `api` ЗАЙВА — вона про бінарний API);
  - `www-ssl` увімкнений із дійсним сертифікатом; порт у бойовій конфігурації
    не 443, а 8443 — тому URL вводиться З ПОРТОМ;
  - `chain=input` має пропускати TCP на цей порт із машини, де працює програма.

Формат відповіді перевірено на бойовому CCR1016-12G (RouterOS 7.16.1):
  {".id": "*86BEF2", "address": "10.0.0.5", "active-address": "10.0.0.5",
   "mac-address": "00:04:13:D8:CA:40", "dynamic": "true", "status": "bound",
   "expires-after": "3m50s", "last-seen": "1m10s", "server": "DHCP_MAIN"}

Три факти з реальних даних, кожен здатний зламати наївну реалізацію:
  1. Булеві поля приходять РЯДКАМИ: `"dynamic": "false"`, не `False`.
  2. У неактивного lease ключа `active-address` НЕМАЄ ВЗАГАЛІ — REST опускає
     незаповнені поля. Перевірка `lease["active-address"] == ""` дала б KeyError.
  3. `status` у статичного офлайн-lease — `"waiting"`, а не `"bound"`. Тому
     `status` тут не читається взагалі: інтуїтивна перевірка на `bound` хибила б
     саме на тому випадку, заради якого модуль і писався.

⚠️ Межа застосовності. `active-address` — індикатор ПРИВ'ЯЗКИ, а не живості:
після зникнення пристрою lease лишається заповненим до кінця `lease-time`. На цьому
розгортанні `expires-after` ≈ 4 хвилини, тож вікно застарілості мізерне. Якщо
lease-time колись подовжать до годин — правило почне брехати, і його треба переглянути.
"""
from __future__ import annotations

import base64
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from typing import Iterable

from core.logger import log

_TIMEOUT_SEC: int = 10
_ENDPOINT: str = "/rest/ip/dhcp-server/lease"

DASH: str = "—"
"""Прочерк для телефона, якого немає в мережі. ЄДИНЕ місце, де живе це значення."""

_RE_NOT_HEX = re.compile(r"[^0-9A-Fa-f]")
_RE_MAC12 = re.compile(r"^[0-9A-F]{12}$")


class MikrotikError(Exception):
    """Помилка звернення до роутера з готовим до показу користувачеві текстом."""


# ─── MAC ──────────────────────────────────────────────────────────────────────

def normalize_mac(value: str) -> str:
    """
    Зводить MAC до 12 великих hex-символів без роздільників.

    Роутер віддає `AA:BB:CC:DD:EE:FF`, а в таблиці той самий MAC може бути
    записаний як `aa-bb-cc-dd-ee-ff`, `aabb.ccdd.eeff` чи в іншому регістрі —
    зіставляти їх можна лише в одній формі.

    Повертає "" для порожнього чи сміттєвого значення (не рівно 12 hex) —
    такий рядок таблиці далі просто пропускається.
    """
    cleaned = _RE_NOT_HEX.sub("", str(value or "")).upper()
    return cleaned if _RE_MAC12.match(cleaned) else ""


# ─── Мережа ───────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """
    Доводить адресу роутера до вигляду, придатного для urllib.

    Без схеми urllib падає невиразним `ValueError: unknown url type`, а користувач
    цілком природно вписує `192.168.0.1:8443`. Дописуємо https, бо REST обслуговує
    саме `www-ssl`.
    """
    address = str(url or "").strip().rstrip("/")
    if address and "://" not in address:
        address = "https://" + address
    return address


def _build_request(url: str, user: str, password: str) -> urllib.request.Request:
    """Готує GET-запит до lease-таблиці із заголовком Basic-авторизації."""
    request = urllib.request.Request(_normalize_url(url) + _ENDPOINT, method="GET")
    credentials = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", "Basic " + credentials)
    return request


def _ssl_context(url: str) -> ssl.SSLContext | None:
    """
    Контекст без перевірки сертифіката для https.

    На відміну від ARI, прапорця в налаштуваннях тут свідомо НЕМАЄ: сертифікат
    `www-ssl` самопідписаний за визначенням (створюється на самому роутері), тож
    перевірка не пройшла б ніколи, а ключ конфігу лише вдавав би вибір.
    """
    if not _normalize_url(url).lower().startswith("https"):
        return None
    context = ssl.create_default_context()
    context.check_hostname = False          # ⚠️ тільки в цьому порядку:
    context.verify_mode = ssl.CERT_NONE     #    зворотний дає ValueError
    return context


def _explain(exc: Exception) -> str:
    """Перекладає виняток мережі/HTTP у текст, за яким видно, що робити."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return "HTTP 401 — невірний логін або пароль користувача MikroTik."
        if exc.code == 403:
            return ("HTTP 403 — групі користувача бракує політики `rest-api` "
                    "(потрібні `read` і `rest-api`).")
        if exc.code == 404:
            return ("HTTP 404 — REST не знайдено. Потрібен RouterOS 7.x; перевірте, "
                    "що в адресі лише хост і порт, без шляху.")
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return ("Помилка TLS. Найпевніше, на цьому порті не HTTPS — REST "
                    "обслуговує сервіс `www-ssl`, а не `www`.")
        if isinstance(reason, socket.timeout):
            return ("Таймаут. Пакет не доходить до роутера: перевірте правило "
                    "`chain=input` для TCP на цей порт і сам порт в IP → Services.")
        if isinstance(reason, ConnectionRefusedError):
            return ("З'єднання відхилено — сервіс `www-ssl` вимкнений або слухає "
                    "інший порт (типово перевішений на 8443).")
        return f"Помилка мережі: {reason}"
    if isinstance(exc, socket.timeout):
        return "Таймаут підключення до роутера."
    return f"{type(exc).__name__}: {exc}"


def read_leases(url: str, user: str, password: str) -> list[dict]:
    """
    Забирає повну таблицю DHCP-lease роутера.

    Повертає список словників «як є» — інтерпретація живе в `_lease_ip`.
    Кидає `MikrotikError` із текстом, придатним для показу користувачеві.
    """
    if not url or not user:
        raise MikrotikError("Не заповнені адреса роутера або логін — перевірте налаштування.")

    log.info(f"MikroTik-запит: {_normalize_url(url)}{_ENDPOINT}")
    try:
        request = _build_request(url, user, password)
        context = _ssl_context(url)
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SEC, context=context) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception as e:
        message = _explain(e)
        log.error(f"MikroTik: {message}")
        raise MikrotikError(message) from e

    try:
        # ⚠️ strict=False ОБОВ'ЯЗКОВИЙ, і це не послаблення «про всяк випадок».
        # RouterOS кладе в JSON значення полів «як є», не екрануючи керуючі символи.
        # Поле `class-id` (DHCP Option 60, Vendor Class Identifier) надсилає САМ
        # клієнтський пристрій — і на бойовій мережі знайшовся телефон, чий class-id
        # містить нульовий байт. RFC 8259 забороняє U+0000..U+001F усередині рядків,
        # тож strict-розбір валив ВЕСЬ запит (424 КБ, ~1500 lease) через один байт
        # в одному полі, якого ми навіть не читаємо.
        payload = json.loads(body, strict=False)
    except json.JSONDecodeError as e:
        # Позиція і причина — у лог: без них «не-JSON» відсилає шукати проблему
        # в адресі й порті, тобто рівно не туди, де вона є.
        log.error(f"MikroTik: розбір JSON не вдався ({e.msg}, позиція {e.pos} "
                  f"з {len(body)}). Початок відповіді: {body[:200]}")
        raise MikrotikError(
            f"Роутер повернув відповідь, яку не вдалося розібрати ({e.msg}). "
            f"Подробиці — у файлі логу."
        ) from e

    if not isinstance(payload, list):
        raise MikrotikError("Несподівана відповідь роутера: очікувався список lease.")

    log.info(f"MikroTik: отримано {len(payload)} lease.")
    return payload


# ─── Правило чотирьох випадків ────────────────────────────────────────────────

def _is_static(lease: dict) -> bool:
    """
    Чи є lease статичним (зарезервованим вручну).

    RouterOS REST віддає булеві поля рядками, а в CLI те саме показується як
    `yes`/`no` — тому приймаємо обидві форми. Невідоме або відсутнє значення
    вважаємо ДИНАМІЧНИМ навмисно: записати чужу адресу гірше, ніж прочерк.
    """
    return str(lease.get("dynamic", "true")).strip().lower() in ("false", "no")


def _lease_ip(lease: dict) -> str:
    """
    Правило чотирьох випадків: що саме писати в таблицю для знайденого lease.

      active-address заповнене          → active-address (пристрій у мережі)
      порожнє, lease статичний          → address (зарезервований за ним IP)
      порожнє, lease динамічний         → прочерк
      (четвертий випадок — MAC узагалі не знайдено — обробляє resolve_ips)

    Порядок перевірки має значення: у статичного АКТИВНОГО lease `address` і
    `active-address` можуть розійтись, і правильна саме активна адреса.
    """
    active = str(lease.get("active-address", "") or "").strip()
    if active:
        return active
    if _is_static(lease):
        reserved = str(lease.get("address", "") or "").strip()
        if reserved:
            return reserved
    return DASH


def resolve_ips(url: str, user: str, password: str, macs: Iterable[str]) -> dict[str, str]:
    """
    Головна функція модуля: список MAC → `dict[нормалізований MAC, IP або прочерк]`.

    Один мережевий запит на весь виклик, не по одному на MAC. Порожні й сміттєві
    MAC відкидаються ще до запиту; якщо валідних не лишилось — до роутера не йдемо.

    Кидає `MikrotikError`.
    """
    wanted = {normalize_mac(mac) for mac in macs}
    wanted.discard("")
    if not wanted:
        log.info("MikroTik: у таблиці немає жодного валідного MAC — запит не потрібен.")
        return {}

    leases = read_leases(url, user, password)

    # Індекс за MAC самого lease. ⚠️ Саме `mac-address`, а не `active-mac-address`:
    # другий — MAC клієнта, що зараз тримає адресу; у нормі вони збігаються, але
    # покладатись на це не можна.
    index: dict[str, dict] = {}
    duplicates = 0
    for lease in leases:
        key = normalize_mac(lease.get("mac-address", ""))
        if not key:
            continue
        if key in index:
            duplicates += 1     # роутер тримає кілька DHCP-серверів; перемагає останній
        index[key] = lease

    result = {mac: (_lease_ip(index[mac]) if mac in index else DASH) for mac in wanted}
    found = sum(1 for ip in result.values() if ip != DASH)
    log.info(f"MikroTik: запитано {len(wanted)} MAC, з IP {found}, "
             f"прочерків {len(wanted) - found}, дублів у lease {duplicates}.")
    return result
