@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creez d'abord l'environnement en suivant README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m macro_studio
