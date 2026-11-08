# Загрузка и применение расширения VAExtension в целевую базу 1С.
# Работает в пакетном режиме конфигуратора; база должна быть свободна от монопольных сеансов.
# Пример: powershell -NoProfile -ExecutionPolicy Bypass -File Vanessa\install\Загрузить-VAExtension.ps1 `
#            -Connection 'localhost\bsp_demo' -User 'Администратор'
param(
    [Parameter(Mandatory = $true)][string]$Connection,
    [string]$User = 'Администратор',
    [string]$Password = '',
    [string]$Cfe = '',
    [string]$Extension = 'VAExtension',
    [string]$Exe = '',
    [string]$LogDir = ''
)

$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
if (-not $Cfe) { $Cfe = Join-Path $root 'tools\VAExtension.1.32.cfe' }
if (-not $LogDir) { $LogDir = $PSScriptRoot }

# Конфигуратор 1С: явный -Exe, переменная среды VANESSA_1C_EXE или автоматический выбор.
# Предпочитается самая новая версия с серверными компонентами (ragent.exe): версия конфигуратора
# должна совпадать с версией сервера, иначе пакетные команды не подключатся к базе.
function Find-DesignerExe {
    if ($env:VANESSA_1C_EXE -and (Test-Path $env:VANESSA_1C_EXE)) {
        $fromEnv = Join-Path (Split-Path $env:VANESSA_1C_EXE -Parent) '1cv8.exe'
        if (Test-Path $fromEnv) { return $fromEnv }
    }
    $all = @()
    foreach ($path in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $path -or -not (Test-Path $path)) { continue }
        $v8 = Join-Path $path '1cv8'
        if (-not (Test-Path $v8)) { continue }
        foreach ($dir in Get-ChildItem $v8 -Directory -ErrorAction SilentlyContinue) {
            $designer = Join-Path $dir.FullName 'bin\1cv8.exe'
            $version = $null
            if ((Test-Path $designer) -and [version]::TryParse($dir.Name, [ref]$version)) {
                $all += [pscustomobject]@{
                    Version   = $version
                    Path      = $designer
                    HasServer = Test-Path (Join-Path $dir.FullName 'bin\ragent.exe')
                }
            }
        }
    }
    $best = $all | Where-Object HasServer | Sort-Object Version | Select-Object -Last 1
    if (-not $best) { $best = $all | Sort-Object Version | Select-Object -Last 1 }
    if ($best) { $best.Path }
}

if (-not $Exe) { $Exe = Find-DesignerExe }
if (-not $Exe -or -not (Test-Path $Exe)) {
    throw "Не найден конфигуратор 1С (1cv8.exe). Укажите -Exe, например -Exe 'C:\Program Files\1cv8\8.3.27.2325\bin\1cv8.exe'"
}
if (-not (Test-Path $Cfe)) { throw "Не найден файл расширения: $Cfe" }
New-Item $LogDir -ItemType Directory -Force | Out-Null

$baseArgs = @('DESIGNER', '/S', $Connection, '/N', $User, '/DisableStartupDialogs', '/DisableStartupMessages')
if ($Password) { $baseArgs += @('/P', $Password) }

function Invoke-Designer {
    param([string[]]$Arguments, [string]$LogName)

    $log = Join-Path $LogDir $LogName
    $arguments = $baseArgs + $Arguments + @('/Out', "`"$log`"")
    $process = Start-Process -FilePath $Exe -Wait -PassThru -NoNewWindow -ArgumentList $arguments
    $text = ''
    if (Test-Path $log) { $text = ((Get-Content $log -Raw -Encoding UTF8) -as [string]).Trim() }
    [pscustomobject]@{
        Команда  = ($Arguments | Where-Object { $_ -like '/*' }) -join ' '
        Код      = $process.ExitCode
        Сообщение = $text
        Лог      = $log
    }
}

Write-Host "Конфигуратор: $Exe"
Write-Host "База:         $Connection"
Write-Host "Расширение:   $Extension из $Cfe"

$results = @()
$results += Invoke-Designer -Arguments @('/LoadCfg', "`"$Cfe`"", '-Extension', $Extension) -LogName "$Extension-load.log"
$results += Invoke-Designer -Arguments @('/UpdateDBCfg', '-Extension', $Extension) -LogName "$Extension-update.log"
$results += Invoke-Designer -Arguments @('/CheckConfig', '-Extension', $Extension) -LogName "$Extension-check.log"

$failed = @($results | Where-Object { $_.Код -ne 0 })
foreach ($result in $results) {
    $state = if ($result.Код -eq 0) { 'ok' } else { 'ошибка' }
    Write-Host ("{0,-28} код {1} ({2}) {3}" -f $result.Команда, $result.Код, $state, $result.Сообщение)
}
if ($failed.Count -gt 0) {
    throw "Загрузка расширения $Extension не выполнена. Код 1 обычно означает: расширение с таким именем не найдено при /UpdateDBCfg или /CheckConfig; смотрите логи в $LogDir"
}
Write-Host "Готово: расширение $Extension загружено и применено."
