"""Попросить свой менеджер Vanessa загрузить .feature штатным загрузчиком дерева."""
from pathlib import Path
import argparse, json, time, uuid

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('feature',type=Path);args=parser.parse_args()
feature=args.feature.resolve()
if not feature.is_relative_to(ROOT/'1c/vanessa') or feature.suffix!='.feature' or not feature.is_file():
    raise SystemExit('Нужен существующий .feature внутри 1c/vanessa проекта')
folder=ROOT/'1c/tmp/salary-audit-20261031';command=folder/'va-control-command.json';response=folder/'va-control-response.json'
ident=str(uuid.uuid4())
temporary=command.with_suffix('.new')
temporary.write_text(json.dumps({'Идентификатор':ident,'Действие':'Загрузить','Путь':str(feature)},ensure_ascii=False),encoding='utf-8')
temporary.replace(command)
deadline=time.monotonic()+30
while time.monotonic()<deadline:
    if response.exists():
        try:
            result=json.loads(response.read_text(encoding='utf-8-sig'))
            if result.get('Идентификатор')==ident:
                print(json.dumps(result,ensure_ascii=False,indent=2))
                raise SystemExit(1 if result.get('Статус')=='Ошибка' else 0)
        except json.JSONDecodeError:pass
    time.sleep(.25)
raise SystemExit('Менеджер не подтвердил загрузку за30секунд; факт загрузки не подтвержден')
