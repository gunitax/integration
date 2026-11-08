"""Диагностика Streamable HTTP: завершение по JSON-RPC ответу, а не по закрытию SSE."""
from pathlib import Path
import json,sys,urllib.request
import onec
ROOT=Path(__file__).resolve().parents[1]
headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
url=onec.va_mcp_url().geturl();seq=0
def call(method,params,notification=False):
 global seq
 payload={'jsonrpc':'2.0','method':method,'params':params};seq+=1
 if not notification:payload['id']=seq
 req=urllib.request.Request(url,json.dumps(payload).encode(),headers)
 with urllib.request.urlopen(req,timeout=45) as response:
  sid=response.headers.get('Mcp-Session-Id')
  if sid:headers['Mcp-Session-Id']=sid
  if response.status==202:return None
  if 'text/event-stream' not in response.headers.get('Content-Type',''):return json.loads(response.read())
  lines=[]
  while True:
   line=response.readline().decode('utf-8-sig').rstrip('\r\n')
   if line.startswith('data:'):lines.append(line[5:].lstrip())
   elif not line and lines:
    message=json.loads('\n'.join(lines));lines=[]
    print('SSE',method,'id=',message.get('id'),'keys=',','.join(message.keys()),flush=True)
    if str(message.get('id'))==str(payload.get('id')) and ('result' in message or 'error' in message):return message
   elif not line and response.isclosed():raise RuntimeError('SSE завершился без JSON-RPC ответа')
call('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'salary-incremental','version':'1'}})
call('notifications/initialized',{},True)
tool=sys.argv[1];arguments=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig')) if len(sys.argv)>2 else {}
result=call('tools/call',{'name':tool,'arguments':arguments})
(ROOT/'output/salary-audit-20261031'/('va-stream-'+tool+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False)[:3500])
