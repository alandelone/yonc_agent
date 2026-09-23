[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [Parameter(Mandatory = $true)][string]$UumaRoot,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [string]$PythonExe = "python",
    [string]$UumaPythonExe = "",
    [string]$HermesExe = (Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\hermes.exe"),
    [string]$UumaDataDir = (Join-Path $env:LOCALAPPDATA "UuMA"),
    [int]$Port = 8765,
    [string]$ProfilesRoot = (Join-Path $env:LOCALAPPDATA "hermes\profiles"),
    [switch]$SkipInstall,
    [switch]$SkipGatewayRestart
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$uuma = (Resolve-Path -LiteralPath $UumaRoot).Path
$database = (Resolve-Path -LiteralPath $DatabasePath).Path
$PythonExe = (Get-Command $PythonExe -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($UumaPythonExe)) {
    $UumaPythonExe = Join-Path $uuma ".venv\Scripts\python.exe"
}
$UumaPythonExe = (Resolve-Path -LiteralPath $UumaPythonExe -ErrorAction Stop).Path
$HermesExe = (Resolve-Path -LiteralPath $HermesExe -ErrorAction Stop).Path
$profile = Join-Path $ProfilesRoot "yonc"
$runtime = Join-Path $root "data\runtime"
$deployment = Join-Path $root ("data\deployments\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$backupRoot = Join-Path $deployment "backup"
New-Item -ItemType Directory -Force -Path $backupRoot, $runtime | Out-Null

foreach ($required in @(
    (Join-Path $uuma "scripts\configure-hermes-profile.py"),
    (Join-Path $uuma "profiles\yonc\SOUL.md"),
    (Join-Path $root "graph_app\mcp_project.py"),
    $database
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required path is missing: $required" }
}
& $PythonExe --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Python is unavailable: $PythonExe" }
& $UumaPythonExe --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "UuMA Python is unavailable: $UumaPythonExe" }
& $HermesExe --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Hermes is unavailable: $HermesExe" }

$manifestFiles = [Collections.Generic.List[object]]::new()
function Backup-ManagedFile([string]$Path, [string]$Name) {
    if (Test-Path -LiteralPath $Path) {
        $destination = Join-Path $backupRoot $Name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $Path -Destination $destination -Force
        $manifestFiles.Add([ordered]@{ path = $Path; backup = $destination; created = $false })
    } else {
        $manifestFiles.Add([ordered]@{ path = $Path; backup = $null; created = $true })
    }
}
function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = [Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in Get-Content -LiteralPath $Path) { $lines.Add([string]$line) }
    }
    $replacement = "$Key=$Value"
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([regex]::Escape($Key))=") { $lines[$index] = $replacement; $found = $true }
    }
    if (-not $found) { $lines.Add($replacement) }
    Set-Content -LiteralPath $Path -Value $lines -Encoding utf8
}

$dbBackup = Join-Path $backupRoot "project-graph.sqlite3"
Copy-Item -LiteralPath $database -Destination $dbBackup -Force

if (-not $SkipInstall) {
    & $PythonExe -m pip install -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    Push-Location (Join-Path $root "graph_app\frontend")
    try {
        & pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & pnpm build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally { Pop-Location }
}

$oldDb = $env:YONC_GRAPH_DB
try {
    $env:YONC_GRAPH_DB = $database
    Push-Location $root
    try {
        & $PythonExe -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Database migration failed; use the recorded backup for recovery." }
    } finally { Pop-Location }
} finally { $env:YONC_GRAPH_DB = $oldDb }

$tokenFile = Join-Path $runtime "hermes-agent-token"
if (-not (Test-Path -LiteralPath $tokenFile)) {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [IO.File]::WriteAllText($tokenFile, [Convert]::ToBase64String($bytes))
}
$token = (Get-Content -LiteralPath $tokenFile -Raw).Trim()

$oldPythonPath = $env:PYTHONPATH
$oldUumaData = $env:UUMA_DATA_DIR
$oldHermesExe = $env:UUMA_HERMES_EXE
try {
    $env:PYTHONPATH = Join-Path $uuma "src"
    $env:UUMA_DATA_DIR = $UumaDataDir
    $env:UUMA_HERMES_EXE = $HermesExe
    & $UumaPythonExe -m uuma.cli init
    if ($LASTEXITCODE -ne 0) { throw "UuMA identity/capability registration failed." }
} finally {
    $env:PYTHONPATH = $oldPythonPath
    $env:UUMA_DATA_DIR = $oldUumaData
    $env:UUMA_HERMES_EXE = $oldHermesExe
}

& $HermesExe profile show yonc *> $null
if ($LASTEXITCODE -ne 0) {
    & $HermesExe profile create --clone-from default --description "Governed Yonc project graph steward." yonc
    if ($LASTEXITCODE -ne 0) { throw "Failed to create Hermes yonc profile." }
}
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$configPath = Join-Path $profile "config.yaml"
$envPath = Join-Path $profile ".env"
foreach ($item in @(
    @{ Path = (Join-Path $profile "SOUL.md"); Name = "SOUL.md" },
    @{ Path = $configPath; Name = "config.yaml" },
    @{ Path = $envPath; Name = ".env" }
)) { Backup-ManagedFile -Path $item.Path -Name $item.Name }

Copy-Item -LiteralPath (Join-Path $uuma "profiles\yonc\SOUL.md") -Destination (Join-Path $profile "SOUL.md") -Force
$skillTarget = Join-Path $profile "skills\yonc-project-management"
New-Item -ItemType Directory -Force -Path $skillTarget | Out-Null
Copy-Item -LiteralPath (Join-Path $uuma "profiles\yonc\skills\yonc-project-management\SKILL.md") -Destination (Join-Path $skillTarget "SKILL.md") -Force
foreach ($pluginName in @("uuma_audit", "uuma_control_guard")) {
    $source = Join-Path $uuma "integrations\hermes\$pluginName"
    $target = Join-Path $profile "plugins\$pluginName"
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
}

if (-not (Test-Path -LiteralPath $configPath)) { throw "Hermes profile did not create $configPath" }
& $UumaPythonExe (Join-Path $uuma "scripts\configure-hermes-profile.py") `
    --config $configPath --role worker --agent-id yonc `
    --python-exe $UumaPythonExe --source-path (Join-Path $uuma "src") `
    --data-dir $UumaDataDir --gemini-allowed-roots $root `
    --yonc-root $root --yonc-python $PythonExe --yonc-api-url "http://127.0.0.1:$Port"
if ($LASTEXITCODE -ne 0) { throw "Failed to configure Hermes yonc profile." }
Set-DotEnvValue -Path $envPath -Key "UUMA_AGENT_ID" -Value "yonc"
Set-DotEnvValue -Path $envPath -Key "UUMA_DATA_DIR" -Value $UumaDataDir
Set-DotEnvValue -Path $envPath -Key "UUMA_TOKEN_FILE" -Value (Join-Path $UumaDataDir "tokens.json")
Set-DotEnvValue -Path $envPath -Key "UUMA_INGEST_URL" -Value "http://127.0.0.1:8766/ingest/hermes"
Set-DotEnvValue -Path $envPath -Key "YONC_API_URL" -Value "http://127.0.0.1:$Port"
Set-DotEnvValue -Path $envPath -Key "YONC_AGENT_COMMIT_TOKEN" -Value $token

$manifest = [ordered]@{
    schema_version = 1
    created_at = (Get-Date).ToString("o")
    yonc_root = $root
    uuma_root = $uuma
    database_path = $database
    database_backup = $dbBackup
    profile_home = $profile
    files = $manifestFiles
}
$manifestPath = Join-Path $deployment "manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8

& (Join-Path $root "scripts\start-yonc.ps1") -ProjectRoot $root -PythonExe $PythonExe -DatabasePath $database -Port $Port
if ($LASTEXITCODE -ne 0) { throw "Yonc service startup failed." }

if (-not $SkipGatewayRestart) {
    & $HermesExe gateway restart
    if ($LASTEXITCODE -ne 0) { throw "Hermes gateway restart failed. Configuration is installed; retry the restart, then rerun the check." }
}

& (Join-Path $root "scripts\check-hermes-deployment.ps1") -ProjectRoot $root -UumaRoot $uuma -DatabasePath $database -Port $Port -ProfilesRoot $ProfilesRoot
if ($LASTEXITCODE -ne 0) { throw "Deployment checks failed. Roll back with manifest $manifestPath" }
Write-Output "Yonc Hermes deployment complete. Manifest: $manifestPath"
