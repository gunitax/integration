import onec
cfg=onec.settings()
for name in ['client_mcp','VAExtension','ИнструментыVanessaСервер']:
    onec.run_ibcmd(cfg,['update','--name='+name,'--active=yes','--safe-mode=no','--unsafe-action-protection=no'])
print('Инструменты Vanessa включены')
