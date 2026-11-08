"""Вызовы MCP Vanessa для приемки УПД; сохраняет ответы каждого шага."""
from pathlib import Path
import json,time,sys,urllib.request
import onec
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'docs/reports/upd-barcode-20261025'
LOG=ROOT/'1c/tmp/upd-barcode-20261025/va';LOG.mkdir(parents=True,exist_ok=True)
SHOTS=REPORT/'screenshots';SHOTS.mkdir(parents=True,exist_ok=True)

def call(tool,args=None,timeout=180):
    raw=onec.va_mcp_call(onec.va_mcp_url(),tool,args or {},timeout=timeout).decode('utf-8-sig')
    p=LOG/(str(time.time_ns())+'-'+tool+'.json');p.write_text(raw,'utf-8')
    data=json.loads(raw if raw.lstrip().startswith('{') else next(x[6:] for x in raw.splitlines() if x.startswith('data: ')))
    result=data.get('result',{});text='\n'.join(x.get('text','') for x in result.get('content',[]) if x.get('type')=='text')
    p.with_suffix('.txt').write_text(text,'utf-8')
    assert not data.get('error') and not result.get('isError'),text
    if tool=='execute_feature_step':assert 'успешно выполнен' in text,text
    return text

def execute(actions,name='Приемка УПД'):
    f=LOG/('steps-'+str(time.time_ns())+'.feature')
    lines=['# language: ru','Функционал: УПД со штрихкодами','','Сценарий: '+name];nums=[]
    for a in actions:
        nums.append(len(lines)+1);lines+=['    '+x for x in a.splitlines()]
    f.write_text('\n'.join(lines)+'\n','utf-8');call('open_feature_file',{'filePath':str(f)})
    for n in nums:
        print(n,lines[n-1],flush=True)
        print(call('execute_feature_step',{'filePath':str(f),'lineNumber':n})[:350],flush=True)
    return f

def server(code):
    return 'И я выполняю код встроенного языка на сервере (Расширение)\n    """bsl\n'+''.join('    '+l+'\n' for l in code.splitlines())+'    """'

def discover():
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    def rpc(method,params,ident=1):
        body={'jsonrpc':'2.0','method':method,'params':params}
        if ident:body['id']=ident
        req=urllib.request.Request(onec.va_mcp_url().geturl(),json.dumps(body).encode(),headers)
        with urllib.request.urlopen(req,timeout=120) as response:
            if response.headers.get('Mcp-Session-Id'):headers['Mcp-Session-Id']=response.headers['Mcp-Session-Id']
            raw=response.read().decode('utf-8-sig')
        if not raw.strip():return {}
        return json.loads(raw if raw.lstrip().startswith('{') else next(x[6:] for x in raw.splitlines() if x.startswith('data: ')))
    rpc('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'upd-acceptance','version':'1'}})
    rpc('notifications/initialized',{},None)
    result=rpc('tools/list',{})
    (LOG/'tools.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return result

if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='server':execute([server(Path(sys.argv[2]).read_text('utf-8-sig'))])
    elif mode=='step':execute([sys.argv[2]])
    elif mode=='analysis':print(call('get_form_analysis',{'format':'full'}))
    elif mode=='call':print(call(sys.argv[2],json.loads(sys.argv[3]) if len(sys.argv)>3 else {}))
    elif mode=='tools':print('\n'.join(t['name']+' '+t.get('description','')[:170] for t in discover().get('result',{}).get('tools',[])))
