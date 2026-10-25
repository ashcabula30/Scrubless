@echo off
rem Scrubless setup / repair: checks or installs the Python environment (see setup-env.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-env.ps1" %*
