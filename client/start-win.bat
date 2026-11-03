@echo off
rem Запуск десктоп-клиента КорпМессенджер.
rem Если Electron не установлен — пытается докачать бинарник с зеркала.
setlocal
cd /d "%~dp0"
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/

if not exist "node_modules\electron\dist\electron.exe" (
    echo [INFO] Electron не найден, запускаю восстановление...
    node fix-electron.js
    if not exist "node_modules\electron\dist\electron.exe" (
        echo [ОШИБКА] Не удалось установить Electron.
        echo Откройте вместо клиента веб-версию: http://адрес-сервера:5000
        pause
        exit /b 1
    )
)
start "" node_modules\electron\dist\electron.exe .
