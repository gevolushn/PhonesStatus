"""
crypto.py — ОБФУСКАЦІЯ конфігу (XOR + Base64). ОПЦІЙНИЙ модуль.

⚠️ Це НЕ шифрування. Ключ вшитий у бінарник і дістається через `strings` за секунди,
   XOR тривіально обертається. Захищає лише від ВИПАДКОВОГО перегляду у текстовому
   редакторі — не від зловмисника.

   Для реальної безпеки на desktop без сервера:
     - Windows DPAPI (win32crypt.CryptProtectData) — прив'язка до облікового запису;
     - cryptography.fernet з ключем, похідним від пароля користувача (PBKDF2).

⚠️ КЛЮЧ ПОХІДНИЙ ВІД APP_NAME — перейменування програми РОЗБИВАЄ старі значення.
   `SECRET_KEY` обчислюється як f"{APP_NAME}_ObfuscationKey_2026", тож зміна APP_NAME
   (ребрендинг, друкарська помилка у назві, міграція проєкту) робить усе раніше
   обфусковане нечитабельним — `decrypt()` поверне сміття або кине виняток на
   .decode("utf-8"). Це не гіпотеза: та сама пастка вже описана в
   docs/HOW_MIGRATE_YOUR_PROJECT.md для міграції сторонніх проєктів.
   Якщо APP_NAME таки міняється — розшифрувати ЗАРАНІ старим ключем, потім
   зашифрувати новим; або перейти на модуль зі справжнім шифруванням.

⚠️ Для секретів, витік яких дорого коштує (API-ключі, токени, паролі до сервісів),
   цей модуль НЕ придатний — попри назву «crypto». Обирай за задачею, не за назвою файлу.

Підключення: скопіювати у core/, у config_manager.py замінити json.load/dump на
crypto.decrypt/encrypt. Ключ — SECRET_KEY з core/build_info.py.
"""
import base64

from core.build_info import SECRET_KEY  # f"{APP_NAME}_ObfuscationKey_2026" — НЕ секрет у криптосенсі


def _xor(data: bytes, key: bytes) -> bytes:
    """Побайтовий XOR з циклічним ключем."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encrypt(text: str) -> str:
    """Обфускує рядок: XOR ключем → Base64. Повертає ASCII-токен."""
    key = SECRET_KEY.encode("utf-8")
    return base64.b64encode(_xor(text.encode("utf-8"), key)).decode("ascii")


def decrypt(token: str) -> str:
    """Зворотна до encrypt операція. Повертає вихідний рядок."""
    key = SECRET_KEY.encode("utf-8")
    raw = base64.b64decode(token.encode("ascii"))
    return _xor(raw, key).decode("utf-8")
