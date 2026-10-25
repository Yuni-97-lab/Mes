<#
.SYNOPSIS
  Build the React UI (if needed) and serve UI + API with uvicorn on one port.

.DESCRIPTION
  1. Finds a real Python interpreter (the Windows Store "python" stub is skipped).
  2. Builds frontend/dist when it is missing or when -Rebuild is given
     (npm ci, or npm install when there is no lockfile, then npm run build).
  3. Runs: python -m uvicorn backend.app.main:app --port <Port>
  The simulator is NOT started here; run it in a second terminal (see README).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1 -Rebuild -Port 8001
  powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1 -Python C:\Users\me\anaconda3\python.exe
#>
param(
    [string]$Python = "",
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-Python([string]$exe) {
    if (-not $exe) { return $false }
    try {
        $out = & $exe -c "import sys; print(sys.version_info[0])" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "3")
    } catch { return $false }
}

function Find-Python {
    if ($Python) {
        if (Test-Python $Python) { return $Python }
        throw "-Python '$Python' is not a working Python 3 interpreter."
    }
    $candidates = @()
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += @(
        (Join-Path $env:USERPROFILE "anaconda3\python.exe"),
        (Join-Path $env:USERPROFILE "miniconda3\python.exe"),
        "C:\ProgramData\Anaconda3\python.exe",
        "C:\ProgramData\miniconda3\python.exe"
    )
    $candidates += @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe") -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    foreach ($c in $candidates) { if (Test-Python $c) { return $c } }
    throw "No working Python 3 found. Pass one with -Python C:\path\to\python.exe"
}

function Find-Npm {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $known = "C:\Program Files\nodejs\npm.cmd"
    if (Test-Path $known) {
        $env:PATH = "C:\Program Files\nodejs;$env:PATH"
        return $known
    }
    throw "npm not found. Install Node.js LTS (winget install OpenJS.NodeJS.LTS) and retry."
}

$py = Find-Python
Write-Host "Python: $py"

$depsOk = $false
try { & $py -c "import fastapi, uvicorn, psycopg" 2>$null; $depsOk = ($LASTEXITCODE -eq 0) } catch { $depsOk = $false }
if (-not $depsOk) {
    throw "Python packages missing. Run: $py -m pip install -r requirements.txt"
}

$dist = Join-Path $Root "frontend\dist\index.html"
if ($Rebuild -or -not (Test-Path $dist)) {
    $npm = Find-Npm
    Write-Host "Building frontend (npm: $npm)"
    Push-Location (Join-Path $Root "frontend")
    try {
        if (Test-Path "package-lock.json") { & $npm ci } else { & $npm install }
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        & $npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally { Pop-Location }
} else {
    Write-Host "Using existing frontend\dist (pass -Rebuild to rebuild)"
}

Write-Host "Serving on http://localhost:$Port  (Ctrl+C to stop)"
& $py -m uvicorn backend.app.main:app --host $BindHost --port $Port
