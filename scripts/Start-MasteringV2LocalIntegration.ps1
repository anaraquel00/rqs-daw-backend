[CmdletBinding()]
param(
    [string]$FrontendPath = 'C:\!git\Core\rqs-daw-frontend',
    [string]$PythonPath = 'D:\RQS-Dev\venvs\rqs-daw-backend-mastering-py312\Scripts\python.exe',
    [int]$BackendPort = 8080,
    [int]$FrontendPort = 4200,
    [switch]$OpenBrowser,
    [switch]$SkipBranchCheck
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$BackendPath = Split-Path -Parent $PSScriptRoot
$BackendBranchExpected = 'feat/mastering-v2-api-integration'
$FrontendBranchExpected = 'feat/mastering-v2-integration'
$BackendProcess = $null
$FrontendProcess = $null
$OldPythonBin = $env:RQS_PYTHON_BIN
$OldLocalOutput = $env:RQS_MASTERING_V2_LOCAL_OUTPUT
$OldPort = $env:PORT

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found in PATH: $Name"
    }
}

function Get-GitBranch {
    param([Parameter(Mandatory = $true)][string]$Repo)
    $branch = (& git -C $Repo branch --show-current 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot read Git branch in: $Repo`n$branch"
    }
    return $branch
}

function Assert-CleanBranchSelection {
    param(
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $actual = Get-GitBranch -Repo $Repo
    if ($actual -ne $Expected) {
        throw "$Label is on branch '$actual'. Expected '$Expected'. No checkout was performed."
    }
    Write-Host "[PASS] $Label branch: $actual"
}

function Wait-Http {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for: $Url"
}

function Assert-FrontendDevelopmentIsolation {
    param([Parameter(Mandatory = $true)][string]$Repo)
    $environmentFile = Join-Path $Repo 'src\environments\environment.ts'
    if (-not (Test-Path -LiteralPath $environmentFile)) {
        throw "Frontend development environment not found: $environmentFile"
    }

    $content = Get-Content -LiteralPath $environmentFile -Raw
    $expectedUrl = "http://localhost:$BackendPort"
    if ($content -notmatch [regex]::Escape($expectedUrl)) {
        throw "Frontend development environment does not target $expectedUrl"
    }
    if ($content -notmatch 'masteringV2DirectUpload\s*:\s*true') {
        throw 'Frontend development environment is not configured for direct Mastering V2 upload.'
    }
    Write-Host "[PASS] Frontend development isolation: $expectedUrl + direct upload"
}

try {
    Write-Host '=== RQS MASTERING V2 LOCAL INTEGRATION ==='
    Write-Host "Backend : $BackendPath"
    Write-Host "Frontend: $FrontendPath"

    Assert-Command -Name 'git'
    Assert-Command -Name 'node'
    Assert-Command -Name 'npm.cmd'
    Assert-Command -Name 'ffmpeg'

    if (-not (Test-Path -LiteralPath $BackendPath)) {
        throw "Backend path not found: $BackendPath"
    }
    if (-not (Test-Path -LiteralPath $FrontendPath)) {
        throw "Frontend path not found: $FrontendPath"
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Validated Python executable not found: $PythonPath"
    }

    if (-not $SkipBranchCheck) {
        Assert-CleanBranchSelection -Repo $BackendPath -Expected $BackendBranchExpected -Label 'Backend'
        Assert-CleanBranchSelection -Repo $FrontendPath -Expected $FrontendBranchExpected -Label 'Frontend'
    }

    Assert-FrontendDevelopmentIsolation -Repo $FrontendPath

    $backendNodeModules = Join-Path $BackendPath 'node_modules'
    $frontendNodeModules = Join-Path $FrontendPath 'node_modules'
    if (-not (Test-Path -LiteralPath $backendNodeModules)) {
        throw "Backend node_modules missing. Run 'npm ci' in $BackendPath first."
    }
    if (-not (Test-Path -LiteralPath $frontendNodeModules)) {
        throw "Frontend node_modules missing. Run 'npm ci' in $FrontendPath first."
    }

    $env:RQS_PYTHON_BIN = $PythonPath
    $env:RQS_MASTERING_V2_LOCAL_OUTPUT = '1'
    $env:PORT = [string]$BackendPort

    Write-Host '[START] Mastering V2 backend...'
    $BackendProcess = Start-Process `
        -FilePath 'node' `
        -ArgumentList @('scripts/mastering-v2-local-server.js') `
        -WorkingDirectory $BackendPath `
        -PassThru

    Wait-Http -Url "http://127.0.0.1:$BackendPort/health" -TimeoutSeconds 60
    Write-Host "[PASS] Backend health: http://127.0.0.1:$BackendPort/health"

    $capabilities = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/mastering/v2/capabilities" -Method Get -TimeoutSec 30
    if ($capabilities.release -ne 'mastering-v2-v1') {
        throw "Unexpected Mastering V2 release: $($capabilities.release)"
    }
    Write-Host "[PASS] Backend contract release: $($capabilities.release)"

    Write-Host '[START] Angular frontend...'
    $FrontendProcess = Start-Process `
        -FilePath 'npm.cmd' `
        -ArgumentList @('start', '--', '--host', '127.0.0.1', '--port', [string]$FrontendPort) `
        -WorkingDirectory $FrontendPath `
        -PassThru

    Wait-Http -Url "http://127.0.0.1:$FrontendPort" -TimeoutSeconds 120
    Write-Host "[PASS] Frontend: http://127.0.0.1:$FrontendPort"
    Write-Host ''
    Write-Host 'LOCAL FRONTEND <-> MASTERING V2 BACKEND IS READY.'
    Write-Host 'No Git checkout, merge, main update or production deployment was performed.'

    if ($OpenBrowser) {
        Start-Process "http://127.0.0.1:$FrontendPort"
    }

    Write-Host ''
    Read-Host 'Press ENTER to stop both local processes'
}
finally {
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        Stop-Process -Id $FrontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
    }

    $env:RQS_PYTHON_BIN = $OldPythonBin
    $env:RQS_MASTERING_V2_LOCAL_OUTPUT = $OldLocalOutput
    $env:PORT = $OldPort

    Write-Host '[STOP] Local integration processes stopped.'
}
