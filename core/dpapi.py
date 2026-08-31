"""
dpapi.py — шифрування окремих полів конфігу через Windows DPAPI. ЯДРО (проєктне).

Навіщо. У `data/settings.json` лежить пароль ARI-користувача Asterisk. Тримати його
відкритим текстом не хочеться, а обфускація рівня XOR+Base64 (опційний
`optional_modules/core/crypto.py` шаблону, у проєкт свідомо не брали) захисту не дає
взагалі: ключ виводиться з `SECRET_KEY` і вшитий у .exe — дістається `strings` за секунди.

DPAPI (`CryptProtectData`/`CryptUnprotectData`) — рідний механізм Windows: ключ
виводиться з облікового запису користувача і зберігається операційною системою.
Файл, скопійований на інший ПК або в інший обліковий запис, **не розшифрується**.
Зовнішніх залежностей немає — лише `ctypes` зі stdlib (той самий підхід, що в
`core/instance_lock.py` та `core/elevation.py`).

Межі захисту (важливо розуміти, а не вірити в магію):
  - зловмисник, який виконує код ПІД ВАШИМ обліковим записом, розшифрує так само легко;
  - DPAPI захищає від копіювання файлу, не від локального зловмисника;
  - зміна `APP_NAME` міняє ентропію (`build_info.SECRET_KEY`) → раніше зашифровані
    поля стають нечитабельними і їх треба ввести заново. Це очікувано, не баг.

Формат токена: `dpapi:<base64>`. Значення без префіксу вважається відкритим текстом —
так конфіг, створений до підключення модуля (або збережений при недоступному DPAPI),
читається без окремої міграції `config_version`.

⚠️ Походження: модуль обкатано в проєкті TelegramSenderBot; у Python App Template його
немає — там лише специфікація (`docs/BACKLOG.md`, дефект D-38). Кандидат на промоцію
в шаблон за `HOW_INTEGRATE_NEW_MODULES.md`, Частина B.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

from core.build_info import SECRET_KEY
from core.logger import log

PREFIX: str = "dpapi:"

_CRYPTPROTECT_UI_FORBIDDEN = 0x01   # без діалогів — програма може працювати у фоні/треї


class _DataBlob(ctypes.Structure):
    """DATA_BLOB із wincrypt.h — пара (довжина, вказівник на буфер)."""
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


# use_last_error=True — інакше ctypes.get_last_error() поверне сміття від сторонніх викликів.
_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Явні сигнатури обов'язкові на x64: без них ctypes вважає, що функція повертає int,
# і 64-бітний вказівник мовчки обрізається до 32 біт.
_PBLOB = ctypes.POINTER(_DataBlob)
for _fn in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
    _fn.restype = wintypes.BOOL
    _fn.argtypes = [_PBLOB, wintypes.LPCWSTR, _PBLOB, ctypes.c_void_p,
                    ctypes.c_void_p, wintypes.DWORD, _PBLOB]
_kernel32.LocalFree.restype = ctypes.c_void_p
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]


def _to_blob(data: bytes) -> _DataBlob:
    """Загортає bytes у DATA_BLOB (буфер копіюється — Python тримає посилання)."""
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _DataBlob) -> bytes:
    """Витягує bytes із DATA_BLOB і звільняє пам'ять, виділену Windows (LocalFree)."""
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def is_available() -> bool:
    """Чи працює DPAPI у цій системі (перевірка одним циклом encrypt→decrypt)."""
    try:
        return unprotect(protect("probe")) == "probe"
    except Exception as e:
        log.warning(f"DPAPI недоступний: {e}")
        return False


def is_protected(value: str) -> bool:
    """Чи є значення DPAPI-токеном (а не відкритим текстом)."""
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(text: str) -> str:
    """
    Шифрує рядок і повертає токен `dpapi:<base64>`.

    Порожній рядок повертається як є: шифрувати «нічого» немає сенсу, а порожнє
    значення в конфігу має лишатись видимо порожнім.
    """
    if not text:
        return ""
    data_in = _to_blob(text.encode("utf-8"))
    entropy = _to_blob(SECRET_KEY.encode("utf-8"))
    data_out = _DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return PREFIX + base64.b64encode(_from_blob(data_out)).decode("ascii")


def unprotect(token: str) -> str:
    """
    Розшифровує токен `dpapi:<base64>`. Значення без префіксу повертається як є
    (відкритий текст — див. docstring модуля).
    """
    if not token or not is_protected(token):
        return token or ""
    raw = base64.b64decode(token[len(PREFIX):].encode("ascii"))
    data_in = _to_blob(raw)
    entropy = _to_blob(SECRET_KEY.encode("utf-8"))
    data_out = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return _from_blob(data_out).decode("utf-8")
