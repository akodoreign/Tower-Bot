$log = 'C:\ProgramData\MySQL\MySQL Server 9.6\Data\DH0424-C8823422.err'
$out = 'C:\Users\akodoreign\Desktop\mysql_log.txt'
Get-Content $log -Tail 30 | Set-Content $out
