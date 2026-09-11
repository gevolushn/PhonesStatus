# -*- mode: python ; coding: utf-8 -*-
"""
build_portable_bare.spec — portable .exe БЕЗ вбудованого updater.exe.

Відмінність від `build_portable.spec` рівно в одному: не вшивається
`assets/updater/updater.exe` і немає перевірки на його наявність. Решта
(тип дистрибуції, ім'я, upx=False, console=False, іконка) — ідентична.

Навіщо окремий файл, а не правка канонічного: `build_portable.spec` приїхав із
шаблону й описує ШТАТНУ збірку з автооновленням. Прибрати звідти updater означало б
тихо зламати реліз, коли до нього дійде черга. Тут — свідомо урізаний варіант
«просто працююча програма».

⚠️ Наслідок: самооновлення в цій збірці НЕ ПРАЦЮЄ.
`core/updater.py` лишається в коді, але `_apply_portable()` не знайде `updater.exe`
і чесно повідомить про помилку. Автоперевірка за замовчуванням вимкнена
(`update_check: "never"`), тож у звичайній роботі це не проявиться взагалі.
Для релізу з оновленням — збирати `build_portable.spec`, попередньо зібравши
`assets/updater/updater.exe` (див. README).

Збірка:  pyinstaller build_portable_bare.spec
Результат: dist/{APP_NAME}_{APP_VERSION}_portable.exe
"""
import os
import re

# ── Записати тип дистрибуції (build-generated, gitignored) ────────────────────
with open(os.path.join("core", "_build_dist.py"), "w", encoding="utf-8") as _f:
    _f.write('DISTRIBUTION = "portable"\n')


def _read_const(name: str) -> str:
    """Дістає рядкову константу з core/build_info.py без виконання модуля."""
    src = open(os.path.join("core", "build_info.py"), encoding="utf-8").read()
    m = re.search(rf'^{name}\s*[:=].*?["\']([^"\']+)["\']', src, re.M)
    return m.group(1) if m else name


APP_NAME = _read_const("APP_NAME")
APP_VERSION = _read_const("APP_VERSION")

_icon = os.path.join("assets", "icons", "app.ico")
_icon = _icon if os.path.isfile(_icon) else None

# Вкладаємо лише ті теки assets, які реально існують і не порожні: PyInstaller
# на порожній теці нічого не додає, але шумить попередженням.
_datas = []
for _sub in ("themes", "icons", "images"):
    _path = os.path.join("assets", _sub)
    if os.path.isdir(_path) and os.listdir(_path):
        _datas.append((_path, f"assets/{_sub}"))

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f"{APP_NAME}_{APP_VERSION}_portable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False СВІДОМО: пакування — сильний антивірусний тригер.
    # Рішення й обґрунтування — docs/DECISIONS.md шаблону.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI-програма — без консолі
    disable_windowed_traceback=False,
    icon=_icon,
)
