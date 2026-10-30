@echo off
rem ------------------------------------------------------------------
rem  Builds SimbioKernelUtility.exe (Windows).
rem    build_exe.bat            -> single file   dist\SimbioKernelUtility.exe
rem    build_exe.bat onedir     -> folder        dist\SimbioKernelUtility\SimbioKernelUtility.exe (starts faster)
rem  Needs Python 3.10-3.13 on PATH (or the "py" launcher). A private .venv is created next to this file.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=onefile

where py >nul 2>nul
if %ERRORLEVEL%==0 (set PY=py -3) else (set PY=python)

if not exist .venv\Scripts\python.exe (
    %PY% -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
pip install -r requirements-dev.txt || goto :fail

echo Running tests...
python -m pytest -q tests
if errorlevel 1 echo WARNING: some tests failed - continuing with the build anyway

set SKU_MODE=%MODE%
pyinstaller --noconfirm --clean SimbioKernelUtility.spec || goto :fail

echo.
echo Done.  See the dist folder.
exit /b 0

:fail
echo.
echo BUILD FAILED (see messages above)
exit /b 1
