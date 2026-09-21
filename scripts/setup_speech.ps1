# Install isolated optional speech environments; this does not download model weights.
param([ValidateSet("tts", "asr", "both")][string]$Component = "both")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$pythonExe = if ($env:WRS_AGENT_PYTHON) { $env:WRS_AGENT_PYTHON } else { 'python' }
$uvExe = Join-Path $projectRoot '.local/tools/bin/uv.exe'
if (-not (Test-Path -LiteralPath $uvExe)) { throw 'Run scripts/bootstrap.ps1 first.' }
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousCache = $env:UV_CACHE_DIR
try {
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.local/uv-cache'
    $components = if ($Component -eq "both") { @("tts", "asr") } else { @($Component) }
    foreach ($name in $components) {
        $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot ".local/venvs/qwen-$name"
        & $uvExe sync --locked --no-default-groups --extra "qwen-$name" --python $pythonExe
        if ($LASTEXITCODE) { throw "qwen-$name dependency installation failed" }
    }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    $env:UV_CACHE_DIR = $previousCache
}
Write-Host 'Next: .local/venvs/qwen-asr/Scripts/python.exe scripts/download_speech_models.py'
