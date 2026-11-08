param([int]$Step = 0)

$exe  = 'C:\Program Files\1cv8\8.5.1.1529\bin\1cv8.exe'
$base = 'C:\Users\sax\Documents\InfoBase22'
$user = 'Администратор'
$ext  = 'КассовыеДокументы'
$src  = 'Q:\AIZCODE.V5\src\extensions\КассовыеДокументы'
$cfe  = 'C:\temp\kd_out\КассовыеДокументы.cfe'
$log  = 'C:\temp\kd_step.log'
if (Test-Path $log) { Remove-Item $log -Force }

$arg = @('DESIGNER', '/F', $base, '/N', $user)
switch ($Step) {
    1 { $arg += @('/CreateExtension', '-Extension', $ext) }
    2 { $arg += @('/LoadConfigFromFiles', $src, '-Extension', $ext) }
    3 { $arg += @('/UpdateDBCfg', '-Extension', $ext) }
    4 { $arg += @('/DumpCfg', 'C:\temp\kd_check.cf', '-Extension', $ext) }
    5 { $arg += @('/LoadCfg', $cfe, '-Extension', $ext) }
    default { Write-Output 'STEP?'; exit 2 }
}
$arg += @('/Out', $log)

$p = Start-Process -FilePath $exe -ArgumentList $arg -Wait -PassThru
Write-Output ("EXIT=" + $p.ExitCode)
if (Test-Path $log) { Get-Content $log -Encoding UTF8 }
else { Write-Output '(log missing)' }
