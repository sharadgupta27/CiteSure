# Proves the private stack's claims from inside the API container. Usage: deploy\verify-isolation.ps1
Set-Location (Join-Path $PSScriptRoot "..")
Get-Content -Raw deploy\verify-isolation.py | docker compose -f docker-compose.private.yml exec -T api python -
exit $LASTEXITCODE
