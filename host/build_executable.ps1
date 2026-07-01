$ErrorActionPreference = "Stop"

$HostRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectPython = Join-Path $HostRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $ProjectPython)) {
    throw "Project virtual environment not found at $ProjectPython. Create it first."
}

# Keep environments, analysis files, and output away from OneDrive. Override
# this location by setting MAKESENSE_BUILD_ROOT before running the script.
$BuildRoot = if ($env:MAKESENSE_BUILD_ROOT) {
    $env:MAKESENSE_BUILD_ROOT
} else {
    Join-Path $env:LOCALAPPDATA "MakeSense\PyInstaller"
}
$BuildVenv = Join-Path $BuildRoot ".venv"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$WorkPath = Join-Path $BuildRoot "work"
$DistPath = Join-Path $BuildRoot "dist"
$SetupMarker = Join-Path $BuildVenv ".makesense-build-ready"

New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null

if (-not (Test-Path $BuildPython)) {
    $BasePython = & $ProjectPython -c "import sys; print(sys._base_executable)"
    if ($LASTEXITCODE -ne 0 -or -not $BasePython) {
        throw "Could not determine the base Python interpreter."
    }
    Write-Host "Creating build environment outside OneDrive: $BuildVenv"
    & $BasePython -m venv $BuildVenv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the external build environment."
    }
}

if (-not (Test-Path $SetupMarker)) {
    Write-Host "Installing application and build dependencies..."
    & $BuildPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Could not update pip in the build environment."
    }
    & $BuildPython -m pip install -r (Join-Path $HostRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install application dependencies."
    }
    & $BuildPython -m pip install -r (Join-Path $HostRoot "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install PyInstaller."
    }
    New-Item -ItemType File -Path $SetupMarker -Force | Out-Null
}

Push-Location $HostRoot
try {
    & $BuildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath $WorkPath `
        --distpath $DistPath `
        makesense.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
    Write-Host ""
    Write-Host "Build complete: $DistPath\MakeSense\MakeSense.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
