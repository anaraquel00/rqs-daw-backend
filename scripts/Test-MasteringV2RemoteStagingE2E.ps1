#requires -Version 7.0
<#
RQS Mastering V2 — remote isolated-staging E2E validator.

Default mode is preflight only. It performs no S3 object write.
Real staging PUT / Preview / Full Master requires -AllowStagingObjectMutation.
Optional cleanup requires -AllowStagingCleanup and an AWS CLI identity scoped to
only the dedicated staging bucket.

Never prints passwords, JWTs, signed URLs, AWS credentials or server secrets.
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^https://')]
    [string]$BackendUrl,

    [Parameter(Mandatory=$true)]
    [ValidatePattern('^https://')]
    [string]$FrontendOrigin,

    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')]
    [string]$StagingBucket,

    [string]$AudioFile = '',
    [switch]$AllowStagingObjectMutation,
    [switch]$AllowStagingCleanup
)

$ErrorActionPreference = 'Stop'

$ProductionBackend = 'https://m2ud3r3gh7vocnc3hzvhnv4s4m0dmujw.lambda-url.sa-east-1.on.aws'
$ProductionBucket = 'amzn-rqs-bunker-sa'
$ProductionStudioOrigin = 'https://studio.raquelsynths.com'
$ExpectedAccount = '861276090852'
$ExpectedRegion = 'sa-east-1'
$ExpectedSupabaseRef = 'uwrqbywapomuloresoek'
$SupabaseUrl = "https://$ExpectedSupabaseRef.supabase.co"
$PublishableKey = [string]$env:RQS_STAGING_SUPABASE_PUBLISHABLE_KEY
$TestEmail = [string]$env:RQS_STAGING_TEST_EMAIL
$PlainPassword = [string]$env:RQS_STAGING_TEST_PASSWORD
$AccessToken = $null
$UserId = $null
$SecurePassword = $null
$Bstr = [IntPtr]::Zero
$InputKey = $null
$OutputKey = $null
$PreviewPath = $null
$MasterPath = $null

function Normalize-Origin([string]$Value) {
    $uri = [Uri]$Value
    if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw "Invalid HTTPS origin: $Value"
    }
    if ($uri.AbsolutePath -ne '/') {
        throw "Origin must not contain a path: $Value"
    }
    return $uri.GetLeftPart([System.UriPartial]::Authority)
}

function Normalize-Backend([string]$Value) {
    $uri = [Uri]$Value
    if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw "Invalid HTTPS backend URL: $Value"
    }
    if ($uri.AbsolutePath -ne '/') {
        throw "Backend URL must not contain a path: $Value"
    }
    return $uri.GetLeftPart([System.UriPartial]::Authority)
}

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

    return [pscustomobject]@{
        StatusCode = [int]$response.StatusCode
        Json = $json
        Headers = $response.Headers
    }
}

function Assert-Status([string]$Name, [int]$Expected, $Response, [string]$ExpectedCode = '') {
    if ([int]$Response.StatusCode -ne $Expected) {
        throw "$Name failed: expected HTTP $Expected, got $($Response.StatusCode)."
    }
    if ($ExpectedCode) {
        $actual = [string]$Response.Json.code
        if ($actual -ne $ExpectedCode) {
            throw "$Name failed: expected code '$ExpectedCode', got '$actual'."
        }
    }
    Write-Host "$Name`: PASS"
}

function Get-Profile([hashtable]$Headers, [string]$Id) {
    $encodedId = [Uri]::EscapeDataString($Id)
    $response = Invoke-RqsJson -Method GET -Uri "$SupabaseUrl/rest/v1/profiles?id=eq.$encodedId&select=id,role,completed_masters" -Headers $Headers
    if ($response.StatusCode -ne 200 -or $null -eq $response.Json -or $response.Json.Count -ne 1) {
        throw "Staging profile lookup failed with HTTP $($response.StatusCode)."
    }
    return $response.Json[0]
}

function Get-KeyFromSignedDownload([string]$SignedUrl, [string]$Prefix) {
    $uri = [Uri]$SignedUrl
    $decoded = [Uri]::UnescapeDataString($uri.AbsolutePath.TrimStart('/'))
    $index = $decoded.IndexOf($Prefix, [StringComparison]::Ordinal)
    if ($index -lt 0) {
        throw "Signed download path does not contain expected '$Prefix' namespace."
    }
    return $decoded.Substring($index)
}

function Assert-SignedUrlBoundary([string]$SignedUrl, [string]$ExpectedBucket) {
    $uri = [Uri]$SignedUrl
    $raw = $uri.AbsoluteUri
    if ($raw -match [regex]::Escape($ProductionBucket)) {
        throw 'SAFETY STOP: signed URL references the production bucket.'
    }
    if ($raw -notmatch [regex]::Escape($ExpectedBucket)) {
        throw 'Signed URL does not reference the approved staging bucket.'
    }
}

$BackendUrl = Normalize-Backend $BackendUrl
$FrontendOrigin = Normalize-Origin $FrontendOrigin

if ($BackendUrl -eq $ProductionBackend) {
    throw 'SAFETY STOP: staging backend equals production backend.'
}
if ($FrontendOrigin -eq $ProductionStudioOrigin) {
    throw 'SAFETY STOP: staging frontend origin equals production Studio origin.'
}
if ($StagingBucket -eq $ProductionBucket) {
    throw 'SAFETY STOP: staging bucket equals production bucket.'
}
if ([string]::IsNullOrWhiteSpace($PublishableKey)) {
    throw 'RQS_STAGING_SUPABASE_PUBLISHABLE_KEY is not set.'
}
if ($PublishableKey -match 'service_role|sb_secret_') {
    throw 'SAFETY STOP: server/service secret must never be supplied to this validator.'
}
if ($AllowStagingCleanup -and -not $AllowStagingObjectMutation) {
    throw '-AllowStagingCleanup requires -AllowStagingObjectMutation.'
}

try {
    $health = Invoke-RqsJson -Method GET -Uri "$BackendUrl/health" -Headers @{ Origin = $FrontendOrigin }
    Assert-Status 'STAGING_REMOTE_HEALTH' 200 $health

    $allowedCors = [string]$health.Headers['Access-Control-Allow-Origin']
    if ($allowedCors -ne $FrontendOrigin) {
        throw "Exact staging CORS failed. Expected '$FrontendOrigin', got '$allowedCors'."
    }
    Write-Host 'STAGING_REMOTE_EXACT_CORS: PASS'

    $productionOriginProbe = Invoke-RqsJson -Method GET -Uri "$BackendUrl/health" -Headers @{ Origin = $ProductionStudioOrigin }
    $productionCors = [string]$productionOriginProbe.Headers['Access-Control-Allow-Origin']
    if (-not [string]::IsNullOrWhiteSpace($productionCors)) {
        throw 'SAFETY STOP: staging backend grants CORS authority to production Studio origin.'
    }
    Write-Host 'STAGING_REMOTE_PRODUCTION_ORIGIN_CORS_DENIED: PASS'

    $capabilities = Invoke-RqsJson -Method GET -Uri "$BackendUrl/mastering/v2/capabilities" -Headers @{ Origin = $FrontendOrigin }
    Assert-Status 'STAGING_REMOTE_CAPABILITIES' 200 $capabilities

    $payment = Invoke-RqsJson -Method POST -Uri "$BackendUrl/payment/stripe-webhook" -Headers @{ Origin = $FrontendOrigin } -Body @{}
    Assert-Status 'STAGING_REMOTE_PAYMENT_DISABLED' 503 $payment 'PAYMENT_DISABLED'

    $noAuth = Invoke-RqsJson -Method GET -Uri "$BackendUrl/mastering/v2/presigned-url?filename=staging-e2e.wav" -Headers @{ Origin = $FrontendOrigin }
    Assert-Status 'STAGING_REMOTE_AUTH_REQUIRED' 401 $noAuth 'AUTH_REQUIRED'

    $invalidAuth = Invoke-RqsJson -Method GET -Uri "$BackendUrl/mastering/v2/presigned-url?filename=staging-e2e.wav" -Headers @{
        Origin = $FrontendOrigin
        Authorization = 'Bearer invalid-staging-token'
    }
    Assert-Status 'STAGING_REMOTE_INVALID_JWT' 401 $invalidAuth 'AUTH_INVALID'

    if ([string]::IsNullOrWhiteSpace($TestEmail)) {
        $TestEmail = Read-Host 'Existing disposable STAGING test e-mail'
    }
    if ([string]::IsNullOrWhiteSpace($PlainPassword)) {
        $SecurePassword = Read-Host 'Existing disposable STAGING test password' -AsSecureString
        $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
        $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
    }

    if ([string]::IsNullOrWhiteSpace($TestEmail) -or $TestEmail -notmatch '@') {
        throw 'A valid staging test e-mail is required.'
    }
    if ([string]::IsNullOrWhiteSpace($PlainPassword)) {
        throw 'A staging test password is required.'
    }

    $publicHeaders = @{ apikey = $PublishableKey }
    $signin = Invoke-RqsJson -Method POST -Uri "$SupabaseUrl/auth/v1/token?grant_type=password" -Headers $publicHeaders -Body @{
        email = $TestEmail
        password = $PlainPassword
    }
    if ($signin.StatusCode -notin 200, 201 -or -not $signin.Json.access_token -or -not $signin.Json.user.id) {
        throw "Staging sign-in failed with HTTP $($signin.StatusCode)."
    }

    $AccessToken = [string]$signin.Json.access_token
    $UserId = [string]$signin.Json.user.id
    Write-Host 'STAGING_REMOTE_REAL_JWT: PASS'

    $userHeaders = @{
        apikey = $PublishableKey
        Authorization = "Bearer $AccessToken"
    }
    $backendHeaders = @{
        Origin = $FrontendOrigin
        Authorization = "Bearer $AccessToken"
    }

    $profileBefore = Get-Profile $userHeaders $UserId
    if ([string]$profileBefore.id -ne $UserId) {
        throw 'Owner profile identity mismatch.'
    }
    Write-Host 'STAGING_REMOTE_OWNER_PROFILE: PASS'

    if ($AllowStagingObjectMutation) {
        if ([string]$profileBefore.role -ne 'free' -or [int]$profileBefore.completed_masters -ne 0) {
            throw 'Full E2E requires a disposable Free staging identity with completed_masters=0.'
        }
    }

    $presignName = "staging-e2e-$([guid]::NewGuid().ToString('N')).wav"
    if ($AllowStagingObjectMutation) {
        if ([string]::IsNullOrWhiteSpace($AudioFile) -or -not (Test-Path -LiteralPath $AudioFile -PathType Leaf)) {
            throw '-AudioFile must point to an existing WAV/MP3 file when object mutation is enabled.'
        }
        $ext = [IO.Path]::GetExtension($AudioFile).ToLowerInvariant()
        if ($ext -notin '.wav', '.mp3') {
            throw 'AudioFile must be WAV or MP3.'
        }
        if ((Get-Item -LiteralPath $AudioFile).Length -gt 1GB) {
            throw 'AudioFile exceeds the 1 GiB Mastering V2 limit.'
        }
        $presignName = [IO.Path]::GetFileName($AudioFile)
    }

    $encodedName = [Uri]::EscapeDataString($presignName)
    $presign = Invoke-RqsJson -Method GET -Uri "$BackendUrl/mastering/v2/presigned-url?filename=$encodedName" -Headers $backendHeaders
    Assert-Status 'STAGING_REMOTE_AUTHENTICATED_PRESIGN' 200 $presign

    $uploadUrl = [string]$presign.Json.uploadUrl
    $InputKey = [string]$presign.Json.s3Key
    if ([string]::IsNullOrWhiteSpace($uploadUrl) -or [string]::IsNullOrWhiteSpace($InputKey)) {
        throw 'Presign response is incomplete.'
    }
    if (-not $InputKey.StartsWith("uploads/$UserId/", [StringComparison]::Ordinal)) {
        throw 'Presign key is outside the authenticated user namespace.'
    }
    Assert-SignedUrlBoundary $uploadUrl $StagingBucket
    Write-Host 'STAGING_REMOTE_PRESIGN_BUCKET_ISOLATION: PASS'

    Write-Host 'STAGING_RUNTIME_PREFLIGHT: PASS'
    Write-Host 'STAGING_PRODUCTION_REQUESTS: NONE'
    Write-Host 'STAGING_SECRETS_PRINTED: NONE'

    if (-not $AllowStagingObjectMutation) {
        Write-Host 'STAGING_OBJECT_MUTATION: NONE'
        Write-Host 'MASTERING_V2_ISOLATED_STAGING_E2E: PREFLIGHT_PASS / FULL_E2E_NOT_RUN'
        exit 0
    }

    $contentType = if ([IO.Path]::GetExtension($AudioFile).ToLowerInvariant() -eq '.mp3') { 'audio/mpeg' } else { 'audio/wav' }
    $put = Invoke-WebRequest -Method PUT -Uri $uploadUrl -InFile $AudioFile -ContentType $contentType -SkipHttpErrorCheck
    if ([int]$put.StatusCode -notin 200, 201) {
        throw "Staging S3 PUT failed with HTTP $($put.StatusCode)."
    }
    Write-Host 'STAGING_REMOTE_S3_PUT: PASS'

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) "rqs-staging-e2e-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $PreviewPath = Join-Path $tempRoot 'preview.wav'
    $MasterPath = Join-Path $tempRoot 'master.wav'

    $formBase = @{
        s3Key = $InputKey
        destination = 'streaming'
        platform = 'spotify'
        atmosphere = 'clear_sky'
        intensity_percent = '50'
        soundcloud_mode = 'standard'
    }

    $previewForm = @{} + $formBase
    $previewForm.preview = 'true'
    $preview = Invoke-WebRequest -Method POST -Uri "$BackendUrl/mastering/v2/process" -Headers $backendHeaders -Form $previewForm -OutFile $PreviewPath -PassThru -SkipHttpErrorCheck
    if ([int]$preview.StatusCode -ne 200 -or -not (Test-Path $PreviewPath) -or (Get-Item $PreviewPath).Length -le 44) {
        throw "Staging Preview failed with HTTP $($preview.StatusCode)."
    }
    Write-Host 'STAGING_REMOTE_PREVIEW_RENDER: PASS'

    $profileAfterPreview = Get-Profile $userHeaders $UserId
    if ([int]$profileAfterPreview.completed_masters -ne 0) {
        throw 'Preview unexpectedly consumed Full Master quota.'
    }
    Write-Host 'STAGING_REMOTE_PREVIEW_QUOTA_UNCHANGED: PASS'

    $fullForm = @{} + $formBase
    $fullForm.preview = 'false'
    $fullResponse = Invoke-WebRequest -Method POST -Uri "$BackendUrl/mastering/v2/process" -Headers $backendHeaders -Form $fullForm -SkipHttpErrorCheck
    if ([int]$fullResponse.StatusCode -ne 200) {
        throw "Staging Full Master failed with HTTP $($fullResponse.StatusCode)."
    }
    $fullJson = $fullResponse.Content | ConvertFrom-Json
    if (-not $fullJson.success -or [string]$fullJson.outputMode -ne 's3' -or -not $fullJson.downloadUrl) {
        throw 'Full Master response contract failed.'
    }

    $downloadUrl = [string]$fullJson.downloadUrl
    Assert-SignedUrlBoundary $downloadUrl $StagingBucket
    $OutputKey = Get-KeyFromSignedDownload $downloadUrl 'masters/'
    if (-not $OutputKey.StartsWith("masters/$UserId/", [StringComparison]::Ordinal)) {
        throw 'Master output is outside the authenticated user namespace.'
    }
    Write-Host 'STAGING_REMOTE_FULL_MASTER_RESPONSE: PASS'

    $download = Invoke-WebRequest -Method GET -Uri $downloadUrl -OutFile $MasterPath -PassThru -SkipHttpErrorCheck
    if ([int]$download.StatusCode -ne 200 -or -not (Test-Path $MasterPath) -or (Get-Item $MasterPath).Length -le 44) {
        throw "Staging master download failed with HTTP $($download.StatusCode)."
    }
    Write-Host 'STAGING_REMOTE_FULL_MASTER_DOWNLOAD: PASS'

    $profileAfterFull = Get-Profile $userHeaders $UserId
    if ([int]$profileAfterFull.completed_masters -ne 1) {
        throw "Full Master quota mismatch: expected 1, got $($profileAfterFull.completed_masters)."
    }
    Write-Host 'STAGING_REMOTE_FULL_MASTER_QUOTA_EXACTLY_ONCE: PASS'

    if ($AllowStagingCleanup) {
        if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
            throw 'AWS CLI is required for -AllowStagingCleanup.'
        }
        $identityRaw = & aws sts get-caller-identity --output json 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw 'AWS STS identity lookup failed for staging cleanup.'
        }
        $identity = $identityRaw | ConvertFrom-Json
        if ([string]$identity.Account -ne $ExpectedAccount) {
            throw 'AWS cleanup identity is in the wrong account.'
        }
        if ($StagingBucket -eq $ProductionBucket) {
            throw 'SAFETY STOP: cleanup bucket equals production.'
        }

        foreach ($key in @($InputKey, $OutputKey)) {
            if ([string]::IsNullOrWhiteSpace($key)) { continue }
            if (-not ($key.StartsWith("uploads/$UserId/") -or $key.StartsWith("masters/$UserId/"))) {
                throw "Cleanup key is outside the test user namespace: $key"
            }
            & aws s3api delete-object --bucket $StagingBucket --key $key --region $ExpectedRegion --no-cli-pager | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to delete staging test key: $key"
            }
        }
        Write-Host 'STAGING_REMOTE_TEST_OBJECT_CLEANUP: PASS'
    }
    else {
        Write-Host 'STAGING_REMOTE_TEST_OBJECT_CLEANUP: DEFERRED_TO_OPERATOR_OR_LIFECYCLE'
    }

    Write-Host 'STAGING_OBJECT_MUTATION: DEDICATED_STAGING_ONLY'
    Write-Host 'STAGING_PRODUCTION_REQUESTS: NONE'
    Write-Host 'STAGING_SECRETS_PRINTED: NONE'
    Write-Host 'MASTERING_V2_ISOLATED_STAGING_HTTP_E2E: PASS'
}
finally {
    if ($Bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
    }
    $PlainPassword = $null
    $AccessToken = $null
    $SecurePassword = $null
    if ($PreviewPath -and (Test-Path -LiteralPath $PreviewPath)) { Remove-Item -LiteralPath $PreviewPath -Force }
    if ($MasterPath -and (Test-Path -LiteralPath $MasterPath)) { Remove-Item -LiteralPath $MasterPath -Force }
    if ($PreviewPath) {
        $dir = Split-Path -Parent $PreviewPath
        if ($dir -and (Test-Path -LiteralPath $dir)) { Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue }
    }
}
