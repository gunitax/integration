# Тестовый прогон Vanessa smoke на файловой базе InfoBase22 (Q:\AIZCODE.V5).
# Раннер va.ps1 создает отчет в Vanessa\reports\run-<дата-время>:
# status.txt (0 = успех), junit.xml, steps.log, manager.log, screenshots.
$ErrorActionPreference = 'Stop'

$vanessa = $PSScriptRoot
$runner  = Join-Path $vanessa 'va.ps1'
$feature = Join-Path $vanessa 'features\smoke\bsp-demo-smoke.feature'
$exe     = 'C:\Program Files\1cv8\8.5.1.1529\bin\1cv8c.exe'

try {
    & $runner -Feature $feature `
        -BasePath 'D:\infobase\infobase22' `
        -User 'Администратор' -Profile 'Демо' `
        -PreLaunchClient `
        -Exe $exe -TimeoutMinutes 10
    exit 0
} catch {
    Write-Output ('FAIL: ' + $_.Exception.Message)
    exit 1
}
