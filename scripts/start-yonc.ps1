[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonExe = "python",
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$database = (Resolve-Path -LiteralPath $DatabasePath).Path
$runtime = Join-Path $root "data\runtime"
$logs = Join-Path $runtime "logs"
$pidFile = Join-Path $runtime "yonc.pid"
$tokenFile = Join-Path $runtime "hermes-agent-token"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if (Test-Path -LiteralPath $pidFile) {
    $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/health" -TimeoutSec 5
            if ([IO.Path]::GetFullPath($health.database_path) -eq [IO.Path]::GetFullPath($database)) {
                Write-Output "Yonc is already running (PID $oldPid) with the requested database."
                exit 0
            }
        } catch {}
        throw "Managed Yonc PID $oldPid is running but does not report the requested database."
    }
}

try {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    if ($listener) { throw "Port $Port is already in use by PID $($listener[0].OwningProcess)." }
} catch [Microsoft.PowerShell.Cmdletization.Cim.CimJobException] {}

$previousDb = $env:YONC_GRAPH_DB
$previousToken = $env:YONC_AGENT_COMMIT_TOKEN
try {
    $env:YONC_GRAPH_DB = $database
    if (Test-Path -LiteralPath $tokenFile) {
        $env:YONC_AGENT_COMMIT_TOKEN = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
    }
    $process = Start-Process -FilePath $PythonExe `
        -ArgumentList @("-m", "graph_app", "serve", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logs "yonc.out.log") `
        -RedirectStandardError (Join-Path $logs "yonc.err.log")
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii
} finally {
    $env:YONC_GRAPH_DB = $previousDb
    $env:YONC_AGENT_COMMIT_TOKEN = $previousToken
}

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/health" -TimeoutSec 2
        if ([IO.Path]::GetFullPath($health.database_path) -ne [IO.Path]::GetFullPath($database)) {
            throw "Yonc started with a different database: $($health.database_path)"
        }
        Write-Output "Yonc ready at http://127.0.0.1:$Port (PID $($process.Id), DB $($health.database_identity))."
        exit 0
    } catch {
        if ($process.HasExited) { throw "Yonc exited during startup. See $logs\yonc.err.log" }
    }
}
throw "Yonc did not become healthy. See $logs\yonc.err.log"
