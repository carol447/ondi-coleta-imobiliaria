$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$origem = Join-Path $raiz "extensao"
$destinoWorkers = Join-Path $raiz "workers"

foreach ($workerId in @("worker1", "worker2", "worker3")) {
    $workerRoot = Join-Path $destinoWorkers $workerId
    $extensao = Join-Path $workerRoot "extensao"
    New-Item -ItemType Directory -Force -Path $workerRoot | Out-Null
    if (Test-Path $extensao) {
        $workersResolvido = (Resolve-Path -LiteralPath $destinoWorkers).Path
        $extensaoResolvida = (Resolve-Path -LiteralPath $extensao).Path
        if (-not $extensaoResolvida.StartsWith($workersResolvido, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Caminho inesperado: $extensaoResolvida"
        }
        Remove-Item -LiteralPath $extensao -Recurse -Force
    }
    Copy-Item -LiteralPath $origem -Destination $extensao -Recurse
    $config = @"
globalThis.ZAP_V4_WORKER = {
  id: "$workerId"
};
"@
    Set-Content -LiteralPath (Join-Path $extensao "worker_config.js") -Value $config -Encoding UTF8
}

Write-Host "Três workers genéricos preparados."
Write-Host "O servidor-maestro decidirá município e tipo de cada tarefa."
