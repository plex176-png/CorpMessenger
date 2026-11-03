@echo off
rem ============================================================
rem  КорпМессенджер — установка зависимостей клиента (Windows)
rem  Лечит сетевые ошибки npm (ECONNRESET и т.п.) через зеркало.
rem  Двойной щелчок или запуск из cmd:  install-win.bat
rem ============================================================
setlocal
cd /d "%~dp0"

where npm >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] npm не найден. Установите Node.js ^(для Win7 — Node 14, иначе LTS^).
    pause
    exit /b 1
)

echo [1/3] Настраиваю зеркала...
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
set ELECTRON_GET_MODE=reuse

echo [2/3] Устанавливаю зависимости (npm install)...
call npm install --loglevel=warn
if errorlevel 1 (
    echo.
    echo [ОШИБКА] npm install завершился с ошибкой. Возможные причины:
    echo   - корпоративный прокси: npm config set proxy http://user:pass@host:port
    echo     и npm config set https-proxy http://user:pass@host:port
    echo   - антивирус с SSL-инспекцией: добавьте node.exe в исключения
    echo   - нет доступа к registry.npmmirror.com — попробуйте без зеркала:
    echo     npm config delete registry ^&^& npm install
    pause
    exit /b 1
)

echo [3/3] Проверяю бинарник Electron...
if not exist "node_modules\electron\dist\electron.exe" (
    echo electron.exe отсутствует — докачиваю с зеркала...
    node fix-electron.js
)

if exist "node_modules\electron\dist\electron.exe" (
    echo.
    echo ВСЁ ГОТОВО. Запуск клиента:  start-win.bat   (или npm start)
) else (
    echo.
    echo [ВНИМАНИЕ] Электрон так и не установлен. Варианты:
    echo   1) Повторить:  node fix-electron.js
    echo   2) Скачать вручную electron-v22.3.27-win32-x64.zip с
    echo      https://npmmirror.com/mirrors/electron/22.3.27/
    echo      распаковать в node_modules\electron\dist
    echo   3) Использовать веб-версию: откройте в браузере http://АДРЕС_СЕРВЕРА:5000
)
pause
