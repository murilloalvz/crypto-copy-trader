param(
    [string]$OutputRoot = "research\external_intelligence\gmgn_capability_audit\timing_samples"
)

$ErrorActionPreference = "Stop"

function Get-UnixMs {
    return [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
}

function Invoke-GmgnReadOnlySample {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$Directory
    )

    $beforeUtc = [DateTimeOffset]::UtcNow
    $beforeMs = $beforeUtc.ToUnixTimeMilliseconds()
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    $stdout = ""
    $stderr = ""
    $exitCode = $null

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "gmgn-cli"
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        foreach ($arg in $Args) {
            [void]$psi.ArgumentList.Add($arg)
        }

        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
    }
    finally {
        $sw.Stop()
    }

    $afterUtc = [DateTimeOffset]::UtcNow
    $afterMs = $afterUtc.ToUnixTimeMilliseconds()

    $meta = [ordered]@{
        capability = $Name
        request_before_utc = $beforeUtc.ToString("o")
        request_before_unix_ms = $beforeMs
        response_after_utc = $afterUtc.ToString("o")
        response_after_unix_ms = $afterMs
        duration_ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 3)
        exit_code = $exitCode
        command = "gmgn-cli " + ($Args -join " ")
        private_key_used = $false
        capital_used = $false
    }

    $meta | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.meta.json")
    $stdout | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.raw.json")
    $stderr | Set-Content -Encoding UTF8 (Join-Path $Directory "$Name.stderr.txt")

    if ($exitCode -ne 0) {
        Write-Warning "$Name failed with exit code $exitCode. Do not retry repeatedly if rate-limited."
    } else {
        Write-Host "$Name OK — $([math]::Round($sw.Elapsed.TotalMilliseconds, 1)) ms"
    }
}

$stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss")
$out = Join-Path $OutputRoot $stamp
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host "Checking GMGN CLI configuration..."
& gmgn-cli config --check
if ($LASTEXITCODE -ne 0) {
    throw "gmgn-cli config --check failed. Do not put API keys in this script or repository."
}

Invoke-GmgnReadOnlySample -Name "trenches_new_creation_pumpfun" -Directory $out -Args @(
    "market","trenches","--chain","sol","--type","new_creation",
    "--launchpad-platform","Pump.fun","--limit","80","--raw"
)

Invoke-GmgnReadOnlySample -Name "smartmoney" -Directory $out -Args @(
    "track","smartmoney","--chain","sol","--limit","100","--raw"
)

Invoke-GmgnReadOnlySample -Name "kol" -Directory $out -Args @(
    "track","kol","--chain","sol","--limit","100","--raw"
)

Invoke-GmgnReadOnlySample -Name "trending_5m" -Directory $out -Args @(
    "market","trending","--chain","sol","--interval","5m","--limit","100","--raw"
)

if ($env:GMGN_SAMPLE_WALLET) {
    Invoke-GmgnReadOnlySample -Name "wallet_stats_30d" -Directory $out -Args @(
        "portfolio","stats","--chain","sol","--wallet",$env:GMGN_SAMPLE_WALLET,
        "--period","30d","--raw"
    )
    Invoke-GmgnReadOnlySample -Name "wallet_activity" -Directory $out -Args @(
        "portfolio","activity","--chain","sol","--wallet",$env:GMGN_SAMPLE_WALLET,
        "--limit","100","--raw"
    )
}

if ($env:GMGN_SAMPLE_DEPLOYER) {
    Invoke-GmgnReadOnlySample -Name "deployer_created_tokens" -Directory $out -Args @(
        "portfolio","created-tokens","--chain","sol","--wallet",$env:GMGN_SAMPLE_DEPLOYER,
        "--order-by","token_ath_mc","--direction","desc","--raw"
    )
}

if ($env:GMGN_SAMPLE_TOKEN) {
    Invoke-GmgnReadOnlySample -Name "token_info" -Directory $out -Args @(
        "token","info","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,"--raw"
    )
    Invoke-GmgnReadOnlySample -Name "token_security" -Directory $out -Args @(
        "token","security","--chain","sol","--address",$env:GMGN_SAMPLE_TOKEN,"--raw"
    )
}

Write-Host ""
Write-Host "GMGN read-only timing sample complete:"
Write-Host $out
Write-Host "No private key or trade command was used."
