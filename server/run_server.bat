@echo off
REM Запуск сервера КорпМессенджера (Windows 7/10/11, Python 3.7+)
cd /d "%~dp0"
where python >nul 2>nul || (echo Не найден Python. Установите python-3.8.10.exe (Win7) или новее && pause && exit /b 1)
if not exist venv (
  python -m venv venv
  call venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate.bat
)
echo Откройте в браузере http://127.0.0.1:5000  (логин admin / admin123)
python run.py --port 5000
pause
