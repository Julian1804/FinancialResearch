@echo off
setlocal
set "FR_ROOT=%~dp0"
cd /d "%FR_ROOT%"
where py >nul 2>&1
if errorlevel 1 (
  echo FR requires the Windows Python launcher with CPython 3.13 x64 installed.
  exit /b 2
)
py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 (
  echo FR requires a supported CPython 3.13 x64 installation.
  exit /b 2
)

set "FR_BOOTSTRAP_ROOT=%LOCALAPPDATA%\FinancialResearch"
set "FR_INSTALLATION_BOOTSTRAP_REQUIRED=1"
set "FINANCIAL_RESEARCH_RUNTIME_ROOT=%FR_BOOTSTRAP_ROOT%\runtime"
set "FR_LOCK=%FR_ROOT%requirements-runtime-py313-win64.lock"
for /f "delims=" %%H in ('powershell -NoProfile -Command "Import-Module Microsoft.PowerShell.Utility; (Get-FileHash -Algorithm SHA256 -LiteralPath $env:FR_LOCK).Hash.ToLowerInvariant()"') do set "FR_LOCK_HASH=%%H"
if not defined FR_LOCK_HASH (
  echo Unable to calculate the FR runtime lock digest.
  exit /b 2
)
set "FR_VENV=%FR_BOOTSTRAP_ROOT%\venv\py313-%FR_LOCK_HASH%"
if not exist "%FR_VENV%\Scripts\python.exe" (
  py -3.13 -m venv "%FR_VENV%"
  if errorlevel 1 exit /b 2
)

"%FR_VENV%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 (
  echo The FR venv is not a supported CPython 3.13 x64 environment.
  exit /b 2
)

if not exist "%FR_VENV%\installed.ok" (
  "%FR_VENV%\Scripts\python.exe" -m pip install --require-hashes -r "%FR_LOCK%"
  if errorlevel 1 (
    echo FR dependency installation failed. The venv remains unmarked and can be retried.
    exit /b 2
  )
  "%FR_VENV%\Scripts\python.exe" -m pip check
  if errorlevel 1 (
    echo FR dependency verification failed. The venv remains unmarked and can be retried.
    exit /b 2
  )
  type nul > "%FR_VENV%\installed.ok"
)

set "FR_PYTHON=%FR_VENV%\Scripts\python.exe"
"%FR_PYTHON%" scripts\fr_local_app_launcher.py start
exit /b %ERRORLEVEL%
