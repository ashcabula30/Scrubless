# Sets up (or checks) the Python environment Scrubless runs in.
# Started by the app the first time it opens on a PC, and by the Start menu entry "Scrubless setup (repair)".
# First time on a PC it downloads Python 3.12 and the AI libraries (~4 GB); after that it's a quick check.
#
# Not run from inside the installer: Windows blocks processes started by an installer from following the
# folder junction uv keeps in its Python folder ("untrusted mount point", os error 448).
param(
  [string] $Data,   # e.g. D:\footage-finder-data; default: data= from ..\launcher.ini
  [string] $App     # folder holding pyproject.toml, uv.lock and footage_finder\; default: ..\app
)
$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Scrubless setup'
$install = Split-Path $PSScriptRoot -Parent
if (-not $App) { $App = Join-Path $install 'app' }
if (-not $Data) {
  $ini = Join-Path $install 'launcher.ini'
  $line = if (Test-Path $ini) { Get-Content $ini | Where-Object { $_ -match '^\s*data\s*=' } | Select-Object -First 1 }
  $Data = if ($line) { ($line -split '=', 2)[1].Trim() } else { 'D:\footage-finder-data' }
}
$uv = Join-Path $PSScriptRoot 'uv.exe'
if (-not (Test-Path $uv)) { $uv = 'uv' }

Write-Host "Scrubless setup" -ForegroundColor Cyan
Write-Host "  Data folder: $Data"
Write-Host "  App folder:  $App`n"
New-Item -ItemType Directory -Force $Data | Out-Null

$env:UV_CACHE_DIR = Join-Path $Data 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Data 'python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Data 'venv'
$env:UV_LINK_MODE = 'copy'          # works on any drive format
$env:UV_HTTP_TIMEOUT = '120'

$fresh = -not (Test-Path (Join-Path $Data 'venv\Scripts\pythonw.exe'))
if ($fresh) {
  Write-Host "Installing Python 3.12 and the AI libraries. This downloads about 4 GB the first time...`n"
  & $uv python install 3.12
} else {
  Write-Host "Checking the existing environment...`n"
}

# --no-install-project: the app runs straight from the App folder, so only the libraries are installed.
# --inexact: add what's missing, never remove anything already there (e.g. a developer's own install).
for ($i = 1; $i -le 3; $i++) {
  & $uv sync --project $App --python 3.12 --frozen --no-install-project --inexact
  if ($LASTEXITCODE -eq 0) { break }
  Write-Host "Download problem, retrying ($i of 3)..." -ForegroundColor Yellow
  Start-Sleep 10
}
if ($LASTEXITCODE -ne 0) {
  Write-Host "`nSetup failed. Check the internet connection and run 'Scrubless setup (repair)' from the Start menu." -ForegroundColor Red
  Read-Host 'Press Enter to close'
  exit 1
}
Write-Host "`nDone." -ForegroundColor Green
if ($fresh) {
  Write-Host "Opening Scrubless. The AI models (about 8 GB) download the first time a folder is indexed."
  Start-Process (Join-Path $install 'Scrubless.exe')
  Start-Sleep 4
} else { Start-Sleep 2 }
