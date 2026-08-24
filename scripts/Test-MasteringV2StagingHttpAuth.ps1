#requires -Version 7.0
<#
RQS Mastering V2 — isolated staging HTTP Auth/ownership validator.

Purpose:
  Validate the real candidate Express middleware/controller with a real staging
  Supabase JWT, while deliberately avoiding both production and S3 I/O.

Safety:
  - STAGING Supabase only: uwrqbywapomuloresoek
  - browser-safe staging publishable key only
  - disposable staging password/JWT are never printed
  - no service-role key is required
  - no S3 request is allowed by the chosen assertions
  - candidate source is downloaded to a disposable validation directory
  - no mutation of the user's project Git working tree

Prerequisite:
  $env:RQS_STAGING_SUPABASE_PUBLISHABLE_KEY = '<staging publishable key>'
#>

$ErrorActionPreference = 'Stop'

$ExpectedProjectRef = 'uwrqbywapomuloresoek'
$SupabaseUrl = "https://$ExpectedProjectRef.supabase.co"
$PublishableKey = [string]$env:RQS_STAGING_SUPABASE_PUBLISHABLE_KEY
$CandidateBranch = 'integration/mastering-v2-secure-p1-20260816'
$ArchiveUrl = "https://github.com/anaraquel00/rqs-daw-backend/archive/refs/heads/$CandidateBranch.zip"
$Port = 18081
$BaseUrl = "http://127.0.0.1:$Port"
$ValidationRoot = 'D:\RQS-Dev\mastering_v2_staging_http_gate'
$RunDir = Join-Path $ValidationRoot (Get-Date -Format 'yyyyMMdd_HHmmss')
$ZipPath = Join-Path $RunDir 'candidate.zip'
$ExtractPath = Join-Path $RunDir 'candidate'
$ServerStdout = Join-Path $RunDir 'server.stdout.log'
$ServerStderr = Join-Path $RunDir 'server.stderr.log'

if ([string]::IsNullOrWhiteSpace($PublishableKey)) {
    throw 'RQS_STAGING_SUPABASE_PUBLISHABLE_KEY is not set.'
}
if ($PublishableKey -match 'service_role|sb_secret_') {
    throw 'SAFETY STOP: a service/server secret must never be used by this validator.'
}

$Email = Read-Host 'Existing STAGING test e-mail'
$SecurePassword = Read-Host 'Existing STAGING test password' -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
$PlainPassword = $null
$AccessToken = $null
$UserId = $null
$ServerProcess = $null

function Invoke-RqsJson {
    param(
        [Parameter(Mandatory)] [string] $Method,
        [Parameter(Mandatory)] [string] $Uri,
        [hashtable] $Headers = @{},
        [object] $Body = $null
    )

    $params = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
        SkipHttpErrorCheck = $true
    }
    if ($null -ne $Body) {
        $params.ContentType = 'application/json'
        $params.Body = ($Body | ConvertTo-Json -Depth 8 -Compress)
    }

    $response = Invoke-WebRequest @params
    $json = $null
    if (-not [string]::IsNullOrWhiteSpace($response.Content)) {
        try { $json = $response.Content | ConvertFrom-Json } catch { $json = $null }
    }
    [pscustomobject]@{
        StatusCode = [int]$response.StatusCode
        Json = $json
        Raw = $response.Content
    }
}

function Assert-Http {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [int] $ExpectedStatus,
        [Parameter(Mandatory)] $Response,
        [string] $ExpectedCode = ''
    )

    if ([int]$Response.StatusCode -ne $ExpectedStatus) {
        throw "$Name failed: expected HTTP $ExpectedStatus, got $($Response.StatusCode). Body: $($Response.Raw)"
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedCode)) {
        $actualCode = [string]$Response.Json.code
        if ($actualCode -ne $ExpectedCode) {
            throw "$Name failed: expected code $ExpectedCode, got '$actualCode'. Body: $($Response.Raw)"
        }
    }
    Write-Host "$Name`: PASS"
}

try {
    if ([string]::IsNullOrWhiteSpace($Email) -or $Email -notmatch '@') {
        throw 'A valid existing staging test e-mail is required.'
    }

    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
    if ([string]::IsNullOrWhiteSpace($PlainPassword)) {
        throw 'The staging test password is required.'
    }

    $PublicHeaders = @{ apikey = $PublishableKey }
    $signin = Invoke-RqsJson -Method POST -Uri "$SupabaseUrl/auth/v1/token?grant_type=password" -Headers $PublicHeaders -Body @{
        email = $Email
        password = $PlainPassword
    }

    if ($signin.StatusCode -notin 200, 201 -or -not $signin.Json.access_token -or -not $signin.Json.user.id) {
        throw "STAGING sign-in failed with HTTP $($signin.StatusCode)."
    }

    $AccessToken = [string]$signin.Json.access_token
    $UserId = [string]$signin.Json.user.id
    Write-Host 'STAGING_HTTP_REAL_JWT_ACQUIRED: PASS'

    New-Item -ItemType Directory -Force -Path $RunDir, $ExtractPath | Out-Null
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ZipPath
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractPath -Force

    $RepoDir = Get-ChildItem -LiteralPath $ExtractPath -Directory | Select-Object -First 1 -ExpandProperty FullName
    if ([string]::IsNullOrWhiteSpace($RepoDir) -or -not (Test-Path (Join-Path $RepoDir 'server.js'))) {
        throw 'Downloaded candidate archive does not contain server.js.'
    }

    Push-Location $RepoDir
    try {
        & npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
    }
    Write-Host 'STAGING_HTTP_CANDIDATE_INSTALL: PASS'

    $env:SUPABASE_URL = $SupabaseUrl
    # For this auth-only gate the browser-safe project key is sufficient as the
    # Supabase apikey. Full quota RPC validation still requires the later real
    # staging backend/service-role deployment gate.
    $env:SUPABASE_SECRET_KEY = $PublishableKey
    $env:RQS_MASTERING_V2_STORAGE_ENV = 'staging'
    $env:RQS_MASTERING_V2_BUCKET_NAME = 'rqs-mastering-v2-staging-http-gate-placeholder'
    $env:RQS_MASTERING_V2_AWS_REGION = 'sa-east-1'
    $env:PORT = [string]$Port
    $env:STRIPE_SECRET_KEY = 'sk_test_http_gate_placeholder'
    $env:STRIPE_WEBHOOK_SECRET = 'whsec_http_gate_placeholder'

    $ServerProcess = Start-Process -FilePath 'node' -ArgumentList 'server.js' `
        -WorkingDirectory $RepoDir -PassThru `
        -RedirectStandardOutput $ServerStdout -RedirectStandardError $ServerStderr

    $HealthReady = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if ($ServerProcess.HasExited) {
            $stderr = if (Test-Path $ServerStderr) { Get-Content -LiteralPath $ServerStderr -Raw } else { '' }
            throw "Candidate server exited early. STDERR: $stderr"
        }
        try {
            $health = Invoke-RqsJson -Method GET -Uri "$BaseUrl/health"
            if ($health.StatusCode -eq 200) {
                $HealthReady = $true
                break
            }
        }
        catch {
            # Expected during the short startup race; retry until timeout.
        }
    }
    if (-not $HealthReady) {
        $stderr = if (Test-Path $ServerStderr) { Get-Content -LiteralPath $ServerStderr -Raw } else { '' }
        throw "Candidate server did not become healthy within the timeout. STDERR: $stderr"
    }
    Write-Host 'STAGING_HTTP_CANDIDATE_HEALTH: PASS'

    $noAuth = Invoke-RqsJson -Method GET -Uri "$BaseUrl/mastering/v2/presigned-url?filename=test.wav"
    Assert-Http -Name 'STAGING_HTTP_AUTH_REQUIRED_401' -ExpectedStatus 401 -Response $noAuth -ExpectedCode 'AUTH_REQUIRED'

    $invalidAuth = Invoke-RqsJson -Method GET -Uri "$BaseUrl/mastering/v2/presigned-url?filename=test.wav" -Headers @{
        Authorization = 'Bearer invalid-staging-token'
    }
    Assert-Http -Name 'STAGING_HTTP_INVALID_JWT_401' -ExpectedStatus 401 -Response $invalidAuth -ExpectedCode 'AUTH_INVALID'

    $legacy = Invoke-RqsJson -Method POST -Uri "$BaseUrl/mastering/process" -Body @{}
    Assert-Http -Name 'STAGING_HTTP_LEGACY_MASTERING_410' -ExpectedStatus 410 -Response $legacy -ExpectedCode 'LEGACY_MASTERING_PROCESS_RETIRED'

    $foreignUserId = '00000000-0000-4000-8000-000000000099'
    if ($foreignUserId -eq $UserId) { throw 'Unexpected test user ID collision.' }

    $foreignResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" `
        -Headers @{ Authorization = "Bearer $AccessToken" } `
        -Form @{
            s3Key = "uploads/$foreignUserId/foreign.wav"
            destination = 'streaming'
            platform = 'spotify'
            atmosphere = 'clear_sky'
            intensity_percent = '50'
            soundcloud_mode = 'standard'
            preview = 'true'
        } -SkipHttpErrorCheck
    $foreignJson = $foreignResponse.Content | ConvertFrom-Json
    $foreignResult = [pscustomobject]@{
        StatusCode = [int]$foreignResponse.StatusCode
        Json = $foreignJson
        Raw = $foreignResponse.Content
    }
    Assert-Http -Name 'STAGING_HTTP_FOREIGN_S3_KEY_403' -ExpectedStatus 403 -Response $foreignResult -ExpectedCode 'S3_KEY_FORBIDDEN'

    $escapeResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" `
        -Headers @{ Authorization = "Bearer $AccessToken" } `
        -Form @{
            s3Key = "uploads/$UserId/../escape.wav"
            destination = 'streaming'
            platform = 'spotify'
            atmosphere = 'clear_sky'
            intensity_percent = '50'
            soundcloud_mode = 'standard'
            preview = 'true'
        } -SkipHttpErrorCheck
    $escapeJson = $escapeResponse.Content | ConvertFrom-Json
    $escapeResult = [pscustomobject]@{
        StatusCode = [int]$escapeResponse.StatusCode
        Json = $escapeJson
        Raw = $escapeResponse.Content
    }
    Assert-Http -Name 'STAGING_HTTP_PATH_ESCAPE_KEY_400' -ExpectedStatus 400 -Response $escapeResult -ExpectedCode 'S3_KEY_INVALID'

    Write-Host 'MASTERING_V2_STAGING_HTTP_AUTH_OWNERSHIP: PASS'
    Write-Host 'S3_REQUESTS_PERFORMED: NONE'
    Write-Host 'PRODUCTION_REQUESTS_PERFORMED: NONE'
    Write-Host 'SERVICE_ROLE_SECRET_USED: NONE'
    Write-Host 'SECRETS_PRINTED: NONE'
    Write-Host "VALIDATION_LOG_DIR: $RunDir"
}
finally {
    if ($null -ne $ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        try { $ServerProcess.WaitForExit(5000) | Out-Null } catch {}
    }

    foreach ($name in @(
        'SUPABASE_URL',
        'SUPABASE_SECRET_KEY',
        'RQS_MASTERING_V2_STORAGE_ENV',
        'RQS_MASTERING_V2_BUCKET_NAME',
        'RQS_MASTERING_V2_AWS_REGION',
        'PORT',
        'STRIPE_SECRET_KEY',
        'STRIPE_WEBHOOK_SECRET'
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }

    if ($Bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
    }
    $PlainPassword = $null
    $AccessToken = $null
    $SecurePassword = $null
}
