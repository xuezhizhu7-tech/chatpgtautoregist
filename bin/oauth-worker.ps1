param(
    [int]$Worker = 1,
    [int]$Count = 0,
    [string]$AccountsFile = ""
)

$basePort = 9336
$port = $basePort + $Worker - 1
$root = Split-Path -Parent $PSScriptRoot

$env:CDP_PORT = "$port"
$env:CHROME_PROFILE_DIR = "/tmp/chrome-reg-$port"

if ($AccountsFile) {
    $env:ACCOUNTS_LOG = $AccountsFile
} else {
    $env:ACCOUNTS_LOG = Join-Path $root "accounts_worker_$Worker.jsonl"
}

Write-Host "Worker $Worker -> CDP_PORT=$env:CDP_PORT"
Write-Host "Worker $Worker -> CHROME_PROFILE_DIR=$env:CHROME_PROFILE_DIR"
Write-Host "Worker $Worker -> ACCOUNTS_LOG=$env:ACCOUNTS_LOG"

$argsList = @("--file", $env:ACCOUNTS_LOG)
if ($Count -gt 0) {
    $argsList += @("--count", "$Count")
}

python (Join-Path $root "step_05_import\oauth_import.py") @argsList
