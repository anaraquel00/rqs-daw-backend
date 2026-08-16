#requires -Version 7.0
<#
RQS Mastering V2 — staging S3 preflight.
READ ONLY: no bucket/object/IAM mutation.

Purpose:
  Confirm the local AWS CLI identity/region and inspect only the dedicated
  staging bucket candidate before any provisioning or real audio upload.

Safety:
  - never queries the production Mastering bucket
  - never creates/deletes/modifies a bucket or object
  - never prints AWS secret/access-key material
#>

$ErrorActionPreference = 'Stop'

$ExpectedRegion = 'sa-east-1'
$StagingBucket = 'rqs-mastering-v2-staging-uwrqbywapomuloresoek'
$ForbiddenProductionBucket = 'amzn-rqs-bunker-sa'

if ($StagingBucket -eq $ForbiddenProductionBucket) {
    throw 'SAFETY STOP: staging bucket name equals the production bucket.'
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host 'AWS_CLI: NOT_FOUND'
    Write-Host 'NEXT_ACTION: Install/configure AWS CLI before staging storage validation.'
    exit 2
}

Write-Host "AWS_CLI: $(& aws --version 2>&1)"

$identityRaw = & aws sts get-caller-identity --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host 'AWS_STS_IDENTITY: FAIL'
    Write-Host $identityRaw
    exit 3
}

$identity = $identityRaw | ConvertFrom-Json
Write-Host 'AWS_STS_IDENTITY: PASS'
Write-Host "AWS_ACCOUNT_ID: $($identity.Account)"
Write-Host "AWS_CALLER_ARN: $($identity.Arn)"

$ConfiguredRegion = [string]$env:AWS_REGION
if ([string]::IsNullOrWhiteSpace($ConfiguredRegion)) {
    $ConfiguredRegion = [string]$env:AWS_DEFAULT_REGION
}
if ([string]::IsNullOrWhiteSpace($ConfiguredRegion)) {
    $ConfiguredRegion = [string](& aws configure get region 2>$null)
}
if ([string]::IsNullOrWhiteSpace($ConfiguredRegion)) {
    $ConfiguredRegion = $ExpectedRegion
}

Write-Host "AWS_EFFECTIVE_REGION: $ConfiguredRegion"
if ($ConfiguredRegion -ne $ExpectedRegion) {
    Write-Host "AWS_REGION_MATCH: WARN (expected $ExpectedRegion)"
} else {
    Write-Host 'AWS_REGION_MATCH: PASS'
}

Write-Host "STAGING_BUCKET_CANDIDATE: $StagingBucket"
Write-Host "PRODUCTION_BUCKET_QUERIED: NONE"

& aws s3api head-bucket --bucket $StagingBucket 2>$null
$BucketExists = ($LASTEXITCODE -eq 0)

if (-not $BucketExists) {
    Write-Host 'STAGING_BUCKET_EXISTS: NO_OR_NOT_ACCESSIBLE'
    Write-Host 'STAGING_S3_PREFLIGHT: PASS / PROVISIONING_REQUIRED'
    Write-Host 'AWS_MUTATION: NONE'
    exit 0
}

Write-Host 'STAGING_BUCKET_EXISTS: YES'

$LocationRaw = & aws s3api get-bucket-location --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $Location = $LocationRaw | ConvertFrom-Json
    $BucketRegion = if ([string]::IsNullOrWhiteSpace([string]$Location.LocationConstraint)) { 'us-east-1' } else { [string]$Location.LocationConstraint }
    Write-Host "STAGING_BUCKET_REGION: $BucketRegion"
    if ($BucketRegion -eq $ExpectedRegion) {
        Write-Host 'STAGING_BUCKET_REGION_MATCH: PASS'
    } else {
        Write-Host "STAGING_BUCKET_REGION_MATCH: FAIL (expected $ExpectedRegion)"
    }
} else {
    Write-Host 'STAGING_BUCKET_REGION: UNKNOWN'
}

$PublicBlockRaw = & aws s3api get-public-access-block --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $PublicBlock = $PublicBlockRaw | ConvertFrom-Json
    $cfg = $PublicBlock.PublicAccessBlockConfiguration
    $AllBlocked = $cfg.BlockPublicAcls -and $cfg.IgnorePublicAcls -and $cfg.BlockPublicPolicy -and $cfg.RestrictPublicBuckets
    Write-Host "STAGING_BUCKET_PUBLIC_ACCESS_BLOCK_ALL: $($AllBlocked.ToString().ToUpperInvariant())"
} else {
    Write-Host 'STAGING_BUCKET_PUBLIC_ACCESS_BLOCK_ALL: UNKNOWN'
}

$EncryptionRaw = & aws s3api get-bucket-encryption --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $Encryption = $EncryptionRaw | ConvertFrom-Json
    $Algorithms = @($Encryption.ServerSideEncryptionConfiguration.Rules.ApplyServerSideEncryptionByDefault.SSEAlgorithm) -join ','
    Write-Host "STAGING_BUCKET_ENCRYPTION: $Algorithms"
} else {
    Write-Host 'STAGING_BUCKET_ENCRYPTION: NOT_CONFIRMED'
}

$OwnershipRaw = & aws s3api get-bucket-ownership-controls --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $Ownership = $OwnershipRaw | ConvertFrom-Json
    $OwnershipModes = @($Ownership.OwnershipControls.Rules.ObjectOwnership) -join ','
    Write-Host "STAGING_BUCKET_OBJECT_OWNERSHIP: $OwnershipModes"
} else {
    Write-Host 'STAGING_BUCKET_OBJECT_OWNERSHIP: NOT_CONFIRMED'
}

$VersioningRaw = & aws s3api get-bucket-versioning --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $Versioning = $VersioningRaw | ConvertFrom-Json
    $VersioningStatus = if ($Versioning.Status) { [string]$Versioning.Status } else { 'Disabled/Unset' }
    Write-Host "STAGING_BUCKET_VERSIONING: $VersioningStatus"
} else {
    Write-Host 'STAGING_BUCKET_VERSIONING: UNKNOWN'
}

$PolicyStatusRaw = & aws s3api get-bucket-policy-status --bucket $StagingBucket --output json 2>&1
if ($LASTEXITCODE -eq 0) {
    $PolicyStatus = $PolicyStatusRaw | ConvertFrom-Json
    Write-Host "STAGING_BUCKET_POLICY_IS_PUBLIC: $($PolicyStatus.PolicyStatus.IsPublic)"
} else {
    Write-Host 'STAGING_BUCKET_POLICY_IS_PUBLIC: UNKNOWN_OR_NO_POLICY'
}

Write-Host 'STAGING_S3_PREFLIGHT: PASS / EXISTING_BUCKET_INSPECTED'
Write-Host 'AWS_MUTATION: NONE'
