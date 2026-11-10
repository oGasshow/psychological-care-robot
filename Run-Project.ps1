param([switch]$ApiOnly, [switch]$Stop, [switch]$NoBrowser, [switch]$Clean)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot 'runtime/direct_start'
$activePointer = Join-Path $projectRoot 'runtime/active_runtime.txt'
if (Test-Path -LiteralPath $activePointer) {
    $candidateRoot = [IO.Path]::GetFullPath([IO.File]::ReadAllText($activePointer).Trim())
    $allowedRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime')) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidateRoot.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid runtime pointer.' }
    $runtimeRoot = $candidateRoot
}
$pythonTool = Join-Path $projectRoot '.venv/Scripts/python.exe'
$demoTool = Join-Path $projectRoot 'backend/tools/demo_care.py'
$env:PYTHONUTF8 = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'

function Invoke-Demo([string]$Action, [switch]$WithoutFrontend) {
    $demoArguments = @($demoTool, $Action, '--runtime', $runtimeRoot)
    if ($WithoutFrontend) { $demoArguments += '--no-frontend' }
    & $pythonTool @demoArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Local service operation failed: $Action. Logs: $runtimeRoot"
    }
}

try {
    Set-Location -LiteralPath $projectRoot
    if (-not (Test-Path -LiteralPath $pythonTool)) {
        throw 'Project Python is missing. Run Setup-Project.ps1 first.'
    }
    if ($Stop) {
        if (Test-Path -LiteralPath (Join-Path $runtimeRoot 'access.json')) { Invoke-Demo 'stop' }
        Write-Host 'Services stopped.' -ForegroundColor Green
        exit 0
    }
    if (-not $ApiOnly) {
        if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is missing from PATH.' }
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/node_modules/next/dist/bin/next'))) {
            throw 'Frontend dependencies are missing. Run Setup-Project.ps1 first.'
        }
    }
    if ($Clean) {
        if (Test-Path -LiteralPath (Join-Path $runtimeRoot 'pids.json')) { Invoke-Demo 'stop' }
        $runtimeRoot = Join-Path $projectRoot ('runtime/presentation_' + [DateTime]::Now.ToString('yyyyMMdd_HHmmss_fff'))
        & $pythonTool $demoTool prepare --runtime $runtimeRoot --empty
        if ($LASTEXITCODE -ne 0) { throw 'Clean presentation preparation failed.' }
        [IO.File]::WriteAllText($activePointer, $runtimeRoot)
    }
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot 'access.json'))) {
        Invoke-Demo 'prepare'
    }
    if (Test-Path -LiteralPath (Join-Path $runtimeRoot 'pids.json')) { Invoke-Demo 'stop' }
    # Invalidate the existing build when application sources change. The demo
    # runner performs the actual build with its selected backend address.
    if (-not $ApiOnly) {
        $trackedSources = @('frontend/src','frontend/package.json','frontend/package-lock.json','frontend/next.config.ts','frontend/tsconfig.json')
        $sourceFiles = foreach ($relativePath in $trackedSources) {
            $candidate = Join-Path $projectRoot $relativePath
            if (Test-Path -LiteralPath $candidate -PathType Container) {
                Get-ChildItem -LiteralPath $candidate -Recurse -File
            } else { Get-Item -LiteralPath $candidate }
        }
        $sourceFingerprint = (($sourceFiles | Sort-Object FullName | ForEach-Object {
            $hasher = [Security.Cryptography.SHA256]::Create()
            try { $digest = [BitConverter]::ToString($hasher.ComputeHash([IO.File]::ReadAllBytes($_.FullName))).Replace('-', '') }
            finally { $hasher.Dispose() }
            $_.FullName.Substring($projectRoot.Length) + ':' + $digest
        }) -join "`n")
        $fingerprintPath = Join-Path $runtimeRoot 'frontend_sources.txt'
        $previous = if (Test-Path -LiteralPath $fingerprintPath) { [IO.File]::ReadAllText($fingerprintPath) } else { '' }
        if ($previous -ne $sourceFingerprint) {
            $manifest = Join-Path $projectRoot 'frontend/.next/routes-manifest.json'
            if (Test-Path -LiteralPath $manifest) { Remove-Item -LiteralPath $manifest }
            Write-Host 'Building current frontend sources. Please wait...'
        }
    }
    Invoke-Demo 'start' -WithoutFrontend:$ApiOnly
    if (-not $ApiOnly) { [IO.File]::WriteAllText($fingerprintPath, $sourceFingerprint) }
    $access = Get-Content -LiteralPath (Join-Path $runtimeRoot 'access.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $apiAddress = 'http://127.0.0.1:' + $access.backend_port
    $webAddress = 'http://127.0.0.1:' + $access.frontend_port + '/robot-care'
    if ($Clean) { $webAddress = 'http://127.0.0.1:' + $access.frontend_port + '/login' }
    Write-Host ''
    Write-Host ('API docs: ' + $apiAddress + '/docs') -ForegroundColor Green
    if (-not $ApiOnly) { Write-Host ('Web:      ' + $webAddress) -ForegroundColor Green }
    Write-Host 'Local fictional demo account (do not publish these credentials):'
    Write-Host ('Username: ' + $access.users[0].username)
    Write-Host ('Password: ' + $access.users[0].password)
    Write-Host ('Private runtime and logs: ' + $runtimeRoot)
    Write-Host 'Use Stop-Project.cmd to stop these services. Closing this window keeps them running.'
    if (-not $NoBrowser) {
        $openAddress = if ($ApiOnly) { $apiAddress + '/docs' } else { $webAddress }
        Start-Process $openAddress
    }
} catch {
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('Inspect logs in: ' + $runtimeRoot)
    exit 1
}
