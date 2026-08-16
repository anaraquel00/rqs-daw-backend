#requires -Version 7.0
<#
RQS Mastering V2 — isolated staging HTTP quota validator.

Purpose:
  Validate the real candidate Express controller against the real staging
  Supabase quota RPC path using the retained disposable staging identity.

Safety:
  - STAGING Supabase only: uwrqbywapomuloresoek
  - no production requests
  - no S3 request is allowed by the chosen assertions
  - staging server secret is read as SecureString and never printed
  - the disposable user's original completed_masters value is restored
  - test reservations for the disposable user are cleaned in finally
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
$Port = 18082
$BaseUrl = "http://127.0.0.1:$Port"
$ValidationRoot = 'D:\RQS-Dev\mastering_v2_staging_quota_http_gate'
$RunDir = Join-Path $ValidationRoot (Get-Date -Format 'yyyyMMdd_HHmmss')
$ZipPath = Join-Path $RunDir 'candidate.zip'
$ExtractPath = Join-Path $RunDir 'candidate'
$ServerStdout = Join-Path $RunDir 'server.stdout.log'
$ServerStderr = Join-Path $RunDir 'server.stderr.log'

if ([string]::IsNullOrWhiteSpace($PublishableKey)) {
    throw 'RQS_STAGING_SUPABASE_PUBLISHABLE_KEY is not set.'
}
if ($PublishableKey -match 'service_role|sb_secret_') {
    throw 'SAFETY STOP: publishable-key variable contains a server secret.'
}

$Email = Read-Host 'Existing STAGING test e-mail'
$SecurePassword = Read-Host 'Existing STAGING test password' -AsSecureString
$SecureServerKey = Read-Host 'STAGING server secret/service-role key' -AsSecureString
$PasswordBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
$ServerKeyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureServerKey)
$PlainPassword = $null
$ServerKey = $null
$AccessToken = $null
$UserId = $null
$OriginalCompleted = $null
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

function Get-AdminHeaders {
    param([Parameter(Mandatory)] [string] $Key)
    $headers = @{ apikey = $Key }
    if ($Key.Split('.').Count -eq 3) {
        $headers.Authorization = "Bearer $Key"
    }
    return $headers
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

function Set-StagingCompletedMasters {
    param(
        [Parameter(Mandatory)] [int] $Value,
        [Parameter(Mandatory)] [hashtable] $Headers,
        [Parameter(Mandatory)] [string] $EncodedUserId
    )
    $result = Invoke-RqsJson -Method PATCH `
        -Uri "$SupabaseUrl/rest/v1/profiles?id=eq.$EncodedUserId" `
        -Headers ($Headers + @{ Prefer = 'return=representation' }) `
        -Body @{ completed_masters = $Value }
    if ($result.StatusCode -notin 200, 204) {
        throw "Failed to set staging completed_masters=$Value (HTTP $($result.StatusCode))."
    }
}

function Get-StagingProfileAdmin {
    param(
        [Parameter(Mandatory)] [hashtable] $Headers,
        [Parameter(Mandatory)] [string] $EncodedUserId
    )
    $result = Invoke-RqsJson -Method GET `
        -Uri "$SupabaseUrl/rest/v1/profiles?id=eq.$EncodedUserId&select=id,role,completed_masters" `
        -Headers $Headers
    if ($result.StatusCode -ne 200 -or $null -eq $result.Json -or $result.Json.Count -ne 1) {
        throw "Admin staging profile read failed (HTTP $($result.StatusCode))."
    }
    return $result.Json[0]
}

function Get-ActiveReservationCount {
    param(
        [Parameter(Mandatory)] [hashtable] $Headers,
        [Parameter(Mandatory)] [string] $EncodedUserId
    )
    $result = Invoke-RqsJson -Method GET `
        -Uri "$SupabaseUrl/rest/v1/mastering_quota_reservations?user_id=eq.$EncodedUserId&status=eq.reserved&select=id" `
        -Headers $Headers
    if ($result.StatusCode -ne 200) {
        throw "Admin reservation read failed (HTTP $($result.StatusCode))."
    }
    return @($result.Json).Count
}

function Remove-TestReservations {
    param(
        [Parameter(Mandatory)] [hashtable] $Headers,
        [Parameter(Mandatory)] [string] $EncodedUserId
    )
    $result = Invoke-RqsJson -Method DELETE `
        -Uri "$SupabaseUrl/rest/v1/mastering_quota_reservations?user_id=eq.$EncodedUserId" `
        -Headers $Headers
    if ($result.StatusCode -notin 200, 204) {
        throw "Reservation cleanup failed (HTTP $($result.StatusCode))."
    }
}

try {
    if ([string]::IsNullOrWhiteSpace($Email) -or $Email -notmatch '@') {
        throw 'A valid existing staging test e-mail is required.'
    }

    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordBstr)
    $ServerKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ServerKeyBstr)

    if ([string]::IsNullOrWhiteSpace($PlainPassword)) {
        throw 'The staging test password is required.'
    }
    if ([string]::IsNullOrWhiteSpace($ServerKey)) {
        throw 'The staging server secret/service-role key is required.'
    }
    if ($ServerKey -match '^sb_publishable_' -or $ServerKey -eq $PublishableKey) {
        throw 'SAFETY STOP: browser publishable key was supplied as the server key.'
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
    Write-Host 'STAGING_QUOTA_HTTP_REAL_JWT_ACQUIRED: PASS'

    $EncodedUserId = [uri]::EscapeDataString($UserId)
    $AdminHeaders = Get-AdminHeaders -Key $ServerKey

    $profile = Get-StagingProfileAdmin -Headers $AdminHeaders -EncodedUserId $EncodedUserId
    if ([string]$profile.role -ne 'free') {
        throw "Disposable staging profile must be free for this gate; found '$($profile.role)'."
    }
    $OriginalCompleted = [int]$profile.completed_masters
    if ($OriginalCompleted -lt 0 -or $OriginalCompleted -gt 3) {
        throw "Unexpected original completed_masters=$OriginalCompleted."
    }

    $activeBefore = Get-ActiveReservationCount -Headers $AdminHeaders -EncodedUserId $EncodedUserId
    if ($activeBefore -ne 0) {
        throw "SAFETY STOP: disposable staging identity has $activeBefore active reservation(s) before the test."
    }
    Write-Host 'STAGING_QUOTA_HTTP_PREFLIGHT: PASS'

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
    Write-Host 'STAGING_QUOTA_HTTP_CANDIDATE_INSTALL: PASS'

    $env:SUPABASE_URL = $SupabaseUrl
    $env:SUPABASE_SECRET_KEY = $ServerKey
    $env:RQS_MASTERING_V2_STORAGE_ENV = 'staging'
    $env:RQS_MASTERING_V2_BUCKET_NAME = 'rqs-mastering-v2-staging-quota-gate-placeholder'
    $env:RQS_MASTERING_V2_AWS_REGION = 'sa-east-1'
    $env:PORT = [string]$Port
    $env:STRIPE_SECRET_KEY = 'sk_test_quota_gate_placeholder'
    $env:STRIPE_WEBHOOK_SECRET = 'whsec_quota_gate_placeholder'

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
        $health = Invoke-RqsJson -Method GET -Uri "$BaseUrl/health"
        if ($health.StatusCode -eq 200) { $HealthReady = $true; break }
    }
    if (-not $HealthReady) { throw 'Candidate server did not become healthy within the timeout.' }
    Write-Host 'STAGING_QUOTA_HTTP_CANDIDATE_HEALTH: PASS'

    # HTTP release path: force Free to 2/3, allow reserve, then fail input
    # validation before any S3 call. The controller must release the reservation.
    Set-StagingCompletedMasters -Value 2 -Headers $AdminHeaders -EncodedUserId $EncodedUserId

    $releaseResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" `
        -Headers @{ Authorization = "Bearer $AccessToken" } `
        -Form @{
            s3Key = "uploads/$UserId/owned.invalid"
            destination = 'streaming'
            platform = 'spotify'
            atmosphere = 'clear_sky'
            intensity_percent = '50'
            soundcloud_mode = 'standard'
            preview = 'false'
        } -SkipHttpErrorCheck
    $releaseResult = [pscustomobject]@{
        StatusCode = [int]$releaseResponse.StatusCode
        Raw = $releaseResponse.Content
    }
    if ($releaseResult.StatusCode -ne 400) {
        throw "Release-path request expected HTTP 400, got $($releaseResult.StatusCode). Body: $($releaseResult.Raw)"
    }

    Start-Sleep -Milliseconds 300
    $afterReleaseProfile = Get-StagingProfileAdmin -Headers $AdminHeaders -EncodedUserId $EncodedUserId
    if ([int]$afterReleaseProfile.completed_masters -ne 2) {
        throw 'HTTP failure path changed completed_masters; expected it to remain 2.'
    }
    if ((Get-ActiveReservationCount -Headers $AdminHeaders -EncodedUserId $EncodedUserId) -ne 0) {
        throw 'HTTP failure path left an active quota reservation.'
    }
    Write-Host 'STAGING_HTTP_QUOTA_RESERVE_RELEASE: PASS'

    # HTTP quota-exhausted path: at 3/3 the controller must return 429 before
    # input resolution/S3.
    Set-StagingCompletedMasters -Value 3 -Headers $AdminHeaders -EncodedUserId $EncodedUserId

    $quotaResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" `
        -Headers @{ Authorization = "Bearer $AccessToken" } `
        -Form @{
            s3Key = "uploads/$UserId/owned.wav"
            destination = 'streaming'
            platform = 'spotify'
            atmosphere = 'clear_sky'
            intensity_percent = '50'
            soundcloud_mode = 'standard'
            preview = 'false'
        } -SkipHttpErrorCheck
    $quotaJson = $quotaResponse.Content | ConvertFrom-Json
    $quotaResult = [pscustomobject]@{
        StatusCode = [int]$quotaResponse.StatusCode
        Json = $quotaJson
        Raw = $quotaResponse.Content
    }
    Assert-Http -Name 'STAGING_HTTP_FREE_3_OF_3_429' -ExpectedStatus 429 -Response $quotaResult -ExpectedCode 'MASTERING_QUOTA_EXCEEDED'

    if ((Get-ActiveReservationCount -Headers $AdminHeaders -EncodedUserId $EncodedUserId) -ne 0) {
        throw 'Quota-exhausted HTTP path unexpectedly left an active reservation.'
    }
    $afterQuotaProfile = Get-StagingProfileAdmin -Headers $AdminHeaders -EncodedUserId $EncodedUserId
    if ([int]$afterQuotaProfile.completed_masters -ne 3) {
        throw 'Quota-exhausted HTTP path changed completed_masters unexpectedly.'
    }

    Write-Host 'MASTERING_V2_STAGING_HTTP_QUOTA: PASS'
    Write-Host 'S3_REQUESTS_PERFORMED: NONE'
    Write-Host 'PRODUCTION_REQUESTS_PERFORMED: NONE'
    Write-Host 'SECRETS_PRINTED: NONE'
    Write-Host "VALIDATION_LOG_DIR: $RunDir"
}
finally {
    if ($null -ne $ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        try { $ServerProcess.WaitForExit(5000) | Out-Null } catch {}
    }

    if ($null -ne $ServerKey -and $null -ne $UserId) {
        try {
            $AdminHeaders = Get-AdminHeaders -Key $ServerKey
            $EncodedUserId = [uri]::EscapeDataString($UserId)
            if ($null -ne $OriginalCompleted) {
                Set-StagingCompletedMasters -Value ([int]$OriginalCompleted) -Headers $AdminHeaders -EncodedUserId $EncodedUserId
            }
            Remove-TestReservations -Headers $AdminHeaders -EncodedUserId $EncodedUserId
            Write-Host 'STAGING_QUOTA_HTTP_CLEANUP: PASS'
        }
        catch {
            Write-Error "STAGING cleanup failed: $($_.Exception.Message)"
        }
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

    if ($PasswordBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordBstr)
    }
    if ($ServerKeyBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ServerKeyBstr)
    }
    $PlainPassword = $null
    $ServerKey = $null
    $AccessToken = $null
    $SecurePassword = $null
    $SecureServerKey = $null
}
