# Запуск сценария Vanessa Automation на демо-базе БСП.
# Менеджер тестирования поднимается в базе, тестовый клиент — в ней же.
# Требуется установленное расширение VAExtension (см. подраздел «Установка расширения» в README).
# Переносимый вариант: клиент 1С ищется в Program Files или задается параметром -Exe,
# база и пользователь — параметрами. Серверная база: -Connection, -Srvr, -Ref.
# Файловая база: -BasePath (путь к каталогу с 1Cv8.1CD), перекрывает серверные параметры.
param(
    [Parameter(Mandatory = $true)][string]$Feature,
    [string]$Profile = 'Демо',
    [string]$User = 'Администратор',
    [string]$Connection = 'localhost\bsp_demo',
    [string]$Srvr = 'localhost',
    [string]$Ref = 'bsp_demo',
    [string]$BasePath = '',
    [switch]$PreLaunchClient,
    [int]$ClientPort = 48050,
    [int]$TimeoutMinutes = 10,
    [string]$Exe = ''
)

$ErrorActionPreference = 'Stop'

$vanessa = $PSScriptRoot

# Файловая база: -BasePath перекрывает серверные -Connection/-Srvr/-Ref.
if ($BasePath) {
    if (-not (Test-Path (Join-Path $BasePath '1Cv8.1CD'))) {
        throw "В файловой базе не найден 1Cv8.1CD: $BasePath"
    }
}

# Клиент 1С: явный -Exe, переменная среды VANESSA_1C_EXE или автоматический выбор.
# Предпочитается самая новая версия, у которой есть и клиент, и сервер (ragent.exe): тестовый
# клиент подключается к серверу той же версии, а клиентские установки без сервера могут не совпасть.
function Find-TestClientExe {
    if ($env:VANESSA_1C_EXE -and (Test-Path $env:VANESSA_1C_EXE)) { return $env:VANESSA_1C_EXE }
    $all = @()
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        $v8 = Join-Path $root '1cv8'
        if (-not (Test-Path $v8)) { continue }
        foreach ($dir in Get-ChildItem $v8 -Directory -ErrorAction SilentlyContinue) {
            $client = Join-Path $dir.FullName 'bin\1cv8c.exe'
            $version = $null
            if ((Test-Path $client) -and [version]::TryParse($dir.Name, [ref]$version)) {
                $all += [pscustomobject]@{
                    Version   = $version
                    Path      = $client
                    HasServer = Test-Path (Join-Path $dir.FullName 'bin\ragent.exe')
                }
            }
        }
    }
    $best = $all | Where-Object HasServer | Sort-Object Version | Select-Object -Last 1
    if (-not $best) { $best = $all | Sort-Object Version | Select-Object -Last 1 }
    if ($best) { $best.Path }
}

if (-not $Exe) { $Exe = Find-TestClientExe }
$epf = Join-Path $vanessa 'tools\vanessa-automation-single.epf'
if (-not $Exe -or -not (Test-Path $Exe)) {
    throw "Не найден клиент 1С (1cv8c.exe). Укажите -Exe, например -Exe 'C:\Program Files\1cv8\8.3.27.2325\bin\1cv8c.exe'"
}
if (-not (Test-Path $epf)) { throw "Не найдена обработка Vanessa: $epf" }
if (-not (Test-Path $Feature)) { throw "Не найден сценарий: $Feature" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = Join-Path $vanessa "reports\run-$stamp"
New-Item $report, (Join-Path $report 'screenshots') -ItemType Directory -Force | Out-Null
$paramsPath = Join-Path $report 'VAParams.json'

# Предзапуск тестового клиента (если -PreLaunchClient). На машинах, где WshShell.Run не
# запускает bat-файлы, штатный запуск клиента из Vanessa падает («Не удается дождаться
# процесса»). Тогда va.ps1 запускает клиента сам, а Vanessa подключается к нему по TCP:
# в профиле клиента задается ИмяКомпьютера 127.0.0.2 — не localhost, чтобы Vanessa не
# пыталась запустить клиента сама (loopback-адрес работает при привязке 0.0.0.0 и не
# режется брандмауэром).
$portBase = $ClientPort
$clientProc = $null
if ($PreLaunchClient) {
    $testPort = $null
    foreach ($p in ($ClientPort..($ClientPort + 49))) {
        if (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) { $testPort = $p; break }
    }
    if (-not $testPort) { throw "Нет свободного порта в диапазоне $ClientPort-$($ClientPort + 49)" }
    $clientArgs = if ($BasePath) { @('ENTERPRISE', '/F', $BasePath) } else { @('ENTERPRISE', '/S', "$Srvr\$Ref") }
    $clientArgs += @('/TESTCLIENT', '-TPort', "$testPort", '/N', $User, '/DisableStartupDialogs', '/DisableStartupMessages')
    Write-Host "Клиент 1С:  $Exe (предзапуск, порт $testPort)"
    $clientProc = Start-Process -FilePath $Exe -ArgumentList $clientArgs -PassThru
    $clientDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $clientDeadline) {
        if ($clientProc.HasExited) { throw "Тестовый клиент завершился сразу после запуска (код $($clientProc.ExitCode))" }
        if (Get-NetTCPConnection -LocalPort $testPort -State Listen -ErrorAction SilentlyContinue) { break }
        Start-Sleep -Seconds 1
    }
    if (-not (Get-NetTCPConnection -LocalPort $testPort -State Listen -ErrorAction SilentlyContinue)) {
        throw "Тестовый клиент не открыл порт $testPort за 90 с; процесс остановлен (PID $($clientProc.Id))"
    }
    $portBase = $testPort
}

$params = [ordered]@{
    'КаталогФич' = (Resolve-Path $Feature).Path
    'ВыполнитьСценарии' = $true
    'ЗавершитьРаботуСистемы' = $true
    'ТаймаутЗапуска1С' = 120
    'ИспользоватьКомпонентуVanessaExt' = $true
    'ИскатьЭлементыФормыПоИмени' = $true
    'ДелатьОтчетВФорматеjUnit' = $true
    'КаталогВыгрузкиJUnit' = $report
    'ВыгружатьСтатусВыполненияСценариевВФайл' = $true
    'ПутьКФайлуДляВыгрузкиСтатусаВыполненияСценариев' = (Join-Path $report 'status.txt')
    'ДелатьЛогВыполненияСценариевВТекстовыйФайл' = $true
    'ИмяФайлаЛогВыполненияСценариев' = (Join-Path $report 'steps.log')
    'ДелатьСкриншотПриВозникновенииОшибки' = $true
    'ИспользоватьВнешнююКомпонентуДляСкриншотов' = $true
    'СпособСнятияСкриншотовВнешнейКомпонентой' = 1
    'КаталогВыгрузкиСкриншотов' = (Join-Path $report 'screenshots')
    'ЗакрытьTestClientПослеЗапускаСценариев' = $true
    'ДиапазонПортовTestclient' = "$portBase-$($portBase + 49)"
    'ДанныеКлиентовТестирования' = @([ordered]@{
        'Имя' = $Profile
        'Синоним' = $Profile
        'ТипКлиента' = 'Тонкий'
        'ПутьКИнфобазе' = $(if ($BasePath) { "File=`"$BasePath`";" } else { "Srvr=`"$Srvr`";Ref=`"$Ref`";" })
        'ПортЗапускаТестКлиента' = $portBase
        'ИмяКомпьютера' = $(if ($PreLaunchClient) { '127.0.0.2' } else { 'localhost' })
        'ДопПараметры' = "/N$User"
    })
}
$json = $params | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($paramsPath, $json, (New-Object Text.UTF8Encoding($false)))

$command = "StartFeaturePlayer;QuietInstallVanessaExt;DisableFirstRunHelper;VAParams=$paramsPath"
# Пути в кавычках: каталог с пробелом в имени должен работать без правки скрипта.
$baseArg = if ($BasePath) { @('/F', $BasePath) } else { @("/S$Connection") }
$arguments = $baseArg + @(
    "/N$User", '/DisableStartupDialogs', '/DisableStartupMessages',
    '/TESTMANAGER', '/Execute', "`"$epf`"", '/C', "`"$command`"", '/Out', "`"$(Join-Path $report 'manager.log')`""
)
Write-Host "Клиент:   $Exe"
Write-Host "Сценарий: $((Resolve-Path $Feature).Path)"
Write-Host "Отчет:    $report"
try {
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -PassThru
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while (-not $process.HasExited -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $process.Refresh()
    }
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        throw "Менеджер Vanessa не завершился за $TimeoutMinutes мин; остановлен свой PID $($process.Id). Отчет: $report"
    }
} finally {
    # Свой тестовый клиент закрываем всегда: сам Vanessa может не успеть, если сценарий упал.
    if ($clientProc -and -not $clientProc.HasExited) {
        Stop-Process -Id $clientProc.Id -Force -ErrorAction SilentlyContinue
    }
}

$statusFile = Join-Path $report 'status.txt'
$status = if (Test-Path $statusFile) { (Get-Content $statusFile -Raw).Trim() } else { '' }
$junitFile = Join-Path $report 'junit.xml'
if (-not (Test-Path $junitFile)) { throw "Нет отчета jUnit; статус '$status'; лог менеджера: $report\manager.log" }
[xml]$junit = Get-Content $junitFile -Raw -Encoding UTF8
$cases = @($junit.SelectNodes('//testcase'))
$failed = @($cases | Where-Object { $_.failure -or $_.error -or $_.skipped })
foreach ($case in $cases) {
    $mark = if ($case.failure -or $case.error -or $case.skipped) { 'X' } else { 'v' }
    Write-Host ("{0} {1}" -f $mark, $case.name)
}
if ($status -ne '0' -or $cases.Count -eq 0 -or $failed.Count -gt 0) {
    throw "Сценарии не прошли: статус '$status', сценариев $($cases.Count), сбоев $($failed.Count). Отчет: $report"
}
Write-Host "Готово: сценариев $($cases.Count), статус 0. Отчет: $report"
