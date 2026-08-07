# PhonesStatus

Порівнює статуси внутрішніх телефонів між таблицею Excel і поточним станом FreePBX:
показує, які номери підключились, а які відключились.

---

## Як користуватись

1. Вкажіть файл таблиці телефонів (`.xlsx`) — поле **«Таблиця Excel»** або кнопка **«Огляд…»**.
2. У FreePBX скопіюйте список **Online** і вставте у ліве поле, список **Offline** — у праве.
   Формат довільний: підходить і таблиця виду `PJSIP  1001  0`, і голий стовпчик номерів.
3. Натисніть **«▶ Порівняти»**.
4. Результат — кольоровий звіт: `↑ підключився` (зелений) і `↓ відключився` (червоний).
   Кнопка **«💾 Зберегти TXT»** вивантажує той самий звіт у текстовий файл.

Шлях до таблиці, розмір і позиція вікна та вибрана тема зберігаються між запусками
(`data/settings.json`).

### Що саме порівнюється

- З таблиці беруться **колонка F** («Внутрішній») і **колонка H** («Статус», `ON`/`OFF`)
  з аркуша, у назві якого є «телефон» (аркуші зі словами `старий`, `copy of`, `експорт`
  ігноруються; якщо підходять кілька — береться останній).
- Зі вставленого тексту беруться числа з **3–5 цифр**, записані окремим словом
  (`PJSIP  1001  0` → `1001`). Номер усередині більшого токена — напр. `SIP/1005-00001` —
  **не** розпізнається.
- У звіт потрапляють **лише номери, присутні в обох джерелах**, і **лише ті, де статус
  відрізняється**. Якщо номер опинився і в Online, і в Offline — перемагає Offline.

---

## Запуск для розробки

```bash
pip install -r requirements.txt
python main.py
```

## Перша збірка: updater.exe (один раз)

Шаблон постачає `assets/updater/updater_src.py`, але **не** зібраний `updater.exe`.
Перед першою portable-збіркою зберіть його один раз:

```bash
cd assets/updater
pyinstaller --onefile --noconsole --name updater updater_src.py
copy dist\updater.exe updater.exe
rmdir /s /q dist build __pycache__
del updater.spec
```

Після цього `updater.exe` версіонується у репозиторії. Перезбирати лише при зміні
`updater_src.py`.

## Збірка .exe

```bash
pyinstaller build_portable.spec
# Результат: dist/PhonesStatus_1.1.1_portable.exe   (ім'я = APP_NAME_APP_VERSION)
```

> Spec сам пише тип дистрибуції у `core/_build_dist.py` і бере назву/версію з
> `core/build_info.py`. Версію змінювати лише в `build_info.py` (`APP_VERSION`).

## Оновлення

Автоперевірка оновлень через GitHub Releases передбачена ядром, але **вимкнена**
(`check_updates: false` у `data/settings.json`) — релізів ще немає. Щоб увімкнути:
створити репозиторій `gevolushn/PhonesStatus`, викласти реліз із asset
`PhonesStatus_X.Y.Z_portable.exe`, заповнити `GITHUB_TOKEN` у `core/build_info.py`
(fine-grained PAT, лише `Contents: Read-only`) і поставити `check_updates: true`.

## Теми

Чотири режими оформлення (вибір зберігається у `data/settings.json`):
- **☀ Світла** — білий фон
- **🌥 Сіра** — темно-сірий (Word-style)
- **🌙 Темна** — майже чорний (за замовчуванням)
- **⚙ Система** — з налаштувань Windows

## Конфігурація проєкту

Уся ідентичність — у `core/build_info.py` (`APP_NAME`, `APP_VERSION`, `GITHUB_REPO`,
`GITHUB_PRIVATE`, `GITHUB_TOKEN`, `TEMP_PREFIX`). Решта значень обчислюється з них.

Опційні модулі (трей, кастомні діалоги, health тощо) — у `optional_modules/`,
див. `optional_modules/README_OPTIONAL_MODULES.md`.

## Версія

Поточна версія: **1.1.1**
Історія змін: [CHANGELOG.md](CHANGELOG.md)
