param(
    [ValidateRange(0.5, 72)]
    [double]$Hours = 12,
    [ValidateRange(1, 60)]
    [double]$PriceIntervalMinutes = 1,
    [ValidateRange(5, 360)]
    [double]$DiscoveryIntervalMinutes = 30,
    [ValidateRange(1, 100)]
    [int]$Tokens = 25,
    [ValidateRange(1, 100)]
    [int]$Top = 3
)

$ErrorActionPreference = "Continue"
$ProjectRoot = $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $ProjectRoot ".env"
$LogDirectory = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $Python)) {
    throw "Ambiente virtual nao encontrado. Crie .venv e instale requirements.txt."
}
if (-not (Test-Path $EnvFile)) {
    throw "Arquivo .env nao encontrado. Copie .env.example para .env e configure a API."
}
if ($DiscoveryIntervalMinutes -lt $PriceIntervalMinutes) {
    throw "DiscoveryIntervalMinutes deve ser maior ou igual a PriceIntervalMinutes."
}

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDirectory "monitor-$Timestamp.log"

Set-Location $ProjectRoot
Write-Host "Crypto Copy Trader - iniciador do laboratorio paper"
Write-Host "Log desta sessao: $LogPath"
Write-Host "Mantenha o notebook ligado e sem suspensao. Ctrl+C encerra com seguranca."

$StartedAt = Get-Date
@(
    "Crypto Copy Trader - monitor log"
    "StartedAt: $($StartedAt.ToString('o'))"
    "Hours: $Hours"
    "PriceIntervalMinutes: $PriceIntervalMinutes"
    "DiscoveryIntervalMinutes: $DiscoveryIntervalMinutes"
    "Tokens: $Tokens"
    "Top: $Top"
    "---"
) | Set-Content -Path $LogPath -Encoding UTF8

$ExitCode = 0
try {
    & $Python monitor.py `
        --hours $Hours `
        --price-interval-minutes $PriceIntervalMinutes `
        --discovery-interval-minutes $DiscoveryIntervalMinutes `
        --tokens $Tokens `
        --top $Top 2>&1 | ForEach-Object {
            $Line = "$_"
            Write-Host $Line
            Add-Content -Path $LogPath -Value $Line -Encoding UTF8
        }
    $ExitCode = $LASTEXITCODE
}
finally {
    $EndedAt = Get-Date
    $EndLine = "EndedAt: $($EndedAt.ToString('o')) | ExitCode: $ExitCode"
    Write-Host $EndLine
    Add-Content -Path $LogPath -Value $EndLine -Encoding UTF8
    Write-Host "Monitor encerrado. Log salvo em: $LogPath"
}

exit $ExitCode
