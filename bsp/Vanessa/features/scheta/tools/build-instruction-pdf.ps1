# Сборка PDF-инструкции «Обмен счёт → заказ» из снимков Vanessa.
# Снимки: C:\temp\manual-scheta (создаются фичами scheta-manual.feature и
# scheta-manual-import.feature). PDF: bsp\Vanessa\docs\обмен-счет-заказ-инструкция.pdf.
# Механика: генерируем HTML с разделами и снимками, печатаем в PDF через
# msedge --headless --print-to-pdf (дополнительные инструменты не требуются).
param(
    [string]$Screens = 'C:\temp\manual-scheta',
    [string]$Out = (Join-Path $PSScriptRoot '..\..\..\docs\обмен-счет-заказ-инструкция.pdf'),
    [string]$Edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
)

$ErrorActionPreference = 'Stop'

# Разделы инструкции; каждый соответствует операции quickstart-сценариев 1-3.
# Имя снимка -> подпись под кадром.
$sections = @(
    [ordered]@{
        Title  = '1. Выгрузка счёта в шину'
        Intro  = 'Обработка «Выгрузка счетов в шину» (InfoBase22, БСП). Задайте адрес брокера и топик, отметьте счёта за период и нажмите «Выгрузить». Счёт с пометкой удаления виден в списке, но пропускается с записью в протоколе.'
        Steps  = @(
            @{ File = '01-vygruzka-forma.png'; Caption = 'Форма выгрузки: период текущего года, список счетов за период с колонками Номер, Дата, Организация, Покупатель, Сумма и отметками' },
            @{ File = '02-vygruzka-itog.png';  Caption = 'Итог выгрузки: «Выгружено счетов: N, ошибок: 0»; протокол пропусков — под итогом' }
        )
    },
    [ordered]@{
        Title  = '2. Загрузка счёта в заказ'
        Intro  = 'Обработка «Загрузка счетов из шины» (uf-demo-test). Адрес, группа получателей и топик подставлены по умолчанию. Кнопка «Загрузить» читает порцию сообщений и создаёт/обновляет заказы: сопоставление справочников — артикул/штрихкод с обрезкой 15/20, остальные наименования — строго полные; новые элементы не создаются.'
        Steps  = @(
            @{ File = '10-zagruzka-forma.png'; Caption = 'Форма загрузки со значениями по умолчанию' },
            @{ File = '11-zagruzka-itog.png';  Caption = 'Итог загрузки: «Прочитано: 1, создано: 1, обновлено: 0, пропущено: 0, ошибок: 0»; заказ не проведён, состояние «Открыт»' }
        )
    },
    [ordered]@{
        Title  = '3. Повторная загрузка (без дублей)'
        Intro  = 'Повторный цикл «экспорт → загрузка» по тому же счёту обновляет существующий заказ и не создаёт дублей: заказ идентифицируется парой «номер + дата», товарные строки заменяются полностью.'
        Steps  = @(
            @{ File = '12-zagruzka-povtor.png'; Caption = 'Итог повторной загрузки: «обновлено: 1», количество заказов не изменилось' }
        )
    },
    [ordered]@{
        Title  = '4. Протокол сопоставления'
        Intro  = 'Ненайденные элементы, предупреждения и пропуски попадают в протокол под итогом загрузки. Заказ с ненайденными элементами пропускается целиком (атомарно); новые элементы справочников при загрузке не создаются.'
        Steps  = @(
            @{ File = '13-protokol.png'; Caption = 'Протокол: «товар не найден: …» — заказ не создан, элемент виден в сообщении' }
        )
    },
    [ordered]@{
        Title  = '5. Сверка заказов'
        Intro  = 'Сверка выполняется в базе БСП по HTTP-срезу приёмника. Шаг 1: «Обновление среза заказов приёмника» загружает заказы uf-demo-test в регистр сверки. Шаг 2: отчёт «Сверка заказов с приёмной базой» сравнивает счета источника со срезом: статусы «Совпадает», «Расходится», «Нет в приёмнике», «Нет в источнике», «Счёт помечен на удаление»; по умолчанию показываются только расхождения.'
        Steps  = @(
            @{ File = '20-srez-forma.png'; Caption = 'Форма среза: адрес публикации http://localhost/uf-demo-test/hs/itsh-goods/v1/orders по умолчанию' },
            @{ File = '21-srez-itog.png';  Caption = 'Итог среза: количество записей регистра «СС_СостояниеЗаказовПриемника»' },
            @{ File = '22-otchet.png';     Caption = 'Отчёт сверки: отбор по умолчанию показывает только расхождения (пример — статус «Нет в приёмнике» у счёта без заказа)' }
        )
    }
)

# Проверка входных снимков
$missing = @()
foreach ($section in $sections) {
    foreach ($step in $section.Steps) {
        if (-not (Test-Path (Join-Path $Screens $step.File))) { $missing += $step.File }
    }
}
if ($missing.Count -gt 0) {
    throw "Нет снимков в ${Screens}: $($missing -join ', '). Выполните прогоны scheta-manual.feature и scheta-manual-import.feature."
}
if (-not (Test-Path $Edge)) { throw "Не найден msedge.exe: $Edge" }

# HTML инструкции
$parts = New-Object System.Collections.Generic.List[string]
$parts.Add(@"
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Обмен «Счёт на оплату покупателю» → «Заказ»: инструкция</title>
<style>
  @page { size: A4; margin: 14mm; }
  body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11pt; color: #1a1a1a; margin: 0; }
  h1 { font-size: 18pt; margin: 0 0 4pt 0; }
  .subtitle { color: #555; font-size: 10pt; margin-bottom: 18pt; }
  h2 { font-size: 14pt; margin: 18pt 0 6pt 0; border-bottom: 2px solid #2f5496; padding-bottom: 2pt; page-break-after: avoid; }
  .intro { font-size: 10pt; margin: 0 0 8pt 0; text-align: justify; }
  .frame { page-break-inside: avoid; margin: 0 0 12pt 0; }
  .frame img { max-width: 100%; border: 1px solid #999; }
  .caption { font-size: 9pt; color: #333; margin-top: 3pt; }
  .toc { font-size: 10pt; }
</style>
</head>
<body>
<h1>Обмен «Счёт на оплату покупателю» → «Заказ»</h1>
<div class="subtitle">Инструкция пользователя: Kafka-обмен между конфигурациями БСП (источник) и «ДемонстрационноеПриложение» (приёмник)</div>
<div class="toc">Операции: выгрузка счёта → загрузка в заказ → повторная загрузка → протокол → сверка</div>
"@)
foreach ($section in $sections) {
    $parts.Add("<h2>$($section.Title)</h2>")
    $parts.Add("<div class='intro'>$($section.Intro)</div>")
    foreach ($step in $section.Steps) {
        $img = (Join-Path $Screens $step.File) -replace '\\', '/'
        $parts.Add("<div class='frame'><img src='file:///$img'><div class='caption'>$($step.Caption)</div></div>")
    }
}
$parts.Add("</body></html>")

$htmlPath = Join-Path $env:TEMP 'obmen-schet-zakaz-instrukciya.html'
[IO.File]::WriteAllText($htmlPath, ($parts -join "`n"), (New-Object Text.UTF8Encoding($false)))

# Печать HTML в PDF (headless Edge)
$pdfDir = Split-Path $Out -Parent
New-Item $pdfDir -ItemType Directory -Force | Out-Null
if (Test-Path $Out) { Remove-Item $Out -Force }
& $Edge --headless --disable-gpu --no-pdf-header-footer --print-to-pdf="$Out" ("file:///" + ($htmlPath -replace '\\', '/')) | Out-Null
if (-not (Test-Path $Out)) { throw "PDF не создан: $Out" }
Write-Host "PDF собран: $Out ($([Math]::Round((Get-Item $Out).Length / 1KB)) KB)"
