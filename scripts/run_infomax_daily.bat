@echo off
REM Infomax IMDP daily snapshot ETL (06:00 Task Scheduler)
REM Run only when the Infomax-logged-on Windows user is logged on.
cd /d "%~dp0.."
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)
python scripts\ingest_snapshot_daily.py %*
exit /b %ERRORLEVEL%
