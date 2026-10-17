@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .env (
  echo .env fayli topilmadi. .env.example faylini .env deb nusxalab, ichini to'ldiring.
  pause
  exit /b
)
if not exist venv (
  echo Python muhiti tayyorlanmoqda...
  py -3.13 -m venv venv || py -3.12 -m venv venv || py -3.11 -m venv venv
)
if not exist venv\Scripts\python.exe (
  echo Python 3.13 topilmadi. Buyruqlar oynasida yozing:  py install 3.13
  pause
  exit /b
)
echo Kerakli kutubxonalar o'rnatilmoqda (birinchi safar 1-2 daqiqa)...
venv\Scripts\python -m pip install -q -r requirements.txt
echo.
echo Bot ishga tushdi. To'xtatish uchun shu oynani yoping.
venv\Scripts\python main.py
pause
