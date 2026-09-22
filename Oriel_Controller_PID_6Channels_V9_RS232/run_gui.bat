@echo off
title Oriel 6-Channel Stage & DAQ Controller
echo Starting Oriel Stage & DAQ Controller GUI (V2)...
python oriel_gui_v2.py
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
