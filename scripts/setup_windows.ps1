param(
    [switch]$PullModels
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"

if (-not (Test-Path $venv)) {
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"

& $python -m pip install --upgrade pip
& $python -m pip install -e $root

New-Item -ItemType Directory -Force -Path (Join-Path $root "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "models") | Out-Null

if ($PullModels) {
    try {
        ollama pull phi3
        ollama pull mistral
        ollama pull llama3.2-vision
    } catch {
        Write-Host "Ollama pull skipped. Start Ollama and run 'ollama pull phi3', 'ollama pull mistral', and optionally 'ollama pull llama3.2-vision' manually."
    }
}

Write-Host ""
Write-Host "Edith is ready."
Write-Host "For offline speech, place a Vosk model in .\models\vosk"
Write-Host "For image-aware smart sorting, optionally pull a local vision model such as llama3.2-vision"
Write-Host "Launch with .\\launch_edith.bat"
