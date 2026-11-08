# Vanessa Automation в проекте

Материалы Vanessa Automation (ВА), перенесенные из `C:\Users\IT\Desktop\hakaton` без `.git`.
Каталог самодостаточен для сценарного прогона в демо-базе БСП `bsp_demo`; правила и
справочники проекта-источника приложены как справка.

Инструкция по переносу в другой проект (что копировать, как загрузить расширение, как
запустить и прочитать результат): `ИНСТРУКЦИЯ-ПЕРЕНОС.md`. Готовый архив для переноса —
`dist/Vanessa-Automation-Kit-20261102.zip` в корне проекта.

## Состав

| Путь | Содержимое |
| --- | --- |
| `va.ps1` | Локальный раннер: менеджер тестирования и тестовый клиент в `bsp_demo` |
| `tools/` | Закрепленные файлы ВА: `vanessa-automation-single.epf` 1.2.043.42, `VAExtension.1.32.cfe`, `client_mcp.cfe` 0.6.5 |
| `features/` | Сценарии `1c/vanessa` источника: 179 `.feature`, каталог `diagnostics` и автоматические снимки `png` |
| `features/smoke/` | Новый дымовой сценарий `bsp-demo-smoke.feature` |
| `install/` | Журналы загрузки и применения `VAExtension` в `bsp_demo` |
| `logs/` | Журналы прежних прогонов: `1c/logs/vanessa` (60 каталогов `run-*`), `1c/logs/va-mcp`, файлы `va-*.log` |
| `extensions/ИнструментыVanessaСервер/` | Серверный bootstrap менеджера из источника (абсолютные пути хакатона; в этой базе не загружался) |
| `scripts/` | Харнесс `onec.py`, va-скрипты источника, закрепы `vanessa.json` |
| `docs/hakaton-skills/` | Правила и справочники источника: `onec-development`, триаж, XML расширения, поля выбора |
| `reports/` | Отчеты, журналы и распакованные исходники EPF из `docs/reports`, `output`, `1c/tmp` источника |

Объем: около 3,3 тыс. файлов и 350 МБ. Из них 219 МБ — распакованные исходники обработки
(`reports/1c/tmp/.../va-pinned-source`, `va-instrumented-source`, `choices-vanessa-source`).
Это диагностические копии источника; при нехватке места их можно удалить без потери запуска.

## Контрольные суммы

Сверены с `scripts/vanessa.json` после копирования, расхождений нет.

| Файл | Версия | SHA-256 |
| --- | --- | --- |
| `tools/vanessa-automation-single.epf` | 1.2.043.42 | `92675132e3b59e9cb492f4202746d29455c108cd6c9e0751c7c3e950080239e0` |
| `tools/VAExtension.1.32.cfe` | 1.32 | `3a90c163f7b7c4852e2a74a1fb4270276310add974fbe443059152e7417e1fc4` |
| `tools/client_mcp.cfe` | 0.6.5 | `d1093475a15e50a33ad48a64b61d09d1108b5a39328c73e6be17a5c914825e7f` |

## Установка расширения

Расширение `VAExtension` 1.32 загружено в `bsp_demo` и применено:

```powershell
$exe = 'C:\Program Files\1cv8\8.3.27.2325\bin\1cv8.exe'
$opt = @('DESIGNER','/S','localhost\bsp_demo','/N','Администратор',
         '/DisableStartupDialogs','/DisableStartupMessages')
Start-Process -FilePath $exe -Wait -ArgumentList ($opt + @(
    '/LoadCfg','Vanessa\tools\VAExtension.1.32.cfe','-Extension','VAExtension',
    '/Out','Vanessa\install\VAExtension-load.log'))
Start-Process -FilePath $exe -Wait -ArgumentList ($opt + @(
    '/UpdateDBCfg','-Extension','VAExtension','/Out','Vanessa\install\VAExtension-update.log'))
```

Проверка: `/CheckConfig -Extension VAExtension` отвечает «Ошибок не обнаружено»
(`install/VAExtension-check.log`). До установки та же команда отвечала «расширение
конфигурации с указанным именем не найдено».

## Тестовый прогон

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File Vanessa\va.ps1 `
    -Feature Vanessa\features\smoke\bsp-demo-smoke.feature
```

Раннер создает `reports/run-<дата-время>`, пишет `VAParams.json`, поднимает
`1cv8c.exe /TESTMANAGER /Execute tools\vanessa-automation-single.epf` в `bsp_demo`,
сохраняет `junit.xml`, `status.txt`, `steps.log`, `manager.log` и снимки ошибок.
Успех требует статус `0`, ненулевое число сценариев и отсутствие `failure/error/skipped`;
код выхода процесса сам по себе успехом не считается.

Сценарий `features/smoke/bsp-demo-smoke.feature` подключает профиль «Демо»
(тонкий клиент, `Srvr="localhost";Ref="bsp_demo";`, пользователь `Администратор`),
открывает список `e1cib/list/Справочник._ДемоОрганизации`, проверяет заголовок окна
«Демо: Организации» и закрывает окна.

Фактические прогоны 02.11.2026:

| Отчет | Что проверено | Результат |
| --- | --- | --- |
| `reports/smoke-20261102-01` | подключение клиента и навигационная ссылка без проверки окна | 1 сценарий, статус 0 |
| `reports/smoke-20261102-02` | то же со снимком `screen-01.png` | 1 сценарий, статус 0; на снимке форма «Демо: Организации» с тремя строками |
| `reports/run-20261102-213042` | финальный прогон через `va.ps1` с проверкой заголовка окна | 1 сценарий, статус 0, 11,9 с |

## Границы переноса

- В `scripts/` лежат справочные `onec.py` и va-скрипты источника:
  они рассчитаны на стенд хакатона (`stand.json` с УТ, `v8-runner`, `v8project.yaml`) и в этом
  проекте как есть не работают. Рабочий запуск здесь дает только `va.ps1`.
- Сценарии в `features/` написаны для УТ 11 и профиля «УТ»; в `bsp_demo` они не запускались
  и годятся как образцы приемов. Целевой рабочий сценарий — `features/smoke`.
- Интерактивный MCP-режим (порт 9874, `client_mcp`, `mcpPort`) не поднимался: он требует
  отдельной настройки менеджера. Файлы `client_mcp.cfe` и настройки `mcp` из источника
  приложены для справки.
- `extensions/ИнструментыVanessaСервер` содержит абсолютные пути хакатона и обработку
  с диагностической копией EPF, поэтому в `bsp_demo` не загружался.
- Прогоны выполнены с закрепленной платформой 8.3.27.2325. Сеансы пользователей и чужие
  клиенты 1С не завершались; после прогонов своих процессов менеджера и тестового клиента
  не осталось.
