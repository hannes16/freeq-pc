@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  py -3 -m venv .venv
)

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b %errorlevel%

".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name FREEQ ^
  --collect-all prism ^
  --add-data "freeq_port\assets;freeq_port\assets" ^
  --add-data "freeq_port\data;freeq_port\data" ^
  freeq_main.py

if errorlevel 1 exit /b %errorlevel%
copy /y "attribution.txt" "dist\attribution.txt" >nul
echo.
echo Built dist\FREEQ.exe
