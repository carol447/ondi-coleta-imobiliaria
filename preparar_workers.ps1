$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseExt = Join-Path $root "extensao"
$workersRoot = Join-Path $root "workers"

New-Item -ItemType Directory -Force -Path $workersRoot | Out-Null

foreach ($worker in @("worker1", "worker2", "worker3")) {
    $workerDir = Join-Path $workersRoot $worker
    $extDir = Join-Path $workerDir "extensao"
    New-Item -ItemType Directory -Force -Path $workerDir | Out-Null

    if (Test-Path $extDir) {
        $resolvedWorkers = (Resolve-Path -LiteralPath $workersRoot).Path
        $resolvedExt = (Resolve-Path -LiteralPath $extDir).Path
        if (-not $resolvedExt.StartsWith($resolvedWorkers, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Caminho inesperado para extensao do worker: $resolvedExt"
        }
        Remove-Item -LiteralPath $extDir -Recurse -Force
    }

    Copy-Item -LiteralPath $baseExt -Destination $extDir -Recurse
    Set-Content -LiteralPath (Join-Path $extDir "worker_config.js") -Value "window.ZAP_WORKER_ID = `"$worker`";" -Encoding UTF8

    $csv = Join-Path $workerDir "municipios.csv"
    if (-not (Test-Path $csv)) {
        @(
            "municipio;estado;url",
            "Presidente Prudente;SP;"
        ) | Set-Content -LiteralPath $csv -Encoding UTF8
    }
}

Write-Host "Workers preparados em: $workersRoot"
Write-Host "Carregue cada extensao pelo Chrome em workers/<worker>/extensao"
