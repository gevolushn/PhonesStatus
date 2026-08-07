updater.exe тут НЕМАЄ навмисно — це зібраний бінарник, він не зберігається у шаблоні.

Зібрати один раз (потрібен PyInstaller) перед першою portable-збіркою:

    cd assets/updater
    pyinstaller --onefile --noconsole --name updater updater_src.py
    copy dist\updater.exe updater.exe
    rmdir /s /q dist build __pycache__
    del updater.spec

Після цього updater.exe ВЕРСІОНУЄТЬСЯ у вашому проєкті (у .gitignore шаблону
ігноруються лише build/, dist/, updater.spec — сам updater.exe треба закомітити).
Перезбирати лише якщо змінили updater_src.py.
