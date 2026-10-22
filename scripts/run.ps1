# ============================================================
# LiaraPilot - one-command local launcher (Windows PowerShell)
# اجرای سریع در ویندوز ۱۱:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
# ============================================================

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [string]$HostAddress = "",
    [int]$PortNumber = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step([string]$Message) { Write-Host "[LiaraPilot] $Message" -ForegroundColor Cyan }
function Write-Fail([string]$Message) { Write-Host "[LiaraPilot] $Message" -ForegroundColor Red }

Write-Step "Checking Python..."
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $version = & $candidate --version 2>&1
        if ($version -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) { $python = $candidate; break }
        }
    } catch { }
}
if (-not $python) {
    Write-Fail "Python 3.11+ not found. Install Python 3.12 from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
    exit 1
}
Write-Step "Using $python ($(& $python --version))"

if (-not (Test-Path ".\.env")) {
    if (Test-Path ".\.env.example") {
        Write-Step "Creating .env from .env.example (existing files are never overwritten)..."
        & $python .\scripts\setup_env.py
    } else {
        Write-Fail ".env.example not found - is this the project root?"
        exit 1
    }
} else {
    Write-Step ".env found."
    & $python .\scripts\setup_env.py | Out-Null
}

Write-Step "Preparing data directories..."
New-Item -ItemType Directory -Force -Path ".\data", ".\data\workspaces", ".\data\artifacts" | Out-Null

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment (.venv)..."
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Fail "Could not create the virtual environment."; exit 1 }
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Step "Syncing dependencies with uv..."
    & uv sync --extra dev
    if ($LASTEXITCODE -ne 0) {
        Write-Step "uv sync failed; falling back to pip..."
        & $venvPython -m pip install --upgrade pip | Out-Null
        & $venvPython -m pip install -e ".[dev]"
    }
} else {
    Write-Step "uv not found - using pip (install uv for faster setup: https://docs.astral.sh/uv/)."
    & $venvPython -m pip install --upgrade pip | Out-Null
    & $venvPython -m pip install -e ".[dev]"
}
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Dependency installation failed. Check your internet connection or proxy settings."
    exit 1
}

Write-Step "Validating configuration..."
& $venvPython .\scripts\validate_config.py
if ($LASTEXITCODE -ne 0) { Write-Fail "Configuration is invalid (see the message above)."; exit 1 }

if (-not $SkipTests) {
    Write-Step "Running the offline test suite..."
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Tests failed. Fix the issues above or run with -SkipTests to start anyway."
        exit 1
    }
}

if ($HostAddress) { $env:APP_HOST = $HostAddress }
if ($PortNumber -gt 0) { $env:APP_PORT = "$PortNumber" }

Write-Step "Starting LiaraPilot..."
Write-Host ""
Write-Host "  UI:       http://127.0.0.1:$($env:APP_PORT ?? '8000')/" -ForegroundColor Green
Write-Host "  API docs: http://127.0.0.1:$($env:APP_PORT ?? '8000')/docs" -ForegroundColor Green
Write-Host "  MCP:      $venvPython -m app.mcp.server" -ForegroundColor DarkGray
Write-Host "  Stop with Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

& $venvPython -m uvicorn app.main:app --host "$($env:APP_HOST ?? '127.0.0.1')" --port "$($env:APP_PORT ?? '8000')"
