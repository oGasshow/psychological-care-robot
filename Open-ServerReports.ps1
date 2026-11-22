$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$python=Join-Path $root '.venv/Scripts/python.exe'
& $python (Join-Path $root 'backend/tools/start_tunnels.py') --config (Join-Path $root 'runtime/edge-central/connection.json') --reports
if($LASTEXITCODE -ne 0){throw 'Encrypted report connection could not start.'}
$address='http://127.0.0.1:53111/login'
Write-Host ('Administrator reports: '+$address)
$chrome=Join-Path $env:ProgramFiles 'Google/Chrome/Application/chrome.exe'
if(Test-Path -LiteralPath $chrome){Start-Process -FilePath $chrome -ArgumentList $address}else{Write-Host 'Open the address in Google Chrome.'}
