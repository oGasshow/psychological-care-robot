param([ValidateSet('Normal','Demo')][string]$Mode='Normal',[switch]$NoBrowser,[switch]$Stop)
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$pythonTool=Join-Path $projectRoot '.venv/Scripts/python.exe'
$runtimeBase=[IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime'))
$env:PYTHONUTF8='1'

function Read-Access([string]$Directory) {
    $resolved=[IO.Path]::GetFullPath($Directory)
    if(-not $resolved.StartsWith($runtimeBase+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Runtime outside project.'}
    return Get-Content -LiteralPath (Join-Path $resolved 'access.json') -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Wait-NormalPage([string]$BaseAddress) {
    $deadline=[DateTime]::UtcNow.AddSeconds(20)
    do {
        try {
            $mode=Invoke-RestMethod -Uri ($BaseAddress+'/api/robot-voice/mode') -TimeoutSec 2
            if($mode.mode -eq 'normal'){return}
        } catch {
            # The frontend can still be loading immediately after launch.
        }
        Start-Sleep -Milliseconds 400
    } while([DateTime]::UtcNow -lt $deadline)
    throw 'Normal mode did not respond on the expected web address. Inspect the frontend and backend runtime logs.'
}

try {
    Set-Location -LiteralPath $projectRoot
    if(-not (Test-Path -LiteralPath $pythonTool)){throw 'Run Setup-Project.ps1 first.'}
    if($Mode -eq 'Demo') {
        $action=if($Stop){'stop'}else{'start'}
        & $pythonTool -X utf8 (Join-Path $projectRoot 'backend/tools/collection_demo.py') $action
        if($LASTEXITCODE -ne 0){throw 'Collection demo operation failed; inspect runtime/collection_demo logs.'}
        if($Stop){exit 0}
        $access=Read-Access (Join-Path $runtimeBase 'collection_demo')
        $address='http://127.0.0.1:'+$access.frontend_port+'/login'
        Write-Host 'QUICK COLLECTION DEMO - isolated data, 3 custom items' -ForegroundColor Yellow
        if(-not $NoBrowser) {
            Write-Host ('Local demo login: '+$access.users[0].username)
            Write-Host ('Local demo password: '+$access.users[0].password)
        }
        Write-Host 'Credentials are stored locally in runtime/collection_demo/access.json. Do not publish.'
    } else {
        $runtime=Join-Path $runtimeBase 'direct_start'
        $pointer=Join-Path $runtimeBase 'active_runtime.txt'
        if(Test-Path -LiteralPath $pointer){
            $runtime=[IO.File]::ReadAllText($pointer).Trim()
            if(-not [IO.Path]::IsPathRooted($runtime)){$runtime=Join-Path $projectRoot $runtime}
        }
        if(Test-Path -LiteralPath (Join-Path $runtime 'access.json')) {
            $access=Read-Access $runtime
            if($access.collection_demo){throw 'Normal runtime pointer must not select the collection demo.'}
        }
        if($Stop){& (Join-Path $projectRoot 'Run-Project.ps1') -Stop -NoBrowser;exit $LASTEXITCODE}
        Write-Host 'Starting normal mode from this project folder. Existing recordings will be kept.'
        & (Join-Path $projectRoot 'Run-Project.ps1') -NoBrowser -NoCredentials
        if($LASTEXITCODE -ne 0){throw 'Normal mode startup failed.'}
        $access=Read-Access $runtime
        $baseAddress='http://127.0.0.1:'+$access.frontend_port
        Wait-NormalPage $baseAddress
        if((Test-Path -LiteralPath (Join-Path $projectRoot '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
            $revision=git -C $projectRoot rev-parse --short --verify HEAD 2>$null
            if($LASTEXITCODE -eq 0){Write-Host ('Local Git commit: '+$revision)}
        }
        $address=$baseAddress+'/robot-care/voice'
        Write-Host 'NORMAL MODE - complete scales and cross-call follow-up' -ForegroundColor Green
        if(-not $NoBrowser -and $access.deployment_role -ne 'edge') {
            Write-Host ('Local normal-mode login: '+$access.users[0].username)
            Write-Host ('Local normal-mode password: '+$access.users[0].password)
            Write-Host 'Use these credentials only for this normal-mode address. Do not publish.'
        }
    }
    Write-Host ('Entry: '+$address)
    if(-not $NoBrowser){Start-Process $address}
} catch {
    Write-Host ('Mode entry failed: '+$_.Exception.Message) -ForegroundColor Red
    exit 1
}
