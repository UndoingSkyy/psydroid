param([switch]$Installer)
# Native tools report failure through $LASTEXITCODE, checked after each step. 'Stop' would also treat their
# ordinary stderr output (unittest progress, pip notices) as fatal when Windows PowerShell 5.1 output is redirected.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot -ErrorAction Stop
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv\Scripts\python.exe tools\make_icon.py
& .venv\Scripts\python.exe -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
# Absolute paths: PyInstaller resolves --icon and --add-data relative to --specpath, not this folder
& .venv\Scripts\python.exe -m PyInstaller "$PSScriptRoot\PsyDroid.pyw" `
    --name PsyDroid --onedir --windowed --icon "$PSScriptRoot\assets\psydroid.ico" `
    --add-data "$PSScriptRoot\assets\psydroid.ico;assets" `
    --add-data "$PSScriptRoot\assets\chevron-down.svg;assets" `
    --exclude-module tkinter `
    --distpath dist --workpath build --specpath build --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
& .venv\Scripts\python.exe tools\package.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
# The work folder holds an unfinished PsyDroid.exe that can't run, and --clean rebuilds it every time anyway
Remove-Item -LiteralPath build -Recurse -Force -ErrorAction Stop
if ($Installer) {
    $psydroidInno = @((Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $psydroidInno) { throw 'Portable build succeeded. Inno Setup 6 is required only for -Installer.' }
    & $psydroidInno /Qp '/DAppVersion=0.1.1' setup.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
}
Write-Host 'Ready: dist\PsyDroid\PsyDroid.exe and dist\PsyDroid-0.1.1-windows-x64.zip'
