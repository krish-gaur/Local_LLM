$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv")) { py -3.11 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Write-Host "Jean Grey installed. Ollama and model weights are not downloaded automatically."
Write-Host "Optional voice libraries: .\.venv\Scripts\python.exe -m pip install -e '.[voice]'"
Write-Host "Optional official MCP SDK: .\.venv\Scripts\python.exe -m pip install -e '.[mcp]'"
Write-Host "Optional local wake engine: .\.venv\Scripts\python.exe -m pip install -e '.[wake]'"
Write-Host "Install Ollama/Piper/Playwright MCP separately only after explicit approval."
Write-Host "Run health checks: .\.venv\Scripts\jean-grey.exe voice --check"
