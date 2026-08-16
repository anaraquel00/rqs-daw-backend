#requires -Version 7.0
<#
RQS Mastering V2 — isolated staging Auth/JWT validator.

STAGING ONLY. Uses normal Supabase Auth signup/sign-in APIs and never prints the
password or access token. The created staging identity is intentionally retained
for the next real backend HTTP gate.

Prerequisite:
  $env:RQS_STAGING_SUPABASE_PUBLISHABLE_KEY = '<staging publishable/anon key>'

The key above is a browser-safe project key; do NOT use a service-role/secret key.
#>

$ErrorActionPreference = 'Stop'

$ExpectedProjectRef = 'uwrqbywapomuloresoek'
$SupabaseUrl = "https://$ExpectedProjectRef.supabase.co"
$PublishableKey = [string]$env:RQS_STAGING_SUPABASE_PUBLISHABLE_KEY

if ([string]::IsNullOrWhiteSpace($PublishableKey)) {
    throw 'RQS_STAGING_SUPABASE_PUBLISHABLE_KEY is not set.'
}

if ($PublishableKey -match 'service_role|sb_secret_') {
    throw 'SAFETY STOP: a server/service secret must never be used by this browser-auth validator.'
}

$Email = Read-Host 'Disposable STAGING test e-mail'
$SecurePassword = Read-Host 'Disposable STAGING test password' -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
$PlainPassword = $null
$AccessToken = $null
$UserId = $null

function Invoke-RqsJson {
    param(
        [Parameter(Mandatory)] [string] $Method,
        [Parameter(Mandatory)] [string] $Uri,
        [Parameter(Mandatory)] [hashtable] $Headers,
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

try {
    if ([string]::IsNullOrWhiteSpace($Email) -or $Email -notmatch '@') {
        throw 'A valid disposable staging e-mail is required.'
    }

    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
    if ([string]::IsNullOrWhiteSpace($PlainPassword) -or $PlainPassword.Length -lt 8) {
        throw 'The disposable staging password must contain at least 8 characters.'
    }

    $PublicHeaders = @{ apikey = $PublishableKey }

    $signup = Invoke-RqsJson -Method POST -Uri "$SupabaseUrl/auth/v1/signup" -Headers $PublicHeaders -Body @{
        email = $Email
        password = $PlainPassword
    }

    if ($signup.StatusCode -notin 200, 201, 400, 422) {
        throw "Unexpected signup HTTP status: $($signup.StatusCode)"
    }

    if ($signup.StatusCode -in 200, 201 -and $signup.Json.access_token) {
        $AccessToken = [string]$signup.Json.access_token
        $UserId = [string]$signup.Json.user.id
        Write-Host 'STAGING_AUTH_SIGNUP: PASS'
    }
    else {
        # Existing user, or signup requires e-mail confirmation. Try normal sign-in.
        $signin = Invoke-RqsJson -Method POST -Uri "$SupabaseUrl/auth/v1/token?grant_type=password" -Headers $PublicHeaders -Body @{
            email = $Email
            password = $PlainPassword
        }

        if ($signin.StatusCode -notin 200, 201 -or -not $signin.Json.access_token) {
            Write-Host 'STAGING_AUTH_SIGNUP_OR_SIGNIN: WAIT'
            Write-Host 'ACTION_REQUIRED: Confirm the disposable staging account e-mail if Supabase requested confirmation, then rerun this script.'
            exit 2
        }

        $AccessToken = [string]$signin.Json.access_token
        $UserId = [string]$signin.Json.user.id
        Write-Host 'STAGING_AUTH_SIGNIN: PASS'
    }

    if ([string]::IsNullOrWhiteSpace($AccessToken) -or [string]::IsNullOrWhiteSpace($UserId)) {
        throw 'Staging Auth did not return a usable session.'
    }

    $UserHeaders = @{
        apikey = $PublishableKey
        Authorization = "Bearer $AccessToken"
    }

    $me = Invoke-RqsJson -Method GET -Uri "$SupabaseUrl/auth/v1/user" -Headers $UserHeaders
    if ($me.StatusCode -ne 200 -or [string]$me.Json.id -ne $UserId) {
        throw "Real JWT verification failed (HTTP $($me.StatusCode))."
    }
    Write-Host 'STAGING_REAL_JWT_AUTH_USER: PASS'

    $encodedId = [uri]::EscapeDataString($UserId)
    $profile = Invoke-RqsJson -Method GET -Uri "$SupabaseUrl/rest/v1/profiles?id=eq.$encodedId&select=id,role,completed_masters" -Headers $UserHeaders
    if ($profile.StatusCode -ne 200 -or $null -eq $profile.Json -or $profile.Json.Count -ne 1) {
        throw "Authenticated owner profile read failed (HTTP $($profile.StatusCode))."
    }

    $row = $profile.Json[0]
    if ([string]$row.id -ne $UserId -or [string]$row.role -ne 'free' -or [int]$row.completed_masters -ne 0) {
        throw 'Signup profile contract failed: expected own free profile with completed_masters=0.'
    }
    Write-Host 'STAGING_SIGNUP_PROFILE_FREE_0: PASS'
    Write-Host 'STAGING_OWNER_PROFILE_SELECT: PASS'

    $forbiddenUpdate = Invoke-RqsJson -Method PATCH -Uri "$SupabaseUrl/rest/v1/profiles?id=eq.$encodedId" -Headers ($UserHeaders + @{ Prefer = 'return=representation' }) -Body @{
        role = 'premium'
    }
    if ($forbiddenUpdate.StatusCode -ge 200 -and $forbiddenUpdate.StatusCode -lt 300) {
        throw 'SECURITY FAILURE: authenticated browser profile UPDATE unexpectedly succeeded.'
    }
    Write-Host 'STAGING_BROWSER_PROFILE_UPDATE_DENIED: PASS'

    $reservationId = [guid]::NewGuid().ToString()
    $forbiddenRpc = Invoke-RqsJson -Method POST -Uri "$SupabaseUrl/rest/v1/rpc/reserve_mastering_quota" -Headers $UserHeaders -Body @{
        p_user_id = $UserId
        p_reservation_id = $reservationId
    }
    if ($forbiddenRpc.StatusCode -ge 200 -and $forbiddenRpc.StatusCode -lt 300) {
        throw 'SECURITY FAILURE: authenticated browser quota RPC unexpectedly succeeded.'
    }
    Write-Host 'STAGING_BROWSER_QUOTA_RPC_DENIED: PASS'

    Write-Host 'MASTERING_V2_STAGING_AUTH_JWT: PASS'
    Write-Host 'STAGING_TEST_IDENTITY: RETAINED_FOR_BACKEND_HTTP_GATE'
    Write-Host 'SECRETS_PRINTED: NONE'
}
finally {
    if ($Bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
    }
    $PlainPassword = $null
    $AccessToken = $null
    $SecurePassword = $null
}
