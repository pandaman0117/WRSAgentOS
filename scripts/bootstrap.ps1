param([ValidateSet("llm")][string[]]$Extra = @())

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$pythonExe = if ($env:WRS_AGENT_PYTHON) { $env:WRS_AGENT_PYTHON } else { 'python' }
& $pythonExe -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
if ($LASTEXITCODE) { throw 'Python 3.12 is required; activate it or set WRS_AGENT_PYTHON.' }
$uvExe = Join-Path $projectRoot '.local\tools\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uvExe)) {
    & $pythonExe -m pip install --target .local/tools 'uv==0.12.15'
    if ($LASTEXITCODE) { throw 'uv installation failed' }
}
$env:UV_CACHE_DIR = Join-Path $projectRoot '.local\uv-cache'
$extraArguments = @()
foreach ($name in $Extra) { $extraArguments += @("--extra", $name) }
& $uvExe export @extraArguments --python $pythonExe --locked --quiet --no-emit-project --format requirements-txt --output-file .local/requirements.txt
if ($LASTEXITCODE) { throw 'Lock export failed' }
& $uvExe pip sync --python $pythonExe --target .local/deps .local/requirements.txt
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
