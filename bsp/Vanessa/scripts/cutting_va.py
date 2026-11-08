"""Вызов MCP Vanessa через проектный харнесс, журнал текущей задачи."""
from pathlib import Path
import sys,json,time,base64
import onec
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'1c/tmp/cutting-va';OUT.mkdir(parents=True,exist_ok=True)
tool=sys.argv[1];args={}
for i in range(2,len(sys.argv),2):
    key=sys.argv[i].lstrip('-');value=sys.argv[i+1]
    if value in ['true','false']:value=value=='true'
    elif key in ['lineNumber','limit','start_number','end_number']:value=int(value)
    args[key]=value
raw=onec.va_mcp_call(onec.va_mcp_url(),tool,args,timeout=150).decode('utf-8-sig')
p=OUT/(str(time.time_ns())+'-'+tool+'.json');p.write_text(raw,'utf-8')
data=json.loads(raw if raw.lstrip().startswith('{') else next(x[6:] for x in raw.splitlines() if x.startswith('data: ')))
r=data.get('result',{});txt='\n'.join(x.get('text','') for x in r.get('content',[]) if x.get('type')=='text');p.with_suffix('.txt').write_text(txt,'utf-8');print(txt[:20000])
for b in r.get('content',[]):
    if b.get('type')=='image':p.with_suffix('.png').write_bytes(base64.b64decode(b['data']));print(p.with_suffix('.png'))
if data.get('error') or r.get('isError'):sys.exit(1)
if tool=='execute_feature_step' and 'успешно выполнен' not in txt:sys.exit(2)
