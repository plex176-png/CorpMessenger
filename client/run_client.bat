@echo off
REM Запуск десктопного клиента (Windows 7 SP1 / 10 / 11). Требуется Node.js 16 и Electron 22.
cd /d "%~dp0"
if not exist node_modules (
  echo Установка зависимостей (первый запуск)...
  call npm install --no-audit --no-fund
)
call npm start
