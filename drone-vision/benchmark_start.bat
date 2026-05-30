@echo off
cd /d "%~dp0"

echo [BENCHMARK] Recording baseline...
call .\venv\Scripts\python.exe tools\benchmark.py record --baseline-dir benchmarks\baseline -- --source "provided_data\drive-download-20260528T184848Z-3-001\Air-to-Air\Vibrations.mp4" --model "provided_data\drive-download-20260528T184848Z-3-001\Baseline_yolo11s_Modell.onnx" --onnx-provider cpu --no-preview
if %errorlevel% neq 0 ( echo FEHLER bei Baseline-Recording & pause & exit /b 1 )

for /f "delims=" %%i in ('dir /b /ad /o-n benchmarks\baseline 2^>nul') do set LATEST=%%i & goto :found
:found

echo.
echo [BENCHMARK] Comparing against latest baseline: %LATEST%
call .\venv\Scripts\python.exe tools\benchmark.py compare --baseline-dir benchmarks\baseline\%LATEST% -- --source "provided_data\drive-download-20260528T184848Z-3-001\Air-to-Air\Vibrations.mp4" --model "provided_data\drive-download-20260528T184848Z-3-001\Baseline_yolo11s_Modell.onnx" --onnx-provider cpu --no-preview
pause
