[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)][string]$UumaRoot,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [int]$Port = 8765,
    [string]$ProfilesRoot = (Join-Path $env:LOCALAPPDATA "hermes\profiles")
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$uuma = (Resolve-Path -LiteralPath $UumaRoot).Path
$database = (Resolve-Path -LiteralPath $DatabasePath).Path
$profile = Join-Path $ProfilesRoot "yonc"
$failures = [Collections.Generic.List[string]]::new()

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/health" -TimeoutSec 8
    if (-not $health.ok) { $failures.Add("Yonc health endpoint is not OK.") }
    if ([IO.Path]::GetFullPath($health.database_path) -ne [IO.Path]::GetFullPath($database)) {
        $failures.Add("Yonc service is using a different database: $($health.database_path)")
    }
} catch { $failures.Add("Yonc API is unavailable on port ${Port}: $($_.Exception.Message)") }

$required = @(
    (Join-Path $profile "SOUL.md"),
    (Join-Path $profile "config.yaml"),
    (Join-Path $profile "skills\yonc-project-management\SKILL.md"),
    (Join-Path $profile "plugins\uuma_control_guard\plugin.yaml"),
    (Join-Path $profile "plugins\uuma_audit\plugin.yaml"),
    (Join-Path $root "graph_app\mcp_project.py"),
    (Join-Path $uuma "src\uuma\mcp_worker.py")
)
foreach ($path in $required) { if (-not (Test-Path -LiteralPath $path)) { $failures.Add("Missing $path") } }

$configPath = Join-Path $profile "config.yaml"
if (Test-Path -LiteralPath $configPath) {
    $configText = Get-Content -LiteralPath $configPath -Raw
    foreach ($needle in @("yonc-project", "uuma-worker", "uuma_control_guard")) {
        if (-not $configText.Contains($needle)) { $failures.Add("Profile config is missing $needle.") }
    }
    foreach ($forbidden in @("uuma-control", "computer_use", "terminal")) {
        if ($configText.Contains($forbidden)) { $failures.Add("Profile config contains forbidden capability $forbidden.") }
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    exit 1
}
Write-Output "Yonc Hermes deployment verified. Database identity: $($health.database_identity); graph version: $($health.graph_version)."
