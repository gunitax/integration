"""Диагностическая копия закрепленной EPF: только журнал точек инициализации."""
from pathlib import Path
import re,shutil,json,hashlib
ROOT=Path(__file__).resolve().parents[1];audit=ROOT/'1c/tmp/salary-audit-20261031'
source=audit/'va-pinned-source';target=audit/'va-instrumented-source'
if target.exists():raise SystemExit('Диагностическая копия уже существует; не перезаписываем результаты')
shutil.copytree(source,target)
rel=Path('vanessa-automation-single/Forms/УправляемаяФорма/Ext/Form/Module.bsl');p=target/rel;before=p.read_bytes();s=before.decode('utf-8-sig');counter=0;points=[]
for name in ['ПриОткрытии','ИнициализацияМодулейИзДругихФорм','ИнициализацияПеременныхМодуляФормы','АсинхронноеПодключениеМодулей','ПриОткрытииПродолжение','ПослеОткрытияФормы','ПослеОткрытияФормыПродолжение']:
 pattern=r'Процедура '+name+r'\([^\n]*\).*?КонецПроцедуры';match=re.search(pattern,s,re.S)
 if match is None:continue
 lines=match[0].splitlines();out=[lines[0]]
 for line in lines[1:]:
  if re.match(r'^\s*[А-Яа-яA-Za-z_][\w.]*\([^\n]*\);\s*$',line) or line.strip()=='КонецПроцедуры':
   counter+=1;label=name+' / '+line.strip();points.append({'number':counter,'point':label})
   out.append('\tЗПАудитVAЭтап("'+str(counter).zfill(3)+'", "'+label.replace('"','""')+'");')
  out.append(line)
 counter+=1;out.insert(1,'\tЗПАудитVAЭтап("'+str(counter).zfill(3)+'", "Вход: '+name+'");')
 s=s[:match.start()]+'\n'.join(out)+s[match.end():]
s+='''
&НаКлиенте
Процедура ЗПАудитVAЭтап(Номер, Текст)
\tЗПЛог = Новый ТекстовыйДокумент; ЗПЛог.УстановитьТекст(Формат(ТекущаяДата(), "ДФ=yyyy-MM-dd HH:mm:ss") + " " + Текст);
\tЗПЛог.Записать("'''+str(ROOT/'1c/logs/va-internal-')+'''" + Номер + ".log", КодировкаТекста.UTF8);
КонецПроцедуры
'''
p.write_text(s,encoding='utf-8-sig')
(audit/'va-instrumentation.json').write_text(json.dumps({'purpose':'Только локализация незавершенной инициализации закрепленной Vanessa 1.2.043.42','original_sha256':hashlib.sha256(before).hexdigest(),'instrumented_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source':str(source),'target':str(target),'points':points},ensure_ascii=False,indent=2),encoding='utf-8')
print('Добавлено точек инициализации:',counter)
