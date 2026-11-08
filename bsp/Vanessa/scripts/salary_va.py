"""Обмен с MCP проекта. Аргументы операций хранятся в JSON внутри проекта."""
import json
from pathlib import Path
import sys
import urllib.request
import onec

root=Path(__file__).resolve().parents[1]
out=root/'output/salary-audit-20261031';out.mkdir(parents=True,exist_ok=True)
tool=sys.argv[1]
args=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig')) if len(sys.argv)>2 else {}
url=onec.va_mcp_url()
if tool=='list':
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    def call(method,params,notification=False):
        payload={'jsonrpc':'2.0','method':method,'params':params}
        if not notification: payload['id']=1
        req=urllib.request.Request(url.geturl(),json.dumps(payload).encode(),headers)
        with urllib.request.urlopen(req,timeout=45) as res:
            session=res.headers.get('Mcp-Session-Id')
            if session: headers['Mcp-Session-Id']=session
            return res.read()
    call('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'salary-audit','version':'1'}})
    call('notifications/initialized',{},True)
    raw=call('tools/list',{})
else:
    raw=onec.va_mcp_call(url,tool,args,timeout=55)
text=raw.decode('utf-8-sig')
if not text.lstrip().startswith('{'):
    text='\n'.join(line[5:].strip() for line in text.splitlines() if line.startswith('data:'))
(out/('va-'+tool+'.json')).write_text(text,encoding='utf-8')
if tool=='list':
    data=json.loads(text)
    print('\n'.join(x['name'] for x in data.get('result',{}).get('tools',[])))
else:
    print(text[:12000])
