param([switch]$NoBrowser,[ValidateRange(1024,65535)][int]$LocalPort=53111)
$ErrorActionPreference='Stop'
$private=Join-Path $PSScriptRoot 'private'
$key=Join-Path $private 'reports_ed25519'
$known=Join-Path $private 'known_hosts'
$config=Join-Path $private 'ssh-config'
$serverHost=(Get-Content -LiteralPath (Join-Path $private 'connection.json') -Raw | ConvertFrom-Json).host
if([Uri]::CheckHostName($serverHost) -eq [UriHostNameType]::Unknown){throw 'Invalid server hostname in private connection.json.'}
$address='http://127.0.0.1:'+$LocalPort
if(-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)){throw 'Windows OpenSSH Client is required.'}
if(-not (Test-Path -LiteralPath $key)){throw 'Private report connection key is missing.'}
$account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $key /inheritance:r /grant:r ($account+':(F)') 'SYSTEM:(F)' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not protect the connection key.'}
$keyPath=$key.Replace([char]92,[char]47)
$knownPath=$known.Replace([char]92,[char]47)
$sshConfig=@"
Host robot-care-reports
    HostName $serverHost
    User robotreports
    IdentityFile "$keyPath"
    UserKnownHostsFile "$knownPath"
    StrictHostKeyChecking yes
    BatchMode yes
    ExitOnForwardFailure yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
    LocalForward 127.0.0.1:$LocalPort 127.0.0.1:3011
"@
[IO.File]::WriteAllText($config,$sshConfig)
$ready=$false
try {$ready=(Invoke-RestMethod ($address+'/api/deployment') -TimeoutSec 2).role -eq 'central'}catch{}
if(-not $ready){
    $process=Start-Process -FilePath (Get-Command ssh.exe).Source -ArgumentList @('-F',('"'+$config+'"'),'-N','-T','robot-care-reports') -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $private 'connection.log')
    for($attempt=0;$attempt -lt 30;$attempt++){
        if($process.HasExited){throw 'Encrypted connection failed. See private/connection.log.'}
        try {$ready=(Invoke-RestMethod ($address+'/api/deployment') -TimeoutSec 1).role -eq 'central'}catch{}
        if($ready){break}
        Start-Sleep -Milliseconds 300
    }
}
if(-not $ready){throw 'Server report service is not available.'}
$url=$address+'/login'
Write-Host ('Server administrator reports: '+$url)
$chrome=Join-Path $env:ProgramFiles 'Google/Chrome/Application/chrome.exe'
if(-not $NoBrowser){
    if(Test-Path -LiteralPath $chrome){Start-Process -FilePath $chrome -ArgumentList $url}else{Write-Host 'Open this address in Google Chrome.'}
}
