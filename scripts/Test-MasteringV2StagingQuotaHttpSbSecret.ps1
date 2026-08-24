#requires -Version 7.0
<#
RQS Mastering V2 — staging quota HTTP wrapper for modern Supabase sb_secret_* keys.

Why this wrapper exists:
  Supabase intentionally rejects sb_secret_* keys when they appear to come from
  a browser-like User-Agent. PowerShell Invoke-WebRequest may use a browser-like
  default UA, so the base validator can receive HTTP 401 before making any
  staging mutation.

This wrapper executes the existing quota validator in the same PowerShell
process while forcing a backend-style User-Agent for Invoke-WebRequest.
No key is hard-coded or printed.
#>

$ErrorActionPreference = 'Stop'

$Validator = Join-Path $PSScriptRoot 'Test-MasteringV2StagingQuotaHttp.ps1'
if (-not (Test-Path -LiteralPath $Validator)) {
    throw "Base validator not found: $Validator"
}

$PreviousDefault = $PSDefaultParameterValues['Invoke-WebRequest:UserAgent']
try {
    $PSDefaultParameterValues['Invoke-WebRequest:UserAgent'] = 'rqs-mastering-v2-staging-validator/1.0'
    & $Validator
}
finally {
    if ($null -eq $PreviousDefault) {
        $PSDefaultParameterValues.Remove('Invoke-WebRequest:UserAgent') | Out-Null
    }
    else {
        $PSDefaultParameterValues['Invoke-WebRequest:UserAgent'] = $PreviousDefault
    }
}
