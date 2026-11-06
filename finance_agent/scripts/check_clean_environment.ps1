param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cleanPath = Join-Path ([System.IO.Path]::GetTempPath()) ("finance-clean-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $cleanPath | Out-Null
foreach ($folder in @("app", "tests", "examples")) {
    $destination = Join-Path $cleanPath $folder
    New-Item -ItemType Directory -Path $destination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $projectPath $folder) -Filter "*.py" -File |
        Copy-Item -Destination $destination
}
Copy-Item -LiteralPath (Join-Path $projectPath "tests\fixtures") -Destination (Join-Path $cleanPath "tests\fixtures") -Recurse
Copy-Item -LiteralPath (Join-Path $projectPath "main.py") -Destination $cleanPath
Write-Output "Clean test directory: $cleanPath"
Push-Location $cleanPath
try {
    & $Python -m unittest discover -s tests -v
    $testExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
# 保留临时副本供失败诊断，不删除用户资料。
exit $testExitCode
