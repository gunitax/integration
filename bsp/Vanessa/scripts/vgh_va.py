"""Вызовы штатного MCP Vanessa с сохранением точного ответа в проекте."""
from pathlib import Path
import json, sys, time, base64
import onec
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'1c/tmp/vgh-va';OUT.mkdir(parents=True,exist_ok=True)
tool=sys.argv[1];args={}
for i in range(2,len(sys.argv),2):
    key=sys.argv[i].lstrip('-');value=sys.argv[i+1]
    if value=='true':value=True
    elif value=='false':value=False
    elif key in ['lineNumber','limit','object_type','start_number','end_number']:value=int(value)
    args[key]=value
raw=onec.va_mcp_call(onec.va_mcp_url(),tool,args,timeout=300).decode('utf-8-sig')
path=OUT/(str(time.time_ns())+'-'+tool+'.json');path.write_text(raw,encoding='utf-8')
try:result=json.loads(next(x[6:] for x in raw.splitlines() if x.startswith('data: '))).get('result',{})
except (ValueError,StopIteration):print(raw[:18000]);sys.exit(1)
path.with_suffix('.txt').write_text('\n'.join(c.get('text','') for c in result.get('content',[]) if c.get('type')=='text'),encoding='utf-8')
for c in result.get('content',[]):
    if c.get('type')=='text':print(c.get('text','')[:24000])
    elif c.get('type')=='image':
        image=path.with_suffix('.png');image.write_bytes(base64.b64decode(c['data']));print('Изображение:',image)
print('Ответ MCP:',path)

