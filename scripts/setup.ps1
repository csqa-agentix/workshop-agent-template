# One-time setup for Windows (PowerShell). Run from the project folder:  .\scripts\setup.ps1
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host ""
Write-Host "Setup finished."
Write-Host "  1) Switch the environment on:   .venv\Scripts\activate"
Write-Host "  2) Check everything:            python -m app doctor"
Write-Host "  3) Try it (no key needed):      python -m app --offline"
Write-Host "  4) For the real model, open .env and paste your NVIDIA key after NVIDIA_API_KEY="
