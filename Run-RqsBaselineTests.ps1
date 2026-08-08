[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepositoryPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = 'D:\RQS-Dev\venvs\rqs-daw-backend-mastering-py312\Scripts\python.exe'
$TempRoot = 'D:\RQS-Dev\temp'

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Nie znaleziono interpretera: $PythonPath"
}

New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:TMPDIR = $TempRoot

Push-Location -LiteralPath $RepositoryPath
try {
    & $PythonPath -m pytest -v -ra
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
