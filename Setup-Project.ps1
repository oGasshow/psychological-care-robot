param(
    [string]$UvExecutable = 'uv',
    [string]$PythonExecutable = '3.13.18',
    [string]$NodeExecutable = 'node',
    [string]$NpmExecutable = 'npm.cmd',
    [string]$Registry = 'https://registry.npmjs.org',
    [string]$UvCacheDirectory = '',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
function Resolve-ProjectTool([string]$Value, [string]$Label) {
    $command = Get-Command $Value -ErrorAction SilentlyContinue
    if (-not $command) { throw "Missing $Label executable: $Value. Install the prerequisite or pass its explicit path." }
    return $command.Source
}
function Lock-Hashes {
    return @{
        frontend = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'frontend/package-lock.json') -Algorithm SHA256).Hash
        backend = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'backend/uv.lock') -Algorithm SHA256).Hash
    }
}
$uvTool = Resolve-ProjectTool $UvExecutable 'uv'
$nodeTool = Resolve-ProjectTool $NodeExecutable 'Node.js'
$npmTool = Resolve-ProjectTool $NpmExecutable 'npm'
$nodeVersion = (& $nodeTool --version).Trim()
if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion.TrimStart('v') -lt [version]'20.9.0') {
    throw 'Node.js 20.9 or newer is required. This release was verified with Node 22.14.0.'
}
$uvVersion = (& $uvTool --version).Trim()
$npmVersion = (& $npmTool --version).Trim()
$venvRoot = Join-Path $projectRoot '.venv'
$pythonTool = Join-Path $venvRoot 'Scripts/python.exe'
$receiptPath = Join-Path $projectRoot 'runtime/setup_receipt.json'
$before = Lock-Hashes
$record = [ordered]@{
    started_at = [DateTimeOffset]::UtcNow.ToString('o')
    project_root = $projectRoot
    check_only = [bool]$CheckOnly
    before = @{ venv_exists = (Test-Path -LiteralPath $venvRoot); node_modules_exists = (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/node_modules')); next_exists = (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/.next')) }
    tools = @{ uv = $uvTool; uv_version = $uvVersion; node = $nodeTool; node_version = $nodeVersion; npm = $npmTool; npm_version = $npmVersion }
    registry = $Registry
    lock_before = $before
}
$savedEnvironment = @{}
foreach ($name in @('UV_PROJECT_ENVIRONMENT','UV_CACHE_DIR','UV_PYTHON_INSTALL_DIR','UV_PYTHON_BIN_DIR','NODE_ENV','PATH')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PATH = (Split-Path -Parent $nodeTool) + [IO.Path]::PathSeparator + $env:PATH
    $env:UV_PROJECT_ENVIRONMENT = $venvRoot
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.tools/bin'
    $env:UV_CACHE_DIR = if ($UvCacheDirectory) { [IO.Path]::GetFullPath($UvCacheDirectory) } else { Join-Path $projectRoot '.uv-cache' }
    $env:NODE_ENV = ''
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'runtime') -Force | Out-Null
    if (-not $CheckOnly) {
        & $uvTool sync --project (Join-Path $projectRoot 'backend') --locked --group dev --python $PythonExecutable
        if ($LASTEXITCODE -ne 0) { throw 'Locked backend dependency sync failed; the lock file was not regenerated.' }
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            & $npmTool ci --include=dev "--registry=$Registry"
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed; inspect the installation log before continuing.' }
        } finally { Pop-Location }
    }
    if (-not (Test-Path -LiteralPath $pythonTool)) { throw 'Project venv is missing. Run setup without -CheckOnly first.' }
    $environmentJson = & $pythonTool -c 'import sys,sqlite3,json; print(json.dumps({"executable":sys.executable,"version":sys.version,"sqlite_version":sqlite3.sqlite_version}))'
    if ($LASTEXITCODE -ne 0) { throw 'Project interpreter check failed.' }
    $record.python = $environmentJson | ConvertFrom-Json
    & $uvTool pip check --python $pythonTool
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency consistency check failed.' }
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        & $npmTool ls --depth=0
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency/peer consistency check failed.' }
    } finally { Pop-Location }
    $after = Lock-Hashes
    if ($before.frontend -ne $after.frontend -or $before.backend -ne $after.backend) { throw 'Installation changed a lock file; stop and investigate.' }
    $record.lock_after = $after
    $record.status = 'passed'
    $record.finished_at = [DateTimeOffset]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Output "Project environment ready. Receipt: $receiptPath"
} finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
}
