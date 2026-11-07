param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$pythonPath = (Get-Command $Python -CommandType Application).Source
$repoPath = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$cleanPath = Join-Path ([System.IO.Path]::GetTempPath()) ("finance-clean-" + [guid]::NewGuid().ToString("N"))
$trackedFiles = git -C $repoPath -c core.quotepath=false ls-files
if ($LASTEXITCODE -ne 0 -or -not $trackedFiles) {
    throw "Run this check from a Git checkout with tracked source files."
}
New-Item -ItemType Directory -Path $cleanPath | Out-Null
foreach ($file in $trackedFiles) {
    $source = Join-Path $repoPath $file
    $destination = Join-Path $cleanPath $file
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
}
Write-Output "Clean source directory: $cleanPath"
# Ignore developer-specific imports and fixture overrides. Keep the copy for diagnosis.
$priorPythonPath = $env:PYTHONPATH
$priorFixture = $env:FINANCE_TEST_EXCEL
$priorUtf8 = $env:PYTHONUTF8
$env:PYTHONPATH = $null
$env:FINANCE_TEST_EXCEL = $null
$env:PYTHONUTF8 = "1"
Push-Location (Join-Path $cleanPath "finance_agent")
try {
    & $pythonPath -m unittest discover -s tests -q
    $testExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH = $priorPythonPath
    $env:FINANCE_TEST_EXCEL = $priorFixture
    $env:PYTHONUTF8 = $priorUtf8
}
exit $testExitCode
