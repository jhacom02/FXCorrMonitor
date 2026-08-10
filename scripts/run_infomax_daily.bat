@echo off
REM Infomax IMDP daily snapshot ETL (06:00 Task Scheduler)
REM Run only when the Infomax-logged-on Windows user is logged on.
cd /d "%~dp0.."
if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
)

python scripts\ingest_snapshot_daily.py %*
if errorlevel 1 exit /b %ERRORLEVEL%

REM Streamlit Cloud: commit DB and push when changed
git add -- "data/fx_dashboard.db"
git diff --cached --quiet -- "data/fx_dashboard.db"
if not errorlevel 1 (
  echo No DB changes to commit.
  exit /b 0
)

git commit -m "Daily Batch: DB Update"
if errorlevel 1 exit /b %ERRORLEVEL%

git push origin main
exit /b %ERRORLEVEL%
