$ErrorActionPreference = 'Stop'
$pythonExe = if ($env:WRS_AGENT_PYTHON) { $env:WRS_AGENT_PYTHON } else { 'python' }
& $pythonExe -X utf8 -S "$PSScriptRoot\run.py" @args
exit $LASTEXITCODE
