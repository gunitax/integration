# Third-party notice

Часть скиллов в `.zcode/skills/` скопирована из репозитория
[Nikolay-Shirokov/cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills)
(коммит `91ebb9e`) и адаптирована для этого проекта (пути скриптов, база по умолчанию).

Скопированные скиллы: `cfe-init`, `cfe-validate`, `db-load-xml`, `db-update`, `db-cfe-admin`.

Оригинальные файлы распространяются по лицензии MIT:

```
MIT License

Copyright (c) 2025-2026 Nick Shirokov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

XSD-схемы формата выгрузки 1С (каталог `.v8-xsd`) в репозиторий не включаются —
они являются частью продукта «1С:Предприятие 8» (правообладатель ООО «1С-Софт»);
при необходимости получаются скиллом `v8-xsd-fetch` из репозитория
`yellow-hammer/namespace-forest`.
