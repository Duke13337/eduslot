@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
where python >nul 2>nul || set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Создаю виртуальное окружение...
    "%PY%" -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo [2/3] Запускаю EduSlot: http://127.0.0.1:8000
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

echo [3/3] Для остановки нажмите Ctrl+C
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
