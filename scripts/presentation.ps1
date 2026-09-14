$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Native = Join-Path $Repo ".venv\Scripts\python.exe"

if (Test-Path $Native) {
    try {
        & $Native -c "import faiss" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $Native (Join-Path $Repo "scripts\presentation.py") @args
            exit $LASTEXITCODE
        }
    } catch {}
}

if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    $Drive = $Repo.Substring(0, 1).ToLowerInvariant()
    $Tail = $Repo.Substring(2).Replace("\", "/")
    $WslRepo = "/mnt/$Drive$Tail"
    if ($WslRepo) {
        Write-Host "Native FAISS is unavailable; starting the tested Ubuntu/WSL presentation path."
        & wsl.exe -d Ubuntu -- bash -lc "cd '$WslRepo' && exec .venv-linux/bin/python scripts/presentation.py $args"
        exit $LASTEXITCODE
    }
}

throw "No runnable STRIVE Python environment. Run scripts/setup.ps1, or create .venv-linux in Ubuntu/WSL."
