# Загрузка и применение VAExtension в файловую тестовую базу InfoBase22 (Q:\AIZCODE.V5).
# По правилам AGENTS.md проверка расширений в InfoBase22 разрешена штатно.
# Платформа 8.5.1.1529 — та же, которой в базу загружалось расширение КассовыеДокументы.
# Результаты: Vanessa\install\InfoBase22-result.txt (UTF-8 BOM).
$ErrorActionPreference = 'Stop'

$exe    = 'C:\Program Files\1cv8\8.5.1.1529\bin\1cv8.exe'
$base   = 'D:\infobase\infobase22'
$user   = 'Администратор'
$cfe    = 'Q:\AIZCODE.V5\Vanessa\tools\VAExtension.1.32.cfe'
$ext    = 'VAExtension'
$logDir = 'Q:\AIZCODE.V5\Vanessa\install'
$result = Join-Path $logDir 'InfoBase22-result.txt'

$steps = @(
    @{ Шаг = 'LoadCfg';     Арг = @('/LoadCfg', $cfe, '-Extension', $ext); Лог = 'VAExtension-load.log' },
    @{ Шаг = 'UpdateDBCfg'; Арг = @('/UpdateDBCfg', '-Extension', $ext);   Лог = 'VAExtension-update.log' },
    @{ Шаг = 'CheckConfig'; Арг = @('/CheckConfig', '-Extension', $ext);   Лог = 'VAExtension-check.log' }
)

$lines = @('Загрузка VAExtension в InfoBase22 — ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$lines += 'Конфигуратор: ' + $exe
$lines += 'База: ' + $base + ' (файловая), пользователь ' + $user
$failed = $false
foreach ($step in $steps) {
    $log = Join-Path $logDir $step.Лог
    if (Test-Path $log) { Remove-Item $log -Force }
    $arg = @('DESIGNER', '/F', $base, '/N', $user, '/DisableStartupDialogs', '/DisableStartupMessages') + $step.Арг + @('/Out', $log)
    $p = Start-Process -FilePath $exe -ArgumentList $arg -Wait -PassThru
    $msg = ''
    if (Test-Path $log) { $msg = ((Get-Content $log -Raw -Encoding UTF8) -as [string]) }
    if ($msg) { $msg = $msg.Trim() }
    $ok = ($p.ExitCode -eq 0)
    if (-not $ok) { $failed = $true }
    $lines += ''
    $lines += $step.Шаг + ': код ' + $p.ExitCode + $(if ($ok) { ' (ok)' } else { ' (ОШИБКА)' })
    if ($msg) { $lines += '  ' + $msg }
}

$lines += ''
if ($failed) {
    $lines += 'ИТОГ: ОШИБКА — расширение не загружено или не применено.'
} else {
    $lines += 'ИТОГ: Готово — расширение VAExtension загружено и применено в InfoBase22.'
}
[IO.File]::WriteAllText($result, ($lines -join "`r`n") + "`r`n", (New-Object Text.UTF8Encoding($true)))
Write-Output ('DONE failed=' + $failed)
if ($failed) { exit 1 } else { exit 0 }
