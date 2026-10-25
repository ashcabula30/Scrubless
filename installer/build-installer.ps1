# Builds installer\build\Scrubless Setup <version>.exe:
#   1. UI (npm run build -> footage_finder\static)
#   2. Scrubless.exe launcher (C# compiler that ships with Windows)
#   3. bundles uv.exe, then compiles Scrubless.iss with Inno Setup
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path $here -Parent
New-Item -ItemType Directory -Force "$here\build" | Out-Null

Write-Host '1/3 UI'
Push-Location "$root\ui"; npm run build; if ($LASTEXITCODE) { throw 'UI build failed' }; Pop-Location

Write-Host '2/3 launcher'
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' /nologo /target:winexe /optimize+ `
  "/win32icon:$root\footage_finder\icon.ico" /r:System.Windows.Forms.dll "/out:$here\build\Scrubless.exe" "$here\Launcher.cs"
if ($LASTEXITCODE) { throw 'Launcher build failed' }

Write-Host '3/3 installer'
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter uv.exe | Select-Object -First 1 -ExpandProperty FullName }
if (-not $uv) { throw 'uv.exe not found (winget install astral-sh.uv)' }
Copy-Item (Get-Item $uv).FullName "$here\build\uv.exe" -Force
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup not found (winget install JRSoftware.InnoSetup)' }
& $iscc /Q "$here\Scrubless.iss"
if ($LASTEXITCODE) { throw 'Installer build failed' }
Get-ChildItem "$here\build\*Setup*.exe" | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
