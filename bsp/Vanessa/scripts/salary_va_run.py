"""Запуск одного feature штатным деревом Vanessa и архив свежих свидетельств."""
from pathlib import Path
import argparse,sys,json,subprocess,time,shutil
from xml.etree import ElementTree as E
import onec
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('feature',type=Path);p.add_argument('archive');p.add_argument('--timeout',type=int,default=55);a=p.parse_args()
archive=ROOT/'output/salary-audit-20261031/vanessa'/a.archive
if archive.exists():raise SystemExit('Архив уже существует; выберите новое имя')
archive.mkdir(parents=True)
shutil.copy2(a.feature.resolve(),archive/'scenario.feature')
subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/salary_va_load_native.py'),str(a.feature)],check=True)
started=time.time();pending=False
try:
 raw=onec.va_mcp_call(onec.va_mcp_url(),'run_scenario',{'mode':'all'},timeout=a.timeout)
 (archive/'run-response.txt').write_bytes(raw)
except TimeoutError as exc:
 pending=True;(archive/'pending.txt').write_text(str(exc),encoding='utf-8')
for f in ['junit/junit.xml','steps.log','manager.log']:
 src=ROOT/'1c/logs/va-mcp'/f
 if src.exists():shutil.copy2(src,archive/src.name)
report=ROOT/'1c/logs/va-mcp/junit/junit.xml'
if not report.exists() or report.stat().st_mtime < started-2:
 print('Нет свежего JUnit; состояние требуется проверить, pending=',pending);raise SystemExit(2)
try:
 tree=E.parse(report);cases=tree.findall('.//testcase')
except E.ParseError:
 print('JUnit еще пишется');raise SystemExit(2)
bad=[x.get('name') for x in cases if x.find('failure') is not None or x.find('error') is not None or x.find('skipped') is not None]
result={'feature':str(a.feature),'cases':len(cases),'bad':bad,'pending_http':pending,'started_epoch':started,'completed_epoch':time.time()}
(archive/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
raise SystemExit(1 if bad or not cases else 0)
