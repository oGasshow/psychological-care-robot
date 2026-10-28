param(
    [string]$UvExecutable = '',
    [string]$PythonExecutable = '3.13.18'
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
if (-not $UvExecutable) {
    $taskLocalUv = Join-Path $taskRoot '.tools\bin\uv.exe'
    if (Test-Path -LiteralPath $taskLocalUv) { $UvExecutable = $taskLocalUv }
    else { $UvExecutable = (Get-Command uv -ErrorAction Stop).Source }
}
$env:UV_PROJECT_ENVIRONMENT = Join-Path $taskRoot '.venv'
$env:UV_CACHE_DIR = Join-Path $taskRoot '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot '.python'
$env:UV_PYTHON_BIN_DIR = Join-Path $taskRoot '.tools\bin'
& $UvExecutable sync --project (Join-Path $taskRoot 'backend') --frozen --python $PythonExecutable
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
& (Join-Path $taskRoot '.venv\Scripts\python.exe') -c 'import sys,sqlite3; print(sys.executable); print(sys.version); print(sqlite3.sqlite_version)'
if ($LASTEXITCODE -ne 0) { throw 'Interpreter check failed' }
