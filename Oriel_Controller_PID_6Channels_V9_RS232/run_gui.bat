@echo off
title Oriel 6-Channel Stage Controller GUI
python "%~dp0oriel_gui.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error. Press any key to close.
    pause > nul
)
