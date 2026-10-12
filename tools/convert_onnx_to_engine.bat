@echo off
setlocal

rem %~dp0 is the tools\ folder; the project root is one level up, not two.
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Project virtual environment not found:
    echo   %PYTHON%
    echo Create the project .venv and install CUDA PyTorch, TensorRT, ModelOpt, and Ultralytics first.
    pause
    exit /b 1
)

rem NOTE: keep the usage text free of unescaped () < > | & characters. Inside a
rem parenthesised block cmd treats a bare ")" as the end of the block, which
rem produced ". was unexpected at this time." when a tip contained "e.g." and an
rem arrow. Plain text only, printed from a :usage label, always parses.
if "%~1"=="" goto :usage

"%PYTHON%" "%~dp0convert_onnx_to_engine.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Conversion failed. Review the error above.
)
pause
exit /b %EXIT_CODE%

:usage
echo Drag one or more .onnx files onto this batch file, or run:
echo   "%~f0" "C:\path\to\model.onnx"
echo.
echo Tip: add --imgsz to match your capture FOV, rounded up to a multiple of 32.
echo      A 519 FOV becomes 544, so no per-frame upscale is paid.
echo   "%~f0" "C:\path\to\model.onnx" --imgsz 544
pause
exit /b 1
