$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'part-c\backend'
$frontend = Join-Path $root 'part-c\frontend'
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Instala Node.js 20.19 o superior y vuelve a abrir VS Code.' }
if (-not (Test-Path $python)) {
    & py -3.12 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Se necesita Python 3.12. Comprueba: py -3.12 --version' }
}
foreach ($port in @(8000, 5173)) {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    if ($listeners | Where-Object { $_.Port -eq $port }) { throw "El puerto $port ya esta ocupado. Cierra la ejecucion anterior antes de iniciar otra." }
}
Push-Location $frontend
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias del frontend.' }
    $server = Start-Process -FilePath $python -ArgumentList @('-u','-m','afc.local','--port','8000') -WorkingDirectory $backend -PassThru
    Write-Host 'Demo local: http://127.0.0.1:5173 - Ctrl+C para detener.'
    & npm.cmd run dev -- --open
}
finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -ErrorAction SilentlyContinue }
    Pop-Location
}
