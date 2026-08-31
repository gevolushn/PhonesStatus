"""
elevation.py — права адміністратора: перевірка, підвищення, розділення процесів. ЯДРО.

Головне правило шаблону (docs/DECISIONS.md): програма НІКОЛИ не вимагає адміністратора
«про всяк випадок». Якщо права потрібні для однієї операції — підвищується ОПЕРАЦІЯ, а
не вся програма. Тому основний патерн тут — run_elevated(): окремий маленький процес для
однієї дії (той самий принцип, що вже реалізований у assets/updater/updater.exe).

Дві різні перевірки, які легко переплутати:
    is_elevated()      — чи процес ЗАРАЗ підвищений (UAC elevated).
    is_admin_account()  — чи МІГ БИ поточний користувач узагалі підвищитись.
Друга потрібна, щоб не показувати кнопку «Запустити від адміністратора» людині, якій
вона однаково нічого не дасть.

Функції НЕ вирішують за викликача, чи виходити з процесу після підвищення — той самий
принцип, що вже діє для core.updater (on_ready_to_exit): ядро сигналить результат,
control-flow лишається за викликачем.

Внутрішні ctypes-виклики винесені в окремі приватні функції (`_open_process_token`,
`_get_elevation_flag`, ...) СВІДОМО: це шви для тестів. Реальний split-token сценарій
(адміністратор без підвищення) неможливо детерміновано відтворити в CI — тести
підміняють ці шви простими Python-значеннями, а не борються з ctypes-структурами.

Нуль зовнішніх залежностей — тільки ctypes, як core/instance_lock.py.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from core.logger import log

# ── ctypes: сигнатури обов'язкові на x64 (клас багів, описаний для DPAPI) ──────

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

_kernel32.GetCurrentProcess.argtypes = []
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [wintypes.HANDLE]
_kernel32.LocalFree.restype = wintypes.HANDLE

_advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
_advapi32.GetTokenInformation.restype = wintypes.BOOL
_advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
_advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
_advapi32.CheckTokenMembership.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL),
]
_advapi32.CheckTokenMembership.restype = wintypes.BOOL

class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
_shell32.ShellExecuteExW.restype = wintypes.BOOL

_SEE_MASK_FLAG_NO_UI = 0x00000400   # придушує ВЛАСНІ діалоги ShellExecute (не UAC-запит)

_TOKEN_QUERY = 0x0008
_TokenElevation = 20          # TOKEN_INFORMATION_CLASS
_TokenElevationType = 18
_TokenLinkedToken = 19
TOKEN_ELEVATION_TYPE_DEFAULT = 1
TOKEN_ELEVATION_TYPE_FULL = 2
TOKEN_ELEVATION_TYPE_LIMITED = 3

_SW_SHOWNORMAL = 1
_ERROR_CANCELLED = 1223        # UAC-діалог: користувач натиснув «Ні»
_ADMINISTRATORS_SID = "S-1-5-32-544"   # well-known SID, однаковий на всіх Windows


# ── Шви: тонкі обгортки над ctypes, підміняються в тестах ─────────────────────

def _open_process_token() -> wintypes.HANDLE | None:
    h_token = wintypes.HANDLE()
    ok = _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(h_token))
    return h_token if ok else None


def _close_handle(handle) -> None:
    if handle:
        _kernel32.CloseHandle(handle)


def _get_elevation_flag(h_token) -> bool | None:
    """TokenElevation → True/False, або None якщо запит не вдався."""
    val = wintypes.DWORD()
    size = wintypes.DWORD()
    ok = _advapi32.GetTokenInformation(
        h_token, _TokenElevation, ctypes.byref(val), ctypes.sizeof(val), ctypes.byref(size)
    )
    return bool(val.value) if ok else None


def _get_elevation_type(h_token) -> int | None:
    """TokenElevationType → TOKEN_ELEVATION_TYPE_*, або None якщо запит не вдався."""
    val = wintypes.DWORD()
    size = wintypes.DWORD()
    ok = _advapi32.GetTokenInformation(
        h_token, _TokenElevationType, ctypes.byref(val), ctypes.sizeof(val), ctypes.byref(size)
    )
    return val.value if ok else None


def _get_linked_token(h_token) -> wintypes.HANDLE | None:
    linked = wintypes.HANDLE()
    size = wintypes.DWORD()
    ok = _advapi32.GetTokenInformation(
        h_token, _TokenLinkedToken, ctypes.byref(linked), ctypes.sizeof(linked), ctypes.byref(size)
    )
    return linked if (ok and linked) else None


def _is_member_of_administrators(h_token) -> bool:
    admin_sid = wintypes.LPVOID()
    if not _advapi32.ConvertStringSidToSidW(_ADMINISTRATORS_SID, ctypes.byref(admin_sid)):
        return False
    try:
        is_member = wintypes.BOOL()
        ok = _advapi32.CheckTokenMembership(h_token, admin_sid, ctypes.byref(is_member))
        return bool(ok) and bool(is_member.value)
    finally:
        _kernel32.LocalFree(admin_sid)


def _shell_execute_runas(exe: str, args: str) -> int:
    """
    Запускає exe з verb='runas' через ShellExecuteExW. Повертає 0 при успіху, інакше
    справжній Win32-код помилки з GetLastError().

    ⚠️ НЕ ShellExecuteW (без Ex): та легасі-функція повертає лише коди SE_ERR_* у
    діапазоні 0-32, і НЕ дає надійного способу відрізнити «користувач натиснув Ні в
    UAC» від інших відмов — перевірку впіймав власний тест цього модуля:
    `ShellExecuteW` міг повернути 1223 (справжній ERROR_CANCELLED) як значення, а
    контракт «> 32 = успіх» трактував це як УСПІХ. `ShellExecuteExW` + `GetLastError()`
    дає задокументований, однозначний код.
    """
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    info.fMask = _SEE_MASK_FLAG_NO_UI
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = args
    info.lpDirectory = None
    info.nShow = _SW_SHOWNORMAL
    info.hInstApp = None
    info.lpIDList = None
    info.lpClass = None
    info.hkeyClass = None
    info.dwHotKey = 0
    info.hIconOrMonitor = None
    info.hProcess = None

    if _shell32.ShellExecuteExW(ctypes.byref(info)):
        return 0
    return ctypes.get_last_error()


# ── Перевірки (орендують лише шви вище — самі не торкаються ctypes) ────────────

def is_elevated() -> bool:
    """
    Чи процес ЗАРАЗ запущений із підвищеними правами (UAC elevated).

    Через GetTokenInformation(TokenElevation), НЕ через застарілий IsUserAnAdmin() —
    той перевіряє членство в групі Administrators, а не фактичний стан UAC-токена, і
    дає хибний результат на фільтрованому токені адміністратора, що не підвищився.
    """
    h_token = _open_process_token()
    if h_token is None:
        return False   # не вдалось дізнатись — консервативний дефолт
    try:
        return bool(_get_elevation_flag(h_token))
    finally:
        _close_handle(h_token)


def is_admin_account() -> bool:
    """
    Чи МІГ БИ поточний користувач узагалі підвищитись — незалежно від того, чи
    процес ЗАРАЗ elevated.

    UAC розщеплює токен адміністратора на два: обмежений (яким процес запускається
    типово) і повний (linked token, доступний через 'runas'). Обмежений токен формально
    МАЄ групу Administrators, але в стані USE_FOR_DENY_ONLY — перевірка членства напряму
    на ньому мовчки бреше і повертає False. Тому для TokenElevationTypeLimited треба
    дістати TokenLinkedToken і перевіряти членство вже на ньому (задокументований підхід
    Microsoft; той самий, що використовують інсталятори для показу UAC-щита на кнопці).

    ⚠️ Живою перевіркою (не-інтерактивне середовище цієї сесії розробки) виявлено
    справжній нетиповий випадок: `TokenElevationType` міг лишатись `Default` навіть коли
    `TokenElevation` = True (процес не в звичайній інтерактивній UAC-сесії — сервіс,
    автоматизація, нестандартний спосіб запуску). Тому першою перевіряємо саме прапорець
    елевації: «зараз підвищений» логічно ЗАВЖДИ означає «є адміністратором», незалежно
    від того, яку саме форму мав токен — це страховка проти нетипових середовищ, а не
    заміна основного алгоритму.
    """
    h_token = _open_process_token()
    if h_token is None:
        return False
    try:
        if _get_elevation_flag(h_token):
            return True   # процес уже підвищений -> користувач точно адміністратор
        elevation_type = _get_elevation_type(h_token)
        if elevation_type == TOKEN_ELEVATION_TYPE_FULL:
            return True
        if elevation_type == TOKEN_ELEVATION_TYPE_LIMITED:
            linked = _get_linked_token(h_token)
            if linked is None:
                return False
            try:
                return _is_member_of_administrators(linked)
            finally:
                _close_handle(linked)
        # TokenElevationTypeDefault: UAC вимкнений АБО система без split-token (рідко) —
        # членство перевіряємо напряму на наявному токені.
        return _is_member_of_administrators(h_token)
    finally:
        _close_handle(h_token)


def requires_admin_for(path: str) -> bool:
    """
    Чи потрібні підвищені права, щоб писати за цим шляхом — пробним файлом, НЕ os.access.

    os.access(path, os.W_OK) на Windows дивиться лише на атрибут «тільки читання» і
    нічого не знає ні про ACL, ні про права на мережевому ресурсі — рапортує «можна»
    там, де перший запис впаде. True тут означає лише «зараз сюди не пишеться»: причиною
    може бути й не брак прав (диск лише для читання, мережевий ресурс відпав) — але для
    типового кейсу (Program Files) це і є відповідь на питання елевації.
    """
    probe = os.path.join(path, f".elevation_probe_{os.getpid()}")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8"):
            pass
    except OSError:
        return True
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return False


# ── Підвищення ───────────────────────────────────────────────────────────────

def _handle_runas_result(code: int) -> bool:
    if code == 0:
        return True
    if code == _ERROR_CANCELLED:
        log.info("Користувач відмовився підвищувати права (UAC).")
    else:
        log.warning(f"Не вдалося запустити з підвищеними правами: код {code}.")
    return False


def relaunch_as_admin(exe: str | None = None, args: str = "") -> bool:
    """
    Готує перезапуск ПОТОЧНОЇ програми з підвищеними правами (UAC-запит).

    Не викликає sys.exit() сам — control-flow лишається за викликачем (той самий
    принцип, що й core.updater.launch_update: ядро сигналить, не вирішує). Типове
    використання: `if relaunch_as_admin(): sys.exit(0)`.

    Відмова користувача в UAC-діалозі (ERROR_CANCELLED) — це його ВИБІР, не помилка;
    викликач не повинен показувати її як збій.
    """
    code = _shell_execute_runas(exe or sys.executable, args)
    return _handle_runas_result(code)


def run_elevated(exe: str, args: str = "") -> bool:
    """
    Запускає ОКРЕМИЙ допоміжний процес з підвищеними правами, не чіпаючи поточний.

    Патерн «розділення процесів» (рекомендований у docs/DECISIONS.md): підвищується
    операція, а не вся програма. `exe` — маленький бінарник для однієї дії (аналог
    assets/updater/updater.exe), НЕ сама програма.
    """
    code = _shell_execute_runas(exe, args)
    return _handle_runas_result(code)
