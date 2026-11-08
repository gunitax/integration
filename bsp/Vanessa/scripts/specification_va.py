"""Целевые проверки через MCP Vanessa с сохранением ответов."""
from pathlib import Path
import json, time, sys, base64, uuid
import onec

ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'1c/tmp/specification-va';LOG.mkdir(parents=True,exist_ok=True)
REPORT=ROOT/'docs/reports/specification-20261101-1.1.1';REPORT.mkdir(parents=True,exist_ok=True)

def call(tool,args=None,timeout=90):
    raw=onec.va_mcp_call(onec.va_mcp_url(),tool,args or {},timeout=timeout).decode('utf-8-sig')
    p=LOG/(str(time.time_ns())+'-'+tool+'.json');p.write_text(raw,'utf-8')
    data=json.loads(raw if raw.lstrip().startswith('{') else next(x[6:] for x in raw.splitlines() if x.startswith('data: ')))
    result=data.get('result',{})
    content='\n'.join(x.get('text','') for x in result.get('content',[]) if x.get('type')=='text')
    p.with_suffix('.txt').write_text(content,'utf-8')
    for x in result.get('content',[]):
        if x.get('type')=='image':p.with_suffix('.png').write_bytes(base64.b64decode(x['data']))
    if data.get('error') or result.get('isError'):raise RuntimeError(content or str(data))
    if tool=='execute_feature_step' and 'успешно выполнен' not in content:raise RuntimeError(content)
    return content

def execute(actions,name):
    f=ROOT/'1c/vanessa/features'/('Спецификация-'+str(time.time_ns())+'.feature')
    lines=['# language: ru','Функционал: Спецификация к договору','','Сценарий: '+name]
    nums=[]
    for action in actions:
        nums.append(len(lines)+1);lines.extend('    '+s for s in action.splitlines())
    f.write_text('\n'.join(lines)+'\n','utf-8')
    # На этом стенде редактор отключен. Существующий серверный bootstrap
    # разрешает только вызов штатного загрузчика .feature из 1c/vanessa.
    control=ROOT/'1c/tmp/salary-audit-20261031/va-control-command.json'
    response=control.with_name('va-control-response.json')
    assert not control.exists(),'Другой запрос к менеджеру еще не обработан'
    ident=str(uuid.uuid4())
    control.write_text(json.dumps({'Идентификатор':ident,'Действие':'Загрузить','Путь':str(f)},ensure_ascii=False),'utf-8')
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        if response.exists():
            try:r=json.loads(response.read_text('utf-8-sig'))
            except (ValueError,OSError):r={}
            if r.get('Идентификатор')==ident:
                assert r.get('Статус')=='Вызван штатный загрузчик',r
                (LOG/(ident+'-loader.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),'utf-8')
                break
        time.sleep(.3)
    else:raise RuntimeError('Штатный загрузчик Vanessa не подтвердил загрузку сценария')
    print(call('run_scenario',{'mode':'all'},timeout=180),flush=True)
    results=call('get_test_results');print(results,flush=True)
    if '- Статус: Success' not in results:raise RuntimeError('Сценарий Vanessa завершился с ошибкой; см. сохраненный отчет')
    return f

def server(code):
    return 'И я выполняю код встроенного языка на сервере (Расширение)\n    """bsl\n'+''.join('    '+s+'\n' for s in code.splitlines())+'    """'

if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='tool':print(call(sys.argv[2],json.loads(sys.argv[3]) if len(sys.argv)>3 else {}))
    elif mode=='step':execute([sys.argv[2]],'Пользовательское действие')
    elif mode=='server':execute([server(Path(sys.argv[2]).read_text('utf-8-sig'))],'Серверная проверка')
    elif mode=='connect':print(call('manage_test_client',{'action':'connect','profileName':'УТ'}))
    elif mode=='capture':
        p=REPORT/(sys.argv[2]+'.png')
        print(call('get_window_screenshot_os',{'window_title':'Демо-база / Управление торговлей, редакция 11','color_mode':'color','file_name':str(p)}))
        assert p.exists();print(p)
