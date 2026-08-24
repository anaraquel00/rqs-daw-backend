#requires -Version 7.0
param(
    [string]$InputRoot = 'D:\RQS-Dev\real_audio_ab\input\Testes RQS DAW',
    [string]$InputFile = '',
    [double]$PreviewStart = [double]::NaN
)

$ErrorActionPreference = 'Stop'

$CandidateBranch = 'integration/mastering-v2-secure-p1-20260816'
$CandidateRepo = 'anaraquel00/rqs-daw-backend'
$StandaloneRepo = 'C:\!git\Core\rqs-daw-backend-mastering'
$ExpectedStandaloneHead = '58d30a345b668f8dd8f07f9dffc3972da9b182ce'
$ValidationRoot = 'D:\RQS-Dev\mastering_v2_real_audio_gate'
$RunDir = Join-Path $ValidationRoot (Get-Date -Format 'yyyyMMdd_HHmmss')
$ExtractDir = Join-Path $RunDir 'candidate'
$ArchivePath = Join-Path $RunDir 'candidate.zip'
$EvidenceDir = Join-Path $RunDir 'evidence'
$ServerStdout = Join-Path $EvidenceDir 'server.stdout.log'
$ServerStderr = Join-Path $EvidenceDir 'server.stderr.log'
$PreviewHttp = Join-Path $RunDir 'preview_http.wav'
$PreviewCanonical = Join-Path $RunDir 'preview_canonical.wav'
$FullHttp = Join-Path $RunDir 'full_http.wav'
$FullCanonical = Join-Path $RunDir 'full_canonical.wav'
$FullResponsePath = Join-Path $EvidenceDir 'full_http_response.json'
$CompareScript = Join-Path $RunDir 'compare_audio.py'
$CompareReport = Join-Path $EvidenceDir 'comparison.json'
$ManifestPath = Join-Path $EvidenceDir 'EVIDENCE.txt'
$EvidenceZip = Join-Path $RunDir 'real_audio_evidence.zip'
$Port = 18083
$BaseUrl = "http://127.0.0.1:$Port"
$ServerProcess = $null
$RunStarted = Get-Date
$TempBefore = @()

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Required command not found: $Name" }
    return $cmd
}

function Invoke-CanonicalRender {
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][string]$InputPath,
        [Parameter(Mandatory)][string]$OutputPath,
        [switch]$Preview
    )

    $args = @(
        '-m', 'src.controllers.mastering_v2_cli', 'render',
        '--input', $InputPath,
        '--output', $OutputPath,
        '--destination', 'streaming',
        '--platform', 'soundcloud',
        '--atmosphere', 'clear_sky',
        '--intensity-percent', '50',
        '--requested-lufs', '-14',
        '--soundcloud-mode', 'standard'
    )
    if ($Preview) {
        $args += @('--preview', '--preview-start-seconds', [string]$PreviewStart)
    }

    Push-Location $StandaloneRepo
    try {
        & $PythonExe @args
        if ($LASTEXITCODE -ne 0) {
            throw "Canonical CLI render failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host '============================================================'
Write-Host ' RQS MASTERING V2 — LOCAL REAL-AUDIO INTEGRATION REGRESSION'
Write-Host '============================================================'
Write-Host 'S3: NOT USED'
Write-Host 'SUPABASE: NOT USED'
Write-Host 'PRODUCTION REQUESTS: NONE'
Write-Host 'GIT MUTATION OF CANONICAL REPO: NONE'

$Node = Assert-Command 'node'
$Npm = Assert-Command 'npm'
$Python = (Assert-Command 'python').Source

if (-not (Test-Path -LiteralPath $StandaloneRepo)) {
    throw "Canonical standalone repo not found: $StandaloneRepo"
}

$StandaloneHead = (& git -C $StandaloneRepo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not read standalone HEAD.' }
if ($StandaloneHead -ne $ExpectedStandaloneHead) {
    throw "SAFETY STOP: standalone HEAD is $StandaloneHead, expected $ExpectedStandaloneHead."
}
& git -C $StandaloneRepo diff --quiet
if ($LASTEXITCODE -ne 0) { throw 'SAFETY STOP: standalone tracked working tree has unstaged changes.' }
& git -C $StandaloneRepo diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw 'SAFETY STOP: standalone tracked working tree has staged changes.' }
Write-Host "CANONICAL_STANDALONE_HEAD: $StandaloneHead"
Write-Host 'CANONICAL_TRACKED_TREE: CLEAN'

if (-not (Test-Path -LiteralPath $InputRoot)) {
    throw "Real-audio input root not found: $InputRoot"
}

Write-Host ''
Write-Host '=== REAL-AUDIO INVENTORY REFRESH ==='
$Inventory = Get-ChildItem -LiteralPath $InputRoot -Recurse -File -ErrorAction Stop |
    Where-Object { $_.Extension.ToLowerInvariant() -in @('.wav', '.mp3', '.flac') } |
    Sort-Object FullName

if ($Inventory.Count -eq 0) { throw 'No real-audio files found in the configured input root.' }
$Inventory | Select-Object FullName, Length, LastWriteTime | Format-Table -AutoSize

$SelectionPolicy = 'EXPLICIT_INPUT'

if ([string]::IsNullOrWhiteSpace($InputFile)) {
    # Current canonical real-audio order for this project:
    # PRIMARY: Lockdown Protocol 145-175 s
    # BACKUP: Cybernetic Grid 285-315 s
    # Historical HUSARIA/Kwiat premaster windows remain fallback-only.
    $Lockdown = @($Inventory | Where-Object { $_.Name -match '(?i)^4-Lockdown Protocol\.wav$' })
    $Cybernetic = @($Inventory | Where-Object { $_.Name -match '(?i)^7-Cybernetic Grid.*\.wav$' })
    $Husaria = @($Inventory | Where-Object { $_.Name -match '(?i)HUSARIA.*Premaster.*\.wav$' })
    $Kwiat = @($Inventory | Where-Object { $_.Name -match '(?i)Kwiat.*Premaster.*\.wav$' })

    if ($Lockdown.Count -eq 1) {
        $InputFile = $Lockdown[0].FullName
        if ([double]::IsNaN($PreviewStart)) { $PreviewStart = 145.0 }
        $SelectionPolicy = 'LOCKDOWN_PRIMARY_145_175'
    }
    elseif ($Cybernetic.Count -eq 1) {
        $InputFile = $Cybernetic[0].FullName
        if ([double]::IsNaN($PreviewStart)) { $PreviewStart = 285.0 }
        $SelectionPolicy = 'CYBERNETIC_BACKUP_285_315'
    }
    elseif ($Husaria.Count -eq 1) {
        $InputFile = $Husaria[0].FullName
        if ([double]::IsNaN($PreviewStart)) { $PreviewStart = 290.0 }
        $SelectionPolicy = 'HUSARIA_FALLBACK_290_310'
    }
    elseif ($Kwiat.Count -eq 1) {
        $InputFile = $Kwiat[0].FullName
        if ([double]::IsNaN($PreviewStart)) { $PreviewStart = 270.0 }
        $SelectionPolicy = 'KWIAT_FALLBACK_270_290'
    }
    else {
        throw 'Could not select one unambiguous validated WAV. Re-run with -InputFile <full path> -PreviewStart <seconds>.'
    }
}

$InputFile = (Resolve-Path -LiteralPath $InputFile).Path
if ([IO.Path]::GetExtension($InputFile).ToLowerInvariant() -ne '.wav') {
    throw 'This regression gate currently requires a WAV premaster.'
}

if ([double]::IsNaN($PreviewStart)) {
    $SelectedName = [IO.Path]::GetFileName($InputFile)
    if ($SelectedName -match '(?i)^4-Lockdown Protocol\.wav$') {
        $PreviewStart = 145.0
        $SelectionPolicy = 'EXPLICIT_LOCKDOWN_145_175'
    }
    elseif ($SelectedName -match '(?i)^7-Cybernetic Grid.*\.wav$') {
        $PreviewStart = 285.0
        $SelectionPolicy = 'EXPLICIT_CYBERNETIC_285_315'
    }
    elseif ($SelectedName -match '(?i)HUSARIA.*Premaster.*\.wav$') {
        $PreviewStart = 290.0
        $SelectionPolicy = 'EXPLICIT_HUSARIA_290_310'
    }
    elseif ($SelectedName -match '(?i)Kwiat.*Premaster.*\.wav$') {
        $PreviewStart = 270.0
        $SelectionPolicy = 'EXPLICIT_KWIAT_270_290'
    }
    else {
        throw 'PreviewStart cannot be inferred for the explicit input. Re-run with -PreviewStart <seconds>.'
    }
}

Write-Host "SELECTED_REAL_AUDIO: $InputFile"
Write-Host "REAL_AUDIO_SELECTION_POLICY: $SelectionPolicy"
Write-Host "PREVIEW_WINDOW_START_SECONDS: $PreviewStart"

New-Item -ItemType Directory -Force -Path $RunDir, $ExtractDir, $EvidenceDir | Out-Null

$ApiHeaders = @{ 'User-Agent' = 'rqs-mastering-v2-local-real-audio-validator/1.0' }
$CommitInfo = Invoke-RestMethod -Headers $ApiHeaders -Uri "https://api.github.com/repos/$CandidateRepo/commits/$CandidateBranch"
$CandidateHead = [string]$CommitInfo.sha
if ($CandidateHead -notmatch '^[0-9a-f]{40}$') { throw 'Could not resolve candidate branch HEAD.' }
Write-Host "CANDIDATE_HEAD: $CandidateHead"

$ArchiveUrl = "https://github.com/$CandidateRepo/archive/$CandidateHead.zip"
Invoke-WebRequest -Headers $ApiHeaders -Uri $ArchiveUrl -OutFile $ArchivePath
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractDir -Force
$RepoDir = Get-ChildItem -LiteralPath $ExtractDir -Directory | Select-Object -First 1 -ExpandProperty FullName
if (-not $RepoDir -or -not (Test-Path (Join-Path $RepoDir 'server.js'))) {
    throw 'Downloaded candidate archive does not contain server.js.'
}

$coreCandidate = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $RepoDir 'src\controllers\core_dsp.py')
$coreCanonical = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $StandaloneRepo 'src\controllers\core_dsp.py')
if ($coreCandidate.Hash -ne $coreCanonical.Hash) {
    throw 'DSP_CANONICAL_CORE_HASH_PARITY: FAIL'
}
Write-Host 'DSP_CANONICAL_CORE_HASH_PARITY: PASS'
Write-Host "CORE_DSP_SHA256: $($coreCandidate.Hash)"

$v2Candidate = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $RepoDir 'src\controllers\mastering_v2.py')
$v2Canonical = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $StandaloneRepo 'src\controllers\mastering_v2.py')
if ($v2Candidate.Hash -ne $v2Canonical.Hash) {
    throw 'DSP_CANONICAL_V2_HASH_PARITY: FAIL'
}
Write-Host 'DSP_CANONICAL_V2_HASH_PARITY: PASS'
Write-Host "MASTERING_V2_SHA256: $($v2Candidate.Hash)"

Push-Location $RepoDir
try {
    & $Npm.Source ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
Write-Host 'LOCAL_REAL_AUDIO_CANDIDATE_INSTALL: PASS'

$TempBefore = @(Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter 'v2_output_*.wav' -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)

try {
    $env:RQS_MASTERING_V2_LOCAL_OUTPUT = '1'
    $env:RQS_MASTERING_V2_DIRECT_UPLOAD = '1'
    $env:RQS_PYTHON_BIN = $Python
    $env:PORT = [string]$Port
    $env:STRIPE_SECRET_KEY = 'sk_test_local_real_audio_placeholder'
    $env:STRIPE_WEBHOOK_SECRET = 'whsec_local_real_audio_placeholder'

    $ServerProcess = Start-Process -FilePath $Node.Source -ArgumentList 'server.js' `
        -WorkingDirectory $RepoDir -PassThru `
        -RedirectStandardOutput $ServerStdout -RedirectStandardError $ServerStderr

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if ($ServerProcess.HasExited) {
            $err = if (Test-Path $ServerStderr) { Get-Content -LiteralPath $ServerStderr -Raw } else { '' }
            throw "Candidate server exited early. STDERR: $err"
        }
        try {
            $health = Invoke-WebRequest -Uri "$BaseUrl/health" -SkipHttpErrorCheck
            if ([int]$health.StatusCode -eq 200) { $ready = $true; break }
        }
        catch {}
    }
    if (-not $ready) { throw 'Candidate server did not become healthy.' }
    Write-Host 'LOCAL_REAL_AUDIO_CANDIDATE_HEALTH: PASS'

    $PreviewForm = @{
        audio = Get-Item -LiteralPath $InputFile
        destination = 'streaming'
        platform = 'soundcloud'
        atmosphere = 'clear_sky'
        intensity_percent = '50'
        requested_lufs = '-14'
        soundcloud_mode = 'standard'
        preview = 'true'
        preview_start_seconds = [string]$PreviewStart
    }
    Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" -Form $PreviewForm -OutFile $PreviewHttp
    if (-not (Test-Path $PreviewHttp) -or (Get-Item $PreviewHttp).Length -le 44) {
        throw 'HTTP Preview output is missing or invalid.'
    }
    Write-Host 'LOCAL_REAL_AUDIO_HTTP_PREVIEW_RENDER: PASS'

    Invoke-CanonicalRender -PythonExe $Python -InputPath $InputFile -OutputPath $PreviewCanonical -Preview
    Write-Host 'LOCAL_REAL_AUDIO_CANONICAL_PREVIEW_RENDER: PASS'

    $FullForm = @{
        audio = Get-Item -LiteralPath $InputFile
        destination = 'streaming'
        platform = 'soundcloud'
        atmosphere = 'clear_sky'
        intensity_percent = '50'
        requested_lufs = '-14'
        soundcloud_mode = 'standard'
        preview = 'false'
    }
    $FullResponse = Invoke-WebRequest -Method POST -Uri "$BaseUrl/mastering/v2/process" -Form $FullForm -SkipHttpErrorCheck
    if ([int]$FullResponse.StatusCode -ne 200) {
        throw "HTTP Full Master failed: HTTP $($FullResponse.StatusCode) $($FullResponse.Content)"
    }
    $FullResponse.Content | Set-Content -LiteralPath $FullResponsePath -Encoding UTF8
    $FullJson = $FullResponse.Content | ConvertFrom-Json
    if (-not $FullJson.success -or $FullJson.outputMode -ne 'local' -or -not $FullJson.downloadUrl) {
        throw 'HTTP Full Master response does not satisfy local-output contract.'
    }
    Invoke-WebRequest -Uri ([string]$FullJson.downloadUrl) -OutFile $FullHttp
    if (-not (Test-Path $FullHttp) -or (Get-Item $FullHttp).Length -le 44) {
        throw 'HTTP Full Master download is missing or invalid.'
    }
    Write-Host 'LOCAL_REAL_AUDIO_HTTP_FULL_RENDER_DOWNLOAD: PASS'

    Invoke-CanonicalRender -PythonExe $Python -InputPath $InputFile -OutputPath $FullCanonical
    Write-Host 'LOCAL_REAL_AUDIO_CANONICAL_FULL_RENDER: PASS'

    @'
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

source_path, preview_http_path, preview_ref_path, full_http_path, full_ref_path = map(Path, sys.argv[1:6])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def info(path: Path):
    i = sf.info(str(path))
    return {
        'samplerate': i.samplerate,
        'channels': i.channels,
        'frames': i.frames,
        'duration': i.frames / i.samplerate,
        'format': i.format,
        'subtype': i.subtype,
    }


def peak_dbfs(path: Path) -> float:
    peak = 0.0
    with sf.SoundFile(str(path)) as f:
        while True:
            x = f.read(65536, dtype='float64', always_2d=True)
            if len(x) == 0:
                break
            if not np.isfinite(x).all():
                raise RuntimeError(f'Non-finite audio samples: {path}')
            peak = max(peak, float(np.max(np.abs(x))))
    return -math.inf if peak <= 0.0 else 20.0 * math.log10(peak)


def compare_samples(a: Path, b: Path):
    ia, ib = sf.info(str(a)), sf.info(str(b))
    meta_equal = (ia.samplerate, ia.channels, ia.frames) == (ib.samplerate, ib.channels, ib.frames)
    max_abs = 0.0
    exact = True
    if not meta_equal:
        return False, False, float('inf')
    with sf.SoundFile(str(a)) as fa, sf.SoundFile(str(b)) as fb:
        while True:
            xa = fa.read(65536, dtype='float64', always_2d=True)
            xb = fb.read(65536, dtype='float64', always_2d=True)
            if len(xa) == 0 and len(xb) == 0:
                break
            if xa.shape != xb.shape:
                return False, False, float('inf')
            if not np.array_equal(xa, xb):
                exact = False
                max_abs = max(max_abs, float(np.max(np.abs(xa - xb))))
    return True, exact, max_abs

src = info(source_path)
ph = info(preview_http_path)
pr = info(preview_ref_path)
fh = info(full_http_path)
fr = info(full_ref_path)

preview_meta, preview_exact, preview_delta = compare_samples(preview_http_path, preview_ref_path)
full_meta, full_exact, full_delta = compare_samples(full_http_path, full_ref_path)

preview_expected_frames = round(ph['samplerate'] * 15.0)
checks = {
    'preview_http_vs_canonical_meta': preview_meta,
    'preview_http_vs_canonical_samples': preview_exact or preview_delta <= 1e-7,
    'preview_exact_15_seconds': ph['frames'] == preview_expected_frames,
    'preview_sr_matches_source': ph['samplerate'] == src['samplerate'],
    'preview_channels_match_source': ph['channels'] == src['channels'],
    'full_http_vs_canonical_meta': full_meta,
    'full_http_vs_canonical_samples': full_exact or full_delta <= 1e-7,
    'full_sr_matches_source': fh['samplerate'] == src['samplerate'],
    'full_channels_match_source': fh['channels'] == src['channels'],
    'full_length_matches_source': fh['frames'] == src['frames'],
}

report = {
    'status': 'PASS' if all(checks.values()) else 'FAIL',
    'checks': checks,
    'source': src,
    'preview_http': {**ph, 'sha256': sha256(preview_http_path), 'peak_dbfs': peak_dbfs(preview_http_path)},
    'preview_canonical': {**pr, 'sha256': sha256(preview_ref_path), 'peak_dbfs': peak_dbfs(preview_ref_path)},
    'full_http': {**fh, 'sha256': sha256(full_http_path), 'peak_dbfs': peak_dbfs(full_http_path)},
    'full_canonical': {**fr, 'sha256': sha256(full_ref_path), 'peak_dbfs': peak_dbfs(full_ref_path)},
    'preview_max_abs_sample_delta': preview_delta,
    'full_max_abs_sample_delta': full_delta,
}
print(json.dumps(report, indent=2))
sys.exit(0 if report['status'] == 'PASS' else 2)
'@ | Set-Content -LiteralPath $CompareScript -Encoding UTF8

    $CompareText = & $Python $CompareScript $InputFile $PreviewHttp $PreviewCanonical $FullHttp $FullCanonical
    $CompareExit = $LASTEXITCODE
    $CompareText | Set-Content -LiteralPath $CompareReport -Encoding UTF8
    if ($CompareExit -ne 0) {
        Write-Host $CompareText
        throw 'LOCAL_REAL_AUDIO_SAMPLE_PARITY: FAIL'
    }
    $Compare = $CompareText | ConvertFrom-Json
    if ($Compare.status -ne 'PASS') { throw 'LOCAL_REAL_AUDIO_SAMPLE_PARITY: FAIL' }

    Write-Host 'LOCAL_REAL_AUDIO_PREVIEW_15S_EXACT: PASS'
    Write-Host 'LOCAL_REAL_AUDIO_PREVIEW_HTTP_CANONICAL_PARITY: PASS'
    Write-Host 'LOCAL_REAL_AUDIO_FULL_HTTP_CANONICAL_PARITY: PASS'
    Write-Host 'LOCAL_REAL_AUDIO_FULL_DURATION_PRESERVED: PASS'

    $Manifest = @(
        'MASTERING_V2_LOCAL_REAL_AUDIO_INTEGRATION: PASS',
        "CANDIDATE_HEAD: $CandidateHead",
        "CANONICAL_STANDALONE_HEAD: $StandaloneHead",
        "INPUT: $InputFile",
        "PREVIEW_START_SECONDS: $PreviewStart",
        "REAL_AUDIO_SELECTION_POLICY: $SelectionPolicy",
        'DESTINATION: streaming',
        'PLATFORM: soundcloud',
        'ATMOSPHERE: clear_sky',
        'INTENSITY_PERCENT: 50',
        'REQUESTED_LUFS: -14',
        'SOUNDCLOUD_MODE: standard',
        "CORE_DSP_SHA256: $($coreCandidate.Hash)",
        "MASTERING_V2_SHA256: $($v2Candidate.Hash)",
        "PREVIEW_HTTP_SHA256: $($Compare.preview_http.sha256)",
        "PREVIEW_CANONICAL_SHA256: $($Compare.preview_canonical.sha256)",
        "FULL_HTTP_SHA256: $($Compare.full_http.sha256)",
        "FULL_CANONICAL_SHA256: $($Compare.full_canonical.sha256)",
        "PREVIEW_MAX_ABS_SAMPLE_DELTA: $($Compare.preview_max_abs_sample_delta)",
        "FULL_MAX_ABS_SAMPLE_DELTA: $($Compare.full_max_abs_sample_delta)",
        'AUTH_QUOTA_GATE: NOT_REPEATED / ALREADY_VALIDATED_ON_STAGING',
        'S3_REQUESTS_PERFORMED: NONE',
        'SUPABASE_REQUESTS_PERFORMED: NONE',
        'PRODUCTION_REQUESTS_PERFORMED: NONE',
        'CANONICAL_GIT_MUTATION: NONE'
    )
    $Manifest | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

    Compress-Archive -LiteralPath $ManifestPath, $CompareReport, $ServerStdout, $ServerStderr, $FullResponsePath -DestinationPath $EvidenceZip -Force
    $EvidenceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $EvidenceZip).Hash

    Write-Host 'MASTERING_V2_LOCAL_REAL_AUDIO_INTEGRATION: PASS'
    Write-Host "REAL_AUDIO_OUTPUT_DIR: $RunDir"
    Write-Host "REAL_AUDIO_EVIDENCE_ZIP: $EvidenceZip"
    Write-Host "REAL_AUDIO_EVIDENCE_ZIP_SHA256: $EvidenceHash"
    Write-Host "HTTP_PREVIEW_FOR_LISTENING: $PreviewHttp"
    Write-Host "HTTP_FULL_MASTER_FOR_LISTENING: $FullHttp"
    Write-Host 'S3_REQUESTS_PERFORMED: NONE'
    Write-Host 'SUPABASE_REQUESTS_PERFORMED: NONE'
    Write-Host 'PRODUCTION_REQUESTS_PERFORMED: NONE'
    Write-Host 'CANONICAL_GIT_MUTATION: NONE'
}
finally {
    if ($null -ne $ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        try { $ServerProcess.WaitForExit(5000) | Out-Null } catch {}
    }

    foreach ($name in @(
        'RQS_MASTERING_V2_LOCAL_OUTPUT',
        'RQS_MASTERING_V2_DIRECT_UPLOAD',
        'RQS_PYTHON_BIN',
        'PORT',
        'STRIPE_SECRET_KEY',
        'STRIPE_WEBHOOK_SECRET'
    )) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }

    $TempRoot = [IO.Path]::GetTempPath()
    $TempAfter = @(Get-ChildItem -LiteralPath $TempRoot -Filter 'v2_output_*.wav' -File -ErrorAction SilentlyContinue)
    foreach ($f in $TempAfter) {
        if ($f.FullName -notin $TempBefore -and $f.LastWriteTime -ge $RunStarted) {
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}
