@echo off
cd /d "%~dp0"
echo.
echo === Drone Surveillance Demo ===
echo.
if not exist "venv\Scripts\python.exe" (
    echo [!] Creating virtual environment...
    python -m venv venv
)
echo [*] Upgrading pip...
call venv\Scripts\python.exe -m pip install -q --upgrade pip
echo [*] Installing dependencies...
call venv\Scripts\python.exe -m pip install -q -r requirements.txt
echo.
echo [*] Starting Streamlit dashboard...
echo     Open http://127.0.0.1:8501 in your browser
echo.
call venv\Scripts\python.exe -m streamlit run mti_detector/streamlit_demo.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
pause
