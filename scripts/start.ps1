param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$localEnv = Join-Path $repository '.env'
if (Test-Path -LiteralPath $localEnv) {
    foreach ($line in Get-Content -LiteralPath $localEnv) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2].Trim().Trim('"').Trim("'"),'Process')
        }
    }
}
Push-Location (Join-Path $repository 'apps/api')
try {
    python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
