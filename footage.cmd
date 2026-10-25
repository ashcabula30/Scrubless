@echo off
rem Launcher: Python, libraries and models live on D (internal NTFS SSD).
rem Not E (external exFAT) and not C (nearly full).
set "FF_DATA=D:\footage-finder-data"
set "HF_HOME=%FF_DATA%\models"
set "UV_CACHE_DIR=%FF_DATA%\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%FF_DATA%\python"
set "UV_PROJECT_ENVIRONMENT=%FF_DATA%\venv"
"%FF_DATA%\venv\Scripts\footage.exe" %*
