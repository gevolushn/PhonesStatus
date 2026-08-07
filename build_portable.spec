# -*- mode: python ; coding: utf-8 -*-
"""
build_portable.spec — збірка portable .exe (один самодостатній файл).

Перед аналізом записує core/_build_dist.py з DISTRIBUTION="portable", щоб build_info.py
підхопив режим у бінарнику. НЕ патчить build_info.py — нема ризику зачепити GITHUB_TOKEN
(зникає клас багів «підмінив-не відновив» при падінні збірки). _build_dist.py — у .gitignore.

Збірка:  pyinstaller build_portable.spec
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

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/updater/updater.exe", "assets/updater"),  # вбудований updater для self-update
        ("assets/themes", "assets/themes"),
        ("assets/icons", "assets/icons"),
        ("assets/images", "assets/images"),
    ],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI-програма — без консолі
    disable_windowed_traceback=False,
    icon=_icon,
)
