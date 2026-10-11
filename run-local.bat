@echo off
setlocal
cd /d "%~dp0"
set "TIMETABLE_ADMIN_USERNAME=admin"
set /p "TIMETABLE_ADMIN_PASSWORD=Choose a local demo password (12+ characters): "
if not defined TIMETABLE_ADMIN_PASSWORD (
    echo A password is required.
    exit /b 1
)
set "TIMETABLE_HOST=127.0.0.1"
set "PORT=8000"
set "TIMETABLE_COOKIE_SECURE=0"
for /f %%S in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString() + [guid]::NewGuid().ToString()"') do set "TIMETABLE_SESSION_SECRET=%%S"
echo Starting the private Timetable Scheduler Pro demo at http://127.0.0.1:8000
echo The demo uses its own fictional sample data. Keep this window open.
start "" http://127.0.0.1:8000
python server.py
endlocal
