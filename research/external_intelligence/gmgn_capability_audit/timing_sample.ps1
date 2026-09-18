param(
    [string]$OutputRoot = "research\external_intelligence\gmgn_capability_audit\timing_samples",
    [int]$InterRequestDelaySeconds = 6
)

$ErrorActionPreference = "Stop"

function Resolve-GmgnCli {
    $cmd = Get-Command gmgn-cli.cmd -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "gmgn-cli.cmd was not found on PATH."
}

function Invoke-GmgnProcess {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$CommandArgs
    )

    $stdoutTemp = [System.IO.Path]::GetTempFileName()
    $stderrTemp = [System.IO.Path]::GetTempFileName()
    $attemptSw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $CommandArgs -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutTemp -RedirectStandardError $stderrTemp
        $attemptSw.Stop()

        return [pscustomobject]@{
            ExitCode = [int]$proc.ExitCode
            Stdout = [string](Get-Content -Raw -ErrorAction SilentlyContinue $stdoutTemp)
            Stderr = [string](Get-Content -Raw -ErrorAction SilentlyContinue $stderrTemp)
            DurationMs = [math]::Round($attemptSw.Elapsed.TotalMilliseconds, 3)
        }
    }
    finally {
        if ($attemptSw.IsRunning) {
            $attemptSw.Stop()
        }
        Remove-Item -Force -ErrorAction SilentlyContinue $stdoutTemp, $stderrTemp
    }
}

function Invoke-GmgnReadOnlySample {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$Directory,
        [Parameter(Mandatory=$true)][string]$GmgnCli
    )

    $beforeUtc = [DateTimeOffset]::UtcNow
    $beforeMs = $beforeUtc.ToUnixTimeMilliseconds()
    $totalSw = [System.Diagnostics.Stopwatch]::StartNew()

    $attemptCount = 1
    $rateLimitEncountered = $false
    $rateLimitWaitSeconds = 0

    $attempt = Invoke-GmgnProcess -FilePath $GmgnCli -CommandArgs $Args

    if ($attempt.ExitCode -ne 0 -and $attempt.Stderr -match "RATE_LIMIT_EXCEEDED") {
        $rateLimitEncountered = $true
        $waitSeconds = 35
        if ($attempt.Stderr -match "~([0-9]+)s remaining") {
            $waitSeconds = [int]$Matches[1] + 5
        }

        $rateLimitWaitSeconds = $waitSeconds
        Write-Warning "$Name hit GMGN rate limit. Waiting $waitSeconds seconds before one retry."
        Start-Sleep -Seconds $waitSeconds

        $attemptCount = 2
        $attempt = Invoke-GmgnProcess -FilePath $GmgnCli -CommandArgs $Args
    }

    $totalSw.Stop()

    $afterUtc = [DateTimeOffset]::UtcNow
    $afterMs = $afterUtc.ToUnixTimeMilliseconds()

    $meta = [ordered]@{
        capability = $Name
        request_before_utc = $beforeUtc.ToString("o")
        request_before_unix_ms = $beforeMs
        response_after_utc = $afterUtc.ToString("o")
        response_after_unix_ms = $afterMs
        duration_ms = [math]::Round($totalSw.Elapsed.TotalMilliseconds, 3)
        final_attempt_duration_ms = $attempt.DurationMs
        exit_code = $attempt.ExitCode
        attempt_count = $attemptCount
        rate_limit_encountered = $rateLimitEncountered
        rate_limit_wait_seconds = $rateLimitWaitSeconds
        command = "gmgn-cli " + ($Args -join " ")
        private_key_used = $false
        capital_used = $false
    }

    $meta | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.meta.json")
    $attempt.Stdout | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.raw.json")
    $attempt.Stderr | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.stderr.txt")

    if ($attempt.ExitCode -ne 0) {
        Write-Warning "$Name failed with exit code $($attempt.ExitCode). Result recorded; continuing."
    }
    else {
        Write-Host "$Name OK - $($attempt.DurationMs) ms"
    }

    if ($InterRequestDelaySeconds -gt 0) {
        Start-Sleep -Seconds $InterRequestDelaySeconds
    }
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")
$out = Join-Path $OutputRoot $stamp
New-Item -ItemType Directory -Force -Path $out | Out-Null

$gmgnCli = Resolve-GmgnCli

Write-Host "Checking GMGN CLI configuration..."
$configCheck = Invoke-GmgnProcess -FilePath $gmgnCli -CommandArgs @("config", "--check")
if ($configCheck.ExitCode -ne 0) {
    throw "gmgn-cli config --check failed. Do not put API keys in this script or repository."
}

Invoke-GmgnReadOnlySample -Name "trenches_new_creation_pumpfun" -Directory $out -GmgnCli $gmgnCli -Args @(
    "market","trenches","--chain","sol","--type","new_creation",
    "--launchpad-platform","Pump.fun","--limit","80","--raw"
)

Invoke-GmgnReadOnlySample -Name "smartmoney" -Directory $out -GmgnCli $gmgnCli -Args @(
    "track","smartmoney","--chain","sol","--limit","100","--raw"
)

Invoke-GmgnReadOnlySample -Name "kol" -Directory $out -GmgnCli $gmgnCli -Args @(
    "track","kol","--chain","sol","--limit","100","--raw"
)

Invoke-GmgnReadOnlySample -Name "trending_5m" -Directory $out -GmgnCli $gmgnCli -Args @(
    "market","trending","--chain","sol","--interval","5m","--limit","100","--raw"
)

if ($env:GMGN_SAMPLE_WALLET) {
    Invoke-GmgnReadOnlySample -Name "wallet_stats_30d" -Directory $out -GmgnCli $gmgnCli -Args @(
        "portfolio","stats","--chain","sol","--wallet",$env:GMGN_SAMPLE_WALLET,
        "--period","30d","--raw"
    )

    Invoke-GmgnReadOnlySample -Name "wallet_activity" -Directory $out -GmgnCli $gmgnCli -Args @(
        "portfolio","activity","--chain","sol","--wallet",$env:GMGN_SAMPLE_WALLET,
        "--limit","100","--raw"
    )
}

if ($env:GMGN_SAMPLE_DEPLOYER) {
    Invoke-GmgnReadOnlySample -Name "deployer_created_tokens" -Directory $out -GmgnCli $gmgnCli -Args @(
        "portfolio","created-tokens","--chain","sol","--wallet",$env:GMGN_SAMPLE_DEPLOYER,
        "--order-by","token_ath_mc","--direction","desc","--raw"
    )
}

if ($env:GMGN_SAMPLE_TOKEN) {
    Invoke-GmgnReadOnlySample -Name "token_info" -Directory $out -GmgnCli $gmgnCli -Args @(
        "token","info","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,"--raw"
    )

    Invoke-GmgnReadOnlySample -Name "token_security" -Directory $out -GmgnCli $gmgnCli -Args @(
        "token","security","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,"--raw"
    )

    Invoke-GmgnReadOnlySample -Name "token_holders_top100" -Directory $out -GmgnCli $gmgnCli -Args @(
        "token","holders","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,
        "--limit","100","--order-by","amount_percentage","--direction","desc","--raw"
    )

    Invoke-GmgnReadOnlySample -Name "token_holders_smart_degen" -Directory $out -GmgnCli $gmgnCli -Args @(
        "token","holders","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,
        "--limit","100","--tag","smart_degen","--order-by","amount_percentage","--direction","desc","--raw"
    )

    Invoke-GmgnReadOnlySample -Name "token_traders_top100_profit" -Directory $out -GmgnCli $gmgnCli -Args @(
        "token","traders","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,
        "--limit","100","--order-by","profit","--direction","desc","--raw"
    )
}

Write-Host ""
Write-Host "GMGN read-only timing sample complete:"
Write-Host $out
Write-Host "No private key or trade command was used."
