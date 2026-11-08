"""Прочитать опубликованные схемы MCP Vanessa."""
import json, urllib.request
from pathlib import Path
import onec
headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
def request(method, params, ident=1):
    body = {'jsonrpc':'2.0','method':method,'params':params}
    if ident:
        body['id'] = ident
    with urllib.request.urlopen(urllib.request.Request(onec.va_mcp_url().geturl(), json.dumps(body).encode(), headers), timeout=30) as response:
        if response.headers.get('Mcp-Session-Id'):
            headers['Mcp-Session-Id'] = response.headers['Mcp-Session-Id']
        raw = response.read().decode('utf-8-sig')
    if not raw:
        return {}
    return json.loads(raw if raw.lstrip().startswith('{') else next(line[6:] for line in raw.splitlines() if line.startswith('data: ')))
request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'sales-tools','version':'1'}})
request('notifications/initialized',{},None)
data = request('tools/list',{})
target = Path(__file__).resolve().parents[1]/'1c/tmp/sales-va-tools.json'
target.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
for tool in data.get('result',{}).get('tools',[]):
    if any(word in tool['name'] for word in ['scenario','test_client','feature','screenshot','keyboard']):
        print(tool['name'], json.dumps(tool.get('inputSchema',{}),ensure_ascii=False))

