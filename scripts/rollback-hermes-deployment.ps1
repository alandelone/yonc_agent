[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProjectRoot = "",
    [Parameter(Mandatory = $true)][string]$ManifestPath
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$manifest = Get-Content -LiteralPath (Resolve-Path -LiteralPath $ManifestPath) -Raw | ConvertFrom-Json
$pidFile = Join-Path $root "data\runtime\yonc.pid"
if (Test-Path -LiteralPath $pidFile) {
    $pidValue = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($process -and $PSCmdlet.ShouldProcess("Yonc PID $pidValue", "Stop managed process")) {
        Stop-Process -Id $pidValue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
foreach ($entry in $manifest.files) {
    if ($entry.backup -and (Test-Path -LiteralPath $entry.backup)) {
        if ($PSCmdlet.ShouldProcess($entry.path, "Restore managed configuration")) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $entry.path) | Out-Null
            Copy-Item -LiteralPath $entry.backup -Destination $entry.path -Force
        }
    } elseif ($entry.created -and (Test-Path -LiteralPath $entry.path)) {
        if ($PSCmdlet.ShouldProcess($entry.path, "Remove deployment-created file")) {
            Remove-Item -LiteralPath $entry.path -Force
        }
    }
}
Write-Output "Managed profile/configuration rollback complete. The project database was not overwritten or deleted."
