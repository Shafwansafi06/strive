$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and retry.' }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-demo.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Run: .\.venv\Scripts\python.exe scripts\start.py'
