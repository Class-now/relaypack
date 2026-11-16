# Full live benchmark on Windows (keys come from the local secret vault; nothing is written to disk).
#   Start-Process pwsh -WindowStyle Hidden -ArgumentList '-NoProfile','-File','run_live.ps1'
param([int]$Runs = 10)
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:MEKO_API_KEY = (& secret get mekodata.ai meko-api-key)
$env:ANTHROPIC_API_KEY = (& secret get anthropic.com contextcon)
python -u -m relaypack.bench --runs $Runs --live --out results *> results/live-run.log
"exit $LASTEXITCODE" | Out-File -Append results/live-run.log
