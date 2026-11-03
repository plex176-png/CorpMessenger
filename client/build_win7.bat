@echo off
REM Сборка portable-версии для Windows 7 (32 бита). Итог: ..\release\КорпМессенджер-win32-ia32\
cd /d "%~dp0"
if not exist node_modules call npm install --no-audit --no-fund
call npx electron-packager . CorpMessenger --platform=win32 --arch=ia32 --out=../release --overwrite
echo Готово: ..\release\CorpMessenger-win32-ia32\CorpMessenger.exe
pause
