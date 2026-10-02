# Runs one or more Rejection Filter V3 cohorts (T1..T10, then T11..T13 only for DEGRADED ones) on the owner's machine.
# PAPER / RESEARCH / NO LIVE MONEY. Makes live provider calls (Solana WSS/RPC, Jupiter quotes).
# It only chains the documented steps; every safety rule lives in rejection_filter_holdout_v3_collect.py
# (protocol hash, run-key freshness, UTC-day rules, pre-flight, console guard). It never edits the protocol.
#
# Usage:   .\research\run_v3_cohorts.ps1 -DryRun          # checks only, changes nothing
#          .\research\run_v3_cohorts.ps1 -Cohorts 3       # up to 3 cohorts in a row (max per UTC day)
param(
  [int]$Cohorts = 1,
  [string]$Repo = "C:\Users\LocalUser\Projetos\copytrader-sim",
  [string]$Py = "C:\Users\LocalUser\Projetos\crypto-copy-trader\.venv\Scripts\python.exe",
  [string]$Db = "C:\Users\LocalUser\Projetos\crypto-copy-trader\data\copytrader.db",
  [switch]$SkipBackup,
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
if ($Cohorts -lt 1 -or $Cohorts -gt 3) { throw "-Cohorts must be 1..3 (at most 3 cohorts may start per UTC day)" }
Set-Location $Repo
$utc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
Write-Host "UTC date: $utc (a cohort counts for the UTC date on which it STARTS)"
$env:DATABASE_PATH = $Db
if (-not (Test-Path $Db)) { throw "Database not found: $Db" }
if (-not (Test-Path (Join-Path $Repo ".env"))) { throw ".env missing in $Repo (copy it from the original folder; never commit it)" }
& $Py -c "from src.config import settings; h=settings.rpc_url.split('?')[0].split('/')[2]; print('rpc host:', h); print('jupiter key set:', bool(settings.jupiter_api_key)); import sys; sys.exit(0 if settings.jupiter_api_key and h not in ('api.mainnet.solana.com','api.mainnet-beta.solana.com') else 3)"
if ($LASTEXITCODE -ne 0) { throw "Environment check failed (need a dedicated RPC host and JUPITER_API_KEY set)" }
if ($DryRun) { Write-Host "DRY RUN OK: date, database, .env and settings look fine. Nothing was changed."; return }

git fetch origin research/exit-hypothesis-bankroll-sim-v0
git merge --ff-only origin/research/exit-hypothesis-bankroll-sim-v0
if ($LASTEXITCODE -ne 0) { throw "git merge --ff-only failed; resolve before running" }
git log --oneline -1

if (-not $SkipBackup) {
  $bak = "$Db.bak-v3-$utc"
  if (-not (Test-Path $bak)) { Copy-Item $Db $bak }
  $a = (Get-Item $Db).Length; $b = (Get-Item $bak).Length
  Write-Host "backup: $bak ($b bytes; db $a bytes)"
}

Write-Host "Generating a fresh PumpSwap identity bootstrap (about 1-3 minutes)..."
& $Py -m benchmarks.pumpswap_identity_bootstrap_v0.bootstrap | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Bootstrap failed (exit $LASTEXITCODE); no cohort was started" }
$bs = Get-ChildItem -Recurse -File artifacts\pumpswap_identity_bootstrap_v0 -Filter report.json |
  Sort-Object LastWriteTime -Descending |
  Where-Object { (Get-Content $_.FullName -Raw | ConvertFrom-Json).valid_bootstrap -eq $true } |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $bs) { throw "No valid bootstrap report found" }
Write-Host "bootstrap: $bs"

for ($i = 1; $i -le $Cohorts; $i++) {
  Write-Host "`n=== V3 cohort run $i of $Cohorts ==="
  & $Py rejection_filter_holdout_v3_collect.py --bootstrap-report "$bs" --confirm-live-acquisition
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    Write-Host "Stopped: the runner exited with code $code (2 = cohort DEGRADED, otherwise a refusal or error). Read its message above."
    break
  }
}
Get-ChildItem artifacts\rejection_filter_holdout_v3 -Filter *-acquisition-report.json -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime | ForEach-Object { $_.Name }
