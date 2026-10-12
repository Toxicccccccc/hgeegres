@echo off
setlocal

:: Make sure you are in the same directory as best.pt
:: And have Ultralytics YOLO installed

echo [*] Exporting best.pt to ONNX...
yolo export model=best.pt format=onnx imgsz=256 batch=1 opset=17 half=False dynamic=False simplify=True nms=False

if %ERRORLEVEL% neq 0 (
    echo [!] Export failed. Keeping best.pt
    exit /b %ERRORLEVEL%
)

:: Confirm best.onnx was created
if exist "best.onnx" (
    echo [+] Export successful. Deleting best.pt...
    del /f /q best.pt
    echo Done.
) else (
    echo [!] best.onnx not found. Export may have failed.
)

endlocal
pause