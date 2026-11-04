@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/projects',timeout=2)" >nul 2>&1
if not errorlevel 1 (
  start "" http://127.0.0.1:8080
  exit /b 0
)
set "APP_PYTHON=python"
python -c "import fastapi,uvicorn,multipart,pymupdf,openpyxl,reportlab" >nul 2>&1
if errorlevel 1 (
  if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python local...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
  )
  set "APP_PYTHON=.venv\Scripts\python.exe"
  echo Instalando dependencias do aplicativo...
  "!APP_PYTHON!" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)
echo Abrindo http://127.0.0.1:8080un
start "" http://127.0.0.1:8080
"%APP_PYTHON%" app.py
if errorlevel 1 goto :error
exit /b 0
:error
echo Nao foi possivel iniciar. Confira Python 3 e as dependencias.
pause
exit /b 1
